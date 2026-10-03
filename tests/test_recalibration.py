"""Tests for the recalibration cycle (Real2Sim)."""

import ast
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from engine.boundary import BoundaryError
from engine.ledger import verify_chain
from engine.run import run_assurance
from telemetry.faults import RecalibrationRequest, Scenario, WearDrift
from vendor.advise import recommend
from vendor.recalibrate import owner_for_platform, recalibrate
from vendor.endpoint import simulated_vendors

ROOT = Path(__file__).resolve().parent.parent
START = datetime(2026, 10, 1, tzinfo=timezone.utc)
MOTOR, COMP, SYSTEM = "motor-op-001", "compressor-op-001", "compressor-system-op-001"


def full_cycle(**overrides):
    d = json.loads((ROOT / "scenarios" / "demo_full_cycle.json").read_text())
    d.update(overrides)
    return Scenario.from_dict(d)


def run(s, recalibrator=owner_for_platform):
    return run_assurance(s, simulated_vendors(recalibrator=recalibrator), seed=42, start_time=START)


def first(result, entry_type):
    return next(e for e in result.ledger.entries if e["entry_type"] == entry_type)


class SpyOwner:
    def __init__(self, inner=owner_for_platform):
        self.inner, self.released = inner, None

    def __call__(self, twin_type, current, released, envelopes):
        self.released = released
        return self.inner(twin_type, current, released, envelopes)


def stale_owner(twin_type, current, released, envelopes):
    """An owner that fits on the EARLIEST released data, while wear was still growing."""
    early = sorted({r["tick"] for r in released})[:5]
    subset = [r for r in released if r["tick"] in early]
    return recalibrate(twin_type, current, subset, envelopes, "1.1.0-stale").to_dict()


class TestWearCap(unittest.TestCase):
    def test_wear_levels_off(self):
        w = WearDrift("motor", 0, {"speed": -20}, max_abs_pct=15)
        self.assertAlmostEqual(w.wear_pct(10, 240, 24)["speed"], -4.8)
        self.assertEqual(w.wear_pct(100, 2400, 24)["speed"], -15)


class TestFullCycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spy = SpyOwner()
        cls.result = run(full_cycle(), cls.spy)

    def test_split_is_temporal_from_first_flag(self):
        split = first(self.result, "recalibration_requested")["payload"]["split"]
        self.assertEqual(split["released_to_owner"], [19, 47])
        self.assertEqual(split["held_out"], [48, 59])

    def test_both_parts_sealed_before_release_and_held_out_never_released(self):
        seqs = [first(self.result, t)["seq"] for t in
                ("recalibration_data_sealed", "recalibration_data_released", "recalibration_submitted")]
        self.assertEqual(seqs, sorted(seqs))
        sealed = first(self.result, "recalibration_data_sealed")["payload"]
        validation = first(self.result, "held_out_validation")["payload"]
        self.assertEqual(sealed["held_out_part"]["readings_sha256"], validation["held_out_readings_sha256"])
        released_ticks = {r["tick"] for r in self.spy.released}
        self.assertEqual((min(released_ticks), max(released_ticks)), (19, 47))
        self.assertEqual({r["twin_id"] for r in self.spy.released}, {MOTOR})

    def test_new_version_issued_and_supersedes(self):
        issued = [e["payload"] for e in self.result.ledger.of_type("assurance_issued")
                  if e["payload"]["twin_id"] == MOTOR]
        self.assertEqual([i["assurance_id"] for i in issued], ["asr-motor-op-001-v1", "asr-motor-op-001-v2"])
        self.assertEqual(issued[1]["supersedes"], "asr-motor-op-001-v1")
        self.assertEqual(issued[1]["effective_from_tick"], 60)
        # v2 restated its output ranges; the re-verification records the old envelope beside them.
        rever = [e["payload"] for e in self.result.ledger.of_type("verification") if e["payload"].get("stage")]
        self.assertLess(rever[0]["envelope"]["speed"]["min"], rever[0]["previous_envelope"]["speed"]["min"])

    def test_operator_runs_v2_from_tick_60_and_motor_stays_assured(self):
        versions = {r["tick"]: r["twin_version"] for r in self.result.readings
                    if r["twin_id"] == MOTOR and r["channel_id"] == "speed"}
        self.assertEqual((versions[59], versions[60]), ("1.0.0", "1.1.0"))
        self.assertTrue(all(t["status"][MOTOR] == "assured" for t in self.result.timeline[60:]))
        self.assertEqual(self.result.monitor.status[MOTOR].assurance_id, "asr-motor-op-001-v2")

    def test_system_stays_flagged_blocked_by_compressor(self):
        reassess = first(self.result, "composition_reassessment")["payload"]
        self.assertEqual(reassess["result"], "not_reassured")
        self.assertEqual([b["constituent"] for b in reassess["blocked_by"]], [COMP])
        self.assertEqual(reassess["blocked_by"][0]["reasons"][0]["cause"], "envelope_violation")
        self.assertTrue(all(t["status"][SYSTEM] == "flagged" for t in self.result.timeline[60:]))

    def test_history_before_recalibration_is_untouched(self):
        without = run(full_cycle(recalibration=None), None)
        cut = first(self.result, "recalibration_requested")["seq"]
        self.assertEqual(self.result.ledger.entries[:cut], without.ledger.entries[:cut])
        self.assertTrue(verify_chain(self.result.ledger.entries).valid)

    def test_reproducible(self):
        self.assertEqual(run(full_cycle()).ledger.head_hash, self.result.ledger.head_hash)


class TestRecalibrationGuards(unittest.TestCase):
    def test_stale_recalibration_is_caught_by_held_out(self):
        result = run(full_cycle(), stale_owner)
        self.assertFalse(first(result, "held_out_validation")["payload"]["passed"])
        rejected = first(result, "recalibration_rejected")["payload"]
        self.assertEqual(rejected["status_unchanged"], "nullified")
        self.assertEqual(result.monitor.status[MOTOR].assurance_id, "asr-motor-op-001-v1")
        self.assertEqual({r["twin_version"] for r in result.readings if r["twin_id"] == MOTOR}, {"1.0.0"})

    def test_assured_twin_cannot_be_recalibrated(self):
        s = Scenario(name="t", ticks=30, recalibration=RecalibrationRequest("motor", 20))
        result = run(s)
        self.assertEqual(first(result, "recalibration_refused")["payload"]["reason"],
                         "twin is assured; nothing to recalibrate")

    def test_owner_without_recalibration_is_an_error(self):
        with self.assertRaises(BoundaryError):
            run(full_cycle(), None)

    def test_engine_never_imports_the_owner(self):
        for path in (ROOT / "engine").glob("*.py"):
            if path.name == "__main__.py":
                continue  # the command-line wiring hands the owner in; the engine itself never imports it
            tree = ast.parse(path.read_text())
            names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
            names += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
            self.assertFalse(any(n.startswith("vendor") for n in names), path.name)


if __name__ == "__main__":
    unittest.main()
