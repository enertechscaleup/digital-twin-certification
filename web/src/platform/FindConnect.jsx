import { useState } from 'react'
import { BadgeCheck, Check, Link2, Plus, Trash2, X } from 'lucide-react'
import { InputChart } from './components.jsx'
import { removeTwin, uniqueKey } from './model/draft.js'
import { REGISTRY, characteristic, connectTwin, registryEntry } from './model/registry.js'
import WireframeAsset from '../visual/wireframe/WireframeAsset.jsx'

const DEFAULT_NAME = { electric_motor: 'Motor', compressor: 'Compressor', amr: 'AMR', pick_station: 'Pick station', fleet_dispatcher: 'Fleet dispatcher', conveyor: 'Conveyor', case_packer: 'Case packer' }
const DOMAINS = ['All', ...new Set(REGISTRY.map((r) => r.domain))]

function suggestName(p, entry) {
  const base = DEFAULT_NAME[entry.asset_kind]
  const n = p.twins.filter((t) => t.registry_id === entry.registry_id).length
  return n || entry.asset_kind === 'amr' ? `${base} ${n + 1}` : base
}

export default function FindConnect({ p, update, head, addManual }) {
  const [domain, setDomain] = useState(DOMAINS.includes(p.domain) ? p.domain : 'All')
  const [selected, setSelected] = useState(null)
  const [hover, setHover] = useState(null)
  const [name, setName] = useState('')
  const [justConnected, setJustConnected] = useState(null)
  const entry = selected && registryEntry(selected)
  const list = REGISTRY.filter((r) => domain === 'All' || r.domain === domain)

  const pick = (r) => {
    if (selected === r.registry_id) { setSelected(null); return }
    setSelected(r.registry_id)
    setName(suggestName(p, r))
    setJustConnected(null)
  }
  const connect = () => {
    const label = name.trim() || suggestName(p, entry)
    update((d) => { d.twins.push(connectTwin(entry, label, uniqueKey(d, label))) })
    setJustConnected(`${label} · ${entry.name}`)
    setSelected(null)
  }

  return (
    <>
      {head}

      <div className="panel">
        <div className="panel-head">
          <h3 className="label">This project's twins · {p.twins.length}</h3>
          <span className="small muted">The system twin is derived from composition in step 5; it is never connected</span>
        </div>
        {p.twins.length === 0 ? <p className="hint panel-pad">None connected yet. Select a twin below and connect it.</p> : (
          <ul className="rule-list panel-pad" style={{ paddingBlock: 2 }}>
            {p.twins.map((t, ti) => {
              const e = t.registry_id && registryEntry(t.registry_id)
              return (
                <li key={t.key} className="slot">
                  {e ? <BadgeCheck size={16} className="ok" /> : <span className="pill pill-flagged" style={{ height: 18 }}>Unregistered</span>}
                  <span><b>{t.name}</b> <span className="muted">· {e ? `${e.name}, ${e.vendor}` : 'cannot be assured until its owner registers it'}</span></span>
                  <button className="icon-button" aria-label={`Disconnect ${t.name}`} onClick={() => update((d) => { removeTwin(d, ti) })}><Trash2 size={14} /></button>
                </li>
              )
            })}
          </ul>
        )}
        {justConnected && <div className="connected-note"><Check size={14} /> Connected {justConnected}. Its declared channels are in step 3.</div>}
      </div>

      <div className="section-head" style={{ alignItems: 'center' }}>
        <h3 className="label">Twin registry · {list.length} of {REGISTRY.length}</h3>
        <div className="seg" role="group" aria-label="Filter by domain">
          {DOMAINS.map((d) => <button key={d} aria-pressed={domain === d} onClick={() => setDomain(d)}>{d}</button>)}
        </div>
      </div>

      <div className="registry-grid">
        {list.map((r) => {
          const ch = characteristic(r)
          const count = p.twins.filter((t) => t.registry_id === r.registry_id).length
          const isSel = selected === r.registry_id
          return (
            <article key={r.registry_id} className="registry-card" aria-selected={isSel}
              onMouseEnter={() => setHover(r.registry_id)} onMouseLeave={() => setHover(null)}>
              <button className="registry-select" onClick={() => pick(r)} aria-pressed={isSel} aria-label={`${isSel ? 'Deselect' : 'Select'} ${r.name}`} />
              <WireframeAsset kind={r.asset_kind} height={150} spin={isSel || hover === r.registry_id} label={`Wireframe of ${r.name}`} />
              <div className="registry-body">
                <div className="project-card-top">
                  <span className="project-domain">{r.vendor}</span>
                  {count > 0 && <span className="chip"><Link2 size={12} /> Connected{count > 1 ? ` ×${count}` : ''}</span>}
                </div>
                <h4 className="h3" style={{ fontSize: 19 }}>{r.name}</h4>
                <p className="hint">{r.summary}</p>
                <div>
                  <div className="label" style={{ marginBottom: 2 }}>Characteristic output · {ch.channel.name} ({ch.channel.unit})</div>
                  <InputChart rows={ch.rows} tick={ch.ticks - 1} range={ch.channel.declared_range} ticks={ch.ticks} />
                </div>
                <div className="interface">
                  {['input', 'output'].map((dir) => (
                    <div key={dir}>
                      <div className="label">{dir === 'input' ? 'Inputs' : 'Outputs'}</div>
                      <ul>{r.channels.filter((c) => c.direction === dir).map((c) => <li key={c.id}>{c.name} <span className="muted">{c.unit}</span></li>)}</ul>
                    </div>
                  ))}
                </div>
                <div className="small muted">{r.registry_id} · modes: {r.modes.map((m) => m.replace('_', '-')).join(', ')}</div>
              </div>
            </article>
          )
        })}
      </div>

      {entry && (
        <div className="connect-bar" role="region" aria-label="Connect selected twin">
          <div style={{ display: 'grid', gap: 2, minWidth: 0 }}>
            <span className="label" style={{ color: 'var(--orange-bright)' }}>Selected · {entry.vendor}</span>
            <b>{entry.name}</b>
          </div>
          <label className="field" style={{ flex: '1 1 200px' }}><span style={{ color: 'rgba(244,242,235,0.6)' }}>Name in this project</span>
            <input id="connect-name" className="input compact" value={name} onChange={(e) => setName(e.target.value)} /></label>
          <button className="button button-primary" onClick={connect}><Link2 size={15} /> Connect twin</button>
          <button className="icon-button" style={{ background: 'transparent', color: 'var(--paper-light)' }} onClick={() => setSelected(null)} aria-label="Cancel"><X size={15} /></button>
        </div>
      )}

      <div className="callout">
        Can't find the twin you need? Ask its owner to register it. Meanwhile you can{' '}
        <button className="text-link" onClick={addManual}><Plus size={13} /> add an unregistered twin</button>
        {' '}and describe its channels yourself. It can be configured, but it cannot be assured until its owner registers it.
      </div>
    </>
  )
}
