import { useEffect, useState } from 'react'
import { ArrowLeft, ArrowRight, Check, Copy, Lock, Plus, Trash2, TriangleAlert } from 'lucide-react'
import { Graph } from './components.jsx'
import { ESCALATION, GAP_METRIC, TWIN_MODES, topology, validate } from './model/projects.js'
import { saveProject } from './model/store.js'

const slug = (s) => s.toLowerCase().trim().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '')
const DOMAINS = ['Oil & gas', 'Manufacturing', 'Warehousing & robotics', 'Power & utilities', 'Process industry', 'Other']
const STEPS = [
  ['Project', 'Name and domain'],
  ['Twins & channels', 'What each twin predicts'],
  ['Gap & tolerances', 'When twin and reality disagree'],
  ['Composition', 'How the twins connect'],
  ['Review', 'Check and create'],
]

const chan = (name, unit, direction, min, max, tolerance_pct = 5) => ({ id: slug(name), name, unit, direction, assured_range: [min, max], tolerance_pct })
const EXAMPLE = {
  name: 'Packaging line 2',
  domain: 'Manufacturing',
  summary: 'A conveyor feeds a case packer. Example values: edit them or clear the form.',
  gap: { metric: GAP_METRIC.id },
  twins: [
    { key: 'conveyor', name: 'Conveyor', role: 'product', owner: 'Conveyor vendor', twin_mode: 'observational',
      channels: [chan('Drive frequency', 'Hz', 'input', 30, 60), chan('Belt speed', 'm/s', 'output', 0.5, 1.5)] },
    { key: 'case_packer', name: 'Case packer', role: 'product', owner: 'Packer vendor', twin_mode: 'semi_autonomous',
      channels: [chan('Infeed speed', 'm/s', 'input', 0.5, 1.5), chan('Cases per minute', 'cases/min', 'output', 10, 30), chan('Motor temperature', '°C', 'output', 30, 80, 4)] },
  ],
  composition: {
    system_twin: { name: 'Packaging line 2' },
    output_constituents: ['case_packer'],
    connections: [{ from: ['conveyor', 'belt_speed'], to: ['case_packer', 'infeed_speed'] }],
  },
}
const BLANK = { name: '', domain: 'Other', summary: '', gap: { metric: GAP_METRIC.id }, twins: [], composition: { system_twin: { name: '' }, output_constituents: [], connections: [] } }

function loadDraft() {
  try { return JSON.parse(localStorage.getItem('te.draft')) || EXAMPLE } catch { return EXAMPLE }
}

export default function NewProject() {
  const [p, setP] = useState(loadDraft)
  const [step, setStep] = useState(0)
  useEffect(() => { try { localStorage.setItem('te.draft', JSON.stringify(p)) } catch { /* storage unavailable */ } }, [p])
  const issues = validate(p)
  const update = (fn) => setP((prev) => { const next = structuredClone(prev); fn(next); return next })

  return (
    <div className="content-width page">
      <div className="page-head">
        <nav className="crumbs" aria-label="Breadcrumb"><a href="#projects">Projects</a><span>/</span><span>New project</span></nav>
        <div className="page-head-row">
          <h1 className="display display-l">Configure a <em>new</em> project</h1>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button className="button button-ghost button-small" onClick={() => { setP(EXAMPLE); setStep(0) }}>Load example</button>
            <button className="button button-ghost button-small" onClick={() => { setP(BLANK); setStep(0) }}>Clear form</button>
          </div>
        </div>
      </div>

      <div className="wizard">
        <ol className="stepper" aria-label="Steps">
          {STEPS.map(([title, sub], i) => (
            <li key={title}>
              <button aria-current={step === i ? 'step' : undefined} className={i < step ? 'done' : undefined} onClick={() => setStep(i)}>
                <span className="dot">{i < step ? <Check size={13} /> : String(i + 1).padStart(2, '0')}</span>
                <span><b>{title}</b><span className="sub">{sub}</span></span>
              </button>
            </li>
          ))}
        </ol>

        <div style={{ display: 'grid', gap: 22, alignContent: 'start' }}>
          {step === 0 && <StepProject p={p} update={update} />}
          {step === 1 && <StepTwins p={p} update={update} />}
          {step === 2 && <StepGap p={p} update={update} />}
          {step === 3 && <StepComposition p={p} update={update} />}
          {step === 4 && <StepReview p={p} issues={issues} />}
          <div className="wizard-foot">
            <button className="button button-ghost" onClick={() => setStep(step - 1)} disabled={step === 0}><ArrowLeft size={15} /> Back</button>
            {step < 4
              ? <button className="button button-dark" onClick={() => setStep(step + 1)}>Continue <ArrowRight size={15} /></button>
              : <CreateButton p={p} issues={issues} />}
          </div>
        </div>
      </div>
    </div>
  )
}

