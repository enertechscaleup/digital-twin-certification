import { useState } from 'react'
import Chart from './Chart.jsx'
import { CAUSES, anomalyClass, anomalyLabel, fmtNum, short, summarize, twinName } from './labels.js'

const STATUS_COLOR = { flagged: '#b45309', nullified: '#b3261e', assured: '#137333' }
// Inputs charted besides connected ones: the motor's supply voltage, the control input for adjustments.
const DISPLAY_INPUTS = { 'motor-op-001': ['volt'] }

/* ---------- Twins ---------- */

export function TwinCard({ id, role, twin }) {
  const status = twin?.status || 'assured'
  const history = twin?.assurance_history || []
  const current = history[history.length - 1]
  return (
    <div className={`panel twin-card ${status}`}>
      <div className="role">{role}</div>
      <div className="name">{twinName(id)}</div>
      <span className={`pill big ${status}`}>{status}</span>
      <div className="asr">
        Assurance <code>{twin?.assurance_id || '—'}</code>
        {current?.twin_version && <> · twin {current.twin_version}</>}
        {current?.supersedes && <> · supersedes <code>{current.supersedes}</code></>}
      </div>
      <ul className="reasons">
        {(twin?.reasons || []).map((r, i) => (
          <li key={i} className={`reason ${r.level} ${r.resolved ? 'resolved' : ''}`}>
            <div className="what">{CAUSES[r.cause] || r.cause}{r.channel_id ? ` · ${r.channel_id}` : ''}</div>
            <div className="detail">{r.constituent ? `${twinName(r.constituent)}: ` : ''}{r.detail} · since tick {r.since_tick}</div>
            {r.root_causes?.length > 0 && (
              <div className="root">Traced to: {r.root_causes.map((c) => `${CAUSES[c.cause] || c.cause}${c.channel_id ? ` on ${c.channel_id}` : ''}`).join('; ')}</div>
            )}
            {r.resolved && <div className="resolved-note">Resolved at tick {r.resolved.at_tick}: {r.resolved.note}</div>}
          </li>
        ))}
        {twin && !twin.reasons?.length && <li className="reason"><div className="detail">No open reasons under this assurance.</div></li>}
      </ul>
    </div>
  )
}

export function Composition({ twins, showSystem }) {
  const s = (id) => twins?.[id]?.status || 'assured'
  return (
    <div className="composition">
      <span className={`node ${s('motor-op-001')}`}>Motor · {s('motor-op-001')}</span>
      {showSystem && <>
        <span className="edge">— shaft speed →</span>
        <span className={`node ${s('compressor-op-001')}`}>Compressor · {s('compressor-op-001')}</span>
        <span className="edge">=</span>
        <span className={`node ${s('compressor-system-op-001')}`}>Compressor system twin · {s('compressor-system-op-001')}</span>
      </>}
    </div>
  )
}

/* ---------- Charts ---------- */

function statusMarkers(ledger, twinId, tick) {
  const out = []
  for (const e of ledger) {
    const p = e.payload
    if (e.tick > tick) continue
    if (e.entry_type === 'assurance_status_changed' && p.twin_id === twinId) {
      out.push({ x: p.tick, label: `${p.to[0].toUpperCase()}${p.to.slice(1)} @${p.tick}`, color: STATUS_COLOR[p.to] })
    }
    if (e.entry_type === 'assurance_issued' && p.twin_id === twinId && p.supersedes) {
      out.push({ x: e.tick, label: `v2 assured @${e.tick}`, color: STATUS_COLOR.assured })
    }
    if (e.entry_type === 'adjustment_recommended' && twinId !== 'compressor-system-op-001') {
      out.push({ x: p.tick, label: `Recommended @${p.tick}`, color: '#1a73e8' })
    }
    if (e.entry_type === 'adjustment_executed' && twinId !== 'compressor-system-op-001') {
      out.push({ x: p.tick, label: `Executed @${p.tick}`, color: '#0b57d0' })
    }
  }
  return out
}

function paddedRange(r, pad = 0.08) {
  const span = (r.max - r.min) || Math.abs(r.max) * 0.1 || 1
  return [r.min - span * pad, r.max + span * pad]
}

