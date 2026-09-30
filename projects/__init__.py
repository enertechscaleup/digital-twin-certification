"""Project configuration: which twins a project connects, and how they compose.

A project file names its twins (each pointing at the twin's own config file,
which is never modified) and its composition: which output feeds which input,
and which twins produce the system twin's outputs. The processing order is
worked out from those connections, so no twin order is fixed in code.

The loader only reads and checks configuration. It makes no assurance
decision and changes nothing in the engine's rules.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

PROJECTS_DIR = Path(__file__).parent
DEFAULT_PROJECT = PROJECTS_DIR / "compressor_train.json"
SCHEMA_VERSION = 1
# The only gap definition this version of the platform supports (engine/readings.py gap_pct).
GAP_METRICS = ("relative_pct_of_prediction",)
TWIN_MODES = ("observational", "semi_autonomous")
ROLES = ("product", "controller")


class ProjectError(ValueError):
    def __init__(self, path: Path, issues: list[str]):
        self.path, self.issues = path, issues
        super().__init__(f"{path.name}: " + "; ".join(issues))


@dataclass(frozen=True)
class ProjectTwin:
    twin_type: str
    name: str
    role: str  # descriptive only: a controller follows the same cascade rules as any twin
    config_path: Path
    config: dict
    registry_id: str | None = None
    asset_kind: str | None = None


@dataclass(frozen=True)
class Project:
    path: Path
    project_id: str
    name: str
    domain: str
    summary: str
    gap_metric: str
    twins: tuple[ProjectTwin, ...]  # in processing order
    system_name: str
    system_description: str
    design_system_twin_id: str
    operational_system_twin_id: str
    output_constituents: tuple[str, ...]
    connections: tuple[dict, ...]

    @property
    def processing_order(self) -> tuple[str, ...]:
        return tuple(t.twin_type for t in self.twins)

    def twin(self, twin_type: str) -> ProjectTwin:
        return next(t for t in self.twins if t.twin_type == twin_type)

    def config(self, twin_type: str) -> dict:
        return self.twin(twin_type).config

    def config_sha256(self, twin_type: str) -> str:
        return hashlib.sha256(self.twin(twin_type).config_path.read_bytes()).hexdigest()

    def linked_inputs(self, twin_type: str) -> dict[str, dict]:
        """Inputs of this twin fed by another twin's output: {input: {from_twin, from_channel}}."""
        return {c["to_channel"]: {"from_twin": c["from_twin"], "from_channel": c["from_channel"]}
                for c in self.connections if c["to_twin"] == twin_type}

    @property
    def entry_twins(self) -> tuple[str, ...]:
        """Twins with no incoming connection: visible and meaningful on their own, before the rest
        of the project is connected (e.g. the motor before the compressor is registered)."""
        fed = {c["to_twin"] for c in self.connections}
        return tuple(t.twin_type for t in self.twins if t.twin_type not in fed)


def list_projects(directory: Path = PROJECTS_DIR) -> list[Project]:
    """Every project file in ``directory``, loaded and checked, sorted by project id."""
    projects = [load_project(f) for f in sorted(directory.glob("*.json"))]
    return sorted(projects, key=lambda p: p.project_id)


def find_project(project_id: str, directory: Path = PROJECTS_DIR) -> Project | None:
    return next((p for p in list_projects(directory) if p.project_id == project_id), None)


def load_project(path: Path | str = DEFAULT_PROJECT) -> Project:
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    issues: list[str] = []

    if raw.get("schema_version") != SCHEMA_VERSION:
        issues.append(f"schema_version must be {SCHEMA_VERSION}")
    for key in ("project_id", "name"):
        if not raw.get(key):
            issues.append(f"missing {key}")
    metric = raw.get("gap", {}).get("metric")
    if metric not in GAP_METRICS:
        issues.append(f"gap metric {metric!r} is not supported; this version supports only {', '.join(GAP_METRICS)}")

    twins: dict[str, ProjectTwin] = {}
    for entry in raw.get("twins", []):
        t = entry.get("twin_type")
        if not t:
            issues.append("every twin needs a twin_type")
            continue
        if t in twins:
            issues.append(f"twin_type {t!r} is listed twice")
            continue
        cfg_path = (path.parent / entry.get("config", "")).resolve()
        if not cfg_path.is_file():
            issues.append(f"{t}: config file {entry.get('config')!r} not found")
            continue
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        issues += [f"{t}: {i}" for i in _check_twin_config(t, cfg)]
        role = entry.get("role", "product")
        if role not in ROLES:
            issues.append(f"{t}: role must be one of {', '.join(ROLES)}")
        twins[t] = ProjectTwin(t, entry.get("name") or t, role, cfg_path, cfg, entry.get("registry_id"), entry.get("asset_kind"))
    if not twins:
        issues.append("a project needs at least one twin")
    op_ids = [tw.config.get("operational_twin_id") for tw in twins.values()]
    if len(set(op_ids)) != len(op_ids):
        issues.append("two twins share an operational twin id")

    comp = raw.get("composition", {})
    connections = tuple(comp.get("connections", []))
    issues += _check_connections(twins, connections)
    outputs = tuple(comp.get("output_constituents", []))
    if not outputs:
        issues.append("choose at least one output constituent: the twins whose outputs are the system's outputs")
    for k in outputs:
        if k not in twins:
            issues.append(f"output constituent {k!r} is not one of the project's twins")
    for key in ("design_system_twin_id", "operational_system_twin_id"):
        if not comp.get(key):
            issues.append(f"composition is missing {key}")
    for t, tw in twins.items():
        legacy = tw.config.get("linked_inputs")
        if legacy is not None and legacy != _linked_from(connections, t):
            issues.append(f"{t}: its config's linked_inputs disagree with the project's connections")

    order = _processing_order(list(twins), connections) if not issues else None
    if order is None and not issues:
        issues.append("the connections form a loop; twins must feed each other in one direction")
    if issues:
        raise ProjectError(path, issues)

    return Project(
        path=path, project_id=raw["project_id"], name=raw["name"], domain=raw.get("domain", ""),
        summary=raw.get("summary", ""), gap_metric=metric, twins=tuple(twins[t] for t in order),
        system_name=comp.get("name", raw["name"]), system_description=comp.get("description", ""),
        design_system_twin_id=comp["design_system_twin_id"], operational_system_twin_id=comp["operational_system_twin_id"],
        output_constituents=outputs, connections=connections,
    )


