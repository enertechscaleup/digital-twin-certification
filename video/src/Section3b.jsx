import { AbsoluteFill, Img, Sequence, interpolate, staticFile, useCurrentFrame } from 'remotion'
import DATA from './s3data.json'
import IMAGES from '../public/s3/n3_df/images.json'
import DURATIONS from './vo.json'
import { CUES_V5 } from './narration.js'
import { FULL, FadeIn, Screencast, Stills, Title, blend, capped, clamp, ease, fit, localFrame, unite } from './Section3.jsx'
import { TOKENS, sans } from './theme.js'

// v5 draft: "For a new project." — after Section 3, before the close. Recorded from the local
// build of main (capture/section3b.mjs): the Connect telemetry step, a sample check, the recorded
// result of the ingestion replay, Waqar's cropped Dataflow stills, and the status view. Same
// calm style as Section 3: plain cuts with the 8-frame dissolve, cameras that close in on the
// recorded boxes. Shot lengths fit the measured narration (src/vo.json); each line lands 0.3 s in.

const FPS = 30
export const NEW_SHOTS = [
  { id: 'n0', at: 0, len: 105 }, // the title card; Section 3's last line finishes over it
  { id: 'n1', at: 105, len: 387 },
  { id: 'n2', at: 492, len: 264 },
  { id: 'n3', at: 756, len: 624 },
  { id: 'n4', at: 1380, len: 420 },
]
export const NEW_FRAMES = 1800

/** Segments mapping a recording's marks onto target local seconds: [[markFrom, markTo, targetSeconds], ...]. */
function fitted(shot, plan) {
  const m = { 0: 0, ...DATA[shot].marks }
  const at = (k) => (typeof k === 'number' ? k : m[k])
  return plan.map(([a, b, secs]) => [at(a), at(b), (at(b) - at(a)) / secs])
}

/** Camera keys [[frame, view], ...]: holds each view, easing over ``ramp`` frames into the next. */
function keyed(keys, f, ramp = 18) {
  let i = 0
  while (i + 1 < keys.length && keys[i + 1][0] <= f) i++
  const prev = i > 0 ? keys[i - 1][1] : keys[0][1]
  return blend(prev, keys[i][1], interpolate(f, [keys[i][0], keys[i][0] + ramp], [0, 1], { ...clamp, easing: ease }))
}
/** A camera view on a box, zoom capped, kept inside the recorded page (no empty edge shows). */
const view = (box, margin = 1.1) => {
  const v = capped(fit(box, margin), 1.7)
  const s = Math.max(1, v.s)
  return { s, x: Math.min(0, Math.max(1920 - 1920 * s, v.x)), y: Math.min(0, Math.max(1080 - 1080 * s, v.y)) }
}

/** A label in the style of Section 3's GemLabel (ink box, Manrope 22/700). */
export function Chip({ children, style, opacity = 1 }) {
  return (
    <div style={{ position: 'absolute', padding: '12px 20px', background: TOKENS.ink, color: TOKENS.paperLight, fontFamily: sans, fontSize: 22,
      fontWeight: 700, letterSpacing: '0.04em', whiteSpace: 'nowrap', opacity, ...style }}>{children}</div>
  )
}
const REPLAYED = 'REPLAYED SYNTHETIC DATA'

// N1: source choice, the twin and plant streams (with the synthetic-plant line), the contract,
// the comparison rule; each beat sized to the words that name it.
const N1_SEG = fitted('n1', [[0, 'to_streams', 3.6], ['to_streams', 'to_table', 3.3], ['to_table', 'to_rule', 2.4], ['to_rule', 'end', 3.6]])
function N1() {
  const f = useCurrentFrame()
  const b = DATA.n1.boxes
  const at = (k) => localFrame(N1_SEG, DATA.n1.marks[k])
  const camera = (fr) => keyed([[0, FULL], [10, view(b.source)], [at('streams'), view(b.streams, 1.08)], [at('table'), view(b.table, 1.04)], [at('rule'), view(b.rule, 1.15)]], fr)
  return <Screencast shot="n1" segments={N1_SEG} camera={camera}><Chip style={{ right: 70, top: 60 }} opacity={interpolate(f, [8, 20], [0, 1], clamp)}>{REPLAYED}</Chip></Screencast>
}

// N2: valid, then the unit changed and the hashes recomputed, then the rejection with its reason.
const N2_SEG = fitted('n2', [[0, 2.87, 3.0], [2.87, 5.32, 1.9], [5.32, 'rejected', 1.4], ['rejected', 'end', 2.5]])
function N2() {
  const b = DATA.n2.boxes
  const at = (k) => localFrame(N2_SEG, DATA.n2.marks[k])
  const sample = view(b.sample, 1.06)
  const result = view({ x: b.result.x - 10, y: b.result.y - 70, width: 980, height: 110 }, 1.06)
  return <Screencast shot="n2" segments={N2_SEG} camera={(fr) => keyed([[0, FULL], [8, sample], [at('rejected'), result]], fr)} />
}

