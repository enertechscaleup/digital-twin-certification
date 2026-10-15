"""The two-source path: the plant's measurements and the twin's predictions as two separate feeds,
validated separately and joined per tick into the engine's ingested readings.

Additive: the single-message path (ingest/pipeline.py, schema dtc-reading/1) is not changed; this
module only imports its constants and helpers. Standard library only, so the Dataflow workers (no
internet access) need nothing extra.

    plant message (dtc-plant/1): every channel; physical_value; no predicted_value, no twin_version
    twin message  (dtc-twin/1):  output channels only; predicted_value and twin_version; no physical_value

The join rebuilds each 13-field reading exactly (engine/readings.py: ALLOWED_FIELDS order). A tick
missing either side, or with conflicting twin versions, is incomplete: nothing is guessed, and the
engine's loader refuses an incomplete run.
"""

from __future__ import annotations

import hashlib
import json
import math

from pipeline import ALLOWED_FIELDS, TIMESTAMP, _strict_constant

SIDES = ("plant", "twin")
SCHEMAS = {"plant": "dtc-plant/1", "twin": "dtc-twin/1"}
PLANT_FIELDS = ("run_id", "kind", "tick", "timestamp", "operational_hours", "twin_id", "channel_id", "direction", "unit",
                "physical_value", "test_point")
TWIN_FIELDS = ("run_id", "kind", "tick", "timestamp", "operational_hours", "twin_id", "twin_version", "channel_id",
               "direction", "unit", "predicted_value", "test_point")
FIELDS = {"plant": PLANT_FIELDS, "twin": TWIN_FIELDS}
VALUE = {"plant": "physical_value", "twin": "predicted_value"}
REQUIRED_ATTRIBUTES = ("sender", "replay_id", "reading_key", "content_sha256")
# In the order classify_side() checks them; conflicting_duplicate is found per tick, across messages.
REJECT_REASONS = (
    ("bad_attributes", "Attributes missing or wrong: schema, sender, replay_id, reading_key, content_sha256, or a reading_key that does not match the reading"),
    ("wrong_side", "The schema or the sender is the other side's, or a twin message is on an input channel"),
    ("content_hash_mismatch", "content_sha256 is not the SHA-256 of the message data"),
    ("malformed_json", "The data is not a JSON object, or uses NaN / Infinity"),
    ("forbidden_field", "A field outside this side's fields"),
    ("missing_field", "One of this side's fields is missing"),
    ("wrong_kind", "kind is not \"field\", or test_point is not null"),
    ("bad_type", "A field has the wrong type"),
    ("unknown_channel", "The twin and channel are not in the project, or the direction or unit differs"),
    ("conflicting_duplicate", "Two messages with the same reading_key and different content (checked across messages, per tick)"),
)


def reading_key(replay_id: str, sender: str, run_id: str, tick, twin_id: str, channel_id: str) -> str:
    """The idempotency key of one side's message; the sender is part of it, so the two sides never collide."""
    return hashlib.sha256(f"{replay_id}|{sender}|{run_id}|{tick}|{twin_id}|{channel_id}".encode()).hexdigest()[:32]


def split_reading(reading: dict) -> tuple[dict, dict | None]:
    """A 13-field ingested reading -> (plant message data, twin message data or None for an input channel)."""
    plant = {k: reading[k] for k in PLANT_FIELDS}
    twin = {k: reading[k] for k in TWIN_FIELDS} if reading["direction"] == "output" else None
    return plant, twin


def _number_or_null(v) -> bool:
    return v is None or (isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v))


