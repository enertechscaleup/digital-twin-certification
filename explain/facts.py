"""Grounded fact packs: everything Gemini is allowed to see about one event.

Facts come only from the platform's own evidence -- the ledger, the readings
the engine received, and the engine's per-tick classifications -- and only
after that evidence has been checked: the ledger's hash chain must be intact
and the readings must match the checkpoint hashes sealed into it.
"""

from __future__ import annotations

from engine.ledger import sha256_hex, verify_chain
from engine.readings import gap_pct, is_valid_number
from engine.registry import Registry

WINDOW_TICKS = 12  # readings shown before and including the event's tick

PLATFORM_SCOPE = (
    "This platform assures demonstrated predictive fidelity within validated operating conditions: "
    "that a digital twin's simulated behaviour matches physical readings within a defined tolerance. "
    "It does not certify that the physical system is safe to operate. All data here is synthetic."
)


class EvidenceIntegrityError(Exception):
    pass


def check_evidence(ledger: list[dict], readings: list[dict]) -> None:
    chain = verify_chain(ledger)
    if not chain.valid:
        raise EvidenceIntegrityError(f"ledger chain broken at entry {chain.first_bad_seq}: {chain.reason}")
    for cp in (e["payload"] for e in ledger if e["entry_type"] == "readings_checkpoint"):
        covered = [r for r in readings if cp["from_tick"] <= r["tick"] <= cp["to_tick"]]
        if sha256_hex(covered) != cp["readings_sha256"]:
            raise EvidenceIntegrityError(f"readings for ticks {cp['from_tick']}-{cp['to_tick']} do not match the ledger")


def system_description(registry: Registry, ledger: list[dict]) -> dict:
    protocol = next(e["payload"]["escalation_protocol"] for e in ledger if e["entry_type"] == "run_started")
    return {
        "product_twins": {
            p.operational_twin_id: {
                "twin_type": p.twin_type,
                "channels": {c.channel_id: {"direction": c.direction, **c.envelope_dict()} for c in p.channels},
            }
            for p in registry.products.values()
        },
        "system_twin": {
            "twin_id": registry.system.operational_system_twin_id,
            "constituents": [registry.products[t].operational_twin_id for t in registry.system.constituents],
            "outputs_come_from": [registry.products[t].operational_twin_id for t in registry.system.output_constituents],
            "connections": list(registry.system.connections),
        },
        "escalation_protocol": protocol,
    }


def readings_window(readings: list[dict], timeline: list[dict], tick: int) -> list[dict]:
    classes = {t["tick"]: t["classifications"] for t in timeline}
    rows = []
    for r in readings:
        if not (tick - WINDOW_TICKS < r["tick"] <= tick):
            continue
        phys, pred = r["physical_value"], r["predicted_value"]
        cls = classes.get(r["tick"], {}).get(r["twin_id"], {}).get(r["channel_id"], {})
        rows.append({
            "tick": r["tick"], "operational_hours": r["operational_hours"], "twin_id": r["twin_id"], "channel_id": r["channel_id"], "direction": r["direction"],
            "unit": r["unit"], "physical_value": phys, "predicted_value": pred,
            "gap_pct": round(gap_pct(phys, pred), 3) if is_valid_number(phys) and is_valid_number(pred) and pred else None,
            "engine_classification": cls.get("class"),
            "engine_detail": {k: v for k, v in cls.items() if k not in ("class", "gap_pct")} or None,
        })
    return rows


def fact_pack(subject: dict, ledger: list[dict], readings: list[dict], timeline: list[dict],
              registry: Registry) -> dict:
    """``subject`` is the ledger entry to explain."""
    p = subject["payload"]
    tick = p["tick"]
    twin_id = p["twin_id"]
    prior_anomalies = [e["payload"] for e in ledger
                       if e["entry_type"] == "anomaly_opened" and e["seq"] < subject["seq"]]
    prior_status_events = [{"entry_type": e["entry_type"], **e["payload"]} for e in ledger
                           if e["entry_type"] in ("assurance_status_changed", "assurance_reason_added")
                           and e["seq"] < subject["seq"]]
    return {
        "platform_scope": PLATFORM_SCOPE,
        "system": system_description(registry, ledger),
        "subject": {"ledger_seq": subject["seq"], "entry_hash": subject["entry_hash"],
                    "entry_type": subject["entry_type"], "timestamp": subject["timestamp"], **p},
        "subject_twin_id": twin_id,
        "earlier_status_events": prior_status_events,
        "earlier_anomalies": prior_anomalies,
        "readings_window": readings_window(readings, timeline, tick),
        "time_note": "Each tick is 2 seconds of stream time; operational_hours is the asset's simulated age.",
    }
