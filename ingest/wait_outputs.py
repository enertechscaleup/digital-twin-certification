"""Waits until a replay's messages have all reached the bucket: the raw copy holds at least the
published count and the validated output covers every tick, then stays unchanged for a while.

    python ingest/wait_outputs.py --bucket B --replay-id R --published N --ticks T [--timeout-s 1500]
"""

import argparse
import re
import time

from google.cloud import storage


def snapshot(gcs, bucket, replay_id):
    raw = sum(len(b.download_as_bytes().splitlines()) for b in gcs.list_blobs(bucket, prefix=f"raw/{replay_id}/"))
    panes = {}
    for b in gcs.list_blobs(bucket, prefix=f"validated/{replay_id}/"):
        m = re.search(r"tick-(\d+)\.p(\d+)\.jsonl$", b.name)
        if m:
            panes[int(m.group(1))] = max(panes.get(int(m.group(1)), -1), int(m.group(2)))
    return raw, panes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--replay-id", required=True)
    ap.add_argument("--published", type=int, required=True)
    ap.add_argument("--ticks", type=int, required=True)
    ap.add_argument("--settle-s", type=int, default=40)
    ap.add_argument("--timeout-s", type=int, default=1500)
    args = ap.parse_args()
    gcs = storage.Client()
    start, stable_since, last = time.time(), None, None
    while time.time() - start < args.timeout_s:
        raw, panes = snapshot(gcs, args.bucket, args.replay_id)
        state = (raw, tuple(sorted(panes.items())))
        done = raw >= args.published and len(panes) >= args.ticks
        print(f"{int(time.time() - start):5d}s raw {raw}/{args.published}, ticks {len(panes)}/{args.ticks}", flush=True)
        if done and state == last:
            if stable_since and time.time() - stable_since >= args.settle_s:
                print("outputs complete and stable")
                return
            stable_since = stable_since or time.time()
        else:
            stable_since = None
        last = state
        time.sleep(10)
    raise SystemExit(f"timed out after {args.timeout_s}s (raw {raw}, ticks {len(panes)})")


if __name__ == "__main__":
    main()
