# TwinEvidence

Independent evidence infrastructure for digital twins. TwinEvidence records,
measures, and assures the gap between a digital twin's simulated behaviour and
real-world behaviour: demonstrated predictive fidelity within validated
operating conditions, backed by a hash-chained evidence ledger. It does not
certify that the physical system is safe to operate. Prototype for the Google
Cloud AI Builder Cup 2026.

**Live app:** https://digital-twin-certification-79846353908.us-central1.run.app

The repository and Cloud Run service keep the name `digital-twin-certification`
by design: the build, deployment configuration, service accounts and public URL
were established under it, and keeping one stable technical name avoids churn
across infrastructure while the product name lives in the interface.

## All data is simulated

Every reading, twin, vendor and fault in this repository is synthetic. No real
equipment, sensor, vendor or customer is connected or named:

- **Telemetry:** generated with a fixed seed by `telemetry/generator.py`.
- **Twins:** illustrative formulas in `telemetry/models.py`.
- **Vendors:** named `synthetic-vendor-a` to `-e`, with simulated endpoints in
  `vendor/endpoint.py`.
- **Faults:** wear, out-of-range inputs and sensor faults, introduced
  deliberately by scenario files to test how the engine classifies them.

What is real:
- the hash-chained evidence and its verification;
- the deterministic engine's decisions on that data;
- the Gemini responses, which are grounded in that data.

## Two projects, one engine

| | Compressor train | Fulfilment cell |
|---|---|---|
| Domain | Oil & gas | Warehousing & robotics |
| Twins | Motor → compressor, composed into a system twin | Fleet dispatcher → two autonomous mobile robots (AMR 1, AMR 2) → pick station, composed into a system twin |
| Channels | 8 | 17 |
| Joint composition test | 5 levels × 3 external inputs = 125 points | 3 levels × 5 external inputs = 243 points |
| Project file | `projects/compressor_train.json` | `projects/fulfilment_cell.json` |
| Evidence write-up | `docs/twin-lineage.md` | `docs/fulfilment-cell.md` |

Each project has three pinned runs:
- a full assurance cycle;
- wear to nullified;
- a fault types showcase.

All six are served by the same app, through the same 11 integrity checks.

The full cycle in each project runs through these steps:
1. A machine wears, and its twin goes from Assured to Flagged to Nullified. The
   system twin is flagged by cascade.
2. A sensor fault is classified as data quality, not as twin error.
3. The twin's owner recalibrates it on released data. The new version is
   validated on held-out data it never saw, and re-assured.
4. The twins are run jointly again. The joint test fails on a named interface,
   so the system is not re-assured.
5. A human approves one setpoint adjustment that the twin recommends. It is
   executed and checked.

## What decides, and what explains

**The deterministic engine decides.** `engine/` has no AI dependency: it never
imports the explanation code or any Gemini SDK. Every Assured / Flagged /
Nullified decision is made by fixed rules, sealed into each run:
- **Flagged:** 3 consecutive readings beyond tolerance.
- **Nullified:** 10 consecutive readings beyond twice the tolerance.
- **Envelope violations:** never nullify.

Each decision is written to a hash-chained core ledger.

**Gemini explains and assists; it never sets a status.** It is used in two
ways:

- **Sealed explanations** (`explain/`), written after a run is complete. Each
  one explains a status change, an impact, a sensor fault, a recalibration, a
  composition test or the adjustment. They go into a separate supplementary
  ledger, chained and bound to the core ledger's head. The engine never reads
  them.
  - For the Fulfilment cell, every answer is first checked against the facts it
    was given: schema, cited ledger entries, figures, status claims and
    wording. The check rejects it otherwise.
  - All 27 cell explanations passed on the first attempt.
- **The live evidence assistant**, in the app. It answers questions using 12
  read-only lookups (function calling), cut off at the tick on screen. It cites
  ledger entries and refuses requests to change a status. Its answers are not
  recorded as evidence.

The app reads statuses only from the core ledger.

## Google Cloud services used

| Service | Use |
|---|---|
| Cloud Run | Hosts the app (`digital-twin-certification`, us-central1) |
| Cloud Build, Artifact Registry | Build and store the container on source deploy |
| Cloud Storage | The evidence bucket `gs://dtc-evidence-ledger-46053a8a` (retention policy locked, 1 day); the app re-verifies every run from it before serving it |
| Vertex AI, Gemini (`gemini-3.8-flash`, global endpoint) | Sealed explanations and the live assistant |
| IAM | `dtc-runtime` runs the service (`roles/aiplatform.user`; `roles/storage.objectViewer` on the bucket only); `dtc-builder` builds (`roles/cloudbuild.builds.builder`). Application Default Credentials only, no keys |
| Cloud Logging, Cloud Monitoring | Cloud Run's automatic logs and metrics |

The demo video (in `video/`, not part of the app) also used Vertex AI Lyria and
Cloud Text-to-Speech.

