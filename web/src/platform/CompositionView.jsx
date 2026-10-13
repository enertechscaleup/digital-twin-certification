import { useState } from 'react'
import { RotateCcw } from 'lucide-react'
import { Graph, StatusPill } from './components.jsx'
import { FlaskConical } from 'lucide-react'
import { topology, twinByKey } from './model/projects.js'

const NEXT = { assured: 'flagged', flagged: 'nullified', nullified: 'assured' }
const RANK = { assured: 0, flagged: 1, nullified: 2 }

/** The engine's existing system rules, nothing more: a nullified constituent flags the
 *  system, and the system takes the status of its output constituents. */
function systemLevel(project, lv) {
  let level = 'assured'
  const why = []
  for (const t of project.twins) {
    if (lv[t.key] === 'nullified') { why.push(`${t.name} is nullified → system at least flagged`); if (RANK.flagged > RANK[level]) level = 'flagged' }
  }
  for (const k of project.composition.output_constituents) {
    const s = lv[k]
    if (s !== 'assured') { why.push(`${twinByKey(project, k).name} is its output twin → system takes ${s}`); if (RANK[s] > RANK[level]) level = s }
  }
  return { level, why }
}

function Pattern({ project, index, blurb, preview }) {
  const initial = Object.fromEntries(project.twins.map((t) => [t.key, 'assured']))
  const [lv, setLv] = useState(initial)
  const sys = systemLevel(project, lv)
  const levels = Object.fromEntries(project.twins.map((t) => [t.operational_twin_id, lv[t.key]]))
  levels[project.composition.system_twin.operational_twin_id] = sys.level
  return (
    <article className="panel" style={{ display: 'grid', alignContent: 'start' }}>
      <div className="panel-pad" style={{ display: 'grid', gap: 10, borderBottom: '1px solid var(--rule)' }}>
        <p className="kicker"><span className="accent">{index}</span><span className="sep" />{project.domain}</p>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline', flexWrap: 'wrap' }}>
          <h2 className="h3">{topology(project)}: {project.name}</h2>
          <button className="text-link" onClick={() => setLv(initial)}><RotateCcw size={13} /> Reset</button>
        </div>
        <p className="hint">{blurb}</p>
        {preview && <span className="chip" style={{ justifySelf: 'start' }}><FlaskConical size={12} /> Preview · mock project, no evidence yet</span>}
      </div>
      <div className="panel-pad"><Graph project={project} levels={levels} onPick={(k) => setLv({ ...lv, [k]: NEXT[lv[k]] })} /></div>
      <div className="panel-pad" style={{ display: 'grid', gap: 12, borderTop: '1px solid var(--rule)' }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <span className="label">System twin</span><StatusPill level={sys.level} />
          <span className="small muted">Select a twin to change its status and watch the system respond.</span>
        </div>
        <ul className="checklist">
          {sys.why.length ? sys.why.map((w) => <li key={w}>• {w}</li>) : <li className="muted">• Every constituent is assured, so the system twin is assured.</li>}
        </ul>
        <div className="table-wrap">
          <table className="grid" style={{ minWidth: 460 }}>
            <thead><tr><th>From (output)</th><th>To (input)</th><th>Unit</th></tr></thead>
            <tbody>
              {project.composition.connections.map((c, i) => {
                const a = twinByKey(project, c.from[0]), b = twinByKey(project, c.to[0])
                const ac = a.channels.find((x) => x.id === c.from[1]), bc = b.channels.find((x) => x.id === c.to[1])
                return <tr key={i}><td>{a.name} · {ac.name}</td><td>{b.name} · {bc.name}</td><td>{ac.unit}</td></tr>
              })}
            </tbody>
          </table>
        </div>
      </div>
    </article>
  )
}

export default function CompositionView({ real }) {
  const oilGas = real?.find((p) => p.project_id === 'oil-gas-compressor-train')
  const cell = real?.find((p) => p.project_id === 'amr-fulfilment-cell')
  return (
    <div className="content-width page">
      <div className="page-head">
        <p className="kicker"><span className="accent">Platform</span><span className="sep" />Composition patterns</p>
        <div className="page-head-row">
          <h1 className="display display-xl">One rule set, <em>any</em> shape.</h1>
          <p className="lead" style={{ maxWidth: 440 }}>
            A project lists its twins, which outputs feed which inputs, and which twins produce the system's outputs.
            The drawing and the cascade both follow from that list, whether the twins run in a chain or take instructions from a controller.
          </p>
        </div>
      </div>

      <section className="section">
        <div className="legend">
          <span><i className="swatch" style={{ borderColor: 'var(--assured)', background: 'var(--assured-bg)' }} /> Assured</span>
          <span><i className="swatch" style={{ borderColor: 'var(--flagged)', background: 'var(--flagged-bg)' }} /> Flagged</span>
          <span><i className="swatch" style={{ borderColor: 'var(--nullified)', background: 'var(--nullified-bg)' }} /> Nullified</span>
          <span>Arrows run from an output channel to the input it feeds</span>
        </div>
        <div className="compare">
          {oilGas ? <Pattern project={oilGas} index="Pattern A" blurb="The motor's shaft speed is the compressor's drive speed. No coordinating controller: each twin feeds the next." />
            : <div className="panel panel-pad muted">Loading the compressor train…</div>}
          {cell ? <Pattern project={cell} index="Pattern B" blurb="A dispatcher assigns tasks to two robots working side by side; both deliver to one pick station." />
            : <div className="panel panel-pad muted">Loading the fulfilment cell…</div>}
        </div>
      </section>

      <section className="section">
        <div className="callout">
          <b>Rules applied here are the engine's existing ones.</b> A nullified constituent flags the system twin; the system twin takes the status of the
          twins that produce its outputs; statuses are sticky until a twin is re-assured. The controller in pattern B follows exactly these rules.
          Controller-specific cascade rules have not been designed yet and are deliberately left out.
        </div>
      </section>
    </div>
  )
}
