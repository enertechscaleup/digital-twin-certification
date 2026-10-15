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


def build() -> dict:
    from engine.readings import ALLOWED_FIELDS
    from engine.registry import load_registry
    from pipeline import ALLOWED_FIELDS as PIPELINE_FIELDS, REJECT_REASONS, REQUIRED_ATTRIBUTES, SCHEMA, TIMESTAMP, reading_key
    from projects import load_project
    if tuple(PIPELINE_FIELDS) != tuple(ALLOWED_FIELDS):
        raise SystemExit("the pipeline's fields differ from the engine's")
    project = load_project(ROOT / EXAMPLE_PROJECT)
    registry = load_registry(project)
    channels = [{"twin_id": p.operational_twin_id, "twin": p.twin_type, "channel_id": c.channel_id, "name": c.name,
                 "direction": c.direction, "unit": c.unit, "range": [c.env_min, c.env_max]}
                for p in registry.products.values() for c in p.channels]
    first_output = next(c for c in channels if c["direction"] == "output")
    lo, hi = first_output["range"]
    data = {"run_id": f"field-{project.project_id}-sample", "kind": "field", "tick": 0, "timestamp": "2026-10-01T00:00:00Z",
            "operational_hours": 0, "twin_id": first_output["twin_id"], "twin_version": "1.0.0",
            "channel_id": first_output["channel_id"], "direction": "output", "unit": first_output["unit"],
            "physical_value": round((lo + hi) / 2, 4), "predicted_value": round((lo + hi) / 2 * 1.01, 4), "test_point": None}
    data_text = json.dumps(data)
    attributes = {"schema": SCHEMA, "source": "sample", "replay_id": "sample", "event_ts": data["timestamp"],
                  "reading_key": reading_key("sample", data["run_id"], 0, data["twin_id"], data["channel_id"]),
                  "content_sha256": hashlib.sha256(data_text.encode()).hexdigest()}
    return {
        "source": "Exported by ingest/export_rules.py from engine/readings.py (ALLOWED_FIELDS) and ingest/pipeline.py "
                  "(SCHEMA, REQUIRED_ATTRIBUTES, TIMESTAMP, REJECT_REASONS). Do not edit by hand.",
        "schema": SCHEMA,
        "allowed_fields": list(ALLOWED_FIELDS),
        "required_attributes": list(REQUIRED_ATTRIBUTES),
        "timestamp_pattern": TIMESTAMP.pattern,
        "reading_key": "first 32 hex characters of the SHA-256 of replay_id, run_id, tick, twin_id and channel_id, joined with a vertical bar",
        "reject_reasons": [{"code": code, "meaning": meaning} for code, meaning in REJECT_REASONS],
        "example_project": {"label": "Example project", "name": project.name, "project_id": project.project_id,
                            "channels": channels, "sample": {"data": data_text, "attributes": attributes}},
    }


def text() -> str:
    return json.dumps(build(), indent=1, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    if "--check" in sys.argv:
        raise SystemExit(0 if OUT.read_text(encoding="utf-8") == text() else 1)
    OUT.write_text(text(), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
