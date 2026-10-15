"""Writes the recorded result of one replay for the app's Integration panel
(web/src/platform/ingestion-demo.json), from that replay's receipt and engine reports.

Logical names only: no project ID or number, no bucket suffix, no job ID.

    python ingest/export_demo_result.py deck-assets/ingest-runs/r1015b
"""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web/src/platform/ingestion-demo.json"


def main() -> None:
    d = Path(sys.argv[1])
    rid = d.name
    receipt_path = d / f"{rid}.receipt.json"
    receipt = json.loads(receipt_path.read_text())
    if not receipt["complete"]:
        raise SystemExit("this replay is incomplete; only a complete replay is shown")
    reports = {m: json.loads(next(d.glob(f"*.{m}.report.json")).read_text()) for m in ("comparison-copy", "ingestion-labelled")}
    run = reports["comparison-copy"]["run"]
    pin = next(r for r in json.loads((ROOT / "app/config/runs.json").read_text())["runs"] if r["run"] == run)
    project = {"amr-fulfilment-cell": "Fulfilment cell", "oil-gas-compressor-train": "Compressor train"}[pin["project_id"]]
    readings = (d / receipt["validated"]["readings_file"]).read_text().splitlines()
    example_line = next(l for l in readings if json.loads(l)["direction"] == "output")
    example = json.loads(example_line)
    sys.path.insert(0, str(ROOT / "ingest"))
    from publisher import attributes
    example_attrs = attributes(example_line.encode(), rid, example)
    date = receipt["sealed_at"][:10]
    c = receipt["counts"]
    known = {"reading", "identical_duplicate", "end_marker"}
    other = {k: v for k, v in c["published_by_category"].items() if k not in known and not k.startswith("invalid_")}
    if other:
        raise SystemExit(f"published categories the panel does not show: {other}")
    result = {
        "label": f"Streaming ingestion: demonstrated on replayed synthetic data on {date}. Not live telemetry. Not tested at scale.",
        "date": date,
        "replay_id": rid,
        "replayed_run": {"project": project, "run": run, "title": pin["title"]},
        "topic": "dtc-ingest-readings",
        "dead_letter_topic": "dtc-ingest-readings-dlq",
        "bigquery_table": "dtc_ingest.readings_validated",
        "region": "us-central1",
        "pipeline": {"service": "Dataflow", "sdk": "Apache Beam, Python", "mode": "streaming",
                     "workers": 1, "machine": receipt["pipeline"]["worker"], "stopped": "drained after the replay"},
        "counts": {
            "published": c["published"],
            "readings": c["published_by_category"].get("reading", 0),
            "identical_duplicates_sent": c["published_by_category"].get("identical_duplicate", 0),
            "end_of_replay_markers": c["published_by_category"].get("end_marker", 0),
            "invalid_messages_sent": sum(v for k, v in c["published_by_category"].items() if k.startswith("invalid_")),
            "raw_messages_stored": c["raw_messages"],
            "validated_readings": c["validated_readings"],
            "ticks": c["ticks"],
            "dead_lettered": c["dead_lettered"],
            "bigquery_rows": c["bigquery_rows"],
        },
        "readings_file_identical_to_sealed": reports["comparison-copy"]["readings_file_identical_to_sealed"],
        "engine": {
            "comparison_copy": {"head": reports["comparison-copy"]["head"], "pin_head": pin["core_ledger_head_hash"],
                                "head_identical": reports["comparison-copy"]["level2_same_head"],
                                "same_decisions": reports["comparison-copy"]["level1_same_decisions"]},
            "ingestion_labelled": {"same_decisions": reports["ingestion-labelled"]["level1_same_decisions"],
                                   "head_identical": reports["ingestion-labelled"]["level2_same_head"]},
        },
        "example_message": {"data": example, "attributes": example_attrs},
        "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        "other_tests": [
            "8 malformed messages, one per reject reason: all 8 in the dead-letter topic, none in BigQuery",
            "a reading published 4 minutes late: its tick re-fired with the reading; same result",
            "a conflicting copy and a reading sent after the job was stopped: the engine refused the incomplete ticks",
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
