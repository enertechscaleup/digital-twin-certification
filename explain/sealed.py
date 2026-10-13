"""Sealed explanations, profile 2: every engine decision in a run, explained and checked.

Profile 1 (``explain.gemini.generate_artifacts``) explains status changes, added
reasons and data-quality anomalies; the compressor train's sealed explanations were
made with it and are kept exactly as they are. Profile 2 also explains the
recalibration, every joint composition test and the adjustment episode, adds
cross-twin narratives that follow a cause across a connection (citing every ledger
entry on the way), and checks every answer against the evidence before sealing it
(``explain.validate``). An answer that fails a check is retried once with the
problems named; if it fails again it is logged and not sealed.

Gemini only ever explains. Nothing here reads or writes the core ledger except to
build facts from it, and the facts come only from integrity-checked evidence.
"""

from __future__ import annotations

import copy
import json
import time
from typing import Callable

from engine.ledger import sha256_hex
from engine.registry import Registry
from explain.facts import check_evidence, fact_pack, readings_window, system_description, PLATFORM_SCOPE
from explain.gemini import (CLASSIFICATIONS, RESPONSE_SCHEMA, SUPPLEMENTARY_NOTICE, SYSTEM_INSTRUCTION, TASKS,
                            Generator)
from explain.validate import validate
from projects import Project

PROFILE = "sealed-explanations/2"

SCHEMA = copy.deepcopy(RESPONSE_SCHEMA)
SCHEMA["properties"]["suggested_classification"]["enum"] = CLASSIFICATIONS + ["not_applicable"]
SCHEMA["properties"]["suggested_classification"]["description"] += (
    " not_applicable: the subject is not a status event (a recalibration, joint test or adjustment).")
SCHEMA["properties"]["ledger_entries_cited"] = {
    "type": "array", "items": {"type": "integer"},
    "description": "Every ledger entry number (ledger_seq) the answer relies on, from the facts only."}
SCHEMA["required"] = SCHEMA["required"] + ["ledger_entries_cited"]

INSTRUCTION = SYSTEM_INSTRUCTION + """9. Cite ledger entries as "ledger #N", using only ledger_seq values that appear in the facts, and list
   every one you rely on in ledger_entries_cited.
10. Quote figures exactly as they appear in the facts; you may round them to fewer decimals. Never compute
   new figures (no differences, ratios, sums or averages).
11. When you state a twin's status now, use status_at_subject from the facts. Refer to twins by the names in
   twin_names or by their ids.
12. An input outside its assured range is an operating condition, not twin drift. A data-quality anomaly is a
   problem with a sensor or a reading, never a twin error. Do not describe either as drift of the twin.
"""

TASKS_2 = {
    **TASKS,
    "recalibration_explanation": (
        "Explain the recalibration recorded in the facts: how the flagged-period data was split by time and sealed, "
        "what the twin's owner was given, what the owner submitted (the new version and how it was fitted), and the "
        "result of re-verification and of validation on the held-out data the owner never saw."
    ),
    "composition_test_explanation": (
        "Explain this joint composition test: the twins were run together through their owners' endpoints, each "
        "downstream twin fed the upstream twin's prediction. Say what the interface check and the interaction check "
        "found, naming any connection that failed and how many test points were outside, and what followed for the "
        "system twin."
    ),
    "adjustment_explanation": (
        "Explain the semi-autonomous adjustment episode: the pre-state check, the twin's recommendation and predicted "
        "end state, the named human approval, the single execution, and the outcome check (Sim2Real and the objective)."
    ),
    "cross_twin_narrative": (
        "Write a cross-twin narrative that follows the cause in causal_chain from twin to twin to the subject entry on "
        "the system twin, in order, citing each ledger entry number on the way. Where an earlier joint composition test "
        "predicted the failure that field readings later confirmed, link the prediction to the confirmation."
    ),
}

