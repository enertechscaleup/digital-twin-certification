"""Checks every AI answer against the evidence before it may be sealed.

An answer is sealed only if all of these hold; otherwise it is rejected, logged
with its reasons, and never written to the supplementary ledger:

* schema: every required field, of the right type and allowed value;
* citations: every ledger entry it cites (``ledger #N`` in the text, and the
  ``ledger_entries_cited`` list) is one of the entries in its facts;
* figures: every number it quotes appears in its facts as a figure of the same
  kind -- a tick must be a tick in the facts, a count (points, readings,
  consecutive readings) a count, and a measured or configured value a value; a
  quoted figure may be rounded, never computed;
* status, now: no present-tense claim ("is", "remains", "stays") about a twin's
  status differs from the engine's status for that twin as of the explained entry;
* status, before: no past-tense claim ("was", "became", "changed from .. to ..")
  names a status the twin never held up to the explained entry, a change that
  never happened, or a status it did not hold at the tick the claim names;
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

# Field names whose numbers are ticks (moments), and those whose numbers are counts.
TICK_KEYS = {"tick", "ticks", "held_out", "released_to_owner", "window", "fitted_on_ticks", "held_out_ticks",
             "readings_window_ticks", "last_tick_in_run"}
COUNT_KEYS = {"points", "points_outside", "evaluated_points", "not_evaluated_points", "samples", "bench_samples",
              "calls", "readings", "ticks_checked", "ticks_in_range", "ticks_evaluated", "ticks_skipped", "evaluated",
              "over_tolerance", "core_entries", "failures", "levels", "probes", "flag_after_consecutive",
              "nullify_after_consecutive", "stuck_after_identical", "min_holdout_ticks", "entries",
              "test_points"}

_VERSION = re.compile(r"\bv?\d+\.\d+\.\d+\b")
_IDS = re.compile(r"\b(?:[a-z]+(?:_[a-z]+)*_\d+|[a-z0-9_]+-op-\d+|[a-z0-9_]+-design|cmp-\d+|asr-[a-z0-9_-]+|anm-\d+|adj-\d+|twn_[a-z0-9]+|sys_[a-z0-9]+)\b")
_HEX = re.compile(r"\b[0-9a-f]{12,}\b")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T[\d:]+Z?")
_CITATION = re.compile(r"(?:ledger\s*(?:entry\s*)?#\s*|entry\s*#\s*|#)(\d+)", re.IGNORECASE)
_NUM = r"-?\d+(?:,\d{3})*(?:\.\d+)?"
_NUMBER = re.compile(rf"(?<![\w.]){_NUM}")
# "tick 21", "ticks 67 to 71", "ticks 48-59", "ticks 29, 30, and 31": the numbers after the word are ticks.
# A tick is a whole number with no unit after it, so a list stops at the first figure that is not.
_TICK = r"\d+(?![\d.,]*\d)(?!\s*(?:%|percent|totes/h|tasks/h|lines/h|picks/h|m/s|mm/s|rpm|bar|degC|°C|kg|V\b|A\b|s\b|seconds?|hours?))"
_TICKS = re.compile(rf"\bticks?\s+({_TICK}(?:\s*(?:,\s*(?:and\s+)?|and|to|through|until|–|-)\s*{_TICK})*)", re.IGNORECASE)
# "27 of 243 points", "5 ticks", "3 consecutive readings": the number before the word is a count.
_COUNTS = re.compile(rf"({_NUM})(?:\s+of\s+({_NUM}))?\s+(?:consecutive|identical|test\s+points?|points?|readings?|"
                     rf"values|ticks|samples|exchanges|calls|entries|levels|times|constituents|twins|channels)\b",
                     re.IGNORECASE)
_UNIT = re.compile(rf"({_NUM})\s*(?:%|percent\b|totes/h|tasks/h|lines/h|picks/h|m/s|mm/s|rpm|bar|degC|°C|kg|V\b|A\b|s\b|"
                   r"seconds?\b|operational hours|hours?\b|m3/min)", re.IGNORECASE)
_PAST = r"(?:was|were|became|had become|turned|went|changed|moved|dropped|escalated|returned|rose)\s+(?:back\s+)?(?:to\s+)?"


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


def _num(s: str) -> str:
    return s.replace(",", "")


def _classify(text: str) -> dict[str, list[str]]:
    """Every number in ``text``, sorted by kind: ticks, counts, values (with a unit or decimals), other."""
    out = {"tick": [], "count": [], "value": [], "other": []}
    spans: list[tuple[int, int]] = []

    def take(kind: str, m: re.Match, group: int) -> None:
        if m.group(group) is None:
            return
        start, end = m.span(group)
        if any(s <= start < e for s, e in spans):
            return
        spans.append((start, end))
        out[kind].append(_num(m.group(group)))

    for m in _TICKS.finditer(text):
        for n in _NUMBER.finditer(m.group(1)):
            start = m.start(1) + n.start()
            if not any(s <= start < e for s, e in spans):
                spans.append((start, start + len(n.group())))
                out["tick"].append(_num(n.group()))
    for m in _COUNTS.finditer(text):
        take("count", m, 1)
        take("count", m, 2)
    for m in _UNIT.finditer(text):
        take("value", m, 1)
    for n in _NUMBER.finditer(text):
        if not any(s <= n.start() < e for s, e in spans):
            out["value" if "." in n.group() else "other"].append(_num(n.group()))
    return out


def fact_figures(facts, aliases: list[str]) -> dict[str, list[float]]:
    """Every number in the facts, by kind, from the field it sits in or the words around it."""
    out: dict[str, list[float]] = {"tick": [], "count": [], "value": []}

    def walk(x, key: str | None = None, in_list: bool = False) -> None:
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            kind = ("tick" if key in TICK_KEYS or (key or "").endswith("_tick") or (in_list and (key or "").endswith("_ticks"))
                    else "count" if key in COUNT_KEYS or (key or "").endswith("_ticks") else "value")
            out[kind].append(float(x))
        elif isinstance(x, str):
            for kind, nums in _classify(_strip_tokens(x, aliases)).items():
                out["value" if kind == "other" else kind].extend(float(n) for n in nums)
        elif isinstance(x, dict):
            for k, v in x.items():
                walk(v, k)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v, key, True)
    walk(facts)
    return out


def fact_numbers(facts, aliases: list[str]) -> list[float]:
    figures = fact_figures(facts, aliases)
    return figures["tick"] + figures["count"] + figures["value"]


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


def _held(history: list[tuple[int, str]], tick: int | None) -> set[str]:
    """Statuses a twin held: over its whole history, or just before and after ``tick``'s changes."""
    if tick is None:
        return {s for _, s in history}
    before = [s for t, s in history if t < tick]
    upto = [s for t, s in history if t <= tick]
    return {x for x in (before[-1] if before else None, upto[-1] if upto else None) if x}