export function TwinCharts({ meta, view, twinId, tick }) {
  const twin = meta.twins[twinId]
  const outputs = twin.channels.filter((c) => c.direction === 'output')
  const linkedIds = meta.system_twin.connections.filter((c) => twinId.startsWith(c.to_twin)).map((c) => c.to_channel)
  const inputIds = [...linkedIds, ...(DISPLAY_INPUTS[twinId] || [])]
  const inputs = inputIds.map((id) => twin.channels.find((ch) => ch.channel_id === id))
  const rec = view.ledger.find((e) => e.entry_type === 'adjustment_recommended')
  const readings = view.readings.filter((r) => r.twin_id === twinId)
  const series = (ch, field) => readings.filter((r) => r.channel_id === ch).map((r) => [r.tick, r[field]])
  const markers = statusMarkers(view.ledger, twinId, tick)
  const xMax = meta.ticks - 1
  const tol = outputs[0]?.tolerance_pct ?? 5
  const mult = meta.escalation_protocol.nullify_tolerance_multiplier
  const gapMax = Math.max(tol * mult + 4, Math.ceil((meta.display_ranges.gap_pct_max + 1) / 5) * 5)
  const gapColors = ['#7c3aed', '#0d9488']
  const notEvaluated = view.timeline
    .filter((row) => Object.values(row.classifications[twinId] || {}).some((c) => c.class === 'not_evaluated'))
    .map((row) => row.tick)

  return (
    <div className="section">
      {inputs.map((ch) => {
        const isLinked = linkedIds.includes(ch.channel_id)
        const dr = meta.display_ranges[`${twinId}/${ch.channel_id}`]
        const [lo, hi] = isLinked
          ? paddedRange({ min: Math.min(dr.min, ch.envelope[0]), max: Math.max(dr.max, ch.envelope[0]) })
          : paddedRange({ min: Math.min(dr.min, ch.envelope[0]), max: Math.max(dr.max, ch.envelope[1]) + (ch.envelope[1] - ch.envelope[0]) * 0.35 })
        const hl = isLinked
          ? [{ y: ch.envelope[0], label: `Assured minimum ${fmtNum(ch.envelope[0], 0)} ${ch.unit}`, color: '#137333' }]
          : [{ y: ch.envelope[1], left: true, label: `Assured maximum ${fmtNum(ch.envelope[1], 0)} ${ch.unit}`, color: '#137333' }]
        if (isLinked && rec) {
          hl.push({ y: rec.payload.predicted_objective_value, x0: rec.payload.tick, left: true, below: true, color: '#1a73e8',
            label: `Predicted after adjustment ${fmtNum(rec.payload.predicted_objective_value, 0)} ${ch.unit} (+${fmtNum(rec.payload.predicted_margin_above_objective, 0)} above minimum)` })
        }
        if (!isLinked && rec && rec.payload.recommendation.control_channel === ch.channel_id) {
          hl.push({ y: rec.payload.recommendation.to, left: true, below: true, color: '#1a73e8',
            label: `Recommended setpoint ${fmtNum(rec.payload.recommendation.to, 0)} ${ch.unit}` })
        }
        return (
          <div className="panel chart-card section" key={ch.channel_id}>
            <h3>{twinName(twinId)} {ch.name.toLowerCase()} ({isLinked ? 'input, driven by the motor' : 'input'}) vs its assured range</h3>
            <div className="legend">
              <span><span className="key" style={{ borderTopColor: '#111827' }} />Measured {ch.unit}</span>
              <span><span className="key" style={{ borderTopColor: '#34a853', borderTopWidth: 10 }} />Assured range {fmtNum(ch.envelope[0], 0)}–{fmtNum(ch.envelope[1], 0)} {ch.unit}</span>
              {isLinked && <span>Grey = outputs not evaluated (input outside assured range)</span>}
            </div>
            <Chart W={1400} H={260} xMax={xMax} yMin={lo} yMax={hi} cursor={tick} shade={isLinked ? notEvaluated : []}
              band={{ min: ch.envelope[0], max: ch.envelope[1] }}
              hlines={hl}
              vlines={markers}
              series={[{ label: 'measured', color: '#111827', points: series(ch.channel_id, 'physical_value') }]} />
          </div>
        )
      })}
      <div className="grid-2 section">
        {outputs.map((ch) => {
          const [lo, hi] = paddedRange(meta.display_ranges[`${twinId}/${ch.channel_id}`])
          return (
            <div className="panel chart-card" key={ch.channel_id}>
              <h3>{twinName(twinId)} {ch.name.toLowerCase()} ({ch.unit})</h3>
              <div className="legend">
                <span><span className="key" style={{ borderTopColor: 'var(--physical)' }} />Physical reading</span>
                <span><span className="key dashed" style={{ borderTopColor: 'var(--predicted)' }} />Twin prediction (same instant)</span>
              </div>
              <Chart xMax={xMax} yMin={lo} yMax={hi} cursor={tick} vlines={markers}
                series={[
                  { label: 'physical', color: '#111827', points: series(ch.channel_id, 'physical_value') },
                  { label: 'predicted', color: '#1a73e8', dashed: true, points: series(ch.channel_id, 'predicted_value') },
                ]} />
            </div>
          )
        })}
      </div>
      <div className="panel chart-card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 12 }}>
          <h3>{twinName(twinId)}: gap between reality and twin (%)</h3>
          <div style={{ display: 'flex', gap: 28 }}>
            {outputs.map((ch) => {
              const c = view.timeline[view.timeline.length - 1]?.classifications[twinId]?.[ch.channel_id]
              const g = c?.gap_pct
              const cls = g == null ? '' : g > tol * mult ? 'bad' : g > tol ? 'warn' : 'ok'
              return (
                <div key={ch.channel_id} style={{ textAlign: 'right' }}>
                  <div className="hint" style={{ margin: 0 }}>{ch.name} gap now</div>
                  <div className={`figure ${cls}`}>{g == null ? <span className="hint" style={{ fontSize: 18 }}>not evaluated</span> : `${fmtNum(g, 1)}%`}</div>
                </div>
              )
            })}
          </div>
        </div>
        <div className="legend">
          {outputs.map((ch, i) => (
            <span key={ch.channel_id}><span className="key" style={{ borderTopColor: gapColors[i] }} />{ch.name} gap</span>
          ))}
          <span>Flagged after {meta.escalation_protocol.flag_after_consecutive} readings in a row above {tol}% · Nullified after {meta.escalation_protocol.nullify_after_consecutive} in a row above {tol * mult}%</span>
        </div>
        <Chart W={1400} H={340} xMax={xMax} yMin={0} yMax={gapMax} cursor={tick} vlines={markers} shade={notEvaluated} yLabel="gap %"
          hlines={[
            { y: tol, label: `${tol}% tolerance`, color: '#b45309' },
            { y: tol * mult, label: `${tol * mult}% nullify threshold`, color: '#b3261e' },
          ]}
          series={outputs.map((ch, i) => ({
            label: ch.channel_id, color: gapColors[i],
            points: view.timeline.map((row) => [row.tick, row.classifications[twinId]?.[ch.channel_id]?.gap_pct ?? null]),
          }))} />
      </div>
    </div>
  )
}

