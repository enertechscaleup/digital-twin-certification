"""The recalibration cycle (Real2Sim), run by the platform.

1. Request: only for a Flagged or Nullified Operational Twin.
2. Split BY TIME the field data from when the twin was first flagged up to the
   request: the earlier part is for the twin's owner, the later part is held
   out. Degradation is time-dependent, so a temporal split resists overfitting
   in a way a random split cannot.
3. Seal both parts' SHA-256 in the ledger BEFORE anything is released.
4. Release only the earlier part to the owner, through its endpoint. The owner
   recalibrates inside its own environment and publishes a new version; the
   platform receives the version label, declared ranges and method, and a
   fingerprint the owner declares -- never the parameters.
5. Register the new version on arrival: the platform probes it and seals its
   measured fingerprint, with the version in operation as its parent. A label
   already registered that now behaves differently is rejected before any test.
6. Re-verify it, then validate it on the held-out part, both by querying it.
7. Pass: issue a new assurance version, effective from the request, that
   supersedes the old one; the new version goes into operation, the system twin
   is registered as a new version, and the twins are run jointly again
   (engine/composition.py). A failing joint test is a specific reason on the
   system twin and blocks its re-assurance. Every earlier entry stays exactly
   as it was. Fail: record the rejection; the old assurance and status stand.
"""

from __future__ import annotations

from dataclasses import replace

from engine.boundary import RemoteTwin
from engine.composition import CompositionTester, failure_reasons
from engine.ledger import EvidenceLedger, sha256_hex
from engine.lineage import LineageError
from engine.monitor import FieldMonitor
from engine.protocol import EscalationProtocol
from engine.readings import gap_pct, is_valid_number
from engine.registry import ProductTwin
from engine.verification import verify


def plan_split(first_flagged_tick: int, at_tick: int, protocol: EscalationProtocol) -> dict | None:
    window_ticks = at_tick - first_flagged_tick
    held = max(protocol.min_holdout_ticks, round(window_ticks * protocol.holdout_fraction))
    if window_ticks - held < 1:
        return None
    boundary = at_tick - held
    return {
        "window": [first_flagged_tick, at_tick - 1],
        "released_to_owner": [first_flagged_tick, boundary - 1],
        "held_out": [boundary, at_tick - 1],
        "holdout_fraction": protocol.holdout_fraction,
    }


def _in(r: dict, span: list[int]) -> bool:
    return span[0] <= r["tick"] <= span[1]


def with_declared_outputs(product: ProductTwin, ranges: dict[str, dict]) -> ProductTwin:
    channels = tuple(
        replace(c, env_min=ranges[c.channel_id]["min"], env_max=ranges[c.channel_id]["max"])
        if c.direction == "output" and c.channel_id in ranges else c
        for c in product.channels
    )
    return replace(product, channels=channels)


def held_out_validate(product: ProductTwin, model, held_out: list[dict],
                      protocol: EscalationProtocol) -> dict:
    """Re-simulate the held-out ticks with the recalibrated twin and compare
    against the physical readings. Ticks with bad or out-of-envelope inputs,
    or bad outputs, are skipped (the same rules as field monitoring)."""
    by_tick: dict[int, dict[str, float | None]] = {}
    for r in held_out:
        by_tick.setdefault(r["tick"], {})[r["channel_id"]] = r["physical_value"]
    per_channel = {c.channel_id: {"gaps": [], "tolerance_pct": c.tolerance_pct} for c in product.outputs}
    evaluated, skipped = 0, 0
    for tick in sorted(by_tick):
        values = by_tick[tick]
        inputs = {c.channel_id: values.get(c.channel_id) for c in product.inputs}
        if not all(is_valid_number(v) and c.in_envelope(v) for c, v in zip(product.inputs, inputs.values())):
            skipped += 1
            continue
        predicted = model.predict(inputs)
        outputs_ok = all(is_valid_number(values.get(c.channel_id)) and is_valid_number(predicted.get(c.channel_id))
                         for c in product.outputs)
        if not outputs_ok:
            skipped += 1
            continue
        evaluated += 1
        for c in product.outputs:
            per_channel[c.channel_id]["gaps"].append(gap_pct(values[c.channel_id], predicted[c.channel_id]))
    summary = {
        ch: {"evaluated": len(d["gaps"]), "tolerance_pct": d["tolerance_pct"],
             "max_gap_pct": round(max(d["gaps"]), 4) if d["gaps"] else None,
             "over_tolerance": sum(g > d["tolerance_pct"] for g in d["gaps"])}
        for ch, d in per_channel.items()
    }
    passed = evaluated >= protocol.min_holdout_ticks and all(s["over_tolerance"] == 0 for s in summary.values())
    return {
        "passed": passed,
        "rule": f"every evaluated held-out output within tolerance, at least {protocol.min_holdout_ticks} ticks evaluated",
        "ticks_evaluated": evaluated, "ticks_skipped": skipped, "per_channel": summary,
        "held_out_readings_sha256": sha256_hex(held_out),
    }


def _next_version(assurance_id: str) -> str:
    stem, v = assurance_id.rsplit("-v", 1)
    return f"{stem}-v{int(v) + 1}"


