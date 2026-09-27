"""Bench validation: does the twin match physical test-bench evidence within
tolerance across the assured input range? The same gap measure is used later
for field validation."""

from __future__ import annotations

from engine.ledger import sha256_hex
from engine.readings import gap_pct, is_valid_number
from engine.registry import ProductTwin


def bench_validate(twin: ProductTwin, readings: list[dict]) -> dict:
    """``readings`` are ingested bench readings for this twin's design twin."""
    per_channel = {}
    for c in twin.outputs:
        rows = [r for r in readings if r["channel_id"] == c.channel_id]
        valid = [r for r in rows if is_valid_number(r["physical_value"]) and is_valid_number(r["predicted_value"])
                 and r["predicted_value"] != 0]
        gaps = [gap_pct(r["physical_value"], r["predicted_value"]) for r in valid]
        per_channel[c.channel_id] = {
            "samples": len(gaps),
            "tolerance_pct": c.tolerance_pct,
            "max_gap_pct": round(max(gaps), 4) if gaps else None,
            "mean_gap_pct": round(sum(gaps) / len(gaps), 4) if gaps else None,
            "over_tolerance": sum(g > c.tolerance_pct for g in gaps),
            "invalid_readings": len(rows) - len(valid),
        }
    passed = all(ch["samples"] > 0 and ch["over_tolerance"] == 0 and ch["invalid_readings"] == 0
                 for ch in per_channel.values())
    return {
        "twin_id": twin.design_twin_id,
        "passed": passed,
        "rule": "every bench output reading valid and within its channel tolerance",
        "per_channel": per_channel,
        "readings": len(readings),
        "readings_sha256": sha256_hex(readings),
    }
