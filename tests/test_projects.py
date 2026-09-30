"""Tests for project files: loading, processing order from connections, and
cascades in sequential, parallel and controller layouts. The layouts use small
made-up twins fed straight into the unchanged engine monitor."""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from engine.ledger import EvidenceLedger
from engine.monitor import FieldMonitor
from engine.protocol import EscalationProtocol
from engine.registry import load_registry
from engine.run import run_assurance
from projects import DEFAULT_PROJECT, ProjectError, load_project
from telemetry.faults import Scenario

ROOT = Path(__file__).resolve().parent.parent
START = datetime(2026, 10, 1, tzinfo=timezone.utc)


def channel(cid, direction, unit="u"):
    return {"channel_id": cid, "name": cid, "unit": unit, "direction": direction,
            "envelope": {"min": 0, "max": 100}, "tolerance_pct": 5}


class Layout:
    """Writes a throwaway project (twin configs plus project file) into a temp folder."""

    def __init__(self, twins, connections, outputs, metric="relative_pct_of_prediction", roles=None):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        entries = []
        for t, channels in twins.items():
            cfg = {"twin_type": t, "design_twin_id": f"{t}-design", "operational_twin_id": f"{t}-op",
                   "asset_id": f"{t}-asset", "vendor": "test vendor", "twin_mode": "observational", "channels": channels}
            (d / f"{t}.json").write_text(json.dumps(cfg))
            entries.append({"twin_type": t, "config": f"{t}.json", "name": t, "role": (roles or {}).get(t, "product")})
        self.path = d / "project.json"
        self.path.write_text(json.dumps({
            "schema_version": 1, "project_id": "test", "name": "Test", "gap": {"metric": metric}, "twins": entries,
            "composition": {"design_system_twin_id": "sys-design", "operational_system_twin_id": "sys-op",
                            "output_constituents": outputs,
                            "connections": [{"from_twin": a, "from_channel": ac, "to_twin": b, "to_channel": bc}
                                            for (a, ac), (b, bc) in connections]},
        }))

    def load(self):
        return load_project(self.path)

    def close(self):
        self.tmp.cleanup()


def sequential():
    return Layout({"a": [channel("in", "input"), channel("out", "output")],
                   "b": [channel("in", "input"), channel("out", "output")]},
                  [(("a", "out"), ("b", "in"))], ["b"])


def parallel():
    return Layout({"a": [channel("in", "input"), channel("out", "output")],
                   "b": [channel("in", "input"), channel("out", "output")]},
                  [], ["a", "b"])


def controller():
    # Declared out of order on purpose: the pick station first, the controller last.
    return Layout({"pick": [channel("in_1", "input"), channel("in_2", "input"), channel("rate", "output")],
                   "amr1": [channel("tasks", "input"), channel("deliveries", "output")],
                   "amr2": [channel("tasks", "input"), channel("deliveries", "output")],
                   "dispatch": [channel("orders", "input"), channel("to_1", "output"), channel("to_2", "output")]},
                  [(("dispatch", "to_1"), ("amr1", "tasks")), (("dispatch", "to_2"), ("amr2", "tasks")),
                   (("amr1", "deliveries"), ("pick", "in_1")), (("amr2", "deliveries"), ("pick", "in_2"))],
                  ["pick"], roles={"dispatch": "controller"})


def drive(project, gaps, ticks=12):
    """Feed ``ticks`` ticks to the engine's monitor. Every input reads 50 (inside its range);
    every output is predicted 50 and measured 50, except ``gaps``: {twin: gap %} on its outputs."""
    reg = load_registry(project)
    ledger = EvidenceLedger()
    monitor = FieldMonitor(reg, EscalationProtocol(), ledger,
                           {t: f"asr-{p.operational_twin_id}" for t, p in reg.products.items()},
                           f"asr-{reg.system.operational_system_twin_id}")
    for tick in range(ticks):
        rows = []
        for t, p in reg.products.items():
            for c in p.channels:
                out = c.direction == "output"
                rows.append({"run_id": "r", "kind": "field", "tick": tick, "timestamp": f"2026-10-01T00:00:{tick:02d}Z",
                             "operational_hours": tick, "twin_id": p.operational_twin_id, "twin_version": "1.0.0",
                             "channel_id": c.channel_id, "direction": c.direction, "unit": c.unit,
                             "physical_value": 50 * (1 + gaps.get(t, 0) / 100) + 0.001 * tick if out else 50 + 0.001 * tick,
                             "predicted_value": 50 * (1 + 0.00002 * tick) if out else None, "test_point": None})
        monitor.process_tick(rows)
    return {tid: a for tid, a in monitor.status.items()}


