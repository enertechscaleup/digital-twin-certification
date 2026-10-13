"""The supplementary ledger: AI artifacts, hash-chained on their own and
anchored to the core evidence ledger by fingerprint.

The core ledger stays exactly repeatable (same inputs, same hashes). AI output
varies between runs, so it lives here instead: tamper-evident in the same way,
and every entry names the hash of the core entry it explains. The first entry
records the core ledger's head hash, binding this ledger to one exact core
record.

Entries are timestamped with the wall-clock time they were generated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from engine.ledger import EvidenceLedger, verify_chain


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def start(path: Path | None, core: list[dict]) -> EvidenceLedger:
    ledger = EvidenceLedger(path)
    run = next(e["payload"] for e in core if e["entry_type"] == "run_started")
    ledger.append("supplementary_ledger_started", _now(), {
        "core_head_hash": core[-1]["entry_hash"],
        "core_entries": len(core),
        "core_scenario": run["scenario"],
        "core_seed": run["seed"],
        "notice": "Supplementary AI artifacts. Nothing here is used in any assurance decision.",
    })
    return ledger


def record(ledger: EvidenceLedger, artifact: dict) -> dict:
    return ledger.append("ai_artifact", _now(), artifact)


UNAVAILABLE = "explanations_unavailable"


def record_unavailable(ledger: EvidenceLedger, reason: str, artifacts_sealed: int) -> dict:
    """Gemini could not be reached: the run carries no (or no further) explanations. The core
    evidence and its verification are unaffected."""
    return ledger.append(UNAVAILABLE, _now(), {
        "reason": reason, "artifacts_sealed_before": artifacts_sealed,
        "notice": "No explanations: the AI service was unavailable. Assurance decisions do not depend on it.",
    })


@dataclass(frozen=True)
class AnchorCheck:
    valid: bool
    reason: str | None = None


def verify(supplementary: list[dict], core: list[dict]) -> AnchorCheck:
    for name, entries in (("core", core), ("supplementary", supplementary)):
        chain = verify_chain(entries)
        if not chain.valid:
            return AnchorCheck(False, f"{name} ledger chain broken at entry {chain.first_bad_seq}: {chain.reason}")
    header = supplementary[0]
    if header["entry_type"] != "supplementary_ledger_started" or \
            header["payload"]["core_head_hash"] != core[-1]["entry_hash"]:
        return AnchorCheck(False, "supplementary ledger is not bound to this core ledger")
    for e in supplementary[1:]:
        if e["entry_type"] == UNAVAILABLE:
            continue
        if e["entry_type"] != "ai_artifact":
            return AnchorCheck(False, f"supplementary entry {e['seq']} has an unknown type {e['entry_type']!r}")
        p = e["payload"]
        seq = p["explains_ledger_seq"]
        if seq >= len(core) or core[seq]["entry_hash"] != p["explains_entry_hash"]:
            return AnchorCheck(False, f"supplementary entry {e['seq']} points at a core entry that does not match")
        for c in p.get("cites", []):
            n = c["ledger_seq"]
            if n >= len(core) or core[n]["entry_hash"] != c["entry_hash"]:
                return AnchorCheck(False, f"supplementary entry {e['seq']} cites core entry {n}, which does not match")
    return AnchorCheck(True)
