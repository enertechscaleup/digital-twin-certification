"""Offline tests of the ingestion pipeline (no cloud): the shape checks, the per-tick assembly and
the whole pipeline on Beam's DirectRunner. Run with the ingest environment:

    .venv-ingest/bin/python -m unittest discover -s ingest/tests -t .
"""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "ingest"), str(ROOT)]

import apache_beam as beam  # noqa: E402
from apache_beam.io.gcp.pubsub import PubsubMessage  # noqa: E402
from apache_beam.testing.test_pipeline import TestPipeline  # noqa: E402
from apache_beam.testing.util import assert_that, equal_to  # noqa: E402

import pipeline as pl  # noqa: E402
from publisher import attributes, invalid_messages  # noqa: E402

CHANNELS = [["amr1-op-001", "task_rate", "input", "tasks/h"], ["amr1-op-001", "deliveries", "output", "totes/h"]]
SPEC = {(t, c): (d, u) for t, c, d, u in CHANNELS}
ORDER = [(t, c) for t, c, _, _ in CHANNELS]


def row(tick, channel="task_rate", value=50.0):
    t, c, d, u = next(x for x in CHANNELS if x[1] == channel)
    return {"run_id": "field-x", "kind": "field", "tick": tick, "timestamp": f"2026-10-01T00:00:{2 * tick:02d}Z",
            "operational_hours": 24 * tick, "twin_id": t, "twin_version": "1.0.0", "channel_id": c, "direction": d,
            "unit": u, "physical_value": value, "predicted_value": None if d == "input" else 51.0, "test_point": None}


def message(r, replay="r1", data=None):
    data = data or json.dumps(r).encode()
    return PubsubMessage(data, attributes(data, replay, r))


class TestShape(unittest.TestCase):
    def test_field_list_matches_the_engine(self):
        from engine.readings import ALLOWED_FIELDS
        self.assertEqual(pl.ALLOWED_FIELDS, ALLOWED_FIELDS)

    def test_valid_reading_passes_unchanged(self):
        r = row(3)
        kind, item = pl.classify(json.dumps(r).encode(), message(r).attributes, SPEC)
        self.assertEqual(kind, "valid")
        self.assertEqual(item["reading"], r)

    def test_values_are_never_judged(self):
        # A dropout, a spike and an out-of-range value are the engine's to classify.
        for v in (None, 1e6, -5.0):
            r = row(3, value=v)
            self.assertEqual(pl.classify(json.dumps(r).encode(), message(r).attributes, SPEC)[0], "valid")

    def test_every_reject_reason(self):
        for reason, data, attrs in invalid_messages(row(3), "r1"):
            with self.subTest(reason=reason):
                self.assertEqual(pl.classify(data, attrs, {**SPEC}), ("invalid", reason))

    def test_non_standard_json_token(self):
        data = json.dumps(row(3)).replace("50.0", "NaN").encode()
        self.assertEqual(pl.classify(data, attributes(data, "r1", row(3)), SPEC), ("invalid", "malformed_json"))

    def test_control_message(self):
        self.assertEqual(pl.classify(b"{}", {"kind": "control"}, SPEC), ("control", {}))


class TestAssembleTick(unittest.TestCase):
    def items(self, *rows):
        return [pl.classify(json.dumps(r).encode(), message(r).attributes, SPEC)[1] for r in rows]

    def test_order_and_identical_duplicates(self):
        a, b = row(1, "task_rate"), row(1, "deliveries")
        rows, dropped, conflicts = pl.assemble_tick(self.items(b, a, b), ORDER)
        self.assertEqual((rows, dropped, conflicts), ([a, b], 1, []))

    def test_conflicting_duplicate_is_never_resolved(self):
        a, b, b2 = row(1, "task_rate"), row(1, "deliveries"), row(1, "deliveries", value=60.0)
        rows, dropped, conflicts = pl.assemble_tick(self.items(a, b, b2), ORDER)
        self.assertEqual(rows, [a])  # the tick is now incomplete: the engine will refuse it
        self.assertEqual(len(conflicts), 2)


class TestDirectRunner(unittest.TestCase):
    def test_whole_pipeline(self):
        good = [row(t, c) for t in range(3) for c in ("task_rate", "deliveries")]
        msgs = [message(r) for r in reversed(good)] + [message(good[0])]
        msgs += [PubsubMessage(d, a) for _, d, a in invalid_messages(good[0], "r1")]
        with tempfile.TemporaryDirectory() as t:
            out = Path(t)
            bq, dlq = [], []
            with TestPipeline() as p:
                ms = p | beam.Create(msgs)

                def write_bq(rows):
                    assert_that(rows | beam.Map(lambda r: (r["tick"], r["channel_id"])),
                                equal_to([(r["tick"], r["channel_id"]) for r in good]), label="bq")

                def write_dlq(rejected):
                    assert_that(rejected | beam.Map(lambda m: m.attributes["reject_reason"]),
                                equal_to([r for r, _, _ in invalid_messages(good[0], "r1")]), label="dlq")

                pl.build(p, ms, channels_spec=CHANNELS, out_prefix=f"{out}/", write_bq=write_bq, write_dlq=write_dlq)
            files = sorted((out / "validated" / "r1" / "field-x").glob("tick-*.jsonl"))
            self.assertEqual([f.name for f in files], [f"tick-000{i}.p0000.jsonl" for i in range(3)])
            self.assertEqual(files[1].read_bytes(), pl.jsonl([good[2], good[3]]))
            raw = (out / "raw" / "r1").glob("chunk-*.jsonl")
            self.assertEqual(sum(len(f.read_text().splitlines()) for f in raw), len(msgs))


if __name__ == "__main__":
    unittest.main()
