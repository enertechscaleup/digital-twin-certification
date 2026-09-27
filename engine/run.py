"""End-to-end assurance run: verify and bench-validate each Design Twin, issue
assurance, clone Operational Twins, assure the composed system twin, then
monitor the field stream -- all recorded in one evidence ledger."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from engine import ENGINE_VERSION
from engine.ledger import EvidenceLedger
from engine.monitor import FieldMonitor
from engine.protocol import EscalationProtocol
from engine.readings import ingest
from engine.recalibration import Recalibrator, run_recalibration
from engine.registry import Registry, load_registry
from engine.validation import bench_validate
from engine.verification import verify
from telemetry.faults import Scenario
from telemetry.generator import GENERATOR_VERSION, TelemetryGenerator


@dataclass
class RunResult:
    ledger: EvidenceLedger
    timeline: list[dict]
    readings: list[dict]  # every ingested field reading, as the engine saw it
    monitor: FieldMonitor | None
    assured: bool  # did every twin pass design-time assurance?


def _asr_id(twin_id: str, version: int = 1) -> str:
    return f"asr-{twin_id}-v{version}"


def run_assurance(
    scenario: Scenario,
    seed: int = 42,
    start_time: datetime | None = None,
    ledger_path: Path | None = None,
    protocol: EscalationProtocol | None = None,
    registry: Registry | None = None,
    twins: dict | None = None,
    checkpoint_every: int = 10,
    recalibrator: Recalibrator | None = None,
) -> RunResult:
    protocol = protocol or EscalationProtocol()
    registry = registry or load_registry()
    gen = TelemetryGenerator(seed=seed, start_time=start_time, twins=twins)
    ts0 = gen._timestamp(0)
    ledger = EvidenceLedger(ledger_path)

    ledger.append("run_started", ts0, {
        "engine_version": ENGINE_VERSION, "generator_version": GENERATOR_VERSION,
        "scenario": scenario.name, "seed": seed, "escalation_protocol": protocol.to_dict(),
    })

    # Design time: verify and bench-validate each product Design Twin.
    product_ids: dict[str, str] = {}
    all_assured = True
    for t, product in registry.products.items():
        model = gen.twins[t]
        v = ledger.append("verification", ts0, verify(product, model, protocol))
        bench = [ingest(asdict(r)) for batch in gen.bench_sweep(t) for r in batch]
        b = ledger.append("bench_validation", ts0, bench_validate(product, bench))
        if not (v["payload"]["passed"] and b["payload"]["passed"]):
            all_assured = False
            ledger.append("assurance_refused", ts0, {
                "twin_id": product.design_twin_id,
                "verification_passed": v["payload"]["passed"], "bench_validation_passed": b["payload"]["passed"],
                "evidence_seq": [v["seq"], b["seq"]],
            })
            continue
        design_asr = _asr_id(product.design_twin_id)
        ledger.append("assurance_issued", ts0, {
            "assurance_id": design_asr, "twin_id": product.design_twin_id, "stage": "design",
            "composition": "product", "status": "assured", "twin_version": model.version,
            "twin_mode": product.twin_mode, "vendor": product.vendor,
            "evidence_seq": [v["seq"], b["seq"]], "envelope": product.envelope_snapshot(),
        })
        product_ids[t] = _asr_id(product.operational_twin_id)
        ledger.append("assurance_issued", ts0, {
            "assurance_id": product_ids[t], "twin_id": product.operational_twin_id, "stage": "operational",
            "composition": "product", "status": "assured", "twin_version": model.version,
            "parent_twin_id": product.design_twin_id, "parent_assurance_id": design_asr,
            "asset_id": product.asset_id, "twin_mode": product.twin_mode,
        })

    if not all_assured:
        ledger.append("run_completed", ts0, {"reason": "design-time assurance refused; no field monitoring"})
        ledger.close()
        return RunResult(ledger, [], [], None, False)

    # A system twin can only be composed from assured product twins.
    sys = registry.system
    design_constituents = [_asr_id(registry.products[t].design_twin_id) for t in sys.constituents]
    ledger.append("composition_assured", ts0, {
        "composition_assurance_id": _asr_id(sys.design_system_twin_id), "system_twin_id": sys.design_system_twin_id,
        "stage": "design", "constituent_assurance_ids": design_constituents,
        "output_constituents": list(sys.output_constituents),
    })
    system_asr = _asr_id(sys.operational_system_twin_id)
    ledger.append("composition_assured", ts0, {
        "composition_assurance_id": system_asr, "system_twin_id": sys.operational_system_twin_id,
        "stage": "operational", "parent_twin_id": sys.design_system_twin_id,
        "constituent_assurance_ids": [product_ids[t] for t in sys.constituents],
        "output_constituents": list(sys.output_constituents),
    })

    # Operation: field validation and escalation, tick by tick.
    monitor = FieldMonitor(registry, protocol, ledger, product_ids, system_asr, checkpoint_every)
    readings: list[dict] = []
    timeline = []
    recal = scenario.recalibration
    if recal and recalibrator is None:
        raise ValueError("scenario requests recalibration but no twin owner (recalibrator) was supplied")
    for batch in gen.field_run(scenario):
        tick_readings = [ingest(asdict(r)) for r in batch]
        readings.extend(tick_readings)
        timeline.append(monitor.process_tick(tick_readings))
        # The generator produces each tick lazily, so a recalibrated twin swapped
        # in here is the one the operator runs from the requested tick onward.
        if recal and tick_readings[0]["tick"] + 1 == recal.at_tick:
            product = registry.products[recal.twin_type]
            new_twin = run_recalibration(ledger, monitor, product, gen.twins[recal.twin_type], readings,
                                         recal.at_tick, gen._timestamp(recal.at_tick), protocol, recalibrator)
            if new_twin is not None:
                gen.twins[recal.twin_type] = new_twin
    monitor.finish()
    ledger.append("run_completed", timeline[-1]["timestamp"] if timeline else ts0, {
        "ticks": len(timeline),
        "final_status": {tid: {"level": a.level, "assurance_id": a.assurance_id} for tid, a in monitor.status.items()},
    })
    ledger.close()
    return RunResult(ledger, timeline, readings, monitor, True)


def write_jsonl(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
