"""Generate or verify Gemini explanations for a saved assurance run.

    python -m explain run    data/assurance-demo_wear_to_nullified-seed42
    python -m explain verify data/assurance-demo_wear_to_nullified-seed42

``run`` reads <run>.ledger.jsonl, <run>.readings.jsonl and <run>.timeline.jsonl,
checks their integrity, and writes the supplementary ledger
<run>.supplementary.jsonl. ``verify`` checks both ledgers and every link
between them.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.ledger import load_ledger
from engine.registry import load_registry
from explain import supplementary
from explain.gemini import PINNED_LOCATION, PINNED_MODEL, VertexGemini, generate_artifacts


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def cmd_run(args: argparse.Namespace) -> None:
    prefix = args.run
    core = load_ledger(Path(f"{prefix}.ledger.jsonl"))
    readings = _jsonl(Path(f"{prefix}.readings.jsonl"))
    timeline = _jsonl(Path(f"{prefix}.timeline.jsonl"))
    out = Path(f"{prefix}.supplementary.jsonl")
    sup = supplementary.start(out, core)
    generator = VertexGemini(args.model, project=args.project, location=args.location)

    def on_artifact(a: dict) -> None:
        supplementary.record(sup, a)
        r = a["response"] or {}
        print(f"[explains core #{a['explains_ledger_seq']}] {a['artifact_type']}: {r.get('headline', a['parse_error'])}")

    artifacts = generate_artifacts(core, readings, timeline, load_registry(), generator, on_artifact=on_artifact)
    sup.close()
    print(f"{len(artifacts)} artifacts ({generator.model_id} @ {args.location}) -> {out}")


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
    r.add_argument("--project", default="project-46053a8a-6324-40f0-ba8")
    r.set_defaults(func=cmd_run)
    v = sub.add_parser("verify", help="verify the core and supplementary ledgers and their links")
    v.add_argument("run")
    v.set_defaults(func=cmd_verify)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