/** One of the Dataflow stills, on paper, framed on a box of the image, with a slow push-in. */
function Picture({ index, box, from, to, len }) {
  const f = useCurrentFrame()
  const img = IMAGES.images[index]
  const [w, h] = img.size
  const a = img.boxes[from], z = img.boxes[to || from]
  const t = interpolate(f, [0, len], [0, 1], { ...clamp, easing: ease })
  const bx = { x: a.x + (z.x - a.x) * t, y: a.y + (z.y - a.y) * t, width: a.width + (z.width - a.width) * t, height: a.height + (z.height - a.height) * t }
  const s = Math.min(1920 / (bx.width * 1.12), 960 / (bx.height * 1.12))
  const clip = { x: Math.min(a.x, z.x), y: Math.min(a.y, z.y), r: Math.max(a.x + a.width, z.x + z.width), b: Math.max(a.y + a.height, z.y + z.height) }
  return (
    <AbsoluteFill style={{ background: TOKENS.paper, overflow: 'hidden' }}>
      <div style={{ position: 'absolute', left: 960 - (bx.x + bx.width / 2 - clip.x) * s, top: 560 - (bx.y + bx.height / 2 - clip.y) * s,
        width: (clip.r - clip.x) * s, height: (clip.b - clip.y) * s, overflow: 'hidden', background: '#fff', boxShadow: '0 14px 40px rgba(23,43,56,0.12)' }}>
        <Img src={staticFile(`s3/n3_df/${img.file}`)} style={{ position: 'absolute', width: w * s, height: h * s, left: -clip.x * s, top: -clip.y * s }} />
      </div>
    </AbsoluteFill>
  )
}

// N3: Pub/Sub → Dataflow (the job graph), into BigQuery (the counters), the recorded result,
// the separate feeds' row, then the result's checks. Product names appear, as text, when spoken.
const N3_CUE = CUES_V5.find((c) => c.id === 'n3')
/** Local frame at which a phrase of the N3 line is spoken (by its share of the line's characters). */
const said = (phrase) => Math.round((0.3 + DURATIONS.n3 * N3_CUE.text.indexOf(phrase) / N3_CUE.text.length) * FPS)
const N3_CUTS = [0, said('orders them'), said('We replayed'), said('as separate'), said('The decisions'), 624]
const PRODUCTS = [['Pub/Sub', said('Pub/Sub')], ['Dataflow', said('Dataflow')], ['BigQuery', said('BigQuery')], ['Cloud Storage', said('Cloud Storage')]]
function N3() {
  const f = useCurrentFrame()
  const len = (i) => N3_CUTS[i + 1] - N3_CUTS[i]
  const part = (i, node) => (
    <Sequence from={N3_CUTS[i]} durationInFrames={len(i) + (i < 4 ? 8 : 0)}><FadeIn first={i === 0}>{node}</FadeIn></Sequence>
  )
  return (
    <AbsoluteFill style={{ background: TOKENS.paper }}>
      {part(0, <Picture index={0} from="all" to="top" len={len(0)} />)}
      {part(1, <Picture index={1} from="rows" len={len(1)} />)}
      {part(2, <Stills shot="n3_app" keys={[{ f: 0, still: 0, box: 'counts', margin: 1.12 }]} />)}
      {part(3, <Stills shot="n3_app" keys={[{ f: 0, still: 1, box: ['table', 'row'], margin: 1.06 }]} />)}
      {part(4, <Stills shot="n3_app" keys={[{ f: 0, still: 0, box: 'checks', margin: 1.12 }]} />)}
      <Chip style={{ right: 70, top: 60 }} opacity={interpolate(f, [4, 16], [0, 1], clamp)}>{REPLAYED}</Chip>
      <div style={{ position: 'absolute', left: 70, bottom: 60, display: 'flex', gap: 12 }}>
        {PRODUCTS.map(([name, at]) => (
          <Chip key={name} style={{ position: 'relative' }} opacity={interpolate(f, [at - 2, at + 8], [0, 1], clamp)}>{name}</Chip>
        ))}
      </div>
    </AbsoluteFill>
  )
}

// N4: the button is pressed; the status view's first line, then Built, Designed, the go-live steps.
const N4_SEG = fitted('n4', [[0, 'open', 3.4], ['open', 'end', 10.6]])
function N4() {
  const b = DATA.n4.boxes
  const s = (x) => Math.round(x * FPS)
  // The recorded boxes are full-width blocks; each is narrowed to the text it holds.
  const left = (box, width) => ({ ...box, width })
  const camera = (fr) => keyed([[0, FULL], [s(3.4), view(left(unite(b.first, b.line), 760), 1.15)], [s(5.7), view(left(b.built, 1300), 1.06)],
    [s(8.4), view(left(b.designed, 1000), 1.08)], [s(12.0), view(b.golive, 1.06)]], fr, 22)
  return <Screencast shot="n4" segments={N4_SEG} camera={camera} />
}

function NewShot({ shot }) {
  if (shot.id === 'n0') return <Title text="For a new project." />
  if (shot.id === 'n1') return <N1 />
  if (shot.id === 'n2') return <N2 />
  if (shot.id === 'n3') return <N3 />
  return <N4 />
}

export function Section3b() {
  // No background of its own: the first shot dissolves in over Section 3's last frame (FullV5).
  return (
    <AbsoluteFill>
      {NEW_SHOTS.map((s, i) => (
        <Sequence key={s.id} from={s.at} durationInFrames={s.len + (i < NEW_SHOTS.length - 1 ? 8 : 0)}>
          <FadeIn first={false}><NewShot shot={s} /></FadeIn>
        </Sequence>
      ))}
    </AbsoluteFill>
  )
}
