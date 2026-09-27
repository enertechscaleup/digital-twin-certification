"""Command-line entry point.

    python -m engine run --scenario scenarios/demo_wear_to_nullified.json
    python -m engine verify-ledger data/<run>.ledger.jsonl
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from engine.ledger import load_ledger, verify_chain
from engine.run import run_assurance, write_jsonl
from telemetry.faults import Scenario


def cmd_run(args: argparse.Namespace) -> None:
    raw = json.loads(args.scenario.read_text(encoding="utf-8"))
    start = datetime.fromisoformat(args.start_time.replace("Z", "+00:00")) if args.start_time else None
    stem = f"assurance-{raw['name']}-seed{args.seed}"
    ledger_path = args.out / f"{stem}.ledger.jsonl"
    # The twin owner is a separate party; the engine is handed it, never imports it.
    from vendor.recalibrate import owner_for_platform
    result = run_assurance(Scenario.from_dict(raw), seed=args.seed, start_time=start, ledger_path=ledger_path,
                           recalibrator=owner_for_platform)
    write_jsonl(result.timeline, args.out / f"{stem}.timeline.jsonl")
    write_jsonl(result.readings, args.out / f"{stem}.readings.jsonl")

    for e in result.ledger.entries:
        p = e["payload"]
        if e["entry_type"] == "verification" and p.get("stage") == "re-verification":
            print(f"[{e['seq']:3d}] re-verification  {p['twin_id']:<20} {'PASS' if p['passed'] else 'FAIL'} (twin {p['twin_version']})")
        elif e["entry_type"] in ("verification", "bench_validation"):
            print(f"[{e['seq']:3d}] {e['entry_type']:<16} {p['twin_id']:<20} {'PASS' if p['passed'] else 'FAIL'}")
        elif e["entry_type"] in ("assurance_issued", "composition_assured", "assurance_refused"):
            print(f"[{e['seq']:3d}] {e['entry_type']:<16} {p.get('assurance_id') or p.get('composition_assurance_id') or p['twin_id']}")
        elif e["entry_type"] in ("assurance_status_changed", "assurance_reason_added"):
            what = f"{p['from']} -> {p['to']}" if e["entry_type"] == "assurance_status_changed" else f"still {p['status']}, new reason"
            causes = "; ".join(f"{r['cause']}" + (f" on {r['channel_id']}" if r.get("channel_id") else "")
                               + (f" from {r['constituent']}" if r.get("constituent") else "") for r in p["new_reasons"])
            print(f"[{e['seq']:3d}] tick {p['tick']:3d}  {p['twin_id']:<24} {what:<24} {causes}")
        elif e["entry_type"].startswith("recalibration_") or e["entry_type"] in (
                "held_out_validation", "assurance_superseded", "composition_reassessment"):
            extra = ""
            if e["entry_type"] == "recalibration_requested":
                extra = f"split {p['split']['released_to_owner']} to owner / {p['split']['held_out']} held out"
            elif e["entry_type"] == "held_out_validation":
                extra = ("PASS" if p["passed"] else "FAIL") + f", {p['ticks_evaluated']} ticks, " + ", ".join(
                    f"{c} max gap {d['max_gap_pct']}%" for c, d in p["per_channel"].items())
            elif e["entry_type"] == "assurance_superseded":
                extra = f"{p['old_assurance_id']} -> {p['new_assurance_id']}"
            elif e["entry_type"] == "composition_reassessment":
                extra = p["result"] + "".join(f"; blocked by {b['constituent']} ({b['status']}: "
                                              + ", ".join(r["cause"] + " on " + str(r.get("channel_id")) for r in b["reasons"]) + ")"
                                              for b in p.get("blocked_by", []))
            print(f"[{e['seq']:3d}] {e['entry_type']:<26} {extra}")
    opened = result.ledger.of_type("anomaly_opened")
    kinds: dict[str, int] = {}
    for e in opened:
        k = e["payload"]["type"] + (f":{e['payload']['subtype']}" if e["payload"]["subtype"] else "")
        kinds[k] = kinds.get(k, 0) + 1
    print(f"anomalies opened: {kinds or 'none'}")
    print(f"ledger: {len(result.ledger.entries)} entries, head {result.ledger.head_hash[:16]}... -> {ledger_path}")


def cmd_verify(args: argparse.Namespace) -> None:
    check = verify_chain(load_ledger(args.ledger))
    if check.valid:
        print(f"VALID: {check.entries_checked} entries, hash chain intact")
    else:
        print(f"INVALID at entry {check.first_bad_seq}: {check.reason}")
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m engine", description="Deterministic assurance engine.")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="assure the twins and monitor a scenario's field stream")
    r.add_argument("--scenario", type=Path, required=True)
    r.add_argument("--seed", type=int, default=42)
    r.add_argument("--start-time", default="2026-10-01T00:00:00Z", help="ISO timestamp for tick 0")
    r.add_argument("--out", type=Path, default=Path("data"))
    r.set_defaults(func=cmd_run)
    v = sub.add_parser("verify-ledger", help="check a ledger file's hash chain")
    v.add_argument("ledger", type=Path)
    v.set_defaults(func=cmd_verify)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
