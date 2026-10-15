import { useEffect, useMemo, useState } from 'react'
import { ArrowUpRight, Braces, FlaskConical, Link2, Pause, Play, Sparkles } from 'lucide-react'
import { ConfigDrawer, GapChart, Graph, InputChart, StatusPill } from './components.jsx'
import { digitsFor, fmt } from './format.js'
import IntegrationPanel from './IntegrationPanel.jsx'
import { ESCALATION, TWIN_MODES, channelCount, layers, topology, twinByKey } from './model/projects.js'
import { mockRun } from './model/mockRun.js'
import WireframeAsset from '../visual/wireframe/WireframeAsset.jsx'

const CAUSE = {
  gap: (r) => `${r.channel}: gap beyond tolerance for ${ESCALATION.flag_after}+ readings (tick ${r.since})`,
  gap_2x: (r) => `${r.channel}: gap beyond 2× tolerance for ${ESCALATION.nullify_after} readings (tick ${r.since})`,
  envelope: (r) => `${r.channel}: input outside its assured range (tick ${r.since})`,
  cascade: (r) => `Cascade: ${r.channel} is nullified (tick ${r.since})`,
  own_output: (r) => `Takes the status of ${r.channel}, its output twin (tick ${r.since})`,
}

export default function OperationView({ project }) {
  if (project.status === 'awaiting_telemetry') return <PendingProject project={project} />
  return <Operating project={project} />
}

export function Header({ project, children, onConfig, sub }) {
  return (
    <div className="page-head">
      <nav className="crumbs" aria-label="Breadcrumb"><a href="#projects">Projects</a><span>/</span><span>{project.name}</span></nav>
      <div className="page-head-row">
        <div style={{ display: 'grid', gap: 14 }}>
          <p className="kicker">
            <span className="accent">{project.domain}</span><span className="sep" />{topology(project)}
            <span className="sep" />{project.twins.length} twins<span className="sep" />{channelCount(project)} channels
          </p>
          <h1 className="display display-l">{project.name}</h1>
          {sub && <p className="small muted" style={{ margin: 0 }}>{sub}</p>}
          {project.preview && <span className="chip" style={{ justifySelf: 'start' }}>Preview · mock data, not evidence</span>}
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          {children}
          <button className="button button-ghost" onClick={onConfig}><Braces size={15} /> Project configuration</button>
        </div>
      </div>
    </div>
  )
}

