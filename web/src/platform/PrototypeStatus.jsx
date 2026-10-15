import { useEffect, useRef } from 'react'
import { HOME_URL } from './site.js'
import { BUILT_AND_DEMONSTRATED, DESIGNED_NOT_BUILT, GO_LIVE_STEPS, STATUS_FIRST_LINE, STATUS_HEADING } from './prototypeStatus.js'

// Shown in place of the Connect telemetry step when "Register project and enable connection" is
// pressed. It registers nothing, stores nothing and sends nothing: it says what is built and what is not.
export default function PrototypeStatus({ onBack }) {
  const heading = useRef(null)
  useEffect(() => { heading.current?.focus(); heading.current?.scrollIntoView({ block: 'start' }) }, [])
  const linkButton = { background: 'none', border: 0, padding: 0, font: 'inherit', color: 'inherit', cursor: 'pointer', textDecoration: 'underline' }
  return (
    <div className="panel-pad" style={{ display: 'grid', gap: 18 }} data-testid="prototype-status">
      <nav className="crumbs" aria-label="Breadcrumb">
        <button type="button" style={linkButton} onClick={onBack}>Connect telemetry</button><span>/</span><span>{STATUS_HEADING}</span>
      </nav>
      <h3 ref={heading} tabIndex={-1} className="h3" style={{ margin: 0 }}>{STATUS_HEADING}</h3>
      <p style={{ margin: 0 }}><b>{STATUS_FIRST_LINE}</b></p>

      <div style={{ display: 'grid', gap: 8 }}>
        <div className="h4">Built and demonstrated</div>
        <ul className="hint" style={{ margin: 0, paddingLeft: 18, display: 'grid', gap: 4 }}>{BUILT_AND_DEMONSTRATED.map((t) => <li key={t} data-status="built">{t}</li>)}</ul>
      </div>

      <div style={{ display: 'grid', gap: 8 }}>
        <div className="h4">Designed, not built</div>
        <ul className="hint" style={{ margin: 0, paddingLeft: 18, display: 'grid', gap: 4 }}>{DESIGNED_NOT_BUILT.map((t) => <li key={t} data-status="designed">{t}</li>)}</ul>
      </div>

      <div style={{ display: 'grid', gap: 8 }}>
        <div className="h4">What a real go-live needs, in order</div>
        <div className="table-wrap">
          <table className="grid" style={{ minWidth: 0 }}>
            <thead><tr><th>#</th><th>Step</th><th>Status</th><th>Today</th></tr></thead>
            <tbody>{GO_LIVE_STEPS.map(([step, built, note], i) => (
              <tr key={step} data-status={built ? 'built' : 'not-built'}><td className="num">{i + 1}</td><td>{step}</td><td>{built ? 'Built' : 'Not built'}</td><td>{note}</td></tr>
            ))}</tbody>
          </table>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
        <button type="button" className="button button-small" onClick={onBack}>Back to Connect telemetry</button>
        <a className="text-link" href={HOME_URL}>TwinEvidence home</a>
      </div>
    </div>
  )
}
