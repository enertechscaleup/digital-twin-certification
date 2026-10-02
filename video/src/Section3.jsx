import { AbsoluteFill, Easing, Img, Sequence, interpolate, staticFile, useCurrentFrame } from 'remotion'
import DATA from './s3data.json'
import { TOKENS, sans, serif } from './theme.js'

// Section 3 — The real platform (1:00–2:30). Recorded from the built platform, served
// locally and reading the locked evidence bucket (capture/section3.mjs). Calmer than
// Sections 1–2: plain cuts with short dissolves, and status colours appear here only.

const FPS = 30
const clamp = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
const FADE = 8

// Shot list (approved): start frame, length, and how each recording maps onto it.
// Beat 4 shows the ledger and integrity (4.2) before composition (4.1), so the locked Beat 4
// narration lands on each: "tamper-evident ledger" over 4.2, "which vendor's twin diverged,
// and which didn't" over 4.1. The title card is 1 s (chrome trimmed for a 2:55 cut).
const SHOTS = [
  { id: 'title', at: 0, len: 30 },
  { id: 's1_1', at: 30, len: 390, segments: [[1.6, 14.6, 1]] },
  { id: 's2_1', at: 420, len: 450 },
  { id: 's2_2', at: 870, len: 450, segments: [[0.8, 15.8, 1]] },
  { id: 's3_1', at: 1320, len: 390 },
  { id: 's3_2', at: 1710, len: 360 },
  // The re-verify round trip to the bucket (8.7 s → 15.5 s) is shortened to half a second;
  // the result on screen still reports the real time it took. While the camera is close in,
  // sharp double-resolution stills taken during the same still moments replace the capture.
  { id: 's4_2', at: 2070, len: 300, segments: [[1.1, 8.7, 1], [8.7, 15.5, 13.6], [15.5, 17.4, 1]],
    stills: [{ from: 3.0, to: 5.8, file: 'hold_ledger.png' }, { from: 15.6, to: 99, file: 'hold_integrity.png' }] },
  { id: 's4_1', at: 2370, len: 300, segments: [[1.0, 11.0, 1]] },
]
export const SECTION3_FRAMES = 2670
export const SECTION3_SHOTS = SHOTS

/** Source time (s) in a recording for a local frame, through [from, to, speed] segments. */
function sourceTime(segments, f) {
  let t = f / FPS
  for (const [from, to, speed] of segments) {
    const len = (to - from) / speed
    if (t <= len) return from + t * speed
    t -= len
  }
  const [, to] = segments[segments.length - 1]
  return to
}

function Screencast({ shot, segments, camera, stills = [] }) {
  const f = useCurrentFrame()
  const frames = DATA[shot].frames
  const t = sourceTime(segments, f)
  let i = 0
  while (i + 1 < frames.length && frames[i + 1].t <= t) i++
  const view = camera ? camera(f) : { s: 1, x: 0, y: 0 }
  const still = stills.find((w) => t >= w.from && t < w.to)
  return (
    <AbsoluteFill style={{ background: TOKENS.paper, overflow: 'hidden' }}>
      <Img src={staticFile(`s3/${shot}/${still ? still.file : frames[i].file}`)}
        style={{ width: 1920, height: 1080, transform: `translate(${view.x}px, ${view.y}px) scale(${view.s})`, transformOrigin: '0 0' }} />
    </AbsoluteFill>
  )
}

