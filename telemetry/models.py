"""Made-up formulas for the synthetic machines.

Every machine is described twice:

* ``TwinModel`` -- what the digital twin predicts. A clean formula, driven by
  the *measured* inputs it is fed.
* ``PhysicalModel`` -- the "real" machine. The same formula, driven by the
  *true* operating condition, plus a small fixed bias (no twin is perfect),
  wear, extra divergence when operated outside its assured envelope, and
  random sensor noise.

The formulas are illustrative only and make no engineering claim. The platform
is domain-agnostic: it assures the gap between these two, not the physics.
"""

from __future__ import annotations

import random
from typing import Callable

Inputs = dict[str, float]
Outputs = dict[str, float]


def _motor(inputs: Inputs, p: dict[str, float]) -> Outputs:
    speed = p["speed_per_volt"] * inputs["volt"] + p["speed_per_amp"] * inputs["current"]
    vibration = p["vib_base"] + p["vib_per_rpm_sq"] * speed**2 + p["vib_per_amp"] * inputs["current"]
    return {"speed": speed, "vibration": vibration}


def _compressor(inputs: Inputs, p: dict[str, float]) -> Outputs:
    pressure = p["p_base"] + p["p_per_rpm"] * inputs["speed"] + p["p_per_flow"] * inputs["flow"]
    temperature = p["t_ambient"] + p["t_per_bar"] * pressure + p["t_per_flow"] * inputs["flow"]
    return {"pressure": pressure, "temperature": temperature}


def _dispatcher(inputs: Inputs, p: dict[str, float]) -> Outputs:
    # A fleet dispatcher splits incoming order lines into tasks for each robot.
    return {"tasks_1": p["t1_base"] + p["t1_per_line"] * inputs["order_rate"],
            "tasks_2": p["t2_base"] + p["t2_per_line"] * inputs["order_rate"]}


def _amr(inputs: Inputs, p: dict[str, float]) -> Outputs:
    # An autonomous mobile robot: travel speed follows its speed setpoint, scaled by battery
    # voltage and slowed slightly by its task load; the share of tasks delivered rises with speed.
    speed = (inputs["speed_setpoint"] * (p["s_gain"] + p["s_per_volt"] * (inputs["battery"] - 48.0))
             - p["s_per_task"] * inputs["task_rate"])
    deliveries = inputs["task_rate"] * (p["d_base"] + p["d_per_speed"] * speed)
    return {"speed": speed, "deliveries": deliveries}


def _pick_station(inputs: Inputs, p: dict[str, float]) -> Outputs:
    totes = inputs["arrivals_1"] + inputs["arrivals_2"]
    return {"pick_rate": p["picks_per_tote"] * totes,
            "cycle_time": p["c_base"] - p["c_per_tote"] * totes}


FORMULAS: dict[str, Callable[[Inputs, dict[str, float]], Outputs]] = {
    "motor": _motor,
    "compressor": _compressor,
    "dispatcher": _dispatcher,
    # Two robots of the same model: two twins, one formula.
    "amr1": _amr,
    "amr2": _amr,
    "pick_station": _pick_station,
}

# Each formula's declared identifier, sealed into every twin version's fingerprint. Changing
# what a formula computes means declaring a new identifier here, never editing it in place;
# formatting or refactoring the code leaves the identifier (and so the fingerprint) unchanged.
FORMULA_IDS: dict[str, str] = {
    "motor": "synthetic-motor/1",
    "compressor": "synthetic-compressor/1",
    "dispatcher": "synthetic-dispatcher/1",
    "amr1": "synthetic-amr/1",
    "amr2": "synthetic-amr/1",
    "pick_station": "synthetic-pick-station/1",
}

OUTPUT_CHANNELS: dict[str, tuple[str, ...]] = {
    "motor": ("speed", "vibration"),
    "compressor": ("pressure", "temperature"),
    "dispatcher": ("tasks_1", "tasks_2"),
    "amr1": ("speed", "deliveries"),
    "amr2": ("speed", "deliveries"),
    "pick_station": ("pick_rate", "cycle_time"),
}

