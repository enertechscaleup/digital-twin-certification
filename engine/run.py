"""End-to-end assurance run: verify and bench-validate each Design Twin, issue
assurance, clone Operational Twins, test the composed system twin by running
the twins together, then monitor the field stream -- all recorded in one
evidence ledger.

Every twin is reached only through its owner's endpoint (engine/boundary.py):
``vendors`` maps each twin type to a connection. The platform never sees a
twin's formula or parameters, only what crosses the boundary."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from engine import ENGINE_VERSION
from engine.adjustment import AdjustmentEpisode
from engine.boundary import Connection, ExchangeLog, RemoteTwin
from engine.composition import CompositionTester, failure_reasons
from engine.ledger import EvidenceLedger
from engine.lineage import Lineage
from engine.monitor import FieldMonitor
from engine.protocol import EscalationProtocol
from engine.readings import ingest
from engine.recalibration import run_recalibration
from engine.registry import Registry, load_registry
from engine.validation import bench_validate
from engine.verification import verify
from projects import Project, load_project
from telemetry.faults import Scenario
from telemetry.generator import GENERATOR_VERSION, TelemetryGenerator


@dataclass
class RunResult:
    ledger: EvidenceLedger
    timeline: list[dict]
    readings: list[dict]  # every ingested field reading, as the engine saw it
    monitor: FieldMonitor | None
    assured: bool  # did every twin, and their composition, pass design-time assurance?
    exchange: list[dict] = field(default_factory=list)  # every input/output exchange at the boundary


def _asr_id(twin_id: str, version: int = 1) -> str:
    return f"asr-{twin_id}-v{version}"


def run_assurance(
    scenario: Scenario,
    vendors: dict[str, Connection],
    seed: int = 42,
    start_time: datetime | None = None,
    ledger_path: Path | None = None,
    protocol: EscalationProtocol | None = None,
    registry: Registry | None = None,
    checkpoint_every: int = 10,
    project: Project | None = None,
    identities: list[dict] | None = None,
    code_commit: str | None = None,
    field_source: Iterable[list[dict]] | None = None,
    readings_source: dict | None = None,
) -> RunResult:
    """``vendors``: a connection to each twin owner's endpoint, by twin type.
    ``project`` defaults to the oil & gas compressor train (projects/compressor_train.json).
    ``identities`` defaults to the platform's permanent twin identities (registry/identities.json);
    ``code_commit`` is the platform commit, sealed beside each registered version.

    ``field_source`` (replay mode, engine/replay.py): the field readings, one list of ingested dicts
    per tick, taken from outside instead of the generator. Design time, the joint tests and the
    owners' recalibration and advice are unchanged. Left as None, the run is exactly as before.
    ``readings_source``: recorded in a ``field_readings_source`` entry just before ``run_completed``;
    only allowed with ``field_source``."""
    if readings_source is not None and field_source is None:
        raise ValueError("readings_source describes an external field_source; none was given")
    protocol = protocol or EscalationProtocol()
    project = project or load_project()
    registry = registry or load_registry(project)
    # The asset side (the generator) queries the same endpoints for the predictions in its data
    # stream; those queries are the operator's, not evidence the platform relies on.
    operator = {t: RemoteTwin(vendors[t], t) for t in project.processing_order}
    gen = TelemetryGenerator(seed=seed, start_time=start_time, twins=operator, project=project)
    ts0 = gen._timestamp(0)
    ledger = EvidenceLedger(ledger_path)
    exchange = ExchangeLog()
    lineage = Lineage(ledger, registry, project.project_id, exchange, identities, code_commit)
    evidence = {t: lineage.evidence_twin(t, RemoteTwin(vendors[t], t, operator[t].version)) for t in registry.products}
    tester = CompositionTester(ledger, registry, lineage, exchange, lambda points, tick: gen.system_bench(points, scenario, tick))

    ledger.append("run_started", ts0, {
        "engine_version": ENGINE_VERSION, "generator_version": GENERATOR_VERSION,
        "scenario": scenario.name, "seed": seed, "escalation_protocol": protocol.to_dict(),
    })

    # Design time: verify and bench-validate each product Design Twin.
    product_ids: dict[str, str] = {}
    all_assured = True
    for t, product in registry.products.items():
        twin = evidence[t]
        # The version under test is measured and sealed before any evidence about it.
        node = lineage.register_product(t, product, twin, ts0, "twin owner (registration)")
        lineage.adopt(t, node)
        cite = {"twin_ref": node.ref()}
        with exchange.batch("verification") as seal:
            record = verify(product, twin, protocol)
        v = ledger.append("verification", ts0, {**record, "exchange": seal, **cite})
        bench = [ingest(asdict(r)) for batch in gen.bench_sweep(t) for r in batch]
        b = ledger.append("bench_validation", ts0, {**bench_validate(product, bench), **cite})
        if not (v["payload"]["passed"] and b["payload"]["passed"]):
            all_assured = False
            ledger.append("assurance_refused", ts0, {
                "twin_id": product.design_twin_id,
                "verification_passed": v["payload"]["passed"], "bench_validation_passed": b["payload"]["passed"],
                "evidence_seq": [v["seq"], b["seq"]], **cite,
            })
            continue
        design_asr = _asr_id(product.design_twin_id)
        ledger.append("assurance_issued", ts0, {
            "assurance_id": design_asr, "twin_id": product.design_twin_id, "stage": "design",
            "composition": "product", "status": "assured", "twin_version": twin.version,
            "twin_mode": product.twin_mode, "vendor": product.vendor,
            "evidence_seq": [v["seq"], b["seq"]], "envelope": product.envelope_snapshot(), **cite,
        })
        product_ids[t] = _asr_id(product.operational_twin_id)
        ledger.append("assurance_issued", ts0, {
            "assurance_id": product_ids[t], "twin_id": product.operational_twin_id, "stage": "operational",
            "composition": "product", "status": "assured", "twin_version": twin.version,
            "parent_twin_id": product.design_twin_id, "parent_assurance_id": design_asr,
            "asset_id": product.asset_id, "twin_mode": product.twin_mode, **cite,
        })

    def finish(reason: str) -> RunResult:
        ledger.append("run_completed", ts0, {"reason": reason, "final_refs": lineage.final_refs()})
        ledger.close()
        return RunResult(ledger, [], [], None, False, exchange.records)

    if not all_assured:
        return finish("design-time assurance refused; no field monitoring")

    # A system twin can only be composed from assured product twins, and only if they still
    # predict well together: its version is sealed, then the twins are run jointly.
    sys = registry.system
    system_ref = lineage.register_system(ts0, "platform (composition)").ref()
    design_ids = {t: _asr_id(registry.products[t].design_twin_id) for t in sys.constituents}
    test = tester.run(evidence, ts0, "initial build", design_ids, stage="design")
    if not test["payload"]["passed"]:
        ledger.append("composition_refused", ts0, {
            "system_twin_id": sys.design_system_twin_id, "system_ref": system_ref,
            "constituent_refs": lineage.constituent_refs(design_ids, "design"),
            "composition_test": test["payload"]["test_id"], "test_seq": test["seq"],
            "reasons": failure_reasons(test),
        })
        return finish("system composition refused by its joint test; no field monitoring")
    joint = {"composition_test": test["payload"]["test_id"], "test_seq": test["seq"],
             "test_fingerprint": test["payload"]["test_fingerprint"]}
    ledger.append("composition_assured", ts0, {
        "composition_assurance_id": _asr_id(sys.design_system_twin_id), "system_twin_id": sys.design_system_twin_id,
        "stage": "design", "constituent_assurance_ids": list(design_ids.values()),
        "output_constituents": list(sys.output_constituents),
        "system_ref": system_ref, "constituent_refs": lineage.constituent_refs(design_ids, "design"), **joint,
    })
    system_asr = _asr_id(sys.operational_system_twin_id)
    ledger.append("composition_assured", ts0, {
        "composition_assurance_id": system_asr, "system_twin_id": sys.operational_system_twin_id,
        "stage": "operational", "parent_twin_id": sys.design_system_twin_id,
        "constituent_assurance_ids": [product_ids[t] for t in sys.constituents],
        "output_constituents": list(sys.output_constituents),
        "system_ref": system_ref, "constituent_refs": lineage.constituent_refs(product_ids), **joint,
    })

    # Operation: field validation and escalation, tick by tick.
    monitor = FieldMonitor(registry, protocol, ledger, product_ids, system_asr, checkpoint_every, lineage)
    readings: list[dict] = []
    timeline = []
    recal = scenario.recalibration
    episode = AdjustmentEpisode(scenario.adjustment, registry, ledger, monitor) if scenario.adjustment else None
    # In replay mode the readings already carry any approved setpoint, so the adjustment episode's
    # write into the generator (before_tick) has no effect on them.
    for batch in (gen.field_run(scenario) if field_source is None else field_source):
        tick_readings = [ingest(r if isinstance(r, dict) else asdict(r)) for r in batch]
        readings.extend(tick_readings)
        timeline.append(monitor.process_tick(tick_readings))
        tick = tick_readings[0]["tick"]
        if episode:
            episode.after_tick(tick, tick_readings[0]["timestamp"], tick_readings, timeline[-1]["classifications"],
                               gen.twins[scenario.adjustment.twin_type])
        # The generator produces each tick lazily, so a recalibrated twin swapped
        # in here is the one the operator runs from the requested tick onward.
        if recal and tick + 1 == recal.at_tick:
            t = recal.twin_type
            accepted = run_recalibration(ledger, monitor, registry.products[t], evidence[t], readings,
                                         recal.at_tick, gen._timestamp(recal.at_tick), protocol, tester, evidence)
            if accepted is not None:
                evidence[t] = accepted
                gen.twins[t] = RemoteTwin(vendors[t], t, accepted.version)
        if episode:
            episode.before_tick(tick + 1, gen._timestamp(tick + 1), gen)
    monitor.finish()
    if readings_source is not None:
        # Last but one, so no entry that cites an earlier entry's seq moves.
        ledger.append("field_readings_source", timeline[-1]["timestamp"] if timeline else ts0, readings_source)
    ledger.append("run_completed", timeline[-1]["timestamp"] if timeline else ts0, {
        "ticks": len(timeline),
        "final_status": {tid: {"level": a.level, "assurance_id": a.assurance_id} for tid, a in monitor.status.items()},
        "final_refs": lineage.final_refs(),
    })
    ledger.close()
    return RunResult(ledger, timeline, readings, monitor, True, exchange.records)


def write_jsonl(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
