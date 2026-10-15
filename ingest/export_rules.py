"""Writes the message rules for the app's "Check a sample message" (web/src/platform/ingestion-rules.json)
from their single sources: the engine's ingested fields (engine/readings.py: ALLOWED_FIELDS) and the
pipeline's schema, required attributes, timestamp rule and reject reasons (ingest/pipeline.py).
Also the example project for the #ingestion page: the Fulfilment cell's channels from the engine registry.

    python ingest/export_rules.py            # write the file
    python ingest/export_rules.py --check    # exit 1 if the committed file differs (tests use build())
"""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "ingest")]
OUT = ROOT / "web/src/platform/ingestion-rules.json"
EXAMPLE_PROJECT = "projects/fulfilment_cell.json"
# engine/readings.py: gap_pct, in words (tests/test_connect_step.py checks it against the function).
GAP_FORMULA = "gap % = 100 × |physical − predicted| / |predicted|"


def build() -> dict:
    from engine.protocol import EscalationProtocol
    from engine.readings import ALLOWED_FIELDS
    from engine.registry import load_registry
    from pipeline import ALLOWED_FIELDS as PIPELINE_FIELDS, REJECT_REASONS, REQUIRED_ATTRIBUTES, SCHEMA, TIMESTAMP, reading_key
    from projects import load_project
    if tuple(PIPELINE_FIELDS) != tuple(ALLOWED_FIELDS):
        raise SystemExit("the pipeline's fields differ from the engine's")
    project = load_project(ROOT / EXAMPLE_PROJECT)
    registry = load_registry(project)
    channels = [{"twin_id": p.operational_twin_id, "twin": p.twin_type, "channel_id": c.channel_id, "name": c.name,
                 "direction": c.direction, "unit": c.unit, "range": [c.env_min, c.env_max],
                 "tolerance_pct": c.tolerance_pct if c.direction == "output" else None}
                for p in registry.products.values() for c in p.channels]

    def sample(channel: dict) -> dict:
        lo, hi = channel["range"]
        output = channel["direction"] == "output"
        data = {"run_id": f"field-{project.project_id}-sample", "kind": "field", "tick": 0, "timestamp": "2026-10-01T00:00:00Z",
                "operational_hours": 0, "twin_id": channel["twin_id"], "twin_version": "1.0.0",
                "channel_id": channel["channel_id"], "direction": channel["direction"], "unit": channel["unit"],
                "physical_value": round((lo + hi) / 2, 4), "predicted_value": round((lo + hi) / 2 * 1.01, 4) if output else None,
                "test_point": None}
        data_text = json.dumps(data)
        return {"data": data_text, "attributes": {
            "schema": SCHEMA, "source": "sample", "replay_id": "sample", "event_ts": data["timestamp"],
            "reading_key": reading_key("sample", data["run_id"], 0, data["twin_id"], data["channel_id"]),
            "content_sha256": hashlib.sha256(data_text.encode()).hexdigest()}}

    first_input = next(c for c in channels if c["direction"] == "input")
    first_output = next(c for c in channels if c["direction"] == "output")
    proto = EscalationProtocol()
    times = "×" if proto.nullify_tolerance_multiplier != int(proto.nullify_tolerance_multiplier) else ""
    comparison = {
        "protocol": {k: v for k, v in proto.to_dict().items() if k not in ("holdout_fraction", "min_holdout_ticks")},
        "gap_formula": GAP_FORMULA,
        "rules": [
            f"Flagged after {proto.flag_after_consecutive} consecutive readings beyond τ (the channel's tolerance).",
            f"Nullified after {proto.nullify_after_consecutive} consecutive readings beyond {proto.nullify_tolerance_multiplier:g}{times}τ.",
            f"An input outside its assured range {proto.flag_after_consecutive} times in a row flags the twin; "
            + ("it can also nullify it." if proto.envelope_can_nullify else "input-envelope violations never nullify."),
            f"Sensor faults (dropout, stuck ×{proto.stuck_after_identical}, a jump above {proto.spike_jump_pct:g}%) are data quality "
            "and never count as twin error.",
            "The gap is not evaluated when the prediction is missing or zero, or when any input of the twin is not clean "
            "(data quality or outside its assured range).",
        ],
        "source": "engine/protocol.py: EscalationProtocol (defaults sealed into every run), engine/readings.py: gap_pct, "
                  "engine/monitor.py: _evaluate_product",
    }
    return {
        "source": "Exported by ingest/export_rules.py from engine/readings.py (ALLOWED_FIELDS) and ingest/pipeline.py "
                  "(SCHEMA, REQUIRED_ATTRIBUTES, TIMESTAMP, REJECT_REASONS). Do not edit by hand.",
        "schema": SCHEMA,
        "allowed_fields": list(ALLOWED_FIELDS),
        "required_attributes": list(REQUIRED_ATTRIBUTES),
        "timestamp_pattern": TIMESTAMP.pattern,
        "reading_key": "first 32 hex characters of the SHA-256 of replay_id, run_id, tick, twin_id and channel_id, joined with a vertical bar",
        "reject_reasons": [{"code": code, "meaning": meaning} for code, meaning in REJECT_REASONS],
        "comparison": comparison,
        "example_project": {"label": "Example project", "name": project.name, "project_id": project.project_id,
                            "channels": channels,
                            "samples": {"plant_only": sample(first_input), "both": sample(first_output)}},
    }


def text() -> str:
    return json.dumps(build(), indent=1, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    if "--check" in sys.argv:
        raise SystemExit(0 if OUT.read_text(encoding="utf-8") == text() else 1)
    OUT.write_text(text(), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
