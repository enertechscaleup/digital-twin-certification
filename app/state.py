"""What the evidence says as of a given tick.

The dashboard replays a run tick by tick, and everything it shows -- statuses,
reasons, anomalies, ledger entries, AI explanations -- is cut off at the tick
being displayed, so nothing from later in the run leaks into an earlier view.
"""

from __future__ import annotations

from app.evidence import RunEvidence

STATUS_ENTRIES = ("assurance_status_changed", "assurance_reason_added")


def core_upto(ev: RunEvidence, tick: int) -> list[dict]:
    return [dict(e, tick=ev.tick_of(e)) for e in ev.core if ev.tick_of(e) <= tick]


def explanations_upto(ev: RunEvidence, tick: int) -> list[dict]:
    out = []
    for e in ev.supplementary[1:]:
        explained = ev.core[e["payload"]["explains_ledger_seq"]]
        if ev.tick_of(explained) <= tick:
            out.append({**e, "explains_tick": ev.tick_of(explained)})
    return out


def state_at(ev: RunEvidence, tick: int) -> dict:
    tick = max(0, min(tick, len(ev.timeline) - 1))
    entries = core_upto(ev, tick)
    twins: dict[str, dict] = {}

    def twin(tid: str) -> dict:
        return twins.setdefault(tid, {"twin_id": tid, "assurance_id": None, "status": "assured",
                                      "reasons": [], "assurance_history": []})

    open_anomalies: dict[str, dict] = {}
    recalibration: list[dict] = []
    adjustment: list[dict] = []
    for e in entries:
        t, p = e["entry_type"], e["payload"]
        if t == "assurance_issued":
            tw = twin(p["twin_id"])
            tw.update(assurance_id=p["assurance_id"], status="assured", reasons=[])
            tw["assurance_history"].append({"assurance_id": p["assurance_id"], "issued_at_tick": e["tick"],
                                            "ledger_seq": e["seq"],
                                            "supersedes": p.get("supersedes"), "twin_version": p.get("twin_version")})
        elif t == "composition_assured":
            tw = twin(p["system_twin_id"])
            tw.update(assurance_id=p["composition_assurance_id"], status="assured", reasons=[])
            tw["assurance_history"].append({"assurance_id": p["composition_assurance_id"], "issued_at_tick": e["tick"],
                                            "ledger_seq": e["seq"]})
        elif t in STATUS_ENTRIES:
            tw = twin(p["twin_id"])
            tw["reasons"].extend({**r, "since_tick": p["tick"], "ledger_seq": e["seq"]} for r in p["new_reasons"])
            if t == "assurance_status_changed":
                tw["status"] = p["to"]
        elif t == "anomaly_opened":
            open_anomalies[p["anomaly_id"]] = {**p, "ledger_seq": e["seq"]}
        elif t == "anomaly_closed":
            open_anomalies.pop(p["anomaly_id"], None)
        elif t.startswith("adjustment_"):
            adjustment.append({"seq": e["seq"], "entry_type": t, "tick": e["tick"], "payload": p})
        elif t.startswith("recalibration_") or t in ("held_out_validation", "assurance_superseded",
                                                     "composition_reassessment"):
            recalibration.append({"seq": e["seq"], "entry_type": t, "tick": e["tick"], "payload": p})

    row = ev.timeline[tick]
    for tid, level in row["status"].items():
        twin(tid)["status"] = level  # the engine's own per-tick record is authoritative

    # Status is sticky, so a cascade reason stays on the record after its
    # constituent is re-assured. Label it resolved rather than hiding it.
    for tw in twins.values():
        for r in tw["reasons"]:
            src = twins.get(r.get("constituent") or "")
            if r["cause"] == "cascade" and src and src["status"] == "assured":
                reissued = [h for h in src["assurance_history"] if h["issued_at_tick"] > r["since_tick"]]
                if reissued:
                    r["resolved"] = {"at_tick": reissued[-1]["issued_at_tick"],
                                     "note": f"constituent re-assured as {reissued[-1]['assurance_id']}"}
    return {
        "tick": tick,
        "timestamp": row["timestamp"],
        "ticks_total": len(ev.timeline),
        "twins": twins,
        "classifications": row["classifications"],
        "open_anomalies": list(open_anomalies.values()),
        "recalibration": recalibration,
        "adjustment": adjustment,
        "ledger_entries_so_far": len(entries),
        "ledger_head_so_far": entries[-1]["entry_hash"] if entries else None,
    }