/** One screenshot per tick, dissolving into the next; ``camera`` zooms onto recorded boxes. */
function Ticked({ shot, len, hold = 0, camera, caption }) {
  const f = useCurrentFrame()
  const { shots, boxes } = DATA[shot]
  const per = (len - hold) / shots.length
  const idx = Math.min(shots.length - 1, Math.floor(f / per))
  const mix = interpolate(f - idx * per, [per - 6, per], [0, 1], clamp)
  const next = idx + 1 < shots.length ? idx + 1 : null
  const view = camera ? camera(f, boxes, idx) : { s: 1, x: 0, y: 0 }
  const img = (k, opacity) => (
    <Img key={k} src={staticFile(`s3/${shot}/${shots[k].file}`)} style={{ position: 'absolute', inset: 0, width: 1920, height: 1080, opacity }} />
  )
  return (
    <AbsoluteFill style={{ background: TOKENS.paper, overflow: 'hidden' }}>
      <AbsoluteFill style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.s})`, transformOrigin: '0 0' }}>
        {img(idx, 1)}
        {next != null && mix > 0 && img(next, mix)}
      </AbsoluteFill>
      {caption && caption(f, idx)}
    </AbsoluteFill>
  )
}

/** A view that fits ``box`` (CSS px of the 1920×1080 page) into the frame with some margin. */
function fit(box, margin = 1.25) {
  const s = Math.min(1920 / (box.width * margin), 1080 / (box.height * margin))
  const cx = box.x + box.width / 2, cy = box.y + box.height / 2
  return { s, x: 960 - cx * s, y: 540 - cy * s }
}
const unite = (a, b) => {
  const x = Math.min(a.x, b.x), y = Math.min(a.y, b.y)
  return { x, y, width: Math.max(a.x + a.width, b.x + b.width) - x, height: Math.max(a.y + a.height, b.y + b.height) - y }
}
const FULL = { s: 1, x: 0, y: 0 }
const blend = (a, b, t) => ({ s: a.s + (b.s - a.s) * t, x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t })
const ease = Easing.inOut(Easing.cubic)

// 3.1: from the full view, close in on the Shaft speed gap; when the motor flags (tick 19,
// the last shot) pan to show the gap and the motor's status card together.
const camera31 = (f, boxes, idx) => {
  const gap = fit(boxes.channel, 1.15)
  const both = fit(unite(boxes.channel, boxes.card), 1.12)
  if (idx < 5) return blend(FULL, gap, interpolate(f, [20, 70], [0, 1], { ...clamp, easing: ease }))
  return blend(gap, both, interpolate(f, [5 * 60, 5 * 60 + 36], [0, 1], { ...clamp, easing: ease }))
}

/** Like ``fit``, but places ``box`` in the left part of the frame, leaving the right for a caption. */
function fitLeft(box, share = 0.6, margin = 1.1) {
  const s = Math.min((1920 * share) / (box.width * margin), 1080 / (box.height * margin))
  const cx = box.x + box.width / 2, cy = box.y + box.height / 2
  return { s, x: 1920 * share * 0.52 - cx * s, y: 540 - cy * s }
}

// 3.2: frame the compressor's status card with its Drive speed input on the left; the
// caption takes the right, so it never covers the evidence it describes.
const camera32 = (f, boxes) => blend(FULL, fitLeft(unite(boxes.channel, boxes.card)), interpolate(f, [10, 60], [0, 1], { ...clamp, easing: ease }))

// 4.2: close on the Evidence ledger while an entry opens, pull back during the scroll,
// then close on the Evidence integrity panel through the re-verify result. Boxes are the
// panels' positions in the recording (CSS px of the 1920×1080 page).
const LEDGER = { x: 1258, y: 125, width: 364, height: 532 }
const INTEGRITY = { x: 298, y: 448, width: 432, height: 460 }
const camera42 = (f) => {
  const ledger = fit(LEDGER, 1.1), integrity = fit(INTEGRITY, 1.12)
  if (f < 140) return blend(FULL, ledger, interpolate(f, [4, 32], [0, 1], { ...clamp, easing: ease }))
  if (f < 186) return blend(ledger, FULL, interpolate(f, [140, 164], [0, 1], { ...clamp, easing: ease }))
  return blend(FULL, integrity, interpolate(f, [186, 214], [0, 1], { ...clamp, easing: ease }))
}

function Caption({ opacity, children }) {
  return (
    <div style={{ position: 'absolute', left: 1210, right: 90, top: '50%', opacity, transform: `translateY(calc(-50% + ${(1 - opacity) * 12}px))`,
      padding: '26px 30px', background: 'rgba(251,250,246,0.97)', borderLeft: `4px solid ${TOKENS.orange}`, boxShadow: '0 14px 40px rgba(23,43,56,0.18)' }}>
      <div style={{ fontFamily: serif, fontSize: 46, lineHeight: 1.1, letterSpacing: '-0.03em', color: TOKENS.ink }}>{children}</div>
    </div>
  )
}

function Title() {
  const f = useCurrentFrame()
  const inn = interpolate(f, [4, 26], [0, 1], { ...clamp, easing: Easing.bezier(0.23, 1, 0.32, 1) })
  return (
    <AbsoluteFill style={{ background: TOKENS.paper, alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ opacity: inn, transform: `translateY(${(1 - inn) * 16}px)`, textAlign: 'center' }}>
        <div style={{ fontFamily: sans, fontSize: 20, fontWeight: 800, letterSpacing: '0.18em', color: TOKENS.orange }}>TWINEVIDENCE</div>
        <div style={{ fontFamily: serif, fontSize: 120, letterSpacing: '-0.04em', color: TOKENS.ink, marginTop: 8 }}>What we built.</div>
      </div>
    </AbsoluteFill>
  )
}

function Shot({ shot }) {
  if (shot.id === 'title') return <Title />
  if (shot.segments) return <Screencast shot={shot.id} segments={shot.segments} stills={shot.stills} camera={shot.id === 's4_2' ? camera42 : null} />
  if (shot.id === 's2_1') return <Ticked shot="s2_1" len={shot.len} />
  if (shot.id === 's3_1') return <Ticked shot="s3_1" len={shot.len} hold={30} camera={camera31} />
  return (
    <Ticked shot="s3_2" len={shot.len} hold={30} camera={camera32}
      caption={(f, idx) => <Caption opacity={interpolate(f, [5 * 30, 5 * 30 + 20], [0, 1], clamp)}>Input recovered. Status stays flagged until re‑assured.</Caption>} />
  )
}

export function Section3() {
  return (
    <AbsoluteFill style={{ background: TOKENS.paper }}>
      {SHOTS.map((s, i) => (
        <Sequence key={s.id} from={s.at} durationInFrames={s.len + (i < SHOTS.length - 1 ? FADE : 0)}>
          <FadeIn first={i === 0}><Shot shot={s} /></FadeIn>
        </Sequence>
      ))}
    </AbsoluteFill>
  )
}

function FadeIn({ first, children }) {
  const f = useCurrentFrame()
  return <AbsoluteFill style={{ opacity: first ? 1 : interpolate(f, [0, FADE], [0, 1], clamp) }}>{children}</AbsoluteFill>
}