class TestOilGasProject(unittest.TestCase):
    def test_loads_with_processing_order_from_connections(self):
        p = load_project()
        self.assertEqual(p.processing_order, ("motor", "compressor"))
        self.assertEqual(p.gap_metric, "relative_pct_of_prediction")
        reg = load_registry()
        self.assertEqual(list(reg.products), ["motor", "compressor"])
        self.assertEqual(reg.system.constituents, ("motor", "compressor"))
        self.assertEqual(reg.system.output_constituents, ("compressor",))
        self.assertEqual(reg.system.connections, ({"from_twin": "motor", "from_channel": "speed", "to_twin": "compressor",
                                                   "to_channel": "speed", "description": "the motor's shaft speed drives the compressor"},))

    def test_twin_config_files_are_used_as_they_are(self):
        p = load_project()
        for t in p.processing_order:
            path = ROOT / "telemetry" / "config" / f"{t}.json"
            self.assertEqual(p.twin(t).config_path, path)
            self.assertEqual(p.config(t), json.loads(path.read_text()))

    def test_file_order_does_not_change_the_evidence(self):
        # List the compressor before the motor: the order still comes from the connection,
        # and the evidence is identical to the unmodified project's.
        raw = json.loads(DEFAULT_PROJECT.read_text())
        raw["twins"].reverse()
        for t in raw["twins"]:
            t["config"] = str((DEFAULT_PROJECT.parent / t["config"]).resolve())
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "reversed.json"
            path.write_text(json.dumps(raw))
            reversed_project = load_project(path)
            self.assertEqual(reversed_project.processing_order, ("motor", "compressor"))
            s = Scenario.from_dict(json.loads((ROOT / "scenarios" / "healthy.json").read_text()))
            a = run_assurance(s, seed=7, start_time=START)
            b = run_assurance(s, seed=7, start_time=START, project=reversed_project)
            self.assertEqual(a.ledger.head_hash, b.ledger.head_hash)


