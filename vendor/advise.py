"""The twin owner's recommendation for a semi-autonomous adjustment -- the
owner's method, not the platform's. The platform only checks and records it.

Method: find the lowest setpoint on the control input (in 0.5-unit steps) that
the twin predicts gives at least ``margin_pct`` above the objective, but never
closer than ``edge_margin`` to the input's assured maximum (real inputs jitter,
so a setpoint on the edge would stray outside the assured range). If no such
setpoint exists, recommend the highest allowed one and say the objective is
not predicted to be met.
"""

from __future__ import annotations

from telemetry.models import TwinModel


def recommend(twin_type: str, model: TwinModel, pre_inputs: dict[str, float], control_channel: str,
              control_range: tuple[float, float], target_output: str, target_min: float,
              margin_pct: float = 2.0, edge_margin: float = 3.0) -> dict:
    lo, hi = control_range
    ceiling = hi - edge_margin
    goal = target_min * (1 + margin_pct / 100)
    current = pre_inputs[control_channel]
    candidates = []
    v = max(lo, round(current * 2) / 2)
    while v <= ceiling + 1e-9:
        candidates.append(v)
        v += 0.5
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
