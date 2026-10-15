import { useEffect, useState } from 'react'
import { Wordmark } from './components.jsx'
import { loadProjects } from './api.js'
import { PREVIEW_PROJECTS } from './model/projects.js'
import { loadSaved } from './model/store.js'
import { HOME_URL } from './site.js'
import ProjectsView from './ProjectsView.jsx'
import NewProject from './NewProject.jsx'
import OperationView from './OperationView.jsx'
import EvidenceView from './EvidenceView.jsx'
import CompositionView from './CompositionView.jsx'

// Screens are addressed by a bare hash token, e.g. #projects, #new, #composition,
// #oil-gas-compressor-train.
const readRoute = () => (window.location.hash || '#projects').slice(1) || 'projects'

export default function App() {
  const [route, setRoute] = useState(readRoute)
  useEffect(() => {
    const on = () => { setRoute(readRoute()); window.scrollTo(0, 0) }
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])

  // Real projects come from the evidence API; preview projects are mock data, labelled as such.
  const [real, setReal] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => { loadProjects().then(setReal).catch((e) => setError(e.message)) }, [])

  const realProject = real?.find((p) => p.project_id === route)
  const project = realProject || [...PREVIEW_PROJECTS, ...loadSaved()].find((p) => p.project_id === route)
  const section = project || (!real && route.includes('-')) ? 'projects' : route

  return (
    <>
      <div className="preview-ribbon"><b>In development</b> · projects marked preview use mock data, not evidence</div>
      <header className="topbar">
        <div className="topbar-inner">
          <Wordmark href={HOME_URL} label="TwinEvidence home" />
          <span className="wordmark-product">PLATFORM</span>
          <nav className="app-nav" aria-label="Platform">
            <a href={HOME_URL}>Home</a>
            <a href="#projects" aria-current={section === 'projects' ? 'page' : undefined}>Projects</a>
            <a href="#composition" aria-current={section === 'composition' ? 'page' : undefined}>Composition patterns</a>
            <a href="#new" aria-current={section === 'new' ? 'page' : undefined}>New project</a>
          </nav>
        </div>
      </header>
      <main>
        {realProject ? <EvidenceView key={realProject.project_id} project={realProject} />
          : project ? <OperationView key={project.project_id} project={project} />
          : !real && !error && route.includes('-') ? <div className="content-width page muted">Loading project…</div>
          : route === 'new' ? <NewProject />
          : route === 'composition' ? <CompositionView real={real} />
          : <ProjectsView real={real} error={error} />}
      </main>
      <footer className="footer">
        <div className="content-width footer-row">
          <Wordmark />
          <span>Independent evidence for industrial autonomy. Twins are registered by their owners; the platform never builds them.</span>
        </div>
      </footer>
    </>
  )
}