function Operating({ project }) {
  const [runId, setRunId] = useState(project.runs[0].id)
  const run = project.runs.find((r) => r.id === runId)
  const data = useMemo(() => mockRun(project, run), [project, run])
  const [tick, setTick] = useState(Math.round(run.ticks * 0.6))
  const [playing, setPlaying] = useState(false)
  const order = layers(project).flat()
  const [selected, setSelected] = useState(run.mock.fault?.twin || order[0])
  const [scope, setScope] = useState('system')
  const [drawer, setDrawer] = useState(false)

  useEffect(() => {
    if (!playing) return
    const id = setInterval(() => setTick((t) => (t >= run.ticks - 1 ? (setPlaying(false), t) : t + 1)), 220)
    return () => clearInterval(id)
  }, [playing, run.ticks])

  const snap = data.snapshots[tick].twins
  const levels = Object.fromEntries(project.twins.map((t) => [t.operational_twin_id, snap[t.key].level]))
  levels[data.sysId] = snap[data.sysId].level
  const twin = twinByKey(project, selected)
  const visible = scope === 'system' ? order : [selected]
  const ledger = data.ledger.filter((e) => e.tick <= tick && (scope === 'system' || e.twin === selected)).slice(-8).reverse()
  const feeds = Object.fromEntries(project.composition.connections.map((c) => [`${c.to[0]}.${c.to[1]}`, c.from]))
  const sysSnap = snap[data.sysId]

  return (
    <>
      <div className="content-width page" style={{ paddingBottom: 0 }}>
        <Header project={project} onConfig={() => setDrawer(true)}>
          <label className="field" style={{ minWidth: 190 }}>
            <span>Evidence run</span>
            <select id="run-select" className="select compact" value={runId} onChange={(e) => { const r = project.runs.find((x) => x.id === e.target.value); setRunId(r.id); setPlaying(false); setTick(Math.round(r.ticks * 0.6)) }}>
              {project.runs.map((r) => <option key={r.id} value={r.id}>{r.name} · {r.ticks} ticks</option>)}
            </select>
          </label>
          <span className="chip" title="Preview projects replay mock data; there is no evidence to verify"><FlaskConical size={14} /> Mock replay · not verified</span>
        </Header>
      </div>

      <div className="replay">
        <div className="content-width replay-inner">
          <button className="icon-button" onClick={() => setPlaying((p) => !p)} aria-label={playing ? 'Pause replay' : 'Play replay'}>
            {playing ? <Pause size={15} /> : <Play size={15} />}
          </button>
          <span className="replay-tick">Tick {tick} <span className="muted">/ {run.ticks - 1}</span></span>
          <input id="tick" type="range" min="0" max={run.ticks - 1} value={tick} onChange={(e) => { setPlaying(false); setTick(Number(e.target.value)) }} aria-label="Replay position" />
          <div className="seg" role="group" aria-label="Scope">
            <button aria-pressed={scope === 'system'} onClick={() => setScope('system')}>Whole system</button>
            <button aria-pressed={scope === 'twin'} onClick={() => setScope('twin')}>{twin.name} only</button>
          </div>
        </div>
      </div>

      <div className="content-width" style={{ paddingBottom: 56 }}>
        <section className="section" aria-labelledby="status-h">
          <div className="section-head">
            <h2 id="status-h" className="label">Assurance status at tick {tick}</h2>
            {scope === 'twin' && <span className="small muted">Viewing {twin.name} as if it were the only monitored asset. Switch to the whole system to see what an isolated view misses.</span>}
          </div>
          <div className="status-row">
            {visible.map((key) => {
              const t = twinByKey(project, key)
              const s = snap[key]
              const open = s.reasons.filter((r) => !r.resolved)
              return (
                <button key={key} className={`twin-card is-${s.level}`} aria-pressed={selected === key} onClick={() => setSelected(key)}>
                  <div className="twin-card-head">
                    <div>
                      <div className="label">{t.role === 'controller' ? 'Controller twin' : 'Product twin'} · v{s.version}</div>
                      <div className="h4" style={{ fontSize: 14, marginTop: 3 }}>{t.name}</div>
                    </div>
                    <StatusPill level={s.level} />
                  </div>
                  <div className="reason">{open.length ? CAUSE[open[open.length - 1].cause](open[open.length - 1]) : s.version > 1 ? 'Re-assured after recalibration' : 'All channels within tolerance'}</div>
                  <div className="small muted">{TWIN_MODES[t.twin_mode].label} · {t.channels.length} channels{open.length > 1 ? ` · ${open.length} reasons` : ''}</div>
                </button>
              )
            })}
            {scope === 'system' && project.twins.length > 1 && (
              <div className={`twin-card is-system is-${sysSnap.level}`} style={{ cursor: 'default' }}>
                <div className="twin-card-head">
                  <div>
                    <div className="label">System twin</div>
                    <div className="h4" style={{ fontSize: 14, marginTop: 3 }}>{project.composition.system_twin.name}</div>
                  </div>
                  <StatusPill level={sysSnap.level} />
                </div>
                <div className="reason">{sysSnap.reasons.length ? CAUSE[sysSnap.reasons[sysSnap.reasons.length - 1].cause](sysSnap.reasons[sysSnap.reasons.length - 1]) : 'Composed from assured twins'}</div>
                <div className="small muted">{project.twins.length} constituents · {topology(project).toLowerCase()}</div>
              </div>
            )}
          </div>
        </section>

        <div className="op-grid section">
          <div className="panel">
            <div className="tabs" role="tablist" aria-label="Twins">
              {visible.map((key) => {
                const t = twinByKey(project, key)
                return (
                  <button key={key} role="tab" className="tab" aria-selected={selected === key} onClick={() => setSelected(key)}>
                    <span className="dot" style={{ background: `var(--${snap[key].level})` }} />{t.name}
                  </button>
                )
              })}
            </div>
            <div className="panel-head" style={{ borderBottom: 0, paddingBottom: 6 }}>
              <div className="small muted">
                {twin.owner} · {TWIN_MODES[twin.twin_mode].label} · {twin.channels.filter((c) => c.direction === 'input').length} inputs,{' '}
                {twin.channels.filter((c) => c.direction === 'output').length} outputs · gap = % of the twin's prediction
              </div>
              <button className="text-link" onClick={() => setDrawer(true)}>See this twin's config <ArrowUpRight size={14} /></button>
            </div>
            <div className="channel-grid">
              {twin.channels.map((c) => {
                const row = data.series[selected][c.id][tick]
                const d = digitsFor(c.assured_range)
                const src = feeds[`${selected}.${c.id}`]
                return (
                  <div key={c.id} className="channel">
                    <div className="channel-head">
                      <div>
                        <div className="h4">{c.name}</div>
                        <div className="small muted">
                          {c.direction === 'output' ? `Tolerance ${c.tolerance_pct}% · range ${fmt(c.assured_range[0], d)}–${fmt(c.assured_range[1], d)} ${c.unit}` : `Assured ${fmt(c.assured_range[0], d)}–${fmt(c.assured_range[1], d)} ${c.unit}`}
                        </div>
                      </div>
                      <span className={`dir dir-${c.direction}`}>{c.direction}</span>
                    </div>
                    {c.direction === 'output' ? (
                      <>
                        <div style={{ display: 'flex', alignItems: 'baseline', gap: 14, flexWrap: 'wrap' }}>
                          <span className="channel-value">{row.cls === 'not_evaluated' ? '—' : `${fmt(row.gap, 1)}%`}<small>gap</small></span>
                          <span className="small muted num">measured {fmt(row.physical, d)} · twin {fmt(row.predicted, d)} {c.unit}</span>
                        </div>
                        <GapChart rows={data.series[selected][c.id]} tick={tick} tol={c.tolerance_pct} ticks={run.ticks} />
                        {row.cls === 'not_evaluated' && <div className="small" style={{ color: 'var(--flagged)' }}>Not evaluated: an input is outside its assured range</div>}
                      </>
                    ) : (
                      <>
                        <div style={{ display: 'flex', alignItems: 'baseline', gap: 14, flexWrap: 'wrap' }}>
                          <span className="channel-value">{fmt(row.physical, d)}<small>{c.unit}</small></span>
                          {src && <span className="small muted" style={{ display: 'inline-flex', gap: 5, alignItems: 'center' }}><Link2 size={12} /> from {twinByKey(project, src[0]).name}</span>}
                        </div>
                        <InputChart rows={data.series[selected][c.id]} tick={tick} range={c.assured_range} ticks={run.ticks} />
                      </>
                    )}
                  </div>
                )
              })}
            </div>
          </div>

          <div className="side">
            <div className="panel">
              <div className="panel-head"><h2 className="label">Composition</h2><span className="small muted">Select a twin</span></div>
              <div className="panel-pad"><Graph project={project} levels={levels} onPick={setSelected} selected={selected} compact /></div>
            </div>
            <div className="panel">
              <div className="panel-head"><h2 className="label">Mock event log</h2><span className="small muted">Preview · not a sealed ledger · to tick {tick}</span></div>
              <ul className="rule-list panel-pad" style={{ paddingBlock: 4 }}>
                {ledger.map((e) => (
                  <li key={e.seq} className="ledger-row">
                    <span className="seq">#{e.seq}</span>
                    <span>{e.text}<br /><code>tick {e.tick}</code></span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="panel">
              <div className="panel-head"><h2 className="label" style={{ display: 'flex', gap: 6, alignItems: 'center' }}><Sparkles size={13} color="var(--orange)" /> Evidence assistant</h2></div>
              <div className="panel-pad" style={{ display: 'grid', gap: 12 }}>
                <div className="assistant-q">
                  {[`Why is ${twin.name} ${snap[selected].level}?`, 'What changed in the last 10 ticks?', 'Is the evidence intact?'].map((q) => (
                    <button key={q} className="chip" style={{ cursor: 'pointer' }}>{q}</button>
                  ))}
                </div>
                <div className="assistant-answer">
                  The assistant answers only from verified evidence, so it is not available for preview projects.
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {(run.mock.recalibration || run.mock.adjustment) && <ScenarioBand project={project} run={run} tick={tick} />}
      {drawer && <ConfigDrawer project={project} focusKey={selected} onClose={() => setDrawer(false)} />}
    </>
  )
}

function Steps({ steps, tick }) {
  return (
    <ol className="step-list">
      {steps.map(([at, text], i) => (
        <li key={i}>
          <span className={`step-mark${tick >= at ? ' done' : ''}`}>{i + 1}</span>
          <span style={{ opacity: tick >= at ? 1 : 0.55 }}>{text}</span>
          <span className="when">T{at}</span>
        </li>
      ))}
    </ol>
  )
}

function ScenarioBand({ project, run, tick }) {
  const { recalibration: rc, adjustment: ad } = run.mock
  const rt = rc && twinByKey(project, rc.twin)
  const at = ad && twinByKey(project, ad.twin)
  const control = at?.channels.find((c) => c.id === ad.control)
  const objective = ad && twinByKey(project, ad.objective[0]).channels.find((c) => c.id === ad.objective[1])
  return (
    <section className="night" style={{ padding: '44px 0 52px' }} aria-labelledby="scen-h">
      <div className="content-width" style={{ display: 'grid', gap: 22 }}>
        <div className="section-head">
          <div style={{ display: 'grid', gap: 10 }}>
            <p className="kicker"><span className="accent">Run scenario</span><span className="sep" />{run.name}</p>
            <h2 id="scen-h" className="display display-l" style={{ fontSize: 'clamp(1.8rem, 3vw, 2.4rem)' }}>Real2Sim and Sim2Real, on the record</h2>
          </div>
          <p className="lead" style={{ maxWidth: 380 }}>These panels appear only when a run's scenario includes them. Every step is a ledger entry.</p>
        </div>
        <div className="scenario-grid">
          {rc && (
            <div className="panel panel-pad" style={{ display: 'grid', gap: 12 }}>
              <div><div className="label" style={{ color: 'var(--orange-bright)' }}>Recalibration · Real2Sim</div><h3 className="h3" style={{ marginTop: 6 }}>{rt.name} twin, v1 → v2</h3></div>
              <Steps tick={tick} steps={[
                [rc.at, `Recalibration requested while ${rt.name} is not assured`],
                [rc.at, 'Evidence split by time: earlier 70% to the twin owner, later 30% held out; both sealed first'],
                [rc.at, 'Owner submits v2; the platform re-verifies it'],
                [rc.at, 'Held-out validation on data the owner never saw: pass'],
                [rc.at, `v2 supersedes v1; ${project.composition.system_twin.name} reassessed (status stays sticky)`],
              ]} />
            </div>
          )}
          {ad && (
            <div className="panel panel-pad" style={{ display: 'grid', gap: 12 }}>
              <div><div className="label" style={{ color: 'var(--orange-bright)' }}>Semi-autonomous adjustment · Sim2Real</div>
                <h3 className="h3" style={{ marginTop: 6 }}>{control.name}: {ad.from} → {ad.to} {control.unit}</h3></div>
              <Steps tick={tick} steps={[
                [ad.recommend, `${at.name} twin recommends the change; platform checks mode, status and assured ranges`],
                [ad.approve, 'Approved by a named role: Operator (demo)'],
                [ad.execute, 'Executed once, then back to passive monitoring'],
                [ad.execute + 5, `Post-state check: Sim2Real within tolerance; ${objective.name.toLowerCase()} back in its assured range`],
              ]} />
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

function PendingProject({ project }) {
  const [drawer, setDrawer] = useState(false)
  return (
    <div className="content-width page">
      <Header project={project} onConfig={() => setDrawer(true)}><StatusPill level="pending" /></Header>
      <div className="op-grid section">
        <div style={{ display: 'grid', gap: 18 }}>
          <div className="panel">
            <div className="panel-head"><h2 className="label">Composition</h2><span className="small muted">{topology(project)}</span></div>
            <div className="panel-pad"><Graph project={project} pending /></div>
          </div>
          {project.twins.map((t) => (
            <div key={t.key} className="panel">
              <div className="panel-head">
                <div><div className="label">{t.role === 'controller' ? 'Controller twin' : 'Product twin'} · {TWIN_MODES[t.twin_mode].label}</div><div className="h4" style={{ fontSize: 14 }}>{t.name}</div></div>
                <span className="small muted">{t.registry_id ? `Registered: ${t.registry_id} · ${t.owner}` : 'Unregistered · cannot be assured until its owner registers it'}</span>
              </div>
              {t.asset_kind && <WireframeAsset kind={t.asset_kind} height={120} spin={false} label={`Wireframe of ${t.name}`} />}
              <div className="table-wrap" style={{ border: 0, borderRadius: 0 }}>
                <table className="grid" style={{ minWidth: 520 }}>
                  <thead><tr><th>Channel</th><th>Direction</th><th>Unit</th><th>Assured range</th><th>Tolerance</th></tr></thead>
                  <tbody>{t.channels.map((c) => (
                    <tr key={c.id}><td>{c.name}</td><td><span className={`dir dir-${c.direction}`}>{c.direction}</span></td><td>{c.unit}</td>
                      <td className="num">{c.assured_range[0]} – {c.assured_range[1]}</td><td className="num">{c.monitored === false ? 'not monitored' : c.direction === 'output' ? `${c.tolerance_pct}%` : '—'}</td></tr>
                  ))}</tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
        <div className="panel panel-pad" style={{ display: 'grid', gap: 14 }}>
          <h2 className="label">What happens next</h2>
          <ol className="checklist" style={{ listStyle: 'decimal', paddingLeft: 18, display: 'grid', gap: 10 }}>
            <li style={{ display: 'list-item' }}>Each twin owner registers their design twin and operational twin against this configuration.</li>
            <li style={{ display: 'list-item' }}>Telemetry is connected: measured values from the asset, predictions from each twin.</li>
            <li style={{ display: 'list-item' }}>The platform verifies and bench-validates each twin, then issues assurance.</li>
            <li style={{ display: 'list-item' }}>Monitoring starts; this page becomes the live operation view.</li>
          </ol>
          <p className="hint">The platform never builds or adjusts a twin itself. Until the owners register their twins, this project holds configuration only.</p>
        </div>
      </div>
      <IntegrationPanel project={project} />
      {drawer && <ConfigDrawer project={project} onClose={() => setDrawer(false)} />}
    </div>
  )
}
