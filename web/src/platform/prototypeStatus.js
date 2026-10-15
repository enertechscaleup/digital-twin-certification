// What this prototype has built, and what is designed only: one list, used by the Connect telemetry
// step and by the "Status of this prototype" view. tests/test_register_status.py checks both views
// render from here and nowhere else.
import demo from './ingestion-demo.json'
import twoSource from './ingestion-two-source.json'

export const ALIGNMENT_BUILT_LABEL = 'Built (both paths)'
export const ALIGNMENT_BUILT = [
  'Twin and plant values are matched on one tick index.',
  'A tick is evaluated only when it is complete: every channel of the project, and both sides of every output.',
  'A reading that arrives late re-issues its tick, and the complete tick is used (tested in replays r1015e and t1015e).',
  'An incomplete tick, including one missing either side, makes the engine refuse the run; it is never patched.',
  'Two copies of a reading with different content are dead-lettered, never resolved (on each feed).',
]
export const ALIGNMENT_BUILT_NOTE = 'Built rows were demonstrated on replayed synthetic data. Both feeds replayed the same sealed run and shared its tick index. This is not clock synchronisation.'
export const ALIGNMENT_DESIGNED = [
  'Clock synchronisation between the twin side’s and the plant side’s systems',
  'Resampling of readings taken at different rates onto the tick grid',
  'Lag compensation between a plant measurement and the matching twin prediction',
  'An alignment window per channel, declared and sealed into the evidence',
  'A tick missing either side is “not evaluated” and is never guessed',
]
export const SEPARATE_FEEDS = 'Separate twin messages and plant messages, joined per tick in the pipeline'
export const PROVENANCE = 'Per-value provenance'
export const DESIGNED_LABEL = 'Not built, designed only'
export const TWO_SOURCE_BUILT_LABEL = `Built and run on replayed synthetic data on ${twoSource.date}`
// [what, status, today]
export const VALUE_SOURCES = [
  [PROVENANCE, DESIGNED_LABEL, 'Which party supplied physical_value and which supplied predicted_value. The separate feeds carry a sender attribute, but the publisher declares it and nothing verifies it or seals it into the evidence; the separate publishing account for each feed separates the two only at the transport level.'],
  [SEPARATE_FEEDS, TWO_SOURCE_BUILT_LABEL, `${twoSource.shared_tick_index} A tick missing either side is incomplete, and the engine refuses the run.`],
]
export const TWO_PATHS = 'Two paths are built: one message carrying both sides, and separate twin and plant messages joined per tick (both demonstrated on replayed synthetic data).'

export const STATUS_HEADING = 'Status of this prototype'
export const STATUS_FIRST_LINE = 'Nothing was registered or sent. This prototype has no live registration.'

export const BUILT_AND_DEMONSTRATED = [
  'The evidence engine and its hash-chained ledger',
  'Retention-locked evidence in Cloud Storage',
  'Re-verification on Cloud Run before a run is served',
  'Explanations by Gemini on Vertex AI, and the read-only evidence assistant',
  `Streaming ingestion (Pub/Sub, Dataflow, BigQuery, Cloud Storage) on replayed synthetic data on ${demo.date}`,
  `Separate twin and plant feeds (Pub/Sub, Dataflow, BigQuery), joined per tick, on replayed synthetic data on ${twoSource.date}; both feeds replayed the same sealed run and shared its tick index`,
]
export const DESIGNED_NOT_BUILT = [
  'A source connection for a real project: push from a customer system, pull from a historian or an OPC UA / MQTT gateway, or a vendor twin API',
  PROVENANCE,
  ...ALIGNMENT_DESIGNED,
]
export const GO_LIVE_STEPS = [
  ['Register the project on the platform', false, 'Projects made in the wizard are configuration saved in this browser.'],
  ['Create its topic, subscription and publish-only service account', false, 'The replay demonstrations used topics and service accounts created by script, not one set per project.'],
  ['The twin owner and the plant each publish their data', false, 'In the demonstration, two publishers replayed the same sealed synthetic run, one feed each.'],
  ['Declare and seal the alignment window', false, 'Designed only.'],
  ['Monitoring starts', false, 'The engine monitors sealed and replayed synthetic runs only.'],
]
