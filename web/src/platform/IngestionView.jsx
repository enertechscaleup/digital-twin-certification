import IntegrationPanel from './IntegrationPanel.jsx'

// A page of its own for the recorded streaming-ingestion demonstration, reachable from New project
// without creating a project first. No project data: the Integration panel, unchanged.
export default function IngestionView() {
  return (
    <div className="content-width page">
      <div className="page-head">
        <nav className="crumbs" aria-label="Breadcrumb"><a href="#new">New project</a><span>/</span><span>Streaming ingestion demonstration</span></nav>
        <h1 className="display display-l">Streaming ingestion demonstration</h1>
        <p className="muted" style={{ margin: 0 }}>Demonstrated on replayed synthetic data. Not live telemetry.</p>
      </div>
      <IntegrationPanel />
    </div>
  )
}
