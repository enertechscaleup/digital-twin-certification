import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig, Easing } from 'remotion'
import WireframeScene from '@visual/wireframe/WireframeScene.jsx'
import { VISION } from './vision.js'
import { SCENE_COLORS, TOKENS, serif, serifItalic } from './theme.js'

// Section 1 — Vision (0:00–0:24). The statement lands first and fades before the voiceover
// begins (5 s in), so the narration's technical content has the screen to itself.
export function Section1() {
  const frame = useCurrentFrame()
  const { width, height } = useVideoConfig()
  const ease = Easing.bezier(0.23, 1, 0.32, 1)
  const clamp = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
  const line1 = interpolate(frame, [8, 34], [0, 1], { ...clamp, easing: ease })
  const line2 = interpolate(frame, [36, 62], [0, 1], { ...clamp, easing: ease })
  const fade = interpolate(frame, [104, 136], [1, 0], { ...clamp, easing: Easing.inOut(Easing.cubic) })
  const sceneIn = interpolate(frame, [84, 130], [0, 1], clamp)

  return (
    <AbsoluteFill style={{ background: `radial-gradient(ellipse at 85% 0%, rgba(72,106,116,0.30), transparent 45%), linear-gradient(135deg, ${TOKENS.night}, ${TOKENS.nightDeep})` }}>
      <AbsoluteFill style={{ opacity: sceneIn }}>
        <WireframeScene spec={VISION} colors={SCENE_COLORS} frame={frame} width={width} height={height} />
      </AbsoluteFill>
      <div style={{
        position: 'absolute', left: width / 2, top: height / 2, transform: 'translate(-50%, -50%)', opacity: fade,
        fontFamily: serif, fontSize: 112, lineHeight: 1.02, letterSpacing: '-0.035em', color: TOKENS.paperLight,
        textAlign: 'center', whiteSpace: 'nowrap',
      }}>
        <div style={{ opacity: line1, transform: `translateY(${(1 - line1) * 24}px)` }}>Digital twins of everything.</div>
        <div style={{ opacity: line2, transform: `translateY(${(1 - line2) * 24}px)` }}>
          Simulated at <span style={{ fontFamily: serifItalic, fontStyle: 'italic', color: TOKENS.orangeBright }}>any scale</span>.
        </div>
      </div>
    </AbsoluteFill>
  )
}