## Run it from a clean clone

Python 3.12 and Node 24.

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python --only-binary cryptography -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests
```

**Run the engine** (no cloud access needed):

```bash
.venv/bin/python -m engine run --scenario scenarios/demo_full_cycle.json
.venv/bin/python -m engine run --project projects/fulfilment_cell.json --scenario scenarios/amr_full_cycle.json
.venv/bin/python -m engine verify-ledger data/assurance-demo_full_cycle-seed42.ledger.jsonl
```

Output goes to `data/`, which is git-ignored.

**Why your heads differ from the pins.** The run's head hash will differ from
the pinned one, because the engine seals the checked-out code commit into the
ledger. A clone's own commit is sealed, so the head differs; the decisions and
readings do not.

To reproduce a pinned head exactly, run from a clean working tree at the commit
sealed in that run's manifest:
- `59bc6dd` for the compressor runs;
- `4025058` for the Fulfilment-cell runs.

**Serve the app locally.** The pinned runs live in the evidence bucket, so a
clone has no evidence to serve. Build a local pack instead. It contains the
compressor full cycle with clearly labelled placeholder AI text, and needs no
Gemini call:

```bash
.venv/bin/python -m tools.lineage_dev_pack          # writes data/lineage-dev/
(cd web && npm ci && npm run build)                 # the app serves web/dist
EVIDENCE_DIR=data/lineage-dev RUNS_CONFIG=data/lineage-dev/runs.json .venv/bin/uvicorn app.main:app
```

With read access to the evidence bucket, set `EVIDENCE_SOURCE=gcs`,
`EVIDENCE_BUCKET=dtc-evidence-ledger-46053a8a` and
`GOOGLE_CLOUD_PROJECT=project-46053a8a-6324-40f0-ba8` instead, and leave
`RUNS_CONFIG` unset. The app then serves and
verifies all six pinned runs.

**Gemini explanations** need `gcloud auth application-default login` and Vertex
AI access:

```bash
.venv/bin/python -m explain run data/assurance-amr_full_cycle-seed42 --project-file projects/fulfilment_cell.json --profile 2
.venv/bin/python -m explain verify data/assurance-amr_full_cycle-seed42
```

The compressor train uses the original profile (`--profile 1`, the default).

## How it works

### Telemetry (`telemetry/`)

Each reading carries the *physical reference* and the *twin prediction* side by
side.

- **Reproducible:** the same seed, scenario and start time give identical data.
- **Fast-forward wear:** asset ageing is compressed (1 tick = 24 operational
  hours) while the stream keeps a 2 s cadence.
- **Labels the engine never sees:** the injected-fault labels are for testing
  only. `engine/readings.py` drops them before the engine sees a reading.

### Engine (`engine/`)

What a run does, all recorded in one hash-chained ledger
(`data/<run>.ledger.jsonl`), plus a per-tick status timeline:

1. **Verification** of each design twin: deterministic, complete, finite, and
   within its declared output ranges across the assured input sweep.
2. **Bench validation** against synthetic test-bench data.
3. **Assurance issued** to each twin. The system twin is composed only from
   assured twins, after a **joint composition test**: the twins are run together
   through their owners' endpoints, with an interface check and an interaction
   check.
4. **Field monitoring.** Each reading is classified in a fixed order:
   1. data quality (dropout / stuck / spike);
   2. envelope violation;
   3. gap exceedance.

   Outputs are not evaluated while an input is bad or out of range.
5. **Escalation and cascade.** Statuses are sticky.
   - A nullified constituent flags the system twin.
   - The system twin takes its output constituent's status.
   - Every reason names its constituent and cause.
6. **Recalibration (Real2Sim).** The flagged period is split by time and both
   parts are sealed. Only the earlier part goes to the twin's owner. The new
   version must pass on the held-out part before it is re-assured, and the twins
   are then tested jointly again.
7. **Semi-autonomous adjustment.** A twin may recommend one setpoint change. A
   human approves it before execution, and the outcome is checked against the
   twin's prediction (Sim2Real).
8. **Readings checkpoints.** Every 10 ticks, the raw readings' SHA-256 is sealed
   into the chain.

**Twin identity and lineage** (`docs/twin-lineage.md`):
- Every twin has a permanent random identity (`registry/identities.json`).
- Each version is fingerprinted by the platform, which probes it with sealed
  inputs.
- Every ledger entry cites the exact version it concerns.

The ledger proves the record was not altered afterwards, not that the sensor
data was truthful.

| Path | What it is |
|---|---|
| `projects/`, `engine/registry.py` | Project files (twins, channels, composition) and the loader |
| `engine/ledger.py` | Hash-chained ledger and chain verification |
| `engine/protocol.py` | Escalation and data-quality rules |
| `engine/monitor.py` | Field classification, escalation, cascade, anomalies |
| `engine/boundary.py`, `vendor/` | The vendor boundary, and the simulated vendor endpoints, owners' recalibration and advice |
| `engine/lineage.py` | Identities, measured version fingerprints, lineage checks |
| `engine/composition.py` | Joint composition test |
| `engine/run.py` | End-to-end orchestration |
| `scenarios/*.json` | The runs: `demo_full_cycle`, `demo_wear_to_nullified`, `faults_showcase`, `amr_full_cycle`, `amr_wear_to_nullified`, `amr_faults_showcase`, plus `healthy` |

### Evidence API (`app/`, FastAPI on Cloud Run)

Runs are pinned by core-ledger head hash in `app/config/runs.json` and loaded
from `gs://dtc-evidence-ledger-46053a8a/runs/<run>/<first 16 of head>/`.

When an instance starts, it loads and verifies every pinned run in the background, so the first
viewer does not wait for it. A failure there is logged and never stops the app from starting or
serving; that run is fetched and verified again when it is requested.

Nothing is served until it passes **11 checks**:
- the manifest names the pinned head;
- each of the five files (ledger, AI ledger, readings, timeline, exchange)
  matches its fingerprint;
- the core chain is intact and ends at the pinned head;
- the AI ledger is intact and anchored to the core ledger;
- the readings match the sealed checkpoints;
- twin lineage holds.

| Endpoint | Returns |
|---|---|
| `GET /api/projects`, `/api/projects/{id}`, `/api/projects/{id}/runs` | Projects and their pinned runs |
| `GET /api/registry` | The twin catalogue |
| `GET /api/runs/{run}/meta` | Twins, channels, protocol, run label, verification report |
| `GET /api/runs/{run}/view?tick=N` | Everything the screen shows at tick N |
| `GET /api/runs/{run}/state`, `timeline`, `readings`, `ledger`, `explanations` | Evidence up to tick N only |
| `POST /api/runs/{run}/verify` | Re-fetches every file and re-checks it now (rate-limited) |
| `POST /api/runs/{run}/ask` | The evidence assistant |

Every endpoint is cut off at the tick on screen, so no later evidence leaks into
an earlier view.

**Assistant guards:**
- questions up to 800 characters;
- 6 per minute and 60 per day per visitor;
- 300 per hour per instance;
- at most 8 tool rounds per question;
- each model call waits at most 25 s per attempt. A timeout or a Gemini server error (HTTP 5xx) is
  retried up to twice, after 1 s and then 2 s; client errors (4xx) are never retried;
- no new model call starts once a question has used 200 s, and a call's timeout shrinks so it
  cannot run past that;
- when a limit is reached, the assistant replies with a plain message that says which: too many
  lookups, too long overall, Gemini did not answer in time, or Gemini returned a temporary error.
- capped answer length.

These limits apply to the live assistant only. The sealed-explanation pipeline uses its own client
with no timeout or retry, because its calls can legitimately take longer (up to 49 s measured).

### Dashboard (`web/`, React + Vite)

Built into the container and served by the same Cloud Run service.

- **Pages:**
  - **Projects:** both projects, with their final statuses.
  - **Each project's evidence view:** replay of a run with twin cards and
    traced reasons, physical vs predicted charts, gap charts, anomalies,
    recalibration and lineage, composition tests, the adjustment, sealed AI
    explanations with their cited ledger entries, the ledger itself, and live
    re-verification.
  - **Composition patterns.**
  - **New project.**
- **How each project opens:**
  - The compressor train opens on the motor alone; "Connect" reveals the system.
  - The Fulfilment cell opens in the whole-system view. It adds a status
    timeline, a cascade view and a split of sensor faults from twin error.
- **Demo-only and local-only pieces, labelled as such:**
  - Projects created under "New project" are saved only in the viewer's
    browser. They are shown as previews from mock data, with no evidence.
  - "Acknowledge (demo)" on anomalies is not written to evidence.

## Deploy

See `docs/deploy-plan.md` for the current plan, including tagged no-traffic
revisions and rollback.

The service is deployed from source:
- builds run as `dtc-builder`;
- the service runs as `dtc-runtime`;
- at most 3 instances.

```bash
gcloud run deploy digital-twin-certification --source . --region us-central1 \
  --allow-unauthenticated \
  --service-account=dtc-runtime@project-46053a8a-6324-40f0-ba8.iam.gserviceaccount.com \
  --build-service-account=projects/project-46053a8a-6324-40f0-ba8/serviceAccounts/dtc-builder@project-46053a8a-6324-40f0-ba8.iam.gserviceaccount.com \
  --set-env-vars=EVIDENCE_BUCKET=dtc-evidence-ledger-46053a8a,GOOGLE_CLOUD_PROJECT=project-46053a8a-6324-40f0-ba8 \
  --max-instances=3
```

The image contains no evidence: it reads the evidence bucket and verifies each
run on load.
