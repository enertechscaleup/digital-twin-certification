"""Command-line entry point.

    python -m telemetry bench  --twin all
    python -m telemetry field  --scenario scenarios/demo_wear_to_nullified.json
    python -m telemetry field  --scenario scenarios/healthy.json --realtime

Output goes to ``data/`` as a readings file (.jsonl) plus a manifest (.json)
describing the run.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from telemetry.faults import Scenario
from telemetry.generator import TWIN_ORDER, Reading, TelemetryGenerator
from telemetry.sinks import JsonlFileSink


def _parse_time(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def _sinks(out_dir: Path, run_id: str) -> JsonlFileSink:
    return JsonlFileSink(out_dir / f"{run_id}.jsonl", out_dir / f"{run_id}.manifest.json")


def _gap_line(batch: list[Reading]) -> str:
    """A human-readable preview of each output's gap. Display only -- the
    verification engine (Phase 2) does the real classification."""
    parts = []
    for r in batch:
        if r.direction != "output":
            continue
        if r.physical_value is None or r.predicted_value is None:
            gap = "  n/a "
        else:
            gap = f"{100 * (r.physical_value - r.predicted_value) / r.predicted_value:+6.2f}%"
        mark = "*" if r.injected_faults else " "
        parts.append(f"{r.twin_type[:4]}.{r.channel_id[:5]:<5} {gap}{mark}")
    return "  ".join(parts)


def cmd_bench(args: argparse.Namespace) -> None:
    gen = TelemetryGenerator(seed=args.seed, start_time=_parse_time(args.start_time))
    for twin_type in TWIN_ORDER if args.twin == "all" else (args.twin,):
        run_id = gen.bench_run_id(twin_type)
        sink = _sinks(args.out, run_id)
        sink.write_manifest(gen.manifest(run_id, "bench", {
            "twin_type": twin_type, "levels": args.levels, "repeats": args.repeats,
        }))
        samples = 0
        for batch in gen.bench_sweep(twin_type, levels=args.levels, repeats=args.repeats):
            sink.write(batch)
            samples += 1
        sink.close()
        print(f"{twin_type}: {samples} bench samples -> {args.out / (run_id + '.jsonl')}")


def cmd_field(args: argparse.Namespace) -> None:
    raw = json.loads(args.scenario.read_text(encoding="utf-8"))
    if args.ticks:
        raw["ticks"] = args.ticks
    scenario = Scenario.from_dict(raw)
    gen = TelemetryGenerator(seed=args.seed, start_time=_parse_time(args.start_time))
    run_id = gen.field_run_id(scenario)
    sink = _sinks(args.out, run_id)
    sink.write_manifest(gen.manifest(run_id, "field", {"scenario": raw}))

    print(f"run {run_id}  ({'real time, 1 tick every %ss' % gen.tick_seconds if args.realtime else 'as fast as possible'})")
    print("gap = (physical - predicted) / predicted;  * = a fault was injected into that reading")
    next_tick = time.monotonic()
    for batch in gen.field_run(scenario):
        if args.realtime:
            time.sleep(max(0.0, next_tick - time.monotonic()))
            next_tick += gen.tick_seconds
        sink.write(batch)
        if not args.quiet:
            first = batch[0]
            print(f"tick {first.tick:3d}  {first.operational_hours:7.0f}h  {_gap_line(batch)}")
    sink.close()
    print(f"-> {args.out / (run_id + '.jsonl')}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m telemetry", description="Synthetic telemetry for the motor and compressor twins.")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--seed", type=int, default=42, help="random seed; same seed = same data (default 42)")
    common.add_argument("--start-time", help="ISO timestamp for tick 0, e.g. 2026-10-01T00:00:00Z (default: now)")
    common.add_argument("--out", type=Path, default=Path("data"), help="output folder (default data/)")
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("bench", parents=[common], help="test-bench sweep across the assured input range")
    b.add_argument("--twin", choices=[*TWIN_ORDER, "all"], default="all")
    b.add_argument("--levels", type=int, default=5, help="values per input across its range (default 5)")
    b.add_argument("--repeats", type=int, default=3, help="samples per test point (default 3)")
    b.set_defaults(func=cmd_bench)

    f = sub.add_parser("field", parents=[common], help="operational stream driven by a scenario file")
    f.add_argument("--scenario", type=Path, required=True)
    f.add_argument("--ticks", type=int, help="override the scenario's tick count")
    f.add_argument("--realtime", action="store_true", help="pace output at the real tick cadence (2s)")
    f.add_argument("--quiet", action="store_true", help="don't print each tick")
    f.set_defaults(func=cmd_field)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
