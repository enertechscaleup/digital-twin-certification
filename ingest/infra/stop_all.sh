#!/usr/bin/env bash
# Stops every Dataflow job of the ingestion slice (name dtc-ingest-*) and checks that none is left.
# Exit status 0 only if no dtc-ingest-* job is running, draining, cancelling or pending.
set -uo pipefail
. "$(cd "$(dirname "$0")" && pwd)/names.sh"
active() { gcloud dataflow jobs list --project "$PROJECT" --region "$REGION" --status active \
             --filter "name:dtc-ingest-" --format "value(id,name,state)"; }
active | while read -r id name state; do
  [ -z "$id" ] && continue
  case "$state" in Draining|Cancelling) echo "already stopping: $name ($state)";;
    *) echo "cancelling $name ($state)"; gcloud dataflow jobs cancel "$id" --project "$PROJECT" --region "$REGION" >/dev/null;; esac
done
for i in $(seq 1 60); do
  left="$(active)"
  [ -z "$left" ] && { echo "check: no dtc-ingest-* Dataflow job active in $REGION"; exit 0; }
  sleep 10
done
echo "still active after 10 minutes:"; echo "$left"; exit 1
