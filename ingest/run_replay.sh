#!/usr/bin/env bash
# One replay of a sealed synthetic run through the ingestion slice, end to end:
#   launch the Dataflow job -> publish -> wait for the outputs -> capture console evidence ->
#   drain the job -> stop-all check -> seal -> engine replay (comparison copy + ingestion-labelled).
#
#   ingest/run_replay.sh <pinned run> <replay id> [publisher options...]
#   e.g. ingest/run_replay.sh assurance-amr_faults_showcase-seed42 r1015a --shuffle-ticks 3 --duplicate-fraction 0.05
#
# Outputs (git-ignored): deck-assets/ingest-runs/<replay id>/. Env: MACHINE (default n1-standard-1),
# SKIP_ENGINE=1 (stop after sealing), AFTER_DRAIN_FILE (publish this kept-back reading after the drain).
set -euo pipefail
# Never leave a job running: on any error or interruption, stop every dtc-ingest-* job and check.
trap 'echo "$(date -u +%FT%TZ) error or interruption: stopping every dtc-ingest-* job"; ingest/infra/stop_all.sh' ERR INT TERM
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
. ingest/infra/names.sh
RUN="$1"; RID="$2"; shift 2
MACHINE="${MACHINE:-n1-standard-1}"
JOB="dtc-ingest-replay-$RID"
OUT="deck-assets/ingest-runs/$RID"
mkdir -p "$OUT"
case "$RUN" in assurance-amr_*) PROJ=projects/fulfilment_cell.json; SEALED=data/fulfilment;;
               *) PROJ=projects/compressor_train.json; SEALED=data/lineage;; esac
READINGS="$SEALED/$RUN.readings.jsonl"
CHANNELS="$(.venv/bin/python -c "
import json; from engine.registry import load_registry; from projects import load_project
r = load_registry(load_project('$PROJ'))
print(json.dumps([[p.operational_twin_id, c.channel_id, c.direction, c.unit] for p in r.products.values() for c in p.channels]))")"
PER_TICK="$(echo "$CHANNELS" | .venv/bin/python -c 'import json,sys; print(len(json.load(sys.stdin)))')"
TICKS="$(.venv/bin/python -c "import json; print(len({json.loads(l)['tick'] for l in open('$READINGS')}))")"
ts() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }
echo "$(ts) replay $RID of $RUN: $TICKS ticks x $PER_TICK readings; job $JOB on $MACHINE"

echo "$(ts) launching the Dataflow job"
.venv-ingest/bin/python ingest/pipeline.py --runner DataflowRunner --project "$PROJECT" --region "$REGION" \
  --job_name "$JOB" --temp_location "gs://$BUCKET/dataflow/temp" --staging_location "gs://$BUCKET/dataflow/staging" \
  --service_account_email "$SA_DF" --no_use_public_ips --subnetwork "regions/$REGION/subnetworks/$SUBNET" \
  --num_workers 1 --max_num_workers 1 --autoscaling_algorithm NONE --worker_machine_type "$MACHINE" \
  --enable_streaming_engine \
  --subscription "projects/$PROJECT/subscriptions/$SUB" --dlq_topic "projects/$PROJECT/topics/$DLQ" \
  --out_prefix "gs://$BUCKET/" --bq_table "$PROJECT:$DATASET.$TABLE" --channels_json "$CHANNELS" \
  > "$OUT/$RID.launch.log" 2>&1
tail -2 "$OUT/$RID.launch.log"
JOB_ID="$(gcloud dataflow jobs list --project "$PROJECT" --region "$REGION" --status active --filter "name=$JOB" --format 'value(id)' | head -1)"
[ -n "$JOB_ID" ] || { echo "job not found"; exit 1; }
echo "$(ts) job $JOB_ID submitted"
for i in $(seq 1 60); do
  STATE="$(gcloud dataflow jobs describe "$JOB_ID" --project "$PROJECT" --region "$REGION" --format 'value(currentState)')"
  [ "$STATE" = JOB_STATE_RUNNING ] && break
  case "$STATE" in JOB_STATE_FAILED|JOB_STATE_CANCELLED) echo "job $STATE"; exit 1;; esac
  sleep 10
done
echo "$(ts) job state $STATE"

