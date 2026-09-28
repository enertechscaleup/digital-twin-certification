import { X } from 'lucide-react'
import { layers, twinByKey } from './model/projects.js'
import { digitsFor, fmt } from './format.js'

export function Wordmark({ href = '#projects' }) {
  return (
    <a className="wordmark" href={href} aria-label="TwinEvidence platform home">
      <span className="wordmark-mark" aria-hidden="true"><span /><span /><span /></span>
      <span className="wordmark-type">twin<span>evidence</span></span>
    </a>
  )
}

const LEVEL_TEXT = { assured: 'Assured', flagged: 'Flagged', nullified: 'Nullified', pending: 'Awaiting telemetry' }
export const StatusPill = ({ level }) => <span className={`pill pill-${level}`}>{LEVEL_TEXT[level]}</span>

/** Composition drawing: columns come from the connections, so any topology lays itself out. */
export function Graph({ project, levels = {}, onPick, selected, compact = false, pending = false }) {
  const cols = layers(project)
  const W = compact ? 124 : 158, H = compact ? 48 : 60, GX = compact ? 52 : 92, GY = compact ? 12 : 18
  const PAD = compact ? 14 : 24, TOP = compact ? 14 : 34
  const rows = Math.max(...cols.map((c) => c.length))
  const innerH = rows * H + (rows - 1) * GY
  const pos = {}
  cols.forEach((col, i) => {
    const colH = col.length * H + (col.length - 1) * GY
    col.forEach((key, j) => { pos[key] = { x: PAD + i * (W + GX), y: TOP + (innerH - colH) / 2 + j * (H + GY) } })
  })
  const outX = PAD + cols.length * (W + GX) - GX + (compact ? 26 : 40)
  const width = outX + (compact ? 58 : 96)
  const height = TOP + innerH + (compact ? 14 : 26)
  const sys = project.composition.system_twin
  const sysLevel = pending ? 'pending' : levels[sys.operational_twin_id]

  return (
    <div className="graph">
      <svg viewBox={`0 0 ${width} ${height}`} style={{ maxWidth: width * (compact ? 1.15 : 1.35), minWidth: compact ? 0 : width * 0.8 }} role="img" aria-label={`Composition of ${project.name}`}>
        <defs>
          <marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0 L8 4 L0 8 z" fill="var(--ink-soft)" />
          </marker>
        </defs>
        {project.twins.length > 1 && (
          <>
            <rect className="boundary" x={PAD - 10} y={TOP - (compact ? 8 : 22)} width={outX - PAD + 6} height={innerH + (compact ? 16 : 34)} rx="6" />
            {!compact && (
              <text className="boundary-label" x={PAD - 2} y={TOP - 8}>
                SYSTEM TWIN · {sys.name.toUpperCase()}
                {sysLevel && <tspan fill={`var(--${sysLevel === 'pending' ? 'ink-soft' : sysLevel})`}> · {LEVEL_TEXT[sysLevel].toUpperCase()}</tspan>}
              </text>
            )}
          </>
        )}
        {project.composition.connections.map((c, i) => {
          const a = pos[c.from[0]], b = pos[c.to[0]]
          if (!a || !b) return null
          const x1 = a.x + W, y1 = a.y + H / 2, x2 = b.x - 3, y2 = b.y + H / 2, mx = (x1 + x2) / 2
          const from = twinByKey(project, c.from[0]).channels.find((x) => x.id === c.from[1])
          return (
            <g key={i}>
              <path className="edge" d={`M${x1} ${y1} C${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`} markerEnd="url(#arrow)" />
              {!compact && from && <text className="edge-label" x={mx} y={(y1 + y2) / 2 - 5} textAnchor="middle">{from.name.toLowerCase()}</text>}
            </g>
          )
        })}
        {project.composition.output_constituents.map((k) => {
          const a = pos[k]
          if (!a) return null
          return (
            <g key={k}>
              <path className="edge" d={`M${a.x + W} ${a.y + H / 2} L${outX} ${a.y + H / 2}`} markerEnd="url(#arrow)" />
              <text className="edge-label" x={outX + 6} y={a.y + H / 2 + 3}>{compact ? 'outputs' : 'system outputs'}</text>
            </g>
          )
        })}
        {project.twins.map((t) => {
          const p = pos[t.key]
          const lv = pending ? 'pending' : levels[t.operational_twin_id] || 'assured'
          return (
            <g key={t.key} className={`node is-${lv}${onPick ? ' clickable' : ''}`} transform={`translate(${p.x} ${p.y})`}
              onClick={onPick ? () => onPick(t.key) : undefined}
              role={onPick ? 'button' : undefined} tabIndex={onPick ? 0 : undefined}
              onKeyDown={onPick ? (e) => (e.key === 'Enter' || e.key === ' ') && onPick(t.key) : undefined}>
              <rect width={W} height={H} rx="4" strokeWidth={selected === t.key ? 2.4 : 1.3} />
              <text className="meta" x="12" y={compact ? 16 : 19}>{t.role === 'controller' ? 'CONTROLLER' : 'PRODUCT TWIN'}</text>
              <text className="name" x="12" y={compact ? 32 : 37}>{t.name}</text>
              {!compact && <text className="state" x="12" y="51" fill={`var(--${lv === 'pending' ? 'ink-soft' : lv})`}>{LEVEL_TEXT[lv].toUpperCase()}</text>}
            </g>
          )
        })}
      </svg>
    </div>
  )
}

const CW = 320, CH = 118, L = 34, R = 30, T = 8, B = 16

