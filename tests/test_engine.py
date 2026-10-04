"""Tests for the assurance engine. The generator's ``injected_faults`` labels
are used here -- and only here -- as ground truth to check the engine's
decisions; the engine itself never sees them."""

import json
import math
import unittest
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from engine.ledger import verify_chain
from engine.protocol import EscalationProtocol
from engine.readings import ingest
from engine.registry import load_registry
from engine.run import run_assurance
from engine.validation import bench_validate
from engine.verification import verify
from telemetry.faults import DataQualityFault, EnvelopeViolation, Scenario
from telemetry.generator import TelemetryGenerator
from telemetry.models import TwinModel
from vendor.endpoint import simulated_vendors

START = datetime(2026, 10, 1, tzinfo=timezone.utc)
SCENARIOS = Path(__file__).resolve().parent.parent / "scenarios"
MOTOR, COMP, SYSTEM = "motor-op-001", "compressor-op-001", "compressor-system-op-001"


def scenario(name):
    return Scenario.from_dict(json.loads((SCENARIOS / f"{name}.json").read_text()))


def run(s, twins=None, **kw):
    return run_assurance(s, simulated_vendors(twins=twins), seed=42, start_time=START, **kw)


def transitions(result):
    """[(tick, twin, from, to)] for every status change."""
    return [(e["payload"]["tick"], e["payload"]["twin_id"], e["payload"]["from"], e["payload"]["to"])
            for e in result.ledger.of_type("assurance_status_changed")]


def reasons(result, twin_id):
    return [(r["level"], r["cause"], r.get("channel_id"), r.get("constituent"))
            for r in result.monitor.status[twin_id].reasons]


class BrokenTwin(TwinModel):
    """A twin that is not internally coherent: gives NaN for one input region."""

    def predict(self, inputs):
        out = super().predict(inputs)
        if inputs.get("volt", 0) > 410:
            out = {**out, "vibration": math.nan}
        return out


class TestDesignTimeAssurance(unittest.TestCase):
    def setUp(self):
        self.reg = load_registry()
        self.protocol = EscalationProtocol()

    def test_default_twins_pass_verification(self):
        for t, product in self.reg.products.items():
            self.assertTrue(verify(product, TwinModel(t), self.protocol)["passed"], t)

    def test_incoherent_twin_fails_verification(self):
        record = verify(self.reg.products["motor"], BrokenTwin("motor"), self.protocol)
        self.assertFalse(record["passed"])
        self.assertFalse(next(c for c in record["checks"] if c["check"] == "finite")["passed"])

    def test_verification_records_envelope_and_protocol(self):
        record = verify(self.reg.products["motor"], TwinModel("motor"), self.protocol)
        self.assertEqual(record["envelope"]["volt"]["max"], 420)
        self.assertEqual(record["escalation_protocol"]["flag_after_consecutive"], 3)

    def test_miscalibrated_twin_fails_bench_validation(self):
        bad = TwinModel("motor", params={**TwinModel("motor").params, "speed_per_volt": 3.5})
        gen = TelemetryGenerator(seed=42, start_time=START, twins={"motor": bad, "compressor": TwinModel("compressor")})
        bench = [ingest(asdict(r)) for b in gen.bench_sweep("motor") for r in b]
        record = bench_validate(self.reg.products["motor"], bench)
        self.assertFalse(record["passed"])
        self.assertGreater(record["per_channel"]["speed"]["over_tolerance"], 0)

    def test_refused_assurance_blocks_monitoring(self):
        result = run(Scenario(name="t", ticks=5), twins={"motor": BrokenTwin("motor"), "compressor": TwinModel("compressor")})
        self.assertFalse(result.assured)
        self.assertEqual(len(result.ledger.of_type("assurance_refused")), 1)
        self.assertEqual(result.ledger.of_type("composition_assured"), [])
        self.assertEqual(result.timeline, [])

    def test_operational_twins_and_compositions_issued(self):
        result = run(Scenario(name="t", ticks=1))
        issued = {e["payload"]["assurance_id"] for e in result.ledger.of_type("assurance_issued")}
        self.assertEqual(issued, {"asr-motor-design-v1", "asr-motor-op-001-v1",
                                  "asr-compressor-design-v1", "asr-compressor-op-001-v1"})
        comp = {e["payload"]["composition_assurance_id"] for e in result.ledger.of_type("composition_assured")}
        self.assertEqual(comp, {"asr-compressor-system-design-v1", "asr-compressor-system-op-001-v1"})


