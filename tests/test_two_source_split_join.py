"""Offline proof of the two-source path (no cloud): every sealed run, split into a plant feed and a twin
feed, shuffled and duplicated, validated per side, de-duplicated and joined per tick, gives back the
sealed readings byte for byte, and the engine reaches the pinned head. A missing side, a conflicting
copy or conflicting twin versions leave the tick incomplete, and the engine refuses."""

import hashlib
import json
import random
import sys
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "ingest")]
import two_source as ts  # noqa: E402
from engine.registry import load_registry  # noqa: E402
from engine.replay import COMPARISON, INGESTION, ReplayRefused, compare, load_readings, replay  # noqa: E402
from projects import find_project  # noqa: E402
from vendor.endpoint import simulated_vendors  # noqa: E402

PINS = {r["run"]: r for r in json.loads((ROOT / "app/config/runs.json").read_text())["runs"]}
SEALED = {"oil-gas-compressor-train": ROOT / "data/lineage", "amr-fulfilment-cell": ROOT / "data/fulfilment"}
HAVE_DATA = all((SEALED[p["project_id"]] / f"{r}.readings.jsonl").exists() for r, p in PINS.items())
SMALL = "assurance-amr_faults_showcase-seed42"


def project_spec(project):
    reg = load_registry(project)
    order = [(p.operational_twin_id, c.channel_id, c.direction) for p in reg.products.values() for c in p.channels]
    channels = {(p.operational_twin_id, c.channel_id): (c.direction, c.unit) for p in reg.products.values() for c in p.channels}
    return order, channels


def messages(rows, replay_id="offline"):
    """Each sealed reading -> its plant message and (outputs) its twin message: (side, data bytes, attributes)."""
    out = []
    for r in rows:
        for side, data in zip(ts.SIDES, ts.split_reading(r)):
            if data is None:
                continue
            raw = json.dumps(data).encode()
            out.append((side, raw, {"schema": ts.SCHEMAS[side], "sender": side, "source": "replay", "replay_id": replay_id,
                                    "event_ts": data["timestamp"], "content_sha256": hashlib.sha256(raw).hexdigest(),
                                    "reading_key": ts.reading_key(replay_id, side, data["run_id"], data["tick"], data["twin_id"], data["channel_id"])}))
    return out


def ingest_two_sources(msgs, order, channels):
    """What the two-source pipeline does: classify per side, group per tick, de-duplicate per side, join."""
    by_tick = defaultdict(lambda: {"plant": [], "twin": []})
    rejected = []
    for side, data, attrs in msgs:
        kind, item = ts.classify_side(side, data, attrs, channels)
        if kind == "valid":
            by_tick[(item["reading"]["run_id"], item["reading"]["tick"])][side].append(item)
        elif kind == "invalid":
            rejected.append((side, item))
    joined, incomplete = [], {}
    for (run_id, tick) in sorted(by_tick, key=lambda k: k[1]):
        sides = by_tick[(run_id, tick)]
        plant, _, plant_conflicts = ts.dedupe(sides["plant"])
        twin, _, twin_conflicts = ts.dedupe(sides["twin"])
        rejected += [("plant", "conflicting_duplicate")] * len(plant_conflicts) + [("twin", "conflicting_duplicate")] * len(twin_conflicts)
        readings, problems = ts.join_tick(plant, twin, order)
        if readings is None:
            incomplete[tick] = problems
        else:
            joined.extend(readings)
    return joined, incomplete, rejected


def write(rows, path: Path) -> Path:
    path.write_bytes("".join(json.dumps(r) + "\n" for r in rows).encode())
    return path


