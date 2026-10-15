#!/usr/bin/env bash
# Creates the ingestion slice's resources (idempotent). Needs INFRA APPROVED.
#   PROJECT=<id> ingest/infra/create.sh
# Never touches the evidence bucket, the Cloud Run services or any other network.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
if [ ! -f "$HERE/.env" ]; then
  : "${PROJECT:?set PROJECT}"
  printf 'PROJECT=%s\nREGION=us-central1\nSUFFIX=%s\n' "$PROJECT" "$(openssl rand -hex 4)" > "$HERE/.env"
fi
. "$HERE/infra/names.sh"
P=(--project "$PROJECT")
ME="$(gcloud config get-value account 2>/dev/null)"
exists() { "$@" >/dev/null 2>&1; }

echo "== APIs"
gcloud services enable dataflow.googleapis.com compute.googleapis.com "${P[@]}"

echo "== network (workers have no public IP: Private Google Access)"
exists gcloud compute networks describe "$VPC" "${P[@]}" || gcloud compute networks create "$VPC" --subnet-mode=custom "${P[@]}"
exists gcloud compute networks subnets describe "$SUBNET" --region "$REGION" "${P[@]}" || \
  gcloud compute networks subnets create "$SUBNET" --network "$VPC" --region "$REGION" --range 10.10.0.0/24 \
    --enable-private-ip-google-access "${P[@]}"
exists gcloud compute firewall-rules describe "$FIREWALL" "${P[@]}" || \
  gcloud compute firewall-rules create "$FIREWALL" --network "$VPC" --direction INGRESS --action ALLOW \
    --rules tcp:12345-12346 --source-tags dataflow --target-tags dataflow "${P[@]}"

echo "== service accounts"
for sa in dtc-ingest-publisher dtc-ingest-dataflow; do
  exists gcloud iam service-accounts describe "$sa@$PROJECT.iam.gserviceaccount.com" "${P[@]}" || \
    gcloud iam service-accounts create "$sa" --display-name "$sa (ingestion slice, synthetic replay)" "${P[@]}"
done
sleep 10

echo "== Pub/Sub"
exists gcloud pubsub topics describe "$TOPIC" "${P[@]}" || gcloud pubsub topics create "$TOPIC" "${P[@]}"
exists gcloud pubsub topics describe "$DLQ" "${P[@]}" || gcloud pubsub topics create "$DLQ" "${P[@]}"
exists gcloud pubsub subscriptions describe "$SUB" "${P[@]}" || \
  gcloud pubsub subscriptions create "$SUB" --topic "$TOPIC" --ack-deadline 60 --message-retention-duration 1d "${P[@]}"
exists gcloud pubsub subscriptions describe "$DLQ_SUB" "${P[@]}" || \
  gcloud pubsub subscriptions create "$DLQ_SUB" --topic "$DLQ" --ack-deadline 60 --message-retention-duration 7d "${P[@]}"

echo "== Cloud Storage (a new bucket; never the evidence bucket)"
exists gcloud storage buckets describe "gs://$BUCKET" "${P[@]}" || \
  gcloud storage buckets create "gs://$BUCKET" --location "$REGION" --uniform-bucket-level-access \
    --public-access-prevention "${P[@]}"
printf '{"rule":[{"action":{"type":"Delete"},"condition":{"age":30}}]}' > /tmp/dtc-ingest-lifecycle.json
gcloud storage buckets update "gs://$BUCKET" --lifecycle-file /tmp/dtc-ingest-lifecycle.json "${P[@]}" >/dev/null
rm -f /tmp/dtc-ingest-lifecycle.json

echo "== BigQuery"
exists bq --project_id "$PROJECT" show "$DATASET" || \
  bq --project_id "$PROJECT" --location "$REGION" mk --dataset --description "Ingestion slice: replayed synthetic readings" "$PROJECT:$DATASET"
exists bq --project_id "$PROJECT" show "$DATASET.$TABLE" || \
  bq --project_id "$PROJECT" mk --table --description "Validated readings from replays of sealed synthetic runs (not live telemetry)" \
    "$PROJECT:$DATASET.$TABLE" \
    run_id:STRING,kind:STRING,tick:INTEGER,timestamp:TIMESTAMP,operational_hours:FLOAT,twin_id:STRING,twin_version:STRING,channel_id:STRING,direction:STRING,unit:STRING,physical_value:FLOAT,predicted_value:FLOAT,test_point:STRING,replay_id:STRING,reading_key:STRING,ingested_at:TIMESTAMP

echo "== IAM (least privilege, on single resources)"
gcloud pubsub topics add-iam-policy-binding "$TOPIC" --member "serviceAccount:$SA_PUB" --role roles/pubsub.publisher "${P[@]}" >/dev/null
gcloud iam service-accounts add-iam-policy-binding "$SA_PUB" --member "user:$ME" --role roles/iam.serviceAccountTokenCreator "${P[@]}" >/dev/null
gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA_DF" --role roles/dataflow.worker --condition None >/dev/null
for role in roles/pubsub.subscriber roles/pubsub.viewer; do
  gcloud pubsub subscriptions add-iam-policy-binding "$SUB" --member "serviceAccount:$SA_DF" --role "$role" "${P[@]}" >/dev/null
done
gcloud pubsub topics add-iam-policy-binding "$DLQ" --member "serviceAccount:$SA_DF" --role roles/pubsub.publisher "${P[@]}" >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member "serviceAccount:$SA_DF" --role roles/storage.objectAdmin "${P[@]}" >/dev/null
bq --project_id "$PROJECT" add-iam-policy-binding --member "serviceAccount:$SA_DF" --role roles/bigquery.dataEditor "$PROJECT:$DATASET" >/dev/null
echo "done: bucket gs://$BUCKET, dataset $DATASET, topic $TOPIC"
