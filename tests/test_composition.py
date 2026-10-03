"""Tests for the joint composition test (engine/composition.py) and the vendor boundary."""

import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from engine.boundary import HttpConnection, RemoteTwin
from engine.composition import external_inputs, test_points
from engine.lineage import verify_lineage
from engine.registry import load_registry
from engine.run import run_assurance
from projects import load_project
from telemetry.faults import Scenario
from telemetry.generator import TelemetryGenerator
from vendor.endpoint import simulated_endpoints, simulated_vendors

ROOT = Path(__file__).resolve().parent.parent
START = datetime(2026, 10, 1, tzinfo=timezone.utc)
SYSTEM = "compressor-system-op-001"


def scenario(name: str) -> Scenario:
    return Scenario.from_dict(json.loads((ROOT / "scenarios" / f"{name}.json").read_text()))


def tests_of(result) -> list[dict]:
    return [e["payload"] for e in result.ledger.of_type("composition_test")]


class TestJointRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = run_assurance(scenario("demo_full_cycle"), simulated_vendors(), seed=42, start_time=START)
        cls.build, cls.after = tests_of(cls.r)

    def test_points_cover_only_the_systems_external_inputs(self):
        reg = load_registry()
        self.assertEqual(external_inputs(reg), [("motor", "volt"), ("motor", "current"), ("compressor", "flow")])
        self.assertEqual(len(test_points(reg)), 125)

    def test_downstream_twins_are_fed_upstream_predictions_not_measurements(self):
        joint = [x for x in self.r.exchange if x["batch"] == self.build["exchange"]["batch"]]
        motor, comp = joint[0::2], joint[1::2]
        self.assertTrue(all(c["inputs"]["speed"] == m["outputs"]["speed"] for m, c in zip(motor, comp)))

    def test_initial_build_passes_and_gates_the_composition(self):
        self.assertEqual((self.build["trigger"], self.build["passed"]), ("initial build", True))
        assured = self.r.ledger.of_type("composition_assured")
        self.assertTrue(all(e["payload"]["composition_test"] == self.build["test_id"] for e in assured))
        self.assertLess(self.r.ledger.of_type("composition_test")[0]["seq"], assured[0]["seq"])

    def test_after_recalibration_the_interface_fails_and_interaction_is_checked_where_it_holds(self):
        a = self.after
        self.assertEqual(a["trigger"], "after recalibration of motor-op-001 to 1.1.0")
        self.assertEqual({c["twin_type"]: c["version"] for c in a["constituent_refs"]}, {"motor": "1.1.0", "compressor": "1.0.0"})
        conn = a["interface"]["connections"][0]
        self.assertFalse(a["interface"]["passed"])
        self.assertEqual(conn["to"], "compressor/speed")
        self.assertLess(conn["predicted_range"][0], conn["assured_range"][0])
        self.assertEqual(a["interaction"]["evaluated_points"] + a["interaction"]["not_evaluated_points"], 125)
        self.assertEqual(a["interaction"]["not_evaluated_points"], conn["points_outside"])
        self.assertTrue(a["interaction"]["passed"])

    def test_an_interface_failure_is_its_own_reason_and_blocks_reassurance(self):
        reasons = [r for e in self.r.ledger.of_type("assurance_reason_added") + self.r.ledger.of_type("assurance_status_changed")
                   if e["payload"]["twin_id"] == SYSTEM for r in e["payload"]["new_reasons"] if "composition_test" in r]
        self.assertEqual([r["cause"] for r in reasons], ["interface_invalid"])
        self.assertEqual(reasons[0]["constituent_ref"]["version"], "1.0.0")
        self.assertIn("leave compressor/speed's assured range", reasons[0]["detail"])
        re = self.r.ledger.of_type("composition_reassessment")[0]["payload"]
        self.assertEqual(re["result"], "not_reassured")
        self.assertEqual((re["composition_test"]["interface_passed"], re["composition_test"]["interaction_passed"]), (False, True))

    def test_the_test_fingerprint_covers_what_was_tested(self):
        self.assertNotEqual(self.build["test_fingerprint"], self.after["test_fingerprint"])
        self.assertEqual(len(self.build["test_fingerprint"]), 64)


