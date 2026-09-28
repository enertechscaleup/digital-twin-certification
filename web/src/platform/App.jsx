import { useEffect, useState } from 'react'
import { Wordmark } from './components.jsx'
import { BUILT_IN } from './model/projects.js'
import { loadSaved } from './model/store.js'
import ProjectsView from './ProjectsView.jsx'
import NewProject from './NewProject.jsx'
import OperationView from './OperationView.jsx'
import CompositionView from './CompositionView.jsx'

// Screens are addressed by a bare hash token, e.g. #projects, #new, #composition,
// #oil-gas-compressor-train. Real paths replace this in F3.
const readRoute = () => (window.location.hash || '#projects').slice(1) || 'projects'

export default function App() {
  const [route, setRoute] = useState(readRoute)
  useEffect(() => {
    const on = () => { setRoute(readRoute()); window.scrollTo(0, 0) }
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])

  const project = [...BUILT_IN, ...loadSaved()].find((p) => p.project_id === route)
  const section = project ? 'projects' : route

  return (
    <>
      <div className="preview-ribbon"><b>Design preview</b> · mock data for layout review · not evidence</div>
      <header className="topbar">
        <div className="topbar-inner">
          <Wordmark />
          <span className="wordmark-product">PLATFORM</span>
          <nav className="app-nav" aria-label="Platform">
            <a href="#projects" aria-current={section === 'projects' ? 'page' : undefined}>Projects</a>
            <a href="#composition" aria-current={section === 'composition' ? 'page' : undefined}>Composition patterns</a>
            <a href="#new" aria-current={section === 'new' ? 'page' : undefined}>New project</a>
          </nav>
        </div>
      </header>
      <main>
        {project ? <OperationView key={project.project_id} project={project} />
          : route === 'new' ? <NewProject />
          : route === 'composition' ? <CompositionView />
          : <ProjectsView />}
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
