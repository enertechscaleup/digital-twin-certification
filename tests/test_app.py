"""Tests for the dashboard backend, against an evidence pack built from scratch."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main
from app.evidence import load_runs_config, write_manifest
from engine.registry import load_registry
from engine.run import run_assurance, write_jsonl
from explain import supplementary
from explain.gemini import generate_artifacts
from telemetry.faults import Scenario
from tests.test_explain import FakeGemini
from vendor.advise import recommend
from vendor.recalibrate import owner_for_platform

ROOT = Path(__file__).resolve().parent.parent
RUN = "assurance-demo_full_cycle-seed42"


def build_pack(directory: Path) -> str:
    s = Scenario.from_dict(json.loads((ROOT / "scenarios" / "demo_full_cycle.json").read_text()))
    r = run_assurance(s, seed=42, start_time=datetime(2026, 10, 1, tzinfo=timezone.utc),
                      ledger_path=directory / f"{RUN}.ledger.jsonl", recalibrator=owner_for_platform,
                      advisor=recommend)
    write_jsonl(r.readings, directory / f"{RUN}.readings.jsonl")
    write_jsonl(r.timeline, directory / f"{RUN}.timeline.jsonl")
    sup = supplementary.start(directory / f"{RUN}.supplementary.jsonl", r.ledger.entries)
    generate_artifacts(r.ledger.entries, r.readings, r.timeline, load_registry(), FakeGemini(),
                       on_artifact=lambda a: supplementary.record(sup, a))
    sup.close()
    return write_manifest(directory, RUN, "demo_full_cycle")["core_ledger_head_hash"]


class TestDashboardApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.head = build_pack(cls.dir)
        os.environ["EVIDENCE_SOURCE"], os.environ["EVIDENCE_DIR"] = "local", str(cls.dir)
        main._cache.clear()
        main._verify_calls.clear()
        cls.client = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        main._cache.clear()

    def test_regenerated_run_matches_the_pinned_fingerprint(self):
        pin = next(r for r in load_runs_config()["runs"] if r["run"] == RUN)
        self.assertEqual(self.head, pin["core_ledger_head_hash"], "app/config/runs.json pins are out of date")

    def test_meta_reports_verified_evidence(self):
        m = self.client.get(f"/api/runs/{RUN}/meta").json()
        self.assertTrue(m["verification"]["valid"])
        self.assertEqual(len(m["verification"]["checks"]), 9)
        self.assertEqual(m["ticks"], 80)
        self.assertIn("motor-op-001", m["twins"])

    def test_state_is_cut_off_at_the_tick_on_screen(self):
        s30 = self.client.get(f"/api/runs/{RUN}/state", params={"tick": 30}).json()
        motor = s30["twins"]["motor-op-001"]
        self.assertEqual((motor["status"], motor["assurance_id"]), ("flagged", "asr-motor-op-001-v1"))
        self.assertEqual(s30["recalibration"], [])
        s70 = self.client.get(f"/api/runs/{RUN}/state", params={"tick": 70}).json()
        motor = s70["twins"]["motor-op-001"]
        self.assertEqual((motor["status"], motor["assurance_id"]), ("assured", "asr-motor-op-001-v2"))
        self.assertEqual(s70["twins"]["compressor-system-op-001"]["status"], "flagged")
        self.assertIn("composition_reassessment", [e["entry_type"] for e in s70["recalibration"]])

    def test_no_future_evidence_leaks(self):
        ledger = self.client.get(f"/api/runs/{RUN}/ledger", params={"upto": 30}).json()
        self.assertTrue(ledger and all(e["tick"] <= 30 for e in ledger))
        self.assertNotIn("assurance_status_changed",
                         [e["entry_type"] for e in ledger if e["payload"].get("to") == "nullified"])
        expl = self.client.get(f"/api/runs/{RUN}/explanations", params={"upto": 30}).json()
        self.assertTrue(expl and all(e["explains_tick"] <= 30 for e in expl))
        reads = self.client.get(f"/api/runs/{RUN}/readings", params={"upto": 5, "twin_id": "motor-op-001"}).json()
        self.assertEqual(len(reads), 6 * 4)

    def test_view_is_cut_off_and_labels_resolved_cascade(self):
        v = self.client.get(f"/api/runs/{RUN}/view", params={"tick": 65}).json()
        self.assertEqual(max(r["tick"] for r in v["readings"]), 65)
        self.assertEqual(len(v["timeline"]), 66)
        self.assertTrue(all(e["tick"] <= 65 for e in v["ledger"]))
        reasons = {r["cause"]: r for r in v["state"]["twins"]["compressor-system-op-001"]["reasons"]}
        self.assertEqual(reasons["cascade"]["resolved"]["at_tick"], 60)
        self.assertNotIn("resolved", reasons["own_output"])
        v30 = self.client.get(f"/api/runs/{RUN}/view", params={"tick": 30}).json()
        self.assertNotIn("cascade", [r["cause"] for r in v30["state"]["twins"].get("compressor-system-op-001", {}).get("reasons", [])])

    def test_verify_endpoint_and_rate_limit(self):
        main._verify_calls.clear()
        for _ in range(main.VERIFY_LIMIT_PER_MINUTE):
            self.assertTrue(self.client.post(f"/api/runs/{RUN}/verify").json()["valid"])
        self.assertEqual(self.client.post(f"/api/runs/{RUN}/verify").status_code, 429)
        main._verify_calls.clear()

    def test_tampered_evidence_is_refused(self):
        path = self.dir / f"{RUN}.readings.jsonl"
        original = path.read_bytes()
        try:
            path.write_bytes(original.replace(b'"tick": 5,', b'"tick": 5, ', 1))  # one extra space
            main._verify_calls.clear()
            result = self.client.post(f"/api/runs/{RUN}/verify").json()
            self.assertFalse(result["valid"])
            self.assertIn("readings file matches its manifest fingerprint", result["error"])
            main._cache.clear()
            self.assertEqual(self.client.get(f"/api/runs/{RUN}/meta").status_code, 503)
        finally:
            path.write_bytes(original)
            main._cache.clear()

    def test_unknown_run(self):
        self.assertEqual(self.client.get("/api/runs/nope/meta").status_code, 404)


if __name__ == "__main__":
    unittest.main()