_AMR_PARAMS = {"s_gain": 0.98, "s_per_volt": 0.01, "s_per_task": 0.001, "d_base": 0.35, "d_per_speed": 0.45}

DEFAULT_PARAMS: dict[str, dict[str, float]] = {
    "motor": {
        "speed_per_volt": 3.75,
        "speed_per_amp": -5.0,
        "vib_base": 0.5,
        "vib_per_rpm_sq": 1.2e-6,
        "vib_per_amp": 0.02,
    },
    "compressor": {
        "p_base": 1.5,
        "p_per_rpm": 0.0035,
        "p_per_flow": -0.12,
        "t_ambient": 25.0,
        "t_per_bar": 9.0,
        "t_per_flow": 0.3,
    },
    "dispatcher": {"t1_base": 10.0, "t1_per_line": 0.1, "t2_base": 12.0, "t2_per_line": 0.095},
    "amr1": dict(_AMR_PARAMS),
    "amr2": dict(_AMR_PARAMS),
    "pick_station": {"picks_per_tote": 4.6, "c_base": 12.0, "c_per_tote": 0.03},
}


class TwinModel:
    """The digital twin's prediction. Parameters are versioned so a
    recalibrated twin (Real2Sim) can be swapped in as a new version later."""

    def __init__(self, twin_type: str, params: dict[str, float] | None = None, version: str = "1.0.0"):
        self.twin_type = twin_type
        self.params = dict(params or DEFAULT_PARAMS[twin_type])
        self.version = version

    @property
    def formula_id(self) -> str:
        return FORMULA_IDS[self.twin_type]

    def predict(self, measured_inputs: dict[str, float | None]) -> dict[str, float | None]:
        if any(v is None for v in measured_inputs.values()):
            # A missing input reading means the twin cannot make a prediction.
            return {name: None for name in OUTPUT_CHANNELS[self.twin_type]}
        return FORMULAS[self.twin_type](measured_inputs, self.params)  # type: ignore[arg-type]


class PhysicalModel:
    """The "real" machine: what a real sensor (or test bench) would report."""

    def __init__(self, config: dict, rng: random.Random):
        self.twin_type = config["twin_type"]
        self.params = DEFAULT_PARAMS[self.twin_type]
        self.noise_pct = config["physical_noise_pct"]
        self.bias_pct = config.get("physical_bias_pct", {})
        self.divergence_pct_per_span = config.get("out_of_envelope_divergence_pct_per_span", 0.0)
        self.input_envelopes = {
            c["channel_id"]: c["envelope"] for c in config["channels"] if c["direction"] == "input"
        }
        self.rng = rng

    def true_outputs(self, true_inputs: Inputs, wear_pct: dict[str, float]) -> Outputs:
        """The machine's actual behaviour, before a sensor reads it."""
        clean = FORMULAS[self.twin_type](true_inputs, self.params)
        divergence = self._out_of_envelope_divergence_pct(true_inputs)
        return {
            name: value
            * (1 + self.bias_pct.get(name, 0.0) / 100)
            * (1 + wear_pct.get(name, 0.0) / 100)
            * (1 - divergence / 100)
            for name, value in clean.items()
        }

    def sense(self, true_value: float) -> float:
        """A sensor reading of a true value: adds random noise."""
        return true_value * (1 + self.rng.gauss(0, self.noise_pct / 100))

    def _out_of_envelope_divergence_pct(self, true_inputs: Inputs) -> float:
        """Outside its assured envelope the real machine starts behaving in
        ways the twin was never validated for. Grows with how far outside."""
        total = 0.0
        for name, env in self.input_envelopes.items():
            span = env["max"] - env["min"]
            value = true_inputs[name]
            excess = max(0.0, value - env["max"], env["min"] - value)
            total += self.divergence_pct_per_span * excess / span
        return total
