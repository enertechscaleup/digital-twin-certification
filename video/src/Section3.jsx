import { AbsoluteFill, Easing, Img, Sequence, interpolate, staticFile, useCurrentFrame } from 'remotion'
import DATA from './s3data.json'
import { TOKENS, sans, serif } from './theme.js'

// Section 3 — The real platform (0:53–2:45). Recorded from the built platform served locally
// (capture/section3.mjs). Draft cut of the v3 script: recorded from the local lineage run; the
// final cut is re-recorded from the regenerated evidence. Calmer than Sections 1–2: plain cuts
// with short dissolves, and status colours appear here only.

const FPS = 30
const clamp = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
const FADE = 8

// Shot list (script v3, plus v4's Gemini shot): start frame, length, and how each recording maps onto it. Each beat is
// sized to its narration line (src/vo.json) plus a little air; the narration lands 0.3 s in.
// Beat 4 shows the ledger and integrity (4.2) before composition (4.1), so "which vendor's twin
// diverged, and which didn't" lands on the composition patterns.
const SHOTS = [
  { id: 'title', at: 0, len: 30 },
  { id: 'lib', at: 30, len: 140 },
  // Projects: the pointer's travel to each card runs fast; it rests a moment on each project.
  { id: 's1_1', at: 170, len: 172, marked: true },
  { id: 's2_1', at: 342, len: 330 },
  { id: 's3_1', at: 672, len: 365 },
  { id: 's3_2', at: 1037, len: 328 },
  { id: 'lin', at: 1365, len: 376 },
  { id: 'joint', at: 1741, len: 665 },
  // The ledger opens, then the integrity panel re-verifies; the pointer travel and scroll run
  // faster, the moments the camera closes in on run in real time (from the recorded marks).
  // Gemini explains it (v4): the live assistant answer, then the sealed explanation beside it.
  { id: 'gem', at: 2406, len: 480 },
  { id: 's4_2', at: 2886, len: 270, stills: [{ from: 'ledger_still', to: 'scroll', file: 'hold_ledger.png' }, { from: 'integrity_still', to: 'end', file: 'hold_integrity.png' }] },
  { id: 's4_1', at: 3156, len: 208, segments: [[1.0, 11.0, 1.44]] },
]
export const SECTION3_FRAMES = 3364
export const SECTION3_SHOTS = SHOTS

function s11Segments() {
  // Rests on each project at double speed (1.5 s); the pointer's travel fills the rest of the shot.
  const m = DATA.s1_1.marks, len = SHOTS.find((x) => x.id === 's1_1').len / FPS
  const glide = (m.on_first - m.to_first + m.on_second - m.to_second) / (len - (m.to_second - m.on_first + m.to_open - m.on_second) / 2)
  return [[m.to_first, m.on_first, glide], [m.on_first, m.to_second, 2], [m.to_second, m.on_second, glide], [m.on_second, m.to_open, 2]]
}

function s42Segments() {
  const m = DATA.s4_2.marks
  // The round trip to the evidence store is shortened to half a second; the result on screen
  // still reports the real time it took.
  return [[m.click_ledger, m.ledger_still, 3], [m.ledger_still, m.ledger_still + 2.6, 1], [m.ledger_still + 2.6, m.click_verify + 1, 3],
    [m.click_verify + 1, m.verified, (m.verified - m.click_verify - 1) / 0.5], [m.verified, m.end, 1]]
}

function gemSegments() {
  // The click plays in real time; the wait for Gemini's answer (about 13 s on the live service)
  // is shortened to 1.2 s, and a label on screen says so; the answer then holds for reading.
  const m = DATA.gem.marks, len = SHOTS.find((x) => x.id === 'gem').len / FPS
  const rest = len - m.thinking - 1.2
  return [[0, m.thinking, 1], [m.thinking, m.answered, (m.answered - m.thinking) / 1.2], [m.answered, m.end, (m.end - m.answered) / rest]]
}

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

