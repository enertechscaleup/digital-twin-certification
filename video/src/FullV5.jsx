import { AbsoluteFill, Audio, Sequence, staticFile } from 'remotion'
import { Section1 } from './Section1.jsx'
import { Section2 } from './Section2.jsx'
import { SECTION2_FRAMES } from './library.js'
import { Screencast, Section3, SECTION3_FRAMES, SECTION3_SHOTS } from './Section3.jsx'
import { Section3b, NEW_FRAMES, NEW_SHOTS } from './Section3b.jsx'
import { Section4 } from './Section4.jsx'
import { CUES_V5 } from './narration.js'
import { VISION_END } from './vision.js'
import DURATIONS from './vo.json'

// The v5 draft (3:57): v4's four sections, with Section 3's Projects and Composition shots
// re-recorded from the current build, the new-project block between Section 3 and the close,
// script v5's narration, and the music bed extended to the new length. v4 (Full.jsx) is unchanged.
const FPS = 30
const S4_FRAMES = 360
const FOOTAGE = { s1_1: 's1_1_v5', s4_1: 's4_1_v5' }
const LAST = SECTION3_SHOTS.at(-1) // s4_1: its recording's last frame holds under the dissolve
const lens = [[1, VISION_END], [2, SECTION2_FRAMES], [3, SECTION3_FRAMES], ['new', NEW_FRAMES], [4, S4_FRAMES]]
export const SECTIONS_V5 = lens.map(([n, len], i) => ({ n, len, at: lens.slice(0, i).reduce((a, [, l]) => a + l, 0) }))
export const FULL_V5_FRAMES = SECTIONS_V5.reduce((n, s) => n + s.len, 0)

const GAP = 0.3
export function placeCuesV5() {
  let end = 0
  return CUES_V5.map((c) => {
    const section = SECTIONS_V5.find((s) => s.n === c.section)
    const shots = c.section === 'new' ? NEW_SHOTS : SECTION3_SHOTS
    const anchor = c.shot ? shots.find((s) => s.id === c.shot).at / FPS + 0.3 : c.anchor
    const start = Math.max(section.at / FPS + anchor, end + GAP)
    end = start + DURATIONS[c.id]
    return { ...c, from: Math.round(start * FPS), frames: Math.ceil(DURATIONS[c.id] * FPS) + 2 }
  })
}

// The bed as in v4 (Lyria clips, 2.5 s cross-fades, ducking under every line), extended: b2 and
// b3 play once more after b3, and the resolving clip b4 moves to the end, as v4 placed it.
const CLIP = 32.7
const XF = 2.5
const B1 = SECTIONS_V5[2].at / FPS - 0.5
const STEP = CLIP - XF
const BED = [
  { key: 'a1', file: 'a1', at: 0 }, { key: 'a2', file: 'a2', at: CLIP - XF },
  { key: 'b1', file: 'b1', at: B1 }, { key: 'b2', file: 'b2', at: B1 + STEP }, { key: 'b3', file: 'b3', at: B1 + 2 * STEP },
  { key: 'b2r', file: 'b2', at: B1 + 3 * STEP }, { key: 'b3r', file: 'b3', at: B1 + 4 * STEP },
  { key: 'b4', file: 'b4', at: Math.min(B1 + 5 * STEP, FULL_V5_FRAMES / FPS - CLIP) },
]
const OPEN = 0.75
const UNDER = 0.13
const RAMP = 0.5

function bedGain(t, cues) {
  let duck = 0
  for (const c of cues) {
    const s = c.from / FPS, e = (c.from + c.frames) / FPS
    const d = t < s - RAMP || t > e + RAMP ? 0 : t < s ? (t - (s - RAMP)) / RAMP : t > e ? 1 - (t - e) / RAMP : 1
    duck = Math.max(duck, d)
  }
  return OPEN + (UNDER - OPEN) * duck
}

function clipGain(t, start, end, total) {
  const fadeIn = start === 0 ? Math.min(1, t / 2) : Math.min(1, (t - start) / XF)
  const fadeOut = end >= total ? Math.min(1, (total - t) / 3) : Math.min(1, (end - t) / XF)
  return Math.max(0, Math.min(fadeIn, fadeOut))
}

function MusicBed({ cues }) {
  const total = FULL_V5_FRAMES / FPS
  return BED.map((c, i) => {
    const next = BED[i + 1]
    const end = Math.min(total, next ? next.at + XF : total, c.at + CLIP)
    return (
      <Sequence key={c.key} from={Math.round(c.at * FPS)} durationInFrames={Math.round((end - c.at) * FPS)}>
        <Audio src={staticFile(`music/${c.file}.wav`)} volume={(f) => {
          const t = c.at + f / FPS
          return clipGain(t, c.at, i === 1 ? B1 + XF : end, total) * bedGain(t, cues)
        }} />
      </Sequence>
    )
  })
}

export function FullV5() {
  const cues = placeCuesV5()
  const at = (n) => SECTIONS_V5.find((s) => s.n === n)
  return (
    <AbsoluteFill style={{ background: '#101f2a' }}>
      {/* Section 3's last frame, held under the new block's first dissolve (drawn first, so beneath it). */}
      <Sequence from={at('new').at} durationInFrames={8}>
        <Sequence from={-LAST.len}><Screencast shot={FOOTAGE.s4_1} segments={LAST.segments} /></Sequence>
      </Sequence>
      {SECTIONS_V5.map((s) => (
        <Sequence key={s.n} from={s.at} durationInFrames={s.len}>
          {s.n === 1 ? <Section1 /> : s.n === 2 ? <Section2 /> : s.n === 3 ? <Section3 footage={FOOTAGE} />
            : s.n === 'new' ? <Section3b /> : <Section4 length={s.len} />}
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
