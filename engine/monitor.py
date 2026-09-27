"""Field monitoring: classify every live reading, escalate assurance status,
cascade it through the system twin, and record everything in the ledger.

Per reading, checks run in a fixed order and the first that applies wins:

1. Data quality -- the reading itself is bad (dropout: missing; stuck: exact
   value for the protocol's number of readings in a row; spike: jump beyond the protocol's limit
   versus the last accepted value). The sensor is blamed, not the twin.
2. Envelope violation -- an input is outside its assured envelope. The twin
   was never validated there, so its outputs are *not evaluated* for Sim2Real.
3. Gap exceedance (Sim2Real) -- inputs are clean and in-envelope, but an
   output's gap exceeds tolerance.

Readings that are not evaluated (data quality, or outputs while an input is
bad or out of envelope) neither advance nor reset the consecutive counters.

Status is sticky: Assured -> Flagged -> Nullified, returning to Assured only
through recalibration and a new assurance version.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.ledger import EvidenceLedger, sha256_hex
from engine.protocol import EscalationProtocol
from engine.readings import gap_pct, is_valid_number
from engine.registry import ProductTwin, Registry

LEVELS = ("assured", "flagged", "nullified")
SEVERITY_ORDER = ("low", "medium", "high")


def _worse(a: str, b: str) -> str:
    return a if LEVELS.index(a) >= LEVELS.index(b) else b


@dataclass
class Assurance:
    twin_id: str
    assurance_id: str
    level: str = "assured"
    reasons: list[dict] = field(default_factory=list)

    def reason_keys(self) -> set[tuple]:
        return {_reason_key(r) for r in self.reasons}


def _reason_key(r: dict) -> tuple:
    return (r["level"], r["cause"], r.get("channel_id"), r.get("constituent"))


@dataclass
class _ChannelState:
    last_reported: float | None = None
    last_accepted: float | None = None
    gap_run: int = 0  # consecutive readings beyond tolerance
    critical_run: int = 0  # consecutive readings beyond tolerance x multiplier
    envelope_run: int = 0  # consecutive out-of-envelope readings (inputs)
    identical_run: int = 0  # consecutive identical reported values


@dataclass
class _Episode:
    anomaly_id: str
    kind: str  # "data_quality:<subtype>" | "envelope_violation" | "gap_exceedance"
    readings: int = 0
    max_severity: str = "low"
    max_gap_pct: float | None = None


class FieldMonitor:
    def __init__(self, registry: Registry, protocol: EscalationProtocol, ledger: EvidenceLedger,
                 product_assurance_ids: dict[str, str], system_assurance_id: str, checkpoint_every: int = 10):
        self.registry = registry
        self.protocol = protocol
        self.ledger = ledger
        self.checkpoint_every = checkpoint_every
        self.status = {
            p.operational_twin_id: Assurance(p.operational_twin_id, product_assurance_ids[t])
            for t, p in registry.products.items()
        }
        sys_id = registry.system.operational_system_twin_id
        self.status[sys_id] = Assurance(sys_id, system_assurance_id)
        self._channels: dict[tuple[str, str], _ChannelState] = {}
        self._episodes: dict[tuple[str, str], _Episode] = {}
        self._anomaly_count = 0
        self._pending_readings: list[dict] = []
        self._pending_from_tick: int | None = None
        self._last_tick: int | None = None
        self._last_timestamp: str | None = None

    # -- public ----------------------------------------------------------

    def process_tick(self, readings: list[dict]) -> dict:
        """``readings``: one tick's ingested readings for all twins. Returns a
        per-tick summary (classifications and statuses) for the timeline."""
        tick, ts = readings[0]["tick"], readings[0]["timestamp"]
        by_twin: dict[str, dict[str, dict]] = {}
        for r in readings:
            by_twin.setdefault(r["twin_id"], {})[r["channel_id"]] = r

        classifications = {}
        for product in self.registry.products.values():
            rows = by_twin.get(product.operational_twin_id, {})
            classifications[product.operational_twin_id] = self._evaluate_product(product, rows, tick, ts)
        self._evaluate_system(tick, ts)

        if self._pending_from_tick is None:
            self._pending_from_tick = tick
        self._pending_readings.extend(readings)
        self._last_tick, self._last_timestamp = tick, ts
        if (tick - self._pending_from_tick + 1) >= self.checkpoint_every:
            self._checkpoint()

        return {
            "tick": tick,
            "timestamp": ts,
            "status": {tid: a.level for tid, a in self.status.items()},
            "classifications": classifications,
        }

    def finish(self) -> None:
        """Seal any readings not yet covered by a checkpoint."""
        if self._pending_readings:
            self._checkpoint()

    def acknowledge(self, anomaly_id: str, acknowledged_by: str, action: str, timestamp: str) -> dict:
        """Record a human response to an anomaly -- who, when, what followed."""
        return self.ledger.append("anomaly_acknowledged", timestamp, {
            "anomaly_id": anomaly_id, "acknowledged_by": acknowledged_by, "action": action,
        })

    # -- product twins ---------------------------------------------------

    def _state(self, twin_id: str, channel_id: str) -> _ChannelState:
        return self._channels.setdefault((twin_id, channel_id), _ChannelState())

    def _evaluate_product(self, product: ProductTwin, rows: dict[str, dict], tick: int, ts: str) -> dict:
        tid = product.operational_twin_id
        result: dict[str, dict] = {}

        # 1. Data quality, on every channel.
        for c in product.channels:
            r = rows.get(c.channel_id)
            v = None if r is None else r["physical_value"]
            st = self._state(tid, c.channel_id)
            subtype = None
            st.identical_run = st.identical_run + 1 if (v is not None and v == st.last_reported) else 1
            if not is_valid_number(v):
                subtype = "dropout"
            elif st.identical_run >= self.protocol.stuck_after_identical:
                subtype = "stuck"
            elif st.last_accepted is not None and st.last_accepted != 0 and \
                    100 * abs(v - st.last_accepted) / abs(st.last_accepted) > self.protocol.spike_jump_pct:
                subtype = "spike"
            st.last_reported = v
            if subtype:
                result[c.channel_id] = {"class": "data_quality", "subtype": subtype, "severity": "low"}
            else:
                st.last_accepted = v

        # 2. Envelope, on clean inputs.
        for c in product.inputs:
            if c.channel_id in result:
                continue
            v = rows[c.channel_id]["physical_value"]
            st = self._state(tid, c.channel_id)
            if c.in_envelope(v):
                result[c.channel_id] = {"class": "ok"}
                st.envelope_run = 0
            else:
                result[c.channel_id] = {"class": "envelope_violation", "severity": "medium",
                                        "value": v, "envelope": [c.env_min, c.env_max]}
                st.envelope_run += 1

        # 3. Gap (Sim2Real), on clean outputs whose inputs are clean and in-envelope.
        bad_inputs = [c.channel_id for c in product.inputs if result[c.channel_id]["class"] != "ok"]
        for c in product.outputs:
            if c.channel_id in result:
                continue
            r = rows[c.channel_id]
            st = self._state(tid, c.channel_id)
            if bad_inputs:
                reason = ("input_data_quality" if any(result[i]["class"] == "data_quality" for i in bad_inputs)
                          else "input_outside_envelope")
                result[c.channel_id] = {"class": "not_evaluated", "reason": reason, "inputs": bad_inputs}
                continue
            if not is_valid_number(r["predicted_value"]) or r["predicted_value"] == 0:
                result[c.channel_id] = {"class": "not_evaluated", "reason": "no_valid_prediction"}
                continue
            g = gap_pct(r["physical_value"], r["predicted_value"])
            critical_limit = c.tolerance_pct * self.protocol.nullify_tolerance_multiplier
            if g > c.tolerance_pct:
                st.gap_run += 1
                st.critical_run = st.critical_run + 1 if g > critical_limit else 0
                result[c.channel_id] = {"class": "gap_exceedance", "gap_pct": round(g, 4),
                                        "severity": "high" if g > critical_limit else "medium"}
            else:
                st.gap_run = st.critical_run = 0
                result[c.channel_id] = {"class": "ok", "gap_pct": round(g, 4)}

        self._track_anomalies(product, rows, result, tick, ts)
        self._escalate_product(product, tick, ts)
        return result

    def _track_anomalies(self, product: ProductTwin, rows: dict, result: dict, tick: int, ts: str) -> None:
        tid = product.operational_twin_id
        for c in product.channels:
            res = result[c.channel_id]
            kind = None
            if res["class"] == "data_quality":
                kind = f"data_quality:{res['subtype']}"
            elif res["class"] in ("envelope_violation", "gap_exceedance"):
                kind = res["class"]
            key = (tid, c.channel_id)
            ep = self._episodes.get(key)
            if ep and ep.kind != kind:
                self._close_episode(key, tick, ts)
                ep = None
            if kind is None:
                continue
            if ep is None:
                self._anomaly_count += 1
                ep = _Episode(f"anm-{self._anomaly_count:04d}", kind)
                self._episodes[key] = ep
                r = rows.get(c.channel_id) or {}
                self.ledger.append("anomaly_opened", ts, {
                    "anomaly_id": ep.anomaly_id, "twin_id": tid, "channel_id": c.channel_id,
                    "type": kind.split(":")[0], "subtype": kind.split(":")[1] if ":" in kind else None,
                    "severity": res["severity"], "tick": tick,
                    "physical_value": r.get("physical_value"), "predicted_value": r.get("predicted_value"),
                    "gap_pct": res.get("gap_pct"),
                })
            ep.readings += 1
            if SEVERITY_ORDER.index(res["severity"]) > SEVERITY_ORDER.index(ep.max_severity):
                ep.max_severity = res["severity"]
            if res.get("gap_pct") is not None:
                ep.max_gap_pct = max(ep.max_gap_pct or 0.0, res["gap_pct"])

    def _close_episode(self, key: tuple[str, str], tick: int, ts: str) -> None:
        ep = self._episodes.pop(key)
        self.ledger.append("anomaly_closed", ts, {
            "anomaly_id": ep.anomaly_id, "twin_id": key[0], "channel_id": key[1], "type": ep.kind.split(":")[0],
            "closed_at_tick": tick, "readings": ep.readings,
            "max_severity": ep.max_severity, "max_gap_pct": ep.max_gap_pct,
        })

    def _escalate_product(self, product: ProductTwin, tick: int, ts: str) -> None:
        p = self.protocol
        tid = product.operational_twin_id
        reasons = []
        for c in product.outputs:
            st = self._state(tid, c.channel_id)
            if st.critical_run >= p.nullify_after_consecutive:
                reasons.append({"level": "nullified", "cause": "gap_exceedance", "channel_id": c.channel_id,
                                "detail": f"{st.critical_run} consecutive readings beyond "
                                          f"{c.tolerance_pct * p.nullify_tolerance_multiplier:g}%"})
            if st.gap_run >= p.flag_after_consecutive:
                reasons.append({"level": "flagged", "cause": "gap_exceedance", "channel_id": c.channel_id,
                                "detail": f"{st.gap_run} consecutive readings beyond {c.tolerance_pct:g}%"})
        for c in product.inputs:
            st = self._state(tid, c.channel_id)
            if st.envelope_run >= p.flag_after_consecutive:
                reasons.append({"level": "nullified" if p.envelope_can_nullify else "flagged",
                                "cause": "envelope_violation", "channel_id": c.channel_id,
                                "detail": f"{st.envelope_run} consecutive readings outside "
                                          f"[{c.env_min:g}, {c.env_max:g}] {c.unit}"})
        self._apply(tid, reasons, tick, ts)

    # -- system twin -----------------------------------------------------

    def _evaluate_system(self, tick: int, ts: str) -> None:
        sys = self.registry.system
        reasons = []
        for t in sys.constituents:
            member = self.status[self.registry.products[t].operational_twin_id]
            if member.level == "nullified":
                reasons.append({"level": "flagged", "cause": "cascade", "constituent": member.twin_id,
                                "detail": f"constituent {member.twin_id} is nullified",
                                "root_causes": [r for r in member.reasons if r["level"] == "nullified"]})
        for t in sys.output_constituents:
            member = self.status[self.registry.products[t].operational_twin_id]
            if member.level != "assured":
                reasons.append({"level": member.level, "cause": "own_output", "constituent": member.twin_id,
                                "detail": f"output constituent {member.twin_id} is {member.level}",
                                "root_causes": [r for r in member.reasons if r["level"] == member.level]})
        self._apply(sys.operational_system_twin_id, reasons, tick, ts)

    # -- shared ----------------------------------------------------------

    def _apply(self, twin_id: str, candidate_reasons: list[dict], tick: int, ts: str) -> None:
        a = self.status[twin_id]
        known = a.reason_keys()
        new = [r for r in candidate_reasons if _reason_key(r) not in known]
        if not new:
            return
        a.reasons.extend(new)
        new_level = a.level
        for r in new:
            new_level = _worse(new_level, r["level"])
        payload = {"twin_id": twin_id, "assurance_id": a.assurance_id, "tick": tick, "new_reasons": new}
        if new_level != a.level:
            self.ledger.append("assurance_status_changed", ts, {**payload, "from": a.level, "to": new_level})
            a.level = new_level
        else:
            self.ledger.append("assurance_reason_added", ts, {**payload, "status": a.level})

    def _checkpoint(self) -> None:
        self.ledger.append("readings_checkpoint", self._last_timestamp, {
            "from_tick": self._pending_from_tick, "to_tick": self._last_tick,
            "readings": len(self._pending_readings), "readings_sha256": sha256_hex(self._pending_readings),
        })
        self._pending_readings = []
        self._pending_from_tick = None
