#!/usr/bin/env bash
# Creates ONLY the two-source path's new resources (idempotent); never modifies an existing resource.
# New grants for the existing worker account are on the new topics and subscriptions only (it already
# writes to the dataset and the bucket). Needs INFRA APPROVED.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
. "$HERE/infra/names_two_source.sh"
P=(--project "$PROJECT")
ME="$(gcloud config get-value account 2>/dev/null)"
exists() { "$@" >/dev/null 2>&1; }
cd "$HERE/.."

echo "== service accounts (publish-only, one per feed)"
for sa in dtc-ingest-plant-publisher dtc-ingest-twin-publisher; do
  exists gcloud iam service-accounts describe "$sa@$PROJECT.iam.gserviceaccount.com" "${P[@]}" || \
    gcloud iam service-accounts create "$sa" --display-name "$sa (two-source replay, synthetic)" "${P[@]}"
done
sleep 10

echo "== Pub/Sub"
for t in "$PLANT_TOPIC" "$TWIN_TOPIC" "$PLANT_DLQ" "$TWIN_DLQ"; do
  exists gcloud pubsub topics describe "$t" "${P[@]}" || gcloud pubsub topics create "$t" "${P[@]}"
done
for pair in "$PLANT_SUB:$PLANT_TOPIC:1d" "$TWIN_SUB:$TWIN_TOPIC:1d" "$PLANT_DLQ_SUB:$PLANT_DLQ:7d" "$TWIN_DLQ_SUB:$TWIN_DLQ:7d"; do
  IFS=: read -r s t r <<< "$pair"
  exists gcloud pubsub subscriptions describe "$s" "${P[@]}" || \
    gcloud pubsub subscriptions create "$s" --topic "$t" --ack-deadline 60 --message-retention-duration "$r" "${P[@]}"
done

echo "== BigQuery tables (new, in the existing dataset)"
for table in $TWO_SOURCE_TABLES; do
  schema="$(.venv/bin/python -c "import sys; sys.path[:0]=['ingest']; from pipeline_two_source import BQ_SCHEMAS; print(BQ_SCHEMAS['$table'])")"
  exists bq --project_id "$PROJECT" show "$DATASET.$table" || \
    bq --project_id "$PROJECT" mk --table --description "Two-source replay of sealed synthetic runs (not live telemetry)" "$PROJECT:$DATASET.$table" "$schema"
done

echo "== IAM (on the new resources only)"
gcloud pubsub topics add-iam-policy-binding "$PLANT_TOPIC" --member "serviceAccount:$SA_PLANT" --role roles/pubsub.publisher "${P[@]}" >/dev/null
gcloud pubsub topics add-iam-policy-binding "$TWIN_TOPIC" --member "serviceAccount:$SA_TWIN" --role roles/pubsub.publisher "${P[@]}" >/dev/null
for sa in "$SA_PLANT" "$SA_TWIN"; do
  gcloud iam service-accounts add-iam-policy-binding "$sa" --member "user:$ME" --role roles/iam.serviceAccountTokenCreator "${P[@]}" >/dev/null
done
for s in "$PLANT_SUB" "$TWIN_SUB"; do
  for role in roles/pubsub.subscriber roles/pubsub.viewer; do
    gcloud pubsub subscriptions add-iam-policy-binding "$s" --member "serviceAccount:$SA_DF" --role "$role" "${P[@]}" >/dev/null
  done
done
for t in "$PLANT_DLQ" "$TWIN_DLQ"; do
  gcloud pubsub topics add-iam-policy-binding "$t" --member "serviceAccount:$SA_DF" --role roles/pubsub.publisher "${P[@]}" >/dev/null
done
echo "done: topics $PLANT_TOPIC $TWIN_TOPIC, tables $TWO_SOURCE_TABLES"
