"""Tests for watch.py, using fixture data shaped like the Hetzner Cloud API spec."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest import mock

import watch

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


def stype(name, disk, locations, storage="local", arch="x86"):
    return {"name": name, "disk": disk, "storage_type": storage, "architecture": arch, "locations": locations}


def loc(name, available=True, deprecation=None):
    return {"id": 1, "name": name, "available": available, "recommended": False, "deprecation": deprecation}


CX23 = stype("cx23", 40, [loc("nbg1"), loc("fsn1")])
CX43_OUT = stype("cx43", 160, [loc("nbg1", available=False), loc("fsn1", available=True)])
CX43_IN = stype("cx43", 160, [loc("nbg1", available=True), loc("fsn1", available=True)])
SERVER = {"name": "secret-name", "location": {"name": "nbg1"}, "server_type": CX23}


class LocationStatusTest(unittest.TestCase):
    def test_states(self):
        self.assertEqual(watch.location_status(CX43_OUT, "nbg1", NOW), (False, "temporarily unavailable"))
        self.assertEqual(watch.location_status(CX43_OUT, "fsn1", NOW), (True, "available"))
        self.assertEqual(watch.location_status(CX43_OUT, "ash", NOW), (False, "not offered in this location"))

    def test_retired(self):
        retired = stype("cx22", 40, [loc("nbg1", deprecation={"announced": "2025-10-16T00:00:00Z",
                                                                "unavailable_after": "2026-01-01T00:00:00Z"})])
        self.assertEqual(watch.location_status(retired, "nbg1", NOW), (False, "retired in this location"))


class EvaluateTest(unittest.TestCase):
    def test_new_and_upgrade_unavailable_in_nbg1(self):
        results = watch.evaluate({"cx43": CX43_OUT}, ["nbg1"], SERVER, NOW)
        self.assertEqual([(r.purpose, r.available) for r in results], [("new", False), ("upgrade", False)])

    def test_upgrade_available(self):
        results = watch.evaluate({"cx43": CX43_IN}, ["nbg1"], SERVER, NOW)
        self.assertTrue(all(r.available for r in results))
        self.assertEqual(watch.summary_title(results), "CX43 available: nbg1 (new, upgrade)")

    def test_wildcard_locations(self):
        results = watch.evaluate({"cx43": CX43_OUT}, ["*"], None, NOW)
        self.assertEqual({r.location: r.available for r in results}, {"fsn1": True, "nbg1": False})

    def test_upgrade_blocked_by_storage_type(self):
        ceph = stype("cx43", 160, [loc("nbg1")], storage="network")
        results = watch.evaluate({"cx43": ceph}, [], SERVER, NOW)
        self.assertFalse(results[0].available)
        self.assertIn("storage type", results[0].reason)


class RunTest(unittest.TestCase):
    def test_missing_token_fails(self):
        self.assertEqual(watch.run({}), 1)

    def test_report_and_outputs_omit_server_name(self):
        def fake_find(settings, path, key, name):
            return CX43_IN if key == "server_types" else SERVER

        with mock.patch.object(watch, "find_one", side_effect=fake_find), \
                mock.patch("builtins.open", mock.mock_open()) as opened:
            code = watch.run({"HCLOUD_TOKEN": "t", "WATCH_SERVER_NAME": "secret-name",
                              "GITHUB_OUTPUT": "out.txt"}, NOW)
        self.assertEqual(code, 0)
        written = "".join(c.args[0] for c in opened().write.call_args_list)
        self.assertIn("available=true", written)
        self.assertNotIn("secret-name", written)


if __name__ == "__main__":
    unittest.main()
