import { AbsoluteFill, Audio, Sequence, staticFile } from 'remotion'
import { Section1 } from './Section1.jsx'
import { Section2 } from './Section2.jsx'
import { Section3, SECTION3_FRAMES, SECTION3_SHOTS } from './Section3.jsx'
import { Section4 } from './Section4.jsx'
import { CUES } from './narration.js'
import DURATIONS from './vo.json'

// The full demo video: four sections back to back, with the narration placed on top.
const FPS = 30
const S4_FRAMES = 26 * FPS // Section 4 trimmed from 30 s (closing hold) for a 2:55 cut
export const SECTIONS = [
  { n: 1, at: 0, len: 30 * FPS },
  { n: 2, at: 30 * FPS, len: 30 * FPS },
  { n: 3, at: 60 * FPS, len: SECTION3_FRAMES },
  { n: 4, at: 60 * FPS + SECTION3_FRAMES, len: S4_FRAMES },
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

export function Full() {
  return (
    <AbsoluteFill style={{ background: '#101f2a' }}>
      {SECTIONS.map((s) => (
        <Sequence key={s.n} from={s.at} durationInFrames={s.len}>
          {s.n === 1 ? <Section1 /> : s.n === 2 ? <Section2 /> : s.n === 3 ? <Section3 /> : <Section4 length={s.len} />}
        </Sequence>
      ))}
      {placeCues().map((c) => (
        <Sequence key={c.id} from={c.from} durationInFrames={c.frames}>
          <Audio src={staticFile(`vo/${c.id}.mp3`)} />
        </Sequence>
      ))}
    </AbsoluteFill>
  )
}
