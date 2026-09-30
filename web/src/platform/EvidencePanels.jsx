// Evidence panels ported from the original dashboard (web/src/panels.jsx) into the
// platform's design. Same content and behaviour; twin names and units come from the
// project and the evidence instead of oil & gas constants.

import { useState } from 'react'
import { Check, RefreshCw, ShieldCheck, Sparkles, X } from 'lucide-react'
import { TraceChart } from './components.jsx'
import { CAUSES, anomalyKind, anomalyLabel, short, summarize } from './evidenceText.js'
import { unitLabel } from './api.js'
import { fmt } from './format.js'

const Mark = ({ ok, warn }) => (
  <span className={`step-mark ${warn ? 'warn' : ok ? 'done' : 'fail'}`}>{warn ? '•' : ok ? <Check size={11} /> : <X size={11} />}</span>
)

/* ---------- Recalibration (Real2Sim) ---------- */

export function Recalibration({ state, who, showSystem }) {
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
  return (
    <div className="panel panel-pad" style={{ display: 'grid', gap: 14, alignContent: 'start' }}>
      <div><div className="label" style={{ color: 'var(--orange-bright)' }}>Recalibration · Real2Sim</div>
        <h3 className="h3" style={{ marginTop: 6 }}>{who(req.twin_id)}</h3></div>
      <p className="muted" style={{ margin: 0, fontSize: 12 }}>Requested at tick {req.at_tick} while {req.status}. Flagged-period data (ticks {w0}–{w1}) is split by time, not at random.</p>
      <div className="splitbar">
        <div className="owner" style={{ flex: ownerTicks }}>Released to twin owner · ticks {split.released_to_owner.join('–')}</div>
        <div className="held" style={{ flex: heldTicks }}>Held out · ticks {split.held_out.join('–')}</div>
      </div>
      <ul className="step-list">
        {sealed && <li><Mark ok /><span>Both parts sealed before release: <code>{short(sealed.released_part.readings_sha256)}</code> and <code>{short(sealed.held_out_part.readings_sha256)}</code></span></li>}
        {rec.recalibration_data_released && <li><Mark ok /><span>Earlier part released to the twin owner. Held-out part released: <b>no</b></span></li>}
        {sub && <li><Mark ok /><span>Owner submitted twin <b>{sub.twin_version}</b>: {sub.method}</span></li>}
        {hv && <li><Mark ok={hv.passed} /><span>Held-out validation <b>{hv.passed ? 'PASSED' : 'FAILED'}</b> on {hv.ticks_evaluated} held-out ticks the owner never saw</span></li>}
        {sup && <li><Mark ok /><span><code>{sup.old_assurance_id}</code> superseded by <code>{sup.new_assurance_id}</code>, effective tick {sup.effective_from_tick}. Prior evidence unchanged.</span></li>}
        {re && showSystem && <li><Mark ok={re.result === 'reassured'} /><span>System twin {re.result === 'reassured' ? 're-assured' : <>not re-assured: blocked by <b>{re.blocked_by.map((b) => `${who(b.constituent)} (${b.reasons.map((r) => CAUSES[r.cause] + (r.channel_id ? ` · ${r.channel_id}` : '')).join('; ')})`).join(', ')}</b></>}</span></li>}
      </ul>
      {hv && (
        <div className="table-wrap night-table">
          <table className="grid" style={{ minWidth: 420 }}>
            <thead><tr><th>Held-out channel</th><th>Ticks</th><th>Worst gap</th><th>Tolerance</th><th>Result</th></tr></thead>
            <tbody>
              {Object.entries(hv.per_channel).map(([ch, d]) => (
                <tr key={ch}>
                  <td><b>{ch}</b></td>
                  <td className="num">{d.evaluated}</td>
                  <td className="num"><b style={{ color: d.over_tolerance ? 'var(--nullified)' : 'var(--assured)' }}>{fmt(d.max_gap_pct, 1)}%</b></td>
                  <td className="num">{d.tolerance_pct}%</td>
                  <td><span className={`pill ${d.over_tolerance ? 'pill-nullified' : 'pill-assured'}`}>{d.over_tolerance ? `${d.over_tolerance} over` : 'within'}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/* ---------- Semi-autonomous adjustment (Sim2Real) ---------- */

export function Adjustment({ state, view, meta, project, who, tick }) {
  const steps = Object.fromEntries(state.adjustment.map((e) => [e.entry_type, e.payload]))
  const rec = steps.adjustment_recommended
  const refused = steps.adjustment_refused
  if (!rec && !refused) return null
  const appr = steps.adjustment_approval
  const exe = steps.adjustment_executed
  const post = steps.adjustment_post_state_check
  const r = rec?.recommendation
  const obj = rec?.objective
  const twinId = rec?.twin_id || refused.twin_id
  const control = rec && meta.twins[twinId].channels.find((c) => c.channel_id === r.control_channel)
  const objTwin = rec && project.twins.find((t) => t.key === obj.twin_type)
  const objChannel = rec && meta.twins[objTwin.operational_twin_id].channels.find((c) => c.channel_id === obj.channel)
  const cu = control && unitLabel(control.unit)
  const ou = objChannel && unitLabel(objChannel.unit)
  return (
    <div className="panel panel-pad" style={{ display: 'grid', gap: 14, alignContent: 'start' }}>
      <div><div className="label" style={{ color: 'var(--orange-bright)' }}>Semi-autonomous adjustment · Sim2Real</div>
        <h3 className="h3" style={{ marginTop: 6 }}>{who(twinId)}{rec && `: ${control.name.toLowerCase()}`}</h3></div>
      {rec && <p className="muted" style={{ margin: 0, fontSize: 12 }}>Goal: {obj.description.toLowerCase()} ({fmt(obj.assured_range[0], 0)} {ou} or more). The twin recommends; a named human approves; it is executed once; the platform checks the result.</p>}
      {rec && (
        <div className="figures">
          <div><div className="label">Recommended {control.name.toLowerCase()}</div>
            <div className="figure">{fmt(r.from, 1)} → {fmt(r.to, 1)} {cu}</div>
            <div className="small muted">by twin {r.twin_version} under {rec.assurance_id}</div></div>
          <div><div className="label">Predicted {who(objTwin.operational_twin_id).toLowerCase()} {objChannel.name.toLowerCase()}</div>
            <div className="figure">{fmt(rec.predicted_objective_value, 1)} {ou}</div>
            <div className="small" style={{ fontWeight: 800, color: rec.predicted_margin_above_objective > 0 ? 'var(--assured-light)' : 'var(--nullified-light)' }}>
              {rec.predicted_margin_above_objective > 0 ? '+' : ''}{fmt(rec.predicted_margin_above_objective, 1)} {ou} above the {fmt(obj.assured_range[0], 0)} minimum</div></div>
          <div><div className="label">Outcome after execution</div>
            {post ? <>
              <div className="figure" style={{ color: post.objective.met ? 'var(--assured-light)' : 'var(--nullified-light)' }}>{post.objective.ticks_in_range} of {post.objective.ticks_checked} ticks in range</div>
              <div className="small muted">lowest {fmt(post.objective.min_value, 1)} {ou} (+{fmt(post.objective.min_value - obj.assured_range[0], 1)})</div>
            </> : <div className="small muted" style={{ fontSize: 14 }}>{exe ? 'checking…' : 'not yet executed'}</div>}</div>
        </div>
      )}
      {rec && <MarginChart rec={rec} post={post} exe={exe} view={view} meta={meta} objId={objTwin.operational_twin_id} unit={ou} tick={tick}
        title={`${who(objTwin.operational_twin_id).toLowerCase()} ${objChannel.name.toLowerCase()}`} />}
      <ul className="step-list">
        {rec && <li><Mark ok={rec.pre_state_input_range_check.passed} /><span>Pre-state check at tick {rec.tick}: every {who(twinId).toLowerCase()} input inside its assured range; twin mode <b>{rec.twin_mode.replace('_', '-')}</b>, status assured</span></li>}
        {rec && <li><Mark ok={rec.setpoint_within_assured_range.passed} /><span>Recommended setpoint {fmt(r.to, 1)} {cu} is inside the assured range {rec.setpoint_within_assured_range.assured_range.join('–')} {cu}
          {r.predicted_to_meet_margin ? '' : ` · the twin owner's preferred margin (${r.method}) is not reached; the ${fmt(obj.assured_range[0], 0)} ${ou} minimum is`}</span></li>}
        {appr && <li><Mark ok={appr.decision === 'approve'} /><span>{appr.decision === 'approve' ? 'Approved' : 'Declined'} by <b>{appr.approver}</b> at tick {appr.tick} (human approval, recorded in the ledger)</span></li>}
        {exe && <li><Mark ok /><span>Executed once at tick {exe.tick}; the system then returns to passive monitoring</span></li>}
        {post && <li><Mark ok={post.sim2real_passed} /><span>Sim2Real, ticks {post.check_ticks.join('–')}: reality {post.sim2real_passed ? 'matched' : 'did not match'} the predicted end-state ({Object.entries(post.sim2real).map(([c, d]) => `${c} within ${fmt(d.max_gap_pct, 1)}%`).join(', ')}; tolerance {Object.values(post.sim2real)[0]?.tolerance_pct}%)</span></li>}
        {post && <li><Mark ok={post.objective.met} /><span>Objective: {who(objTwin.operational_twin_id).toLowerCase()} {objChannel.name.toLowerCase()} back in its assured range on {post.objective.ticks_in_range} of {post.objective.ticks_checked} ticks</span></li>}
        {post && <li><Mark warn /><span>Status is sticky: twins that are flagged stay flagged until re-assured</span></li>}
        {refused && <li><Mark ok={false} /><span>Refused at tick {refused.tick}: {refused.reason}</span></li>}
      </ul>
    </div>
  )
}

// A zoomed view of the objective channel around the episode, so a thin margin is readable.
function MarginChart({ rec, post, exe, view, meta, objId, unit, tick, title }) {
  const floor = rec.objective.assured_range[0]
  const x0 = Math.max(0, rec.tick - 6)
  const points = view.readings.filter((r) => r.twin_id === objId && r.channel_id === rec.objective.channel && r.tick >= x0)
    .map((r) => [r.tick, r.physical_value])
  const markers = [{ x: rec.tick, label: `Recommended @${rec.tick}`, color: 'var(--orange)' }]
  if (exe) markers.push({ x: exe.tick, label: `Executed @${exe.tick}`, color: 'var(--orange)' })
  const shade = post ? Array.from({ length: post.check_ticks[1] - post.check_ticks[0] + 1 }, (_, i) => post.check_ticks[0] + i) : []
  return (
    <div className="chart-light">
      <div className="h4">Zoomed: {title} around the adjustment</div>
      <div className="legend" style={{ margin: '4px 0 2px' }}>
        <span><i className="key" style={{ borderTopColor: 'var(--ink)' }} />Measured {unit}</span>
        <span><i className="key dashed" style={{ borderTopColor: 'var(--orange)' }} />Twin's predicted end-state</span>
        <span><i className="key dashed" style={{ borderTopColor: 'var(--assured)' }} />Assured minimum</span>
        {post && <span>Shaded = post-state check window</span>}
      </div>
      <TraceChart W={640} H={190} xMin={x0} xMax={meta.ticks - 1} yMin={floor - 80} yMax={floor + 70} shade={shade} markers={markers} cursor={tick}
        hlines={[
          { y: floor, label: `Assured minimum ${fmt(floor, 0)} ${unit}`, color: 'var(--assured)' },
          { y: rec.predicted_objective_value, x0: rec.tick, color: 'var(--orange)', label: `Predicted ${fmt(rec.predicted_objective_value, 1)} ${unit} (+${fmt(rec.predicted_margin_above_objective, 1)})` },
        ]}
        series={[{ color: 'var(--ink)', points }]} />
    </div>
  )
}

/* ---------- Evidence feeds ---------- */

export function Ledger({ entries, head, total, who }) {
  const [open, setOpen] = useState(null)
  const shown = [...entries].reverse().slice(0, 30)
  return (
    <div className="panel">
      <div className="panel-head"><h2 className="label">Evidence ledger</h2><span className="small muted">{total} entries · head <code>{short(head, 12)}</code></span></div>
      <p className="hint" style={{ padding: '10px 18px 0' }}>Each entry is sealed with SHA-256 and linked to the one before. Select one to see its payload.</p>
      <ul className="rule-list panel-pad scroll-list" style={{ paddingBlock: 4 }}>
        {shown.map((e) => (
          <li key={e.seq} className="ledger-row" onClick={() => setOpen(open === e.seq ? null : e.seq)} style={{ cursor: 'pointer' }}>
            <span className="seq">#{e.seq}</span>
            <span>{summarize(e, who)}<br /><code>tick {e.tick} · {short(e.entry_hash, 12)} ← {short(e.prev_hash, 8)}</code>
              {open === e.seq && <pre className="payload">{JSON.stringify(e.payload, null, 2)}</pre>}</span>
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
      <div className="panel-head"><h2 className="label" style={{ display: 'flex', gap: 6, alignItems: 'center' }}><Sparkles size={13} color="var(--orange)" /> AI explanations</h2></div>
      <p className="hint" style={{ padding: '10px 18px 0' }}>Generated by Gemini from the evidence alone. Supplementary: never used in any assurance decision. Kept in a separate ledger linked to the entry each one explains.</p>
      <ul className="rule-list panel-pad scroll-list" style={{ paddingBlock: 4 }}>
        {shown.length === 0 && <li className="hint">None yet at this tick.</li>}
        {shown.map((e) => {
          const a = e.payload
          const r = a.response || {}
          return (
            <li key={e.seq} style={{ display: 'grid', gap: 5 }}>
              <span className="label" style={{ color: 'var(--orange)' }}>Supplementary AI · {a.artifact_type.replaceAll('_', ' ')}</span>
              <b style={{ fontSize: 13 }}>{r.headline}</b>
              <span style={{ fontSize: 12, lineHeight: 1.65 }}>{r.explanation}</span>
              <span className="small muted">Suggested: <b>{(r.suggested_classification || '').replaceAll('_', ' ')}</b> ({r.confidence} confidence) · explains ledger #{a.explains_ledger_seq} <code>{short(a.explains_entry_hash)}</code> · {a.model_id}</span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export function Anomalies({ ledger, who }) {
  const [acks, setAcks] = useState({})
  const closed = new Set(ledger.filter((e) => e.entry_type === 'anomaly_closed').map((e) => e.payload.anomaly_id))
  const opened = ledger.filter((e) => e.entry_type === 'anomaly_opened').reverse()
  return (
    <div className="panel">
      <div className="panel-head"><h2 className="label">Anomalies</h2><span className="small muted">{opened.filter((e) => !closed.has(e.payload.anomaly_id)).length} open</span></div>
      <p className="hint" style={{ padding: '10px 18px 0' }}>Acknowledging here is a demo action kept in this browser session only; it is never written to the evidence.</p>
      <ul className="rule-list panel-pad scroll-list" style={{ paddingBlock: 4 }}>
        {opened.length === 0 && <li className="hint">None yet at this tick.</li>}
        {opened.map((e) => {
          const p = e.payload
          const isOpen = !closed.has(p.anomaly_id)
          return (
            <li key={p.anomaly_id} style={{ display: 'grid', gap: 5 }}>
              <span style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                <span><span className={`badge badge-${anomalyKind(p)}`}>{anomalyLabel(p)}</span> <b style={{ fontSize: 12 }}>{who(p.twin_id)} · {p.channel_id}</b></span>
                <span className="small muted">tick {p.tick} · {isOpen ? 'open' : 'closed'}</span>
              </span>
              <span className="small muted">
                {p.gap_pct != null && <>gap {fmt(p.gap_pct, 2)}% · </>}severity {p.severity} · ledger #{e.seq} ·{' '}
                {acks[p.anomaly_id]
                  ? <b>acknowledged in this session (demo)</b>
                  : <button className="button button-ghost button-small" style={{ minHeight: 24 }} onClick={() => setAcks({ ...acks, [p.anomaly_id]: true })}>Acknowledge (demo)</button>}
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export function Integrity({ meta, run }) {
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
      <div className="panel-head"><h2 className="label" style={{ display: 'flex', gap: 6, alignItems: 'center' }}><ShieldCheck size={13} color="var(--orange)" /> Evidence integrity</h2></div>
      <div className="panel-pad" style={{ display: 'grid', gap: 10 }}>
        {v.valid
          ? <div className="verified"><Check size={15} /> Verified · {v.checks.length} of {v.checks.length} checks passed{result ? ` just now in ${v.seconds}s` : ''}</div>
          : <div className="callout callout-warn"><b>Not verified.</b> {v.error}</div>}
        <span className="small muted">Source <code>{v.source || meta.evidence_source}</code></span>
        {v.checks && <ul className="checklist">{v.checks.map((c) => <li key={c.check}><Check size={14} className="ok" /> {c.check}</li>)}</ul>}
        <div><button className="button button-ghost button-small" onClick={reverify} disabled={busy}><RefreshCw size={13} /> {busy ? 'Checking…' : 'Re-verify now from the evidence store'}</button></div>
      </div>
    </div>
  )
}

/* ---------- Assistant ---------- */

export function Assistant({ run, tick, showSystem, soloNames }) {
  const [turns, setTurns] = useState([])
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const suggestions = showSystem
    ? ['Why is the system twin flagged?', 'Was the recalibrated twin tested on data the owner never saw?', 'Draft a short compliance summary up to now.']
    : [`Why is the ${soloNames.toLowerCase()} flagged?`, 'What does the gap chart show right now?', 'Is the evidence intact?']

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
    <div className="panel">
      <div className="panel-head"><h2 className="label" style={{ display: 'flex', gap: 6, alignItems: 'center' }}><Sparkles size={13} color="var(--orange)" /> Evidence assistant</h2></div>
      <div className="panel-pad" style={{ display: 'grid', gap: 12 }}>
        <p className="hint">Gemini answers only from the evidence up to tick {tick}{showSystem ? '' : `, ${soloNames.toLowerCase()} only`}, using read-only lookups listed under each answer. It never makes or changes an assurance decision, and answers are not recorded as evidence.</p>
        <div className="assistant-q">
          {suggestions.map((s) => <button key={s} className="chip" style={{ cursor: 'pointer' }} onClick={() => send(s)} disabled={busy}>{s}</button>)}
        </div>
        {turns.length > 0 && (
          <div className="scroll-list" style={{ display: 'grid', gap: 12, maxHeight: 460 }}>
            {turns.map((t, i) => (
              <div key={i} style={{ display: 'grid', gap: 6 }}>
                <b style={{ fontSize: 13 }}>{t.q}</b>
                <div className="assistant-answer">
                  <div className="label" style={{ color: 'var(--orange)', marginBottom: 4 }}>AI assistant · evidence up to tick {t.a.tick}</div>
                  <div style={{ whiteSpace: 'pre-wrap' }}>{t.a.answer}</div>
                  <div className="small muted" style={{ marginTop: 6 }}>Grounded in: {t.a.tool_calls.map((c) => c.name.replace('get_', '').replaceAll('_', ' ')).join(', ') || 'no lookups'} · {t.a.model_id}</div>
                </div>
              </div>
            ))}
          </div>
        )}
        {busy && <div className="hint">Looking through the evidence…</div>}
        {err && <div className="callout callout-warn">{err}</div>}
        <form style={{ display: 'flex', gap: 8 }} onSubmit={(e) => { e.preventDefault(); send(q) }}>
          <input id="ask" className="input compact" value={q} onChange={(e) => setQ(e.target.value)} maxLength={800} placeholder="Ask about what you see…" />
          <button className="button button-dark button-small" disabled={busy || !q.trim()}>Ask</button>
        </form>
      </div>
    </div>
  )
}
