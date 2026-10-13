"""The twin owner's recommendation for a semi-autonomous adjustment -- the
owner's method, not the platform's. The platform only checks and records it.

Method: find the lowest setpoint on the control input (in ``step`` units) that
the twin predicts gives at least ``margin_pct`` above the objective, but never
closer than ``edge_margin`` to the input's assured maximum (real inputs jitter,
so a setpoint on the edge would stray outside the assured range). If no such
setpoint exists, recommend the highest allowed one and say the objective is
not predicted to be met. Step and edge margin are in the control input's own
units, so each owner sets them for its twin (``SETPOINT_GRID``).
"""

from __future__ import annotations

from telemetry.models import TwinModel

# The owner's setpoint grid per twin type: (step, edge margin), in the control input's units.
# Default: 0.5-unit steps kept 3 units below the maximum (the motor's supply voltage, in V).
SETPOINT_GRID = {
    "amr1": (0.02, 0.1),  # speed setpoint, m/s
    "amr2": (0.02, 0.1),
}
DEFAULT_GRID = (0.5, 3.0)


def recommend(twin_type: str, model: TwinModel, pre_inputs: dict[str, float], control_channel: str,
              control_range: tuple[float, float], target_output: str, target_min: float,
              margin_pct: float = 2.0, edge_margin: float | None = None) -> dict:
    step, default_edge = SETPOINT_GRID.get(twin_type, DEFAULT_GRID)
    edge_margin = default_edge if edge_margin is None else edge_margin
    lo, hi = control_range
    ceiling = hi - edge_margin
    goal = target_min * (1 + margin_pct / 100)
    current = pre_inputs[control_channel]
    base = max(lo, round(current / step) * step)
    candidates = []
    i = 0
    while base + i * step <= ceiling + 1e-9:
        candidates.append(round(base + i * step, 6))
        i += 1
    choice, meets = None, False
    for v in candidates:
        if model.predict({**pre_inputs, control_channel: v})[target_output] >= goal:
            choice, meets = v, True
            break
    if choice is None:
        choice = ceiling
    predicted = model.predict({**pre_inputs, control_channel: choice})
    return {
        "control_channel": control_channel,
        "from": round(current, 4),
        "to": choice,
        "predicted_end_state": {k: round(val, 4) for k, val in predicted.items()},
        "predicted_to_meet_objective": predicted[target_output] >= target_min,
        "predicted_to_meet_margin": meets,
        "twin_version": model.version,
        "method": (f"lowest {control_channel} setpoint predicted to give {margin_pct:g}% above the objective, "
                   f"kept at least {edge_margin:g} below the assured maximum"),
    }
