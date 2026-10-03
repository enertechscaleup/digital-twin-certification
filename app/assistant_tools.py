"""The assistant's tools: read-only views of verified evidence.

Every tool is cut off at the tick on screen, and -- in the dashboard's
solo opening view -- limited to the project's entry twins (those nothing
else feeds, e.g. the motor before the compressor is registered), so the
assistant can never say more than the viewer could see. None of them can
change anything.
"""

from __future__ import annotations

from app.evidence import RunEvidence
from app.state import core_upto, explanations_upto, state_at
from engine.registry import load_registry
from projects import Project, load_project

MAX_READING_TICKS = 40
MAX_LEDGER_ENTRIES = 25


class ToolError(Exception):
    pass


class Toolbox:
    def __init__(self, ev: RunEvidence, tick: int, motor_only: bool, project: Project | None = None):
        self.ev = ev
        self.tick = max(0, min(tick, len(ev.timeline) - 1))
        self.motor_only = motor_only
        self.project = project or load_project()
        reg = load_registry(self.project)
        # The twins visible before the rest of the project is connected: those the project's own
        # connections don't feed. Replaces the old, oil & gas-only hardcoded MOTOR_ONLY set.
        self._solo_ids = {reg.products[t].operational_twin_id for t in self.project.entry_twins}

    def _visible(self, twin_id: str | None) -> bool:
        return not self.motor_only or twin_id is None or twin_id in self._solo_ids

    def _entry_visible(self, e: dict) -> bool:
        p = e["payload"]
        ids = [x for x in (p.get("twin_id"), p.get("system_twin_id")) if x]
        return not ids or any(self._visible(i) for i in ids)

    # -- tools -----------------------------------------------------------

    def get_current_tick(self) -> dict:
        state = state_at(self.ev, self.tick)
        hours = next((r["operational_hours"] for r in reversed(self.ev.readings) if r["tick"] == self.tick), None)
        return {"tick": self.tick, "last_tick_in_run": len(self.ev.timeline) - 1, "timestamp": state["timestamp"],
                "operational_hours": hours, "view": "single twin" if self.motor_only else "full system",
                "note": "Evidence after this tick is not available to you."}

    def get_twin_definitions(self) -> dict:
        reg = load_registry(self.project)
        started = next(e["payload"] for e in self.ev.core if e["entry_type"] == "run_started")
        twins = {
            p.operational_twin_id: {
                "twin_type": p.twin_type, "vendor": p.vendor, "twin_mode": p.twin_mode,
                "channels": {c.channel_id: {"name": c.name, "unit": c.unit, "direction": c.direction,
                                            "assured_range": [c.env_min, c.env_max], "tolerance_pct": c.tolerance_pct}
                             for c in p.channels},
            } for p in reg.products.values() if self._visible(p.operational_twin_id)
        }
        out = {"twins": twins, "escalation_protocol": started["escalation_protocol"]}
        if not self.motor_only:
            out["system_twin"] = {"twin_id": reg.system.operational_system_twin_id,
                                  "constituents": [reg.products[t].operational_twin_id for t in reg.system.constituents],
                                  "connections": list(reg.system.connections)}
        return out

    def get_status(self, twin_id: str | None = None) -> dict:
        state = state_at(self.ev, self.tick)
        twins = {tid: t for tid, t in state["twins"].items()
                 if "-op-" in tid and self._visible(tid) and (twin_id is None or tid == twin_id)}
        if twin_id and not twins:
            raise ToolError(f"no visible twin {twin_id!r}")
        return {"tick": self.tick, "twins": twins}

    def get_anomalies(self, twin_id: str | None = None, include_closed: bool = True) -> dict:
        entries = [e for e in core_upto(self.ev, self.tick) if self._entry_visible(e)]
        closed = {e["payload"]["anomaly_id"]: e["tick"] for e in entries if e["entry_type"] == "anomaly_closed"}
        out = []
        for e in entries:
            p = e["payload"]
            if e["entry_type"] != "anomaly_opened" or (twin_id and p["twin_id"] != twin_id):
                continue
            is_open = p["anomaly_id"] not in closed
            if is_open or include_closed:
                out.append({**p, "ledger_seq": e["seq"], "open": is_open, "closed_at_tick": closed.get(p["anomaly_id"])})
        return {"tick": self.tick, "anomalies": out}

    def get_readings(self, twin_id: str, channel_id: str, from_tick: int, to_tick: int) -> dict:
        if not self._visible(twin_id):
            raise ToolError(f"no visible twin {twin_id!r}")
        to_tick = min(int(to_tick), self.tick)
        from_tick = max(0, int(from_tick), to_tick - MAX_READING_TICKS + 1)
        rows = [{"tick": r["tick"], "physical_value": r["physical_value"], "predicted_value": r["predicted_value"],
                 "unit": r["unit"], "twin_version": r["twin_version"]}
                for r in self.ev.readings
                if r["twin_id"] == twin_id and r["channel_id"] == channel_id and from_tick <= r["tick"] <= to_tick]
        classes = {row["tick"]: row["classifications"].get(twin_id, {}).get(channel_id)
                   for row in self.ev.timeline[from_tick: to_tick + 1]}
        for row in rows:
            row["engine_classification"] = classes.get(row["tick"])
        return {"twin_id": twin_id, "channel_id": channel_id, "ticks": [from_tick, to_tick], "readings": rows}

    def get_ledger_entries(self, entry_type: str | None = None, twin_id: str | None = None,
                           limit: int = 15) -> dict:
        entries = [e for e in core_upto(self.ev, self.tick) if self._entry_visible(e)]
        if entry_type:
            entries = [e for e in entries if e["entry_type"] == entry_type]
        if twin_id:
            entries = [e for e in entries if twin_id in (e["payload"].get("twin_id"), e["payload"].get("system_twin_id"))]
        entries = entries[-max(1, min(int(limit), MAX_LEDGER_ENTRIES)):]
        return {"tick": self.tick, "entries": [
            {"seq": e["seq"], "tick": e["tick"], "entry_type": e["entry_type"], "entry_hash": e["entry_hash"][:16],
             "payload": _trim(e["payload"])} for e in entries]}

    def get_recalibration(self) -> dict:
        state = state_at(self.ev, self.tick)
        steps = [s for s in state["recalibration"] if self._entry_visible(s)]
        return {"tick": self.tick, "steps": [{**s, "payload": _trim(s["payload"])} for s in steps],
                "note": "Empty if no recalibration has happened by this tick."}

    def get_adjustment_episode(self) -> dict:
        if self.motor_only:
            return {"note": "Adjustment episodes involve twins connected downstream; they are not visible in the solo view."}
        steps = state_at(self.ev, self.tick)["adjustment"]
        return {"tick": self.tick, "steps": [{**s, "payload": _trim(s["payload"])} for s in steps],
                "note": "Empty if no semi-autonomous adjustment has happened by this tick."}

    def get_ai_explanations(self, twin_id: str | None = None) -> dict:
        out = []
        for e in explanations_upto(self.ev, self.tick):
            explained = self.ev.core[e["payload"]["explains_ledger_seq"]]
            tid = explained["payload"].get("twin_id")
            if self._visible(tid) and (twin_id is None or tid == twin_id):
                a = e["payload"]
                out.append({"explains_ledger_seq": a["explains_ledger_seq"], "artifact_type": a["artifact_type"],
                            "model_id": a["model_id"], "response": a["response"]})
        return {"notice": "Supplementary AI explanations, never used in any assurance decision.", "explanations": out}

    def get_evidence_integrity(self) -> dict:
        v = self.ev.verification
        return {"valid": v["valid"], "checks": [c["check"] if c.get("applicable", True) else f"{c['check']}: {c['detail']}"
                                                for c in v["checks"] if c["passed"]],
                "source": v["source"], "core_ledger_head_hash": v["core_ledger_head_hash"][:16],
                "note": "Checked when this evidence was loaded; the dashboard's Re-verify button re-checks it live."}

    def get_twin_lineage(self, twin_id: str | None = None) -> dict:
        state = state_at(self.ev, self.tick)
        if not state["lineage_recorded"]:
            return {"recorded": False, "note": "Pre-fingerprint evidence: recorded before twin lineage existed. Twins "
                    "are identified by role ids and owner-declared version labels only; no content fingerprints."}
        versions = [v for v in state["versions"]
                    if self._visible(v.get("operational_twin_id") or v.get("operational_system_twin_id"))
                    and (twin_id is None or twin_id in (v.get("operational_twin_id"), v.get("operational_system_twin_id")))]
        return {"recorded": True, "versions": versions,
                "note": "Each version: a permanent random identity, the owner's version label, a fingerprint the platform "
                        "measured by probing the twin with sealed inputs (the evidence), a fingerprint the owner declares "
                        "(an unverified claim), and its parent version. Every ledger entry cites the measured one."}

    def get_composition_tests(self) -> dict:
        tests = state_at(self.ev, self.tick)["composition_tests"]
        if self.motor_only:
            return {"note": "Composition tests concern the whole system; connect the system to see them."}
        return {"tests": [_trim(t["payload"]) for t in tests],
                "note": "Joint runs of the twins through their owners' endpoints (simulated vendor endpoints in this "
                        "prototype). interface: each upstream prediction inside the downstream twin's assured range; "
                        "interaction: joint prediction within tolerance against the combined test bench."}

    def call(self, name: str, args: dict) -> dict:
        fn = getattr(self, name, None) if name in TOOL_NAMES else None
        if fn is None:
            raise ToolError(f"unknown tool {name!r}")
        try:
            return fn(**args)
        except TypeError as exc:
            raise ToolError(f"bad arguments for {name}: {exc}")


