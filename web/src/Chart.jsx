// A small SVG line chart built for legibility on recorded video: thick lines,
// large labels, and threshold labels with a white halo so they stay readable
// where they cross data.

const M = { l: 70, r: 18, t: 16, b: 40 }

function niceTicks(min, max, count = 5) {
  const span = max - min || 1
  const step0 = span / count
  const mag = 10 ** Math.floor(Math.log10(step0))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0)
  const out = []
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(+v.toFixed(10))
  return out
}

function fmt(v) {
  const a = Math.abs(v)
  if (a >= 1000) return v.toLocaleString('en-GB', { maximumFractionDigits: 0 })
  if (a >= 100) return v.toFixed(0)
  if (a >= 10) return v.toFixed(1).replace(/\.0$/, '')
  return v.toFixed(2).replace(/0$/, '').replace(/\.0$/, '')
}

function Halo({ children, ...props }) {
  return (
    <text {...props} paintOrder="stroke" stroke="#fff" strokeWidth={5} strokeLinejoin="round">
      {children}
    </text>
  )
}

// W/H set the drawing size; the chart scales to its container, so a wide
// chart gets a wider W to keep text the same size on screen.
export default function Chart({ W = 680, H = 300, xMax, yMin, yMax, series = [], hlines = [], band, vlines = [], shade = [], yLabel, cursor }) {
  const x = (t) => M.l + ((W - M.l - M.r) * t) / Math.max(xMax, 1)
  const y = (v) => H - M.b - ((H - M.t - M.b) * (v - yMin)) / (yMax - yMin || 1)
  const colW = (W - M.l - M.r) / Math.max(xMax, 1)

  const paths = series.map((s) => {
    let d = ''
    let pen = false
    for (const [t, v] of s.points) {
      if (v == null || Number.isNaN(v)) { pen = false; continue }
      d += `${pen ? 'L' : 'M'}${x(t).toFixed(1)},${y(Math.max(yMin, Math.min(yMax, v))).toFixed(1)}`
      pen = true
    }
    return { ...s, d }
  })

  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img">
        {band && (
          <g>
            <rect x={M.l} width={W - M.l - M.r} y={y(Math.min(band.max, yMax))}
              height={Math.max(0, y(Math.max(band.min, yMin)) - y(Math.min(band.max, yMax)))} fill="#e6f4ea" />
          </g>
        )}
        {shade.map((t) => (
          <rect key={`s${t}`} x={x(t) - colW / 2} width={colW} y={M.t} height={H - M.t - M.b} fill="#eceff3" />
        ))}
        {niceTicks(yMin, yMax).map((v) => (
          <g key={`y${v}`}>
            <line x1={M.l} x2={W - M.r} y1={y(v)} y2={y(v)} stroke="#eef0f3" />
            <text x={M.l - 10} y={y(v) + 5} textAnchor="end" fontSize="16" fill="#374151">{fmt(v)}</text>
          </g>
        ))}
        {niceTicks(0, xMax, 8).map((t) => (
          <text key={`x${t}`} x={x(t)} y={H - M.b + 22} textAnchor="middle" fontSize="16" fill="#374151">{t}</text>
        ))}
        <line x1={M.l} x2={W - M.r} y1={H - M.b} y2={H - M.b} stroke="#9ca3af" />
        <text x={W - M.r} y={H - 4} textAnchor="end" fontSize="14" fill="#6b7280">tick</text>
        {yLabel && <text x={14} y={M.t + 4} fontSize="14" fill="#6b7280" transform={`rotate(-90 14 ${M.t + 4})`} textAnchor="end">{yLabel}</text>}

        {vlines.map((v, i) => (
          <g key={`v${i}`}>
            <line x1={x(v.x)} x2={x(v.x)} y1={M.t} y2={H - M.b} stroke={v.color} strokeWidth={2} strokeDasharray="3 3" />
            <Halo x={x(v.x) + 5} y={M.t + 17 + (i % 3) * 19} fontSize="15" fontWeight="700" fill={v.color}>{v.label}</Halo>
          </g>
        ))}

        {paths.map((p) => (
          <path key={p.label} d={p.d} fill="none" stroke={p.color} strokeWidth={p.width || 3}
            strokeDasharray={p.dashed ? '8 5' : undefined} strokeLinejoin="round" strokeLinecap="round" />
        ))}

        {hlines.map((h) => (
          <g key={`h${h.y}${h.label}`}>
            <line x1={M.l} x2={W - M.r} y1={y(h.y)} y2={y(h.y)} stroke={h.color} strokeWidth={3} strokeDasharray="10 6" />
            <Halo x={W - M.r - 6} y={y(h.y) - 9} textAnchor="end" fontSize="20" fontWeight="800" fill={h.color}>{h.label}</Halo>
          </g>
        ))}

        {cursor != null && <line x1={x(cursor)} x2={x(cursor)} y1={M.t} y2={H - M.b} stroke="#111827" strokeOpacity="0.25" strokeWidth={2} />}
      </svg>
    </div>
  )
}
