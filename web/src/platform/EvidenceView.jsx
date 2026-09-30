// The operation view for a real project: every value on screen comes from the
// verified evidence as of the tick on screen (/api/runs/{run}/view?tick=N).
// Replay behaviour matches the original dashboard: it opens on the project's entry
// twins alone, one tick every 2 s, and accepts ?run=, ?tick=, ?stage=system,
// ?reveal=N (connect the rest of the system at tick N) and ?tick_ms=.

import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowUpRight, Link2, Pause, Play, RotateCcw, ShieldAlert, ShieldCheck, SkipBack, SkipForward } from 'lucide-react'
import { ConfigDrawer, Graph, StatusPill, TraceChart } from './components.jsx'
import { Header } from './OperationView.jsx'
import { Adjustment, Anomalies, Assistant, Explanations, Integrity, Ledger, Recalibration } from './EvidencePanels.jsx'
import { CAUSES, entryTwins, namer } from './evidenceText.js'
import { getJson, unitLabel } from './api.js'
import { TWIN_MODES, topology } from './model/projects.js'
import { digitsFor, fmt } from './format.js'

const params = new URLSearchParams(window.location.search)
const TICK_MS = Number(params.get('tick_ms')) || 2000
const AUTO_REVEAL = params.has('reveal') ? Number(params.get('reveal')) : null
const LEVEL_COLOR = { assured: 'var(--assured)', flagged: 'var(--flagged)', nullified: 'var(--nullified)' }

function statusMarkers(ledger, twinId, tick, systemId) {
  const out = []
  for (const e of ledger) {
    const p = e.payload
    if (e.tick > tick) continue
    if (e.entry_type === 'assurance_status_changed' && p.twin_id === twinId) out.push({ x: p.tick, label: `${p.to} @${p.tick}`, color: LEVEL_COLOR[p.to] })
    if (e.entry_type === 'assurance_issued' && p.twin_id === twinId && p.supersedes) out.push({ x: e.tick, label: `re-assured @${e.tick}`, color: LEVEL_COLOR.assured })
    if (e.entry_type === 'adjustment_recommended' && twinId !== systemId) out.push({ x: p.tick, label: `Recommended @${p.tick}`, color: 'var(--orange)' })
    if (e.entry_type === 'adjustment_executed' && twinId !== systemId) out.push({ x: p.tick, label: `Executed @${p.tick}`, color: 'var(--orange)' })
  }
  return out
}

function padded(lo, hi, pad = 0.08) {
  const span = (hi - lo) || Math.abs(hi) * 0.1 || 1
  return [lo - span * pad, hi + span * pad]
}