class TestFieldMonitoring(unittest.TestCase):
    def test_healthy_run_stays_assured_with_no_anomalies(self):
        result = run(Scenario(name="t", ticks=500, operational_hours_per_tick=24))
        self.assertEqual(transitions(result), [])
        self.assertEqual(result.ledger.of_type("anomaly_opened"), [])

    def test_wear_demo_sequence(self):
        result = run(scenario("demo_wear_to_nullified"))
        self.assertEqual(transitions(result), [
            (19, MOTOR, "assured", "flagged"),
            (25, COMP, "assured", "flagged"),
            (25, SYSTEM, "assured", "flagged"),
            (36, MOTOR, "flagged", "nullified"),
        ])
        # The compressor is flagged for its OWN reason: its input left the envelope.
        self.assertEqual(reasons(result, COMP), [("flagged", "envelope_violation", "speed", None)])
        # The system twin carries two distinct, traceable reasons.
        self.assertEqual(reasons(result, SYSTEM), [
            ("flagged", "own_output", None, COMP),
            ("flagged", "cascade", None, MOTOR),
        ])
        cascade = result.monitor.status[SYSTEM].reasons[1]
        self.assertEqual(cascade["root_causes"][0]["cause"], "gap_exceedance")

    def test_out_of_envelope_gaps_are_not_blamed_on_the_twin(self):
        result = run(scenario("demo_wear_to_nullified"))
        comp_gaps = [e for e in result.ledger.of_type("anomaly_opened")
                     if e["payload"]["twin_id"] == COMP and e["payload"]["type"] == "gap_exceedance"]
        self.assertEqual(comp_gaps, [])
        late = result.timeline[57]["classifications"][COMP]["temperature"]
        self.assertEqual(late, {"class": "not_evaluated", "reason": "input_outside_envelope", "inputs": ["speed"]})

    def test_data_quality_faults_match_ground_truth(self):
        s = scenario("faults_showcase")
        result = run(s)
        found = {(e["payload"]["twin_id"], e["payload"]["channel_id"], e["payload"]["subtype"], e["payload"]["tick"])
                 for e in result.ledger.of_type("anomaly_opened") if e["payload"]["type"] == "data_quality"}
        # Ground truth from the scenario. A stuck fault repeats the reading from the tick
        # before it starts, so the 3rd identical reading lands one tick after it starts.
        expected = {(f"{q.twin_type}-op-001", q.channel, q.kind, q.start_tick + (q.kind == "stuck"))
                    for q in s.data_quality}
        self.assertEqual(found, expected)
        gap_anomalies = [e for e in result.ledger.of_type("anomaly_opened") if e["payload"]["type"] == "gap_exceedance"]
        self.assertEqual(gap_anomalies, [])

    def test_envelope_violation_flags_but_never_nullifies(self):
        s = Scenario(name="t", ticks=40, envelope_violations=(EnvelopeViolation("motor", "volt", 5, 30, 470),))
        result = run(s)
        self.assertEqual(result.monitor.status[MOTOR].level, "flagged")
        self.assertEqual(transitions(result)[0][:2], (7, MOTOR))  # 3rd consecutive out-of-envelope reading

    def test_dropout_on_input_does_not_reset_gap_run(self):
        # A dropout mid-drift is skipped, so the run of bad readings continues across it.
        s = scenario("demo_wear_to_nullified")
        base = transitions(run(s))
        s2 = Scenario(name=s.name, ticks=s.ticks, operational_hours_per_tick=s.operational_hours_per_tick,
                      wear=s.wear, data_quality=(DataQualityFault("motor", "speed", 18, 1, "dropout"),))
        with_gap = transitions(run(s2))
        self.assertEqual(with_gap[0], (20, MOTOR, "assured", "flagged"))  # one tick later, not reset
        self.assertEqual(base[0], (19, MOTOR, "assured", "flagged"))

    def test_status_is_sticky(self):
        result = run(scenario("faults_showcase"))
        self.assertEqual(result.monitor.status[MOTOR].level, "flagged")
        self.assertEqual(result.timeline[-1]["status"][MOTOR], "flagged")  # long after the violation ended

    def test_acknowledgement_recorded(self):
        result = run(scenario("faults_showcase"))
        anomaly = result.ledger.of_type("anomaly_opened")[0]["payload"]["anomaly_id"]
        entry = result.monitor.acknowledge(anomaly, "operator (demo)", "sensor inspected", "2026-10-01T00:02:00Z")
        self.assertEqual(entry["payload"]["acknowledged_by"], "operator (demo)")
        self.assertTrue(verify_chain(result.ledger.entries).valid)


class TestEvidence(unittest.TestCase):
    def test_ledger_is_valid_and_reproducible(self):
        a, b = run(scenario("demo_wear_to_nullified")), run(scenario("demo_wear_to_nullified"))
        self.assertTrue(verify_chain(a.ledger.entries).valid)
        self.assertEqual(a.ledger.head_hash, b.ledger.head_hash)

    def test_every_reading_covered_by_a_checkpoint(self):
        result = run(scenario("demo_wear_to_nullified"))
        cps = [e["payload"] for e in result.ledger.of_type("readings_checkpoint")]
        self.assertEqual(sum(c["readings"] for c in cps), 60 * 8)
        self.assertEqual([(c["from_tick"], c["to_tick"]) for c in cps][0], (0, 9))
        self.assertEqual(cps[-1]["to_tick"], 59)

    def test_engine_never_sees_ground_truth_labels(self):
        gen = TelemetryGenerator(seed=42, start_time=START)
        r = next(iter(gen.field_run(Scenario(name="t", ticks=1))))[0]
        self.assertNotIn("injected_faults", ingest(asdict(r)))


if __name__ == "__main__":
    unittest.main()
