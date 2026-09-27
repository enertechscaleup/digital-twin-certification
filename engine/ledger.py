"""The evidence ledger: an append-only, hash-chained record.

Every entry carries the SHA-256 hash of the entry before it, and its own hash
is computed over its full content (including that link). Changing, deleting,
inserting, or reordering any entry breaks the chain from that point on, which
``verify_chain`` detects.

This proves the integrity of the record after the fact -- not that the
underlying sensor data was itself truthful.

Entries are timestamped with the time of the evidence they describe (the
reading's timestamp), not the wall clock, so re-running the same inputs
reproduces the same ledger, hash for hash.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

LEDGER_FORMAT_VERSION = 1
GENESIS_HASH = "0" * 64


def _jsonable(obj):
    """Non-finite numbers (NaN, infinity) are not valid JSON; record them as
    explicit strings rather than failing or silently dropping them."""
    if isinstance(obj, float) and not math.isfinite(obj):
        return repr(obj)
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


def canonical_json(obj) -> str:
    """One exact byte-for-byte serialisation, so hashes are reproducible."""
    return json.dumps(_jsonable(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_hex(obj) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def _entry_hash(entry: dict) -> str:
    return sha256_hex({k: v for k, v in entry.items() if k != "entry_hash"})


class EvidenceLedger:
    def __init__(self, path: Path | None = None):
        """In memory only if ``path`` is None; otherwise also appended to a
        JSONL file (one entry per line), starting a fresh chain."""
        self.entries: list[dict] = []
        self._file = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = path.open("w", encoding="utf-8")

    @property
    def head_hash(self) -> str:
        return self.entries[-1]["entry_hash"] if self.entries else GENESIS_HASH

    def append(self, entry_type: str, timestamp: str, payload: dict) -> dict:
        entry = {
            "ledger_format_version": LEDGER_FORMAT_VERSION,
            "seq": len(self.entries),
            "entry_type": entry_type,
            "timestamp": timestamp,
            "prev_hash": self.head_hash,
            "payload": payload,
        }
        entry["entry_hash"] = _entry_hash(entry)
        self.entries.append(entry)
        if self._file:
            self._file.write(canonical_json(entry) + "\n")
            self._file.flush()
        return entry

    def of_type(self, entry_type: str) -> list[dict]:
        return [e for e in self.entries if e["entry_type"] == entry_type]

    def close(self) -> None:
        if self._file:
            self._file.close()


@dataclass(frozen=True)
class ChainCheck:
    valid: bool
    entries_checked: int
    first_bad_seq: int | None = None
    reason: str | None = None


def verify_chain(entries: Iterable[dict]) -> ChainCheck:
    prev = GENESIS_HASH
    count = 0
    for position, entry in enumerate(entries):
        count += 1
        if entry.get("seq") != position:
            return ChainCheck(False, count, position, f"expected seq {position}, found {entry.get('seq')}")
        if entry.get("prev_hash") != prev:
            return ChainCheck(False, count, position, "link to previous entry is broken")
        if _entry_hash(entry) != entry.get("entry_hash"):
            return ChainCheck(False, count, position, "entry content does not match its hash")
        prev = entry["entry_hash"]
    return ChainCheck(True, count)


def load_ledger(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
