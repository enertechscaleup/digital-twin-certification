"""After a two-source replay's Dataflow job is drained: assemble the joined readings (highest pane per
tick), seal both raw feeds and the joined output by SHA-256, count each side's validated rows, dead
letters and BigQuery rows, and write the receipt (receipts2/<replay>/). A tick whose latest pane is
incomplete, or missing, makes the receipt complete=false and the engine refuses the run.

The receipt keeps the top-level keys `python -m engine replay --receipt` reads, so the engine is unchanged.
ingest/seal.py (the single-message path) is not changed."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--replay-id", required=True)
    ap.add_argument("--expected-per-tick", type=int, required=True)
    ap.add_argument("--ticks", type=int, required=True)
    ap.add_argument("--plant-dlq-subscription", required=True)
    ap.add_argument("--twin-dlq-subscription", required=True)
    ap.add_argument("--bq-dataset", required=True, help="PROJECT.DATASET")
    ap.add_argument("--publish-log", type=Path, required=True)
    ap.add_argument("--job", type=json.loads, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    from engine.ledger import sha256_hex
    from google.cloud import bigquery, pubsub_v1, storage

    gcs = storage.Client()
    bucket = gcs.bucket(args.bucket)
    args.out.mkdir(parents=True, exist_ok=True)
    rid = args.replay_id

    raw_objects, raw_messages = [], {}
    for side in ("plant", "twin"):
        raw_messages[side] = 0
        for b in sorted(gcs.list_blobs(args.bucket, prefix=f"raw2/{side}/{rid}/"), key=lambda b: b.name):
            data = b.download_as_bytes()
            raw_messages[side] += sum(1 for l in data.splitlines() if l.strip())
            raw_objects.append({"side": side, "name": b.name, "generation": b.generation, "size": b.size, "crc32c": b.crc32c,
                                "sha256": hashlib.sha256(data).hexdigest()})
    raw_manifest = json.dumps(raw_objects, sort_keys=True).encode()

    def latest(prefix):
        panes = {}
        for b in gcs.list_blobs(args.bucket, prefix=prefix):
            m = re.search(r"/([^/]+)/tick-(\d+)\.p(\d+)\.(jsonl|incomplete\.json)$", b.name)
            if m:
                key = (m.group(1), int(m.group(2)))
                if key not in panes or int(m.group(3)) > panes[key][0]:
                    panes[key] = (int(m.group(3)), b.name, m.group(4))
        return panes

    validated = {}
    for side in ("plant", "twin"):
        n = 0
        for _, name, _ in latest(f"validated2/{side}/{rid}/").values():
            n += sum(1 for l in bucket.blob(name).download_as_bytes().splitlines() if l.strip())
        validated[side] = n

    joined_panes = latest(f"joined/{rid}/")
    problems, files, rows = [], [], []
    run_ids = sorted({k[0] for k in joined_panes})
    if len(run_ids) != 1:
        problems.append(f"joined output for {len(run_ids)} runs: {run_ids}")
    seen_ticks = {t for _, t in joined_panes}
    missing = sorted(set(range(args.ticks)) - seen_ticks)
    if missing:
        problems.append(f"ticks with no joined output: {missing}")
    for (run_id, tick) in sorted(joined_panes, key=lambda k: k[1]):
        pane, name, kind = joined_panes[(run_id, tick)]
        data = bucket.blob(name).download_as_bytes()
        if kind == "incomplete.json":
            problems.append(f"tick {tick} incomplete (pane {pane}): {'; '.join(json.loads(data)['problems'])}")
            continue
        tick_rows = [json.loads(l) for l in data.decode().splitlines() if l.strip()]
        if len(tick_rows) != args.expected_per_tick:
            problems.append(f"tick {tick}: {len(tick_rows)} readings, expected {args.expected_per_tick}")
        rows.extend(tick_rows)
        files.append({"name": name, "pane": pane, "readings": len(tick_rows), "sha256": hashlib.sha256(data).hexdigest()})
    readings_bytes = "".join(json.dumps(r) + "\n" for r in rows).encode()
    readings_path = args.out / f"{rid}.joined.readings.jsonl"
    readings_path.write_bytes(readings_bytes)

    sub = pubsub_v1.SubscriberClient()
    dead, other = [], 0
    for side, subscription in (("plant", args.plant_dlq_subscription), ("twin", args.twin_dlq_subscription)):
        while True:
            resp = sub.pull(request={"subscription": subscription, "max_messages": 100}, timeout=30)
            if not resp.received_messages:
                break
            for m in resp.received_messages:
                a = dict(m.message.attributes)
                if a.get("replay_id") == rid:
                    dead.append({"side": side, "message_id": m.message.message_id, "reject_reason": a.get("reject_reason"),
                                 "attributes": a, "data": m.message.data.decode("utf-8", "replace")})
                else:
                    other += 1
            sub.acknowledge(request={"subscription": subscription, "ack_ids": [m.ack_id for m in resp.received_messages]})
    dlq_path = args.out / f"{rid}.dead-letters.jsonl"
    dlq_path.write_text("".join(json.dumps(d, sort_keys=True) + "\n" for d in dead), encoding="utf-8")

    bq = bigquery.Client()
    bq_rows = {}
    for table in ("plant_validated", "twin_validated", "joined_readings"):
        q = bq.query(f"SELECT COUNT(*) AS n FROM `{args.bq_dataset}.{table}` WHERE replay_id = @r",
                     job_config=bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("r", "STRING", rid)]))
        bq_rows[table] = next(iter(q.result())).n

    log = json.loads(args.publish_log.read_text())
    receipt = {
        "replay_id": rid,
        "label": "two-source replay of a sealed synthetic run (not live telemetry); both feeds share the run's tick index",
        "sealed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_readings_file_sha256": log["readings_file_sha256"],
        "pipeline": {**args.job, "path": "two-source", "stages": ["Pub/Sub plant topic", "Pub/Sub twin topic",
                     "Dataflow (Apache Beam, Python, streaming): per-side validation, join per tick",
                     "Cloud Storage (raw2, validated2, joined)", "BigQuery (plant_validated, twin_validated, joined_readings)",
                     "Pub/Sub dead-letter topics (plant, twin)"]},
        "counts": {
            "published": sum(log["total"].values()), "published_by_side": log["published"],
            "raw_messages": raw_messages, "validated_by_side": validated, "joined_readings": len(rows), "ticks": len(files),
            "dead_lettered": len(dead), "dead_lettered_by_side_reason": {
                side: dict(Counter(d["reject_reason"] for d in dead if d["side"] == side)) for side in ("plant", "twin")},
            "bigquery_rows": bq_rows, "dead_letters_of_other_replays": other,
        },
        "raw": {"objects": raw_objects, "manifest_sha256": hashlib.sha256(raw_manifest).hexdigest()},
        "joined": {"files": files, "readings_file": readings_path.name, "readings_file_sha256": hashlib.sha256(readings_bytes).hexdigest(),
                   "readings_sha256": sha256_hex(rows)},
        "dead_letters_file_sha256": hashlib.sha256(dlq_path.read_bytes()).hexdigest(),
        "complete": not problems, "problems": problems,
        **{k: log[k] for k in ("late", "missing", "conflict") if log.get(k)},
    }
    receipt_path = args.out / f"{rid}.receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=1) + "\n", encoding="utf-8")
    for p in (receipt_path, readings_path, dlq_path, args.publish_log):
        bucket.blob(f"receipts2/{rid}/{p.name}").upload_from_filename(str(p))
    print(json.dumps({k: receipt[k] for k in ("replay_id", "counts", "complete", "problems")}, indent=1))
    print(f"receipt sha256 {hashlib.sha256(receipt_path.read_bytes()).hexdigest()}")
    if problems:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
