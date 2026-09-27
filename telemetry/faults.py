"""The three fault injectors, each switched on deliberately by a scenario.

* ``WearDrift`` -- the real machine slowly drifts away from its twin as it
  ages. Drift is tied to *operational hours*, so a scenario can fast-forward
  wear (e.g. one tick = one day of operation) while the live stream still
  ticks every 2 real seconds.
* ``EnvelopeViolation`` -- the real machine is actually operated outside the
  assured input range.
* ``DataQualityFault`` -- a sensor misreports (spike, dropout, or stuck). The
  machine itself is fine; only the reading is wrong.

Each injector only changes the synthetic data. None of them computes gaps or
decides an assurance status -- that is the assurance engine's job.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DATA_QUALITY_KINDS = ("spike", "dropout", "stuck")


@dataclass(frozen=True)
class WearDrift:
    twin_type: str
    start_tick: int
    # Signed drift per channel, in percent per 1000 operational hours.
    # e.g. {"speed": -20, "vibration": 20}: speed falls, vibration rises.
    pct_per_1000_hours: dict[str, float] = field(default_factory=dict)
    # Optional cap on wear magnitude, in percent: wear grows until it reaches
    # this level, then holds steady (the component has settled into a worn state).
    max_abs_pct: float | None = None

    def label(self) -> str:
        return "wear_drift"

    def wear_pct(self, tick: int, hours_since_start: float, hours_per_tick: float) -> dict[str, float]:
        if tick < self.start_tick:
            return {}
        hours_worn = hours_since_start - self.start_tick * hours_per_tick
        wear = {ch: rate * hours_worn / 1000 for ch, rate in self.pct_per_1000_hours.items()}
        if self.max_abs_pct is not None:
            wear = {ch: max(-self.max_abs_pct, min(self.max_abs_pct, v)) for ch, v in wear.items()}
        return wear


@dataclass(frozen=True)
class EnvelopeViolation:
    twin_type: str
    channel: str
    start_tick: int
    duration_ticks: int
    value: float  # the true operating value forced for the duration

    def label(self) -> str:
        return "envelope_violation"

    def active(self, tick: int) -> bool:
        return self.start_tick <= tick < self.start_tick + self.duration_ticks


@dataclass(frozen=True)
class DataQualityFault:
    twin_type: str
    channel: str
    start_tick: int
    duration_ticks: int
    kind: str  # "spike" | "dropout" | "stuck"
    factor: float = 1.5  # spike only: reading multiplied by this

    def __post_init__(self) -> None:
        if self.kind not in DATA_QUALITY_KINDS:
            raise ValueError(f"unknown data-quality kind {self.kind!r}; expected one of {DATA_QUALITY_KINDS}")

    def label(self) -> str:
        return f"data_quality:{self.kind}"

    def active(self, tick: int) -> bool:
        return self.start_tick <= tick < self.start_tick + self.duration_ticks

    def corrupt(self, reading: float | None, previous_reading: float | None) -> float | None:
        if reading is None:
            return None
        if self.kind == "spike":
            return reading * self.factor
        if self.kind == "dropout":
            return None
        return previous_reading  # stuck: sensor keeps repeating its last value


@dataclass(frozen=True)
class RecalibrationRequest:
    """An operator's request, at ``at_tick``, to recalibrate a flagged or
    nullified Operational Twin. How the data is split is the platform's rule,
    not the operator's."""
    twin_type: str
    at_tick: int


@dataclass(frozen=True)
class Scenario:
    name: str
    ticks: int
    # Fast-forward knob for wear: how many operational hours each tick
    # represents. None means real time (tick_seconds / 3600).
    operational_hours_per_tick: float | None = None
    wear: tuple[WearDrift, ...] = ()
    envelope_violations: tuple[EnvelopeViolation, ...] = ()
    data_quality: tuple[DataQualityFault, ...] = ()
    recalibration: RecalibrationRequest | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "Scenario":
        return cls(
            name=d["name"],
            ticks=d["ticks"],
            operational_hours_per_tick=d.get("operational_hours_per_tick"),
            wear=tuple(WearDrift(**w) for w in d.get("wear", [])),
            envelope_violations=tuple(EnvelopeViolation(**e) for e in d.get("envelope_violations", [])),
            data_quality=tuple(DataQualityFault(**q) for q in d.get("data_quality", [])),
            recalibration=RecalibrationRequest(**d["recalibration"]) if d.get("recalibration") else None,
        )
