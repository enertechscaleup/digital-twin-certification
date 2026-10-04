import { TOKENS } from './theme.js'

// TwinEvidence's mark wherever evidence is captured: a seal (a notched ring around a tick).
// Section 2 puts it where the governance layer touches each vendor's twin and on the evidence
// store; Section 3 puts the same mark on the real ledger, so the two read as one thing.

const ring = Array.from({ length: 16 }, (_, i) => {
  const a = (i / 16) * Math.PI * 2
  const r = i % 2 ? 10.2 : 11.6
  return `${12 + r * Math.cos(a)},${12 + r * Math.sin(a)}`
}).join(' ')

export function Seal({ size = 28, color = TOKENS.orangeBright, fill = 'rgba(16,31,42,0.85)', style }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" style={style} aria-hidden>
      <polygon points={ring} fill={fill} stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M7.4 12.3 L10.6 15.4 L16.8 8.9" fill="none" stroke={color} strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/** The evidence store: sealed records stacked, with the seal on top. */
export function EvidenceStore({ size = 64, color = TOKENS.orangeBright, glow = 0 }) {
  const w = size, h = size * 0.82
  const layer = (y, o) => <rect x={w * 0.08} y={y} width={w * 0.84} height={h * 0.2} rx={h * 0.05} fill="rgba(16,31,42,0.9)" stroke={color} strokeWidth="1.6" opacity={o} />
  return (
    <div style={{ position: 'relative', width: w, height: h, filter: glow ? `drop-shadow(0 0 ${8 + glow * 10}px rgba(240,128,80,${0.25 + glow * 0.45}))` : undefined }}>
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden style={{ position: 'absolute', inset: 0 }}>
        {layer(h * 0.68, 0.55)}{layer(h * 0.46, 0.8)}{layer(h * 0.24, 1)}
      </svg>
      <Seal size={size * 0.46} color={color} style={{ position: 'absolute', left: w * 0.27, top: -h * 0.12 }} />
    </div>
  )
}