/** Gap between twin and reality, against the channel's tolerance and the nullify level. */
export function GapChart({ rows, tick, tol, ticks }) {
  const seen = rows.slice(0, tick + 1)
  const yMax = Math.max(tol * 3, ...seen.map((r) => r.gap || 0)) * 1.08
  const x = (t) => L + ((CW - L - R) * t) / (ticks - 1)
  const y = (v) => T + (CH - T - B) * (1 - v / yMax)
  const segs = []
  let cur = []
  for (const r of seen) {
    if (r.cls === 'not_evaluated') { if (cur.length) segs.push(cur); cur = []; continue }
    cur.push(`${x(r.tick).toFixed(1)},${y(r.gap).toFixed(1)}`)
  }
  if (cur.length) segs.push(cur)
  const last = seen[seen.length - 1]
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${CW} ${CH}`} aria-hidden="true">
        <rect x={L} y={y(tol)} width={CW - L - R} height={y(0) - y(tol)} fill="var(--assured-bg)" opacity="0.55" />
        {[0, tol, 2 * tol].map((v) => (
          <g key={v}>
            <line x1={L} x2={CW - R} y1={y(v)} y2={y(v)} stroke={v === 0 ? 'var(--rule-strong)' : v === tol ? 'var(--flagged)' : 'var(--nullified)'} strokeDasharray={v ? '4 3' : ''} strokeWidth="1" />
            <text x={L - 5} y={y(v) + 3} textAnchor="end">{v}%</text>
          </g>
        ))}
        <text x={CW - R + 4} y={y(tol) + 3} style={{ fill: 'var(--flagged)', fontWeight: 800 }}>tol</text>
        <text x={CW - R + 4} y={y(2 * tol) + 3} style={{ fill: 'var(--nullified)', fontWeight: 800 }}>2×</text>
        {seen.filter((r) => r.cls === 'not_evaluated').map((r) => (
          <rect key={r.tick} x={x(r.tick) - 1.5} y={CH - B - 5} width="3" height="5" fill="var(--flagged)" opacity="0.7" />
        ))}
        {segs.map((s, i) => <polyline key={i} points={s.join(' ')} fill="none" stroke="var(--ink)" strokeWidth="1.6" strokeLinejoin="round" />)}
        {last && last.cls !== 'not_evaluated' && <circle cx={x(last.tick)} cy={y(last.gap)} r="3.2" fill="var(--orange)" />}
        <text x={L} y={CH - 3}>0</text>
        <text x={CW - R} y={CH - 3} textAnchor="end">{ticks - 1}</text>
      </svg>
    </div>
  )
}

/** An input's measured value against its assured range. */
export function InputChart({ rows, tick, range, ticks }) {
  const seen = rows.slice(0, tick + 1)
  const span = range[1] - range[0]
  const lo = Math.min(range[0] - span * 0.15, ...seen.map((r) => r.physical))
  const hi = Math.max(range[1] + span * 0.15, ...seen.map((r) => r.physical))
  const x = (t) => L + ((CW - L - R) * t) / (ticks - 1)
  const y = (v) => T + (CH - T - B) * (1 - (v - lo) / (hi - lo))
  const d = digitsFor(range)
  const last = seen[seen.length - 1]
  const out = (v) => v < range[0] || v > range[1]
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${CW} ${CH}`} aria-hidden="true">
        <rect x={L} y={y(range[1])} width={CW - L - R} height={y(range[0]) - y(range[1])} fill="var(--secondary)" />
        {range.map((v) => (
          <g key={v}>
            <line x1={L} x2={CW - R} y1={y(v)} y2={y(v)} stroke="var(--rule-strong)" strokeWidth="1" />
            <text x={L - 5} y={y(v) + 3} textAnchor="end">{fmt(v, d)}</text>
          </g>
        ))}
        <text x={CW - R + 4} y={(y(range[0]) + y(range[1])) / 2 + 3}>range</text>
        <polyline points={seen.map((r) => `${x(r.tick).toFixed(1)},${y(r.physical).toFixed(1)}`).join(' ')} fill="none" stroke="var(--ink-mid)" strokeWidth="1.5" strokeLinejoin="round" />
        {seen.filter((r) => out(r.physical)).map((r) => <circle key={r.tick} cx={x(r.tick)} cy={y(r.physical)} r="2" fill="var(--flagged)" />)}
        {last && <circle cx={x(last.tick)} cy={y(last.physical)} r="3.2" fill="var(--orange)" />}
        <text x={L} y={CH - 3}>0</text>
        <text x={CW - R} y={CH - 3} textAnchor="end">{ticks - 1}</text>
      </svg>
    </div>
  )
}

/** Shows the project config that produced the screen, with the part in view highlighted. */
export function ConfigDrawer({ project, focusKey, onClose }) {
  const shown = { project_id: project.project_id, name: project.name, domain: project.domain, gap: project.gap, twins: project.twins, composition: project.composition }
  const lines = JSON.stringify(shown, null, 2).split('\n')
  let start = -1, end = -1
  if (focusKey) {
    const at = lines.findIndex((l) => l.trim() === `"key": "${focusKey}",`)
    if (at > 0) {
      start = at - 1
      const indent = lines[start].search(/\S/)
      end = lines.findIndex((l, i) => i > start && l.search(/\S/) === indent && l.trim().startsWith('}'))
    }
  }
  return (
    <>
      <div className="drawer-scrim" onClick={onClose} />
      <aside className="drawer" aria-label="Project configuration">
        <div className="panel-head">
          <div>
            <div className="label">Project configuration</div>
            <div className="h4">Every panel on this screen is drawn from this file</div>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close"><X size={16} /></button>
        </div>
        <pre>{lines.map((l, i) => <span key={i} className={i >= start && i <= end ? 'hl' : undefined}>{l}{'\n'}</span>)}</pre>
      </aside>
    </>
  )
}
