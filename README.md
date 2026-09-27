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

## Phase 2b: Gemini explanations (supplementary)

A separate `explain/` package the engine never imports, so no AI output can
reach an assurance decision. For each engine event it writes a structured,
grounded explanation:

- `status_explanation`: why a product twin's status changed, across correlated
  channels and connected twins.
- `data_quality_suggestion`: an independent second opinion on a sensor anomaly,
  for a human to confirm.
- `impact_narrative`: plain-language impact when the system twin's status
  changes, traced to the constituent driving it.

Setup (needs Python 3.12, plus `gcloud auth application-default login` once):

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python --only-binary cryptography -r requirements-dev.txt
```

Run on a saved engine run, then verify:

```bash
.venv/bin/python -m explain run    data/assurance-demo_wear_to_nullified-seed42
.venv/bin/python -m explain verify data/assurance-demo_wear_to_nullified-seed42
```

- **Pinned model**: `gemini-3.8-flash` on the Vertex AI `global` endpoint (it is
  not served from us-central1), temperature 0, JSON-schema output.
- **Grounded**: facts come only from integrity-checked evidence (the ledger chain
  plus the readings' checkpoint hashes). Altered evidence is refused.
- **Supplementary ledger** (`<run>.supplementary.jsonl`): its own hash chain,
  bound to the core ledger's head hash; every artifact carries the hash of the
  core entry it explains, the model ID, and hashes of its instructions and facts.
  The core ledger stays exactly repeatable because AI output lives here instead.
- **Wording rules**: predictions are same-instant simulations, never forecasts;
  gaps are classified as `twin_fidelity_loss` without asserting twin defect vs
  physical change; no safety claims.

## Phase 3a: evidence API (Cloud Run)

The FastAPI app (`app/`) serves evidence runs for the dashboard to replay. Runs
are pinned by core-ledger head hash in `app/config/runs.json` and loaded from
the evidence bucket (`gs://dtc-evidence-ledger-46053a8a/runs/<run>/<head16>/`).
Nothing is served until it passes 9 checks: the manifest names the pinned
head, every file matches its manifest fingerprint, both ledger chains are
intact, every AI artifact is anchored to its core entry, and the readings match
the checkpoints sealed in the core ledger.

| Endpoint | Returns |
|---|---|
| `GET /api/runs` | Pinned runs |
| `GET /api/runs/{run}/meta` | Twins, channels, protocol, verification report |
| `GET /api/runs/{run}/state?tick=N` | Statuses, reasons, assurance versions, open anomalies, recalibration record as of tick N |
| `GET /api/runs/{run}/timeline|readings|ledger|explanations?upto=N` | Evidence up to tick N only |
| `POST /api/runs/{run}/verify` | Re-fetches every file from the bucket and re-checks it now (rate-limited) |

Replay happens in the viewer's browser; every endpoint is cut off at the tick
on screen, so no later evidence leaks into an earlier view.

## Phase 3b: dashboard

React (Vite) in `web/`, built into the container and served by the same
Cloud Run service. The viewer replays a run at 2 s per tick; each tick fetches
`/api/runs/{run}/view?tick=N`, so the browser never holds later evidence.

- Opens on the motor alone; "Connect compressor & system twin" reveals the
  system (`?stage=system` to start revealed, `?reveal=N` to reveal at tick N).
- Twin cards with traced reasons; a cascade reason whose constituent has been
  re-assured is shown as resolved rather than hidden.
- Physical vs predicted charts, gap charts with the 5% and 10% lines and live
  "gap now" figures, the compressor's input against its assured range, with
  not-evaluated ticks shaded.
- Recalibration panel (time split, seals, held-out results, v1 to v2, system
  reassessment), AI explanations, anomalies (demo acknowledgements stay in the
  browser), ledger, and live re-verification.
- `?tick=N` opens at a tick; `?tick_ms=200` speeds playback for previews.

```bash
cd web && npm install && npm run build   # then the FastAPI app serves web/dist
```

Local development reads `data/` instead (`EVIDENCE_SOURCE=local`, the default):

```bash
.venv/bin/uvicorn app.main:app --reload
```

Deploy (builds run as `dtc-builder`, holding only `roles/cloudbuild.builds.builder`;
the service runs as `dtc-runtime`, which holds no project roles and only
`roles/storage.objectViewer` on the evidence bucket):

```bash
gcloud run deploy digital-twin-certification --source . --region us-central1 \
  --allow-unauthenticated \
  --service-account=dtc-runtime@project-46053a8a-6324-40f0-ba8.iam.gserviceaccount.com \
  --build-service-account=projects/project-46053a8a-6324-40f0-ba8/serviceAccounts/dtc-builder@project-46053a8a-6324-40f0-ba8.iam.gserviceaccount.com \
  --set-env-vars=EVIDENCE_BUCKET=dtc-evidence-ledger-46053a8a
```

Development dependencies (Gemini, test client): `requirements-dev.txt`.