def classify_side(side: str, data: bytes, attributes: dict, channels: dict) -> tuple[str, dict | str]:
    """Like ingest/pipeline.py: classify, for one side. Returns ("control", {}), ("valid", item) or ("invalid", reason).
    ``channels``: (twin_id, channel_id) -> (direction, unit)."""
    if attributes.get("kind") == "control":
        return "control", {}
    if attributes.get("schema") not in SCHEMAS.values() or not all(attributes.get(k) for k in REQUIRED_ATTRIBUTES):
        return "invalid", "bad_attributes"
    if attributes["schema"] != SCHEMAS[side] or attributes["sender"] != side:
        return "invalid", "wrong_side"
    if hashlib.sha256(data).hexdigest() != attributes["content_sha256"]:
        return "invalid", "content_hash_mismatch"
    try:
        r = json.loads(data.decode("utf-8"), parse_constant=_strict_constant)
    except (UnicodeDecodeError, ValueError):
        return "invalid", "malformed_json"
    if not isinstance(r, dict):
        return "invalid", "malformed_json"
    fields = FIELDS[side]
    if set(r) - set(fields):
        return "invalid", "forbidden_field"
    if set(fields) - set(r):
        return "invalid", "missing_field"
    if r["kind"] != "field" or r["test_point"] is not None:
        return "invalid", "wrong_kind"
    texts = ("run_id", "twin_id", "channel_id", "direction", "unit") + (("twin_version",) if side == "twin" else ())
    if not (isinstance(r["tick"], int) and not isinstance(r["tick"], bool) and r["tick"] >= 0
            and isinstance(r["timestamp"], str) and TIMESTAMP.match(r["timestamp"])
            and all(isinstance(r[k], str) and r[k] for k in texts)
            and _number_or_null(r["operational_hours"]) and r["operational_hours"] is not None
            and _number_or_null(r[VALUE[side]])):
        return "invalid", "bad_type"
    if channels.get((r["twin_id"], r["channel_id"])) != (r["direction"], r["unit"]):
        return "invalid", "unknown_channel"
    if side == "twin" and r["direction"] != "output":
        return "invalid", "wrong_side"
    if attributes["reading_key"] != reading_key(attributes["replay_id"], side, r["run_id"], r["tick"], r["twin_id"], r["channel_id"]):
        return "invalid", "bad_attributes"
    return "valid", {"side": side, "reading": r, "data": data, "attributes": dict(attributes),
                     "key": attributes["reading_key"], "content": attributes["content_sha256"]}


def dedupe(items: list[dict]) -> tuple[dict, int, list[dict]]:
    """One side's items of one tick -> ({(twin_id, channel_id): row}, identical duplicates dropped, conflicting items).
    A key seen with two different contents is never resolved: every copy is a conflict."""
    by_key: dict[str, list[dict]] = {}
    for it in items:
        by_key.setdefault(it["key"], []).append(it)
    rows, dropped, conflicts = {}, 0, []
    for copies in by_key.values():
        if len({c["content"] for c in copies}) > 1:
            conflicts.extend(copies)
        else:
            r = copies[0]["reading"]
            rows[(r["twin_id"], r["channel_id"])] = r
            dropped += len(copies) - 1
    return rows, dropped, conflicts


def join_tick(plant: dict, twin: dict, order: list[tuple[str, str, str]]) -> tuple[list[dict] | None, list[str]]:
    """Both sides of one tick (from dedupe) -> (the tick's readings in canonical order, or None; problems).
    ``order``: [(twin_id, channel_id, direction)] for the project, in canonical order."""
    problems = []
    versions: dict[str, set] = {}
    for (twin_id, _), w in twin.items():
        versions.setdefault(twin_id, set()).add(w["twin_version"])
    readings = []
    for twin_id, channel_id, direction in order:
        p = plant.get((twin_id, channel_id))
        if p is None:
            problems.append(f"plant missing: {twin_id}/{channel_id}")
            continue
        vs = versions.get(twin_id, set())
        if len(vs) != 1:
            problems.append(f"twin_version {'missing' if not vs else 'conflict ' + str(sorted(vs))}: {twin_id}")
            continue
        predicted = None
        if direction == "output":
            w = twin.get((twin_id, channel_id))
            if w is None:
                problems.append(f"twin missing: {twin_id}/{channel_id}")
                continue
            if any(w[k] != p[k] for k in ("run_id", "tick", "timestamp", "operational_hours", "direction", "unit")):
                problems.append(f"sides disagree: {twin_id}/{channel_id}")
                continue
            predicted = w["predicted_value"]
        readings.append({"run_id": p["run_id"], "kind": p["kind"], "tick": p["tick"], "timestamp": p["timestamp"],
                         "operational_hours": p["operational_hours"], "twin_id": twin_id, "twin_version": next(iter(vs)),
                         "channel_id": channel_id, "direction": p["direction"], "unit": p["unit"],
                         "physical_value": p["physical_value"], "predicted_value": predicted, "test_point": None})
    extra = (set(plant) | set(twin)) - {(t, c) for t, c, _ in order}
    if extra:
        problems.append(f"unknown channels: {sorted(extra)}")
    if problems:
        return None, sorted(set(problems))
    assert all(tuple(r) == tuple(ALLOWED_FIELDS) for r in readings)
    return readings, []
