# Resource names of the ingestion slice. Project, region and bucket suffix come from the
# git-ignored ingest/.env (written by create.sh); nothing project-specific is committed.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$HERE/.env" ] && . "$HERE/.env"
: "${PROJECT:?set PROJECT (or run create.sh)}"
REGION="${REGION:-us-central1}"
TOPIC=dtc-ingest-readings
SUB=dtc-ingest-readings-dataflow
DLQ=dtc-ingest-readings-dlq
DLQ_SUB=dtc-ingest-readings-dlq-hold
BUCKET="dtc-ingest-${SUFFIX:?no SUFFIX}"
DATASET=dtc_ingest
TABLE=readings_validated
VPC=dtc-ingest-vpc
SUBNET=dtc-ingest-subnet
FIREWALL=dtc-ingest-allow-dataflow
SA_PUB="dtc-ingest-publisher@${PROJECT}.iam.gserviceaccount.com"
SA_DF="dtc-ingest-dataflow@${PROJECT}.iam.gserviceaccount.com"
