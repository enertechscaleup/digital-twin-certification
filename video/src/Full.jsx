import { AbsoluteFill, Audio, Sequence, staticFile } from 'remotion'
import { Section1 } from './Section1.jsx'
import { Section2 } from './Section2.jsx'
import { SECTION2_FRAMES } from './library.js'
import { Section3, SECTION3_FRAMES, SECTION3_SHOTS } from './Section3.jsx'
import { Section4 } from './Section4.jsx'
import { CUES } from './narration.js'
import DURATIONS from './vo.json'

// The full demo video (script v3): four sections back to back, with the narration placed on
// top. Section lengths follow the recorded narration, to stay under the 3-minute cap.
const FPS = 30
const S1_FRAMES = 24 * FPS
const S4_FRAMES = 756 // the closing line holds about 1.5 s, then everything fades
export const SECTIONS = [
  { n: 1, at: 0, len: S1_FRAMES },
  { n: 2, at: S1_FRAMES, len: SECTION2_FRAMES },
  { n: 3, at: S1_FRAMES + SECTION2_FRAMES, len: SECTION3_FRAMES },
  { n: 4, at: S1_FRAMES + SECTION2_FRAMES + SECTION3_FRAMES, len: S4_FRAMES },
]
export const FULL_FRAMES = SECTIONS.reduce((n, s) => n + s.len, 0)

const GAP = 0.3 // seconds of air before a line that follows another
/** Narration cue placements in frames: each at its anchor, never before the previous line ends. */
export function placeCues() {
  let end = 0
  return CUES.map((c) => {
    const section = SECTIONS.find((s) => s.n === c.section)
    const anchor = c.shot ? SECTION3_SHOTS.find((s) => s.id === c.shot).at / FPS + 0.3 : c.anchor
    const start = Math.max(section.at / FPS + anchor, end + GAP)
    end = start + DURATIONS[c.id]
    return { ...c, from: Math.round(start * FPS), frames: Math.ceil(DURATIONS[c.id] * FPS) + 2 }
  })
}

// Music bed (Lyria, capture/music.mjs): cinematic under Sections 1–2, clean and confident from
// Section 3. Clips overlap by 3 s and cross-fade; the bed ducks under every narration line.
const CLIP = 32.7
const XF = 2.5
const B1 = SECTIONS[2].at / FPS - 0.5 // the clean bed cross-fades in under the Section 3 title
const BED = [
  { id: 'a1', at: 0 }, { id: 'a2', at: CLIP - XF },
  { id: 'b1', at: B1 }, { id: 'b2', at: B1 + CLIP - XF }, { id: 'b3', at: B1 + 2 * (CLIP - XF) }, { id: 'b4', at: B1 + 3 * (CLIP - XF) },
]
const OPEN = 0.75 // bed level with no narration
const UNDER = 0.13 // bed level under narration (about -15 dB)
const RAMP = 0.5 // seconds

function bedGain(t, cues) {
  // Duck while any line plays, ramping in RAMP seconds before it and out after it.
  let duck = 0
  for (const c of cues) {
    const s = c.from / FPS, e = (c.from + c.frames) / FPS
    const d = t < s - RAMP || t > e + RAMP ? 0 : t < s ? (t - (s - RAMP)) / RAMP : t > e ? 1 - (t - e) / RAMP : 1
    duck = Math.max(duck, d)
  }
  return OPEN + (UNDER - OPEN) * duck
}

function clipGain(t, start, end, total) {
  // Fades: crossfade in/out at clip joins, a 2 s fade-in at 0 and a 3 s fade-out at the end.
  const fadeIn = start === 0 ? Math.min(1, t / 2) : Math.min(1, (t - start) / XF)
  const fadeOut = end >= total ? Math.min(1, (total - t) / 3) : Math.min(1, (end - t) / XF)
  return Math.max(0, Math.min(fadeIn, fadeOut))
}

function MusicBed({ cues }) {
  const total = FULL_FRAMES / FPS
  return BED.map((c, i) => {
    const next = BED[i + 1]
    const end = Math.min(total, next ? next.at + XF : total, c.at + CLIP)
    return (
      <Sequence key={c.id} from={Math.round(c.at * FPS)} durationInFrames={Math.round((end - c.at) * FPS)}>
        <Audio src={staticFile(`music/${c.id}.wav`)} volume={(f) => {
          const t = c.at + f / FPS
          return clipGain(t, c.at, i === 1 ? B1 + XF : end, total) * bedGain(t, cues)
        }} />
      </Sequence>
    )
  })
}

export function Full() {
  const cues = placeCues()
  return (
    <AbsoluteFill style={{ background: '#101f2a' }}>
      {SECTIONS.map((s) => (
        <Sequence key={s.n} from={s.at} durationInFrames={s.len}>
          {s.n === 1 ? <Section1 /> : s.n === 2 ? <Section2 /> : s.n === 3 ? <Section3 /> : <Section4 length={s.len} />}
        </Sequence>
      ))}
      <MusicBed cues={cues} />
      {cues.map((c) => (
        <Sequence key={c.id} from={c.from} durationInFrames={c.frames}>
          <Audio src={staticFile(`vo/${c.id}.mp3`)} />
        </Sequence>
      ))}
    </AbsoluteFill>
  )
}
