import ConnectTelemetry from './ConnectTelemetry.jsx'
import demo from './ingestion-demo.json'

// The Integration step of a project made in the wizard. It shows how telemetry would enter the
// platform, and the RECORDED result of one replay through the ingestion slice (docs/ingestion.md),
// read from a committed file. It shows no live status and starts nothing.

const FIELDS = 'run_id, kind, tick, timestamp, operational_hours, twin_id, twin_version, channel_id, direction, unit, physical_value, predicted_value, test_point'
const yesNo = (v) => (v ? 'Yes' : 'No')

export default function IntegrationPanel({ project }) {
  const c = demo.counts
  const e = demo.engine
  const pre = { margin: 0, padding: '12px 14px', overflow: 'auto', fontSize: 11, lineHeight: 1.6, fontFamily: 'ui-monospace, Menlo, monospace', color: 'var(--ink-mid)', background: 'var(--paper)', border: '1px solid var(--rule)', borderRadius: 3 }
  const row = (k, v) => <tr key={k}><td>{k}</td><td className="num">{v}</td></tr>
  return (
    <section className="section" aria-labelledby="integration-title">
      <div className="section-head"><h2 id="integration-title" className="label">Integration</h2></div>
      <div className="panel panel-pad" style={{ display: 'grid', gap: 8 }}>
        <p className="h4" style={{ fontSize: 13 }}>{demo.label}</p>
        <p className="hint">
          A project made in the wizard is configuration only. It is not connected to this pipeline or to the engine:
          the replay below used the {demo.replayed_run.project}&apos;s sealed run &ldquo;{demo.replayed_run.title}&rdquo;.
          The figures are a recorded result from a file in the repository, not a live status, and nothing on this page starts a cloud job.
        </p>
      </div>
      <ConnectTelemetry project={project} />
      <div style={{ display: 'grid', gap: 18, gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', alignItems: 'start' }}>
        <div className="panel">
          <div className="panel-head"><h3 className="label">Topic and message format</h3></div>
          <div className="panel-pad" style={{ display: 'grid', gap: 8 }}>
            <p className="hint">Topic <b>{demo.topic}</b>; invalid messages go to <b>{demo.dead_letter_topic}</b>.
              Data: one reading with exactly the engine&apos;s 13 fields ({FIELDS}).
              Attributes: schema, source, replay_id, event_ts, reading_key (the idempotency key) and content_sha256.</p>
            <pre style={pre}>{JSON.stringify(demo.example_message, null, 2)}</pre>
          </div>
        </div>
        <div className="panel">
          <div className="panel-head"><h3 className="label">Dataflow stage</h3><span className="small muted">{demo.pipeline.sdk}, {demo.pipeline.mode}</span></div>
          <ul className="panel-pad hint" style={{ margin: 0, paddingLeft: 34, display: 'grid', gap: 6 }}>
            <li>Keeps a raw copy of every message in Cloud Storage.</li>
            <li>Checks the shape only: the 13 fields, types, a known twin and channel. It never cleans or judges a value; dropouts, spikes and out-of-range inputs are the engine&apos;s to classify.</li>
            <li>Drops identical duplicates; a reading sent twice with different content goes to the dead-letter topic and leaves its tick incomplete.</li>
            <li>Groups readings by tick in the project&apos;s twin and channel order; a late reading re-issues its tick.</li>
            <li>Writes the validated readings to Cloud Storage and to BigQuery ({demo.bigquery_table}).</li>
            <li>One worker; the job is {demo.pipeline.stopped}.</li>
          </ul>
        </div>
        <div className="panel">
          <div className="panel-head"><h3 className="label">Google Cloud services involved</h3></div>
          <ul className="panel-pad hint" style={{ margin: 0, paddingLeft: 34, display: 'grid', gap: 6 }}>
            <li>Pub/Sub: the readings topic and the dead-letter topic</li>
            <li>Dataflow: the validation and ordering pipeline</li>
            <li>Cloud Storage: raw and validated readings, receipts</li>
            <li>BigQuery: the validated readings table</li>
            <li>The assurance engine then runs on the validated readings (run locally in the demonstration)</li>
          </ul>
        </div>
      </div>
      <div className="panel">
        <div className="panel-head"><h3 className="label">Recorded result of the last replay</h3><span className="small muted">{demo.date} · replay {demo.replay_id}</span></div>
        <div style={{ display: 'grid', gap: 18, gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', alignItems: 'start', padding: '14px 18px' }}>
          <div className="table-wrap">
            <table className="grid" style={{ minWidth: 0 }}>
              <tbody>
                {row('Messages published', c.published)}
                {row('· readings of the sealed run', c.readings)}
                {row('· identical duplicates (sent on purpose)', c.identical_duplicates_sent)}
                {row('· end-of-replay marker (not a reading)', c.end_of_replay_markers)}
                {row('Raw messages stored', c.raw_messages_stored)}
                {row('Rejected to the dead-letter topic', c.dead_lettered)}
                {row('Validated readings', `${c.validated_readings} (${c.ticks} ticks)`)}
                {row('BigQuery rows', c.bigquery_rows)}
              </tbody>
            </table>
          </div>
          <div className="table-wrap">
            <table className="grid" style={{ minWidth: 0 }}>
              <tbody>
                {row('Validated readings identical to the sealed run', yesNo(demo.readings_file_identical_to_sealed))}
                {row('Comparison copy: ledger head identical to the pinned run', yesNo(e.comparison_copy.head_identical))}
                {row('Ingestion-labelled run: same decisions as the pinned run', yesNo(e.ingestion_labelled.same_decisions))}
                {row('Ingestion-labelled run: same head', `${yesNo(e.ingestion_labelled.head_identical)} (differs by design)`)}
              </tbody>
            </table>
          </div>
        </div>
        <div className="panel-pad" style={{ paddingTop: 0, display: 'grid', gap: 6 }}>
          <p className="hint">The comparison copy records the code commit of the original run, only to show that the same readings give the same ledger; it is never pinned or shown as evidence.
            The ingestion-labelled run records the commit that ran and the ingestion seals. Pinned head {e.comparison_copy.pin_head.slice(0, 16)}…, receipt SHA-256 {demo.receipt_sha256.slice(0, 16)}….</p>
          <p className="hint">Other replays the same day: {demo.other_tests.join('; ')}.</p>
        </div>
      </div>
    </section>
  )
}
