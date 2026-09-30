"""Tests for the telemetry generator. Run with:  python3 -m unittest -v"""

import json
import tempfile
import unittest
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from telemetry.faults import DataQualityFault, EnvelopeViolation, Scenario, WearDrift
from projects import load_project
from telemetry.generator import TelemetryGenerator
from telemetry.sinks import InMemorySink, JsonlFileSink

START = datetime(2026, 10, 1, tzinfo=timezone.utc)
SCENARIOS = Path(__file__).resolve().parent.parent / "scenarios"


def gen(seed=42):
    return TelemetryGenerator(seed=seed, start_time=START)


def rows(scenario, seed=42):
    return [r for batch in gen(seed).field_run(scenario) for r in batch]


def gap_pct(r):
    return 100 * abs(r.physical_value - r.predicted_value) / r.predicted_value


class TestReproducibility(unittest.TestCase):
    def test_same_seed_same_data(self):
        s = Scenario(name="t", ticks=20)
        self.assertEqual([asdict(r) for r in rows(s)], [asdict(r) for r in rows(s)])

    def test_different_seed_different_data(self):
        s = Scenario(name="t", ticks=20)
        self.assertNotEqual([r.physical_value for r in rows(s, 1)], [r.physical_value for r in rows(s, 2)])

    def test_adding_a_fault_does_not_reshuffle_unrelated_randomness(self):
        flow = lambda out: [r.physical_value for r in out if r.channel_id == "flow"]
        plain = rows(Scenario(name="t", ticks=50))
        faulty = rows(Scenario(name="t", ticks=50, wear=(WearDrift("motor", 5, {"speed": -20}),),
                               envelope_violations=(EnvelopeViolation("motor", "volt", 3, 4, 440),)))
        self.assertEqual(flow(plain), flow(faulty))


class TestFieldStream(unittest.TestCase):
    def test_every_channel_every_tick_with_two_second_cadence(self):
        out = rows(Scenario(name="t", ticks=3))
        self.assertEqual(len(out), 3 * 8)  # 2 twins x 4 channels
        self.assertEqual(out[0].timestamp, "2026-10-01T00:00:00Z")
        self.assertEqual(out[-1].timestamp, "2026-10-01T00:00:04Z")

    def test_inputs_have_no_prediction_outputs_do(self):
        for r in rows(Scenario(name="t", ticks=5)):
            if r.direction == "input":
                self.assertIsNone(r.predicted_value)
            else:
                self.assertIsNotNone(r.predicted_value)

    def test_healthy_run_stays_inside_tolerance(self):
        for r in rows(Scenario(name="t", ticks=1000)):
            if r.direction == "output":
                self.assertLess(gap_pct(r), 5, f"tick {r.tick} {r.twin_type}.{r.channel_id}")

    def test_healthy_inputs_stay_inside_envelope(self):
        envelopes = {
            (t, c["channel_id"]): c["envelope"]
            for t in load_project().processing_order
            for c in load_project().config(t)["channels"]
        }
        for r in rows(Scenario(name="t", ticks=1000)):
            if r.direction == "input":
                env = envelopes[(r.twin_type, r.channel_id)]
                self.assertTrue(env["min"] <= r.physical_value <= env["max"], f"tick {r.tick} {r.channel_id}")

    def test_compressor_speed_follows_motor_speed(self):
        out = rows(Scenario(name="t", ticks=30))
        for tick in range(30):
            motor = next(r for r in out if r.tick == tick and r.twin_type == "motor" and r.channel_id == "speed")
            comp = next(r for r in out if r.tick == tick and r.twin_type == "compressor" and r.channel_id == "speed")
            self.assertAlmostEqual(comp.physical_value, motor.physical_value, delta=0.05 * motor.physical_value)

    def test_fast_forward_advances_operational_hours(self):
        out = rows(Scenario(name="t", ticks=3, operational_hours_per_tick=24))
        self.assertEqual(sorted({r.operational_hours for r in out}), [0, 24, 48])
        self.assertEqual(out[-1].timestamp, "2026-10-01T00:00:04Z")  # stream cadence unchanged


