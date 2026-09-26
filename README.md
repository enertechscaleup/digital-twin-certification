# Digital Twin Certification

A domain-agnostic test-bed and governance layer that independently records,
measures, and certifies the gap between a digital twin's simulated behaviour
and real-world behaviour. Prototype for the Google Cloud AI Builder Cup 2026.

## Phase 1: telemetry generator

Synthetic data for two product twins: a **motor** (volt/current in,
speed/vibration out) and the **compressor** it drives (speed/flow in,
pressure/temperature out). The motor's real shaft speed feeds the compressor's
speed input. Each reading carries the *physical reference* and the *twin
prediction* side by side. The generator never computes certification status;
the verification engine (Phase 2) does that.

The formulas are illustrative and make no engineering claim.

Requires Python 3.11+. No third-party packages.

```bash
# Test-bench sweep across each twin's certified input range
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
| `telemetry/config/*.json` | Channels, units, certified envelopes, tolerances, operating profile per twin |
| `telemetry/models.py` | Twin model (prediction) and physical model (the "real" machine) |
| `telemetry/faults.py` | Fault injectors: wear drift, envelope violation, data-quality (spike / dropout / stuck); scenario loader |
| `telemetry/generator.py` | Bench sweep and field stream |
| `telemetry/sinks.py` | Output destinations (file, in-memory). New destinations plug in here |
| `scenarios/*.json` | Demo runs: `healthy`, `demo_wear_to_nullified`, `faults_showcase` |

### Key behaviours

- **Reproducible**: same seed + scenario + start time gives identical data.
- **Fast-forward wear**: `operational_hours_per_tick` compresses asset ageing
  (for example 1 tick = 24 operational hours). The stream cadence stays at 2 s.
- **Held-out tagging**: every field tick is tagged `recalibration` or
  `held_out` at generation time (default 30% held out).
- **Ground-truth labels**: `injected_faults` records what was injected, for
  testing the engine only. The engine must never read it.

## Cloud Run skeleton

A minimal FastAPI app (`app/main.py`) serving a live view of the generator:
`/` (page, refreshes every 2 s), `/api/latest` (JSON), `/health`. It is
stateless: each request works out the current tick from the clock and replays
the deterministic scenario, so every instance serves identical data. The
scenario is chosen with the `SCENARIO` env var (default `healthy`).

Deploy (builds run as a dedicated build-only service account, `dtc-builder`,
holding only `roles/cloudbuild.builds.builder`; the runtime service account
holds no project roles):

```bash
gcloud run deploy digital-twin-certification --source . --region us-central1 \
  --allow-unauthenticated \
  --build-service-account=projects/project-46053a8a-6324-40f0-ba8/serviceAccounts/dtc-builder@project-46053a8a-6324-40f0-ba8.iam.gserviceaccount.com
```
