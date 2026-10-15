#!/usr/bin/env bash
# Removes every resource of the ingestion slice, then verifies nothing is left and that the
# evidence side is untouched. Only on request. Each step tolerates "already gone".
#   ingest/infra/teardown.sh [--disable-apis]
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/names.sh"
P=(--project "$PROJECT" --quiet)
ME="$(gcloud config get-value account 2>/dev/null)"
"$HERE/stop_all.sh" || exit 1
for s in "$SUB" "$DLQ_SUB"; do gcloud pubsub subscriptions delete "$s" "${P[@]}" 2>/dev/null; done
for t in "$TOPIC" "$DLQ"; do gcloud pubsub topics delete "$t" "${P[@]}" 2>/dev/null; done
bq --project_id "$PROJECT" rm -r -f "$PROJECT:$DATASET" 2>/dev/null
gcloud storage rm -r "gs://$BUCKET" "${P[@]}" 2>/dev/null
gcloud compute firewall-rules delete "$FIREWALL" "${P[@]}" 2>/dev/null
gcloud compute networks subnets delete "$SUBNET" --region "$REGION" "${P[@]}" 2>/dev/null
gcloud compute networks delete "$VPC" "${P[@]}" 2>/dev/null
gcloud projects remove-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA_DF" --role roles/dataflow.worker --condition None "${P[@]}" >/dev/null 2>&1
for sa in "$SA_PUB" "$SA_DF"; do gcloud iam service-accounts delete "$sa" "${P[@]}" 2>/dev/null; done
if [ "${1:-}" = "--disable-apis" ]; then gcloud services disable dataflow.googleapis.com "${P[@]}"; fi
echo "== verify"
left=0
chk() { local out; out="$("$@" 2>/dev/null)"; [ -n "$out" ] && { echo "LEFT: $out"; left=1; }; }
chk gcloud pubsub topics list --project "$PROJECT" --filter "name~dtc-ingest" --format "value(name)"
chk gcloud pubsub subscriptions list --project "$PROJECT" --filter "name~dtc-ingest" --format "value(name)"
chk gcloud storage buckets list --project "$PROJECT" --filter "name~^dtc-ingest" --format "value(name)"
chk gcloud compute networks list --project "$PROJECT" --filter "name~^dtc-ingest" --format "value(name)"
chk gcloud iam service-accounts list --project "$PROJECT" --filter "email~^dtc-ingest" --format "value(email)"
chk gcloud dataflow jobs list --project "$PROJECT" --region "$REGION" --status active --filter "name:dtc-ingest-" --format "value(name)"
bq --project_id "$PROJECT" show "$DATASET" >/dev/null 2>&1 && { echo "LEFT: dataset $DATASET"; left=1; }
[ -n "${EVIDENCE_BUCKET:-}" ] && echo "evidence bucket objects (read only): $(gcloud storage ls "gs://$EVIDENCE_BUCKET/**" --project "$PROJECT" 2>/dev/null | grep -c '^gs://')"
[ "$left" = 0 ] && echo "teardown verified: no dtc-ingest resources left" || exit 1
