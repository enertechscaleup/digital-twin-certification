"""Replay mode (engine/replay.py): the engine run on field readings from outside the generator.

The six sealed runs live in the git-ignored data/ folder; the tests that replay them are skipped,
and say so, when it is absent. The loader tests build their own small inputs."""

import json
import random
import tempfile
import unittest
from pathlib import Path

from engine.replay import COMPARISON, INGESTION, ReplayRefused, compare, load_readings, replay
from engine.run import run_assurance
from projects import find_project
from telemetry.faults import Scenario
from vendor.endpoint import simulated_vendors

PINS = {r["run"]: r for r in json.loads(Path("app/config/runs.json").read_text())["runs"]}
SEALED = {"oil-gas-compressor-train": Path("data/lineage"), "amr-fulfilment-cell": Path("data/fulfilment")}
HAVE_DATA = all((SEALED[p["project_id"]] / f"{r}.readings.jsonl").exists() for r, p in PINS.items())
SMALL = "assurance-amr_faults_showcase-seed42"


def sealed_rows(run: str) -> list[dict]:
    d = SEALED[PINS[run]["project_id"]]
    return [json.loads(l) for l in (d / f"{run}.readings.jsonl").read_text().splitlines()]


def write(rows: list[dict], path: Path) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


@unittest.skipUnless(HAVE_DATA, "the sealed runs (git-ignored data/) are not on this machine")
class TestReplayEquivalence(unittest.TestCase):
    def test_comparison_copy_reproduces_every_pinned_head(self):
        for run, pin in PINS.items():
            with self.subTest(run=run), tempfile.TemporaryDirectory() as t:
                project = find_project(pin["project_id"])
                d = SEALED[pin["project_id"]]
                result, loaded = replay(project, simulated_vendors(project), d, run, d / f"{run}.readings.jsonl", COMPARISON, Path(t))
                self.assertEqual(result.ledger.head_hash, pin["core_ledger_head_hash"])
                self.assertTrue(compare(result, d, run, pin["core_ledger_head_hash"])["level1_same_decisions"])

    def test_shuffled_and_duplicated_stream_restored_by_the_canonical_order(self):
        # What the pipeline does: drop duplicates by (tick, twin, channel), then order each tick canonically.
        rows = sealed_rows(SMALL)
        rng = random.Random(7)
        msgs = rows + rng.sample(rows, 50)
        rng.shuffle(msgs)
        order = {(r["twin_id"], r["channel_id"]): i for i, r in enumerate(x for x in rows if x["tick"] == 0)}
        unique = {}
        for r in msgs:
            unique.setdefault((r["tick"], r["twin_id"], r["channel_id"]), r)
        restored = sorted(unique.values(), key=lambda r: (r["tick"], order[(r["twin_id"], r["channel_id"])]))
        pin = PINS[SMALL]
        with tempfile.TemporaryDirectory() as t:
            project = find_project(pin["project_id"])
            result, _ = replay(project, simulated_vendors(project), Path("data/fulfilment"), SMALL,
                               write(restored, Path(t) / "r.jsonl"), COMPARISON, Path(t) / "out")
        self.assertEqual(result.ledger.head_hash, pin["core_ledger_head_hash"])

    def test_ingestion_labelled_run_same_decisions_different_head(self):
        # Every run, including the full cycles, whose approval cites its recommendation by entry hash.
        for run, pin in PINS.items():
            d = SEALED[pin["project_id"]]
            with self.subTest(run=run), tempfile.TemporaryDirectory() as t:
                project = find_project(pin["project_id"])
                result, _ = replay(project, simulated_vendors(project), d, run, d / f"{run}.readings.jsonl", INGESTION,
                                   Path(t), actual_commit="0" * 40, ingestion={"replay_id": "test"})
                report = compare(result, d, run, pin["core_ledger_head_hash"], "0" * 40)
                self.assertTrue(report["level1_same_decisions"], report)
                self.assertFalse(report["level2_same_head"])
        self.assertEqual([e["entry_type"] for e in result.ledger.entries][-2:], ["field_readings_source", "run_completed"])
        source = result.ledger.entries[-2]["payload"]
        self.assertEqual(source["label"], "ingestion-labelled")
        self.assertEqual(source["replay_id"], "test")


class TestLoaderFailsClosed(unittest.TestCase):
    project = find_project("amr-fulfilment-cell")

    def rows(self):
        if HAVE_DATA:
            return [r for r in sealed_rows(SMALL) if r["tick"] < 3]
        self.skipTest("the sealed runs (git-ignored data/) are not on this machine")

    def refused(self, rows):
        with tempfile.TemporaryDirectory() as t, self.assertRaises(ReplayRefused) as e:
            load_readings(write(rows, Path(t) / "r.jsonl"), self.project)
        return str(e.exception)

    def test_accepts_a_complete_stream(self):
        with tempfile.TemporaryDirectory() as t:
            loaded = load_readings(write(self.rows(), Path(t) / "r.jsonl"), self.project)
        self.assertEqual((len(loaded.batches), loaded.rows), (3, 51))

    def test_missing_reading(self):
        rows = self.rows()
        self.assertIn("missing", self.refused(rows[:20] + rows[21:]))

    def test_duplicate_reading(self):
        rows = self.rows()
        self.assertIn("duplicated 1", self.refused(rows[:20] + [rows[19]] + rows[20:]))

    def test_out_of_order_within_a_tick(self):
        rows = self.rows()
        rows[0], rows[1] = rows[1], rows[0]
        self.assertIn("canonical order", self.refused(rows))

    def test_missing_tick(self):
        self.assertIn("tick 1 missing", self.refused([r for r in self.rows() if r["tick"] != 1]))

    def test_ground_truth_field_refused(self):
        rows = self.rows()
        rows[5] = {**rows[5], "injected_faults": []}
        self.assertIn("injected_faults", self.refused(rows))

    def test_two_runs(self):
        rows = self.rows()
        rows[3] = {**rows[3], "run_id": "other"}
        self.assertIn("2 runs", self.refused(rows))


class TestGuards(unittest.TestCase):
    def test_refuses_to_write_into_the_sealed_folders(self):
        with self.assertRaises(ValueError):
            replay(find_project("amr-fulfilment-cell"), {}, Path("data/fulfilment"), SMALL,
                   Path("data/fulfilment") / f"{SMALL}.readings.jsonl", COMPARISON, Path("data/fulfilment/x"))

    def test_readings_source_needs_a_field_source(self):
        with self.assertRaises(ValueError):
            run_assurance(Scenario.from_dict(json.loads(Path("scenarios/amr_faults_showcase.json").read_text())), {},
                          readings_source={"label": "x"})


if __name__ == "__main__":
    unittest.main()
