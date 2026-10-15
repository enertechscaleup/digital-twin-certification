import { useEffect, useMemo, useState } from 'react'
import RULES from './ingestion-rules.json'
import { classify, readingKey, sha256Hex } from './ingestValidate.js'

// "Connect telemetry": how a project's telemetry would reach the platform, the message contract
// built from the project's own channels, and a sample-message check that runs in the browser with
// the Dataflow validator's rules. Nothing here calls a network service or connects anything.

const SOURCES = [
  { id: 'push', label: 'Push to Pub/Sub', status: 'Demonstrated on replayed synthetic data',
    text: 'The asset side publishes every reading as one message to the project’s topic: the data is the reading in the format below, and the attributes identify it. The Dataflow pipeline then checks, de-duplicates and orders the readings per tick before the engine sees them. This is the path demonstrated on replayed synthetic data.' },
  { id: 'pull', label: 'Pull from a historian or an OPC UA / MQTT gateway', status: 'Designed, not built',
    text: 'A connector would read each mapped tag or topic on a schedule, stamp each value with its source timestamp and publish it to the same topic in the same format. The channel table below would be its mapping. Ticks would need an alignment rule, declared per channel and sealed into the evidence.' },
  { id: 'vendor', label: 'Vendor twin API', status: 'Designed, not built',
    text: 'Each twin owner’s endpoint would return the twin’s prediction for the same tick, which the platform would place in predicted_value next to the measured value. In this prototype predictions come from simulated owner endpoints.' },
]
const DISABLED_NOTE = 'Not enabled in this prototype. Connecting a live source needs a project registered on the platform, and the wizard saves configuration in this browser only.'

/** The channels a message may carry, from a wizard project or (with no project) the example project. */
function contractFor(project) {
  if (!project) {
    const ex = RULES.example_project
    return { label: `${RULES.example_project.label}: ${ex.name}`, projectId: ex.project_id, channels: ex.channels, sample: ex.sample }
  }
  const channels = project.twins.flatMap((t) => t.channels.map((c) => ({
    twin_id: t.operational_twin_id, twin: t.name, channel_id: c.id, name: c.name, direction: c.direction, unit: c.unit,
    range: c.assured_range, monitored: c.monitored !== false,
  })))
  return { label: project.name, projectId: project.project_id, channels, sample: null }
}

async function sampleFor(projectId, channels) {
  const c = channels.find((x) => x.direction === 'output' && x.monitored !== false) || channels[0]
  if (!c) return { data: '', attributes: {} }
  const mid = (c.range[0] + c.range[1]) / 2
  const data = JSON.stringify({
    run_id: `field-${projectId}-sample`, kind: 'field', tick: 0, timestamp: '2026-10-01T00:00:00Z', operational_hours: 0,
    twin_id: c.twin_id, twin_version: '1.0.0', channel_id: c.channel_id, direction: c.direction, unit: c.unit,
    physical_value: mid, predicted_value: c.direction === 'output' ? mid : null, test_point: null,
  })
  return { data, attributes: { schema: RULES.schema, source: 'sample', replay_id: 'sample', event_ts: '2026-10-01T00:00:00Z',
    reading_key: await readingKey('sample', `field-${projectId}-sample`, 0, c.twin_id, c.channel_id), content_sha256: await sha256Hex(data) } }
}

const reasonText = (code) => RULES.reject_reasons.find((r) => r.code === code)?.meaning || code

