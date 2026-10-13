"""The Fulfilment cell project (projects/fulfilment_cell.json): a fleet dispatcher, two
autonomous mobile robots and a pick station, on synthetic data. Each test checks a
behaviour of the cell's three scenarios against the engine's sealed rules."""

import copy
import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from engine.boundary import HttpConnection
from engine.composition import external_inputs, test_points
from engine.ledger import verify_chain
from engine.lineage import verify_lineage
from engine.registry import load_registry
from engine.run import run_assurance
from projects import DEFAULT_PROJECT, ProjectError, load_project
from telemetry.faults import Scenario
from vendor.endpoint import simulated_endpoints, simulated_vendors

ROOT = Path(__file__).resolve().parent.parent
START = datetime(2026, 10, 1, tzinfo=timezone.utc)
CELL = load_project(ROOT / "projects" / "fulfilment_cell.json")
SYSTEM = "fulfilment-system-op-001"


def scenario(name: str) -> Scenario:
    return Scenario.from_dict(json.loads((ROOT / "scenarios" / f"{name}.json").read_text()))


def run(name: str, vendors=None):
    return run_assurance(scenario(name), vendors or simulated_vendors(CELL), seed=42, start_time=START, project=CELL)


def changes(result, twin_id: str) -> list[dict]:
    return [e["payload"] for e in result.ledger.entries
            if e["entry_type"] in ("assurance_status_changed", "assurance_reason_added") and e["payload"]["twin_id"] == twin_id]


def gaps(result, twin_id: str, channel: str) -> dict[int, float | None]:
    return {row["tick"]: row["classifications"][twin_id][channel].get("gap_pct") for row in result.timeline}


class TestProject(unittest.TestCase):
    def test_topology_and_processing_order(self):
        self.assertEqual(CELL.processing_order, ("dispatcher", "amr1", "amr2", "pick_station"))
        self.assertEqual(CELL.entry_twins, ("dispatcher",))
        self.assertEqual(CELL.output_constituents, ("pick_station",))
        self.assertEqual(CELL.twin("dispatcher").role, "controller")
        self.assertEqual(sum(len(t.config["channels"]) for t in CELL.twins), 17)

    def test_opens_in_the_whole_system_view_with_a_smaller_joint_grid(self):
        self.assertEqual((CELL.opens_in, CELL.test_levels), ("system", 3))
        compressor = load_project(DEFAULT_PROJECT)
        self.assertEqual((compressor.opens_in, compressor.test_levels), ("entry", 5))

    def test_joint_grid_is_three_levels_on_five_external_inputs(self):
        reg = load_registry(CELL)
        self.assertEqual(external_inputs(reg), [("dispatcher", "order_rate"), ("amr1", "battery"), ("amr1", "speed_setpoint"),
                                                ("amr2", "battery"), ("amr2", "speed_setpoint")])
        self.assertEqual(len(test_points(reg)), 3 ** 5)
        self.assertEqual(len(test_points(load_registry())), 5 ** 3)  # the compressor train is unchanged

    def test_bad_settings_are_refused(self):
        raw = json.loads((ROOT / "projects" / "fulfilment_cell.json").read_text())
        for patch in ({"composition": {**raw["composition"], "test_levels": 1}}, {"view": {"opens_in": "sideways"}}):
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "cell.json"
                p.write_text(json.dumps({**raw, **patch}).replace("../telemetry", str(ROOT / "telemetry")))
                with self.assertRaises(ProjectError):
                    load_project(p)

    def test_data_is_synthetic_and_names_are_neutral(self):
        for t in CELL.twins:
            self.assertTrue(t.config["vendor"].startswith("synthetic-vendor-"))
            self.assertIn("Illustrative only", t.config["description"])
        text = "".join(p.read_text().lower() for p in [CELL.path, *(t.config_path for t in CELL.twins),
                                                        *(ROOT / "scenarios").glob("amr_*.json")])
        self.assertNotIn("lidar", text)


class TestFullCycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = run("amr_full_cycle")
        cls.e = cls.r.ledger.entries

    def test_every_twin_passes_design_time_checks(self):
        for t in ("verification", "bench_validation"):
            design = [p for p in (e["payload"] for e in self.r.ledger.of_type(t)) if p.get("stage") != "re-verification"]
            self.assertEqual(len(design), 4)
            self.assertTrue(all(p["passed"] for p in design))

    def test_amr1_flags_on_the_third_consecutive_breach(self):
        flag = next(c for c in changes(self.r, "amr1-op-001") if c.get("to") == "flagged")
        self.assertEqual(flag["tick"], 21)
        self.assertEqual({(r["channel_id"], r["detail"]) for r in flag["new_reasons"]},
                         {("speed", "3 consecutive readings beyond 5%"), ("deliveries", "3 consecutive readings beyond 5%")})
        g = gaps(self.r, "amr1-op-001", "speed")
        self.assertTrue(all(g[t] > 5 for t in (19, 20, 21)) and g[18] <= 5)

    def test_amr1_nullifies_on_the_tenth_consecutive_reading_beyond_twice_tolerance(self):
        null = next(c for c in changes(self.r, "amr1-op-001") if c.get("to") == "nullified")
        self.assertEqual(null["tick"], 36)
        self.assertEqual(null["new_reasons"][0]["detail"], "10 consecutive readings beyond 10%")
        g = gaps(self.r, "amr1-op-001", null["new_reasons"][0]["channel_id"])
        self.assertTrue(all(g[t] > 10 for t in range(27, 37)) and g[26] <= 10)

    def test_the_nullified_robot_cascades_to_the_system_twin(self):
        first = changes(self.r, SYSTEM)[0]
        self.assertEqual((first["tick"], first["to"]), (36, "flagged"))
        self.assertEqual(first["new_reasons"][0]["cause"], "cascade")
        self.assertEqual(first["new_reasons"][0]["constituent"], "amr1-op-001")

    def test_fewer_totes_flag_the_pick_station_and_the_system_through_its_output(self):
        pick = changes(self.r, "pick-op-001")
        self.assertEqual((pick[0]["tick"], pick[0]["to"]), (64, "flagged"))
        self.assertEqual((pick[0]["new_reasons"][0]["cause"], pick[0]["new_reasons"][0]["channel_id"]),
                         ("envelope_violation", "arrivals_1"))
        own = [c for c in changes(self.r, SYSTEM) if c["new_reasons"][0]["cause"] == "own_output"]
        self.assertEqual(own[0]["tick"], 64)

    def test_wheel_odometry_dropout_is_data_quality_not_twin_error(self):
        dq = [e["payload"] for e in self.r.ledger.of_type("anomaly_opened") if e["payload"]["type"] == "data_quality"]
        self.assertEqual([(p["twin_id"], p["channel_id"], p["subtype"], p["tick"]) for p in dq],
                         [("amr2-op-001", "speed", "dropout", 46)])
        self.assertEqual(changes(self.r, "amr2-op-001"), [])

    def test_recalibration_is_validated_on_held_out_data_and_registers_a_linked_version(self):
        held = self.r.ledger.of_type("held_out_validation")[0]["payload"]
        self.assertTrue(held["passed"])
        self.assertEqual(held["twin_id"], "amr1-op-001")
        versions = [e["payload"] for e in self.r.ledger.of_type("twin_version_registered")]
        amr1 = [v for v in versions if v.get("operational_twin_id") == "amr1-op-001"]
        self.assertEqual([v["twin"]["version"] for v in amr1], ["1.0.0", "1.1.0"])
        self.assertEqual(amr1[1]["parent_fingerprint"], amr1[0]["twin"]["fingerprint"])
        system = [v for v in versions if v.get("composition") == "system"]
        self.assertEqual([v["twin"]["version"] for v in system], ["1", "2"])

    def test_joint_tests_pass_at_build_and_fail_on_the_named_interface_after_recalibration(self):
        build, after = (e["payload"] for e in self.r.ledger.of_type("composition_test"))
        self.assertEqual((build["levels"], build["points"]), (3, 243))
        self.assertTrue(build["passed"])
        self.assertFalse(after["interface"]["passed"])
        failed = [c for c in after["interface"]["connections"] if not c["passed"]]
        self.assertEqual([(c["from"], c["to"]) for c in failed], [("amr1/deliveries", "pick_station/arrivals_1")])
        self.assertGreater(failed[0]["points_outside"], 0)
        self.assertTrue(after["interaction"]["passed"])
        reason = next(c for c in changes(self.r, SYSTEM) if c["new_reasons"][0]["cause"] == "interface_invalid")
        self.assertEqual(reason["tick"], 60)
        self.assertEqual(self.r.ledger.of_type("composition_reassessment")[0]["payload"]["result"], "not_reassured")

    def test_human_approved_adjustment_brings_the_arrivals_back_into_range(self):
        rec = self.r.ledger.of_type("adjustment_recommended")[0]["payload"]
        self.assertEqual(rec["recommendation"]["control_channel"], "speed_setpoint")
        self.assertTrue(1.2 <= rec["recommendation"]["to"] <= 2.0)
        self.assertEqual(self.r.ledger.of_type("adjustment_approval")[0]["payload"]["approver"], "Operator (demo)")
        check = self.r.ledger.of_type("adjustment_post_state_check")[0]["payload"]
        self.assertTrue(check["sim2real_passed"])
        self.assertTrue(check["objective"]["met"])
        # No setpoint change big enough to read as a sensor spike.
        self.assertFalse([e for e in self.r.ledger.of_type("anomaly_opened")
                          if e["payload"]["channel_id"] == "speed_setpoint"])

    def test_final_statuses(self):
        final = self.e[-1]["payload"]["final_status"]
        self.assertEqual({k: v["level"] for k, v in final.items()},
                         {"dispatcher-op-001": "assured", "amr1-op-001": "assured", "amr2-op-001": "assured",
                          "pick-op-001": "flagged", SYSTEM: "flagged"})

    def test_chain_and_lineage_verify_and_tampering_is_caught(self):
        self.assertTrue(verify_chain(self.e).valid)
        self.assertTrue(verify_lineage(self.e, self.r.readings, self.r.exchange).valid)
        bad = copy.deepcopy(self.e)
        seq = next(e["seq"] for e in bad if e["entry_type"] == "assurance_status_changed")
        bad[seq]["payload"]["to"] = "assured"
        check = verify_chain(bad)
        self.assertFalse(check.valid)
        self.assertEqual(check.first_bad_seq, seq)

    def test_a_rerun_gives_the_same_head_hash(self):
        self.assertEqual(run("amr_full_cycle").ledger.head_hash, self.r.ledger.head_hash)


