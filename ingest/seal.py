"""After a replay's Dataflow job is drained: assemble the validated readings, seal raw and validated
objects by SHA-256, count the dead-lettered messages and the BigQuery rows, and write the receipt.

The engine replay (python -m engine replay) accepts the validated file only if its hash matches the
receipt. An incomplete tick is recorded as such and the receipt says complete=false (fail closed)."""

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


def canonical_sha256(rows: list[dict]) -> str:
    """engine/ledger.py: sha256_hex, without importing the engine into this environment."""
    sys.path.insert(0, str(ROOT))
    from engine.ledger import sha256_hex
    return sha256_hex(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", required=True, help="bucket name, no gs://")
    ap.add_argument("--replay-id", required=True)
    ap.add_argument("--expected-per-tick", type=int, required=True)
    ap.add_argument("--dlq-subscription", required=True, help="projects/P/subscriptions/S")
    ap.add_argument("--bq-table", required=True, help="PROJECT.DATASET.TABLE")
    ap.add_argument("--publish-log", type=Path, required=True)
    ap.add_argument("--job", type=json.loads, required=True, help='{"job_id": ..., "job_name": ..., ...}')
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    from google.cloud import bigquery, pubsub_v1, storage

    gcs = storage.Client()
    bucket = gcs.bucket(args.bucket)
    args.out.mkdir(parents=True, exist_ok=True)

    # Raw: every object, hashed on download.
    raw_objects = []
    raw_messages = 0
    for b in sorted(gcs.list_blobs(args.bucket, prefix=f"raw/{args.replay_id}/"), key=lambda b: b.name):
        data = b.download_as_bytes()
        raw_messages += sum(1 for l in data.splitlines() if l.strip())
        raw_objects.append({"name": b.name, "generation": b.generation, "size": b.size, "crc32c": b.crc32c,
                            "sha256": hashlib.sha256(data).hexdigest()})
    raw_manifest = json.dumps(raw_objects, sort_keys=True).encode()

    # Validated: the highest pane of each tick.
    panes: dict[tuple[str, int], tuple[int, str]] = {}
    for b in gcs.list_blobs(args.bucket, prefix=f"validated/{args.replay_id}/"):
        m = re.search(r"validated/[^/]+/([^/]+)/tick-(\d+)\.p(\d+)\.jsonl$", b.name)
        if m:
            key = (m.group(1), int(m.group(2)))
            if key not in panes or int(m.group(3)) > panes[key][0]:
                panes[key] = (int(m.group(3)), b.name)
    run_ids = sorted({k[0] for k in panes})
    files, rows, problems = [], [], []
    if len(run_ids) != 1:
        problems.append(f"validated output for {len(run_ids)} runs: {run_ids}")
    ticks = sorted(t for (_, t) in panes)
    if ticks and ticks != list(range(ticks[-1] + 1)):
        problems.append(f"ticks missing: {sorted(set(range(ticks[-1] + 1)) - set(ticks))}")
    for (run_id, tick) in sorted(panes, key=lambda k: k[1]):
        pane, name = panes[(run_id, tick)]
        data = bucket.blob(name).download_as_bytes()
        tick_rows = [json.loads(l) for l in data.decode().splitlines() if l.strip()]
        if len(tick_rows) != args.expected_per_tick:
            problems.append(f"tick {tick}: {len(tick_rows)} readings, expected {args.expected_per_tick}")
        rows.extend(tick_rows)
        files.append({"name": name, "pane": pane, "readings": len(tick_rows), "sha256": hashlib.sha256(data).hexdigest()})
    readings_bytes = "".join(json.dumps(r) + "\n" for r in rows).encode()
    readings_path = args.out / f"{args.replay_id}.validated.readings.jsonl"
    readings_path.write_bytes(readings_bytes)

    # Dead letters for this replay (pulled and acknowledged; kept in the receipt folder).
    sub = pubsub_v1.SubscriberClient()
    dead, other = [], 0
    while True:
        resp = sub.pull(request={"subscription": args.dlq_subscription, "max_messages": 100}, timeout=30)
        if not resp.received_messages:
            break
        for m in resp.received_messages:
            a = dict(m.message.attributes)
            if a.get("replay_id") == args.replay_id:
                dead.append({"message_id": m.message.message_id, "reject_reason": a.get("reject_reason"),
                             "attributes": a, "data": m.message.data.decode("utf-8", "replace")})
            else:
                other += 1
        sub.acknowledge(request={"subscription": args.dlq_subscription, "ack_ids": [m.ack_id for m in resp.received_messages]})
    dlq_path = args.out / f"{args.replay_id}.dead-letters.jsonl"
    dlq_path.write_text("".join(json.dumps(d, sort_keys=True) + "\n" for d in dead), encoding="utf-8")

    bq = bigquery.Client()
    q = bq.query(f"SELECT COUNT(*) AS n, COUNT(DISTINCT reading_key) AS k FROM `{args.bq_table}` WHERE replay_id = @r",
                 job_config=bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("r", "STRING", args.replay_id)]))
    bq_rows = next(iter(q.result()))

    publish_log = json.loads(args.publish_log.read_text())
    receipt = {
        "replay_id": args.replay_id,
        "label": "replay of a sealed synthetic run (not live telemetry)",
        "sealed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_readings_file_sha256": publish_log["readings_file_sha256"],
        "pipeline": {**args.job, "stages": ["Pub/Sub topic", "Dataflow (Apache Beam, Python, streaming)",
                                            "Cloud Storage (raw, validated)", "BigQuery (validated rows)",
                                            "Pub/Sub dead-letter topic"]},
        "counts": {
            "published": publish_log["total"], "published_by_category": publish_log["published"],
            "raw_messages": raw_messages, "validated_readings": len(rows), "ticks": len(files),
            "dead_lettered": len(dead), "dead_lettered_by_reason": dict(Counter(d["reject_reason"] for d in dead)),
            "bigquery_rows": bq_rows.n, "bigquery_distinct_keys": bq_rows.k, "dead_letters_of_other_replays": other,
        },
        "raw": {"objects": raw_objects, "manifest_sha256": hashlib.sha256(raw_manifest).hexdigest()},
        "validated": {"files": files, "readings_file": readings_path.name,
                      "readings_file_sha256": hashlib.sha256(readings_bytes).hexdigest(),
                      "readings_sha256": canonical_sha256(rows)},
        "dead_letters_file_sha256": hashlib.sha256(dlq_path.read_bytes()).hexdigest(),
        "complete": not problems, "problems": problems,
        **{k: publish_log[k] for k in ("late", "kept_back", "conflict") if k in publish_log},
    }
    receipt_path = args.out / f"{args.replay_id}.receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=1) + "\n", encoding="utf-8")
    for p in (receipt_path, readings_path, dlq_path, args.publish_log):
        bucket.blob(f"receipts/{args.replay_id}/{p.name}").upload_from_filename(str(p))
    print(json.dumps({k: receipt[k] for k in ("replay_id", "counts", "complete", "problems")}, indent=1))
    print(f"receipt sha256 {hashlib.sha256(receipt_path.read_bytes()).hexdigest()}")
    if problems:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
