"""Check Hetzner Cloud server type availability per location.

Reads its settings from environment variables (see README), queries the
Hetzner Cloud API and writes a Markdown report. When run inside GitHub
Actions it also sets the step outputs ``available`` and ``title``.

Exit codes: 0 = check ran (available or not), 1 = configuration or API error.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

log = logging.getLogger("watch")

DEFAULT_API_URL = "https://api.hetzner.cloud/v1"


class WatchError(Exception):
    """Raised for configuration or API problems the run cannot recover from."""


@dataclass(frozen=True)
class Result:
    """Availability of one server type in one location."""

    server_type: str
    location: str
    purpose: str  # "new" or "upgrade"
    available: bool
    reason: str


@dataclass(frozen=True)
class Settings:
    """Run settings, read from the environment."""

    token: str
    server_types: list[str]
    locations: list[str]  # ["*"] means every location the type is offered in
    server_name: str | None
    api_url: str
    report_path: str


def _split(value: str) -> list[str]:
    return [part.strip().lower() for part in value.split(",") if part.strip()]


def load_settings(env: dict[str, str]) -> Settings:
    """Build Settings from an environment mapping; raises WatchError on bad config."""
    token = env.get("HCLOUD_TOKEN", "").strip()
    if not token:
        raise WatchError("HCLOUD_TOKEN is not set")
    server_types = _split(env.get("WATCH_SERVER_TYPES", "") or "cx43")
    locations = _split(env.get("WATCH_LOCATIONS", "") or "nbg1")
    server_name = env.get("WATCH_SERVER_NAME", "").strip() or None
    return Settings(
        token=token,
        server_types=server_types,
        locations=locations,
        server_name=server_name,
        api_url=env.get("HCLOUD_API_URL", "").strip() or DEFAULT_API_URL,
        report_path=env.get("WATCH_REPORT_PATH", "").strip() or "report.md",
    )


def api_get(settings: Settings, path: str, params: dict[str, str] | None = None) -> dict:
    """GET a Hetzner Cloud API path and return the decoded JSON body."""
    url = f"{settings.api_url}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {settings.token}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise WatchError(f"GET {path} failed: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise WatchError(f"GET {path} failed: {exc.reason}") from exc


def find_one(settings: Settings, path: str, key: str, name: str) -> dict | None:
    """Return the single resource with this name from a list endpoint, or None."""
    items = api_get(settings, path, {"name": name}).get(key, [])
    return items[0] if items else None


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def location_status(server_type: dict, location: str, now: datetime) -> tuple[bool, str]:
    """Return (available, reason) for a server type in one location."""
    entry = next((loc for loc in server_type.get("locations", []) if loc.get("name") == location), None)
    if entry is None:
        return False, "not offered in this location"
    deprecation = entry.get("deprecation")
    if deprecation and _parse_time(deprecation["unavailable_after"]) <= now:
        return False, "retired in this location"
    if not entry.get("available", False):
        return False, "temporarily unavailable"
    return True, "available"


def upgrade_blocker(current: dict, target: dict) -> str | None:
    """Return why `current` cannot be rescaled to `target`, or None if it can."""
    if current.get("storage_type") != target.get("storage_type"):
        return f"different storage type ({current.get('storage_type')} -> {target.get('storage_type')})"
    if current.get("architecture") != target.get("architecture"):
        return f"different architecture ({current.get('architecture')} -> {target.get('architecture')})"
    if target.get("disk", 0) < current.get("disk", 0):
        return "target disk is smaller than the current disk"
    return None


def evaluate(
    types: dict[str, dict],
    locations: list[str],
    server: dict | None,
    now: datetime,
) -> list[Result]:
    """Check every watched type against the watched locations and the server's location."""
    results: list[Result] = []
    for name, server_type in types.items():
        targets = locations
        if targets == ["*"]:
            targets = sorted(loc["name"] for loc in server_type.get("locations", []))
        for location in targets:
            available, reason = location_status(server_type, location, now)
            results.append(Result(name, location, "new", available, reason))

        if server is None:
            continue
        location = server["location"]["name"]
        current = server["server_type"]
        if current.get("name") == name:
            results.append(Result(name, location, "upgrade", False, "server already has this type"))
            continue
        blocker = upgrade_blocker(current, server_type)
        if blocker:
            results.append(Result(name, location, "upgrade", False, blocker))
            continue
        available, reason = location_status(server_type, location, now)
        results.append(Result(name, location, "upgrade", available, reason))
    return results


