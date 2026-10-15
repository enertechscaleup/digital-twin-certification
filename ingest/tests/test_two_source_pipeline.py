"""Offline test of the two-source pipeline on Beam's DirectRunner: per-side raw copies, validation and
dead letters, de-duplication, the per-tick join, incomplete ticks, and the three BigQuery outputs.
Run with the ingest environment: .venv-ingest/bin/python -m unittest discover -s ingest/tests"""

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

import pipeline as single  # noqa: E402
import pipeline_two_source as pts  # noqa: E402
import two_source as ts  # noqa: E402

SPEC = [["a-op", "x", "input", "u"], ["a-op", "y", "output", "v"], ["b-op", "z", "output", "w"]]


def reading(tick, twin, ch, direction, unit, version="1.0.0"):
    return {"run_id": "field-t", "kind": "field", "tick": tick, "timestamp": f"2026-10-01T00:00:{2 * tick:02d}Z",
            "operational_hours": 24 * tick, "twin_id": twin, "twin_version": version, "channel_id": ch, "direction": direction,
            "unit": unit, "physical_value": 10.0 + tick, "predicted_value": 10.5 + tick if direction == "output" else None,
            "test_point": None}


def msg(side, data: dict, replay="r1", **attr):
    raw = json.dumps(data).encode()
    a = {"schema": ts.SCHEMAS[side], "sender": side, "source": "replay", "replay_id": replay, "event_ts": data["timestamp"],
         "content_sha256": hashlib.sha256(raw).hexdigest(),
         "reading_key": ts.reading_key(replay, side, data["run_id"], data["tick"], data["twin_id"], data["channel_id"])}
    a.update(attr)
    return PubsubMessage(raw, a)


class TestTwoSourcePipeline(unittest.TestCase):
    def test_join_incomplete_dead_letters_and_tables(self):
        rows = [reading(t, *c) for t in range(3) for c in SPEC]
        plant, twin = [], []
        for r in rows:
            p, w = ts.split_reading(r)
            if not (r["tick"] == 1 and r["channel_id"] == "x"):        # tick 1: one plant message missing
                plant.append(msg("plant", p))
            if w is not None:
                twin.append(msg("twin", w))
        plant.append(plant[0])                                          # an identical duplicate (plant)
        twin.append(twin[0])                                            # an identical duplicate (twin)
        bad_plant = msg("plant", ts.split_reading(rows[0])[0], sender="twin")   # wrong_side
        bad_twin = msg("twin", ts.split_reading(rows[1])[1], content_sha256="0" * 64)  # content_hash_mismatch
        with tempfile.TemporaryDirectory() as t:
            out = Path(t)
            with TestPipeline() as p:
                pl = p | "plant" >> beam.Create(plant + [bad_plant])
                tw = p | "twin" >> beam.Create(twin + [bad_twin])
                tables, dlq = {}, {}

                def write_bq(table, rs):
                    assert_that(rs | f"k_{table}" >> beam.Map(lambda r: (r["tick"], r["channel_id"])), equal_to(EXPECTED[table]), label=f"bq_{table}")

                def write_dlq(side, ms):
                    assert_that(ms | f"r_{side}" >> beam.Map(lambda m: m.attributes["reject_reason"]), equal_to(EXPECTED[f"dlq_{side}"]), label=f"dlq_{side}")

                EXPECTED = {
                    "plant_validated": [(r["tick"], r["channel_id"]) for r in rows if not (r["tick"] == 1 and r["channel_id"] == "x")],
                    "twin_validated": [(r["tick"], r["channel_id"]) for r in rows if r["direction"] == "output"],
                    "joined_readings": [(r["tick"], r["channel_id"]) for r in rows if r["tick"] != 1],
                    "dlq_plant": ["wrong_side"], "dlq_twin": ["content_hash_mismatch"],
                }
                pts.build(p, pl, tw, channels_spec=SPEC, out_prefix=f"{out}/", write_bq=write_bq, write_dlq=write_dlq)
            joined = out / "joined" / "r1" / "field-t"
            self.assertEqual(sorted(f.name for f in joined.iterdir()),
                             ["tick-0000.p0000.jsonl", "tick-0001.p0000.incomplete.json", "tick-0002.p0000.jsonl"])
            self.assertEqual((joined / "tick-0002.p0000.jsonl").read_bytes(), single.jsonl([r for r in rows if r["tick"] == 2]))
            self.assertIn("plant missing: a-op/x", (joined / "tick-0001.p0000.incomplete.json").read_text())
            raw = {side: sum(len(f.read_text().splitlines()) for f in (out / "raw2" / side / "r1").glob("*.jsonl")) for side in ts.SIDES}
            self.assertEqual(raw, {"plant": len(plant) + 1, "twin": len(twin) + 1})
            self.assertTrue((out / "validated2" / "plant" / "r1" / "field-t" / "tick-0000.p0000.jsonl").exists())

    def test_local_modules_ship_by_value(self):
        from apache_beam.internal.cloudpickle import cloudpickle
        pts.ship_local_modules()
        blob = cloudpickle.dumps(ts.join_tick)
        self.assertIn(b"join_tick", blob)
        self.assertNotIn(b"two_source\nmodule", blob)


if __name__ == "__main__":
    unittest.main()