function Screencast({ shot, segments, camera, stills = [], children }) {
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
      {children}
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
  const view = camera ? camera(f, boxes, idx, per) : { s: 1, x: 0, y: 0 }
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
const camera31 = (f, boxes, idx, per) => {
  const gap = fit(boxes.channel, 1.15)
  const both = fit(unite(boxes.channel, boxes.card), 1.12)
  if (idx < 5) return blend(FULL, gap, interpolate(f, [20, 70], [0, 1], { ...clamp, easing: ease }))
  return blend(gap, both, interpolate(f, [5 * per, 5 * per + 36], [0, 1], { ...clamp, easing: ease }))
}

// Lineage: close on the lineage panel, then, as the recalibrated version registers (tick 60),
// on the motor's chain: 1.0.0 superseded, 1.1.0 derived from it.
const cameraLin = (f, boxes, idx, per) => {
  const panel = fit(boxes.lineage, 1.08), motor = fit(boxes.motor, 1.3)
  if (f < 2 * per) return blend(FULL, panel, interpolate(f, [10, 50], [0, 1], { ...clamp, easing: ease }))
  return blend(panel, motor, interpolate(f, [2 * per + 8, 2 * per + 44], [0, 1], { ...clamp, easing: ease }))
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
function localFrame(segments, t) {
  let f = 0
  for (const [from, to, speed] of segments) {
    if (t <= to) return f + Math.max(0, t - from) / speed * FPS
    f += (to - from) / speed * FPS
  }
  return f
}
const camera42 = (f) => {
  const { boxes, marks } = DATA.s4_2
  const seg = s42Segments(), at = (k) => localFrame(seg, marks[k])
  const ledger = fit(boxes.ledger, 1.1), integrity = fit(boxes.integrity, 1.12)
  if (f < at('scroll') - 6) return blend(FULL, ledger, interpolate(f, [4, 32], [0, 1], { ...clamp, easing: ease }))
  if (f < at('verified') - 10) return blend(ledger, FULL, interpolate(f, [at('scroll') - 6, at('scroll') + 16], [0, 1], { ...clamp, easing: ease }))
  return blend(FULL, integrity, interpolate(f, [at('verified') - 10, at('verified') + 16], [0, 1], { ...clamp, easing: ease }))
}

// Gemini: close on the assistant as the question is asked, then on the live answer; as the
// narration reaches "plain-language explanation", across to the sealed Gemini explanation.
const cameraGem = (f) => {
  const { boxes, marks } = DATA.gem
  const at = (k) => localFrame(gemSegments(), marks[k])
  const panel = fit(boxes.assistant, 1.15), answer = fit(unite(boxes.question, boxes.answer), 1.08), sealed = fit(boxes.sealed, 1.3)
  if (f < at('answered')) return blend(FULL, panel, interpolate(f, [at('click_ask') + 14, at('thinking') + 6], [0, 1], { ...clamp, easing: ease }))
  if (f < 300) return blend(panel, answer, interpolate(f, [at('answered'), at('answered') + 24], [0, 1], { ...clamp, easing: ease }))
  return blend(answer, sealed, interpolate(f, [300, 336], [0, 1], { ...clamp, easing: ease }))
}

function GemLabel() {
  const f = useCurrentFrame()
  const m = DATA.gem.marks, at = (k) => localFrame(gemSegments(), m[k])
  const o = interpolate(f, [at('thinking'), at('thinking') + 6, at('answered') + 4, at('answered') + 14], [0, 1, 1, 0], clamp)
  return (
    <div style={{ position: 'absolute', right: 70, top: 60, opacity: o, padding: '12px 20px', background: TOKENS.ink, color: TOKENS.paperLight,
      fontFamily: sans, fontSize: 22, fontWeight: 700, letterSpacing: '0.04em' }}>
      Live Gemini call · {Math.round(m.answered - m.thinking)} s wait shortened
    </div>
  )
}

/** Still screenshots with a keyframed camera: keys [{f, still, box (or null for the whole page), margin}]. */
const capped = (view, max = 2.3) => (view.s <= max ? view : { s: max, x: 960 - (960 - view.x) / view.s * max, y: 540 - (540 - view.y) / view.s * max })
function Stills({ shot, keys }) {
  const f = useCurrentFrame()
  const { stills } = DATA[shot]
  const box = (k) => (Array.isArray(k.box) ? k.box.map((b) => stills[k.still].boxes[b]).reduce(unite) : stills[k.still].boxes[k.box])
  const views = keys.map((k) => (k.box ? capped(fit(box(k), k.margin ?? 1.15)) : FULL))
  let i = 0
  while (i + 1 < keys.length && keys[i + 1].f <= f) i++
  const k0 = keys[i], k1 = keys[i + 1]
  const t = k1 ? interpolate(f, [k0.f + (k0.hold ?? 0), k1.f], [0, 1], { ...clamp, easing: ease }) : 0
  const sameStill = !k1 || k1.still === k0.still
  const view = sameStill ? blend(views[i], k1 ? views[i + 1] : views[i], t) : views[t < 0.5 ? i : i + 1]
  const shown = sameStill ? k0.still : t < 0.5 ? k0.still : k1.still
  const dip = !sameStill ? 1 - Math.sin(Math.PI * Math.min(1, t)) * 0.9 : 1
  return (
    <AbsoluteFill style={{ background: TOKENS.paper, overflow: 'hidden' }}>
      <AbsoluteFill style={{ opacity: dip, transform: `translate(${view.x}px, ${view.y}px) scale(${view.s})`, transformOrigin: '0 0' }}>
        <Img src={staticFile(`s3/${shot}/${stills[shown].file}`)} style={{ width: 1920, height: 1080 }} />
      </AbsoluteFill>
    </AbsoluteFill>
  )
}

// The library: the two registered twins, then close on their permanent identities.
const LIB_KEYS = [{ f: 0, still: 0, box: null }, { f: 18, still: 0, box: 'cards', margin: 1.06, hold: 0 }, { f: 64, still: 0, box: 'cards', margin: 1.06 },
  { f: 104, still: 0, box: ['id0', 'id1'], margin: 1.04 }]
// The joint run: the panel, the build test (pass), the post-recalibration test (interface fails,
// the panel carries the count), then the system twin with its named reason.
const JOINT_KEYS = [{ f: 0, still: 0, box: null }, { f: 50, still: 0, box: 'panel', margin: 1.04 }, { f: 150, still: 0, box: 'panel', margin: 1.04 },
  { f: 190, still: 0, box: 'build', margin: 1.12 }, { f: 340, still: 0, box: 'build', margin: 1.12 }, { f: 385, still: 0, box: 'after', margin: 1.12 },
  { f: 415, still: 0, box: 'after', margin: 1.12 }, { f: 455, still: 0, box: 'interface', margin: 1.15 }, { f: 495, still: 0, box: 'interface', margin: 1.15 },
  { f: 525, still: 1, box: 'system', margin: 1.25 }]

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
  if (shot.id === 'lib') return <Stills shot="lib" keys={LIB_KEYS} />
  if (shot.id === 'joint') return <Stills shot="joint" keys={JOINT_KEYS} />
  if (shot.id === 's4_2') {
    const m = DATA.s4_2.marks
    return <Screencast shot="s4_2" segments={s42Segments()} camera={camera42}
      stills={shot.stills.map((w) => ({ from: m[w.from], to: m[w.to], file: w.file }))} />
  }
  if (shot.id === 'gem') {
    return <Screencast shot="gem" segments={gemSegments()} camera={cameraGem}
      stills={[{ from: DATA.gem.marks.answer_still, to: DATA.gem.marks.end + 1, file: 'hold_answer.png' }]}><GemLabel /></Screencast>
  }
  if (shot.id === 's1_1') return <Screencast shot="s1_1" segments={s11Segments()} />
  if (shot.segments) return <Screencast shot={shot.id} segments={shot.segments} />
  if (shot.id === 's2_1') return <Ticked shot="s2_1" len={shot.len} />
  if (shot.id === 'lin') return <Ticked shot="lin" len={shot.len} hold={30} camera={cameraLin} />
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
