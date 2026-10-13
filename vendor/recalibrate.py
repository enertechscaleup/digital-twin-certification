"""The owner's recalibration method -- the owner's business, not the platform's.

Method: fit one multiplicative correction per output channel, in order, to
the most recent ``fit_last_ticks`` of the data released, scaling that output's
parameter group. Where one output's formula depends on an earlier output
(motor vibration on speed; compressor temperature on pressure; a mobile robot's
deliveries on its travel speed), the owner
knows that dependence is on the machine's as-designed behaviour, so the
earlier correction is undone inside that term before the later output is
fitted. Without this, a single correction factor fitted at one operating
point does not hold at others. Then restate the twin's expected output ranges by sweeping
the recalibrated twin across the assured input envelope.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from telemetry.models import OUTPUT_CHANNELS, TwinModel

# Which parameters shape which output -- knowledge only the twin's owner has.
PARAM_GROUPS = {
    "motor": {"speed": ("speed_per_volt", "speed_per_amp"),
              "vibration": ("vib_base", "vib_per_rpm_sq", "vib_per_amp")},
    "compressor": {"pressure": ("p_base", "p_per_rpm", "p_per_flow"),
                   "temperature": ("t_ambient", "t_per_bar", "t_per_flow")},
    "dispatcher": {"tasks_1": ("t1_base", "t1_per_line"), "tasks_2": ("t2_base", "t2_per_line")},
    "amr1": {"speed": ("s_gain", "s_per_volt", "s_per_task"), "deliveries": ("d_base", "d_per_speed")},
    "amr2": {"speed": ("s_gain", "s_per_volt", "s_per_task"), "deliveries": ("d_base", "d_per_speed")},
    "pick_station": {"pick_rate": ("picks_per_tote",), "cycle_time": ("c_base", "c_per_tote")},
}


# Parameters whose term depends on an earlier output: (that output, power of it in the term).
# Undoing the earlier output's correction k here means multiplying by k ** -power.
COUPLED_TERMS = {
    "motor": {"vib_per_rpm_sq": ("speed", 2)},
    "compressor": {"t_per_bar": ("pressure", 1)},
    "amr1": {"d_per_speed": ("speed", 1)},
    "amr2": {"d_per_speed": ("speed", 1)},
}


@dataclass(frozen=True)
class Submission:
    twin_type: str
    twin_version: str
    params: dict[str, float]
    declared_output_ranges: dict[str, dict[str, float]]
    method: str
    fitted_on_ticks: tuple[int, int]

    def to_dict(self) -> dict:
        return {
            "twin_type": self.twin_type, "twin_version": self.twin_version, "params": self.params,
            "declared_output_ranges": self.declared_output_ranges, "method": self.method,
            "fitted_on_ticks": list(self.fitted_on_ticks),
        }


def _valid(v) -> bool:
    return isinstance(v, (int, float)) and v == v and v not in (float("inf"), float("-inf"))


def recalibrate(twin_type: str, current: TwinModel, released: list[dict],
                input_envelopes: dict[str, tuple[float, float]], new_version: str,
                fit_last_ticks: int = 10) -> Submission:
    """``released``: the readings the platform released (this twin only)."""
    ticks = sorted({r["tick"] for r in released})
    fit_ticks = set(ticks[-fit_last_ticks:])
    by_tick: dict[int, dict[str, float]] = {}
    for r in released:
        if r["tick"] in fit_ticks and _valid(r["physical_value"]):
            by_tick.setdefault(r["tick"], {})[r["channel_id"]] = r["physical_value"]
    input_names = list(input_envelopes)
    samples = [v for v in by_tick.values() if all(n in v for n in input_names)]

    params = dict(current.params)
    corrections: dict[str, float] = {}
    for output in OUTPUT_CHANNELS[twin_type]:
        for p, (upstream, power) in COUPLED_TERMS.get(twin_type, {}).items():
            if p in PARAM_GROUPS[twin_type][output] and upstream in corrections:
                params[p] *= corrections[upstream] ** -power
        model = TwinModel(twin_type, params)
        ratios = [s[output] / model.predict({n: s[n] for n in input_names})[output]
                  for s in samples if output in s]
        if not ratios:
            continue
        k = sum(ratios) / len(ratios)
        corrections[output] = k
        for p in PARAM_GROUPS[twin_type][output]:
            params[p] *= k

    new = TwinModel(twin_type, params, new_version)
    levels = 5
    axes = [[lo + i * (hi - lo) / (levels - 1) for i in range(levels)] for lo, hi in input_envelopes.values()]
    sweep = [new.predict(dict(zip(input_names, combo))) for combo in itertools.product(*axes)]
    ranges = {}
    for output in OUTPUT_CHANNELS[twin_type]:
        values = [p[output] for p in sweep]
        lo, hi = min(values), max(values)
        pad = 0.05 * (hi - lo) + 0.02 * abs(hi)
        ranges[output] = {"min": round(lo - pad, 2), "max": round(hi + pad, 2)}

    return Submission(
        twin_type=twin_type, twin_version=new_version, params={k: round(v, 10) for k, v in params.items()},
        declared_output_ranges=ranges,
        method=(f"per-output multiplicative correction fitted to the last {len(fit_ticks)} ticks released; "
                "coupled terms referenced to as-designed upstream behaviour"),
        fitted_on_ticks=(min(fit_ticks), max(fit_ticks)),
    )


def owner_for_platform(twin_type: str, current: TwinModel, released: list[dict],
                       input_envelopes: dict[str, tuple[float, float]]) -> dict:
    """The owner as the platform calls it: bumps the twin's minor version."""
    major, minor, *_ = (current.version.split(".") + ["0", "0"])
    new_version = f"{major}.{int(minor) + 1}.0"
    return recalibrate(twin_type, current, released, input_envelopes, new_version).to_dict()
