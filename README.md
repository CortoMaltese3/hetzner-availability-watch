# hetzner-availability-watch

Polls the Hetzner Cloud API every 5 minutes and opens a GitHub issue when a watched
server type becomes available, either for a new server or as an upgrade of an existing
one. The issue closes itself when the type sells out again. It runs on GitHub Actions in
this public repo, so it uses no paid Actions minutes.

## How it decides

- `GET /v1/server_types?name=<type>` lists each location the type is offered in, with an
  `available` flag (Hetzner calls it an indicator, not a guarantee) and any `deprecation`.
- If `WATCH_SERVER_NAME` is set, `GET /v1/servers?name=…` finds that server's location and
  current type. The upgrade counts as possible when the target is available there and has
  the same storage type and architecture and a disk at least as big.

It only reads. It never creates or rescales anything.

## Settings

| Name | Kind | Default | Meaning |
|---|---|---|---|
| `HCLOUD_TOKEN` | secret | — | Hetzner Cloud API token, **Read** permission is enough |
| `WATCH_SERVER_NAME` | secret | — | optional: server to check for an upgrade (a secret so it stays out of public logs) |
| `WATCH_SERVER_TYPES` | variable | `cx43` | comma-separated, e.g. `cx43,cx53` |
| `WATCH_LOCATIONS` | variable | `nbg1` | comma-separated, e.g. `nbg1,fsn1`, or `*` for every location |
| `WATCH_NOTIFY_USER` | variable | repo owner | GitHub login mentioned in the issue |

Set them under **Settings → Secrets and variables → Actions**, or:

```sh
gh secret set HCLOUD_TOKEN -R CortoMaltese3/hetzner-availability-watch
gh secret set WATCH_SERVER_NAME -R CortoMaltese3/hetzner-availability-watch
gh variable set WATCH_LOCATIONS -b "nbg1,fsn1" -R CortoMaltese3/hetzner-availability-watch
```

A one-off check with other values: **Actions → watch → Run workflow**, or
`gh workflow run watch -f server_types=cx53 -f locations='*'`.

## Notes

- Workflow logs in a public repo are public. The report shows types and locations,
  never the server name or token.
- GitHub turns off scheduled workflows in public repos after 60 days without a commit. The
  workflow pushes an empty `chore: keepalive` commit after 50 quiet days to prevent that.
- Rescaling needs the server powered off. Choose "CPU and RAM only" (`upgrade_disk: false`)
  to keep the option of downgrading later.

## Local run

```sh
HCLOUD_TOKEN=… WATCH_LOCATIONS='*' python3 watch.py
python3 -m unittest -v
```
