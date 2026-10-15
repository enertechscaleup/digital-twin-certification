#!/usr/bin/env bash
# Removes ONLY the two-source path's resources (topics, subscriptions, publisher accounts, tables and
# the raw2/, validated2/, joined/, receipts2/, dataflow2/ prefixes), then checks none is left. Only on request.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/names_two_source.sh"
P=(--project "$PROJECT" --quiet)
"$HERE/stop_all.sh" || exit 1
for s in "$PLANT_SUB" "$TWIN_SUB" "$PLANT_DLQ_SUB" "$TWIN_DLQ_SUB"; do gcloud pubsub subscriptions delete "$s" "${P[@]}" 2>/dev/null; done
for t in "$PLANT_TOPIC" "$TWIN_TOPIC" "$PLANT_DLQ" "$TWIN_DLQ"; do gcloud pubsub topics delete "$t" "${P[@]}" 2>/dev/null; done
for table in $TWO_SOURCE_TABLES; do bq --project_id "$PROJECT" rm -f -t "$PROJECT:$DATASET.$table" 2>/dev/null; done
for pre in raw2 validated2 joined receipts2 dataflow2; do gcloud storage rm -r "gs://$BUCKET/$pre/" "${P[@]}" 2>/dev/null; done
for sa in "$SA_PLANT" "$SA_TWIN"; do gcloud iam service-accounts delete "$sa" "${P[@]}" 2>/dev/null; done
left=0
for name in "$PLANT_TOPIC" "$TWIN_TOPIC" "$PLANT_DLQ" "$TWIN_DLQ"; do gcloud pubsub topics describe "$name" --project "$PROJECT" >/dev/null 2>&1 && { echo "LEFT: $name"; left=1; }; done
for table in $TWO_SOURCE_TABLES; do bq --project_id "$PROJECT" show "$DATASET.$table" >/dev/null 2>&1 && { echo "LEFT: $table"; left=1; }; done
[ "$left" = 0 ] && echo "two-source teardown verified: none of its resources left"