export default function EvidenceView({ project }) {
  const who = useMemo(() => namer(project), [project])
  const [run, setRun] = useState(() => (project.runs.find((r) => r.id === params.get('run')) || project.runs[0]).id)
  const [meta, setMeta] = useState(null)
  const [view, setView] = useState(null)
  const [tick, setTick] = useState(Number(params.get('tick')) || 0)
  const [playing, setPlaying] = useState(false)
  const [stage, setStage] = useState(params.get('stage') === 'system' ? 'system' : null)
  const [selected, setSelected] = useState(project.entry_twins[0])
  const [drawer, setDrawer] = useState(false)
  const [error, setError] = useState(null)
  const cache = useRef(new Map())

  useEffect(() => {
    let live = true
    getJson(`/api/runs/${run}/meta`).then((m) => live && setMeta(m)).catch((e) => setError(e.message))
    return () => { live = false }
  }, [run])

  // Everything on screen comes from the evidence as of this tick only.
  useEffect(() => {
    if (!meta) return
    const key = `${run}:${tick}`
    if (cache.current.has(key)) { Promise.resolve().then(() => setView(cache.current.get(key))); return }
    let live = true
    getJson(`/api/runs/${run}/view?tick=${tick}`)
      .then((v) => { cache.current.set(key, v); if (live) setView(v) })
      .catch((e) => setError(e.message))
    return () => { live = false }
  }, [run, meta, tick])

  useEffect(() => {
    if (!playing || !meta) return
    const id = setInterval(() => setTick((t) => {
      if (t >= meta.ticks - 1) { setPlaying(false); return t }
      return t + 1
    }), TICK_MS)
    return () => clearInterval(id)
  }, [playing, meta])

  const chooseRun = (id) => {
    cache.current = new Map()
    setPlaying(false); setTick(0); setMeta(null); setView(null); setRun(id)
  }

  const header = (children, sub) => <Header project={project} onConfig={() => setDrawer(true)} sub={sub}>{children}</Header>
  if (error) return <div className="content-width page">{header(null)}<div className="callout callout-warn" style={{ marginTop: 24 }}>Could not load evidence: {error}</div></div>
  if (!meta || !view) return <div className="content-width page">{header(null)}<div className="panel panel-pad muted" style={{ marginTop: 24 }}>Loading and verifying evidence…</div></div>

  const showSystem = stage ? stage === 'system' : AUTO_REVEAL != null && tick >= AUTO_REVEAL
  const state = view.state
  const systemId = project.composition.system_twin.operational_twin_id
  const entry = project.twins.filter((t) => project.entry_twins.includes(t.key))
  const rest = project.twins.filter((t) => !project.entry_twins.includes(t.key))
  const soloIds = new Set(entry.flatMap((t) => [t.operational_twin_id, t.design_twin_id]))
  const inScope = (e) => { const ids = entryTwins(e); return showSystem || ids.length === 0 || ids.some((id) => soloIds.has(id)) }
  const visible = showSystem ? project.twins : entry
  const current = visible.find((t) => t.key === selected) || visible[0]
  const levels = Object.fromEntries(Object.entries(state.twins).map(([id, t]) => [id, t.status]))
  const hours = view.readings.findLast((r) => r.tick === tick)?.operational_hours
  const ledger = view.ledger.filter(inScope)
  const explanations = view.explanations.filter((e) => inScope(view.ledger.find((c) => c.seq === e.payload.explains_ledger_seq) || e))
  const hasRecal = state.recalibration.some((e) => e.entry_type === 'recalibration_requested')
  const hasAdj = showSystem && state.adjustment.some((e) => e.entry_type === 'adjustment_recommended' || e.entry_type === 'adjustment_refused')
  const soloProject = { ...project, twins: entry, composition: { ...project.composition, connections: [], output_constituents: [] } }
  const entryNames = entry.map((t) => t.name).join(' & ')
  const restNames = rest.map((t) => t.name.toLowerCase()).join(' & ')
  const v = meta.verification

  return (
    <>
      <div className="content-width page" style={{ paddingBottom: 0 }}>
        {header(
          <>
            <label className="field" style={{ minWidth: 210 }}>
              <span>Evidence run</span>
              <select id="run-select" className="select compact" value={run} onChange={(e) => chooseRun(e.target.value)}>
                {project.runs.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
            </label>
            {v.valid
              ? <span className="chip"><ShieldCheck size={14} /> Evidence verified · {v.checks.length}/{v.checks.length}</span>
              : <span className="chip" style={{ color: 'var(--nullified)' }}><ShieldAlert size={14} /> Not verified</span>}
          </>,
          `${meta.title} · scenario ${meta.scenario} · seed ${meta.seed} · synthetic data`,
        )}
      </div>

      <div className="replay">
        <div className="content-width replay-inner">
          <button className="button button-dark button-small" onClick={() => { if (tick >= meta.ticks - 1) setTick(0); setPlaying(!playing) }}>
            {playing ? <><Pause size={14} /> Pause</> : tick >= meta.ticks - 1 ? <><RotateCcw size={14} /> Replay</> : <><Play size={14} /> Play</>}
          </button>
          <button className="icon-button" onClick={() => setTick((t) => Math.max(0, t - 1))} disabled={tick === 0} aria-label="Step back"><SkipBack size={14} /></button>
          <button className="icon-button" onClick={() => setTick((t) => Math.min(meta.ticks - 1, t + 1))} disabled={tick >= meta.ticks - 1} aria-label="Step forward"><SkipForward size={14} /></button>
          <span className="replay-tick">Tick {tick} <span className="muted">/ {meta.ticks - 1}</span></span>
          <span className="small muted num">{hours != null ? `${hours.toLocaleString('en-GB')} h · ` : ''}{state.timestamp}</span>
          <input id="tick" type="range" min="0" max={meta.ticks - 1} value={tick} onChange={(e) => { setPlaying(false); setTick(Number(e.target.value)) }} aria-label="Replay position" />
          {rest.length > 0 && (
            <button className={`button button-small ${showSystem ? 'button-ghost' : 'button-primary'}`} onClick={() => setStage(showSystem ? 'solo' : 'system')}>
              <Link2 size={14} /> {showSystem ? `Show ${entryNames.toLowerCase()} only` : `Connect ${restNames} & system twin`}
            </button>
          )}
          <span className="small muted">{TICK_MS / 1000} s per tick</span>
        </div>
      </div>

      <div className="content-width" style={{ paddingBottom: 40 }}>
        <section className="section" aria-labelledby="status-h">
          <div className="section-head">
            <h2 id="status-h" className="label">Assurance status at tick {tick}</h2>
          </div>
          <div className="status-row">
            {visible.map((t) => <TwinStatusCard key={t.key} twin={t} s={state.twins[t.operational_twin_id]} who={who}
              selected={current.key === t.key} onSelect={() => setSelected(t.key)} />)}
            {showSystem && rest.length > 0 && (
              <TwinStatusCard system twin={{ name: project.composition.system_twin.name, operational_twin_id: systemId }}
                s={state.twins[systemId]} who={who} note={`${project.twins.length} constituents · ${topology(project).toLowerCase()}`} />
            )}
            {!showSystem && rest.length > 0 && (
              <div className="twin-card solo-note">
                <div className="h4" style={{ fontSize: 15 }}>Viewing the {entryNames.toLowerCase()} on its own</div>
                <p className="small muted" style={{ margin: 0 }}>As if it were the only monitored asset. Connect the {restNames} it drives to see what an isolated view misses.</p>
                <div><button className="button button-primary button-small" onClick={() => setStage('system')}><Link2 size={14} /> Connect {restNames} & system twin</button></div>
              </div>
            )}
          </div>
        </section>

        <div className="op-grid section">
          <div style={{ display: 'grid', gap: 18, minWidth: 0 }}>
            <div className="panel">
              <div className="tabs" role="tablist" aria-label="Twins">
                {visible.map((t) => (
                  <button key={t.key} role="tab" className="tab" aria-selected={current.key === t.key} onClick={() => setSelected(t.key)}>
                    <span className="dot" style={{ background: LEVEL_COLOR[levels[t.operational_twin_id]] }} />{t.name}
                  </button>
                ))}
              </div>
              <div className="panel-head" style={{ borderBottom: 0, paddingBottom: 6 }}>
                <div className="small muted">
                  {current.owner} · {TWIN_MODES[current.twin_mode]?.label} · gap = % of the twin's prediction · flagged after {meta.escalation_protocol.flag_after_consecutive} readings in a row above tolerance,
                  nullified after {meta.escalation_protocol.nullify_after_consecutive} above {meta.escalation_protocol.nullify_tolerance_multiplier}× tolerance
                </div>
                <button className="text-link" onClick={() => setDrawer(true)}>See this twin's config <ArrowUpRight size={14} /></button>
              </div>
              <Reasons s={state.twins[current.operational_twin_id]} who={who} />
              <div className="channel-grid">
                {meta.twins[current.operational_twin_id].channels.map((c) => (
                  <ChannelCard key={c.channel_id} c={c} twin={current} project={project} meta={meta} view={view} tick={tick} who={who} systemId={systemId} />
                ))}
              </div>
              <div className="legend" style={{ padding: '10px 16px 14px' }}>
                <span><i className="key" style={{ borderTopColor: 'var(--ink)' }} />Measured</span>
                <span><i className="key dashed" style={{ borderTopColor: 'var(--orange)' }} />Twin prediction (same instant)</span>
                <span><i className="swatch" style={{ borderColor: 'var(--flagged)', background: 'var(--flagged-bg)' }} />Not evaluated (an input outside its assured range)</span>
                <span>Dotted lines mark status changes</span>
              </div>
            </div>
          </div>

          <div className="side">
            <div className="panel">
              <div className="panel-head"><h2 className="label">Composition</h2><span className="small muted">{showSystem ? 'Select a twin' : 'Solo view'}</span></div>
              <div className="panel-pad"><Graph project={showSystem ? project : soloProject} levels={levels} onPick={setSelected} selected={current.key} compact /></div>
            </div>
            <Ledger entries={ledger} head={state.ledger_head_so_far} total={state.ledger_entries_so_far} who={who} />
          </div>
        </div>
      </div>

      {(hasRecal || hasAdj) && (
        <section className="night" style={{ padding: '40px 0 48px' }} aria-labelledby="scen-h">
          <div className="content-width" style={{ display: 'grid', gap: 22 }}>
            <div className="section-head">
              <div style={{ display: 'grid', gap: 10 }}>
                <p className="kicker"><span className="accent">Run scenario</span><span className="sep" />{meta.title}</p>
                <h2 id="scen-h" className="display display-l" style={{ fontSize: 'clamp(1.8rem, 3vw, 2.4rem)' }}>Real2Sim and Sim2Real, on the record</h2>
              </div>
              <p className="lead" style={{ maxWidth: 380 }}>Every step below is a ledger entry, shown as of tick {tick}.</p>
            </div>
            <div className="scenario-grid">
              <Recalibration state={state} who={who} showSystem={showSystem} />
              {hasAdj && <Adjustment state={state} view={view} meta={meta} project={project} who={who} tick={tick} />}
            </div>
          </div>
        </section>
      )}

      <div className="content-width" style={{ paddingBottom: 56 }}>
        <div className="evidence-grid section">
          <Assistant run={run} tick={tick} showSystem={showSystem} soloNames={entryNames} />
          <Explanations items={explanations} />
          <Anomalies ledger={ledger} who={who} />
          <Integrity key={run} meta={meta} run={run} />
        </div>
      </div>
      {drawer && <ConfigDrawer project={project} focusKey={current.key} onClose={() => setDrawer(false)} />}
    </>
  )
}

function TwinStatusCard({ twin, s, who, selected, onSelect, system, note }) {
  const status = s?.status || 'assured'
  const open = (s?.reasons || []).filter((r) => !r.resolved)
  const last = open[open.length - 1]
  const hist = s?.assurance_history || []
  const cur = hist[hist.length - 1]
  const Tag = system ? 'div' : 'button'
  return (
    <Tag className={`twin-card is-${status}${system ? ' is-system' : ''}`} aria-pressed={system ? undefined : selected} onClick={onSelect} style={system ? { cursor: 'default' } : undefined}>
      <div className="twin-card-head">
        <div>
          <div className="label">{system ? 'System twin' : twin.role === 'controller' ? 'Controller twin' : 'Product twin'}{cur?.twin_version ? ` · twin ${cur.twin_version}` : ''}</div>
          <div className="h4" style={{ fontSize: 14, marginTop: 3 }}>{twin.name}</div>
        </div>
        <StatusPill level={status} />
      </div>
      <div className="reason">
        {last ? <>{CAUSES[last.cause] || last.cause}{last.channel_id ? ` · ${last.channel_id}` : ''}{last.constituent ? ` · ${who(last.constituent)}` : ''} (tick {last.since_tick})</>
          : 'No open reasons under this assurance.'}
      </div>
      <div className="small muted"><code>{s?.assurance_id || '—'}</code>{note ? ` · ${note}` : open.length > 1 ? ` · ${open.length} open reasons` : ''}</div>
    </Tag>
  )
}

function Reasons({ s, who }) {
  if (!s?.reasons?.length) return null
  const hist = s.assurance_history || []
  const cur = hist[hist.length - 1]
  return (
    <div className="reasons-box">
      <div className="small muted">Assurance <code>{s.assurance_id}</code>{cur?.twin_version && <> · twin {cur.twin_version}</>}{cur?.supersedes && <> · supersedes <code>{cur.supersedes}</code></>}</div>
      <ul>
        {s.reasons.map((r, i) => (
          <li key={i} className={`reason-${r.level}${r.resolved ? ' resolved' : ''}`}>
            <b>{CAUSES[r.cause] || r.cause}{r.channel_id ? ` · ${r.channel_id}` : ''}</b>
            <span>{r.constituent ? `${who(r.constituent)}: ` : ''}{r.detail} · since tick {r.since_tick} · ledger #{r.ledger_seq}</span>
            {r.root_causes?.length > 0 && <span className="muted">Traced to: {r.root_causes.map((c) => `${CAUSES[c.cause] || c.cause}${c.channel_id ? ` on ${c.channel_id}` : ''}`).join('; ')}</span>}
            {r.resolved && <span className="ok">Resolved at tick {r.resolved.at_tick}: {r.resolved.note}</span>}
          </li>
        ))}
      </ul>
    </div>
  )
}

function ChannelCard({ c, twin, project, meta, view, tick, who, systemId }) {
  const id = twin.operational_twin_id
  const unit = unitLabel(c.unit)
  const d = digitsFor(c.envelope)
  const rows = view.readings.filter((r) => r.twin_id === id && r.channel_id === c.channel_id)
  const last = rows[rows.length - 1]
  const markers = statusMarkers(view.ledger, id, tick, systemId)
  const xMax = meta.ticks - 1
  const notEvaluated = view.timeline.filter((row) => Object.values(row.classifications[id] || {}).some((k) => k.class === 'not_evaluated')).map((row) => row.tick)
  const dr = meta.display_ranges[`${id}/${c.channel_id}`] || { min: c.envelope[0], max: c.envelope[1] }
  const feed = project.composition.connections.find((k) => k.to[0] === twin.key && k.to[1] === c.channel_id)
  const rec = view.ledger.find((e) => e.entry_type === 'adjustment_recommended')?.payload

  if (c.direction === 'output') {
    const tol = c.tolerance_pct
    const mult = meta.escalation_protocol.nullify_tolerance_multiplier
    const gapMax = Math.max(tol * mult + 4, Math.ceil((meta.display_ranges.gap_pct_max + 1) / 5) * 5)
    const cls = view.timeline[view.timeline.length - 1]?.classifications[id]?.[c.channel_id]
    const g = cls?.gap_pct
    const [lo, hi] = padded(dr.min, dr.max)
    return (
      <div className="channel">
        <div className="channel-head">
          <div><div className="h4">{c.name}</div><div className="small muted">Tolerance {tol}% · range {fmt(c.envelope[0], d)}–{fmt(c.envelope[1], d)} {unit}</div></div>
          <span className="dir dir-output">output</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 14, flexWrap: 'wrap' }}>
          <span className="channel-value" style={{ color: g == null ? undefined : g > tol * mult ? 'var(--nullified)' : g > tol ? 'var(--flagged)' : undefined }}>
            {g == null ? <span className="small muted">not evaluated</span> : <>{fmt(g, 1)}%<small>gap</small></>}</span>
          <span className="small muted num">measured {fmt(last?.physical_value, d)} · twin {fmt(last?.predicted_value, d)} {unit}</span>
        </div>
        <TraceChart xMax={xMax} yMin={0} yMax={gapMax} cursor={tick} markers={markers} shade={notEvaluated} digits={0}
          hlines={[{ y: tol, label: `${tol}% tol`, color: 'var(--flagged)' }, { y: tol * mult, label: `${tol * mult}% nullify`, color: 'var(--nullified)' }]}
          series={[{ color: 'var(--ink)', points: view.timeline.map((row) => [row.tick, row.classifications[id]?.[c.channel_id]?.gap_pct ?? null]) }]} />
        <TraceChart H={104} xMax={xMax} yMin={lo} yMax={hi} cursor={tick} markers={markers} digits={d}
          series={[{ color: 'var(--ink)', points: rows.map((r) => [r.tick, r.physical_value]) },
            { color: 'var(--orange)', dashed: true, points: rows.map((r) => [r.tick, r.predicted_value]) }]} />
      </div>
    )
  }

  const [lo, hi] = padded(Math.min(dr.min, c.envelope[0]), Math.max(dr.max, c.envelope[1]))
  const hl = []
  if (rec && rec.twin_id === id && rec.recommendation.control_channel === c.channel_id)
    hl.push({ y: rec.recommendation.to, color: 'var(--orange)', label: `Recommended setpoint ${fmt(rec.recommendation.to, d)} ${unit}` })
  if (rec && rec.objective.twin_type === twin.key && rec.objective.channel === c.channel_id)
    hl.push({ y: rec.predicted_objective_value, x0: rec.tick, color: 'var(--orange)', label: `Predicted after adjustment ${fmt(rec.predicted_objective_value, 0)} ${unit}` })
  return (
    <div className="channel">
      <div className="channel-head">
        <div><div className="h4">{c.name}</div><div className="small muted">Assured {fmt(c.envelope[0], d)}–{fmt(c.envelope[1], d)} {unit}</div></div>
        <span className="dir dir-input">input</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 14, flexWrap: 'wrap' }}>
        <span className="channel-value" style={{ color: last && (last.physical_value < c.envelope[0] || last.physical_value > c.envelope[1]) ? 'var(--flagged)' : undefined }}>
          {fmt(last?.physical_value, d)}<small>{unit}</small></span>
        {feed && <span className="small muted" style={{ display: 'inline-flex', gap: 5, alignItems: 'center' }}><Link2 size={12} /> driven by {who(project.twins.find((t) => t.key === feed.from[0]).operational_twin_id)}</span>}
      </div>
      <TraceChart H={feed ? 232 : 128} xMax={xMax} yMin={lo} yMax={hi} cursor={tick} markers={markers} shade={feed ? notEvaluated : []} digits={d}
        band={{ min: c.envelope[0], max: c.envelope[1] }} hlines={hl}
        series={[{ color: 'var(--ink)', points: rows.map((r) => [r.tick, r.physical_value]) }]} />
    </div>
  )
}
