"""Verification: is the twin internally coherent? The twin alone, no physical
data. Coherent is not the same as correct -- that is validation's job."""

from __future__ import annotations

import itertools
import math

from engine.ledger import sha256_hex
from engine.protocol import EscalationProtocol
from engine.registry import ProductTwin


def _sweep(twin: ProductTwin, levels: int) -> list[dict[str, float]]:
    axes = [[c.env_min + i * (c.env_max - c.env_min) / (levels - 1) for i in range(levels)] for c in twin.inputs]
    return [dict(zip((c.channel_id for c in twin.inputs), combo)) for combo in itertools.product(*axes)]


def verify(twin: ProductTwin, model, protocol: EscalationProtocol, levels: int = 5) -> dict:
    """``model`` is the twin under test: anything with ``predict(inputs)`` and
    ``version`` (a twin is only ever queried, never opened). Returns the verification record."""
    points = _sweep(twin, levels)
    failures = {"deterministic": [], "complete": [], "finite": [], "within_declared_output_ranges": []}
    for pt in points:
        first, second = model.predict(dict(pt)), model.predict(dict(pt))
        if first != second:
            failures["deterministic"].append(pt)
        for c in twin.outputs:
            v = first.get(c.channel_id)
            if v is None:
                failures["complete"].append({**pt, "missing": c.channel_id})
            elif not math.isfinite(v):
                failures["finite"].append({**pt, "channel": c.channel_id})
            elif not c.in_envelope(v):
                failures["within_declared_output_ranges"].append({**pt, "channel": c.channel_id, "value": v})
    checks = [
        {"check": name, "passed": not bad, "failures": len(bad), "first_failure": bad[0] if bad else None}
        for name, bad in failures.items()
    ]
    return {
        "twin_id": twin.design_twin_id,
        "twin_version": model.version,
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "test_points": len(points),
        "levels_per_input": levels,
        "test_inputs_sha256": sha256_hex(points),
        "envelope": twin.envelope_snapshot(),
        "escalation_protocol": protocol.to_dict(),
    }
