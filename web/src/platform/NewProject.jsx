import { useEffect, useState } from 'react'
import { ArrowLeft, ArrowRight, BadgeCheck, Check, Copy, Lock, Plus, Search, Trash2, TriangleAlert } from 'lucide-react'
import { Graph } from './components.jsx'
import FindConnect from './FindConnect.jsx'
import { ESCALATION, GAP_METRIC, TWIN_MODES, topology, validate } from './model/projects.js'
import { connectTwin, entryLookup, loadRegistry } from './model/registry.js'
import { removeTwin, slug, uniqueKey } from './model/draft.js'
import { saveProject } from './model/store.js'
import { unitLabel } from './api.js'
const DOMAINS = ['Oil & gas', 'Manufacturing', 'Warehousing & robotics', 'Power & utilities', 'Process industry', 'Other']
const STEPS = [
  ['Project', 'Name and domain'],
  ['Find & connect', 'Choose registered twins'],
  ['Twins & channels', 'What each twin predicts'],
  ['Gap & tolerances', 'When twin and reality disagree'],
  ['Composition', 'How the twins connect'],
  ['Review', 'Check and create'],
]
const LAST = STEPS.length - 1
const DRAFT_KEY = 'te.draft.v2'

const chan = (name, unit, direction, min, max, tolerance_pct = 5) => ({ id: slug(name), name, unit, direction, assured_range: [min, max], tolerance_pct, monitored: true })

const registryEntry = entryLookup(null)

function example() {
  const packer = connectTwin(registryEntry('vendor-g/cp-30'), 'Case packer', 'case_packer')
  packer.twin_mode = 'semi_autonomous'
  packer.channels.find((c) => c.id === 'motor_temperature').tolerance_pct = 4
  return {
    name: 'Packaging line 2',
    domain: 'Manufacturing',
    summary: 'A conveyor feeds a case packer. Example values: edit them or clear the form.',
    gap: { metric: GAP_METRIC.id },
    twins: [connectTwin(registryEntry('vendor-f/conveyor-c3'), 'Conveyor', 'conveyor'), packer],
    composition: {
      system_twin: { name: 'Packaging line 2' },
      output_constituents: ['case_packer'],
      connections: [{ from: ['conveyor', 'belt_speed'], to: ['case_packer', 'infeed_speed'] }],
    },
  }
}
const BLANK = { name: '', domain: 'Other', summary: '', gap: { metric: GAP_METRIC.id }, twins: [], composition: { system_twin: { name: '' }, output_constituents: [], connections: [] } }

function loadDraft() {
  try { return JSON.parse(localStorage.getItem(DRAFT_KEY)) || example() } catch { return example() }
}

