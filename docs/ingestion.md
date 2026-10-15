# Ingestion slice: Pub/Sub and Dataflow, on replayed synthetic data

**What this is.** A thin slice of the telemetry ingestion path, demonstrated on **replayed synthetic data**: the readings of a sealed run are published into Pub/Sub, validated and ordered by a Dataflow pipeline, and the assurance engine runs on the pipeline's output. **It is not live telemetry and it has not been tested at scale.** No real asset, sensor, historian or vendor is connected.

## Status

| Part | Status |
|---|---|
| Engine replay mode: field readings from outside the generator, failing closed on any missing, duplicated or out-of-order reading (`engine/replay.py`, `python -m engine replay`) | **Built and run on replayed synthetic data** |
| Publisher that replays a sealed run into Pub/Sub, accelerated (`ingest/publisher.py`) | **Built and run on replayed synthetic data** |
| Dataflow pipeline, Apache Beam (Python), streaming: raw copy to Cloud Storage, shape validation, per-tick de-duplication and canonical order, validated files to Cloud Storage, rows to BigQuery, invalid messages to a dead-letter topic (`ingest/pipeline.py`) | **Built and run on replayed synthetic data** |
| Seal step: hashes raw and validated objects, counts dead letters and BigQuery rows, writes a receipt (`ingest/seal.py`) | **Built and run on replayed synthetic data** |
| Infrastructure scripts: create, stop every job, tear down (`ingest/infra/`) | **Built and run** (teardown: built, run on request) |
| "Connect telemetry" step in the app: source choice, a message contract built from the project's channels, and a sample-message check in the browser with the pipeline's own rules (`web/src/platform/ConnectTelemetry.jsx`, rules exported by `ingest/export_rules.py`) | **Built**; enabling a live connection is **not built** (the button is disabled) |
| Twin stream and plant stream shown per channel in the contract, with the comparison rule exported from the engine (`ingest/export_rules.py`) and the time-alignment rules the engine applies today | **Built** (presentation of today's single message format) |
| Per-value provenance; separate twin and plant messages joined per tick; clock synchronisation, resampling, lag compensation and an alignment window per channel | **Designed, not built** (below) |
| Pulling from an asset historian or an OPC UA / MQTT gateway | **Designed, not built** (below) |
| Predictions from a vendor twin API | **Designed, not built** (below) |
| A production ledger writer that follows a live stream | **Designed, not built** (below) |
| Continuous monitoring in the cloud, authentication of real sources, scale | **Not built** |

Design time (verification, bench validation), the joint composition tests and the owners' recalibration and advice remain **simulated**, exactly as in every other run of the prototype. Only the field readings come through the ingestion path.

## How it works

```text
publisher (replays a sealed run's readings, accelerated)
  -> Pub/Sub topic dtc-ingest-readings
  -> Dataflow job (streaming, 1 worker, no public IP)
       raw copy, every message as received          -> Cloud Storage  raw/<replay>/
       shape checks (never values)                  -> invalid: Pub/Sub dead-letter topic
       per tick: de-duplicate, canonical order      -> Cloud Storage  validated/<replay>/<run>/tick-NNNN.pK.jsonl
                                                    -> BigQuery       dtc_ingest.readings_validated
  -> job drained (stopped) when the replay is complete
  -> seal step: receipt with SHA-256 of raw and validated objects and every count
  -> python -m engine replay (locally), in two labelled modes
```

**Message.** The data is one reading in the engine's ingested shape (`engine/readings.py: ALLOWED_FIELDS`, 13 fields), byte-identical to the sealed readings line. Attributes: `schema` (`dtc-reading/1`), `source` (`replay`), `replay_id`, `event_ts`, `reading_key` (SHA-256 of replay, run, tick, twin and channel: the idempotency key) and `content_sha256`. No ordering key: Pub/Sub ordering does not carry through a Dataflow pipeline, so the order is restored explicitly per tick, from the project's twin and channel order.

**What the pipeline checks, and what it never does.** It checks shape: valid JSON (no `NaN` / `Infinity` tokens), exactly the 13 fields (the generator's ground-truth `injected_faults` is refused), types, `kind = field`, a known (twin, channel) with the right direction and unit, a correct `reading_key` and `content_sha256`. It **never** cleans, clips or judges a value: dropouts (`null`), spikes, stuck values and out-of-range inputs pass through untouched, because classifying them is the engine's job.

**Ticks, not event-time windows.** Readings are grouped by (replay, run, tick) in the global window and fired every 5 seconds of processing time. Event-time windows on the simulated timestamps were not used: those timestamps lie in the past, and a watermark could treat a whole replay as late.

**Duplicates and late data.** Identical copies of a reading are dropped. Two copies with the same key but different content are never resolved: both go to the dead-letter topic, the tick is then incomplete and the engine refuses to run. A reading that arrives late re-fires its tick with a higher pane number, and the seal step uses the highest pane. A reading that arrives after the job has been drained is not there, and the engine refuses the incomplete tick.

**Two labelled engine runs** (neither is ever pinned or uploaded to the evidence bucket):

- **Comparison copy:** records the code commit sealed in the original run, so the ledger can be compared hash for hash with the pin. It exists only to prove "same readings in, same ledger out".
- **Ingestion-labelled run:** records the commit actually running and a `field_readings_source` entry (just before `run_completed`) with the receipt's hashes. Its decisions match the pinned run; its head hash differs by design.

## Resources (us-central1)

Pub/Sub topics `dtc-ingest-readings` and `dtc-ingest-readings-dlq` with subscriptions `dtc-ingest-readings-dataflow` and `dtc-ingest-readings-dlq-hold`; a new bucket `dtc-ingest-<suffix>` (raw, validated, receipts, Dataflow staging; deleted after 30 days; no retention lock); BigQuery dataset `dtc_ingest`; network `dtc-ingest-vpc` with subnet `dtc-ingest-subnet` (Private Google Access, because the organisation policy forbids public IPs on VMs) and firewall rule `dtc-ingest-allow-dataflow` (worker to worker only); service accounts `dtc-ingest-publisher` (publish to one topic) and `dtc-ingest-dataflow` (Dataflow worker; one subscription, the dead-letter topic, the ingest bucket and the ingest dataset). Nothing in the slice has any access to the evidence bucket, and the deployed app is not involved.

Run one replay: `ingest/run_replay.sh <pinned run> <replay id> [publisher options]`. Stop every job and check: `ingest/infra/stop_all.sh`. Remove everything: `ingest/infra/teardown.sh`. Tests: `python -m unittest tests.test_replay` (engine side) and `.venv-ingest/bin/python -m unittest discover -s ingest/tests` (pipeline, offline).

## Results of the demonstration (15 Oct 2026, replayed synthetic data)

Each replay ran its own Dataflow job (1 worker, n1-standard-1, Streaming Engine), which was drained as soon as the replay was complete. Numbers are from each replay's receipt.

| Replay | What was sent | Pipeline result | Engine result |
|---|---|---|---|
| Fulfilment cell, fault showcase (the key test) | 765 readings, shuffled within ±3 ticks, plus 44 identical duplicates and an end marker (810 messages) | 810 raw; 765 validated, 45 ticks, byte-identical to the sealed readings file; 765 BigQuery rows; 0 dead letters | **Comparison copy: head identical to the pin** (`59952ac5…`). **Ingestion-labelled run: same decisions**, head differs by design |
| Fulfilment cell, full cycle | 1,360 readings, shuffled within ±3 ticks, plus 73 identical duplicates and an end marker (1,434 messages) | 1,360 validated, 80 ticks, byte-identical; 1,360 BigQuery rows; 0 dead letters | **Comparison copy: head identical** (`466d5d1f…`). **Ingestion-labelled: same decisions** |
| Invalid messages | Fault showcase plus one malformed message per reject reason (8) and duplicates | All 8 in the dead-letter subscription, one per reason; none in the validated files or BigQuery; run complete | Head identical (comparison copy); same decisions (labelled) |
| Late reading | Fault showcase with one tick-10 reading published 4 minutes late | Tick 10: first pane 16 readings, late pane 17 | Head identical (comparison copy); same decisions (labelled) |
| Conflict and too late | One reading republished with different content (tick 20); one reading published only after the job was drained (tick 30) | Both conflicting copies dead-lettered; receipt `complete: false`, ticks 20 and 30 incomplete | **Refused** (fail closed): "tick 20: 16 readings, expected 17" |

The engine side is also covered offline: `tests/test_replay.py` replays all six sealed runs (head identical as a comparison copy, same decisions as an ingestion-labelled run) and checks every refusal.

**Cost:** the six Dataflow jobs together used about 30 vCPU-minutes, about $0.05 at list prices; Pub/Sub, BigQuery and Cloud Storage use was within free tiers or a fraction of a cent.

## Designed, not built

**Pulling from a historian or an OPC UA / MQTT gateway.** A connector per source type, run on a schedule, reading each channel's values for a time window, mapping the historian's tags to (twin, channel), stamping each value with its source timestamp and publishing it in the same message format. Ticks then need an alignment rule (the engine compares tick for tick); that rule would be declared per channel and sealed into the evidence. Not built.

**Predictions from a vendor twin API.** For each tick, the platform would ask each twin owner's endpoint for the twin's prediction at the measured inputs and place it in `predicted_value` beside the measured value, through the same boundary the engine already uses for verification and joint tests (`engine/boundary.py`). In the prototype the owners' endpoints are simulated. Not built.

**Twin side and plant side: what is true today.** One reading carries the plant's measured value (`physical_value`, every channel) and, on an output channel, the twin's prediction (`predicted_value`, with `twin_version`). Both arrive in one message, from one sender, with one timestamp. The twin is fed the same values as the plant's measured inputs; the twin's inputs are not recorded separately. The pipeline checks only that each value is a number or null; the engine compares them per tick by the sealed rule (gap %, τ, 3 and 10 consecutive readings). The plant data in the demonstration is synthetic and has never been compared with a real physical system.

**Per-value provenance.** Each value would carry who supplied it (the plant operator's system for `physical_value`, the twin owner's endpoint for `predicted_value`), authenticated per party and sealed with the readings, so that a prediction can never be supplied by the plant side or a measurement by the twin side. Today nothing in the message says which party supplied which value. Not built.

**Separate twin messages and plant messages, joined per tick in the pipeline.** Two message types on two topics, one per party: plant messages carry `physical_value` per (tick, twin, channel); twin messages carry `predicted_value` and `twin_version` for the output channels, and the inputs the twin was given. The pipeline would join them per (run, tick, twin, channel); a tick missing either side would be recorded as "not evaluated" for the affected channels and never guessed, and a twin input that differs from the plant's measured input would be visible. Not built.

**Clock synchronisation, resampling, lag compensation and an alignment window per channel.** Today alignment is a shared tick index: both values of a reading share one tick and one timestamp, and a tick is evaluated only when complete. Two independent systems would need clock synchronisation (each source's clock offset measured and recorded), resampling of readings taken at different rates onto the tick grid, lag compensation where a measurement trails its prediction, and an alignment window per channel, declared and sealed into the evidence so that alignment cannot be tuned after the fact to hide a gap. Not built.

**A ledger writer that follows a live stream.** In the slice the engine runs once, after the job is drained, as a single local process: one writer by construction. In production: one writer per ledger holding a lease; each append a compare-and-swap on the stored head (for example a Cloud Storage generation precondition); a tick processed only when complete (watermark plus the expected set of channels) or explicitly closed as incomplete, with that recorded; idempotent appends keyed by sequence number; recovery from the last checkpoint. Not built.

## What must not be claimed

Live, real-time or production telemetry; "connected"; continuous monitoring in the cloud; any scale or throughput figure; "exactly-once" end to end; integration with historians or industrial protocols; that Dataflow validates the physics; that a project made in the wizard is connected to the engine; that a comparison copy is evidence.
