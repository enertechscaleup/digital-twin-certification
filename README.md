# Digital Twin Certification

A domain-agnostic test-bed and governance layer that independently records,
measures, and assures the gap between a digital twin's simulated behaviour
and real-world behaviour. Prototype for the Google Cloud AI Builder Cup 2026.

## Phase 1: telemetry generator

Synthetic data for two product twins: a **motor** (volt/current in,
speed/vibration out) and the **compressor** it drives (speed/flow in,
pressure/temperature out). The motor's real shaft speed feeds the compressor's
speed input. Each reading carries the *physical reference* and the *twin
prediction* side by side. The generator never computes assurance status;
the assurance engine (Phase 2) does that.

The formulas are illustrative and make no engineering claim.

Requires Python 3.11+. No third-party packages.

```bash
# Test-bench sweep across each twin's assured input range
python3 -m telemetry bench --twin all

# Operational stream driven by a scenario (as fast as possible)
python3 -m telemetry field --scenario scenarios/demo_wear_to_nullified.json

# Same, paced at the real 2-second tick cadence
python3 -m telemetry field --scenario scenarios/healthy.json --realtime

# Tests
python3 -m unittest -v
```

Output lands in `data/` as `<run_id>.jsonl` (one reading per line) plus
`<run_id>.manifest.json` (seed, scenario, twin versions, config hashes).

### Layout

| Path | What it is |
|---|---|
| `telemetry/config/*.json` | Channels, units, assured envelopes, tolerances, operating profile per twin |
| `telemetry/models.py` | Twin model (prediction) and physical model (the "real" machine) |
| `telemetry/faults.py` | Fault injectors: wear drift, envelope violation, data-quality (spike / dropout / stuck); scenario loader |
| `telemetry/generator.py` | Bench sweep and field stream |
| `telemetry/sinks.py` | Output destinations (file, in-memory). New destinations plug in here |
| `scenarios/*.json` | Demo runs: `healthy`, `demo_wear_to_nullified`, `faults_showcase` |

### Key behaviours

- **Reproducible**: same seed + scenario + start time gives identical data.
- **Fast-forward wear**: `operational_hours_per_tick` compresses asset ageing
  (for example 1 tick = 24 operational hours). The stream cadence stays at 2 s.
- **Ground-truth labels**: `injected_faults` records what was injected, for
  testing the engine only. The engine must never read it.

## Phase 2a: assurance engine

Deterministic: no language model is involved in any pass / flag / nullify
decision. Run with:

```bash
python3 -m engine run --scenario scenarios/demo_wear_to_nullified.json
python3 -m engine verify-ledger data/assurance-demo_wear_to_nullified-seed42.ledger.jsonl
```

What a run does, all recorded in one hash-chained evidence ledger
(`data/<run>.ledger.jsonl`), plus a per-tick status timeline:

1. **Verification** of each Design Twin alone: deterministic, complete, finite,
   and within its declared output ranges across the assured input sweep.
2. **Bench validation** against synthetic test-bench data: every output
   reading valid and within tolerance.
3. **Assurance issued** to each Design Twin and its Operational Twin; the
   system twin is composed only from assured product twins.
4. **Field monitoring**, each reading classified in a fixed order: data quality
   (dropout / stuck / spike) → envelope violation → gap exceedance (Sim2Real).
   Outputs are not evaluated while an input is bad or out of envelope.
5. **Escalation** (sticky): Flagged after 3 consecutive gap exceedances or
   out-of-envelope inputs; Nullified after 10 consecutive readings beyond double
   tolerance. Envelope violations never nullify.
6. **Cascade with root cause**: the system twin is at least Flagged while any
   constituent is Nullified, and takes its output constituent's own status;
   each reason names the constituent and cause.
7. **Readings checkpoints** every 10 ticks seal the raw readings' SHA-256 into
   the chain, so every reading is covered.

The ledger proves the record was not altered after the fact, not that the
sensor data was truthful. `engine/protocol.py` holds the escalation rules;
they are written into the ledger at verification time.

| Path | What it is |
|---|---|
| `engine/ledger.py` | Hash-chained ledger and chain verification |
| `engine/protocol.py` | Escalation and data-quality rules |
| `engine/registry.py`, `engine/config/system.json` | Twin registration and system composition |
| `engine/verification.py`, `engine/validation.py` | Design-time checks |
| `engine/monitor.py` | Field classification, escalation, cascade, anomalies |
| `engine/run.py` | End-to-end orchestration |

## Cloud Run skeleton

A minimal FastAPI app (`app/main.py`) serving a live view of the generator:
`/` (page, refreshes every 2 s), `/api/latest` (JSON), `/health`. It is
stateless: each request works out the current tick from the clock and replays
the deterministic scenario, so every instance serves identical data. The
scenario is chosen with the `SCENARIO` env var (default `healthy`).

Deploy (builds run as a dedicated build-only service account, `dtc-builder`,
holding only `roles/cloudbuild.builds.builder`; the service runs as a
dedicated runtime service account, `dtc-runtime`, which holds no roles at all):

```bash
gcloud run deploy digital-twin-certification --source . --region us-central1 \
  --allow-unauthenticated \
  --service-account=dtc-runtime@project-46053a8a-6324-40f0-ba8.iam.gserviceaccount.com \
  --build-service-account=projects/project-46053a8a-6324-40f0-ba8/serviceAccounts/dtc-builder@project-46053a8a-6324-40f0-ba8.iam.gserviceaccount.com
```
