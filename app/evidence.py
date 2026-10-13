"""Loading and verifying the evidence the dashboard serves.

Runs are pinned by core-ledger head hash (``config/runs.json``). Every load
checks, before anything is served:

1. the manifest names the pinned core-ledger head hash;
2. every file matches its SHA-256 in the manifest;
3. the core ledger's hash chain is intact and ends at the pinned head;
4. the supplementary (AI) ledger's chain is intact, bound to this core ledger,
   and every AI artifact is anchored to a matching core entry;
5. the readings match the checkpoint hashes sealed in the core ledger;
6. twin lineage: every version's fingerprint matches its sealed inputs and every
   entry cites a registered version (engine/lineage.py). Evidence recorded before
   lineage existed carries no versions to check and is labelled pre-fingerprint.

The source is Cloud Storage in production and the local ``data/`` folder in
development; both go through the same checks.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from engine.ledger import verify_chain
from engine.lineage import verify_lineage
from explain import supplementary
from explain.facts import EvidenceIntegrityError, check_evidence

ROOT = Path(__file__).resolve().parent.parent
RUNS_CONFIG = Path(__file__).parent / "config" / "runs.json"
FILE_KINDS = ("ledger", "supplementary", "readings", "timeline")
# Runs recorded with twin lineage also carry the boundary exchange file (engine/boundary.py).
OPTIONAL_KINDS = ("exchange",)


class EvidenceStore:
    def read(self, run: str, head: str, filename: str) -> bytes:
        raise NotImplementedError

    def describe(self, run: str, head: str) -> str:
        raise NotImplementedError


class LocalStore(EvidenceStore):
    def __init__(self, directory: Path):
        self.directory = directory

    def read(self, run: str, head: str, filename: str) -> bytes:
        return (self.directory / filename).read_bytes()

    def describe(self, run: str, head: str) -> str:
        return f"local:{self.directory}"


class GcsStore(EvidenceStore):
    def __init__(self, bucket: str):
        from google.cloud import storage  # only needed in production

        self.bucket_name = bucket
        self._bucket = storage.Client().bucket(bucket)

    def _path(self, run: str, head: str, filename: str) -> str:
        return f"runs/{run}/{head[:16]}/{filename}"

    def read(self, run: str, head: str, filename: str) -> bytes:
        return self._bucket.blob(self._path(run, head, filename)).download_as_bytes()

    def describe(self, run: str, head: str) -> str:
        return f"gs://{self.bucket_name}/runs/{run}/{head[:16]}/"


def store_from_env() -> EvidenceStore:
    if os.environ.get("EVIDENCE_SOURCE", "local") == "gcs":
        return GcsStore(os.environ["EVIDENCE_BUCKET"])
    return LocalStore(Path(os.environ.get("EVIDENCE_DIR", ROOT / "data")))


def load_runs_config() -> dict:
    """``RUNS_CONFIG`` (a path) replaces the served run list, for tests and local development."""
    return json.loads(Path(os.environ.get("RUNS_CONFIG", RUNS_CONFIG)).read_text(encoding="utf-8"))


def _jsonl(raw: bytes) -> list[dict]:
    return [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]


@dataclass
class RunEvidence:
    run: str
    title: str
    manifest: dict
    core: list[dict]
    supplementary: list[dict]
    readings: list[dict]
    timeline: list[dict]
    source: str
    verification: dict = field(default_factory=dict)
    exchange: list[dict] = field(default_factory=list)
    start: datetime | None = None
    tick_seconds: int = 2

    def tick_of(self, entry: dict) -> int:
        ts = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
        return round((ts - self.start).total_seconds() / self.tick_seconds)


def verify_run(store: EvidenceStore, run: str, title: str, pinned_head: str) -> RunEvidence:
    """Fetch every file fresh and check it. Raises EvidenceIntegrityError on any failure."""
    started = time.monotonic()
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "", **extra) -> None:
        checks.append({"check": name, "passed": ok, "detail": detail, **extra})
        if not ok:
            raise EvidenceIntegrityError(f"{run}: {name} failed. {detail}")

    manifest_raw = store.read(run, pinned_head, f"{run}.manifest.json")
    manifest = json.loads(manifest_raw)
    check("manifest names the pinned core ledger", manifest["core_ledger_head_hash"] == pinned_head,
          f"pinned {pinned_head[:16]}, manifest {manifest['core_ledger_head_hash'][:16]}")

    kinds = FILE_KINDS + tuple(k for k in OPTIONAL_KINDS if f"{run}.{k}.jsonl" in manifest["file_sha256"])
    raw = {k: store.read(run, pinned_head, f"{run}.{k}.jsonl") for k in kinds}
    for k, content in raw.items():
        name = f"{run}.{k}.jsonl"
        check(f"{k} file matches its manifest fingerprint",
              hashlib.sha256(content).hexdigest() == manifest["file_sha256"][name])

    core, sup = _jsonl(raw["ledger"]), _jsonl(raw["supplementary"])
    readings, timeline = _jsonl(raw["readings"]), _jsonl(raw["timeline"])
    chain = verify_chain(core)
    check("core ledger hash chain intact", chain.valid, chain.reason or f"{chain.entries_checked} entries")
    check("core ledger ends at the pinned head", core[-1]["entry_hash"] == pinned_head)
    anchors = supplementary.verify(sup, core)
    check("AI ledger intact and anchored to the core ledger", anchors.valid, anchors.reason or f"{len(sup)} entries")
    try:
        check_evidence(core, readings)
        check("readings match the checkpoints sealed in the core ledger", True,
              f"{len(readings)} readings")
    except EvidenceIntegrityError as exc:
        check("readings match the checkpoints sealed in the core ledger", False, str(exc))
    exchange = _jsonl(raw["exchange"]) if "exchange" in raw else []
    lineage = verify_lineage(core, readings, exchange)
    if lineage.recorded:
        check("every twin version measured and fingerprinted, every entry cites a registered version, "
              "and every boundary exchange is sealed", lineage.valid,
              lineage.reason or f"{lineage.versions} versions, {lineage.citations} citations, {lineage.exchanges} exchanges")
    else:
        check("twin lineage", lineage.valid, lineage.reason or
              "pre-fingerprint evidence, recorded before twin lineage", applicable=False)

    evidence = RunEvidence(run, title, manifest, core, sup, readings, timeline, store.describe(run, pinned_head))
    evidence.exchange = exchange
    evidence.start = datetime.fromisoformat(core[0]["timestamp"].replace("Z", "+00:00"))
    evidence.verification = {
        "valid": True, "checks": checks, "source": evidence.source,
        "core_ledger_head_hash": pinned_head, "seconds": round(time.monotonic() - started, 3),
    }
    return evidence


def write_manifest(directory: Path, run: str, scenario: str, code_commit: str | None = None) -> dict:
    """Write <run>.manifest.json describing the four evidence files in ``directory``."""
    files = {f"{run}.{k}.jsonl": hashlib.sha256((directory / f"{run}.{k}.jsonl").read_bytes()).hexdigest()
             for k in FILE_KINDS + OPTIONAL_KINDS if (directory / f"{run}.{k}.jsonl").exists()}
    core = _jsonl((directory / f"{run}.ledger.jsonl").read_bytes())
    sup = _jsonl((directory / f"{run}.supplementary.jsonl").read_bytes())
    manifest = {
        "run": run, "scenario": scenario, "start_time": core[0]["timestamp"],
        "core_ledger_head_hash": core[-1]["entry_hash"], "core_ledger_entries": len(core),
        "supplementary_ledger_head_hash": sup[-1]["entry_hash"], "supplementary_entries": len(sup),
        "ai_model": next((e["payload"]["model_id"] for e in sup[1:] if e["entry_type"] == "ai_artifact"), None),
        "code_commit": code_commit, "file_sha256": files,
    }
    (directory / f"{run}.manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
