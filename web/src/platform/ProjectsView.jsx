import { useEffect, useState } from 'react'
import { ArrowUpRight, FlaskConical, Plus, ShieldCheck } from 'lucide-react'
import { finalLevels } from './api.js'
import { Graph, StatusPill } from './components.jsx'
import { PREVIEW_PROJECTS, channelCount, topology } from './model/projects.js'
import { mockRun } from './model/mockRun.js'
import { loadSaved } from './model/store.js'

function mockLatest(project) {
  const run = project.runs[0]
  const r = mockRun(project, run)
  const snap = r.snapshots[r.snapshots.length - 1].twins
  const levels = Object.fromEntries(project.twins.map((t) => [t.operational_twin_id, snap[t.key].level]))
  levels[r.sysId] = snap[r.sysId].level
  return { run, levels, system: snap[r.sysId].level, ticks: run.ticks }
}

/** Final statuses of a project's first run: from the engine's evidence, or from mock data for a preview. */
function useLatest(project) {
  const pending = project.status === 'awaiting_telemetry'
  const [real, setReal] = useState(null)
  useEffect(() => {
    if (pending || project.preview || !project.runs.length) return
    let live = true
    finalLevels(project, project.runs[0]).then((l) => live && setReal({ ...l, run: project.runs[0] })).catch(() => {})
    return () => { live = false }
  }, [project, pending])
  if (pending) return null
  return project.preview ? mockLatest(project) : real
}

function ProjectCard({ project }) {
  const pending = project.status === 'awaiting_telemetry'
  const l = useLatest(project)
  return (
    <a className="project-card" href={`#${project.project_id}`}>
      <div className="project-card-top">
        <span className="project-domain">{project.domain}</span>
        {pending ? <StatusPill level="pending" /> : l ? <StatusPill level={l.system} /> : <span className="small muted">Verifying…</span>}
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
      <div className="small muted" style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        {project.preview
          ? <span className="chip"><FlaskConical size={12} /> Preview · mock data</span>
          : !pending && <span className="chip"><ShieldCheck size={12} /> Verified evidence · {project.runs.length} runs</span>}
        {pending ? 'Awaiting twin registration and telemetry'
          : l ? `Latest run: ${l.run.name} · ${l.ticks} ticks · system ${l.system}` : ''}
      </div>
    </a>
  )
}

export default function ProjectsView({ real, error }) {
  const saved = loadSaved()
  const shown = [...(real || []), ...PREVIEW_PROJECTS]
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
          <h2 id="proj-h" className="label">{shown.length + saved.length} projects</h2>
          <a className="text-link" href="#composition">How twins compose <ArrowUpRight size={15} strokeWidth={1.8} /></a>
        </div>
        <div className="project-grid">
          {error && <div className="callout callout-warn">Could not load projects: {error}</div>}
          {!real && !error && <div className="panel panel-pad muted">Loading projects…</div>}
          {shown.map((p) => <ProjectCard key={p.project_id} project={p} />)}
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
