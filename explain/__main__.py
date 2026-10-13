"""Generate or verify Gemini explanations for a saved assurance run.

    python -m explain run    data/assurance-demo_wear_to_nullified-seed42
    python -m explain run    data/fulfilment/assurance-amr_full_cycle-seed42 \\
        --project-file projects/fulfilment_cell.json --profile 2
    python -m explain verify data/assurance-demo_wear_to_nullified-seed42

``run`` reads <run>.ledger.jsonl, <run>.readings.jsonl and <run>.timeline.jsonl,
checks their integrity, and writes the supplementary ledger
<run>.supplementary.jsonl. Profile 1 (the default) is the original pipeline;
profile 2 (explain/sealed.py) explains every engine decision and checks each
answer against the evidence before sealing it, logging rejected answers to
<run>.ai-rejections.jsonl (a working log, not evidence). If Gemini cannot be
reached, the supplementary ledger records that the run has no (or no further)
explanations. ``verify`` checks both ledgers and every link between them.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import time

from engine.ledger import load_ledger
from engine.registry import load_registry
from explain import supplementary
from explain.gemini import PINNED_LOCATION, PINNED_MODEL, VertexGemini, generate_artifacts
from explain.sealed import ExplanationsUnavailable, generate_sealed
from projects import DEFAULT_PROJECT, load_project


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def cmd_run(args: argparse.Namespace) -> None:
    prefix = args.run
    core = load_ledger(Path(f"{prefix}.ledger.jsonl"))
    readings = _jsonl(Path(f"{prefix}.readings.jsonl"))
    timeline = _jsonl(Path(f"{prefix}.timeline.jsonl"))
    out = Path(f"{prefix}.supplementary.jsonl")
    project = load_project(args.project_file)
    registry = load_registry(project)
    sup = supplementary.start(out, core)
    sealed: list[dict] = []

    def on_artifact(a: dict) -> None:
        supplementary.record(sup, a)
        sealed.append(a)
        r = a["response"] or {}
        print(f"[explains core #{a['explains_ledger_seq']}] {a['artifact_type']}: {r.get('headline', a['parse_error'])}")

    started = time.monotonic()
    try:
        generator = VertexGemini(args.model, project=args.project, location=args.location)
        if args.profile == 1:
            generate_artifacts(core, readings, timeline, registry, generator, on_artifact=on_artifact)
        else:
            log = Path(f"{prefix}.ai-rejections.jsonl")
            log.write_text("", encoding="utf-8")

            def on_rejected(r: dict) -> None:
                with log.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(r) + "\n")
                print(f"[rejected core #{r['explains_ledger_seq']} attempt {r['attempt']}] {r['artifact_type']}: "
                      + "; ".join(r["problems"]))

            generate_sealed(core, readings, timeline, registry, project, generator,
                            on_artifact=on_artifact, on_rejected=on_rejected)
    except ExplanationsUnavailable as exc:
        supplementary.record_unavailable(sup, str(exc), len(sealed))
        print(f"no explanations: the AI service was unavailable ({exc})")
    except Exception as exc:  # the client could not even be created (credentials, network)
        if args.profile == 1:
            raise
        supplementary.record_unavailable(sup, f"{type(exc).__name__}: {exc}", len(sealed))
        print(f"no explanations: the AI service was unavailable ({exc})")
    sup.close()
    print(f"{len(sealed)} artifacts sealed ({args.model} @ {args.location}, profile {args.profile}) "
          f"in {time.monotonic() - started:.1f} s -> {out}")


def cmd_verify(args: argparse.Namespace) -> None:
    core = load_ledger(Path(f"{args.run}.ledger.jsonl"))
    sup = load_ledger(Path(f"{args.run}.supplementary.jsonl"))
    check = supplementary.verify(sup, core)
    if check.valid:
        print(f"VALID: core ({len(core)} entries) and supplementary ({len(sup)} entries) chains intact, "
              f"every AI artifact anchored to a matching core entry")
    else:
        print(f"INVALID: {check.reason}")
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m explain")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="generate AI explanations into a supplementary ledger")
    r.add_argument("run", help="run path prefix, e.g. data/assurance-demo_wear_to_nullified-seed42")
    r.add_argument("--model", default=PINNED_MODEL, help=f"Gemini model ID (pinned: {PINNED_MODEL})")
    r.add_argument("--location", default=PINNED_LOCATION)
    r.add_argument("--project", default="project-46053a8a-6324-40f0-ba8", help="Google Cloud project")
    r.add_argument("--project-file", type=Path, default=DEFAULT_PROJECT,
                   help="the platform project the run belongs to (default: the compressor train)")
    r.add_argument("--profile", type=int, choices=(1, 2), default=1,
                   help="1: the original explanations; 2: every engine decision, checked before sealing")
    r.set_defaults(func=cmd_run)
    v = sub.add_parser("verify", help="verify the core and supplementary ledgers and their links")
    v.add_argument("run")
    v.set_defaults(func=cmd_verify)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
