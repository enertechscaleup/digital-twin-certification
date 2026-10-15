#!/usr/bin/env bash
# One two-source replay of a sealed synthetic run, end to end:
#   launch the two-source Dataflow job -> publish both feeds (shared tick index) -> wait -> capture
#   console evidence -> drain -> stop-all check -> seal -> engine replay (comparison copy + ingestion-labelled).
#
#   ingest/run_replay_two_source.sh <pinned run> <replay id> [publisher_two_source options...]
#
# Outputs (git-ignored): deck-assets/ingest-runs/<replay id>/. Env: MACHINE (default n1-standard-1).
set -euo pipefail
trap 'echo "$(date -u +%FT%TZ) error or interruption: stopping every dtc-ingest-* job"; ingest/infra/stop_all.sh' ERR INT TERM
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
. ingest/infra/names_two_source.sh
RUN="$1"; RID="$2"; shift 2
MACHINE="${MACHINE:-n1-standard-1}"
JOB="dtc-ingest-two-$RID"
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
echo "$(ts) two-source replay $RID of $RUN: $TICKS ticks x $PER_TICK readings; job $JOB on $MACHINE"

(cd ingest && ../.venv-ingest/bin/python pipeline_two_source.py --runner DataflowRunner --project "$PROJECT" --region "$REGION" \
  --job_name "$JOB" --temp_location "gs://$BUCKET/dataflow2/temp" --staging_location "gs://$BUCKET/dataflow2/staging" \
  --service_account_email "$SA_DF" --no_use_public_ips --subnetwork "regions/$REGION/subnetworks/$SUBNET" \
  --num_workers 1 --max_num_workers 1 --autoscaling_algorithm NONE --worker_machine_type "$MACHINE" --enable_streaming_engine \
  --plant_subscription "projects/$PROJECT/subscriptions/$PLANT_SUB" --twin_subscription "projects/$PROJECT/subscriptions/$TWIN_SUB" \
  --plant_dlq "projects/$PROJECT/topics/$PLANT_DLQ" --twin_dlq "projects/$PROJECT/topics/$TWIN_DLQ" \
  --out_prefix "gs://$BUCKET/" --bq_dataset "$PROJECT:$DATASET" --channels_json "$CHANNELS") > "$OUT/$RID.launch.log" 2>&1
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

echo "$(ts) publishing both feeds"
.venv-ingest/bin/python ingest/publisher_two_source.py --readings "$READINGS" --plant-topic "projects/$PROJECT/topics/$PLANT_TOPIC" \
  --twin-topic "projects/$PROJECT/topics/$TWIN_TOPIC" --replay-id "$RID" --impersonate-plant "$SA_PLANT" --impersonate-twin "$SA_TWIN" \
  --log "$OUT/$RID.publish-log.json" "$@" | tail -30
read -r PUB_PLANT PUB_TWIN <<< "$(.venv/bin/python -c "import json; t=json.load(open('$OUT/$RID.publish-log.json'))['total']; print(t['plant'], t['twin'])")"

echo "$(ts) waiting for the outputs"
.venv-ingest/bin/python ingest/wait_two_source.py --bucket "$BUCKET" --replay-id "$RID" --published-plant "$PUB_PLANT" \
  --published-twin "$PUB_TWIN" --ticks "$TICKS" | tail -3

echo "$(ts) capturing console evidence before stopping the job"
gcloud dataflow jobs describe "$JOB_ID" --project "$PROJECT" --region "$REGION" --full --format json > "$OUT/$RID.job.json"
for t in "$PLANT_TOPIC" "$TWIN_TOPIC"; do gcloud pubsub topics describe "$t" --project "$PROJECT" --format json > "$OUT/$RID.$t.json"; done
for table in $TWO_SOURCE_TABLES; do bq --project_id "$PROJECT" show --format prettyjson "$DATASET.$table" > "$OUT/$RID.$table.json"; done

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

echo "$(ts) sealing"
set +e
.venv-ingest/bin/python ingest/seal_two_source.py --bucket "$BUCKET" --replay-id "$RID" --expected-per-tick "$PER_TICK" --ticks "$TICKS" \
  --plant-dlq-subscription "projects/$PROJECT/subscriptions/$PLANT_DLQ_SUB" --twin-dlq-subscription "projects/$PROJECT/subscriptions/$TWIN_DLQ_SUB" \
  --bq-dataset "$PROJECT.$DATASET" --publish-log "$OUT/$RID.publish-log.json" --out "$OUT" \
  --job "{\"job_name\": \"$JOB\", \"job_id\": \"$JOB_ID\", \"region\": \"$REGION\", \"worker\": \"$MACHINE\", \"beam\": \"python 2.76.0\"}"
SEAL=$?
set -e

for MODE in comparison-copy ingestion-labelled; do
  echo "$(ts) engine replay: $MODE"
  set +e
  .venv/bin/python -m engine replay --project "$PROJ" --run "$RUN" --readings "$OUT/$RID.joined.readings.jsonl" \
    --mode "$MODE" --out "$OUT" --receipt "$OUT/$RID.receipt.json" > "$OUT/$RID.$MODE.stdout.txt" 2>&1
  RC=$?
  set -e
  tail -25 "$OUT/$RID.$MODE.stdout.txt"
  [ $RC = 0 ] || { echo "engine replay ($MODE) refused or failed, exit $RC (seal exit $SEAL)"; exit 3; }
  for f in "$OUT/$RUN.$MODE".*; do gcloud storage cp "$f" "gs://$BUCKET/receipts2/$RID/" --project "$PROJECT" >/dev/null; done
done
echo "$(ts) two-source replay $RID finished"
