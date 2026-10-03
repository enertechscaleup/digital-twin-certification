"""The joint composition test: running the twins together, through their owners' endpoints.

Each twin's own evidence shows it represents its own product. It cannot show that the
twins still predict well once they feed each other, because their errors are not
independent. So before the system twin is assured, and again after any accepted
recalibration, the platform orchestrates a joint run:

1. Test points: a grid across the assured ranges of the system's external inputs (the
   inputs no connection feeds).
2. Joint run: each twin is queried in processing order; a connected input receives the
   upstream twin's PREDICTED output, never a measurement. Every exchange is recorded.
3. Interface check: every upstream predicted output must land inside the downstream
   twin's assured input range. A miss is an ``interface_invalid`` failure.
4. Interaction check: at the points where every interface holds, the joint prediction
   of each system output must stay within its output twin's tolerance against the
   combined test bench (the physical system run at the same inputs). A miss is an
   ``interaction_invalid`` failure. Points where an interface fails are not evaluated
   for interaction, as field monitoring does not evaluate outputs when an input is out
   of range.

The test records only what crossed the boundary, its own fingerprint, and the result.
"""

from __future__ import annotations

import itertools
from typing import Callable

from engine.boundary import ExchangeLog, RemoteTwin
from engine.ledger import EvidenceLedger, sha256_hex
from engine.readings import gap_pct, is_valid_number
from engine.registry import Registry

METHOD = "joint-test/1"
LEVELS = 5
RULE = ("interface: every upstream predicted output inside the downstream twin's assured input range; "
        "interaction: at points where every interface holds, the joint prediction of each system output "
        "within its output twin's tolerance against the combined test bench")
# bench(points, tick) -> one dict per sample: {"point": index, "outputs": {twin_type: {channel: value}}}
Bench = Callable[[list[dict], int | None], list[dict]]


def external_inputs(registry: Registry) -> list[tuple[str, str]]:
    fed = {(c["to_twin"], c["to_channel"]) for c in registry.system.connections}
    return [(t, c.channel_id) for t, p in registry.products.items() for c in p.inputs if (t, c.channel_id) not in fed]


def test_points(registry: Registry) -> list[dict]:
    """Each point: {"<twin>/<channel>": value} for every external input."""
    axes = []
    for t, ch in external_inputs(registry):
        c = next(c for c in registry.products[t].inputs if c.channel_id == ch)
        axes.append([c.env_min + i * (c.env_max - c.env_min) / (LEVELS - 1) for i in range(LEVELS)])
    keys = [f"{t}/{ch}" for t, ch in external_inputs(registry)]
    return [dict(zip(keys, combo)) for combo in itertools.product(*axes)]