def _status_problems(text: str, aliases: dict[str, str], status_now: dict[str, str],
                     history: dict[str, list[tuple[int, str]]] | None) -> list[str]:
    problems = []
    states = "|".join(STATUSES)
    for alias, twin_id in aliases.items():
        a = rf"\b{re.escape(alias)}\b(?:'s status| twin| status| assurance)?\s+"
        for claimed in re.findall(a + rf"(?:is|remains|stays)\s+(?:now\s+|still\s+|currently\s+)?({states})\b", text, re.IGNORECASE):
            actual = status_now.get(twin_id)
            if actual and claimed.lower() != actual:
                problems.append(f"states {alias} is {claimed.lower()}; the ledger says {actual}")
        if history is None or twin_id not in history:
            continue
        h = history[twin_id]
        for m in re.finditer(a + rf"{_PAST}({states})\b(?:\s*(?:at|on|by|in)\s+tick\s+(\d+))?", text, re.IGNORECASE):
            claimed, tick = m.group(1).lower(), int(m.group(2)) if m.group(2) else None
            if claimed not in _held(h, tick):
                when = f" at tick {tick}" if tick is not None else " at any point up to this entry"
                problems.append(f"states {alias} was {claimed}{when}; the ledger does not show that")
        for m in re.finditer(rf"\b{re.escape(alias)}\b[^.]{{0,80}}?\bfrom\s+({states})\s+to\s+({states})\b", text, re.IGNORECASE):
            change = (m.group(1).lower(), m.group(2).lower())
            if change not in {(h[i][1], h[i + 1][1]) for i in range(len(h) - 1)}:
                problems.append(f"states {alias} changed from {change[0]} to {change[1]}; the ledger shows no such change")
    return problems


def validate(response, schema: dict, facts: dict, *, allowed_seqs: set[int], status_now: dict[str, str],
             aliases: dict[str, str], engine_cause: str | None, min_citations: int = 1,
             history: dict[str, list[tuple[int, str]]] | None = None) -> Validation:
    """``aliases``: lower-case name or id -> operational twin id, for reading status claims.
    ``status_now``: the engine's status per twin as of the explained entry; ``history``: each twin's
    statuses up to that entry, as (tick, status) in order. ``engine_cause``: the engine's
    classification of the event, when it has one."""
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

    figures = fact_figures(facts, list(aliases))
    anything = figures["tick"] + figures["count"] + figures["value"]
    quoted = _classify(_strip_tokens(_CITATION.sub(" ", joined), list(aliases)))
    for kind, pool, label in (("tick", figures["tick"], "ticks"), ("count", figures["count"], "counts"),
                              ("value", figures["value"] + figures["count"], "values"), ("other", anything, "figures")):
        unmatched = sorted({n for n in quoted[kind] if not _matches(n, pool)}, key=float)
        if unmatched:
            problems.append(f"quotes {label} not in its facts: {unmatched}")

    problems += _status_problems(joined, aliases, status_now, history)

    allowed = CONSISTENT.get(engine_cause or "")
    if allowed and response["suggested_classification"] not in allowed:
        problems.append(f"classifies the event as {response['suggested_classification']}, contradicting "
                        f"the engine's classification ({engine_cause})")

    return Validation(not problems, problems, cited)
