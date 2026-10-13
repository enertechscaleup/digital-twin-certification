// Evidence panels ported from the original dashboard (web/src/panels.jsx) into the
// platform's design. Same content and behaviour; twin names and units come from the
// project and the evidence instead of oil & gas constants.

import { useEffect, useRef, useState } from 'react'
import { ArrowDown, Check, Fingerprint, GitBranch, Link2, Minus, RefreshCw, ShieldCheck, Sparkles, X } from 'lucide-react'
import { TraceChart } from './components.jsx'
import { CAUSES, anomalyKind, anomalyLabel, citedVersion, short, summarize, versionTag } from './evidenceText.js'
import { unitLabel } from './api.js'
import { digitsFor, fmt } from './format.js'

// TwinEvidence's seal: the mark of evidence captured and recorded (the same mark the demo
// video puts on the governance layer and the evidence store).
const SEAL_RING = Array.from({ length: 16 }, (_, i) => {
  const a = (i / 16) * Math.PI * 2
  const r = i % 2 ? 10.2 : 11.6
  return `${12 + r * Math.cos(a)},${12 + r * Math.sin(a)}`
}).join(' ')
export const Seal = ({ size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden style={{ flex: 'none' }}>
    <polygon points={SEAL_RING} fill="none" stroke="var(--orange)" strokeWidth="1.8" strokeLinejoin="round" />
    <path d="M7.4 12.3 L10.6 15.4 L16.8 8.9" fill="none" stroke="var(--orange)" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

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
        {rec.recalibration_submitted?.candidate_ref && <li><Mark ok /><span>Registered on submission as a new version of the same twin: <code>{versionTag(rec.recalibration_submitted.candidate_ref)}</code>, derived from <code>{versionTag(rec.recalibration_submitted.previous_ref)}</code></span></li>}
        {hv && <li><Mark ok={hv.passed} /><span>Held-out validation <b>{hv.passed ? 'PASSED' : 'FAILED'}</b> on {hv.ticks_evaluated} held-out ticks the owner never saw</span></li>}
        {sup && <li><Mark ok /><span><code>{sup.old_assurance_id}</code> superseded by <code>{sup.new_assurance_id}</code>, effective tick {sup.effective_from_tick}. Prior evidence unchanged.</span></li>}
        {re?.system_ref && showSystem && <li><Mark ok /><span>System twin's content changed with it: now version <b>{re.system_ref.version}</b> (<code>{short(re.system_ref.fingerprint)}</code>), composed of {re.constituent_refs.map((c) => `${who(c.twin_id)} v${c.version}`).join(' + ')}. Fresh composition record.</span></li>}
        {re?.composition_test && showSystem && <li><Mark ok={re.composition_test.passed} /><span>Twins run together again ({re.composition_test.test_id}): interface check <b>{re.composition_test.interface_passed ? 'passed' : 'failed'}</b>, interaction check <b>{re.composition_test.interaction_passed ? 'passed' : 'failed'}</b></span></li>}
        {re && showSystem && <li><Mark ok={re.result === 'reassured'} /><span>System twin {re.result === 'reassured' ? 're-assured' : <>not re-assured: blocked by <b>{[
          ...re.blocked_by.map((b) => `${who(b.constituent)} (${b.reasons.map((r) => CAUSES[r.cause] + (r.channel_id ? ` · ${r.channel_id}` : '')).join('; ')})`),
          ...(re.composition_test && !re.composition_test.passed ? [`its joint test ${re.composition_test.test_id}`] : []),
        ].join(', ')}</b></>}</span></li>}
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
  // Decimals follow each channel's own range: the motor's supply voltage and the compressor's
  // drive speed show as before; a robot's speed setpoint in m/s needs two decimals.
  const cd = control ? digitsFor(control.envelope) : 1
  const od = objChannel ? digitsFor(objChannel.envelope) + 1 : 1
  return (
    <div className="panel panel-pad" style={{ display: 'grid', gap: 14, alignContent: 'start' }}>
      <div><div className="label" style={{ color: 'var(--orange-bright)' }}>Semi-autonomous adjustment · Sim2Real</div>
        <h3 className="h3" style={{ marginTop: 6 }}>{who(twinId)}{rec && `: ${control.name.toLowerCase()}`}</h3></div>
      {rec && <p className="muted" style={{ margin: 0, fontSize: 12 }}>Goal: {obj.description.toLowerCase()} ({fmt(obj.assured_range[0], od - 1)} {ou} or more). The twin recommends; a named human approves; it is executed once; the platform checks the result.</p>}
      {rec && (
        <div className="figures">
          <div><div className="label">Recommended {control.name.toLowerCase()}</div>
            <div className="figure">{fmt(r.from, cd)} → {fmt(r.to, cd)} {cu}</div>
            <div className="small muted">by twin {r.twin_version} under {rec.assurance_id}</div></div>
          <div><div className="label">Predicted {who(objTwin.operational_twin_id).toLowerCase()} {objChannel.name.toLowerCase()}</div>
            <div className="figure">{fmt(rec.predicted_objective_value, od)} {ou}</div>
            <div className="small" style={{ fontWeight: 800, color: rec.predicted_margin_above_objective > 0 ? 'var(--assured-light)' : 'var(--nullified-light)' }}>
              {rec.predicted_margin_above_objective > 0 ? '+' : ''}{fmt(rec.predicted_margin_above_objective, od)} {ou} above the {fmt(obj.assured_range[0], od - 1)} minimum</div></div>
          <div><div className="label">Outcome after execution</div>
            {post ? <>
              <div className="figure" style={{ color: post.objective.met ? 'var(--assured-light)' : 'var(--nullified-light)' }}>{post.objective.ticks_in_range} of {post.objective.ticks_checked} ticks in range</div>
              <div className="small muted">lowest {fmt(post.objective.min_value, od)} {ou} (+{fmt(post.objective.min_value - obj.assured_range[0], od)})</div>
            </> : <div className="small muted" style={{ fontSize: 14 }}>{exe ? 'checking…' : 'not yet executed'}</div>}</div>
        </div>
      )}
      {rec && <MarginChart rec={rec} post={post} exe={exe} view={view} meta={meta} objId={objTwin.operational_twin_id} unit={ou} tick={tick} od={od}
        span={objChannel.envelope[1] - objChannel.envelope[0]}
        title={`${who(objTwin.operational_twin_id).toLowerCase()} ${objChannel.name.toLowerCase()}`} />}
      <ul className="step-list">
        {rec && <li><Mark ok={rec.pre_state_input_range_check.passed} /><span>Pre-state check at tick {rec.tick}: every {who(twinId).toLowerCase()} input inside its assured range; twin mode <b>{rec.twin_mode.replace('_', '-')}</b>, status assured</span></li>}
        {rec && <li><Mark ok={rec.setpoint_within_assured_range.passed} /><span>Recommended setpoint {fmt(r.to, cd)} {cu} is inside the assured range {rec.setpoint_within_assured_range.assured_range.join('–')} {cu}
          {r.predicted_to_meet_margin ? '' : ` · the twin owner's preferred margin (${r.method}) is not reached; the ${fmt(obj.assured_range[0], od - 1)} ${ou} minimum is`}</span></li>}
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
function MarginChart({ rec, post, exe, view, meta, objId, unit, tick, title, od = 1, span = 350 }) {
  const floor = rec.objective.assured_range[0]
  // Zoom in proportion to the channel's range (the compressor's 350 rpm range gives -80/+70 rpm).
  const k = span / 350
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
      <TraceChart W={640} H={190} xMin={x0} xMax={meta.ticks - 1} yMin={floor - 80 * k} yMax={floor + 70 * k} digits={Math.max(0, od - 1)} shade={shade} markers={markers} cursor={tick}
        hlines={[
          { y: floor, label: `Assured minimum ${fmt(floor, od - 1)} ${unit}`, color: 'var(--assured)' },
          { y: rec.predicted_objective_value, x0: rec.tick, color: 'var(--orange)', label: `Predicted ${fmt(rec.predicted_objective_value, od)} ${unit} (+${fmt(rec.predicted_margin_above_objective, od)})` },
        ]}
        series={[{ color: 'var(--ink)', points }]} />
    </div>
  )
}

/* ---------- Evidence feeds ---------- */

/** Cited ledger entries as buttons that open the entry in the ledger. */
export function Cites({ cites, onCite }) {
  if (!cites?.length) return null
  return (
    <span className="cite-row">Cites {cites.map((c) => (
      <button key={c.ledger_seq} className="cite" onClick={(ev) => { ev.stopPropagation(); onCite?.(c.ledger_seq) }}
        title={`Ledger entry #${c.ledger_seq} · ${short(c.entry_hash, 16)}`}>#{c.ledger_seq}</button>))}</span>
  )
}

/** A sealed AI explanation shown with an entry: AI-written, supplementary, never core evidence. */
export function AiNote({ a, onCite }) {
  const r = a.response || {}
  return (
    <div className="ai-note" onClick={(ev) => ev.stopPropagation()}>
      <span className="label" style={{ color: 'var(--orange)', display: 'flex', gap: 5, alignItems: 'center' }}>
        <Sparkles size={11} /> AI-written · supplementary, not core evidence · {a.artifact_type.replaceAll('_', ' ')}</span>
      <b style={{ fontSize: 12.5 }}>{r.headline}</b>
      <span style={{ fontSize: 12, lineHeight: 1.6 }}>{r.explanation}</span>
      <span className="small muted">{a.model_id} · checked against the ledger before it was sealed · <Cites cites={a.cites} onCite={onCite} /></span>
    </div>
  )
}

export function Ledger({ entries, head, total, who, explanations = {}, focus = null, onCite }) {
  // The row opened by a click here, or the one a citation elsewhere points at: whichever came last.
  // ``focus.at`` counts citations followed; a click records how many had been followed by then.
  const [manual, setManual] = useState({ seq: null, seen: 0 })
  const listRef = useRef(null)
  const f = focus?.seq ?? null
  const open = focus && focus.at > manual.seen ? f : manual.seq
  const setOpen = (seq) => setManual({ seq, seen: focus?.at || 0 })
  useEffect(() => {
    if (f == null) return
    const row = listRef.current?.querySelector(`[data-seq="${f}"]`)
    if (row) { listRef.current.closest('.panel')?.scrollIntoView({ block: 'start', behavior: 'smooth' }); row.scrollIntoView({ block: 'nearest' }) }
  }, [focus, f])
  const reversed = [...entries].reverse()
  const at = f == null ? -1 : reversed.findIndex((e) => e.seq === f)
  const shown = reversed.slice(0, Math.max(30, at + 1))
  return (
    <div className="panel">
      <div className="panel-head"><h2 className="label" style={{ display: 'flex', gap: 6, alignItems: 'center' }}><Seal size={15} /> Evidence ledger</h2><span className="small muted">{total} entries · head <code>{short(head, 12)}</code></span></div>
      <p className="hint" style={{ padding: '10px 18px 0' }}>Each entry is sealed with SHA-256 and linked to the one before. Select one to see its payload.</p>
      <ul ref={listRef} className="rule-list panel-pad scroll-list" style={{ paddingBlock: 4 }}>
        {shown.map((e) => (
          <li key={e.seq} data-seq={e.seq} className={`ledger-row${f === e.seq ? ' is-focus' : ''}`} onClick={() => setOpen(open === e.seq ? null : e.seq)} style={{ cursor: 'pointer' }}>
            <span className="seq">#{e.seq}</span>
            <span>{summarize(e, who)}{explanations[e.seq] && <span className="ai-chip"><Sparkles size={10} /> AI</span>}<br /><code>tick {e.tick} · {short(e.entry_hash, 12)} ← {short(e.prev_hash, 8)}</code>
              {e.entry_type === 'twin_version_registered'
                ? <><br /><code className="cites">fingerprint {short(e.payload.twin.fingerprint, 16)}</code></>
                : e.payload.version_refs
                  ? <><br /><code className="cites">covers {e.payload.version_refs.map((r) => `${who(r.twin_id)} v${r.version}`).join(', ')}</code></>
                  : citedVersion(e.payload) && <><br /><code className="cites">cites {versionTag(citedVersion(e.payload), 12)}</code></>}
              {open === e.seq && (explanations[e.seq] || []).map((a) => <AiNote key={a.artifact_type} a={a} onCite={onCite} />)}
              {open === e.seq && <pre className="payload">{JSON.stringify(e.payload, null, 2)}</pre>}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function Explanations({ items, status, onCite }) {
  const shown = [...items].reverse()
  return (
    <div className="panel">
      <div className="panel-head"><h2 className="label" style={{ display: 'flex', gap: 6, alignItems: 'center' }}><Sparkles size={13} color="var(--orange)" /> AI explanations</h2></div>
      <p className="hint" style={{ padding: '10px 18px 0' }}>Generated by Gemini from the evidence alone. Supplementary: never used in any assurance decision. Kept in a separate ledger linked to the entry each one explains.</p>
      <ul className="rule-list panel-pad scroll-list" style={{ paddingBlock: 4 }}>
        {status?.status === 'unavailable'
          ? <li className="hint">No explanations: the AI service was unavailable when this run was explained. Everything else on this page is unaffected.</li>
          : shown.length === 0 && <li className="hint">None yet at this tick.</li>}
        {shown.map((e) => {
          const a = e.payload
          const r = a.response || {}
          return (
            <li key={e.seq} id={`ai-${a.explains_ledger_seq}-${a.artifact_type}`} style={{ display: 'grid', gap: 5 }}>
              <span className="label" style={{ color: 'var(--orange)' }}>Supplementary AI · {a.artifact_type.replaceAll('_', ' ')}</span>
              <b style={{ fontSize: 13 }}>{r.headline}</b>
              <span style={{ fontSize: 12, lineHeight: 1.65 }}>{r.explanation}</span>
              <span className="small muted">Suggested: <b>{(r.suggested_classification || '').replaceAll('_', ' ')}</b> ({r.confidence} confidence) · explains ledger {a.cites
                ? <button className="cite" onClick={() => onCite?.(a.explains_ledger_seq)}>#{a.explains_ledger_seq}</button> : <>#{a.explains_ledger_seq}</>} <code>{short(a.explains_entry_hash)}</code> · {a.model_id}</span>
              {a.cites && <span className="small muted"><Cites cites={a.cites} onCite={onCite} /></span>}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function AnomalyItem({ e, isOpen, who, acks, setAcks }) {
  const p = e.payload
  return (
    <li style={{ display: 'grid', gap: 5 }}>
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
}

export function Anomalies({ ledger, who, split = false }) {
  const [acks, setAcks] = useState({})
  const closed = new Set(ledger.filter((e) => e.entry_type === 'anomaly_closed').map((e) => e.payload.anomaly_id))
  const opened = ledger.filter((e) => e.entry_type === 'anomaly_opened').reverse()
  const item = (e) => <AnomalyItem key={e.payload.anomaly_id} e={e} isOpen={!closed.has(e.payload.anomaly_id)} who={who} acks={acks} setAcks={setAcks} />
  const dq = opened.filter((e) => e.payload.type === 'data_quality')
  const twin = opened.filter((e) => e.payload.type !== 'data_quality')
  return (
    <div className="panel">
      <div className="panel-head"><h2 className="label">Anomalies</h2><span className="small muted">{opened.filter((e) => !closed.has(e.payload.anomaly_id)).length} open</span></div>
      <p className="hint" style={{ padding: '10px 18px 0' }}>Acknowledging here is a demo action kept in this browser session only; it is never written to the evidence.</p>
      {split ? (
        <div className="scroll-list">
          <div className="sublabel">Sensor and data quality · a reading problem, not twin error</div>
          <ul className="rule-list panel-pad" style={{ paddingBlock: 4 }}>{dq.length ? dq.map(item) : <li className="hint">None yet at this tick.</li>}</ul>
          <div className="sublabel">Twin and reality · gaps beyond tolerance and inputs outside their assured range</div>
          <ul className="rule-list panel-pad" style={{ paddingBlock: 4 }}>{twin.length ? twin.map(item) : <li className="hint">None yet at this tick.</li>}</ul>
        </div>
      ) : (
        <ul className="rule-list panel-pad scroll-list" style={{ paddingBlock: 4 }}>
          {opened.length === 0 && <li className="hint">None yet at this tick.</li>}
          {opened.map(item)}
        </ul>
      )}
    </div>
  )
}

export function Integrity({ meta, run }) {
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const v = result || meta.verification
  const applicable = (v.checks || []).filter((c) => c.applicable !== false).length
  const notApplicable = (v.checks || []).length - applicable
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
          ? <div className="verified"><Check size={15} /> Verified · {applicable} of {applicable} checks passed{notApplicable ? ` · ${notApplicable} not applicable` : ''}{result ? ` just now in ${v.seconds}s` : ''}</div>
          : <div className="callout callout-warn"><b>Not verified.</b> {v.error}</div>}
        <span className="small muted">Source <code>{v.source || meta.evidence_source}</code></span>
        {v.checks && <ul className="checklist">{v.checks.map((c) => c.applicable === false
          ? <li key={c.check}><Minus size={14} className="na" /> <span>{c.check} · not applicable: <span className="muted">{c.detail}</span></span></li>
          : <li key={c.check}><Check size={14} className="ok" /> {c.check}</li>)}</ul>}
        <div><button className="button button-ghost button-small" onClick={reverify} disabled={busy}><RefreshCw size={13} /> {busy ? 'Checking…' : 'Re-verify now from the evidence store'}</button></div>
      </div>
    </div>
  )
}

/* ---------- Joint composition tests ---------- */

// Each joint run of the twins, as of the tick on screen: the interface check (does every
// upstream prediction land in the downstream twin's assured range?) and the interaction
// check (does the joint prediction hold against the combined test bench?), kept apart.
export function CompositionTests({ state, who }) {
  const tests = state.composition_tests.filter((t) => t.entry_type === 'composition_test')
  if (!tests.length) return null
  return (
    <div className="panel">
      <div className="panel-head"><h2 className="label" style={{ display: 'flex', gap: 6, alignItems: 'center' }}><Link2 size={13} color="var(--orange)" /> Composition · joint runs</h2>
        <span className="small muted">{tests.length} joint {tests.length === 1 ? 'run' : 'runs'}</span></div>
      <p className="hint" style={{ padding: '10px 18px 0' }}>Each twin's own evidence cannot show the twins still predict well together. So the platform runs them jointly through their owners' endpoints (simulated vendor endpoints in this prototype): each downstream twin is fed the upstream twin's prediction, never a measurement. Only what crosses the boundary is recorded.</p>
      <div className="joint-grid panel-pad">
        {tests.map(({ seq, payload: t }) => (
          <article key={seq} className={`joint ${t.passed ? 'is-pass' : 'is-fail'}`}>
            <div className="joint-head">
              <div><div className="label">{t.test_id} · {t.trigger}</div>
                <div className="small muted">system v{t.system_ref.version} = {t.constituent_refs.map((c) => `${who(c.twin_id)} v${c.version}`).join(' + ')} · {t.points} test points · {t.exchange.calls} exchanges sealed</div></div>
              <span className={`pill ${t.passed ? 'pill-assured' : 'pill-flagged'}`}>{t.passed ? 'passed' : 'failed'}</span>
            </div>
            <ul className="step-list">
              {t.interface.connections.map((c) => (
                <li key={c.from + c.to}><Mark ok={c.passed} /><span><b>Interface</b> {c.from} → {c.to}: predicted {fmt(c.predicted_range[0], 0)}–{fmt(c.predicted_range[1], 0)} {unitLabel(c.unit)} against assured {fmt(c.assured_range[0], 0)}–{fmt(c.assured_range[1], 0)} {unitLabel(c.unit)}
                  {c.passed ? ' · inside at every point' : <> · <b>outside at {c.points_outside} of {t.points} points</b></>}</span></li>
              ))}
              {Object.entries(t.interaction.per_channel).map(([k, c]) => (
                <li key={k}><Mark ok={c.passed} /><span><b>Interaction</b> {k}: joint prediction within {c.max_gap_pct == null ? '—' : `${fmt(c.max_gap_pct, 1)}%`} of the combined test bench (tolerance {c.tolerance_pct}%)
                  {t.interaction.not_evaluated_points ? ` · checked at the ${t.interaction.evaluated_points} points where every interface holds` : ''}</span></li>
              ))}
            </ul>
            <div className="small muted">Test fingerprint <code>{short(t.test_fingerprint, 12)}</code> · ledger #{seq}</div>
          </article>
        ))}
      </div>
    </div>
  )
}

/* ---------- Twin lineage ---------- */

// Each twin's permanent identity and its versions as of the tick on screen. A version is in
// operation, superseded (once in operation), rejected (submitted, never in operation), or
// under test (submitted, no outcome yet at this tick).
export function Lineage({ meta, state, ledger, who, inScope }) {
  if (!meta.lineage.recorded) {
    return (
      <div className="panel">
        <div className="panel-head"><h2 className="label" style={{ display: 'flex', gap: 6, alignItems: 'center' }}><Fingerprint size={13} color="var(--orange)" /> Twin lineage</h2><span className="small muted">pre-fingerprint</span></div>
        <p className="hint panel-pad" style={{ margin: 0 }}>This run was recorded before twin lineage existed. Its twins are named by role, with a version label declared by their owner, and carry no content fingerprints. Its ledger, files and readings are verified as before; runs recorded since carry a fingerprinted lineage for every twin.</p>
      </div>
    )
  }
  const accepted = new Set(ledger.flatMap((e) => (e.entry_type === 'assurance_issued' && e.payload.twin_ref ? [e.payload.twin_ref.fingerprint]
    : e.entry_type === 'composition_assured' || e.entry_type === 'composition_reassessment' ? [e.payload.system_ref?.fingerprint] : [])))
  const rejected = new Set(ledger.filter((e) => e.entry_type === 'recalibration_rejected' && e.payload.candidate_ref).map((e) => e.payload.candidate_ref.fingerprint))
  const groups = []
  for (const v of state.versions) {
    const id = v.operational_twin_id || v.operational_system_twin_id
    if (!inScope(id)) continue
    let g = groups.find((x) => x.identity === v.identity)
    if (!g) groups.push(g = { identity: v.identity, id, versions: [] })
    g.versions.push(v)
  }
  const standing = (g, v) => (state.twins[g.id]?.version?.fingerprint === v.fingerprint ? ['in operation', 'ok']
    : accepted.has(v.fingerprint) ? ['superseded', ''] : rejected.has(v.fingerprint) ? ['rejected', 'bad'] : ['under test', ''])
  return (
    <div className="panel">
      <div className="panel-head"><h2 className="label" style={{ display: 'flex', gap: 6, alignItems: 'center' }}><Fingerprint size={13} color="var(--orange)" /> Twin lineage</h2><span className="small muted">{state.versions.length} versions sealed</span></div>
      <p className="hint" style={{ padding: '10px 18px 0' }}>One permanent identity per twin. Each twin runs in its owner's environment, so the platform fingerprints each version by what it can observe: its answers to sealed probe inputs, with its declared interface. That measured fingerprint is the evidence, sealed before anything else about the version, and every ledger entry cites it. The owner's own fingerprint is shown as an unverified claim.</p>
      <ul className="rule-list panel-pad" style={{ paddingBlock: 4 }}>
        {groups.map((g) => (
          <li key={g.identity} style={{ display: 'grid', gap: 6 }}>
            <span><b style={{ fontSize: 13 }}>{who(g.id)}</b> <code className="muted" title="Permanent identity">{g.identity}</code></span>
            <ol className="lineage">
              {g.versions.map((v) => {
                const [label, tone] = standing(g, v)
                return (
                  <li key={v.fingerprint}>
                    <span><b>v{v.version}</b> <code title={v.fingerprint}>{short(v.fingerprint, 12)}</code> <span className={`lineage-state ${tone}`}>{label}</span></span>
                    <span className="small muted">
                      tick {v.tick} · {v.parent_fingerprint ? <>derived from <code>{short(v.parent_fingerprint, 8)}</code></> : 'first version'}
                      {v.constituents ? <> · {v.constituents.map((c) => `${c.twin_type} v${c.version}`).join(' + ')}</> : v.measured?.probes ? <> · measured from {v.measured.probes} probe answers</> : null}
                    </span>
                    {v.declared && <span className="small muted claim">Owner's claim, unverified: <code>{short(v.declared.fingerprint, 10)}</code></span>}
                  </li>
                )
              })}
            </ol>
          </li>
        ))}
      </ul>
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

/* ---------- Status timeline (extended panels) ---------- */

const LEVEL_BG = { assured: 'var(--assured)', flagged: 'var(--flagged)', nullified: 'var(--nullified)' }

export function StatusTimeline({ project, timeline, ticks, tick, ledger, onCite }) {
  const rows = [...project.twins.map((t) => ({ id: t.operational_twin_id, name: t.name })),
    { id: project.composition.system_twin.operational_twin_id, name: `${project.composition.system_twin.name} (system)` }]
  const changes = ledger.filter((e) => e.entry_type === 'assurance_status_changed' || (e.entry_type === 'assurance_issued' && e.payload.supersedes))
  return (
    <div className="panel">
      <div className="panel-head"><h2 className="label">Status timeline</h2><span className="small muted">ticks 0–{tick} of {ticks - 1}</span></div>
      <div className="panel-pad status-timeline">
        {rows.map((r) => (
          <div key={r.id} className="st-row">
            <span className="st-name">{r.name}</span>
            <span className="st-track">
              {timeline.map((row) => <i key={row.tick} style={{ background: LEVEL_BG[row.status[r.id]] || 'var(--rule)', width: `${100 / ticks}%` }}
                title={`${r.name} · tick ${row.tick} · ${row.status[r.id]}`} />)}
            </span>
            <span className="st-marks">{changes.filter((e) => e.payload.twin_id === r.id).map((e) => (
              <button key={e.seq} className="cite" onClick={() => onCite?.(e.seq)} title={`tick ${e.tick}`}>
                {e.payload.to || 're-assured'} @{e.tick} · #{e.seq}</button>))}</span>
          </div>
        ))}
        <div className="legend" style={{ padding: '6px 0 0' }}>
          {Object.entries(LEVEL_BG).map(([k, c]) => <span key={k}><i className="swatch" style={{ borderColor: c, background: c }} />{k}</span>)}
          <span>Each cell is one tick. Buttons open the ledger entry for each change.</span>
        </div>
      </div>
    </div>
  )
}

/* ---------- Cascade (extended panels) ---------- */

export function Cascade({ cascade, explanations, who, onCite }) {
  const [openNarrative, setOpenNarrative] = useState(null)
  if (!cascade.length) return null
  const narrativeFor = (seq) => explanations.find((e) => e.payload.artifact_type === 'cross_twin_narrative' && e.payload.explains_ledger_seq === seq)?.payload
  const latest = cascade[cascade.length - 1]
  const failedIface = new Set()
  return (
    <div className="panel">
      <div className="panel-head"><h2 className="label" style={{ display: 'flex', gap: 6, alignItems: 'center' }}><GitBranch size={13} color="var(--orange)" /> Cascade across twins</h2>
        <span className="small muted">from the ledger · {cascade.length} system {cascade.length === 1 ? 'reason' : 'reasons'} crossing a connection</span></div>
      <p className="hint" style={{ padding: '10px 18px 0' }}>Every ledger entry on the path from the twin where the cause started to the system twin, in order. Built from the evidence alone.</p>
      <div className="panel-pad cascade">
        {cascade.map((c) => {
          const narrative = narrativeFor(c.seq)
          const test = c.chain.find((b) => b.entry_type === 'composition_test' && !b.interface?.passed)
          const confirmed = test && c.chain.filter((b) => b.ledger_seq > test.ledger_seq && b.entry_type === 'assurance_status_changed'
            && test.interface.connections.some((k) => !k.passed && k.to_twin_id === b.twin_id))
          ;(test?.interface.connections || []).forEach((k) => { if (!k.passed) failedIface.add(`${k.from} → ${k.to}`) })
          return (
            <article key={c.seq} className={`cascade-item${c.seq === latest.seq ? ' is-latest' : ''}`}>
              <div className="label">System twin · tick {c.tick} · ledger #{c.seq} · {c.reasons.map((r) => CAUSES[r.cause] || r.cause).join('; ')}</div>
              <ol className="cascade-steps">
                {c.chain.map((b) => {
                  const tag = test && b.ledger_seq === test.ledger_seq ? 'prediction' : confirmed?.some((x) => x.ledger_seq === b.ledger_seq) ? 'confirmation' : null
                  return (
                    <li key={b.ledger_seq} className={tag ? `is-${tag}` : ''}>
                      <button className="cite" onClick={() => onCite?.(b.ledger_seq)}>#{b.ledger_seq}</button>
                      <span>{b.tick != null && <span className="muted">tick {b.tick} · </span>}{summarize({ entry_type: b.entry_type, payload: b }, who)}
                        {tag === 'prediction' && test.interface.connections.filter((k) => !k.passed).map((k) => (
                          <b key={k.from}> — predicted outside at {k.points_outside} of {test.points} points</b>))}
                        {tag && <span className={`tag tag-${tag}`}>{tag === 'prediction' ? 'Joint test prediction' : 'Field confirmation'}</span>}</span>
                    </li>
                  )
                })}
              </ol>
              {narrative && (
                <div>
                  <button className="text-link" onClick={() => setOpenNarrative(openNarrative === c.seq ? null : c.seq)}>
                    <Sparkles size={13} /> {openNarrative === c.seq ? 'Hide' : 'Read'} the AI cross-twin narrative</button>
                  {openNarrative === c.seq && <AiNote a={narrative} onCite={onCite} />}
                </div>
              )}
            </article>
          )
        })}
        {failedIface.size > 0 && <div className="small muted"><ArrowDown size={12} /> Failed interface: {[...failedIface].join(', ')}</div>}
      </div>
    </div>
  )
}