STATUS_ENTRIES = ("assurance_status_changed", "assurance_reason_added")
_DROP = {"exchange", "constituent_refs", "twin_ref", "system_ref", "candidate_ref", "previous_ref", "final_refs",
         "measured", "declared", "inputs", "probes", "test_points", "entry_hash", "readings"}


def _trim(x):
    if isinstance(x, dict):
        return {k: _trim(v) for k, v in x.items()
                if k not in _DROP and not k.endswith("sha256") and not k.endswith("fingerprint")}
    if isinstance(x, list):
        return [_trim(v) for v in x]
    return x


def _tick(e: dict) -> int | None:
    p = e["payload"]
    return p.get("tick", p.get("at_tick", p.get("effective_from_tick")))


def brief(e: dict) -> dict:
    return {"ledger_seq": e["seq"], "entry_type": e["entry_type"], "tick": _tick(e), **_trim(e["payload"])}


def status_after(ledger: list[dict], seq: int) -> dict[str, str]:
    """The engine's status of every twin once entry ``seq`` is recorded."""
    out: dict[str, str] = {}
    for e in ledger[:seq + 1]:
        p = e["payload"]
        if e["entry_type"] == "assurance_issued":
            out[p["twin_id"]] = "assured"
        elif e["entry_type"] == "composition_assured":
            out[p["system_twin_id"]] = "assured"
        elif e["entry_type"] == "assurance_status_changed":
            out[p["twin_id"]] = p["to"]
    return out


def twin_names(project: Project, registry: Registry) -> dict[str, str]:
    names = {registry.products[t.twin_type].operational_twin_id: t.name for t in project.twins}
    names[registry.system.operational_system_twin_id] = project.system_name
    return names


def _aliases(project: Project, registry: Registry) -> dict[str, str]:
    out = {}
    for t in project.twins:
        p = registry.products[t.twin_type]
        out[t.name.lower()] = out[p.operational_twin_id] = p.operational_twin_id
    sid = registry.system.operational_system_twin_id
    out[project.system_name.lower()] = out["system twin"] = out[sid] = sid
    return out


# -- what to explain ------------------------------------------------------

def _root_cause(p: dict) -> str | None:
    r = (p.get("new_reasons") or [{}])[0]
    roots = r.get("root_causes") or [r]
    return roots[0].get("cause")


def _crosses_a_connection(p: dict, registry: Registry) -> bool:
    """A system reason whose cause runs through a connection between two twins."""
    for r in p.get("new_reasons", []):
        if r.get("cause") == "interface_invalid":
            return True
        if r.get("cause") == "own_output":
            down = registry.by_operational_id(r["constituent"]).twin_type
            fed = {c["to_channel"] for c in registry.system.connections if c["to_twin"] == down}
            if any(x.get("cause") == "envelope_violation" and x.get("channel_id") in fed for x in r.get("root_causes", [])):
                return True
    return False


def kinds_for(entry: dict, registry: Registry) -> list[str]:
    t, p = entry["entry_type"], entry["payload"]
    system = registry.system.operational_system_twin_id
    if t in STATUS_ENTRIES:
        if p["twin_id"] != system:
            return ["status_explanation"]
        return ["impact_narrative"] + (["cross_twin_narrative"] if _crosses_a_connection(p, registry) else [])
    if t == "anomaly_opened" and p["type"] == "data_quality":
        return ["data_quality_suggestion"]
    if t == "held_out_validation":
        return ["recalibration_explanation"]
    if t == "composition_test":
        return ["composition_test_explanation"]
    if t == "adjustment_post_state_check":
        return ["adjustment_explanation"]
    return []


# -- facts for each kind ---------------------------------------------------

def _base(subject: dict, ledger: list[dict], registry: Registry, project: Project) -> dict:
    return {"platform_scope": PLATFORM_SCOPE, "system": system_description(registry, ledger),
            "twin_names": twin_names(project, registry), "subject": brief(subject),
            "status_at_subject": status_after(ledger, subject["seq"])}


