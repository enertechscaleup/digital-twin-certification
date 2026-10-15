"""Waits until a two-source replay's messages have reached the bucket: both raw feeds hold at least
their published counts and every tick has a joined output (joined or incomplete), then stay unchanged.

    python ingest/wait_two_source.py --bucket B --replay-id R --published-plant N --published-twin M --ticks T
"""

import argparse
import re
import time

from google.cloud import storage


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--replay-id", required=True)
    ap.add_argument("--published-plant", type=int, required=True)
    ap.add_argument("--published-twin", type=int, required=True)
    ap.add_argument("--ticks", type=int, required=True)
    ap.add_argument("--settle-s", type=int, default=40)
    ap.add_argument("--timeout-s", type=int, default=1500)
    args = ap.parse_args()
    gcs = storage.Client()
    start, stable_since, last = time.time(), None, None
    want = {"plant": args.published_plant, "twin": args.published_twin}
    while time.time() - start < args.timeout_s:
        raw = {s: sum(len(b.download_as_bytes().splitlines()) for b in gcs.list_blobs(args.bucket, prefix=f"raw2/{s}/{args.replay_id}/"))
               for s in want}
        panes = {}
        for b in gcs.list_blobs(args.bucket, prefix=f"joined/{args.replay_id}/"):
            m = re.search(r"tick-(\d+)\.p(\d+)\.", b.name)
            if m:
                panes[int(m.group(1))] = max(panes.get(int(m.group(1)), -1), int(m.group(2)))
        state = (tuple(raw.items()), tuple(sorted(panes.items())))
        done = all(raw[s] >= want[s] for s in want) and len(panes) >= args.ticks
        print(f"{int(time.time() - start):5d}s raw plant {raw['plant']}/{want['plant']}, twin {raw['twin']}/{want['twin']}, "
              f"ticks {len(panes)}/{args.ticks}", flush=True)
        if done and state == last:
            if stable_since and time.time() - stable_since >= args.settle_s:
                print("outputs complete and stable")
                return
            stable_since = stable_since or time.time()
        else:
            stable_since = None
        last = state
        time.sleep(10)
    raise SystemExit(f"timed out after {args.timeout_s}s")


if __name__ == "__main__":
    main()