class TestFaults(unittest.TestCase):
    def test_wear_widens_gap_only_after_start(self):
        s = Scenario(name="t", ticks=60, operational_hours_per_tick=24,
                     wear=(WearDrift("motor", 10, {"speed": -20}),))
        speed = [r for r in rows(s) if r.twin_type == "motor" and r.channel_id == "speed"]
        self.assertTrue(all(not r.injected_faults for r in speed[:11]))
        self.assertTrue(all(gap_pct(r) < 5 for r in speed[:11]))
        self.assertTrue(all(gap_pct(r) > 10 for r in speed[-10:]))

    def test_envelope_violation_forces_input_and_is_labelled(self):
        s = Scenario(name="t", ticks=10, envelope_violations=(EnvelopeViolation("motor", "volt", 3, 2, 440),))
        volt = {r.tick: r for r in rows(s) if r.twin_type == "motor" and r.channel_id == "volt"}
        self.assertAlmostEqual(volt[3].physical_value, 440, delta=6)  # jittered, like a real reading
        self.assertNotEqual(volt[3].physical_value, volt[4].physical_value)  # never an exact repeat
        self.assertEqual(volt[4].injected_faults, ["envelope_violation"])
        self.assertLess(volt[5].physical_value, 420)

    def test_spike_multiplies_reading(self):
        base = rows(Scenario(name="t", ticks=5))
        s = Scenario(name="t", ticks=5, data_quality=(DataQualityFault("compressor", "temperature", 2, 1, "spike", 1.5),))
        pick = lambda out: next(r for r in out if r.tick == 2 and r.channel_id == "temperature")
        self.assertAlmostEqual(pick(rows(s)).physical_value, pick(base).physical_value * 1.5, places=2)

    def test_dropout_on_input_leaves_twin_without_prediction(self):
        s = Scenario(name="t", ticks=5, data_quality=(DataQualityFault("motor", "volt", 2, 1, "dropout"),))
        tick2 = [r for r in rows(s) if r.tick == 2 and r.twin_type == "motor"]
        self.assertIsNone(next(r for r in tick2 if r.channel_id == "volt").physical_value)
        self.assertTrue(all(r.predicted_value is None for r in tick2 if r.direction == "output"))

    def test_stuck_sensor_repeats_last_value(self):
        s = Scenario(name="t", ticks=10, data_quality=(DataQualityFault("compressor", "pressure", 4, 3, "stuck"),))
        p = {r.tick: r.physical_value for r in rows(s) if r.twin_type == "compressor" and r.channel_id == "pressure"}
        self.assertEqual(p[3], p[4])
        self.assertEqual(p[3], p[6])
        self.assertNotEqual(p[6], p[7])

    def test_unknown_data_quality_kind_rejected(self):
        with self.assertRaises(ValueError):
            DataQualityFault("motor", "volt", 0, 1, "glitch")


class TestBench(unittest.TestCase):
    def test_sweep_covers_envelope_corners(self):
        batches = list(gen().bench_sweep("motor", levels=5, repeats=3))
        self.assertEqual(len(batches), 5 * 5 * 3)
        volts = {r.physical_value for b in batches for r in b if r.channel_id == "volt"}
        self.assertEqual((min(volts), max(volts)), (380, 420))
        self.assertTrue(all(r.twin_id == "motor-design" for b in batches for r in b))

    def test_bench_twin_matches_physical_within_tolerance(self):
        for b in gen().bench_sweep("compressor"):
            for r in b:
                if r.direction == "output":
                    self.assertLess(gap_pct(r), 5)


class TestSinksAndScenarios(unittest.TestCase):
    def test_jsonl_sink_writes_manifest_and_one_line_per_reading(self):
        g = gen()
        s = Scenario(name="t", ticks=4)
        with tempfile.TemporaryDirectory() as d:
            sink = JsonlFileSink(Path(d) / "r.jsonl", Path(d) / "m.json")
            sink.write_manifest(g.manifest("rid", "field", {}))
            for batch in g.field_run(s):
                sink.write(batch)
            sink.close()
            self.assertEqual(len((Path(d) / "r.jsonl").read_text().splitlines()), 4 * 8)
            self.assertEqual(json.loads((Path(d) / "m.json").read_text())["seed"], 42)

    def test_in_memory_sink_keeps_only_latest(self):
        sink = InMemorySink(max_readings=8)
        for batch in gen().field_run(Scenario(name="t", ticks=5)):
            sink.write(batch)
        self.assertEqual({r.tick for r in sink.readings}, {4})

    def test_bundled_scenarios_load(self):
        for path in SCENARIOS.glob("*.json"):
            Scenario.from_dict(json.loads(path.read_text()))


if __name__ == "__main__":
    unittest.main()