/* ---------- Recalibration ---------- */

export function Recalibration({ state, showSystem }) {
  const rec = Object.fromEntries(state.recalibration.map((e) => [e.entry_type, e.payload]))
  const req = rec.recalibration_requested
  if (!req) return null
  const sealed = rec.recalibration_data_sealed
  const sub = rec.recalibration_submitted?.submission
  const hv = rec.held_out_validation
  const sup = rec.assurance_superseded
  const re = rec.composition_reassessment
  const split = req.split
  const [w0, w1] = split.window
  const ownerTicks = split.released_to_owner[1] - split.released_to_owner[0] + 1
  const heldTicks = split.held_out[1] - split.held_out[0] + 1
  const Mark = ({ ok }) => <span className={`mark ${ok ? 'ok' : 'bad'}`}>{ok ? '✓' : '✗'}</span>
  return (
    <div className="panel section">
      <h2>Recalibration (Real2Sim) · {twinName(req.twin_id)}</h2>
      <p className="hint">Requested at tick {req.at_tick} while {req.status}. Flagged-period data (ticks {w0}–{w1}) is split by time, not at random.</p>
      <div className="splitbar">
        <div className="owner" style={{ flex: ownerTicks }}>Released to twin owner · ticks {split.released_to_owner.join('–')}</div>
        <div className="held" style={{ flex: heldTicks }}>Held out · ticks {split.held_out.join('–')}</div>
      </div>
      <ul className="steps">
        {sealed && <li><Mark ok /> Both parts sealed before release: <code>{short(sealed.released_part.readings_sha256)}</code> and <code>{short(sealed.held_out_part.readings_sha256)}</code></li>}
        {rec.recalibration_data_released && <li><Mark ok /> Earlier part released to the twin owner. Held-out part released: <b>no</b></li>}
        {sub && <li><Mark ok /> Owner submitted twin <b>{sub.twin_version}</b>: {sub.method}</li>}
        {hv && <li><Mark ok={hv.passed} /> Held-out validation <b>{hv.passed ? 'PASSED' : 'FAILED'}</b> on {hv.ticks_evaluated} held-out ticks the owner never saw</li>}
        {sup && <li><Mark ok /> <code>{sup.old_assurance_id}</code> superseded by <code>{sup.new_assurance_id}</code>, effective tick {sup.effective_from_tick}. Prior evidence unchanged.</li>}
        {re && showSystem && <li><Mark ok={re.result === 'reassured'} /> System twin {re.result === 'reassured' ? 're-assured' : <>not re-assured: blocked by <b>{re.blocked_by.map((b) => `${twinName(b.constituent)} (${b.reasons.map((r) => CAUSES[r.cause] + (r.channel_id ? ` · ${r.channel_id}` : '')).join('; ')})`).join(', ')}</b></>}</li>}
      </ul>
      {hv && (
        <table className="results" style={{ marginTop: 16 }}>
          <thead><tr><th>Held-out channel</th><th>Ticks evaluated</th><th>Worst gap</th><th>Tolerance</th><th>Result</th></tr></thead>
          <tbody>
            {Object.entries(hv.per_channel).map(([ch, d]) => (
              <tr key={ch}>
                <td><b>{ch}</b></td>
                <td>{d.evaluated}</td>
                <td><span className={`figure ${d.over_tolerance ? 'bad' : 'ok'}`}>{fmtNum(d.max_gap_pct, 1)}%</span></td>
                <td><span className="figure small">{d.tolerance_pct}%</span></td>
                <td><span className={`pill ${d.over_tolerance ? 'nullified' : 'assured'}`}>{d.over_tolerance ? `${d.over_tolerance} over` : 'within'}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

/* ---------- Evidence feeds ---------- */

export function Ledger({ entries, head, total }) {
  const [open, setOpen] = useState(null)
  const shown = [...entries].reverse().slice(0, 30)
  return (
    <div className="panel">
      <h2>Evidence ledger</h2>
      <p className="hint">{total} entries so far, each sealed with SHA-256 and linked to the one before. Head <code>{short(head, 16)}</code></p>
      <ul className="feed">
        {shown.map((e, i) => (
          <li key={e.seq} className={`entry ${i === 0 ? 'new' : ''}`} onClick={() => setOpen(open === e.seq ? null : e.seq)} style={{ cursor: 'pointer' }}>
            <div className="top"><span className="type">#{e.seq} {summarize(e)}</span><span className="meta">tick {e.tick}</span></div>
            <div className="chain">hash <code>{short(e.entry_hash)}</code> ← prev <code>{short(e.prev_hash)}</code></div>
            {open === e.seq && <pre>{JSON.stringify(e.payload, null, 2)}</pre>}
          </li>
        ))}
      </ul>
    </div>
  )
}

export function Explanations({ items }) {
  const shown = [...items].reverse()
  return (
    <div className="panel">
      <h2>AI explanations</h2>
      <p className="hint">Generated by Gemini from the evidence alone. Supplementary: never used in any assurance decision. Kept in a separate ledger linked to the entry each one explains.</p>
      <ul className="feed">
        {shown.length === 0 && <li className="hint">None yet at this tick.</li>}
        {shown.map((e) => {
          const a = e.payload
          const r = a.response || {}
          return (
            <li key={e.seq} className="ai-card">
              <div className="ai-label">Supplementary AI · {a.artifact_type.replaceAll('_', ' ')}</div>
              <div className="headline">{r.headline}</div>
              <div className="body">{r.explanation}</div>
              <div className="foot">
                Suggested: <b>{(r.suggested_classification || '').replaceAll('_', ' ')}</b> ({r.confidence} confidence) ·
                explains ledger #{a.explains_ledger_seq} <code>{short(a.explains_entry_hash)}</code> · {a.model_id}
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export function Anomalies({ ledger }) {
  const [acks, setAcks] = useState({})
  const closed = new Set(ledger.filter((e) => e.entry_type === 'anomaly_closed').map((e) => e.payload.anomaly_id))
  const opened = ledger.filter((e) => e.entry_type === 'anomaly_opened').reverse()
  return (
    <div className="panel">
      <h2>Anomalies</h2>
      <p className="hint">Acknowledging here is a demo action kept in this browser session only; it is never written to the evidence.</p>
      <ul className="feed">
        {opened.length === 0 && <li className="hint">None yet at this tick.</li>}
        {opened.map((e) => {
          const p = e.payload
          const isOpen = !closed.has(p.anomaly_id)
          return (
            <li key={p.anomaly_id} className="entry">
              <div className="top">
                <span><span className={`badge ${anomalyClass(p)}`}>{anomalyLabel(p)}</span> <b>{twinName(p.twin_id)} · {p.channel_id}</b></span>
                <span className="meta">tick {p.tick} · {isOpen ? 'open' : 'closed'}</span>
              </div>
              <div className="chain">
                {p.gap_pct != null && <>gap {fmtNum(p.gap_pct, 2)}% · </>}severity {p.severity} · ledger #{e.seq}
                {' · '}
                {acks[p.anomaly_id]
                  ? <b>acknowledged in this session (demo)</b>
                  : <button className="btn" style={{ padding: '2px 8px', fontSize: 13 }} onClick={() => setAcks({ ...acks, [p.anomaly_id]: true })}>Acknowledge (demo)</button>}
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export function Verification({ meta, run }) {
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const v = result || meta.verification
  async function reverify() {
    setBusy(true)
    try {
      const res = await fetch(`/api/runs/${run}/verify`, { method: 'POST' })
      const d = await res.json()
      setResult(res.ok ? d : { valid: false, error: d.detail })
    } finally { setBusy(false) }
  }
  return (
    <div className="panel">
      <h2>Evidence integrity</h2>
      {v.valid
        ? <div className="verified">✓ Verified · {v.checks.length} of {v.checks.length} checks passed{result ? ` just now in ${v.seconds}s` : ''}</div>
        : <div className="error">✗ {v.error}</div>}
      <p className="hint" style={{ marginTop: 6 }}>Source <code>{v.source || meta.evidence_source}</code></p>
      {v.checks && <ul className="checks">{v.checks.map((c) => <li key={c.check}><span className="ok">✓</span> {c.check}</li>)}</ul>}
      <button className="btn" style={{ marginTop: 12 }} onClick={reverify} disabled={busy}>{busy ? 'Checking…' : 'Re-verify now from the evidence bucket'}</button>
    </div>
  )
}

/* ---------- Assistant ---------- */

const SUGGESTIONS = {
  motor: ['Why is the motor flagged?', 'What does the gap chart show right now?', 'Is the evidence intact?'],
  system: ['Why is the system twin flagged?', 'Was the recalibrated twin tested on data the owner never saw?',
    'Draft a short compliance summary up to now.'],
}

export function Assistant({ run, tick, showSystem }) {
  const [turns, setTurns] = useState([])
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  async function send(question) {
    if (!question.trim() || busy) return
    setBusy(true); setErr(null)
    const history = turns.slice(-6).flatMap((t) => [{ role: 'user', text: t.q }, { role: 'assistant', text: t.a.answer }])
    try {
      const res = await fetch(`/api/runs/${run}/ask`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tick, question, history, motor_only: !showSystem }),
      })
      const d = await res.json()
      if (!res.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'the question could not be sent')
      setTurns((t) => [...t, { q: question, a: d }]); setQ('')
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="panel section">
      <h2>Ask about the evidence</h2>
      <p className="hint">Gemini answers only from the evidence up to tick {tick}{showSystem ? '' : ', motor only'}, using read-only lookups listed under each answer. It never makes or changes an assurance decision, and answers are not recorded as evidence.</p>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
        {SUGGESTIONS[showSystem ? 'system' : 'motor'].map((s) => (
          <button key={s} className="btn" onClick={() => send(s)} disabled={busy}>{s}</button>
        ))}
      </div>
      <div className="feed" style={{ maxHeight: 520, marginBottom: 12 }}>
        {turns.map((t, i) => (
          <div key={i} style={{ display: 'grid', gap: 6 }}>
            <div style={{ fontWeight: 700, fontSize: 17 }}>{t.q}</div>
            <div className="ai-card">
              <div className="ai-label">AI assistant · evidence up to tick {t.a.tick}</div>
              <div className="body" style={{ whiteSpace: 'pre-wrap', fontSize: 16, color: 'var(--ink)' }}>{t.a.answer}</div>
              <div className="foot">Grounded in: {t.a.tool_calls.map((c) => c.name.replace('get_', '').replaceAll('_', ' ')).join(', ') || 'no lookups'} · {t.a.model_id}</div>
            </div>
          </div>
        ))}
        {busy && <div className="hint">Looking through the evidence…</div>}
      </div>
      {err && <div className="error" style={{ marginBottom: 8 }}>{err}</div>}
      <form style={{ display: 'flex', gap: 8 }} onSubmit={(e) => { e.preventDefault(); send(q) }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} maxLength={800} placeholder="Ask a question about what you see…"
          style={{ flex: 1, font: 'inherit', padding: '10px 12px', border: '1px solid #cbd5e1', borderRadius: 8 }} />
        <button className="btn primary" disabled={busy || !q.trim()}>Ask</button>
      </form>
    </div>
  )
}

/* ---------- Semi-autonomous adjustment ---------- */

export function Adjustment({ state, view, meta }) {
  const steps = Object.fromEntries(state.adjustment.map((e) => [e.entry_type, e.payload]))
  const rec = steps.adjustment_recommended
  const refused = steps.adjustment_refused
  if (!rec && !refused) return null
  const appr = steps.adjustment_approval
  const exe = steps.adjustment_executed
  const post = steps.adjustment_post_state_check
  const r = rec?.recommendation
  const obj = rec?.objective
  const Mark = ({ ok }) => <span className={`mark ${ok ? 'ok' : 'bad'}`}>{ok ? '✓' : '✗'}</span>
  return (
    <div className="panel section">
      <h2>Semi-autonomous adjustment · {twinName(rec?.twin_id || refused.twin_id)}</h2>
      {rec && <p className="hint">Goal: {obj.description.toLowerCase()} ({fmtNum(obj.assured_range[0], 0)} rpm or more). The twin recommends; a named human approves; it is executed once; the platform checks the result.</p>}
      {rec && (
        <div className="grid-3" style={{ marginBottom: 14 }}>
          <div><div className="hint" style={{ margin: 0 }}>Recommended {r.control_channel === 'volt' ? 'supply voltage' : r.control_channel}</div>
            <div className="figure">{fmtNum(r.from, 1)} → {fmtNum(r.to, 1)} V</div>
            <div className="hint" style={{ margin: 0 }}>by twin {r.twin_version} under {rec.assurance_id}</div></div>
          <div><div className="hint" style={{ margin: 0 }}>Predicted compressor drive speed</div>
            <div className="figure">{fmtNum(rec.predicted_objective_value, 1)} rpm</div>
            <div className={rec.predicted_margin_above_objective > 0 ? 'ok' : 'bad'} style={{ fontWeight: 800, fontSize: 18 }}>
              {rec.predicted_margin_above_objective > 0 ? '+' : ''}{fmtNum(rec.predicted_margin_above_objective, 1)} rpm above the {fmtNum(obj.assured_range[0], 0)} minimum</div></div>
          <div><div className="hint" style={{ margin: 0 }}>Outcome after execution</div>
            {post ? <>
              <div className={`figure ${post.objective.met ? 'ok' : 'bad'}`}>{post.objective.ticks_in_range} of {post.objective.ticks_checked} ticks in range</div>
              <div className="hint" style={{ margin: 0 }}>lowest {fmtNum(post.objective.min_value, 1)} rpm (+{fmtNum(post.objective.min_value - obj.assured_range[0], 1)})</div>
            </> : <div className="hint" style={{ fontSize: 18 }}>{exe ? 'checking…' : 'not yet executed'}</div>}</div>
        </div>
      )}
      {rec && <MarginChart rec={rec} post={post} exe={exe} view={view} meta={meta} />}
      <ul className="steps">
        {rec && <li><Mark ok={rec.pre_state_input_range_check.passed} /> Pre-state check at tick {rec.tick}: every motor input inside its assured range; twin mode <b>{rec.twin_mode.replace('_', '-')}</b>, status assured</li>}
        {rec && <li><Mark ok={rec.setpoint_within_assured_range.passed} /> Recommended setpoint {fmtNum(r.to, 1)} V is inside the assured range {rec.setpoint_within_assured_range.assured_range.join('–')} V
          {r.predicted_to_meet_margin ? '' : ` · the twin owner's preferred 2% margin is not reached; the ${fmtNum(obj.assured_range[0], 0)} rpm minimum is`}</li>}
        {appr && <li><Mark ok={appr.decision === 'approve'} /> {appr.decision === 'approve' ? 'Approved' : 'Declined'} by <b>{appr.approver}</b> at tick {appr.tick} (human approval, recorded in the ledger)</li>}
        {exe && <li><Mark ok /> Executed once at tick {exe.tick}; the system then returns to passive monitoring</li>}
        {post && <li><Mark ok={post.sim2real_passed} /> Sim2Real, ticks {post.check_ticks.join('–')}: reality {post.sim2real_passed ? 'matched' : 'did not match'} the predicted end-state ({Object.entries(post.sim2real).map(([c, d]) => `${c} within ${fmtNum(d.max_gap_pct, 1)}%`).join(', ')}; tolerance 5%)</li>}
        {post && <li><Mark ok={post.objective.met} /> Objective: compressor drive speed back in its assured range on {post.objective.ticks_in_range} of {post.objective.ticks_checked} ticks</li>}
        {post && <li><span className="mark warn">•</span> Status is sticky: the compressor and system twin stay flagged until re-assured</li>}
        {refused && <li><Mark ok={false} /> Refused at tick {refused.tick}: {refused.reason}</li>}
      </ul>
    </div>
  )
}

// A zoomed view of the objective channel around the episode, so a thin margin is readable.
function MarginChart({ rec, post, exe, view, meta }) {
  const floor = rec.objective.assured_range[0]
  const [twinType, channel] = [rec.objective.twin_type, rec.objective.channel]
  const twinId = `${twinType}-op-001`
  const x0 = Math.max(0, rec.tick - 6)
  const points = view.readings.filter((r) => r.twin_id === twinId && r.channel_id === channel && r.tick >= x0)
    .map((r) => [r.tick, r.physical_value])
  const vlines = [{ x: rec.tick, label: `Recommended @${rec.tick}`, color: '#1a73e8' }]
  if (exe) vlines.push({ x: exe.tick, label: `Executed @${exe.tick}`, color: '#0b57d0' })
  const shade = post ? Array.from({ length: post.check_ticks[1] - post.check_ticks[0] + 1 }, (_, i) => post.check_ticks[0] + i) : []
  return (
    <div className="chart-card" style={{ margin: '4px 0 12px' }}>
      <h3>Zoomed: compressor drive speed around the adjustment</h3>
      <div className="legend">
        <span><span className="key" style={{ borderTopColor: '#111827' }} />Measured rpm</span>
        <span><span className="key dashed" style={{ borderTopColor: '#1a73e8' }} />Twin's predicted end-state</span>
        <span><span className="key dashed" style={{ borderTopColor: '#137333' }} />Assured minimum</span>
        {post && <span>Shaded = post-state check window</span>}
      </div>
      <Chart W={1400} H={300} xMin={x0} xMax={meta.ticks - 1} yMin={floor - 80} yMax={floor + 70} shade={shade} vlines={vlines}
        cursor={view.state.tick}
        hlines={[
          { y: floor, label: `Assured minimum ${fmtNum(floor, 0)} rpm`, color: '#137333' },
          { y: rec.predicted_objective_value, x0: rec.tick, left: true, color: '#1a73e8',
            label: `Predicted ${fmtNum(rec.predicted_objective_value, 1)} rpm (+${fmtNum(rec.predicted_margin_above_objective, 1)})` },
        ]}
        series={[{ label: 'measured', color: '#111827', points }]} />
    </div>
  )
}