@unittest.skipUnless(HAVE_DATA, "the sealed runs (git-ignored data/) are not on this machine")
class TestRoundTripAllSixRuns(unittest.TestCase):
    def test_split_shuffle_duplicate_join_is_byte_identical_and_reaches_the_pin(self):
        for run, pin in PINS.items():
            d = SEALED[pin["project_id"]]
            sealed_bytes = (d / f"{run}.readings.jsonl").read_bytes()
            rows = [json.loads(l) for l in sealed_bytes.decode().splitlines()]
            project = find_project(pin["project_id"])
            order, channels = project_spec(project)
            msgs = messages(rows)
            rng = random.Random(11)
            msgs = msgs + rng.sample(msgs, len(msgs) // 20)   # ~5% identical duplicates, both sides
            msgs.sort(key=lambda m: json.loads(m[1])["tick"] + rng.uniform(-3, 3))  # out of order within +/- 3 ticks
            with self.subTest(run=run), tempfile.TemporaryDirectory() as t:
                joined, incomplete, rejected = ingest_two_sources(msgs, order, channels)
                self.assertEqual((incomplete, rejected), ({}, []))
                path = write(joined, Path(t) / "joined.jsonl")
                self.assertEqual(path.read_bytes(), sealed_bytes)
                result, _ = replay(project, simulated_vendors(project), d, run, path, COMPARISON, Path(t) / "c")
                self.assertEqual(result.ledger.head_hash, pin["core_ledger_head_hash"])
                labelled, _ = replay(project, simulated_vendors(project), d, run, path, INGESTION, Path(t) / "i",
                                     actual_commit="0" * 40, ingestion={"replay_id": "offline", "path": "two-source"})
                report = compare(labelled, d, run, pin["core_ledger_head_hash"], "0" * 40)
                self.assertTrue(report["level1_same_decisions"])
                self.assertFalse(report["level2_same_head"])


@unittest.skipUnless(HAVE_DATA, "the sealed runs (git-ignored data/) are not on this machine")
class TestIncompleteTicksAreRefused(unittest.TestCase):
    def setUp(self):
        d = SEALED["amr-fulfilment-cell"]
        self.rows = [json.loads(l) for l in (d / f"{SMALL}.readings.jsonl").read_text().splitlines()]
        self.project = find_project("amr-fulfilment-cell")
        self.order, self.channels = project_spec(self.project)
        self.msgs = messages(self.rows)

    def drop(self, side, tick, nth=0):
        hits = [i for i, (s, data, _) in enumerate(self.msgs) if s == side and json.loads(data)["tick"] == tick]
        return [m for i, m in enumerate(self.msgs) if i != hits[nth]]

    def refused(self, msgs):
        joined, incomplete, rejected = ingest_two_sources(msgs, self.order, self.channels)
        with tempfile.TemporaryDirectory() as t, self.assertRaises(ReplayRefused):
            load_readings(write(joined, Path(t) / "j.jsonl"), self.project)
        return incomplete, rejected

    def test_plant_side_missing(self):
        incomplete, _ = self.refused(self.drop("plant", 20))
        self.assertEqual(list(incomplete), [20])
        self.assertTrue(incomplete[20][0].startswith("plant missing"))

    def test_twin_side_missing(self):
        incomplete, _ = self.refused(self.drop("twin", 30))
        self.assertEqual(list(incomplete), [30])
        self.assertTrue(incomplete[30][0].startswith("twin missing"))

    def test_conflicting_copy_on_each_side(self):
        for side in ts.SIDES:
            with self.subTest(side=side):
                i = next(i for i, (s, data, _) in enumerate(self.msgs) if s == side and json.loads(data)["tick"] == 12
                         and isinstance(json.loads(data)[ts.VALUE[side]], float))
                s, data, attrs = self.msgs[i]
                row = json.loads(data)
                row[ts.VALUE[side]] = round(row[ts.VALUE[side]] * 1.01, 4)
                raw = json.dumps(row).encode()
                incomplete, rejected = self.refused(self.msgs + [(s, raw, {**attrs, "content_sha256": hashlib.sha256(raw).hexdigest()})])
                self.assertEqual(list(incomplete), [12])
                self.assertEqual(rejected, [(side, "conflicting_duplicate")] * 2)

    def test_twin_versions_that_disagree(self):
        i = next(i for i, (s, data, _) in enumerate(self.msgs) if s == "twin" and json.loads(data)["tick"] == 5)
        s, data, attrs = self.msgs[i]
        row = {**json.loads(data), "twin_version": "9.9.9"}
        raw = json.dumps(row).encode()
        msgs = list(self.msgs)
        msgs[i] = (s, raw, {**attrs, "content_sha256": hashlib.sha256(raw).hexdigest()})
        incomplete, _ = self.refused(msgs)
        self.assertIn("twin_version conflict", incomplete[5][0])


class TestValidatorPerSide(unittest.TestCase):
    project = find_project("amr-fulfilment-cell")

    def setUp(self):
        self.order, self.channels = project_spec(self.project)
        out = next(c for c in self.order if c[2] == "output")
        inp = next(c for c in self.order if c[2] == "input")
        base = {"run_id": "field-x", "kind": "field", "tick": 3, "timestamp": "2026-10-01T00:00:06Z", "operational_hours": 72,
                "twin_version": "1.0.0", "physical_value": 50.0, "predicted_value": 51.0, "test_point": None}
        unit = lambda t, c: self.channels[(t, c)][1]
        self.out = {**base, "twin_id": out[0], "channel_id": out[1], "direction": "output", "unit": unit(out[0], out[1])}
        self.inp = {**base, "twin_id": inp[0], "channel_id": inp[1], "direction": "input", "unit": unit(inp[0], inp[1]), "predicted_value": None}

    def msg(self, side, data: dict, **attr):
        raw = json.dumps(data).encode()
        a = {"schema": ts.SCHEMAS[side], "sender": side, "replay_id": "r", "content_sha256": hashlib.sha256(raw).hexdigest(),
             "reading_key": ts.reading_key("r", side, data.get("run_id"), data.get("tick"), data.get("twin_id"), data.get("channel_id"))}
        a.update(attr)
        return raw, {k: v for k, v in a.items() if v is not None}

    def verdict(self, side, data, **attr):
        kind, r = ts.classify_side(side, *self.msg(side, data, **attr), self.channels)
        return r if kind == "invalid" else kind

    def test_valid_each_side(self):
        plant, twin = ts.split_reading(self.out)
        self.assertEqual(self.verdict("plant", plant), "valid")
        self.assertEqual(self.verdict("twin", twin), "valid")
        self.assertEqual(self.verdict("plant", ts.split_reading(self.inp)[0]), "valid")
        self.assertIsNone(ts.split_reading(self.inp)[1])

    def test_every_reject_reason_each_side(self):
        for side in ts.SIDES:
            good = ts.split_reading(self.out)[ts.SIDES.index(side)]
            other = ts.SIDES[1 - ts.SIDES.index(side)]
            cases = [
                ("bad_attributes", good, {"replay_id": None}),
                ("bad_attributes", good, {"reading_key": "0" * 32}),
                ("wrong_side", good, {"sender": other}),
                ("wrong_side", good, {"schema": ts.SCHEMAS[other]}),
                ("content_hash_mismatch", good, {"content_sha256": "0" * 64}),
                ("forbidden_field", {**good, ts.VALUE[other]: 1.0}, {}),
                ("missing_field", {k: v for k, v in good.items() if k != "unit"}, {}),
                ("wrong_kind", {**good, "kind": "bench"}, {}),
                ("bad_type", {**good, "tick": "3"}, {}),
                ("unknown_channel", {**good, "channel_id": "nope"}, {}),
            ]
            for reason, data, attr in cases:
                with self.subTest(side=side, reason=reason, attr=attr):
                    self.assertEqual(self.verdict(side, data, **attr), reason)
            raw = b'{"run_id": "trunc'
            a = {"schema": ts.SCHEMAS[side], "sender": side, "replay_id": "r", "reading_key": "k", "content_sha256": hashlib.sha256(raw).hexdigest()}
            self.assertEqual(ts.classify_side(side, raw, a, self.channels), ("invalid", "malformed_json"))

    def test_twin_message_on_an_input_channel(self):
        twin_on_input = {k: self.inp[k] for k in ts.TWIN_FIELDS}
        self.assertEqual(self.verdict("twin", twin_on_input), "wrong_side")

    def test_publisher_invalid_messages_get_their_reason(self):
        from publisher_two_source import invalid_messages
        plant_good, twin_good = ts.split_reading(self.out)
        input_twin = {k: self.inp[k] for k in ts.TWIN_FIELDS}
        for side, good in (("plant", plant_good), ("twin", twin_good)):
            cases = invalid_messages(side, good, input_twin, "r")
            for reason, data, attrs in cases:
                with self.subTest(side=side, reason=reason):
                    self.assertEqual(ts.classify_side(side, data, attrs, self.channels), ("invalid", reason))
            single_message_codes = {c for c, _ in ts.REJECT_REASONS} - {"conflicting_duplicate"}
            self.assertEqual({r for r, _, _ in cases}, single_message_codes)

    def test_codes_listed(self):
        self.assertEqual([c for c, _ in ts.REJECT_REASONS][-1], "conflicting_duplicate")
        self.assertIn("wrong_side", [c for c, _ in ts.REJECT_REASONS])


if __name__ == "__main__":
    unittest.main()
