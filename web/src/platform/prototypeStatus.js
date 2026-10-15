// What this prototype has built, and what is designed only: one list, used by the Connect telemetry
// step and by the "Status of this prototype" view. tests/test_register_status.py checks both views
// render from here and nowhere else.
import demo from './ingestion-demo.json'

export const ALIGNMENT_BUILT = [
  'Both values of a reading share one tick index (and one timestamp).',
  'A tick is evaluated only when it is complete: every channel of the project, once.',
  'A reading that arrives late re-issues its tick, and the complete tick is used (tested in replay r1015e).',
  'An incomplete tick makes the engine refuse the run; it is never patched.',
  'Two copies of a reading with different content are dead-lettered, never resolved.',
]
export const ALIGNMENT_DESIGNED = [
  'Clock synchronisation between the twin side’s and the plant side’s systems',
  'Resampling of readings taken at different rates onto the tick grid',
  'Lag compensation between a plant measurement and the matching twin prediction',
  'An alignment window per channel, declared and sealed into the evidence',
  'A tick missing either side is “not evaluated” and is never guessed',
]
export const SEPARATE_FEEDS = 'Separate twin messages and plant messages, joined per tick in the pipeline'
export const PROVENANCE = 'Per-value provenance'
export const SOURCES_DESIGNED = [
  [PROVENANCE, 'Which party supplied physical_value and which supplied predicted_value. Today nothing in the message says so.'],
  [SEPARATE_FEEDS, 'Today one message carries both sides.'],
]

export const STATUS_HEADING = 'Status of this prototype'
export const STATUS_FIRST_LINE = 'Nothing was registered or sent. This prototype has no live registration.'

export const BUILT_AND_DEMONSTRATED = [
  'The evidence engine and its hash-chained ledger',
  'Retention-locked evidence in Cloud Storage',
  'Re-verification on Cloud Run before a run is served',
  'Explanations by Gemini on Vertex AI, and the read-only evidence assistant',
  `Streaming ingestion (Pub/Sub, Dataflow, BigQuery, Cloud Storage) on replayed synthetic data on ${demo.date}`,
]
export const DESIGNED_NOT_BUILT = [
  'A source connection for a real project: push from a customer system, pull from a historian or an OPC UA / MQTT gateway, or a vendor twin API',
  `${SEPARATE_FEEDS} (separate twin and plant feeds)`,
  PROVENANCE,
  ...ALIGNMENT_DESIGNED,
]
export const GO_LIVE_STEPS = [
  ['Register the project on the platform', false, 'Projects made in the wizard are configuration saved in this browser.'],
  ['Create its topic, subscription and publish-only service account', false, 'The replay demonstration used one shared topic and service account created by script, not one per project.'],
  ['The twin owner and the plant each publish their data', false, 'In the demonstration one publisher replayed a sealed synthetic run.'],
  ['Declare and seal the alignment window', false, 'Designed only.'],
  ['Monitoring starts', false, 'The engine monitors sealed and replayed synthetic runs only.'],
]