def _related(ledger: list[dict], seq: int, keep: Callable[[dict], bool]) -> list[dict]:
    return [brief(e) for e in ledger[:seq + 1] if e["seq"] != seq and keep(e)]


def facts_for(kind: str, subject: dict, ledger, readings, timeline, registry: Registry, project: Project) -> dict:
    seq, p = subject["seq"], subject["payload"]
    if kind in ("status_explanation", "impact_narrative", "data_quality_suggestion"):
        facts = fact_pack(subject, ledger, readings, timeline, registry)
        facts["earlier_status_events"] = _related(ledger, seq, lambda e: e["entry_type"] in STATUS_ENTRIES)
        facts["anomalies_opened"] = _related(ledger, seq, lambda e: e["entry_type"] == "anomaly_opened")
        facts["subject"] = brief(subject)
        facts["twin_names"] = twin_names(project, registry)
        facts["status_at_subject"] = status_after(ledger, seq)
        return facts
    facts = _base(subject, ledger, registry, project)
    if kind == "recalibration_explanation":
        start = next(e["seq"] for e in ledger if e["entry_type"] == "recalibration_requested")
        after = [e for e in ledger[seq + 1:] if e["entry_type"] in ("assurance_superseded", "assurance_issued")][:2]
        facts["recalibration_record"] = [brief(e) for e in ledger[start:seq]] + [brief(e) for e in after]
    elif kind == "composition_test_explanation":
        test_id = p["test_id"]
        facts["what_followed"] = [brief(e) for e in ledger if e["seq"] > seq and (
            e["payload"].get("test_seq") == seq or e["payload"].get("composition_test") == test_id
            or any(r.get("composition_test") == test_id for r in e["payload"].get("new_reasons", [])))]
    elif kind == "adjustment_explanation":
        facts["episode"] = _related(ledger, seq, lambda e: e["entry_type"].startswith("adjustment_"))
    elif kind == "cross_twin_narrative":
        facts["causal_chain"] = causal_chain(subject, ledger, registry)
        tick = _tick(subject)
        twins = {e["twin_id"] for e in facts["causal_chain"] if e.get("twin_id")}
        facts["readings_window"] = [r for r in readings_window(readings, timeline, tick) if r["twin_id"] in twins]
        facts["prediction_note"] = ("predicted_value is the twin's simulation of the same instant from that tick's "
                                    "inputs. It is not a forecast of the future.")
    return facts


def causal_chain(subject: dict, ledger: list[dict], registry: Registry) -> list[dict]:
    """Every ledger entry on the path from the originating twin to ``subject``, in order."""
    seq = subject["seq"]
    twins: set[str] = set()
    channels: set[tuple[str, str]] = set()
    tests: set[str] = set()
    for r in subject["payload"].get("new_reasons", []):
        down = registry.by_operational_id(r["constituent"])
        twins.add(down.operational_twin_id)
        if r.get("composition_test"):
            tests.add(r["composition_test"])
        roots = r.get("root_causes", []) + ([{"channel_id": r["channel_id"]}] if r.get("channel_id") else [])
        for x in roots:
            for c in registry.system.connections:
                if c["to_twin"] == down.twin_type and c["to_channel"] == x.get("channel_id"):
                    up = registry.products[c["from_twin"]].operational_twin_id
                    twins.add(up)
                    channels.add((c["from_twin"] + "/" + c["from_channel"], c["to_twin"] + "/" + c["to_channel"]))
    system = registry.system.operational_system_twin_id

    def on_path(e: dict) -> bool:
        t, p = e["entry_type"], e["payload"]
        if t in STATUS_ENTRIES:
            return p["twin_id"] in twins or p["twin_id"] == system
        if t == "anomaly_opened":
            return p["twin_id"] in twins and p["type"] != "data_quality"
        if t in ("held_out_validation", "recalibration_submitted"):
            return p.get("twin_id") in twins
        if t == "composition_test":
            return p["test_id"] in tests or any(
                not c["passed"] and (c["from"], c["to"]) in channels for c in p["interface"]["connections"])
        return False
    return [brief(e) for e in ledger[:seq + 1] if on_path(e)]