def _trim(payload: dict, max_list: int = 12) -> dict:
    """Keep tool results small: drop bulky fields, shorten long lists."""
    out = {}
    for k, v in payload.items():
        if k in ("twin_params", "previous_params", "envelope", "previous_envelope", "checks", "fingerprint_inputs"):
            continue
        out[k] = v[:max_list] if isinstance(v, list) else v
    return out


TWIN_ID = {"type": "string", "description": "Operational twin id, e.g. motor-op-001, compressor-op-001, compressor-system-op-001"}

TOOL_SCHEMAS = [
    {"name": "get_current_tick", "description": "The tick the viewer is looking at, the asset's operational hours, and which twins are in view.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "get_twin_definitions", "description": "Twins in view, their channels, units, assured ranges, tolerances, the escalation protocol, and how twins connect.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "get_status", "description": "Assurance status of twins at the current tick: level, assurance version, and every reason traced to its source (resolved reasons are marked).",
     "parameters": {"type": "object", "properties": {"twin_id": TWIN_ID}}},
    {"name": "get_anomalies", "description": "Anomalies recorded up to the current tick (sensor faults, envelope violations, gap exceedances), open or closed.",
     "parameters": {"type": "object", "properties": {"twin_id": TWIN_ID, "include_closed": {"type": "boolean"}}}},
    {"name": "get_readings", "description": f"Physical and predicted values for one channel over a tick range (at most {MAX_READING_TICKS} ticks, never beyond the current tick), with the engine's classification per tick.",
     "parameters": {"type": "object", "properties": {"twin_id": TWIN_ID, "channel_id": {"type": "string"},
                                                     "from_tick": {"type": "integer"}, "to_tick": {"type": "integer"}},
                    "required": ["twin_id", "channel_id", "from_tick", "to_tick"]}},
    {"name": "get_ledger_entries", "description": "Entries from the hash-chained evidence ledger up to the current tick, newest last. Filter by entry_type (e.g. assurance_status_changed, anomaly_opened, verification, held_out_validation) or twin.",
     "parameters": {"type": "object", "properties": {"entry_type": {"type": "string"}, "twin_id": TWIN_ID,
                                                     "limit": {"type": "integer"}}}},
    {"name": "get_recalibration", "description": "The recalibration (Real2Sim) record up to the current tick: time split, seals, owner submission, re-verification, held-out validation, new assurance version, system reassessment.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "get_adjustment_episode", "description": "The semi-autonomous adjustment episode up to the current tick: pre-state and input-range check, the twin's recommendation and predicted end-state, the human approval, execution, and the post-state Sim2Real and objective checks.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "get_ai_explanations", "description": "Supplementary Gemini explanations already generated for status changes and sensor anomalies up to the current tick.",
     "parameters": {"type": "object", "properties": {"twin_id": TWIN_ID}}},
    {"name": "get_twin_lineage", "description": "Each twin's permanent identity and its versions up to the current tick: version label, content fingerprint, parent version, and for the system twin the exact constituent versions.",
     "parameters": {"type": "object", "properties": {"twin_id": TWIN_ID}}},
    {"name": "get_composition_tests", "description": "Joint composition tests up to the current tick: the twins run together through their owners' endpoints, with the interface check and the interaction check results.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "get_evidence_integrity", "description": "Result of the integrity checks run on this evidence (fingerprints, hash chains, AI anchors, sealed readings).",
     "parameters": {"type": "object", "properties": {}}},
]
TOOL_NAMES = {t["name"] for t in TOOL_SCHEMAS}
