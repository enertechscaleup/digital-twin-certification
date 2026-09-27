"""Tests for the semi-autonomous adjustment episode."""

import ast
import json
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from engine.ledger import verify_chain
from engine.run import run_assurance
from telemetry.faults import Scenario
from telemetry.generator import TelemetryGenerator
from vendor.advise import recommend
from vendor.recalibrate import owner_for_platform

ROOT = Path(__file__).resolve().parent.parent
START = datetime(2026, 10, 1, tzinfo=timezone.utc)
MOTOR, COMP, SYSTEM = "motor-op-001", "compressor-op-001", "compressor-system-op-001"


def scenario(**adjust):
    d = json.loads((ROOT / "scenarios" / "demo_full_cycle.json").read_text())
    d["adjustment"].update(adjust)
    return Scenario.from_dict(d)


def run(s, advisor=recommend):
    return run_assurance(s, seed=42, start_time=START, recalibrator=owner_for_platform, advisor=advisor)


def entries(result, prefix="adjustment_"):
    return [e for e in result.ledger.entries if e["entry_type"].startswith(prefix)]


class TestSetpoints(unittest.TestCase):
    def test_setpoint_holds_input_without_shifting_other_channels(self):
        s = Scenario(name="t", ticks=20)
        plain = TelemetryGenerator(seed=1, start_time=START)
        held = TelemetryGenerator(seed=1, start_time=START)
        held.setpoints[("motor", "volt")] = 410.0
        a = [r for b in plain.field_run(s) for r in b]
        b = [r for b in held.field_run(s) for r in b]
        volts = [r.physical_value for r in b if r.channel_id == "volt"]
        self.assertTrue(all(404 < v < 416 for v in volts))
        flow = lambda rows: [r.physical_value for r in rows if r.channel_id == "flow"]
        self.assertEqual(flow(a), flow(b))


class TestEpisode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run(scenario())

    def test_steps_in_order_with_named_approval(self):
        types = [e["entry_type"] for e in entries(self.result)]
        self.assertEqual(types, ["adjustment_recommended", "adjustment_approval", "adjustment_executed",
                                 "adjustment_post_state_check"])
        rec, appr = entries(self.result)[0], entries(self.result)[1]
        self.assertEqual(appr["payload"]["approver"], "Operator (demo)")
        self.assertEqual(appr["payload"]["approval_type"], "human")
        self.assertEqual(appr["payload"]["recommendation_entry_hash"], rec["entry_hash"])
        self.assertTrue(verify_chain(self.result.ledger.entries).valid)

    def test_recommendation_is_checked_and_predicts_an_honest_margin(self):
        p = entries(self.result)[0]["payload"]
        self.assertEqual(p["twin_mode"], "semi_autonomous")
        self.assertEqual(p["assurance_id"], "asr-motor-op-001-v2")
        self.assertTrue(p["pre_state_input_range_check"]["passed"])
        self.assertTrue(p["setpoint_within_assured_range"]["passed"])
        self.assertLessEqual(p["recommendation"]["to"], 417)  # kept inside the assured maximum
        self.assertTrue(p["recommendation"]["predicted_to_meet_objective"])
        self.assertGreater(p["predicted_margin_above_objective"], 0)

    def test_operator_setpoint_applied_from_execution_tick(self):
        volts = {r["tick"]: r["physical_value"] for r in self.result.readings
                 if r["twin_id"] == MOTOR and r["channel_id"] == "volt"}
        self.assertLess(volts[65], 405)
        self.assertTrue(all(410 < volts[t] < 420 for t in range(66, 80)))

    def test_post_state_reports_sim2real_and_objective_separately(self):
        p = entries(self.result)[-1]["payload"]
        self.assertEqual(p["check_ticks"], [67, 71])
        self.assertTrue(p["sim2real_passed"])
        self.assertTrue(p["objective"]["met"])
        self.assertEqual(p["objective"]["ticks_in_range"], 5)

    def test_status_stays_sticky(self):
        final = self.result.timeline[-1]["status"]
        self.assertEqual((final[MOTOR], final[COMP], final[SYSTEM]), ("assured", "flagged", "flagged"))

    def test_reproducible(self):
        self.assertEqual(run(scenario()).ledger.head_hash, self.result.ledger.head_hash)


class TestEpisodeGuards(unittest.TestCase):
    def test_refused_while_twin_not_assured(self):
        result = run(scenario(recommend_at_tick=40, approve_at_tick=41, execute_at_tick=42))
        types = [e["entry_type"] for e in entries(result)]
        self.assertEqual(types, ["adjustment_refused"])
        self.assertIn("nullified", entries(result)[0]["payload"]["reason"])
        self.assertEqual(result.timeline[-1]["status"][MOTOR], "assured")  # recalibration still happens later

    def test_setpoint_outside_assured_range_refused_and_never_executed(self):
        def reckless(*args, **kw):
            advice = recommend(*args, **kw)
            return {**advice, "to": 440.0}
        result = run(scenario(), advisor=reckless)
        self.assertEqual([e["entry_type"] for e in entries(result)], ["adjustment_recommended", "adjustment_refused"])
        self.assertFalse(entries(result)[0]["payload"]["setpoint_within_assured_range"]["passed"])
        volts = [r["physical_value"] for r in result.readings if r["twin_id"] == MOTOR and r["channel_id"] == "volt"]
        self.assertLess(max(volts), 420)

    def test_declined_approval_is_never_executed(self):
        result = run(scenario(approval={"approver": "Operator (demo)", "decision": "decline"}))
        self.assertEqual([e["entry_type"] for e in entries(result)], ["adjustment_recommended", "adjustment_approval"])

    def test_engine_never_imports_the_advisor(self):
        for path in (ROOT / "engine").glob("*.py"):
            if path.name == "__main__.py":
                continue
            tree = ast.parse(path.read_text())
            names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
            self.assertFalse(any(n.startswith("vendor") for n in names), path.name)


if __name__ == "__main__":
    unittest.main()
