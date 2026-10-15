"""Replay mode: run the engine on field readings that arrived from outside (the ingestion slice:
Pub/Sub -> Dataflow -> a validated readings file), instead of the generator's field stream.

Two labelled runs, never pinned, never uploaded to the evidence bucket:

- **comparison copy**: records the code commit sealed in the original run, so the ledger can be
  compared hash for hash with the pin. It exists only to prove "same readings in, same ledger out".
- **ingestion-labelled run**: records the commit actually running and a ``field_readings_source``
  entry with the ingestion seals. Its decisions match the pinned run; its head differs by design.

The loader fails closed: a missing, extra, duplicated or out-of-order reading stops the run.
It never repairs the stream. Design time, the joint tests and the owners' recalibration and advice
stay simulated, exactly as in a generated run; only the field readings come from outside.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from itertools import groupby
from pathlib import Path

from engine.ledger import sha256_hex
from engine.readings import ALLOWED_FIELDS
from engine.registry import load_registry
from engine.run import RunResult, run_assurance
from projects import Project
from telemetry.faults import Scenario

COMPARISON = "comparison-copy"
INGESTION = "ingestion-labelled"
SEALED_DIRS = (Path("data/lineage"), Path("data/fulfilment"))


class ReplayRefused(ValueError):
    """The readings are not a complete, ordered, single-run field stream."""


@dataclass
class LoadedReadings:
    batches: list[list[dict]]
    rows: int
    file_sha256: str  # of the file's bytes
    readings_sha256: str  # canonical, as the engine seals readings (engine/ledger.py: sha256_hex)


def canonical_order(project: Project) -> list[tuple[str, str]]:
    """The (operational twin id, channel id) order of every tick: twins in processing order, each
    twin's channels in its configuration's order. The generator emits exactly this order."""
    registry = load_registry(project)
    return [(p.operational_twin_id, c.channel_id) for p in registry.products.values() for c in p.channels]


def load_readings(path: Path, project: Project) -> LoadedReadings:
    raw = path.read_bytes()
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    if not rows:
        raise ReplayRefused("no readings")
    order = canonical_order(project)
    run_ids = {r.get("run_id") for r in rows}
    if len(run_ids) != 1:
        raise ReplayRefused(f"readings from {len(run_ids)} runs")
    batches = []
    for expected_tick, (tick, group) in enumerate(groupby(rows, key=lambda r: r.get("tick"))):
        group = list(group)
        if tick != expected_tick:
            raise ReplayRefused(f"tick {expected_tick} missing or out of order (found tick {tick})")
        for r in group:
            if set(r) != set(ALLOWED_FIELDS):
                raise ReplayRefused(f"tick {tick}: fields {sorted(set(r) ^ set(ALLOWED_FIELDS))} differ from the ingested shape")
            if r["kind"] != "field":
                raise ReplayRefused(f"tick {tick}: kind {r['kind']!r}")
        found = [(r["twin_id"], r["channel_id"]) for r in group]
        if found != order:
            missing = sorted(set(order) - set(found))
            extra = sorted(set(found) - set(order))
            dupes = len(found) - len(set(found))
            raise ReplayRefused(f"tick {tick}: {len(found)} readings, expected {len(order)} in canonical order "
                                f"(missing {missing}, unknown {extra}, duplicated {dupes})")
        batches.append(group)
    return LoadedReadings(batches, len(rows), hashlib.sha256(raw).hexdigest(), sha256_hex(rows))


def replay(project: Project, vendors: dict, sealed_dir: Path, run: str, readings: Path, mode: str, out: Path,
           actual_commit: str | None = None, ingestion: dict | None = None) -> tuple[RunResult, LoadedReadings]:
    """Run the engine on ``readings`` with the sealed run's scenario, seed and start time.
    ``vendors``: a connection to each twin owner's endpoint (the engine never imports the owners)."""
    out = out.resolve()
    if any(out == d.resolve() or d.resolve() in out.parents for d in SEALED_DIRS):
        raise ValueError(f"refusing to write a replay into the sealed evidence folder {out}")
    manifest = json.loads((sealed_dir / f"{run}.manifest.json").read_text(encoding="utf-8"))
    loaded = load_readings(readings, project)
    if mode == COMPARISON:
        commit, source = manifest["code_commit"], None
    elif mode == INGESTION:
        commit = actual_commit
        source = {"label": INGESTION, "source": "replay of a sealed synthetic run through Pub/Sub and Dataflow",
                  "replayed_run": run, "readings": loaded.rows, "readings_file_sha256": loaded.file_sha256,
                  "readings_sha256": loaded.readings_sha256, **(ingestion or {})}
    else:
        raise ValueError(f"unknown mode {mode!r}")
    scenario = Scenario.from_dict(json.loads(Path(f"scenarios/{manifest['scenario']}.json").read_text(encoding="utf-8")))
    out.mkdir(parents=True, exist_ok=True)
    ledger_path = out / f"{run}.{mode}.ledger.jsonl"
    if ledger_path.exists():
        raise ValueError(f"{ledger_path} already exists; a replay never appends to an earlier one")
    result = run_assurance(scenario, vendors, seed=int(run.rsplit("-seed", 1)[1]),
                           start_time=datetime.fromisoformat(manifest["start_time"].replace("Z", "+00:00")),
                           ledger_path=ledger_path, project=project, code_commit=commit,
                           field_source=loaded.batches, readings_source=source)
    return result, loaded


def compare(result: RunResult, sealed_dir: Path, run: str, pin_head: str, actual_commit: str | None = None) -> dict:
    """Level 2: identical head. Level 1: the same decisions -- every entry's type, timestamp and
    payload in the same order (the code commit string and the extra source entry aside), and the
    same per-tick classifications."""
    sealed = [json.loads(l) for l in (sealed_dir / f"{run}.ledger.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    timeline = [json.loads(l) for l in (sealed_dir / f"{run}.timeline.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    manifest = json.loads((sealed_dir / f"{run}.manifest.json").read_text(encoding="utf-8"))
    sealed_commit = manifest["code_commit"]
    entries = [e for e in result.ledger.entries if e["entry_type"] != "field_readings_source"]

    def decision(e: dict) -> str:
        text = json.dumps({"type": e["entry_type"], "ts": e["timestamp"], "payload": e["payload"]}, sort_keys=True)
        return text.replace(json.dumps(actual_commit), json.dumps(sealed_commit)) if actual_commit else text

    first_diff = next((i for i, (a, b) in enumerate(zip(entries, sealed)) if decision(a) != decision(b)), None)
    same_decisions = len(entries) == len(sealed) and first_diff is None
    same_timeline = [t["classifications"] for t in result.timeline] == [t["classifications"] for t in timeline]
    statuses = lambda es: [(e["payload"]["twin_id"], e["payload"]["from"], e["payload"]["to"], e["payload"]["tick"])
                           for e in es if e["entry_type"] == "assurance_status_changed"]
    head = result.ledger.head_hash
    return {
        "entries": len(result.ledger.entries), "sealed_entries": len(sealed),
        "level1_same_decisions": same_decisions and same_timeline,
        "same_entry_sequence": [e["entry_type"] for e in entries] == [e["entry_type"] for e in sealed],
        "same_status_changes": statuses(entries) == statuses(sealed),
        "same_classifications_per_tick": same_timeline,
        "first_differing_entry": first_diff,
        "level2_same_head": head == pin_head,
        "head": head, "pin_head": pin_head,
    }