function StepHead({ n, title, children }) {
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      <p className="kicker"><span className="accent">Step {n} of 5</span></p>
      <h2 className="h3" style={{ fontSize: 28 }}>{title}</h2>
      {children && <p className="lead">{children}</p>}
    </div>
  )
}

function StepProject({ p, update }) {
  return (
    <>
      <StepHead n={1} title="Name the project">A project is one asset or system whose twins you want independently assured.</StepHead>
      <div className="form-grid">
        <label className="field"><span>Project name</span>
          <input id="p-name" className="input" value={p.name} onChange={(e) => update((d) => { if (!d.composition.system_twin.name || d.composition.system_twin.name === d.name) d.composition.system_twin.name = e.target.value; d.name = e.target.value })} /></label>
        <label className="field"><span>Domain</span>
          <select id="p-domain" className="select" value={p.domain} onChange={(e) => update((d) => { d.domain = e.target.value })}>
            {DOMAINS.map((x) => <option key={x}>{x}</option>)}
          </select></label>
      </div>
      <label className="field"><span>What the system does</span>
        <textarea id="p-summary" className="textarea" value={p.summary} onChange={(e) => update((d) => { d.summary = e.target.value })} /></label>
    </>
  )
}

function StepTwins({ p, update }) {
  const addTwin = () => update((d) => {
    const n = d.twins.length + 1
    d.twins.push({ key: `twin_${n}`, name: `Twin ${n}`, role: 'product', owner: '', twin_mode: 'observational', channels: [chan('Input 1', 'unit', 'input', 0, 100), chan('Output 1', 'unit', 'output', 0, 100)] })
  })
  return (
    <>
      <StepHead n={2} title="Twins and their channels">
        List each twin the owners will register, and the channels it works with. Inputs are measured conditions; outputs are what the twin predicts and what the platform compares with reality.
      </StepHead>
      {p.twins.map((t, ti) => (
        <div key={ti} className="twin-block">
          <div className="twin-block-head">
            <div className="form-grid" style={{ flex: 1 }}>
              <label className="field"><span>Twin name</span>
                <input id={`t${ti}-name`} className="input" value={t.name} onChange={(e) => update((d) => { renameTwin(d, ti, e.target.value) })} /></label>
              <label className="field"><span>Twin owner</span>
                <input id={`t${ti}-owner`} className="input" value={t.owner} placeholder="Company that builds the twin" onChange={(e) => update((d) => { d.twins[ti].owner = e.target.value })} /></label>
            </div>
            <button className="icon-button" aria-label={`Remove ${t.name}`} onClick={() => update((d) => { removeTwin(d, ti) })}><Trash2 size={15} /></button>
          </div>
          <div style={{ display: 'flex', gap: 22, flexWrap: 'wrap', alignItems: 'end' }}>
            <div className="field"><span>Role</span>
              <div className="seg" role="group" aria-label="Role">
                {[['product', 'Product twin'], ['controller', 'Controller']].map(([v, l]) => (
                  <button key={v} aria-pressed={t.role === v} onClick={() => update((d) => { d.twins[ti].role = v })}>{l}</button>
                ))}
              </div></div>
            <div className="field"><span>Assured mode</span>
              <div className="seg" role="group" aria-label="Twin mode">
                {Object.entries(TWIN_MODES).map(([v, m]) => (
                  <button key={v} aria-pressed={t.twin_mode === v} disabled={m.disabled} title={m.note} onClick={() => update((d) => { d.twins[ti].twin_mode = v })}>{m.label}</button>
                ))}
              </div></div>
            <p className="hint" style={{ flex: '1 1 220px' }}>{TWIN_MODES[t.twin_mode].note}{t.role === 'controller' ? ' The controller role is descriptive: it follows the same cascade rules as any twin.' : ''}</p>
          </div>
          <div className="table-wrap">
            <table className="grid">
              <thead><tr><th style={{ width: '26%' }}>Channel</th><th>Direction</th><th>Unit</th><th>Assured min</th><th>Assured max</th><th>Tolerance %</th><th /></tr></thead>
              <tbody>
                {t.channels.map((c, ci) => (
                  <tr key={ci}>
                    <td><input id={`t${ti}c${ci}-name`} className="input compact" value={c.name} aria-label="Channel name" onChange={(e) => update((d) => { renameChannel(d, ti, ci, e.target.value) })} /></td>
                    <td><select id={`t${ti}c${ci}-dir`} className="select compact" value={c.direction} aria-label="Direction" onChange={(e) => update((d) => { d.twins[ti].channels[ci].direction = e.target.value })}>
                      <option value="input">Input</option><option value="output">Output</option></select></td>
                    <td><input id={`t${ti}c${ci}-unit`} className="input compact" value={c.unit} aria-label="Unit" onChange={(e) => update((d) => { d.twins[ti].channels[ci].unit = e.target.value })} /></td>
                    {[0, 1].map((k) => (
                      <td key={k}><input id={`t${ti}c${ci}-r${k}`} className="input compact num" type="number" value={c.assured_range[k]} aria-label={k ? 'Assured maximum' : 'Assured minimum'}
                        onChange={(e) => update((d) => { d.twins[ti].channels[ci].assured_range[k] = Number(e.target.value) })} /></td>
                    ))}
                    <td><input id={`t${ti}c${ci}-tol`} className="input compact num" type="number" min="0" step="0.5" value={c.direction === 'output' ? c.tolerance_pct : ''} disabled={c.direction !== 'output'} placeholder="—" aria-label="Tolerance"
                      onChange={(e) => update((d) => { d.twins[ti].channels[ci].tolerance_pct = Number(e.target.value) })} /></td>
                    <td><button className="icon-button" aria-label={`Remove ${c.name}`} onClick={() => update((d) => { removeChannel(d, ti, ci) })}><Trash2 size={14} /></button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div><button className="text-link" onClick={() => update((d) => { d.twins[ti].channels.push(chan(`Channel ${d.twins[ti].channels.length + 1}`, 'unit', 'output', 0, 100)) })}><Plus size={14} /> Add channel</button></div>
        </div>
      ))}
      <div><button className="button button-ghost" onClick={addTwin}><Plus size={15} /> Add a twin</button></div>
    </>
  )
}

function StepGap({ p, update }) {
  const outputs = p.twins.flatMap((t, ti) => t.channels.map((c, ci) => ({ t, ti, c, ci })).filter((x) => x.c.direction === 'output'))
  return (
    <>
      <StepHead n={3} title="What counts as a gap">
        For every output, the platform compares what the asset measured with what the twin predicted for the same moment. Set how far apart they may be.
      </StepHead>
      <div className="locked">
        <Lock size={16} />
        <div style={{ display: 'grid', gap: 4 }}>
          <b>{GAP_METRIC.label}: <span className="formula">{GAP_METRIC.formula}</span></b>
          <span className="muted">{GAP_METRIC.note}</span>
        </div>
      </div>
      <div className="table-wrap">
        <table className="grid" style={{ minWidth: 680 }}>
          <thead><tr><th>Compared</th><th>Tolerance %</th><th>Flagged when</th><th>Nullified when</th></tr></thead>
          <tbody>
            {outputs.map(({ t, ti, c, ci }) => (
              <tr key={`${ti}.${ci}`}>
                <td><b>{t.name} · {c.name}</b><br /><span className="small muted">Measured {c.unit} vs {t.name} twin prediction</span></td>
                <td style={{ width: 110 }}><input id={`g${ti}c${ci}`} className="input compact num" type="number" min="0" step="0.5" value={c.tolerance_pct}
                  onChange={(e) => update((d) => { d.twins[ti].channels[ci].tolerance_pct = Number(e.target.value) })} /></td>
                <td className="small">gap &gt; {c.tolerance_pct}% for {ESCALATION.flag_after} readings in a row</td>
                <td className="small">gap &gt; {c.tolerance_pct * ESCALATION.nullify_multiple}% for {ESCALATION.nullify_after} readings in a row</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="locked">
        <Lock size={16} />
        <div style={{ display: 'grid', gap: 4 }}>
          <b>Platform rules, the same for every project</b>
          <span className="muted">
            Readings are checked for sensor faults first (dropouts, a value stuck for {ESCALATION.stuck_readings} readings, jumps over {ESCALATION.spike_pct}%), then for inputs outside
            their assured range, then for gaps. A reading that cannot be evaluated pauses the counters rather than resetting them. Statuses are sticky until a twin is re-assured.
          </span>
        </div>
      </div>
    </>
  )
}

function StepComposition({ p, update }) {
  const outs = p.twins.flatMap((t) => t.channels.filter((c) => c.direction === 'output').map((c) => ({ v: `${t.key}|${c.id}`, l: `${t.name} · ${c.name} (${c.unit})` })))
  const ins = p.twins.flatMap((t) => t.channels.filter((c) => c.direction === 'input').map((c) => ({ v: `${t.key}|${c.id}`, l: `${t.name} · ${c.name} (${c.unit})` })))
  const conIssues = validate(p).filter((i) => i.includes('→') || i.includes('loop') || i.includes('connection') || i.includes('output twin') || i.includes("system's outputs"))
  return (
    <>
      <StepHead n={4} title="How the twins connect">
        Connect an output of one twin to the input it feeds. Chains, side-by-side twins and a coordinating controller are all described this way. The drawing updates as you go.
      </StepHead>
      <div className="panel">
        <div className="panel-head"><span className="label">Composition preview</span><span className="chip">{topology(p)}</span></div>
        <div className="panel-pad">{p.twins.length ? <Graph project={{ ...p, composition: { ...p.composition, system_twin: { ...p.composition.system_twin, name: p.composition.system_twin.name || p.name || 'System' } } }} pending /> : <p className="hint">Add twins in step 2 first.</p>}</div>
      </div>
      <div className="twin-block">
        <div className="twin-block-head"><h3 className="h4">Connections</h3>
          <button className="text-link" disabled={!outs.length || !ins.length} onClick={() => update((d) => { d.composition.connections.push({ from: outs[0].v.split('|'), to: ins[0].v.split('|') }) })}><Plus size={14} /> Add connection</button></div>
        {p.composition.connections.length === 0 && <p className="hint">No connections: the twins work side by side (parallel).</p>}
        {p.composition.connections.map((c, i) => (
          <div key={i} style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) auto minmax(0,1fr) auto', gap: 10, alignItems: 'center' }}>
            <select id={`c${i}-from`} className="select compact" aria-label="From output" value={c.from.join('|')} onChange={(e) => update((d) => { d.composition.connections[i].from = e.target.value.split('|') })}>
              {outs.map((o) => <option key={o.v} value={o.v}>{o.l}</option>)}</select>
            <ArrowRight size={15} color="var(--orange)" />
            <select id={`c${i}-to`} className="select compact" aria-label="To input" value={c.to.join('|')} onChange={(e) => update((d) => { d.composition.connections[i].to = e.target.value.split('|') })}>
              {ins.map((o) => <option key={o.v} value={o.v}>{o.l}</option>)}</select>
            <button className="icon-button" aria-label="Remove connection" onClick={() => update((d) => { d.composition.connections.splice(i, 1) })}><Trash2 size={14} /></button>
          </div>
        ))}
      </div>
      <div className="twin-block">
        <h3 className="h4">System twin</h3>
        <div className="form-grid">
          <label className="field"><span>System twin name</span>
            <input id="sys-name" className="input" value={p.composition.system_twin.name} onChange={(e) => update((d) => { d.composition.system_twin.name = e.target.value })} /></label>
          <fieldset className="field" style={{ border: 0, padding: 0, margin: 0 }}>
            <span>Twins whose outputs are the system's outputs</span>
            <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', paddingTop: 6 }}>
              {p.twins.map((t) => (
                <label key={t.key} style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: 12, fontWeight: 700 }}>
                  <input id={`oc-${t.key}`} type="checkbox" checked={p.composition.output_constituents.includes(t.key)} style={{ accentColor: 'var(--orange)' }}
                    onChange={(e) => update((d) => { d.composition.output_constituents = e.target.checked ? [...d.composition.output_constituents, t.key] : d.composition.output_constituents.filter((k) => k !== t.key) })} />
                  {t.name}
                </label>
              ))}
            </div>
          </fieldset>
        </div>
        <p className="hint">The system twin is flagged when any constituent is nullified, and takes the status of the twins chosen here.</p>
      </div>
      {conIssues.length > 0 && <Issues issues={conIssues} />}
    </>
  )
}

function Issues({ issues }) {
  return (
    <ul className="checklist panel panel-pad">
      {issues.map((i) => <li key={i}><TriangleAlert size={15} className="bad" style={{ flex: '0 0 auto' }} /> {i}</li>)}
    </ul>
  )
}

function StepReview({ p, issues }) {
  const json = JSON.stringify(toProject(p), null, 2)
  const [copied, setCopied] = useState(false)
  const checks = [
    ['Every twin has a name and at least one output', !issues.some((i) => i.includes('output channel') || i.includes('twin needs'))],
    ['Every channel has a unit and a valid assured range', !issues.some((i) => i.includes('range') || i.includes('unit.'))],
    ['Every output has a tolerance', !issues.some((i) => i.includes('tolerance'))],
    ['Connections run output → input, with matching units, and never loop', !issues.some((i) => i.includes('→') || i.includes('loop') || i.includes('connection'))],
    ['The system twin has at least one output twin', !issues.some((i) => i.includes("system's outputs"))],
  ]
  return (
    <>
      <StepHead n={5} title="Review and create">
        The platform checks the configuration with the same rules it uses when loading a project. Creating it records the setup only: twins are registered by their owners afterwards.
      </StepHead>
      <ul className="checklist panel panel-pad" style={{ gap: 10 }}>
        {checks.map(([t, ok]) => <li key={t}>{ok ? <Check size={15} className="ok" /> : <TriangleAlert size={15} className="bad" />} {t}</li>)}
      </ul>
      {issues.length > 0 && <Issues issues={issues} />}
      <div className="panel">
        <div className="panel-head">
          <span className="label">Project configuration</span>
          <button className="button button-ghost button-small" onClick={() => {
            navigator.clipboard?.writeText(json).then(() => setCopied(true), () => setCopied(false))
          }}><Copy size={13} /> {copied ? 'Copied' : 'Copy JSON'}</button>
        </div>
        <pre style={{ margin: 0, padding: '14px 18px', maxHeight: 360, overflow: 'auto', fontSize: 11, lineHeight: 1.6, fontFamily: 'ui-monospace, Menlo, monospace', color: 'var(--ink-mid)' }}>{json}</pre>
      </div>
    </>
  )
}

function CreateButton({ p, issues }) {
  return (
    <button className="button button-primary" disabled={issues.length > 0} onClick={() => {
      const project = toProject(p)
      saveProject(project)
      window.location.hash = project.project_id
    }}>Create project <ArrowRight size={15} /></button>
  )
}

function toProject(p) {
  const id = `${slug(p.name) || 'project'}`.replace(/_/g, '-')
  return {
    project_id: id,
    name: p.name,
    domain: p.domain,
    summary: p.summary,
    status: 'awaiting_telemetry',
    gap: p.gap,
    twins: p.twins.map((t) => ({ ...t, operational_twin_id: `${t.key.replace(/_/g, '-')}-op-001`, design_twin_id: `${t.key.replace(/_/g, '-')}-design` })),
    composition: { ...p.composition, system_twin: { name: p.composition.system_twin.name || p.name, operational_twin_id: `${id}-system-op-001` } },
    runs: [],
  }
}

// -- edits that keep ids and connections consistent ---------------------

function renameTwin(d, ti, name) {
  const t = d.twins[ti]
  const old = t.key
  t.name = name
  const key = slug(name) || `twin_${ti + 1}`
  if (d.twins.some((x, i) => i !== ti && x.key === key)) return
  t.key = key
  for (const c of d.composition.connections) { if (c.from[0] === old) c.from[0] = key; if (c.to[0] === old) c.to[0] = key }
  d.composition.output_constituents = d.composition.output_constituents.map((k) => (k === old ? key : k))
}
function removeTwin(d, ti) {
  const key = d.twins[ti].key
  d.twins.splice(ti, 1)
  d.composition.connections = d.composition.connections.filter((c) => c.from[0] !== key && c.to[0] !== key)
  d.composition.output_constituents = d.composition.output_constituents.filter((k) => k !== key)
}
function renameChannel(d, ti, ci, name) {
  const t = d.twins[ti]
  const c = t.channels[ci]
  const old = c.id
  c.name = name
  const id = slug(name) || `channel_${ci + 1}`
  if (t.channels.some((x, i) => i !== ci && x.id === id)) return
  c.id = id
  for (const k of d.composition.connections) { if (k.from[0] === t.key && k.from[1] === old) k.from[1] = id; if (k.to[0] === t.key && k.to[1] === old) k.to[1] = id }
}
function removeChannel(d, ti, ci) {
  const t = d.twins[ti]
  const id = t.channels[ci].id
  t.channels.splice(ci, 1)
  d.composition.connections = d.composition.connections.filter((k) => !(k.from[0] === t.key && k.from[1] === id) && !(k.to[0] === t.key && k.to[1] === id))
}