export default function ConnectTelemetry({ project }) {
  const contract = useMemo(() => contractFor(project), [project])
  const [source, setSource] = useState('push')
  const [data, setData] = useState('')
  const [attrs, setAttrs] = useState('')
  const [result, setResult] = useState(null)
  useEffect(() => {
    let live = true
    const load = contract.sample ? Promise.resolve(contract.sample) : sampleFor(contract.projectId, contract.channels)
    load.then((s) => { if (live) { setData(s.data); setAttrs(JSON.stringify(s.attributes, null, 2)); setResult(null) } })
    return () => { live = false }
  }, [contract])

  const check = async () => {
    let a
    try { a = JSON.parse(attrs) } catch { setResult({ kind: 'attributes', reason: null }); return }
    setResult(await classify(data, a, contract.channels, RULES))
  }
  const recompute = async () => {
    let a = {}
    try { a = JSON.parse(attrs) } catch { /* start from empty attributes */ }
    let r = {}
    try { r = JSON.parse(data) } catch { /* the check will report it */ }
    const next = { ...a, content_sha256: await sha256Hex(data),
      reading_key: await readingKey(a.replay_id ?? 'sample', r.run_id, r.tick, r.twin_id, r.channel_id) }
    setAttrs(JSON.stringify(next, null, 2)); setResult(null)
  }
  const chosen = SOURCES.find((s) => s.id === source)
  const box = { width: '100%', fontFamily: 'ui-monospace, Menlo, monospace', fontSize: 11, lineHeight: 1.5, boxSizing: 'border-box' }

  return (
    <div className="panel">
      <div className="panel-head"><h3 className="label">Connect telemetry</h3><span className="small muted">{contract.label}</span></div>
      <div className="panel-pad" style={{ display: 'grid', gap: 18 }}>
        <div style={{ display: 'grid', gap: 10 }}>
          <div className="h4">1 · Source</div>
          <div role="radiogroup" aria-label="Telemetry source" style={{ display: 'grid', gap: 8, gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
            {SOURCES.map((s) => (
              <button key={s.id} role="radio" aria-checked={source === s.id} onClick={() => setSource(s.id)} className="panel"
                style={{ textAlign: 'left', padding: '10px 12px', cursor: 'pointer', borderColor: source === s.id ? 'var(--ink)' : undefined, display: 'grid', gap: 4 }}>
                <span className="h4">{s.label}</span>
                <span className="small muted">{s.status}</span>
              </button>
            ))}
          </div>
          <p className="hint"><b>{chosen.label}</b> ({chosen.status.toLowerCase()}). {chosen.text}</p>
        </div>

        <div style={{ display: 'grid', gap: 10 }}>
          <div className="h4">2 · Contract for {project ? 'this project' : 'the example project'}</div>
          <p className="hint">Topic <b>dtc-telemetry-{contract.projectId}</b> (would be created on connection). Message data: one reading as a JSON object with exactly these fields: {RULES.allowed_fields.join(', ')}.
            Attributes: schema <b>{RULES.schema}</b>, {RULES.required_attributes.join(', ')}, event_ts. The reading_key is the {RULES.reading_key}; it makes a resend harmless.</p>
          <div className="table-wrap">
            <table className="grid" style={{ minWidth: 560 }}>
              <thead><tr><th>Channel</th><th>twin_id</th><th>channel_id</th><th>direction</th><th>unit</th><th>Expected range</th></tr></thead>
              <tbody>{contract.channels.map((c) => (
                <tr key={`${c.twin_id}/${c.channel_id}`}><td>{c.name}{c.monitored === false ? ' (not monitored)' : ''}</td><td>{c.twin_id}</td><td>{c.channel_id}</td>
                  <td>{c.direction}</td><td>{c.unit}</td><td className="num">{c.range[0]} – {c.range[1]}</td></tr>
              ))}</tbody>
            </table>
          </div>
          <p className="hint">physical_value is the measured value (null for a dropout); predicted_value is the twin’s prediction for an output and null for an input. Values outside the expected range are still accepted: classifying them is the engine’s job.</p>
        </div>

        <div style={{ display: 'grid', gap: 6 }}>
          <div className="h4">3 · Access</div>
          <p className="hint">A publish-only service account would be used: it may publish to this project’s topic and nothing else, through short-lived credentials. No keys are issued, and none are shown here.</p>
        </div>

        <div style={{ display: 'grid', gap: 10 }}>
          <div className="h4">4 · Check a sample message</div>
          <p className="hint">Checked in this browser with the same rules and reject codes as the Dataflow validator; nothing is sent anywhere.</p>
          <label className="small muted" htmlFor="sample-data">Message data</label>
          <textarea id="sample-data" className="textarea" rows={6} style={box} value={data} onChange={(e) => { setData(e.target.value); setResult(null) }} />
          <label className="small muted" htmlFor="sample-attrs">Attributes (JSON)</label>
          <textarea id="sample-attrs" className="textarea" rows={7} style={box} value={attrs} onChange={(e) => { setAttrs(e.target.value); setResult(null) }} />
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <button className="button button-small" onClick={check}>Check message</button>
            <button className="button button-ghost button-small" onClick={recompute}>Recompute content_sha256 and reading_key</button>
          </div>
          <p className="small" role="status" aria-live="polite" data-testid="check-result">
            {!result ? '' : result.kind === 'valid' ? 'Valid: the pipeline would accept this message.'
              : result.kind === 'control' ? 'A control message (end of a replay), not a reading.'
              : result.kind === 'attributes' ? 'The attributes are not valid JSON.'
              : `Rejected: ${result.reason}. ${reasonText(result.reason)}.`}
          </p>
          <details className="small muted"><summary>All reject codes</summary>
            <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>{RULES.reject_reasons.map((r) => <li key={r.code}><b>{r.code}</b>: {r.meaning}</li>)}</ul>
          </details>
        </div>

        <div style={{ display: 'grid', gap: 6 }}>
          <div className="h4">5 · Enable</div>
          <div><button className="button button-small" disabled aria-describedby="enable-note">Enable connection</button></div>
          <p id="enable-note" className="hint">{DISABLED_NOTE}</p>
        </div>
      </div>
    </div>
  )
}