echo "$(ts) publishing"
.venv-ingest/bin/python ingest/publisher.py --readings "$READINGS" --topic "projects/$PROJECT/topics/$TOPIC" \
  --replay-id "$RID" --impersonate "$SA_PUB" --log "$OUT/$RID.publish-log.json" "$@" | tail -20
PUBLISHED="$(.venv/bin/python -c "import json; print(json.load(open('$OUT/$RID.publish-log.json'))['total'])")"

echo "$(ts) waiting for the outputs"
.venv-ingest/bin/python ingest/wait_outputs.py --bucket "$BUCKET" --replay-id "$RID" --published "$PUBLISHED" --ticks "$TICKS" | tail -4

echo "$(ts) capturing console evidence before stopping the job"
gcloud dataflow jobs describe "$JOB_ID" --project "$PROJECT" --region "$REGION" --full --format json > "$OUT/$RID.job.json"
gcloud beta dataflow metrics list "$JOB_ID" --project "$PROJECT" --region "$REGION" --source service --format json > "$OUT/$RID.job-metrics.json" 2>/dev/null || true
gcloud pubsub topics describe "$TOPIC" --project "$PROJECT" --format json > "$OUT/$RID.topic.json"
bq --project_id "$PROJECT" show --format prettyjson "$DATASET.$TABLE" > "$OUT/$RID.bq-table.json"

echo "$(ts) draining the job"
gcloud dataflow jobs drain "$JOB_ID" --project "$PROJECT" --region "$REGION" >/dev/null
for i in $(seq 1 90); do
  STATE="$(gcloud dataflow jobs describe "$JOB_ID" --project "$PROJECT" --region "$REGION" --format 'value(currentState)')"
  [ "$STATE" = JOB_STATE_DRAINED ] && break
  sleep 10
done
echo "$(ts) job state $STATE"
[ "$STATE" = JOB_STATE_DRAINED ] || { echo "drain did not finish; cancelling"; gcloud dataflow jobs cancel "$JOB_ID" --project "$PROJECT" --region "$REGION"; }
ingest/infra/stop_all.sh
gcloud beta dataflow metrics list "$JOB_ID" --project "$PROJECT" --region "$REGION" --source service --format json > "$OUT/$RID.job-metrics-final.json" 2>/dev/null || true

if [ -n "${AFTER_DRAIN_FILE:-}" ]; then
  echo "$(ts) publishing the kept-back reading after the drain (no job is reading any more)"
  .venv-ingest/bin/python ingest/publisher.py --readings "$READINGS" --publish-file "$AFTER_DRAIN_FILE" --no-end-marker \
    --topic "projects/$PROJECT/topics/$TOPIC" --replay-id "$RID" --impersonate "$SA_PUB" --log "$OUT/$RID.after-drain-log.json" | tail -3
fi

echo "$(ts) sealing"
set +e
.venv-ingest/bin/python ingest/seal.py --bucket "$BUCKET" --replay-id "$RID" --expected-per-tick "$PER_TICK" \
  --dlq-subscription "projects/$PROJECT/subscriptions/$DLQ_SUB" --bq-table "$PROJECT.$DATASET.$TABLE" \
  --publish-log "$OUT/$RID.publish-log.json" --out "$OUT" \
  --job "{\"job_name\": \"$JOB\", \"job_id\": \"$JOB_ID\", \"region\": \"$REGION\", \"worker\": \"$MACHINE\", \"beam\": \"python 2.76.0\"}"
SEAL=$?
set -e
[ "${SKIP_ENGINE:-}" = 1 ] && exit $SEAL

for MODE in comparison-copy ingestion-labelled; do
  echo "$(ts) engine replay: $MODE"
  set +e
  .venv/bin/python -m engine replay --project "$PROJ" --run "$RUN" --readings "$OUT/$RID.validated.readings.jsonl" \
    --mode "$MODE" --out "$OUT" --receipt "$OUT/$RID.receipt.json" > "$OUT/$RID.$MODE.stdout.txt" 2>&1
  RC=$?
  set -e
  tail -25 "$OUT/$RID.$MODE.stdout.txt"
  [ $RC = 0 ] || { echo "engine replay ($MODE) refused or failed, exit $RC"; exit 3; }
  for f in "$OUT/$RUN.$MODE".*; do gcloud storage cp "$f" "gs://$BUCKET/receipts/$RID/" --project "$PROJECT" >/dev/null; done
done
echo "$(ts) replay $RID finished"