SERVER_LABEL = "your server"


def _where(result: Result) -> str:
    """Location shown publicly; upgrade rows hide the server's location."""
    return SERVER_LABEL if result.purpose == "upgrade" else result.location


def _public_reason(reason: str) -> str:
    """Upgrade blockers can reveal the server's current type, so generalise them."""
    return reason if reason == "temporarily unavailable" else "not possible for your server"


def render_report(results: list[Result], now: datetime) -> str:
    """Render the results as a Markdown report (safe to post publicly).

    Upgrade rows never name the watched server's type or location.
    """
    lines = [f"Checked at {now.strftime('%Y-%m-%d %H:%M UTC')}.", ""]
    lines += ["| Server type | Location | Purpose | Status |", "|---|---|---|---|"]
    for r in results:
        mark = "✅" if r.available else "❌"
        reason = r.reason if r.purpose == "new" or r.available else _public_reason(r.reason)
        lines.append(f"| `{r.server_type}` | {_where(r)} | {r.purpose} | {mark} {reason} |")
    if any(r.available and r.purpose == "upgrade" for r in results):
        lines += [
            "",
            "Upgrading: power the server off, then rescale it in the Cloud Console. "
            "Choose **CPU and RAM only** to keep the option of downgrading later.",
        ]
    return "\n".join(lines) + "\n"


def summary_title(results: list[Result]) -> str:
    """One-line title naming what is available, e.g. 'CX43 available: nbg1 (new), your server (upgrade)'."""
    hits: dict[str, dict[str, list[str]]] = {}
    for r in results:
        if r.available:
            hits.setdefault(r.server_type, {}).setdefault(_where(r), []).append(r.purpose)
    parts = []
    for server_type, locs in hits.items():
        where = ", ".join(f"{loc} ({', '.join(p)})" for loc, p in locs.items())
        parts.append(f"{server_type.upper()} available: {where}")
    return "; ".join(parts) or "Nothing available"


def write_outputs(path: str | None, values: dict[str, str]) -> None:
    """Append key=value pairs to the GitHub Actions output file, if there is one."""
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def run(env: dict[str, str], now: datetime | None = None) -> int:
    """Run one check; returns the process exit code."""
    now = now or datetime.now(timezone.utc)
    try:
        settings = load_settings(env)
        types: dict[str, dict] = {}
        for name in settings.server_types:
            server_type = find_one(settings, "/server_types", "server_types", name)
            if server_type is None:
                raise WatchError(f"unknown server type: {name}")
            types[name] = server_type
        server = None
        if settings.server_name:
            server = find_one(settings, "/servers", "servers", settings.server_name)
            if server is None:
                raise WatchError("WATCH_SERVER_NAME does not match a server in this project")
    except WatchError as exc:
        log.error("%s", exc)
        return 1

    results = evaluate(types, settings.locations, server, now)
    report = render_report(results, now)
    with open(settings.report_path, "w", encoding="utf-8") as handle:
        handle.write(report)
    summary_path = env.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(report)
    log.info("report written to %s", settings.report_path)

    available = any(r.available for r in results)
    write_outputs(
        env.get("GITHUB_OUTPUT"),
        {"available": str(available).lower(), "title": summary_title(results)},
    )
    log.info("available=%s", available)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(run(dict(os.environ)))