class TestInteractionFailure(unittest.TestCase):
    def test_a_joint_prediction_off_the_combined_bench_is_an_interaction_failure_and_refuses_composition(self):
        real = TelemetryGenerator.system_bench

        def biased(self, points, scenario=None, tick=None, repeats=3):  # the physical system runs 8% hotter
            return [{**s, "outputs": {**s["outputs"], "compressor": {**s["outputs"]["compressor"],
                                                                      "temperature": s["outputs"]["compressor"]["temperature"] * 1.08}}}
                    for s in real(self, points, scenario, tick, repeats)]

        with mock.patch.object(TelemetryGenerator, "system_bench", biased):
            r = run_assurance(scenario("faults_showcase"), simulated_vendors(), seed=42, start_time=START)
        test = tests_of(r)[0]
        self.assertEqual((test["interface"]["passed"], test["interaction"]["passed"]), (True, False))
        refused = r.ledger.of_type("composition_refused")[0]["payload"]
        self.assertEqual([x["cause"] for x in refused["reasons"]], ["interaction_invalid"])
        self.assertEqual(refused["reasons"][0]["channel_id"], "temperature")
        self.assertNotIn("composition_assured", [e["entry_type"] for e in r.ledger.entries])
        self.assertEqual(r.timeline, [])
        self.assertTrue(verify_lineage(r.ledger.entries, r.readings, r.exchange).valid)


class TestInterfaceFailureAtBuild(unittest.TestCase):
    def test_twins_valid_alone_but_not_together_are_refused_composition(self):
        """The motor's predictions are inside its own assured range, but the compressor
        is assured only from 1300 rpm: each twin passes alone, the composition does not."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            comp = json.loads((ROOT / "telemetry" / "config" / "compressor.json").read_text())
            for c in comp["channels"]:
                if c["channel_id"] == "speed":
                    c["envelope"]["min"] = 1300
            (d / "compressor.json").write_text(json.dumps(comp))
            proj = json.loads((ROOT / "projects" / "compressor_train.json").read_text())
            proj["twins"][0]["config"] = str(ROOT / "telemetry" / "config" / "motor.json")
            proj["twins"][1]["config"] = "compressor.json"
            (d / "project.json").write_text(json.dumps(proj))
            project = load_project(d / "project.json")
            r = run_assurance(scenario("faults_showcase"), simulated_vendors(project), seed=42, start_time=START,
                              project=project)
        self.assertEqual(len(r.ledger.of_type("assurance_issued")), 4)
        refused = r.ledger.of_type("composition_refused")[0]["payload"]
        self.assertEqual([x["cause"] for x in refused["reasons"]], ["interface_invalid"])
        self.assertFalse(r.assured)


class TestVendorBoundary(unittest.TestCase):
    def test_only_json_crosses_and_parameters_never_do(self):
        e = simulated_endpoints()["motor"]
        reply = json.loads(e.handle(json.dumps({"op": "describe"})))
        self.assertEqual(set(reply), {"twin_type", "version", "current_version", "declared_fingerprint", "declared_method"})
        self.assertIn("error", json.loads(e.handle(json.dumps({"op": "params"}))))

    def test_a_run_over_http_matches_a_run_in_process(self):
        from http.server import ThreadingHTTPServer
        from vendor.serve import handler_for

        endpoints = simulated_endpoints()
        servers = {t: ThreadingHTTPServer(("127.0.0.1", 0), handler_for(e)) for t, e in endpoints.items()}
        for s in servers.values():
            threading.Thread(target=s.serve_forever, daemon=True).start()
        try:
            vendors = {t: HttpConnection(f"http://127.0.0.1:{s.server_address[1]}/") for t, s in servers.items()}
            over_http = run_assurance(scenario("faults_showcase"), vendors, seed=42, start_time=START)
        finally:
            for s in servers.values():
                s.shutdown()
        in_process = run_assurance(scenario("faults_showcase"), simulated_vendors(), seed=42, start_time=START)
        self.assertEqual(over_http.ledger.head_hash, in_process.ledger.head_hash)


if __name__ == "__main__":
    unittest.main()
