"""Replays a sealed synthetic run as two feeds: plant messages (dtc-plant/1) to the plant topic and twin
messages (dtc-twin/1) to the twin topic, each through its own publish-only service account. Both feeds
are cut from the same sealed readings, so they share the run's tick index; nothing aligns two clocks.

Test options, each per side: shuffle within a few ticks, repeat a fraction of messages, deliver one
message late, never send one message, inject one malformed message per reject reason, or republish
one message with changed content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import two_source as ts  # noqa: E402


def attributes(side: str, data: bytes, replay_id: str, row: dict) -> dict:
    return {"schema": ts.SCHEMAS[side], "sender": side, "source": "replay", "replay_id": replay_id,
            "event_ts": str(row.get("timestamp")), "content_sha256": hashlib.sha256(data).hexdigest(),
            "reading_key": ts.reading_key(replay_id, side, str(row.get("run_id")), row.get("tick"), str(row.get("twin_id")), str(row.get("channel_id")))}


def invalid_messages(side: str, good: dict, input_twin: dict | None, replay_id: str) -> list[tuple[str, bytes, dict]]:
    """One message for each reject reason of this side (ingest/two_source.py: classify_side)."""
    other = ts.SIDES[1 - ts.SIDES.index(side)]
    out = []

    def add(reason, row, **over):
        data = json.dumps(row).encode() if isinstance(row, dict) else row
        a = attributes(side, data, replay_id, row if isinstance(row, dict) else good)
        a.update(over)
        out.append((reason, data, {k: v for k, v in a.items() if v is not None}))
    add("bad_attributes", good, replay_id=None)
    add("wrong_side", good, sender=other)
    add("content_hash_mismatch", good, content_sha256="0" * 64)
    add("malformed_json", b'{"run_id": "truncated')
    add("forbidden_field", {**good, ts.VALUE[other]: 1.0})
    add("missing_field", {k: v for k, v in good.items() if k != "unit"})
    add("wrong_kind", {**good, "kind": "bench"})
    add("bad_type", {**good, "tick": str(good["tick"])})
    add("unknown_channel", {**good, "channel_id": "no_such_channel"})
    if side == "twin" and input_twin is not None:
        add("wrong_side", input_twin)  # a twin message on an input channel
    return out


def side_tick(spec: str | None):
    if not spec:
        return None
    side, tick = spec.split(":")
    return side, int(tick)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--readings", type=Path, required=True)
    ap.add_argument("--plant-topic", required=True)
    ap.add_argument("--twin-topic", required=True)
    ap.add_argument("--replay-id", required=True)
    ap.add_argument("--impersonate-plant")
    ap.add_argument("--impersonate-twin")
    ap.add_argument("--rate", type=float, default=50.0, help="messages per second, both feeds together")
    ap.add_argument("--shuffle-ticks", type=int, default=0)
    ap.add_argument("--duplicate-fraction", type=float, default=0.0)
    ap.add_argument("--late", help="SIDE:TICK  hold one message of this side and tick back ...")
    ap.add_argument("--late-delay-s", type=float, default=240.0, help="... and publish it this long after 3 more ticks")
    ap.add_argument("--missing", action="append", default=[], help="SIDE:TICK  never send one message of this side and tick")
    ap.add_argument("--invalid", action="store_true", help="one malformed message per reject reason, on each side")
    ap.add_argument("--conflict", action="append", default=[], help="SIDE:TICK  republish one message with changed content")
    ap.add_argument("--log", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    import google.auth
    from google.auth import impersonated_credentials
    from google.cloud import pubsub_v1

    base, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    clients, topics = {}, {"plant": args.plant_topic, "twin": args.twin_topic}
    for side, sa in (("plant", args.impersonate_plant), ("twin", args.impersonate_twin)):
        creds = impersonated_credentials.Credentials(source_credentials=base, target_principal=sa,
                                                     target_scopes=["https://www.googleapis.com/auth/pubsub"]) if sa else base
        clients[side] = pubsub_v1.PublisherClient(credentials=creds)
    rng = random.Random(args.seed)
    log = {"replay_id": args.replay_id, "readings_file": args.readings.name,
           "readings_file_sha256": hashlib.sha256(args.readings.read_bytes()).hexdigest(),
           "shared_tick_index": "both feeds are cut from the same sealed readings", "published": {"plant": {}, "twin": {}}, "messages": []}
    pending = []

    def publish(side, category, data, attrs):
        pending.append((side, category, attrs.get("reading_key"), clients[side].publish(topics[side], data, **attrs)))
        log["published"][side][category] = log["published"][side].get(category, 0) + 1
        time.sleep(1.0 / args.rate)

    rows = [json.loads(l) for l in args.readings.read_text(encoding="utf-8").splitlines() if l.strip()]
    msgs = []
    for r in rows:
        for side, data in zip(ts.SIDES, ts.split_reading(r)):
            if data is not None:
                raw = json.dumps(data).encode()
                msgs.append((side, data, raw))
    if args.shuffle_ticks:
        msgs.sort(key=lambda m: m[1]["tick"] + rng.uniform(-args.shuffle_ticks, args.shuffle_ticks))

    def take(spec):
        side, tick = spec
        m = next(m for m in msgs if m[0] == side and m[1]["tick"] == tick)
        msgs.remove(m)
        return m
    missing = [take(side_tick(s)) for s in args.missing]
    log["missing"] = [{"side": s, "tick": d["tick"], "twin_id": d["twin_id"], "channel_id": d["channel_id"]} for s, d, _ in missing]
    late = take(side_tick(args.late)) if args.late else None
    late_sent = False
    for side, data, raw in msgs:
        publish(side, "reading", raw, attributes(side, raw, args.replay_id, data))
        if args.duplicate_fraction and rng.random() < args.duplicate_fraction:
            publish(side, "identical_duplicate", raw, attributes(side, raw, args.replay_id, data))
        if late and not late_sent and data["tick"] >= late[1]["tick"] + 3:
            for f in pending:
                f[3].result()
            time.sleep(args.late_delay_s)
            publish(late[0], "reading_late", late[2], attributes(late[0], late[2], args.replay_id, late[1]))
            log["late"] = {"side": late[0], "tick": late[1]["tick"], "twin_id": late[1]["twin_id"], "channel_id": late[1]["channel_id"],
                           "delay_s": args.late_delay_s}
            late_sent = True
    for spec in args.conflict:
        side, tick = side_tick(spec)
        _, data, _ = next(m for m in msgs if m[0] == side and m[1]["tick"] == tick and isinstance(m[1][ts.VALUE[side]], float))
        changed = {**data, ts.VALUE[side]: round(data[ts.VALUE[side]] * 1.01, 4)}
        raw = json.dumps(changed).encode()
        publish(side, "conflicting_duplicate", raw, attributes(side, raw, args.replay_id, changed))
        log.setdefault("conflict", []).append({"side": side, "tick": tick, "twin_id": data["twin_id"], "channel_id": data["channel_id"]})
    if args.invalid:
        out_row = next(r for r in rows if r["direction"] == "output")
        in_row = next(r for r in rows if r["direction"] == "input")
        plant_good, twin_good = ts.split_reading(out_row)
        input_twin = {k: in_row[k] for k in ts.TWIN_FIELDS}
        for side, good in (("plant", plant_good), ("twin", twin_good)):
            for reason, data, attrs in invalid_messages(side, good, input_twin, args.replay_id):
                publish(side, f"invalid_{reason}", data, attrs)
    for side in ts.SIDES:
        publish(side, "end_marker", b"{}", {"schema": ts.SCHEMAS[side], "kind": "control", "sender": side,
                                            "replay_id": args.replay_id, "content_sha256": hashlib.sha256(b"{}").hexdigest()})
    for side, category, key, future in pending:
        log["messages"].append({"side": side, "category": category, "reading_key": key, "message_id": future.result()})
    log["total"] = {side: sum(log["published"][side].values()) for side in ts.SIDES}
    args.log.write_text(json.dumps(log, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in log.items() if k != "messages"}, indent=1))


if __name__ == "__main__":
    main()
