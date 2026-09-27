"""Generate Gemini explanations for a saved assurance run.

    python -m explain data/assurance-demo_wear_to_nullified-seed42 --model <pinned-model-id>

Reads <run>.ledger.jsonl, <run>.readings.jsonl and <run>.timeline.jsonl, checks
their integrity, and writes <run>.explanations.jsonl.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.ledger import load_ledger
from engine.registry import load_registry
from explain.gemini import DEFAULT_LOCATION, DEFAULT_MODEL, VertexGemini, generate_artifacts


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m explain")
    parser.add_argument("run", help="run path prefix, e.g. data/assurance-demo_wear_to_nullified-seed42")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="pinned Gemini model ID (or set GEMINI_MODEL)")
    parser.add_argument("--project", default="project-46053a8a-6324-40f0-ba8")
    parser.add_argument("--location", default=DEFAULT_LOCATION)
    args = parser.parse_args()

    prefix = args.run
    ledger = load_ledger(Path(f"{prefix}.ledger.jsonl"))
    readings = _jsonl(Path(f"{prefix}.readings.jsonl"))
    timeline = _jsonl(Path(f"{prefix}.timeline.jsonl"))
    out = Path(f"{prefix}.explanations.jsonl")
    generator = VertexGemini(args.model, project=args.project, location=args.location)

    with out.open("w", encoding="utf-8") as f:
        def show(a: dict) -> None:
            f.write(json.dumps(a) + "\n")
            f.flush()
            r = a["response"] or {}
            print(f"[explains ledger #{a['explains_ledger_seq']}] {a['artifact_type']}: {r.get('headline', a['parse_error'])}")
        artifacts = generate_artifacts(ledger, readings, timeline, load_registry(), generator, on_artifact=show)
    print(f"{len(artifacts)} artifacts -> {out}")


if __name__ == "__main__":
    main()
