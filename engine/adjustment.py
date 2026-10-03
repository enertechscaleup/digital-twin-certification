"""A semi-autonomous adjustment episode, run by the platform.

Evidence unit (design doc, Twin operating modes): pre-state snapshot with an
input-range check, the twin's recommendation and predicted end-state, a named
approval, a single execution, then a post-state snapshot with a Sim2Real check.

The recommendation comes from the twin's owner (``advisor``, passed in -- the
engine never imports it). The platform only checks and records:

* the twin's assured mode must be semi-autonomous, and it must be assured now;
* every input of the twin must be clean and inside its assured range (pre-state);
* the recommended setpoint must be inside the control input's assured range.

After execution, two results are reported separately, because they answer
different questions: Sim2Real (did reality match the predicted end-state?) and
the objective (did the connected channel return to its assured range?).
"""

from __future__ import annotations

from typing import Callable

from engine.ledger import EvidenceLedger
from engine.monitor import FieldMonitor
from engine.readings import gap_pct, is_valid_number
from engine.registry import Registry
from telemetry.faults import AdjustmentRequest

Advisor = Callable[..., dict]


class AdjustmentEpisode:
    def __init__(self, request: AdjustmentRequest, registry: Registry, ledger: EvidenceLedger,
                 monitor: FieldMonitor, advisor: Advisor, episode_id: str = "adj-0001"):
        self.req = request
        self.registry = registry
        self.ledger = ledger
        self.monitor = monitor
        self.advisor = advisor
        self.episode_id = episode_id
        self.product = registry.products[request.twin_type]
        self.objective_product = registry.products[request.objective["twin_type"]]
        self.objective_channel = next(c for c in self.objective_product.channels
                                      if c.channel_id == request.objective["channel"])
        self.state = "pending"  # pending -> recommended -> approved -> executed -> checked | refused | declined
        self.recommendation: dict | None = None
        self.post: list[dict] = []

    def _cite(self) -> dict:
        """The exact version of the advising twin, when the run records lineage."""
        return self.monitor.cite(self.product.operational_twin_id)

    # Readings for one tick, keyed (twin_id, channel_id).
    @staticmethod
    def _index(readings: list[dict]) -> dict:
        return {(r["twin_id"], r["channel_id"]): r for r in readings}

    def after_tick(self, tick: int, ts: str, tick_readings: list[dict], classifications: dict, twin_model) -> None:
        r = self.req
        if tick == r.recommend_at_tick and self.state == "pending":
            self._recommend(tick, ts, tick_readings, classifications, twin_model)
        elif tick == r.approve_at_tick and self.state == "recommended":
            self._approve(tick, ts)
        elif self.state == "executed" and r.execute_at_tick < tick <= r.execute_at_tick + r.check_ticks:
            self.post.append({"tick": tick, "readings": self._index(tick_readings)})
            if tick == r.execute_at_tick + r.check_ticks:
                self._check(tick, ts)

    def before_tick(self, tick: int, ts: str, generator) -> None:
        if tick == self.req.execute_at_tick and self.state == "approved":
            rec = self.recommendation
            generator.setpoints[(self.req.twin_type, rec["control_channel"])] = rec["to"]
            self.state = "executed"
            self.ledger.append("adjustment_executed", ts, {
                "episode_id": self.episode_id, "twin_id": self.product.operational_twin_id, "tick": tick,
                "control_channel": rec["control_channel"], "setpoint": rec["to"],
                "note": "executed once; the system then returns to passive monitoring", **self._cite(),
            })

    # -- steps ------------------------------------------------------------

    def _refuse(self, tick: int, ts: str, reason: str, extra: dict | None = None) -> None:
        self.state = "refused"
        self.ledger.append("adjustment_refused", ts, {
            "episode_id": self.episode_id, "twin_id": self.product.operational_twin_id, "tick": tick,
            "reason": reason, **(extra or {}), **self._cite()})

    def _recommend(self, tick, ts, tick_readings, classifications, twin_model) -> None:
        p, tid = self.product, self.product.operational_twin_id
        status = self.monitor.status[tid]
        if p.twin_mode != "semi_autonomous":
            return self._refuse(tick, ts, f"twin mode is {p.twin_mode}; only a semi-autonomous twin may recommend actions")
        if status.level != "assured":
            return self._refuse(tick, ts, f"twin is {status.level}; only an assured twin may recommend actions",
                                {"assurance_id": status.assurance_id})
        idx = self._index(tick_readings)
        inputs = {c.channel_id: idx[(tid, c.channel_id)]["physical_value"] for c in p.inputs}
        input_checks = {ch: classifications.get(tid, {}).get(ch, {}).get("class") for ch in inputs}
        pre_ok = all(v == "ok" for v in input_checks.values())
        obj_reading = idx[(self.objective_product.operational_twin_id, self.objective_channel.channel_id)]
        pre_state = {
            "tick": tick,
            "inputs": inputs,
            "outputs": {c.channel_id: idx[(tid, c.channel_id)]["physical_value"] for c in p.outputs},
            "objective_channel_value": obj_reading["physical_value"],
            "statuses": {t: {"status": a.level, "assurance_id": a.assurance_id} for t, a in self.monitor.status.items()},
        }
        if not pre_ok:
            return self._refuse(tick, ts, "pre-state input-range check failed", {"pre_state": pre_state,
                                                                                 "input_checks": input_checks})
        control = next(c for c in p.inputs if c.channel_id == self.req.control_channel)
        connection = next(c for c in self.registry.system.connections
                          if c["to_twin"] == self.req.objective["twin_type"] and c["to_channel"] == self.objective_channel.channel_id)
        advice = self.advisor(p.twin_type, twin_model, inputs, control.channel_id, (control.env_min, control.env_max),
                              connection["from_channel"], self.objective_channel.env_min)
        setpoint_ok = control.env_min <= advice["to"] <= control.env_max
        predicted_objective = advice["predicted_end_state"][connection["from_channel"]]
        self.recommendation = advice
        entry = self.ledger.append("adjustment_recommended", ts, {
            "episode_id": self.episode_id, "twin_id": tid, "assurance_id": status.assurance_id,
            "twin_mode": p.twin_mode, "tick": tick, "pre_state": pre_state,
            "pre_state_input_range_check": {"passed": pre_ok, "inputs": input_checks},
            "objective": {**self.req.objective, "assured_range": [self.objective_channel.env_min, self.objective_channel.env_max],
                          "via_connection": connection},
            "recommendation": advice,
            "setpoint_within_assured_range": {"passed": setpoint_ok, "assured_range": [control.env_min, control.env_max]},
            "predicted_objective_value": predicted_objective,
            "predicted_margin_above_objective": round(predicted_objective - self.objective_channel.env_min, 4),
            **self._cite(),
        })
        if not setpoint_ok:
            return self._refuse(tick, ts, "recommended setpoint is outside the assured range of the control input",
                                {"recommendation_seq": entry["seq"]})
        self.recommendation_entry = entry
        self.state = "recommended"

    def _approve(self, tick, ts) -> None:
        a = self.req.approval
        approved = a["decision"] == "approve"
        self.ledger.append("adjustment_approval", ts, {
            "episode_id": self.episode_id, "twin_id": self.product.operational_twin_id, "tick": tick,
            "approver": a["approver"], "approval_type": "human", "decision": a["decision"],
            "recommendation_entry_hash": self.recommendation_entry["entry_hash"], **self._cite(),
        })
        self.state = "approved" if approved else "declined"

    def _check(self, tick, ts) -> None:
        tid = self.product.operational_twin_id
        predicted = self.recommendation["predicted_end_state"]
        sim2real = {}
        for c in self.product.outputs:
            gaps = [gap_pct(p["readings"][(tid, c.channel_id)]["physical_value"], predicted[c.channel_id])
                    for p in self.post if is_valid_number(p["readings"][(tid, c.channel_id)]["physical_value"])]
            sim2real[c.channel_id] = {"predicted": predicted[c.channel_id], "tolerance_pct": c.tolerance_pct,
                                      "max_gap_pct": round(max(gaps), 4) if gaps else None,
                                      "passed": bool(gaps) and max(gaps) <= c.tolerance_pct}
        obj_key = (self.objective_product.operational_twin_id, self.objective_channel.channel_id)
        obj_values = [p["readings"][obj_key]["physical_value"] for p in self.post]
        met = [v for v in obj_values if is_valid_number(v) and self.objective_channel.in_envelope(v)]
        self.state = "checked"
        self.ledger.append("adjustment_post_state_check", ts, {
            "episode_id": self.episode_id, "twin_id": tid, "tick": tick,
            "check_ticks": [self.post[0]["tick"], self.post[-1]["tick"]],
            "sim2real": sim2real,
            "sim2real_passed": all(v["passed"] for v in sim2real.values()),
            "objective": {"channel": f"{obj_key[0]}/{obj_key[1]}",
                          "assured_range": [self.objective_channel.env_min, self.objective_channel.env_max],
                          "values": obj_values, "ticks_in_range": len(met), "ticks_checked": len(obj_values),
                          "min_value": min(v for v in obj_values if is_valid_number(v)),
                          "met": len(met) == len(obj_values)},
            "statuses": {t: {"status": a.level, "assurance_id": a.assurance_id} for t, a in self.monitor.status.items()},
            "note": "Assurance status is sticky: returning an input to range does not by itself re-assure a twin.",
            **self._cite(),
        })
