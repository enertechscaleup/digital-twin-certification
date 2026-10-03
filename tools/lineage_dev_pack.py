"""A local evidence pack with twin lineage, for reviewing the platform screens.

    .venv/bin/python -m tools.lineage_dev_pack      # writes data/lineage-dev/

Regenerates the full assurance cycle with the current engine (so it records twin
lineage) into data/lineage-dev/, with placeholder AI explanations instead of Gemini
calls, and a runs.json that pins it. It is never uploaded and is not evidence: the
served runs and their pins (app/config/runs.json) are untouched. Serve it with the
"platform-lineage-dev" launch configuration.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.evidence import write_manifest
from engine.__main__ import code_commit
from engine.registry import load_registry
from engine.run import run_assurance, write_jsonl
from explain import supplementary
from explain.gemini import generate_artifacts
from telemetry.faults import Scenario
from vendor.advise import recommend
from vendor.recalibrate import owner_for_platform

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "lineage-dev"
RUN = "lineage-dev-demo_full_cycle-seed42"


class PlaceholderAI:
    """Stands in for Gemini: a clearly labelled placeholder in the expected schema."""

    model_id = "placeholder (no AI call)"

    def __call__(self, system_instruction: str, prompt: str, schema: dict) -> str:
        return json.dumps({k: [] if v["type"] == "array" else v["enum"][0] if "enum" in v
                           else "Placeholder, not AI-generated (local lineage check)"
                           for k, v in schema["properties"].items()})


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    s = Scenario.from_dict(json.loads((ROOT / "scenarios" / "demo_full_cycle.json").read_text()))
    r = run_assurance(s, seed=42, start_time=datetime(2026, 10, 1, tzinfo=timezone.utc),
                      ledger_path=OUT / f"{RUN}.ledger.jsonl", recalibrator=owner_for_platform, advisor=recommend,
                      code_commit=code_commit())
    write_jsonl(r.readings, OUT / f"{RUN}.readings.jsonl")
    write_jsonl(r.timeline, OUT / f"{RUN}.timeline.jsonl")
    sup = supplementary.start(OUT / f"{RUN}.supplementary.jsonl", r.ledger.entries)
    generate_artifacts(r.ledger.entries, r.readings, r.timeline, load_registry(), PlaceholderAI(),
                       on_artifact=lambda a: supplementary.record(sup, a))
    sup.close()
    head = write_manifest(OUT, RUN, "demo_full_cycle", code_commit())["core_ledger_head_hash"]
    (OUT / "runs.json").write_text(json.dumps({
        "_note": "Local lineage check only: not evidence, never uploaded.",
        "default": RUN,
        "runs": [{"run": RUN, "title": "Local lineage check (not evidence)", "core_ledger_head_hash": head,
                  "project_id": "oil-gas-compressor-train"}],
    }, indent=2) + "\n", encoding="utf-8")
    print(f"{RUN}: {len(r.ledger.entries)} entries, head {head[:16]} -> {OUT}")


if __name__ == "__main__":
    main()