export default function NewProject() {
  const [p, setP] = useState(loadDraft)
  const [step, setStep] = useState(0)
  const [registry, setRegistry] = useState(null)
  const [registryError, setRegistryError] = useState(null)
  useEffect(() => { loadRegistry().then(setRegistry).catch((e) => setRegistryError(e.message)) }, [])
  const entryOf = entryLookup(registry)
  useEffect(() => { try { localStorage.setItem(DRAFT_KEY, JSON.stringify(p)) } catch { /* storage unavailable */ } }, [p])
  const issues = validate(p)
  const update = (fn) => setP((prev) => { const next = structuredClone(prev); fn(next); return next })
  const go = (n) => { setStep(n); window.scrollTo(0, 0) }

  return (
    <div className="content-width page">
      <div className="page-head">
        <nav className="crumbs" aria-label="Breadcrumb"><a href="#projects">Projects</a><span>/</span><span>New project</span></nav>
        <div className="page-head-row">
          <h1 className="display display-l">Configure a <em>new</em> project</h1>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button className="button button-ghost button-small" onClick={() => { setP(example()); go(0) }}>Load example</button>
            <button className="button button-ghost button-small" onClick={() => { setP(BLANK); go(0) }}>Clear form</button>
          </div>
        </div>
        <a className="text-link" href="#ingestion" style={{ justifySelf: 'start' }}>See the streaming ingestion demonstration <ArrowRight size={15} strokeWidth={2} /></a>
      </div>

      <div className="wizard">
        <ol className="stepper" aria-label="Steps">
          {STEPS.map(([title, sub], i) => (
            <li key={title}>
              <button aria-current={step === i ? 'step' : undefined} className={i < step ? 'done' : undefined} onClick={() => go(i)}>
                <span className="dot">{i < step ? <Check size={13} /> : String(i + 1).padStart(2, '0')}</span>
                <span><b>{title}</b><span className="sub">{sub}</span></span>
              </button>
            </li>
          ))}
        </ol>

        <div style={{ display: 'grid', gap: 22, alignContent: 'start', minWidth: 0 }}>
          {step === 0 && <StepProject p={p} update={update} />}
          {step === 1 && <FindConnect p={p} update={update} registry={registry} registryError={registryError} entryOf={entryOf} head={<StepHead n={2} title="Find and connect twins">
            Twins are built and owned by their vendors. Browse the registry, select the twin for each part of the system, and connect it. Its declared channels fill in the next step.
          </StepHead>} addManual={() => update((d) => { addManualTwin(d) })} />}
          {step === 2 && <StepTwins p={p} update={update} onFind={() => go(1)} entryOf={entryOf} />}
          {step === 3 && <StepGap p={p} update={update} />}
          {step === 4 && <StepComposition p={p} update={update} />}
          {step === 5 && <StepReview p={p} issues={issues} />}
          <div className="wizard-foot">
            <button className="button button-ghost" onClick={() => go(step - 1)} disabled={step === 0}><ArrowLeft size={15} /> Back</button>
            {step < LAST
              ? <button className="button button-dark" onClick={() => go(step + 1)}>Continue <ArrowRight size={15} /></button>
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
      <p className="kicker"><span className="accent">Step {n} of {STEPS.length}</span></p>
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

function StepTwins({ p, update, onFind, entryOf }) {
  return (
    <>
      <StepHead n={3} title="Twins and their channels">
        A connected twin's channels are its owner's declared interface, so their names, units and directions are fixed. Set the assured range the project will accept, within what the owner validated, and choose which channels to monitor.
      </StepHead>
      {p.twins.length === 0 && <div className="callout">No twins yet. <button className="text-link" onClick={onFind}>Find and connect twins <ArrowRight size={13} /></button></div>}
      {p.twins.map((t, ti) => {
        const entry = t.registry_id && entryOf(t.registry_id)
        return (
          <div key={ti} className="twin-block">
            <div className="twin-block-head">
              <div className="form-grid" style={{ flex: 1 }}>
                <label className="field"><span>Twin name in this project</span>
                  <input id={`t${ti}-name`} className="input" value={t.name} onChange={(e) => update((d) => { renameTwin(d, ti, e.target.value) })} /></label>
                {entry
                  ? <div className="field"><span>Registered twin</span>
                      <div className="registered"><BadgeCheck size={15} /><span><b>{entry.name}</b><br /><span className="small muted">{entry.vendor} · {entry.registry_id}</span></span></div></div>
                  : <label className="field"><span>Twin owner</span>
                      <input id={`t${ti}-owner`} className="input" value={t.owner} placeholder="Company that builds the twin" onChange={(e) => update((d) => { d.twins[ti].owner = e.target.value })} /></label>}
              </div>
              <button className="icon-button" aria-label={`Remove ${t.name}`} onClick={() => update((d) => { removeTwin(d, ti) })}><Trash2 size={15} /></button>
            </div>
            {!entry && (
              <div className="callout callout-warn">
                <b>Unregistered twin: cannot be assured.</b> Assurance needs verification against a registered twin. You can configure this slot now; assurance is refused until its owner registers the twin.
              </div>
            )}
            <div style={{ display: 'flex', gap: 22, flexWrap: 'wrap', alignItems: 'end' }}>
              <div className="field"><span>Role</span>
                <div className="seg" role="group" aria-label="Role">
                  {[['product', 'Product twin'], ['controller', 'Controller']].map(([v, l]) => (
                    <button key={v} aria-pressed={t.role === v} onClick={() => update((d) => { d.twins[ti].role = v })}>{l}</button>
                  ))}
                </div></div>
              <div className="field"><span>Assured mode</span>
                <div className="seg" role="group" aria-label="Twin mode">
                  {Object.entries(TWIN_MODES).map(([v, m]) => {
                    const unsupported = entry && !entry.modes.includes(v)
                    return <button key={v} aria-pressed={t.twin_mode === v} disabled={m.disabled || unsupported} title={unsupported ? 'Not declared by the twin owner' : m.note}
                      onClick={() => update((d) => { d.twins[ti].twin_mode = v })}>{m.label}</button>
                  })}
                </div></div>
              <p className="hint" style={{ flex: '1 1 220px' }}>{TWIN_MODES[t.twin_mode].note}{t.role === 'controller' ? ' The controller role is descriptive: it follows the same cascade rules as any twin.' : ''}</p>
            </div>
            {entry ? <LockedChannels t={t} ti={ti} update={update} /> : <OpenChannels t={t} ti={ti} update={update} />}
          </div>
        )
      })}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
        <button className="button button-ghost" onClick={onFind}><Search size={15} /> Find and connect another twin</button>
      </div>
    </>
  )
}

function LockedChannels({ t, ti, update }) {
  return (
    <div className="table-wrap">
      <table className="grid">
        <thead><tr><th>Monitor</th><th style={{ width: '24%' }}>Channel <Lock size={10} /></th><th>Direction <Lock size={10} /></th><th>Unit <Lock size={10} /></th><th>Owner validated</th><th>Assured min</th><th>Assured max</th><th>Tolerance %</th></tr></thead>
        <tbody>
          {t.channels.map((c, ci) => {
            const off = c.monitored === false
            const outside = c.assured_range[0] < c.declared_range[0] || c.assured_range[1] > c.declared_range[1]
            return (
              <tr key={c.id} style={{ opacity: off ? 0.5 : 1 }}>
                <td><input id={`t${ti}c${ci}-mon`} type="checkbox" checked={!off} aria-label={`Monitor ${c.name}`} style={{ accentColor: 'var(--orange)' }}
                  onChange={(e) => update((d) => { d.twins[ti].channels[ci].monitored = e.target.checked })} /></td>
                <td><b>{c.name}</b></td>
                <td><span className={`dir dir-${c.direction}`}>{c.direction}</span></td>
                <td>{unitLabel(c.unit)}</td>
                <td className="num muted">{c.declared_range[0]} – {c.declared_range[1]}</td>
                {[0, 1].map((k) => (
                  <td key={k}><input id={`t${ti}c${ci}-r${k}`} className="input compact num" type="number" value={c.assured_range[k]} disabled={off}
                    min={c.declared_range[0]} max={c.declared_range[1]} aria-invalid={outside} aria-label={k ? 'Assured maximum' : 'Assured minimum'}
                    style={outside ? { borderColor: 'var(--nullified)' } : undefined}
                    onChange={(e) => update((d) => { d.twins[ti].channels[ci].assured_range[k] = Number(e.target.value) })} /></td>
                ))}
                <td><input id={`t${ti}c${ci}-tol`} className="input compact num" type="number" min="0" step="0.5" value={c.direction === 'output' ? c.tolerance_pct : ''} disabled={off || c.direction !== 'output'} placeholder="—" aria-label="Tolerance"
                  onChange={(e) => update((d) => { d.twins[ti].channels[ci].tolerance_pct = Number(e.target.value) })} /></td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function OpenChannels({ t, ti, update }) {
  return (
    <>
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
    </>
  )
}

function StepGap({ p, update }) {
  const outputs = p.twins.flatMap((t, ti) => t.channels.map((c, ci) => ({ t, ti, c, ci })).filter((x) => x.c.direction === 'output' && x.c.monitored !== false))
  return (
    <>
      <StepHead n={4} title="What counts as a gap">
        For every monitored output, the platform compares what the asset measured with what the twin predicted for the same moment. Set how far apart they may be.
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
                <td><b>{t.name} · {c.name}</b><br /><span className="small muted">Measured {unitLabel(c.unit)} vs {t.name} twin prediction</span></td>
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
  const outs = p.twins.flatMap((t) => t.channels.filter((c) => c.direction === 'output').map((c) => ({ v: `${t.key}|${c.id}`, l: `${t.name} · ${c.name} (${unitLabel(c.unit)})` })))
  const ins = p.twins.flatMap((t) => t.channels.filter((c) => c.direction === 'input').map((c) => ({ v: `${t.key}|${c.id}`, l: `${t.name} · ${c.name} (${unitLabel(c.unit)})` })))
  const conIssues = validate(p).filter((i) => i.includes('→') || i.includes('loop') || i.includes('connection') || i.includes("system's outputs"))
  return (
    <>
      <StepHead n={5} title="How the twins connect">
        Connect an output of one twin to the input it feeds. Chains, side-by-side twins and a coordinating controller are all described this way. The drawing updates as you go.
      </StepHead>
      <div className="panel">
        <div className="panel-head"><span className="label">Composition preview</span><span className="chip">{topology(p)}</span></div>
        <div className="panel-pad">{p.twins.length ? <Graph project={{ ...p, composition: { ...p.composition, system_twin: { ...p.composition.system_twin, name: p.composition.system_twin.name || p.name || 'System' } } }} pending /> : <p className="hint">Connect twins in step 2 first.</p>}</div>
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
        <p className="hint">The system twin is derived from this composition; it is never connected from the registry. It is flagged when any constituent is nullified, and takes the status of the twins chosen here.</p>
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
  const unregistered = p.twins.filter((t) => !t.registry_id)
  const checks = [
    ['Every twin has a name and at least one monitored output', !issues.some((i) => i.includes('output channel') || i.includes('twin needs'))],
    ['Assured ranges are valid and within what each twin owner validated', !issues.some((i) => i.includes('range'))],
    ['Every monitored output has a tolerance', !issues.some((i) => i.includes('tolerance'))],
    ['Connections run output → input, with matching units, and never loop', !issues.some((i) => i.includes('→') || i.includes('loop') || i.includes('connection'))],
    ['The system twin has at least one output twin', !issues.some((i) => i.includes("system's outputs"))],
  ]
  return (
    <>
      <StepHead n={6} title="Review and create">
        This browser checks the configuration with its own copy of the platform's rules; the engine does not load this file yet. Creating the project saves it in this browser only, as configuration: nothing is sent to the platform and no telemetry is connected.
      </StepHead>
      <ul className="checklist panel panel-pad" style={{ gap: 10 }}>
        {checks.map(([t, ok]) => <li key={t}>{ok ? <Check size={15} className="ok" /> : <TriangleAlert size={15} className="bad" />} {t}</li>)}
        <li>{unregistered.length ? <TriangleAlert size={15} style={{ color: 'var(--flagged)' }} /> : <Check size={15} className="ok" />}
          {unregistered.length
            ? `${unregistered.map((t) => t.name).join(', ')} ${unregistered.length > 1 ? 'are' : 'is'} unregistered and cannot be assured until the owner registers the twin.`
            : 'Every twin is connected from the registry'}</li>
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

function addManualTwin(d) {
  const name = `Unregistered twin ${d.twins.filter((t) => !t.registry_id).length + 1}`
  d.twins.push({ key: uniqueKey(d, name), name, role: 'product', owner: '', twin_mode: 'observational',
    channels: [chan('Input 1', 'unit', 'input', 0, 100), chan('Output 1', 'unit', 'output', 0, 100)] })
}
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
