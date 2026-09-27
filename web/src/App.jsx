import { useEffect, useMemo, useRef, useState } from 'react'
import { Anomalies, Composition, Explanations, Ledger, Recalibration, TwinCard, TwinCharts, Verification } from './panels.jsx'
import { entryTwins } from './labels.js'

const params = new URLSearchParams(window.location.search)
const TICK_MS = Number(params.get('tick_ms')) || 2000
const AUTO_REVEAL = params.has('reveal') ? Number(params.get('reveal')) : null
const MOTOR_ONLY = new Set(['motor-op-001', 'motor-design'])

async function getJson(url) {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${res.status}: ${(await res.json().catch(() => ({}))).detail || res.statusText}`)
  return res.json()
}

export default function App() {
  const [runs, setRuns] = useState(null)
  const [run, setRun] = useState(params.get('run'))
  const [meta, setMeta] = useState(null)
  const [tick, setTick] = useState(Number(params.get('tick')) || 0)
  const [view, setView] = useState(null)
  const [playing, setPlaying] = useState(false)
  const [showSystem, setShowSystem] = useState(params.get('stage') === 'system')
  const [error, setError] = useState(null)
  const cache = useRef(new Map())

  useEffect(() => {
    getJson('/api/runs').then((r) => { setRuns(r); setRun((cur) => cur || r.default) }).catch((e) => setError(e.message))
  }, [])

  useEffect(() => {
    if (!run) return
    cache.current = new Map()
    setMeta(null); setView(null)
    getJson(`/api/runs/${run}/meta`).then(setMeta).catch((e) => setError(e.message))
  }, [run])

  // Everything on screen comes from the evidence as of this tick only.
  useEffect(() => {
    if (!run || !meta) return
    const key = `${run}:${tick}`
    if (cache.current.has(key)) { setView(cache.current.get(key)); return }
    let cancelled = false
    getJson(`/api/runs/${run}/view?tick=${tick}`)
      .then((v) => { cache.current.set(key, v); if (!cancelled) setView(v) })
      .catch((e) => setError(e.message))
    return () => { cancelled = true }
  }, [run, meta, tick])

  useEffect(() => {
    if (!playing || !meta) return
    const id = setInterval(() => {
      setTick((t) => {
        if (t >= meta.ticks - 1) { setPlaying(false); return t }
        return t + 1
      })
    }, TICK_MS)
    return () => clearInterval(id)
  }, [playing, meta])

  useEffect(() => {
    if (AUTO_REVEAL != null && tick >= AUTO_REVEAL) setShowSystem(true)
  }, [tick])

  const inScope = useMemo(() => (e) => {
    if (showSystem) return true
    const ids = entryTwins(e)
    return ids.length === 0 || ids.some((id) => MOTOR_ONLY.has(id))
  }, [showSystem])

  if (error) return <div className="page"><div className="panel error">Could not load evidence: {error}</div></div>
  if (!meta || !view) return <div className="page"><div className="panel">Loading and verifying evidence…</div></div>

  const state = view.state
  const hours = view.readings.findLast((r) => r.tick === tick)?.operational_hours
  const ledger = view.ledger.filter(inScope)
  const explanations = view.explanations.filter((e) => inScope(view.ledger.find((c) => c.seq === e.payload.explains_ledger_seq) || e))

  return (
    <div className="page">
      <header className="header">
        <div className="brand">
          <h1>TwinEvidence</h1>
          <div className="sub">{meta.title} · scenario <code>{meta.scenario}</code> · seed {meta.seed} · synthetic data</div>
        </div>
        <div className="clock">
          <div className="tick">Tick {tick} <span style={{ color: 'var(--muted)', fontWeight: 600 }}>/ {meta.ticks - 1}</span></div>
          <div className="hours">{hours != null ? `${hours.toLocaleString('en-GB')} operational hours` : ''} · {state.timestamp}</div>
        </div>
      </header>

      <div className="controls">
        <button className="btn primary" onClick={() => { if (tick >= meta.ticks - 1) setTick(0); setPlaying(!playing) }}>
          {playing ? 'Pause' : tick >= meta.ticks - 1 ? 'Replay' : 'Play'}
        </button>
        <button className="btn" onClick={() => setTick((t) => Math.max(0, t - 1))} disabled={tick === 0}>◀ Step</button>
        <button className="btn" onClick={() => setTick((t) => Math.min(meta.ticks - 1, t + 1))} disabled={tick >= meta.ticks - 1}>Step ▶</button>
        <input type="range" min={0} max={meta.ticks - 1} value={tick} onChange={(e) => { setPlaying(false); setTick(Number(e.target.value)) }} />
        <button className="btn" onClick={() => setShowSystem(!showSystem)}>
          {showSystem ? 'Show motor only' : 'Connect compressor & system twin'}
        </button>
        {runs && runs.runs.length > 1 && (
          <select className="btn" value={run} onChange={(e) => { setPlaying(false); setTick(0); setRun(e.target.value) }}>
            {runs.runs.map((r) => <option key={r.run} value={r.run}>{r.title}</option>)}
          </select>
        )}
        <span className="hint" style={{ margin: 0 }}>{TICK_MS / 1000}s per tick</span>
      </div>

      <Composition twins={state.twins} showSystem={showSystem} />

      <div className="grid-3 section">
        <TwinCard id="motor-op-001" role="Product twin" twin={state.twins['motor-op-001']} />
        {showSystem ? (
          <>
            <TwinCard id="compressor-op-001" role="Product twin" twin={state.twins['compressor-op-001']} />
            <TwinCard id="compressor-system-op-001" role="System twin (motor + compressor)" twin={state.twins['compressor-system-op-001']} />
          </>
        ) : (
          <div className="panel hidden-twin" style={{ gridColumn: 'span 2' }}>
            <div style={{ fontSize: 18, fontWeight: 700 }}>Viewing the motor on its own</div>
            <p>As if it were the only monitored asset. Connect the compressor it drives to see what an isolated view misses.</p>
            <button className="btn primary" onClick={() => setShowSystem(true)}>Connect compressor & system twin</button>
          </div>
        )}
      </div>

      <Recalibration state={state} />

      <TwinCharts meta={meta} view={view} twinId="motor-op-001" tick={tick} />
      {showSystem && <TwinCharts meta={meta} view={view} twinId="compressor-op-001" tick={tick} />}

      <div className="grid-2 section">
        <Explanations items={explanations} />
        <Anomalies ledger={ledger} />
      </div>
      <div className="grid-2 section">
        <Ledger entries={ledger} head={state.ledger_head_so_far} total={state.ledger_entries_so_far} />
        <Verification meta={meta} run={run} />
      </div>
    </div>
  )
}
