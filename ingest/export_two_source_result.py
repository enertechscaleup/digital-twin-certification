"""Writes the recorded result of the two-source key test for the app (web/src/platform/ingestion-two-source.json)
from that replay's receipt and engine reports. Logical names only: no project ID, bucket suffix or job ID.

    python ingest/export_two_source_result.py deck-assets/ingest-runs/t1015a
"""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web/src/platform/ingestion-two-source.json"


def main() -> None:
    d = Path(sys.argv[1])
    rid = d.name
    receipt_path = d / f"{rid}.receipt.json"
    receipt = json.loads(receipt_path.read_text())
    if not receipt["complete"] or receipt["pipeline"].get("path") != "two-source":
        raise SystemExit("only a complete two-source replay is shown")
    reports = {m: json.loads(next(d.glob(f"*.{m}.report.json")).read_text()) for m in ("comparison-copy", "ingestion-labelled")}
    run = reports["comparison-copy"]["run"]
    pin = next(r for r in json.loads((ROOT / "app/config/runs.json").read_text())["runs"] if r["run"] == run)
    c = receipt["counts"]
    result = {
        "date": receipt["sealed_at"][:10],
        "replay_id": rid,
        "replayed_run": {"run": run, "title": pin["title"]},
        "shared_tick_index": "Both publishers replayed the same sealed synthetic run and shared its tick index.",
        "topics": {"plant": "dtc-ingest-plant", "twin": "dtc-ingest-twin"},
        "tables": ["dtc_ingest.plant_validated", "dtc_ingest.twin_validated", "dtc_ingest.joined_readings"],
        "counts": {"validated_by_side": c["validated_by_side"], "joined_readings": c["joined_readings"], "ticks": c["ticks"],
                   "dead_lettered": c["dead_lettered"], "bigquery_rows": c["bigquery_rows"]},
        "joined_identical_to_sealed": reports["comparison-copy"]["readings_file_identical_to_sealed"],
        "engine": {"comparison_copy_head_identical": reports["comparison-copy"]["level2_same_head"],
                   "pin_head": pin["core_ledger_head_hash"], "head": reports["comparison-copy"]["head"],
                   "ingestion_labelled_same_decisions": reports["ingestion-labelled"]["level1_same_decisions"],
                   "ingestion_labelled_head_identical": reports["ingestion-labelled"]["level2_same_head"]},
        "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
    }
    OUT.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