class CompositionTester:
    def __init__(self, ledger: EvidenceLedger, registry: Registry, lineage, exchange: ExchangeLog, bench: Bench):
        self.ledger, self.registry, self.lineage, self.exchange, self.bench = ledger, registry, lineage, exchange, bench
        self.count = 0

    def run(self, twins: dict[str, RemoteTwin], ts: str, trigger: str, assurance_ids: dict[str, str],
            stage: str = "operational", tick: int | None = None) -> dict:
        """Run the joint test on the versions in operation (``twins``: logged evidence handles)."""
        reg, sys = self.registry, self.registry.system
        points = test_points(reg)
        joint: list[dict[str, dict]] = []
        with self.exchange.batch("joint") as seal:
            for pt in points:
                outs: dict[str, dict] = {}
                for t, p in reg.products.items():
                    inputs = {}
                    for c in p.inputs:
                        src = next((k for k in sys.connections if k["to_twin"] == t and k["to_channel"] == c.channel_id), None)
                        inputs[c.channel_id] = outs[src["from_twin"]][src["from_channel"]] if src else pt[f"{t}/{c.channel_id}"]
                    outs[t] = twins[t].predict(inputs)
                joint.append(outs)

        # Interface: every connection's predicted upstream value against the downstream assured range.
        interface, valid = [], [True] * len(points)
        for k in sys.connections:
            down = next(c for c in reg.products[k["to_twin"]].inputs if c.channel_id == k["to_channel"])
            values = [o[k["from_twin"]][k["from_channel"]] for o in joint]
            outside = [i for i, v in enumerate(values) if not (is_valid_number(v) and down.in_envelope(v))]
            for i in outside:
                valid[i] = False
            finite = [v for v in values if is_valid_number(v)]
            interface.append({
                "from": f"{k['from_twin']}/{k['from_channel']}", "to": f"{k['to_twin']}/{k['to_channel']}",
                "from_twin_id": reg.products[k["from_twin"]].operational_twin_id,
                "to_twin_id": reg.products[k["to_twin"]].operational_twin_id, "unit": down.unit,
                "assured_range": [down.env_min, down.env_max],
                "predicted_range": [round(min(finite), 4), round(max(finite), 4)] if finite else None,
                "points_outside": len(outside), "passed": not outside,
            })

        # Interaction: joint prediction of each system output against the combined test bench.
        samples = self.bench(points, tick)
        per_channel = {}
        for t in sys.output_constituents:
            for c in reg.products[t].outputs:
                gaps = [gap_pct(s["outputs"][t][c.channel_id], joint[s["point"]][t][c.channel_id])
                        for s in samples if valid[s["point"]]
                        and is_valid_number(s["outputs"][t][c.channel_id]) and is_valid_number(joint[s["point"]][t][c.channel_id])
                        and joint[s["point"]][t][c.channel_id] != 0]
                per_channel[f"{t}/{c.channel_id}"] = {
                    "twin_id": reg.products[t].operational_twin_id, "channel_id": c.channel_id,
                    "tolerance_pct": c.tolerance_pct, "samples": len(gaps),
                    "max_gap_pct": round(max(gaps), 4) if gaps else None,
                    "over_tolerance": sum(g > c.tolerance_pct for g in gaps),
                    "passed": bool(gaps) and max(gaps) <= c.tolerance_pct,
                }
        evaluated = sum(valid)
        interface_ok = all(i["passed"] for i in interface)
        interaction_ok = evaluated > 0 and all(v["passed"] for v in per_channel.values())

        self.count += 1
        system_ref = self.lineage.system.ref()
        body = {
            "test_id": f"cmp-{self.count:04d}", "trigger": trigger, "method": METHOD, "rule": RULE,
            **({"tick": tick} if tick is not None else {}),
            "system_twin_id": sys.design_system_twin_id if stage == "design" else sys.operational_system_twin_id,
            "system_ref": system_ref, "constituent_refs": self.lineage.constituent_refs(assurance_ids, stage),
            "external_inputs": [f"{t}/{ch}" for t, ch in external_inputs(reg)], "levels": LEVELS,
            "points": len(points), "test_inputs_sha256": sha256_hex(points), "exchange": seal,
            "bench_samples": len(samples), "bench_readings_sha256": sha256_hex(samples),
            "interface": {"passed": interface_ok, "connections": interface},
            "interaction": {"passed": interaction_ok, "evaluated_points": evaluated,
                            "not_evaluated_points": len(points) - evaluated,
                            "not_evaluated_reason": "an upstream prediction outside the downstream assured range",
                            "per_channel": per_channel},
            "passed": interface_ok and interaction_ok,
        }
        body["test_fingerprint"] = sha256_hex({k: body[k] for k in (
            "method", "rule", "system_ref", "test_inputs_sha256", "exchange", "bench_readings_sha256",
            "interface", "interaction", "passed")})
        return self.ledger.append("composition_test", ts, body)


def failure_reasons(test: dict) -> list[dict]:
    """The specific, distinguishable reasons a joint test failed."""
    p = test["payload"]
    out = []
    for i in p["interface"]["connections"]:
        if not i["passed"]:
            lo, hi = i["predicted_range"] or (None, None)
            out.append({"level": "flagged", "cause": "interface_invalid", "constituent": i["to_twin_id"],
                        "channel_id": i["to"].split("/")[1], "composition_test": p["test_id"],
                        "detail": f"joint run: {i['from']} predictions {lo:g}–{hi:g} {i['unit']} leave {i['to']}'s "
                                  f"assured range {i['assured_range'][0]:g}–{i['assured_range'][1]:g} {i['unit']} "
                                  f"at {i['points_outside']} of {p['points']} test points"})
    inter = p["interaction"]
    if not inter["passed"]:
        if inter["evaluated_points"] == 0:
            out.append({"level": "flagged", "cause": "interaction_invalid", "composition_test": p["test_id"],
                        "detail": "joint run: no test point keeps every interface inside its assured range, "
                                  "so the combined behaviour could not be checked"})
        for key, ch in inter["per_channel"].items():
            if not ch["passed"] and ch["samples"]:
                out.append({"level": "flagged", "cause": "interaction_invalid", "constituent": ch["twin_id"],
                            "channel_id": ch["channel_id"], "composition_test": p["test_id"],
                            "detail": f"joint run: predicted {key} differs from the combined test bench by up to "
                                      f"{ch['max_gap_pct']:g}% (tolerance {ch['tolerance_pct']:g}%)"})
    return out
