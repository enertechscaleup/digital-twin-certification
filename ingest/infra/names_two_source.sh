# Names of the two-source path's NEW resources (ingest/infra/create_two_source.sh). Every name contains
# plant or twin; the bucket, dataset, network and worker account are the existing ones (names.sh).
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/names.sh"
PLANT_TOPIC=dtc-ingest-plant
TWIN_TOPIC=dtc-ingest-twin
PLANT_DLQ=dtc-ingest-plant-dlq
TWIN_DLQ=dtc-ingest-twin-dlq
PLANT_SUB=dtc-ingest-plant-dataflow
TWIN_SUB=dtc-ingest-twin-dataflow
PLANT_DLQ_SUB=dtc-ingest-plant-dlq-hold
TWIN_DLQ_SUB=dtc-ingest-twin-dlq-hold
SA_PLANT="dtc-ingest-plant-publisher@${PROJECT}.iam.gserviceaccount.com"
SA_TWIN="dtc-ingest-twin-publisher@${PROJECT}.iam.gserviceaccount.com"
TWO_SOURCE_TABLES="plant_validated twin_validated joined_readings"