# -- generation -------------------------------------------------------------

def _engine_cause(kind: str, subject: dict) -> str | None:
    if kind == "data_quality_suggestion":
        return "data_quality"
    if kind == "status_explanation":
        return _root_cause(subject["payload"])
    return None


def _allowed_seqs(facts: dict) -> set[int]:
    out: set[int] = set()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("ledger_seq", "test_seq", "recommendation_seq") and isinstance(v, int):
                    out.add(v)
                elif k == "evidence_seq" and isinstance(v, list):
                    out.update(i for i in v if isinstance(i, int))
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(facts)
    return out


class ExplanationsUnavailable(Exception):
    """Gemini could not be reached: the run is recorded as having no explanations."""


def generate_sealed(ledger: list[dict], readings: list[dict], timeline: list[dict], registry: Registry,
                    project: Project, generate: Generator, on_artifact: Callable[[dict], None] | None = None,
                    on_rejected: Callable[[dict], None] | None = None, retries: int = 1) -> list[dict]:
    check_evidence(ledger, readings)  # refuse to explain evidence that has been altered
    aliases = _aliases(project, registry)
    artifacts = []
    for entry in ledger:
        for kind in kinds_for(entry, registry):
            facts = facts_for(kind, entry, ledger, readings, timeline, registry, project)
            prompt = f"TASK: {TASKS_2[kind]}\n\nFACTS (JSON):\n{json.dumps(facts, indent=1)}"
            allowed = _allowed_seqs(facts)
            attempt, feedback = 0, ""
            while True:
                attempt += 1
                started = time.monotonic()
                try:
                    raw = generate(INSTRUCTION, prompt + feedback, SCHEMA)
                except Exception as exc:  # network, auth, quota: Gemini is unavailable
                    raise ExplanationsUnavailable(f"{type(exc).__name__}: {exc}") from exc
                seconds = round(time.monotonic() - started, 3)
                try:
                    response, problems = json.loads(raw), []
                except json.JSONDecodeError as exc:
                    response, problems = None, [f"not valid JSON: {exc}"]
                if not problems:
                    check = validate(response, SCHEMA, facts, allowed_seqs=allowed,
                                     status_now=facts["status_at_subject"], aliases=aliases,
                                     engine_cause=_engine_cause(kind, entry),
                                     min_citations=2 if kind == "cross_twin_narrative" else 1)
                    problems = check.problems
                if not problems:
                    break
                rejection = {"artifact_type": kind, "explains_ledger_seq": entry["seq"], "attempt": attempt,
                             "problems": problems, "raw_response": raw, "model_id": generate.model_id,
                             "generation_seconds": seconds}
                if on_rejected:
                    on_rejected(rejection)
                if attempt > retries:
                    response = None
                    break
                feedback = ("\n\nYOUR PREVIOUS ANSWER WAS REJECTED BY THE EVIDENCE CHECK for these reasons: "
                            + "; ".join(problems) + ". Answer again, following every rule.")
            if response is None:
                continue
            artifact = {
                "artifact_type": kind,
                "profile": PROFILE,
                "notice": SUPPLEMENTARY_NOTICE,
                "explains_ledger_seq": entry["seq"],
                "explains_entry_hash": entry["entry_hash"],
                "cites": [{"ledger_seq": n, "entry_hash": ledger[n]["entry_hash"]} for n in check.cited],
                "model_id": generate.model_id,
                "temperature": 0.0,
                "system_instruction_sha256": sha256_hex(INSTRUCTION),
                "facts_sha256": sha256_hex(facts),
                "response": response,
                "validation": {"passed": True, "attempts": attempt,
                               "checks": ["schema", "citations", "figures", "status", "classification", "wording"]},
                "generation_seconds": seconds,
                "raw_response": None,
                "parse_error": None,
            }
            artifacts.append(artifact)
            if on_artifact:
                on_artifact(artifact)
    return artifacts