class TestLayouts(unittest.TestCase):
    def tearDown(self):
        self.layout.close()

    def test_sequential(self):
        self.layout = sequential()
        p = self.layout.load()
        self.assertEqual(p.processing_order, ("a", "b"))
        self.assertEqual(p.linked_inputs("b"), {"in": {"from_twin": "a", "from_channel": "out"}})
        # A nullified upstream twin flags the system (cascade); the downstream twin is untouched.
        s = drive(p, {"a": 25})
        self.assertEqual(s["a-op"].level, "nullified")
        self.assertEqual(s["b-op"].level, "assured")
        self.assertEqual(s["sys-op"].level, "flagged")
        self.assertEqual([(r["cause"], r["constituent"]) for r in s["sys-op"].reasons], [("cascade", "a-op")])

    def test_sequential_output_twin_sets_the_system_status(self):
        self.layout = sequential()
        s = drive(self.layout.load(), {"b": 25})
        self.assertEqual(s["b-op"].level, "nullified")
        self.assertEqual(s["sys-op"].level, "nullified")  # takes its output twin's status
        self.assertEqual({r["cause"] for r in s["sys-op"].reasons}, {"cascade", "own_output"})

    def test_parallel(self):
        self.layout = parallel()
        p = self.layout.load()
        self.assertEqual(p.processing_order, ("a", "b"))  # no connections: file order
        self.assertEqual(p.linked_inputs("b"), {})
        s = drive(p, {"a": 7})  # beyond tolerance, not beyond 2x: flagged
        self.assertEqual(s["a-op"].level, "flagged")
        self.assertEqual(s["b-op"].level, "assured")
        self.assertEqual(s["sys-op"].level, "flagged")
        self.assertEqual([(r["cause"], r["constituent"]) for r in s["sys-op"].reasons], [("own_output", "a-op")])

    def test_controller(self):
        self.layout = controller()
        p = self.layout.load()
        self.assertEqual(p.processing_order, ("dispatch", "amr1", "amr2", "pick"))
        self.assertEqual(p.twin("dispatch").role, "controller")
        self.assertEqual(load_registry(p).system.constituents, ("dispatch", "amr1", "amr2", "pick"))
        # A nullified controller cascades to the system twin like any constituent. No
        # controller-specific rule exists: the robots and pick station it feeds stay assured.
        s = drive(p, {"dispatch": 25})
        self.assertEqual(s["dispatch-op"].level, "nullified")
        self.assertEqual({t: s[f"{t}-op"].level for t in ("amr1", "amr2", "pick")},
                         {"amr1": "assured", "amr2": "assured", "pick": "assured"})
        self.assertEqual(s["sys-op"].level, "flagged")
        self.assertEqual([(r["cause"], r["constituent"]) for r in s["sys-op"].reasons], [("cascade", "dispatch-op")])

    def test_controller_fed_robot_cascades_the_same_way(self):
        self.layout = controller()
        s = drive(self.layout.load(), {"amr1": 25})
        self.assertEqual(s["amr1-op"].level, "nullified")
        self.assertEqual(s["sys-op"].level, "flagged")
        self.assertEqual(s["dispatch-op"].level, "assured")


class TestProjectChecks(unittest.TestCase):
    def assertRejected(self, layout, fragment):
        try:
            with self.assertRaises(ProjectError) as cm:
                layout.load()
            self.assertTrue(any(fragment in i for i in cm.exception.issues), cm.exception.issues)
        finally:
            layout.close()

    def io(self):
        return [channel("in", "input"), channel("out", "output")]

    def test_loop(self):
        self.assertRejected(Layout({"a": self.io(), "b": self.io()}, [(("a", "out"), ("b", "in")), (("b", "out"), ("a", "in"))], ["b"]), "loop")

    def test_output_to_output(self):
        self.assertRejected(Layout({"a": self.io(), "b": self.io()}, [(("a", "out"), ("b", "out"))], ["b"]), "from an output to an input")

    def test_unit_mismatch(self):
        l = Layout({"a": [channel("out", "output", "rpm")], "b": [channel("in", "input", "bar"), channel("out", "output")]},
                   [(("a", "out"), ("b", "in"))], ["b"])
        self.assertRejected(l, "share a unit")

    def test_input_fed_twice(self):
        l = Layout({"a": self.io(), "c": self.io(), "b": self.io()}, [(("a", "out"), ("b", "in")), (("c", "out"), ("b", "in"))], ["b"])
        self.assertRejected(l, "already fed")

    def test_unknown_channel(self):
        self.assertRejected(Layout({"a": self.io(), "b": self.io()}, [(("a", "nope"), ("b", "in"))], ["b"]), "does not have")

    def test_gap_metric_is_fixed(self):
        self.assertRejected(Layout({"a": self.io()}, [], ["a"], metric="absolute"), "not supported")

    def test_output_constituents_required(self):
        self.assertRejected(Layout({"a": self.io()}, [], []), "output constituent")

    def test_twin_needs_an_output(self):
        self.assertRejected(Layout({"a": [channel("in", "input")]}, [], ["a"]), "at least one output")

    def test_legacy_linked_inputs_must_agree(self):
        l = Layout({"a": self.io(), "b": self.io()}, [(("a", "out"), ("b", "in"))], ["b"])
        cfg_path = Path(l.tmp.name) / "b.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["linked_inputs"] = {"in": {"from_twin": "a", "from_channel": "other"}}
        cfg_path.write_text(json.dumps(cfg))
        self.assertRejected(l, "linked_inputs disagree")


if __name__ == "__main__":
    unittest.main()
