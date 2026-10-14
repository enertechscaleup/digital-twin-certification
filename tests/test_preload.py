"""Background load and verification of the pinned runs at startup: it fills the cache, and a failure
is logged without ever stopping the app from starting or serving."""

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

import app.main as main
from tests.test_app import RUN, build_pack


class TestPreload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        build_pack(d)
        cfg = json.loads((d / "runs.json").read_text())
        cfg["runs"].append({"run": "missing-run", "title": "Not in the store", "core_ledger_head_hash": "0" * 64,
                            "project_id": "oil-gas-compressor-train"})
        (d / "runs.json").write_text(json.dumps(cfg))
        cls.env = mock.patch.dict(os.environ, {"EVIDENCE_SOURCE": "local", "EVIDENCE_DIR": str(d),
                                               "RUNS_CONFIG": str(d / "runs.json")})
        cls.env.start()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.tmp.cleanup()
        main._cache.clear()

    def setUp(self):
        main._cache.clear()

    def test_preload_verifies_what_it_can_and_logs_what_it_cannot(self):
        with self.assertLogs("twinevidence", "INFO") as logs:
            outcome = main.preload_pinned_runs()
        self.assertEqual(outcome[RUN], "ok")
        self.assertNotEqual(outcome["missing-run"], "ok")
        self.assertIn(RUN, main._cache)
        self.assertNotIn("missing-run", main._cache)
        self.assertTrue(any("preload: missing-run failed" in l for l in logs.output))
        self.assertTrue(any("of" in l and "runs ready" in l for l in logs.output))

    def test_startup_and_serving_never_wait_for_or_fail_on_preload(self):
        release, started = threading.Event(), threading.Event()

        def stuck_then_broken():
            started.set()
            release.wait(10)
            raise RuntimeError("bucket unreachable")

        with mock.patch.object(main, "store_from_env", side_effect=lambda: stuck_then_broken()), \
                self.assertLogs("twinevidence", "WARNING") as logs:
            with TestClient(main.app) as client:  # runs the startup hook
                self.assertTrue(started.wait(5))
                self.assertEqual(client.get("/health").status_code, 200)  # served while preload is stuck
                self.assertEqual(client.get("/api/projects").status_code, 200)
                release.set()
                preload = next(t for t in threading.enumerate() if t.name == "preload-evidence")
                preload.join(10)
                self.assertEqual(client.get("/health").status_code, 200)  # still serving after it failed
        self.assertTrue(any("RuntimeError: bucket unreachable" in l for l in logs.output))

    def test_preload_can_be_switched_off(self):
        with mock.patch.dict(os.environ, {"PRELOAD_EVIDENCE": "0"}), mock.patch.object(main, "preload_pinned_runs") as p:
            with TestClient(main.app) as client:
                client.get("/health")
        p.assert_not_called()


if __name__ == "__main__":
    unittest.main()
