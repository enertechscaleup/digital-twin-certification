"""The telemetry generator.

Produces two kinds of synthetic data, for every channel of the motor and
compressor twins:

* **Bench** data -- a controlled sweep across each twin's certified input
  range, as a physical test bench would run before deployment. Used for
  verification and bench validation.
* **Field** data -- a live operational stream, one reading per channel per
  tick, with faults injected as a scenario describes. Used for field
  validation, escalation, and recalibration.

Each reading carries the physical reference and the twin prediction side by
side. The generator never computes gaps or certification status; the
verification engine does that from these readings.

Runs are fully reproducible: the same seed, scenario, and start time always
produce exactly the same data.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from telemetry.faults import Scenario
from telemetry.models import PhysicalModel, TwinModel

GENERATOR_VERSION = "0.1.0"
CONFIG_DIR = Path(__file__).parent / "config"
# Motor first: the compressor's speed input comes from the motor's output.
TWIN_ORDER = ("motor", "compressor")
DECIMALS = 4


def load_config(twin_type: str) -> dict:
    return json.loads((CONFIG_DIR / f"{twin_type}.json").read_text(encoding="utf-8"))


def _config_sha256(twin_type: str) -> str:
    return hashlib.sha256((CONFIG_DIR / f"{twin_type}.json").read_bytes()).hexdigest()


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, DECIMALS)


@dataclass
class Reading:
    """One channel's values at one tick (field) or one sample (bench)."""

    run_id: str
    kind: str  # "bench" | "field"
    tick: int
    timestamp: str  # ISO 8601, UTC
    operational_hours: float | None  # field only: simulated asset age
    twin_id: str
    twin_type: str
    twin_version: str
    channel_id: str
    direction: str  # "input" | "output"
    unit: str
    physical_value: float | None  # None = sensor dropout
    predicted_value: float | None  # None for input channels, or when the twin had no input
    split: str | None  # field only: "recalibration" | "held_out"
    test_point: int | None  # bench only: which point in the input sweep
    # GROUND TRUTH for testing the engine only: which faults were injected
    # into this reading. The verification engine must never read this field.
    injected_faults: list[str] = field(default_factory=list)


