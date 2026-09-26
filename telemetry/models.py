"""Made-up formulas for the two synthetic machines.

Every machine is described twice:

* ``TwinModel`` -- what the digital twin predicts. A clean formula, driven by
  the *measured* inputs it is fed.
* ``PhysicalModel`` -- the "real" machine. The same formula, driven by the
  *true* operating condition, plus a small fixed bias (no twin is perfect),
  wear, extra divergence when operated outside its certified envelope, and
  random sensor noise.

The formulas are illustrative only and make no engineering claim. The platform
is domain-agnostic: it certifies the gap between these two, not the physics.
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


FORMULAS: dict[str, Callable[[Inputs, dict[str, float]], Outputs]] = {
    "motor": _motor,
    "compressor": _compressor,
}

OUTPUT_CHANNELS: dict[str, tuple[str, ...]] = {
    "motor": ("speed", "vibration"),
    "compressor": ("pressure", "temperature"),
}

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
}


class TwinModel:
    """The digital twin's prediction. Parameters are versioned so a
    recalibrated twin (Real2Sim) can be swapped in as a new version later."""

    def __init__(self, twin_type: str, params: dict[str, float] | None = None, version: str = "1.0.0"):
        self.twin_type = twin_type
        self.params = dict(params or DEFAULT_PARAMS[twin_type])
        self.version = version

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
        """Outside its certified envelope the real machine starts behaving in
        ways the twin was never validated for. Grows with how far outside."""
        total = 0.0
        for name, env in self.input_envelopes.items():
            span = env["max"] - env["min"]
            value = true_inputs[name]
            excess = max(0.0, value - env["max"], env["min"] - value)
            total += self.divergence_pct_per_span * excess / span
        return total
