"""Twin registration: which twins exist, their channels and assured envelopes,
and how product twins compose into the system twin. Built from a project file
(projects/), so neither the twins nor their order are fixed in code."""

from __future__ import annotations

from dataclasses import dataclass

from projects import Project, load_project


@dataclass(frozen=True)
class Channel:
    channel_id: str
    name: str
    unit: str
    direction: str  # "input" | "output"
    env_min: float
    env_max: float
    tolerance_pct: float

    def in_envelope(self, value: float) -> bool:
        return self.env_min <= value <= self.env_max

    def envelope_dict(self) -> dict:
        return {"min": self.env_min, "max": self.env_max, "tolerance_pct": self.tolerance_pct, "unit": self.unit}


@dataclass(frozen=True)
class ProductTwin:
    twin_type: str
    design_twin_id: str
    operational_twin_id: str
    asset_id: str
    vendor: str
    twin_mode: str
    channels: tuple[Channel, ...]

    @property
    def inputs(self) -> tuple[Channel, ...]:
        return tuple(c for c in self.channels if c.direction == "input")

    @property
    def outputs(self) -> tuple[Channel, ...]:
        return tuple(c for c in self.channels if c.direction == "output")

    def envelope_snapshot(self) -> dict:
        return {c.channel_id: {"direction": c.direction, **c.envelope_dict()} for c in self.channels}


@dataclass(frozen=True)
class SystemTwin:
    design_system_twin_id: str
    operational_system_twin_id: str
    constituents: tuple[str, ...]  # twin types
    output_constituents: tuple[str, ...]  # constituents whose outputs are the system's outputs
    connections: tuple[dict, ...] = ()  # which constituent output feeds which constituent input
    test_levels: int = 5  # joint composition test: grid levels per external input


@dataclass(frozen=True)
class Registry:
    products: dict[str, ProductTwin]  # keyed by twin type, in processing order (feeding twins first)
    system: SystemTwin

    def by_operational_id(self, twin_id: str) -> ProductTwin:
        return next(p for p in self.products.values() if p.operational_twin_id == twin_id)


def _product(cfg: dict) -> ProductTwin:
    return ProductTwin(
        twin_type=cfg["twin_type"],
        design_twin_id=cfg["design_twin_id"],
        operational_twin_id=cfg["operational_twin_id"],
        asset_id=cfg["asset_id"],
        vendor=cfg["vendor"],
        twin_mode=cfg["twin_mode"],
        channels=tuple(
            Channel(c["channel_id"], c["name"], c["unit"], c["direction"],
                    c["envelope"]["min"], c["envelope"]["max"], c["tolerance_pct"])
            for c in cfg["channels"]
        ),
    )


def load_registry(project: Project | None = None) -> Registry:
    """``project`` defaults to the oil & gas compressor train."""
    p = project or load_project()
    return Registry(
        products={t: _product(p.config(t)) for t in p.processing_order},
        system=SystemTwin(
            design_system_twin_id=p.design_system_twin_id,
            operational_system_twin_id=p.operational_system_twin_id,
            constituents=p.processing_order,
            output_constituents=p.output_constituents,
            connections=p.connections,
            test_levels=p.test_levels,
        ),
    )
