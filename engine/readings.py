"""The boundary between incoming telemetry and the engine.

``ingest`` keeps only the fields the engine is allowed to see. In particular it
drops ``injected_faults`` -- the generator's ground-truth test labels -- so no
assurance decision can ever depend on them.
"""

from __future__ import annotations

import math

ALLOWED_FIELDS = (
    "run_id", "kind", "tick", "timestamp", "operational_hours", "twin_id", "twin_version",
    "channel_id", "direction", "unit", "physical_value", "predicted_value", "test_point",
)


def ingest(reading: dict) -> dict:
    return {k: reading.get(k) for k in ALLOWED_FIELDS}


def is_valid_number(v) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(v)


def gap_pct(physical: float, predicted: float) -> float:
    """Absolute gap, as a percentage of the twin's prediction."""
    return 100 * abs(physical - predicted) / abs(predicted)