def run_recalibration(ledger: EvidenceLedger, monitor: FieldMonitor, product: ProductTwin, current: RemoteTwin,
                      readings_so_far: list[dict], at_tick: int, timestamp: str, protocol: EscalationProtocol,
                      tester: CompositionTester, twins: dict[str, RemoteTwin]) -> RemoteTwin | None:
    """``current`` and ``twins``: the versions in operation, as evidence handles. Returns the
    new version's evidence handle if a new assurance version was issued."""
    tid = product.operational_twin_id
    status = monitor.status[tid]
    lineage = monitor.lineage
    cite = monitor.cite(tid)  # the version in operation
    request = {"twin_id": tid, "assurance_id": status.assurance_id, "status": status.level, "at_tick": at_tick, **cite}
    if status.level == "assured":
        ledger.append("recalibration_refused", timestamp, {**request, "reason": "twin is assured; nothing to recalibrate"})
        return None
    split = plan_split(status.flagged_since_tick, at_tick, protocol)
    if split is None:
        ledger.append("recalibration_refused", timestamp, {
            **request, "reason": "not enough flagged-period data to split", "flagged_since_tick": status.flagged_since_tick,
        })
        return None
    ledger.append("recalibration_requested", timestamp, {**request, "flagged_since_tick": status.flagged_since_tick,
                                                         "split": split})

    own = [r for r in readings_so_far if r["twin_id"] == tid]
    released = [r for r in own if _in(r, split["released_to_owner"])]
    held_out = [r for r in own if _in(r, split["held_out"])]
    # Seal both parts before anything leaves the platform.
    ledger.append("recalibration_data_sealed", timestamp, {
        "twin_id": tid,
        "released_part": {"ticks": split["released_to_owner"], "readings": len(released),
                          "readings_sha256": sha256_hex(released)},
        "held_out_part": {"ticks": split["held_out"], "readings": len(held_out),
                          "readings_sha256": sha256_hex(held_out)}, **cite,
    })
    ledger.append("recalibration_data_released", timestamp, {
        "twin_id": tid, "to": "twin owner", "vendor": product.vendor,
        "readings_sha256": sha256_hex(released), "held_out_released": False, **cite,
    })

    envelopes = {c.channel_id: (c.env_min, c.env_max) for c in product.inputs}
    submission = current.recalibrate([dict(r) for r in released], envelopes)
    candidate = RemoteTwin(current.connection, product.twin_type, submission["twin_version"])
    restated = with_declared_outputs(product, submission["declared_output_ranges"])
    try:
        node = lineage.register_product(product.twin_type, restated, candidate, timestamp,
                                        "twin owner (recalibration submission)", at_tick)
    except LineageError as exc:
        ledger.append("recalibration_rejected", timestamp, {
            "twin_id": tid, "assurance_id": status.assurance_id, "status_unchanged": status.level,
            "reason": str(exc), "submission_sha256": sha256_hex(submission), **cite,
        })
        return None
    candidate = lineage.evidence_twin(product.twin_type, candidate)
    new = {"twin_ref": node.ref()}
    ledger.append("recalibration_submitted", timestamp, {
        "twin_id": tid, "vendor": product.vendor, "submission": submission,
        "submission_sha256": sha256_hex(submission), "previous_twin_version": current.version,
        "previous_ref": cite["twin_ref"], "candidate_ref": node.ref(),
    })

    with tester.exchange.batch("verification") as seal:
        record = verify(restated, candidate, protocol)
    v = ledger.append("verification", timestamp, {
        **record, "twin_id": tid, "stage": "re-verification",
        "previous_envelope": product.envelope_snapshot(), "exchange": seal, **new,
    })
    with tester.exchange.batch("held_out_validation") as seal:
        result = held_out_validate(restated, candidate, held_out, protocol)
    h = ledger.append("held_out_validation", timestamp, {
        "twin_id": tid, "twin_version": candidate.version, "held_out_ticks": split["held_out"],
        **result, "exchange": seal, **new,
    })
    if not (v["payload"]["passed"] and h["payload"]["passed"]):
        ledger.append("recalibration_rejected", timestamp, {
            "twin_id": tid, "assurance_id": status.assurance_id, "status_unchanged": status.level,
            "verification_passed": v["payload"]["passed"], "held_out_validation_passed": h["payload"]["passed"],
            "evidence_seq": [v["seq"], h["seq"]], "twin_ref": cite["twin_ref"], "candidate_ref": node.ref(),
        })
        return None

    new_id = _next_version(status.assurance_id)
    ledger.append("assurance_issued", timestamp, {
        "assurance_id": new_id, "twin_id": tid, "stage": "operational", "composition": "product",
        "status": "assured", "twin_version": candidate.version, "supersedes": status.assurance_id,
        "effective_from_tick": at_tick, "effective_from": timestamp, "parent_twin_id": product.design_twin_id,
        "asset_id": product.asset_id, "twin_mode": product.twin_mode, "envelope": restated.envelope_snapshot(),
        "evidence_seq": [v["seq"], h["seq"]], **new,
    })
    ledger.append("assurance_superseded", timestamp, {
        "twin_id": tid, "old_assurance_id": status.assurance_id, "old_status_at_supersession": status.level,
        "new_assurance_id": new_id, "effective_from_tick": at_tick,
        "note": "prior assurance and its evidence remain in the ledger unchanged",
        "previous_ref": cite["twin_ref"], "twin_ref": node.ref(),
    })
    # The new version goes into operation; the system twin's content changed with it, so the
    # twins are run together again before the system can be re-assured.
    lineage.adopt(product.twin_type, node)
    lineage.register_system(timestamp, "platform (recomposition after recalibration)", at_tick)
    monitor.reassure(tid, new_id, at_tick, timestamp)
    joint = {**twins, product.twin_type: candidate}
    ids = {t: monitor.status[p.operational_twin_id].assurance_id for t, p in monitor.registry.products.items()}
    test = tester.run(joint, timestamp, f"after recalibration of {tid} to {candidate.version}", ids, tick=at_tick)
    monitor.composition_tested(test, failure_reasons(test), at_tick, timestamp)
    monitor.reassess_system(at_tick, timestamp, test)
    return candidate