def _check_twin_config(twin_type: str, cfg: dict) -> list[str]:
    issues = []
    if cfg.get("twin_type") != twin_type:
        issues.append(f"config declares twin_type {cfg.get('twin_type')!r}")
    for key in ("design_twin_id", "operational_twin_id", "asset_id", "vendor"):
        if not cfg.get(key):
            issues.append(f"config is missing {key}")
    if cfg.get("twin_mode") not in TWIN_MODES:
        issues.append(f"twin_mode must be one of {', '.join(TWIN_MODES)}")
    ids = set()
    for c in cfg.get("channels", []):
        cid = c.get("channel_id")
        if cid in ids:
            issues.append(f"channel {cid!r} is listed twice")
        ids.add(cid)
        if c.get("direction") not in ("input", "output"):
            issues.append(f"{cid}: direction must be input or output")
        env = c.get("envelope", {})
        if not (isinstance(env.get("min"), (int, float)) and isinstance(env.get("max"), (int, float)) and env["min"] < env["max"]):
            issues.append(f"{cid}: assured range needs a minimum below its maximum")
        if c.get("direction") == "output" and not (isinstance(c.get("tolerance_pct"), (int, float)) and c["tolerance_pct"] > 0):
            issues.append(f"{cid}: an output needs a tolerance above 0%")
    if not any(c.get("direction") == "output" for c in cfg.get("channels", [])):
        issues.append("a twin needs at least one output channel to compare with reality")
    return issues


def _channel(twins: dict[str, ProjectTwin], twin_type: str, channel_id: str) -> dict | None:
    tw = twins.get(twin_type)
    return next((c for c in tw.config.get("channels", []) if c.get("channel_id") == channel_id), None) if tw else None


def _check_connections(twins: dict[str, ProjectTwin], connections: tuple[dict, ...]) -> list[str]:
    issues, fed = [], set()
    for c in connections:
        a = _channel(twins, c.get("from_twin"), c.get("from_channel"))
        b = _channel(twins, c.get("to_twin"), c.get("to_channel"))
        label = f"{c.get('from_twin')}.{c.get('from_channel')} → {c.get('to_twin')}.{c.get('to_channel')}"
        if a is None or b is None:
            issues.append(f"{label}: connects a twin or channel the project does not have")
            continue
        if a["direction"] != "output" or b["direction"] != "input":
            issues.append(f"{label}: connections run from an output to an input")
        if a["unit"] != b["unit"]:
            issues.append(f"{label}: connected channels must share a unit ({a['unit']} vs {b['unit']})")
        if c["from_twin"] == c["to_twin"]:
            issues.append(f"{label}: a twin cannot feed itself")
        key = (c["to_twin"], c["to_channel"])
        if key in fed:
            issues.append(f"{label}: this input is already fed by another connection")
        fed.add(key)
    return issues


def _linked_from(connections: tuple[dict, ...], twin_type: str) -> dict:
    return {c["to_channel"]: {"from_twin": c["from_twin"], "from_channel": c["from_channel"]}
            for c in connections if c["to_twin"] == twin_type}


def _processing_order(declared: list[str], connections: tuple[dict, ...]) -> tuple[str, ...] | None:
    """Every twin after the twins that feed it; ties keep the project file's order. None if there is a loop."""
    feeds = {t: {c["from_twin"] for c in connections if c["to_twin"] == t} for t in declared}
    order: list[str] = []
    while len(order) < len(declared):
        ready = [t for t in declared if t not in order and feeds[t] <= set(order)]
        if not ready:
            return None
        order.append(ready[0])
    return tuple(order)
