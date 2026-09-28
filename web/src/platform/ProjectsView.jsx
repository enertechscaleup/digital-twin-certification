import { ArrowUpRight, Plus } from 'lucide-react'
import { Graph, StatusPill } from './components.jsx'
import { BUILT_IN, channelCount, topology } from './model/projects.js'
import { mockRun } from './model/mockRun.js'
import { loadSaved } from './model/store.js'

function latest(project) {
  const run = project.runs[0]
  const r = mockRun(project, run)
  const snap = r.snapshots[r.snapshots.length - 1].twins
  const levels = Object.fromEntries(project.twins.map((t) => [t.operational_twin_id, snap[t.key].level]))
  levels[r.sysId] = snap[r.sysId].level
  return { run, levels, system: snap[r.sysId].level }
}

function ProjectCard({ project }) {
  const pending = project.status === 'awaiting_telemetry'
  const l = pending ? null : latest(project)
  return (
    <a className="project-card" href={`#${project.project_id}`}>
      <div className="project-card-top">
        <span className="project-domain">{project.domain}</span>
        <StatusPill level={pending ? 'pending' : l.system} />
      </div>
      <div style={{ display: 'grid', gap: 8 }}>
        <h2 className="h3">{project.name}</h2>
        <p className="hint">{project.summary}</p>
      </div>
      <div className="project-thumb"><Graph project={project} levels={l?.levels} compact pending={pending} /></div>
      <div className="card-foot">
        <div className="stat-row">
          <div className="stat"><span className="label">Twins</span><b>{project.twins.length}</b></div>
          <div className="stat"><span className="label">Channels</span><b>{channelCount(project)}</b></div>
          <div className="stat"><span className="label">Composition</span><b style={{ fontSize: 12, paddingTop: 3 }}>{topology(project)}</b></div>
        </div>
        <span className="text-link">{pending ? 'View setup' : 'Open project'} <ArrowUpRight size={15} strokeWidth={1.8} /></span>
      </div>
      <div className="small muted">
        {pending ? 'Awaiting twin registration and telemetry' : `Latest run: ${l.run.name} · ${l.run.ticks} ticks · system ${l.system}`}
      </div>
    </a>
  )
}

export default function ProjectsView() {
  const saved = loadSaved()
  return (
    <div className="content-width page">
      <div className="page-head">
        <p className="kicker"><span className="accent">Platform</span><span className="sep" />Projects</p>
        <div className="page-head-row">
          <h1 className="display display-xl">Bring the twin<br />back to <em>reality</em>.</h1>
          <p className="lead" style={{ maxWidth: 420 }}>
            Each project is one asset or system: its twins, the channels they predict, what counts as a gap, and how the twins
            compose. Every screen for a project is drawn from that configuration.
          </p>
        </div>
      </div>

      <section className="section" aria-labelledby="proj-h">
        <div className="section-head">
          <h2 id="proj-h" className="label">{BUILT_IN.length + saved.length} projects</h2>
          <a className="text-link" href="#composition">How twins compose <ArrowUpRight size={15} strokeWidth={1.8} /></a>
        </div>
        <div className="project-grid">
          {BUILT_IN.map((p) => <ProjectCard key={p.project_id} project={p} />)}
          {saved.map((p) => <ProjectCard key={p.project_id} project={p} />)}
          <a className="new-card" href="#new">
            <span className="plus"><Plus size={20} /></span>
            <h2 className="h3">Start a new project</h2>
            <p className="hint" style={{ maxWidth: 300 }}>
              Name the twins and their channels, set assured ranges and tolerances, and describe how the twins connect.
              Twin owners then register their twins and connect telemetry.
            </p>
            <span className="text-link">Configure a project <ArrowUpRight size={15} strokeWidth={1.8} /></span>
          </a>
        </div>
      </section>
    </div>
  )
}