class TestWearAndFaults(unittest.TestCase):
    def test_wear_to_nullified(self):
        r = run("amr_wear_to_nullified")
        final = {k: v["level"] for k, v in r.ledger.entries[-1]["payload"]["final_status"].items()}
        self.assertEqual(final["amr1-op-001"], "nullified")
        self.assertEqual(final["pick-op-001"], "flagged")
        self.assertEqual(final[SYSTEM], "flagged")
        self.assertFalse(r.ledger.of_type("recalibration_requested"))

    def test_faults_showcase(self):
        r = run("amr_faults_showcase")
        disp = changes(r, "dispatcher-op-001")
        self.assertEqual((disp[0]["tick"], disp[0]["new_reasons"][0]["cause"], disp[0]["new_reasons"][0]["channel_id"]),
                         (12, "envelope_violation", "order_rate"))
        dq = sorted((p["twin_id"], p["channel_id"], p["subtype"]) for p in (e["payload"] for e in r.ledger.of_type("anomaly_opened"))
                    if p["type"] == "data_quality")
        self.assertEqual(dq, [("amr1-op-001", "battery", "stuck"), ("amr2-op-001", "speed", "dropout"),
                              ("pick-op-001", "cycle_time", "spike")])
        final = {k: v["level"] for k, v in r.ledger.entries[-1]["payload"]["final_status"].items()}
        self.assertEqual(final, {"dispatcher-op-001": "flagged", "amr1-op-001": "assured", "amr2-op-001": "assured",
                                 "pick-op-001": "assured", SYSTEM: "assured"})

    def test_a_run_over_http_matches_a_run_in_process(self):
        from http.server import ThreadingHTTPServer
        from vendor.serve import handler_for

        servers = {t: ThreadingHTTPServer(("127.0.0.1", 0), handler_for(e)) for t, e in simulated_endpoints(CELL).items()}
        for s in servers.values():
            threading.Thread(target=s.serve_forever, daemon=True).start()
        try:
            over_http = run("amr_faults_showcase", {t: HttpConnection(f"http://127.0.0.1:{s.server_address[1]}/")
                                                    for t, s in servers.items()})
        finally:
            for s in servers.values():
                s.shutdown()
                s.server_close()
        self.assertEqual(over_http.ledger.head_hash, run("amr_faults_showcase").ledger.head_hash)


if __name__ == "__main__":
    unittest.main()