class TelemetryGenerator:
    def __init__(
        self,
        seed: int = 42,
        start_time: datetime | None = None,
        twins: dict[str, TwinModel] | None = None,
    ):
        self.seed = seed
        self.start_time = (start_time or datetime.now(timezone.utc)).replace(microsecond=0)
        self.configs = {t: load_config(t) for t in TWIN_ORDER}
        self.twins = twins or {t: TwinModel(t) for t in TWIN_ORDER}
        tick_seconds = {c["tick_seconds"] for c in self.configs.values()}
        if len(tick_seconds) != 1:
            raise ValueError("all twins must share one tick cadence")
        self.tick_seconds = tick_seconds.pop()

    # -- helpers ---------------------------------------------------------

    def _rng(self, purpose: str) -> random.Random:
        """A separate, seeded random stream per purpose, so changing one
        part of a scenario never reshuffles the randomness of another."""
        return random.Random(f"{self.seed}:{purpose}")

    def _timestamp(self, tick: int) -> str:
        return (self.start_time + timedelta(seconds=tick * self.tick_seconds)).isoformat().replace("+00:00", "Z")

    def _run_id(self, kind: str, name: str) -> str:
        digest = hashlib.sha256(f"{kind}|{name}|{self.seed}|{self.start_time.isoformat()}".encode()).hexdigest()
        return f"{kind}-{name}-{digest[:10]}"

    def manifest(self, run_id: str, kind: str, details: dict) -> dict:
        return {
            "run_id": run_id,
            "kind": kind,
            "generator_version": GENERATOR_VERSION,
            "seed": self.seed,
            "start_time": self._timestamp(0),
            "tick_seconds": self.tick_seconds,
            "twins": {
                t: {
                    "design_twin_id": self.configs[t]["design_twin_id"],
                    "operational_twin_id": self.configs[t]["operational_twin_id"],
                    "twin_version": self.twins[t].version,
                    "twin_params": self.twins[t].params,
                    "config_sha256": _config_sha256(t),
                }
                for t in TWIN_ORDER
            },
            "note": "injected_faults is ground truth for testing only; the verification engine must not read it.",
            **details,
        }

    # -- bench -----------------------------------------------------------

    def bench_run_id(self, twin_type: str) -> str:
        return self._run_id("bench", twin_type)

    def bench_sweep(self, twin_type: str, levels: int = 5, repeats: int = 3) -> Iterator[list[Reading]]:
        """Step every input across its certified range (``levels`` evenly
        spaced values each, all combinations), ``repeats`` samples per point.
        Bench inputs are exact setpoints; outputs carry sensor noise."""
        if levels < 2:
            raise ValueError("levels must be at least 2 to cover the envelope's min and max")
        cfg = load_config(twin_type)
        twin = self.twins[twin_type]
        physical = PhysicalModel(cfg, self._rng(f"bench-noise:{twin_type}"))
        run_id = self.bench_run_id(twin_type)
        inputs = [c for c in cfg["channels"] if c["direction"] == "input"]
        outputs = [c for c in cfg["channels"] if c["direction"] == "output"]
        axes = [
            [c["envelope"]["min"] + i * (c["envelope"]["max"] - c["envelope"]["min"]) / (levels - 1) for i in range(levels)]
            for c in inputs
        ]
        sample = 0
        for point, combo in enumerate(itertools.product(*axes)):
            setpoints = {c["channel_id"]: v for c, v in zip(inputs, combo)}
            predicted = twin.predict(setpoints)
            for _ in range(repeats):
                true_out = physical.true_outputs(setpoints, wear_pct={})
                batch = [
                    self._reading(run_id, "bench", sample, None, cfg["design_twin_id"], cfg, c,
                                  setpoints[c["channel_id"]], None, None, point, [])
                    for c in inputs
                ] + [
                    self._reading(run_id, "bench", sample, None, cfg["design_twin_id"], cfg, c,
                                  physical.sense(true_out[c["channel_id"]]), predicted[c["channel_id"]],
                                  None, point, [])
                    for c in outputs
                ]
                sample += 1
                yield batch

    # -- field -----------------------------------------------------------

    def field_run_id(self, scenario: Scenario) -> str:
        return self._run_id("field", scenario.name)

    def field_run(self, scenario: Scenario) -> Iterator[list[Reading]]:
        """One batch per tick, covering every channel of both operational twins."""
        run_id = self.field_run_id(scenario)
        hours_per_tick = scenario.operational_hours_per_tick or self.tick_seconds / 3600
        profile_rng = self._rng("field-profile")
        split_rng = self._rng("field-split")
        physical = {t: PhysicalModel(self.configs[t], self._rng(f"field-noise:{t}")) for t in TWIN_ORDER}
        last_reported: dict[tuple[str, str], float | None] = {}

        for tick in range(scenario.ticks):
            hours = tick * hours_per_tick
            # One split tag per tick, so each side gets complete snapshots.
            split = "held_out" if split_rng.random() < scenario.holdout_fraction else "recalibration"
            true_outputs: dict[str, dict[str, float]] = {}
            batch: list[Reading] = []

            for twin_type in TWIN_ORDER:
                cfg = self.configs[twin_type]
                faults: dict[str, list[str]] = defaultdict(list)
                inputs = [c for c in cfg["channels"] if c["direction"] == "input"]
                outputs = [c for c in cfg["channels"] if c["direction"] == "output"]
                linked = cfg.get("linked_inputs", {})

                # 1. The machine's true operating condition.
                true_in: dict[str, float] = {}
                measured: dict[str, float | None] = {}
                for c in inputs:
                    ch = c["channel_id"]
                    if ch in linked:
                        src = linked[ch]
                        true_in[ch] = true_outputs[src["from_twin"]][src["from_channel"]]
                    else:
                        p = cfg["operating_profile"][ch]
                        true_in[ch] = (
                            p["nominal"]
                            + p["swing"] * math.sin(2 * math.pi * tick / p["period_ticks"])
                            + profile_rng.gauss(0, p["jitter"])
                        )
                    for ev in scenario.envelope_violations:
                        if ev.twin_type == twin_type and ev.channel == ch and ev.active(tick):
                            true_in[ch] = ev.value
                            faults[ch].append(ev.label())
                            for o in outputs:
                                faults[o["channel_id"]].append(f"{ev.label()}:{ch}")
                    # Linked inputs are read by this machine's own sensor.
                    measured[ch] = physical[twin_type].sense(true_in[ch]) if ch in linked else true_in[ch]

                # 2. Wear, then the machine's true outputs.
                wear: dict[str, float] = defaultdict(float)
                for w in scenario.wear:
                    if w.twin_type == twin_type:
                        for ch, pct in w.wear_pct(tick, hours, hours_per_tick).items():
                            wear[ch] += pct
                            if pct:
                                faults[ch].append(w.label())
                true_out = physical[twin_type].true_outputs(true_in, wear)
                true_outputs[twin_type] = true_out
                for c in outputs:
                    measured[c["channel_id"]] = physical[twin_type].sense(true_out[c["channel_id"]])

                # 3. Sensor faults corrupt the reported readings only.
                for q in scenario.data_quality:
                    if q.twin_type == twin_type and q.active(tick):
                        measured[q.channel] = q.corrupt(measured[q.channel], last_reported.get((twin_type, q.channel)))
                        faults[q.channel].append(q.label())
                for ch, v in measured.items():
                    last_reported[(twin_type, ch)] = v

                # 4. The twin predicts from the readings it is actually fed.
                predicted = self.twins[twin_type].predict({c["channel_id"]: measured[c["channel_id"]] for c in inputs})

                for c in cfg["channels"]:
                    ch = c["channel_id"]
                    batch.append(
                        self._reading(run_id, "field", tick, hours, cfg["operational_twin_id"], cfg, c,
                                      measured[ch], predicted.get(ch), split, None, faults[ch])
                    )
            yield batch

    def _reading(self, run_id, kind, tick, hours, twin_id, cfg, channel, physical_value, predicted_value,
                 split, test_point, faults) -> Reading:
        return Reading(
            run_id=run_id,
            kind=kind,
            tick=tick,
            timestamp=self._timestamp(tick),
            operational_hours=_round(hours),
            twin_id=twin_id,
            twin_type=cfg["twin_type"],
            twin_version=self.twins[cfg["twin_type"]].version,
            channel_id=channel["channel_id"],
            direction=channel["direction"],
            unit=channel["unit"],
            physical_value=_round(physical_value),
            predicted_value=_round(predicted_value),
            split=split,
            test_point=test_point,
            injected_faults=list(faults),
        )
