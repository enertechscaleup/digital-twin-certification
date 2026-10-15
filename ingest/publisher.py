"""Replays a sealed synthetic run's readings into the Pub/Sub topic, accelerated.

Each message's data is the sealed readings line, byte for byte. Attributes: schema, source=replay,
replay_id, event_ts, reading_key (the idempotency key) and content_sha256. It reads only a local
copy of the sealed file; it never touches the evidence bucket.

Test options (each used in its own replay): shuffle within a few ticks, repeat a fraction of the
messages, deliver one reading late, keep one back entirely (to publish after the job is drained),
inject one malformed message per reject reason, or republish a reading with changed content.
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
from pipeline import SCHEMA, reading_key  # noqa: E402


def attributes(data: bytes, replay_id: str, row: dict | None, key: str | None = None) -> dict:
    a = {"schema": SCHEMA, "source": "replay", "replay_id": replay_id,
         "content_sha256": hashlib.sha256(data).hexdigest()}
    if row is not None:
        a["event_ts"] = str(row.get("timestamp"))
        a["reading_key"] = key or reading_key(replay_id, str(row.get("run_id")), row.get("tick"),
                                              str(row.get("twin_id")), str(row.get("channel_id")))
    return a


def invalid_messages(template: dict, replay_id: str) -> list[tuple[str, bytes, dict]]:
    """One message for each reject reason of the pipeline (ingest/pipeline.py: classify)."""
    t = dict(template)
    out = []
    data = b'{"run_id": "truncated'
    out.append(("malformed_json", data, attributes(data, replay_id, t)))
    for reason, row in (("forbidden_field", {**t, "injected_faults": []}),
                        ("missing_field", {k: v for k, v in t.items() if k != "unit"}),
                        ("bad_type", {**t, "tick": str(t["tick"])}),
                        ("wrong_kind", {**t, "kind": "bench"}),
                        ("unknown_channel", {**t, "channel_id": "no_such_channel"})):
        data = json.dumps(row).encode()
        out.append((reason, data, attributes(data, replay_id, row)))
    data = json.dumps(t).encode()
    out.append(("bad_attributes", data, attributes(data, replay_id, t, key="0" * 32)))
    a = attributes(data, replay_id, t)
    a["content_sha256"] = "0" * 64
    out.append(("content_hash_mismatch", data, a))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--readings", type=Path, required=True)
    ap.add_argument("--topic", required=True, help="projects/P/topics/T")
    ap.add_argument("--replay-id", required=True)
    ap.add_argument("--impersonate", help="publisher service account email")
    ap.add_argument("--rate", type=float, default=50.0, help="messages per second")
    ap.add_argument("--shuffle-ticks", type=int, default=0, help="shuffle within +/- this many ticks")
    ap.add_argument("--duplicate-fraction", type=float, default=0.0, help="republish this fraction, identical")
    ap.add_argument("--late", type=int, help="hold one reading of this tick back ...")
    ap.add_argument("--late-delay-s", type=float, default=15.0, help="... and publish it this long after 3 more ticks")
    ap.add_argument("--keep-back", type=int, help="do not publish one reading of this tick; write it to --kept-file")
    ap.add_argument("--kept-file", type=Path)
    ap.add_argument("--publish-file", type=Path, help="publish only the messages in this file (a kept-back reading)")
    ap.add_argument("--invalid", action="store_true", help="also inject one message per reject reason")
    ap.add_argument("--conflict", type=int, help="republish one reading of this tick with changed content")
    ap.add_argument("--no-end-marker", action="store_true")
    ap.add_argument("--log", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    import google.auth
    from google.auth import impersonated_credentials
    from google.cloud import pubsub_v1

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    if args.impersonate:
        creds = impersonated_credentials.Credentials(source_credentials=creds, target_principal=args.impersonate,
                                                     target_scopes=["https://www.googleapis.com/auth/pubsub"])
    client = pubsub_v1.PublisherClient(credentials=creds)
    rng = random.Random(args.seed)
    log = {"replay_id": args.replay_id, "readings_file": args.readings.name,
           "readings_file_sha256": hashlib.sha256(args.readings.read_bytes()).hexdigest(), "published": {}, "messages": []}
    pending = []

    def publish(category: str, data: bytes, attrs: dict) -> None:
        pending.append((category, attrs.get("reading_key"), client.publish(args.topic, data, **attrs)))
        log["published"][category] = log["published"].get(category, 0) + 1
        time.sleep(1.0 / args.rate)

    lines = [l for l in args.readings.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.publish_file:
        for l in args.publish_file.read_text(encoding="utf-8").splitlines():
            row = json.loads(l)
            publish("reading_after_drain", l.encode(), attributes(l.encode(), args.replay_id, row))
    else:
        rows = [(json.loads(l), l.encode()) for l in lines]
        if args.shuffle_ticks:
            rows.sort(key=lambda x: x[0]["tick"] + rng.uniform(-args.shuffle_ticks, args.shuffle_ticks))
        held_late = held_back = None
        if args.late is not None:
            held_late = next(x for x in rows if x[0]["tick"] == args.late)
            rows.remove(held_late)
        if args.keep_back is not None:
            held_back = next(x for x in rows if x[0]["tick"] == args.keep_back)
            rows.remove(held_back)
            args.kept_file.write_text(held_back[1].decode() + "\n", encoding="utf-8")
            log["kept_back"] = {"tick": held_back[0]["tick"], "twin_id": held_back[0]["twin_id"], "channel_id": held_back[0]["channel_id"]}
        late_sent = False
        for i, (row, data) in enumerate(rows):
            publish("reading", data, attributes(data, args.replay_id, row))
            if args.duplicate_fraction and rng.random() < args.duplicate_fraction:
                publish("identical_duplicate", data, attributes(data, args.replay_id, row))
            if held_late and not late_sent and row["tick"] >= args.late + 3:
                for f in pending:
                    f[2].result()
                time.sleep(args.late_delay_s)
                publish("reading_late", held_late[1], attributes(held_late[1], args.replay_id, held_late[0]))
                log["late"] = {"tick": held_late[0]["tick"], "twin_id": held_late[0]["twin_id"],
                               "channel_id": held_late[0]["channel_id"], "after_tick": row["tick"], "delay_s": args.late_delay_s}
                late_sent = True
        if args.conflict is not None:
            row, data = next(x for x in rows if x[0]["tick"] == args.conflict and isinstance(x[0]["physical_value"], (int, float)))
            changed = json.dumps({**row, "physical_value": round(row["physical_value"] * 1.01, 4)}).encode()
            publish("conflicting_duplicate", changed, attributes(changed, args.replay_id, row))
            log["conflict"] = {"tick": row["tick"], "twin_id": row["twin_id"], "channel_id": row["channel_id"]}
        if args.invalid:
            for reason, data, attrs in invalid_messages(rows[0][0], args.replay_id):
                publish(f"invalid_{reason}", data, attrs)
    if not args.no_end_marker:
        publish("end_marker", b"{}", {"schema": SCHEMA, "kind": "control", "replay_id": args.replay_id,
                                      "content_sha256": hashlib.sha256(b"{}").hexdigest()})
    for category, key, future in pending:
        log["messages"].append({"category": category, "reading_key": key, "message_id": future.result()})
    log["total"] = len(log["messages"])
    args.log.write_text(json.dumps(log, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in log.items() if k != "messages"}, indent=1))


if __name__ == "__main__":
    main()
