"""Command-line entry point.

    python -m engine run --scenario scenarios/demo_wear_to_nullified.json
    python -m engine run --scenario ... --vendor motor=http://localhost:9101 --vendor compressor=http://localhost:9102
    python -m engine run --project projects/fulfilment_cell.json --scenario scenarios/amr_full_cycle.json
    python -m engine verify-ledger data/<run>.ledger.jsonl
    python -m engine register-twins [--project projects/<project>.json]
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path

from engine.boundary import ExchangeLog
from engine.ledger import load_ledger, verify_chain
from engine.lineage import IDENTITIES, REGISTERED, register_identities
from engine.registry import load_registry
from engine.run import run_assurance, write_jsonl
from projects import DEFAULT_PROJECT, load_project
from telemetry.faults import Scenario


def code_commit() -> str | None:
    """The checked-out commit, marked -dirty if the working tree has uncommitted changes."""
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return head + ("-dirty" if dirty else "")


def vendors(urls: list[str], project=None) -> dict:
    """A connection to each twin owner's endpoint: simulated in process, or over HTTP for any
    ``twin=url`` given (python -m vendor.serve). The engine itself never imports the vendor side."""
    from engine.boundary import HttpConnection
    from vendor.endpoint import simulated_vendors
    out = simulated_vendors(project)
    for spec in urls or []:
        twin, url = spec.split("=", 1)
        out[twin] = HttpConnection(url)
    return out


def cmd_run(args: argparse.Namespace) -> None:
    raw = json.loads(args.scenario.read_text(encoding="utf-8"))
    start = datetime.fromisoformat(args.start_time.replace("Z", "+00:00")) if args.start_time else None
    stem = f"assurance-{raw['name']}-seed{args.seed}"
    ledger_path = args.out / f"{stem}.ledger.jsonl"
    project = load_project(args.project)
    result = run_assurance(Scenario.from_dict(raw), vendors(args.vendor, project), seed=args.seed, start_time=start,
                           ledger_path=ledger_path, project=project, code_commit=code_commit())
    write_jsonl(result.timeline, args.out / f"{stem}.timeline.jsonl")
    write_jsonl(result.readings, args.out / f"{stem}.readings.jsonl")
    ExchangeLog.write_records(result.exchange, args.out / f"{stem}.exchange.jsonl")

    for e in result.ledger.entries:
        p = e["payload"]
        if e["entry_type"] == REGISTERED:
            parent = f"parent {p['parent_fingerprint'][:12]}" if p["parent_fingerprint"] else "first version"
            print(f"[{e['seq']:3d}] version registered {p['twin']['identity']} v{p['twin']['version']:<8} "
                  f"{p['twin']['fingerprint'][:12]}  {parent}")
        elif e["entry_type"] == "composition_test":
            i, x = p["interface"], p["interaction"]
            print(f"[{e['seq']:3d}] joint composition test {p['test_id']} ({p['trigger']}): "
                  f"interface {'PASS' if i['passed'] else 'FAIL'}, interaction {'PASS' if x['passed'] else 'FAIL'} "
                  f"on {x['evaluated_points']}/{p['points']} points")
        elif e["entry_type"] == "verification" and p.get("stage") == "re-verification":
            print(f"[{e['seq']:3d}] re-verification  {p['twin_id']:<20} {'PASS' if p['passed'] else 'FAIL'} (twin {p['twin_version']})")
        elif e["entry_type"] in ("verification", "bench_validation"):
            print(f"[{e['seq']:3d}] {e['entry_type']:<16} {p['twin_id']:<20} {'PASS' if p['passed'] else 'FAIL'}")
        elif e["entry_type"] in ("assurance_issued", "composition_assured", "assurance_refused"):
            print(f"[{e['seq']:3d}] {e['entry_type']:<16} {p.get('assurance_id') or p.get('composition_assurance_id') or p['twin_id']}")
        elif e["entry_type"].startswith("adjustment_"):
            if e["entry_type"] == "adjustment_recommended":
                r = p["recommendation"]
                extra = (f"{r['control_channel']} {r['from']:.1f} -> {r['to']}, predicted objective "
                         f"{p['predicted_objective_value']:.1f} (margin {p['predicted_margin_above_objective']:+.1f})")
            elif e["entry_type"] == "adjustment_approval":
                extra = f"{p['decision']} by {p['approver']}"
            elif e["entry_type"] == "adjustment_post_state_check":
                extra = (f"Sim2Real {'PASS' if p['sim2real_passed'] else 'FAIL'} ("
                         + ", ".join(f"{c} max gap {d['max_gap_pct']}%" for c, d in p["sim2real"].items())
                         + f"); objective {p['objective']['ticks_in_range']}/{p['objective']['ticks_checked']} ticks in range, "
                         f"lowest {p['objective']['min_value']:.1f}")
            else:
                extra = p.get("reason", p.get("note", ""))
            print(f"[{e['seq']:3d}] tick {p['tick']:3d}  {e['entry_type']:<28} {extra}")
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


def cmd_register(args: argparse.Namespace) -> None:
    project = load_project(args.project)
    new = register_identities(load_registry(project), project.project_id, args.identities)
    for r in new:
        print(f"registered {r['identity']}  {r.get('design_twin_id') or r.get('design_system_twin_id')}")
    print(f"{len(new)} new identities" if new else "every twin already has a permanent identity")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m engine", description="Deterministic assurance engine.")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="assure the twins and monitor a scenario's field stream")
    r.add_argument("--scenario", type=Path, required=True)
    r.add_argument("--project", type=Path, default=DEFAULT_PROJECT, help="project file (default: the compressor train)")
    r.add_argument("--seed", type=int, default=42)
    r.add_argument("--start-time", default="2026-10-01T00:00:00Z", help="ISO timestamp for tick 0")
    r.add_argument("--out", type=Path, default=Path("data"))
    r.add_argument("--vendor", action="append", metavar="TWIN=URL",
                   help="query this twin's owner over HTTP (python -m vendor.serve) instead of in process")
    r.set_defaults(func=cmd_run)
    v = sub.add_parser("verify-ledger", help="check a ledger file's hash chain")
    v.add_argument("ledger", type=Path)
    v.set_defaults(func=cmd_verify)
    g = sub.add_parser("register-twins", help="give each unregistered twin of a project its permanent identity")
    g.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    g.add_argument("--identities", type=Path, default=IDENTITIES)
    g.set_defaults(func=cmd_register)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
