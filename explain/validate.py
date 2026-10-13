"""Checks every AI answer against the evidence before it may be sealed.

An answer is sealed only if all of these hold; otherwise it is rejected, logged
with its reasons, and never written to the supplementary ledger:

* schema: every required field, of the right type and allowed value;
* citations: every ledger entry it cites (``ledger #N`` in the text, and the
  ``ledger_entries_cited`` list) is one of the entries in its facts;
* figures: every number it quotes appears in its facts (a quoted figure may be
  rounded, never computed);
* status: no present-tense status claim about a twin differs from the engine's
  status for that twin as of the explained entry;
* classification: its suggested category does not contradict the engine's own
  classification of the event (an out-of-range input is not twin drift, a sensor
  fault is not twin error);
* wording: no banned terms.

These checks make the AI layer answerable to the core ledger; they never change it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

BANNED_TERMS = ("lidar",)
STATUSES = ("assured", "flagged", "nullified")
TEXT_FIELDS = ("headline", "explanation", "suggested_investigation", "limitations")

# Which suggested categories are consistent with each engine cause.
CONSISTENT = {
    "gap_exceedance": {"twin_fidelity_loss", "unclear"},
    "envelope_violation": {"operating_outside_envelope", "unclear"},
    "data_quality": {"sensor_fault", "unclear"},
}

_VERSION = re.compile(r"\bv?\d+\.\d+\.\d+\b")
_IDS = re.compile(r"\b(?:[a-z0-9_]+-op-\d+|[a-z0-9_]+-design|cmp-\d+|asr-[a-z0-9_-]+|anm-\d+|adj-\d+|twn_[a-z0-9]+|sys_[a-z0-9]+)\b")
_HEX = re.compile(r"\b[0-9a-f]{12,}\b")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T[\d:]+Z?")
_CITATION = re.compile(r"(?:ledger\s*(?:entry\s*)?#\s*|entry\s*#\s*|#)(\d+)", re.IGNORECASE)
_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?")


@dataclass
class Validation:
    passed: bool
    problems: list[str] = field(default_factory=list)
    cited: list[int] = field(default_factory=list)


def _strip_tokens(text: str, aliases: list[str]) -> str:
    for a in sorted(aliases, key=len, reverse=True):
        text = re.sub(re.escape(a), " ", text, flags=re.IGNORECASE)
    for pattern in (_TIMESTAMP, _VERSION, _IDS, _HEX):
        text = pattern.sub(" ", text)
    return text


def _numbers(text: str) -> list[str]:
    return [m.replace(",", "") for m in _NUMBER.findall(text)]


def fact_numbers(facts, aliases: list[str]) -> list[float]:
    """Every number in the facts: numeric values, and figures written inside strings."""
    out: list[float] = []

    def walk(x):
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            out.append(float(x))
        elif isinstance(x, str):
            out.extend(float(n) for n in _numbers(_strip_tokens(x, aliases)))
        elif isinstance(x, dict):
            for k, v in x.items():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
    walk(facts)
    return out


def _matches(quoted: str, values: list[float]) -> bool:
    q = float(quoted)
    decimals = len(quoted.split(".")[1]) if "." in quoted else 0
    return any(abs(v - q) < 1e-9 or round(v, decimals) == q for v in values)


def _schema_problems(r, schema: dict) -> list[str]:
    if not isinstance(r, dict):
        return ["the answer is not a JSON object"]
    problems = []
    for key in schema["required"]:
        spec = schema["properties"][key]
        if key not in r:
            problems.append(f"missing field {key}")
            continue
        v = r[key]
        if spec["type"] == "string" and not isinstance(v, str):
            problems.append(f"{key} must be text")
        elif spec["type"] == "array":
            item = spec["items"]["type"]
            ok = isinstance(v, list) and all(isinstance(i, str) if item == "string" else
                                             isinstance(i, int) and not isinstance(i, bool) for i in v)
            if not ok:
                problems.append(f"{key} must be a list of {'text' if item == 'string' else 'whole numbers'}")
        if "enum" in spec and v not in spec["enum"]:
            problems.append(f"{key} {v!r} is not an allowed value")
    return problems


def validate(response, schema: dict, facts: dict, *, allowed_seqs: set[int], status_now: dict[str, str],
             aliases: dict[str, str], engine_cause: str | None, min_citations: int = 1) -> Validation:
    """``aliases``: lower-case name or id -> operational twin id, for reading status claims.
    ``status_now``: the engine's status per twin as of the explained entry.
    ``engine_cause``: the engine's classification of the event, when it has one."""
    problems = _schema_problems(response, schema)
    if problems:
        return Validation(False, problems)
    texts = [response[k] for k in TEXT_FIELDS] + list(response["evidence_cited"])
    joined = "\n".join(texts)

    for term in BANNED_TERMS:
        if term in joined.lower():
            problems.append(f"uses the term {term!r}")

    cited = sorted({int(n) for n in _CITATION.findall(joined)} | set(response["ledger_entries_cited"]))
    unknown = [n for n in cited if n not in allowed_seqs]
    if unknown:
        problems.append(f"cites ledger entries not in its facts: {unknown}")
    if len(cited) < min_citations:
        problems.append(f"cites {len(cited)} ledger entries; at least {min_citations} required")

    values = fact_numbers(facts, list(aliases))
    stripped = _strip_tokens(_CITATION.sub(" ", joined), list(aliases))
    unmatched = sorted({n for n in _numbers(stripped) if not _matches(n, values)}, key=float)
    if unmatched:
        problems.append(f"quotes figures not in its facts: {unmatched}")

    for alias, twin_id in aliases.items():
        pattern = (rf"\b{re.escape(alias)}\b(?:'s status| twin| status| assurance)?\s+"
                   rf"(?:is|remains|stays)\s+(?:now\s+|still\s+|currently\s+)?({'|'.join(STATUSES)})\b")
        for claimed in re.findall(pattern, joined, flags=re.IGNORECASE):
            actual = status_now.get(twin_id)
            if actual and claimed.lower() != actual:
                problems.append(f"states {alias} is {claimed.lower()}; the ledger says {actual}")

    allowed = CONSISTENT.get(engine_cause or "")
    if allowed and response["suggested_classification"] not in allowed:
        problems.append(f"classifies the event as {response['suggested_classification']}, contradicting "
                        f"the engine's classification ({engine_cause})")

    return Validation(not problems, problems, cited)
