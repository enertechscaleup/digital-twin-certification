import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig, Easing } from 'remotion'
import WireframeScene from '@visual/wireframe/WireframeScene.jsx'
import { VISION } from './vision.js'
import { SCENE_COLORS, TOKENS, serif, serifItalic } from './theme.js'

// Section 1 — Vision (0:00–0:30). On-screen text only, no voiceover.
export function Section1() {
  const frame = useCurrentFrame()
  const { width, height } = useVideoConfig()
  const ease = Easing.bezier(0.23, 1, 0.32, 1)
  const line1 = interpolate(frame, [8, 34], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease })
  const line2 = interpolate(frame, [36, 62], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease })
  // The statement shrinks into a caption as the first asset starts drawing.
  const shrink = interpolate(frame, [100, 132], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.inOut(Easing.cubic) })
  const size = interpolate(shrink, [0, 1], [112, 38])
  const left = interpolate(shrink, [0, 1], [width / 2, 96])
  const top = interpolate(shrink, [0, 1], [height / 2, 92])
  const shift = interpolate(shrink, [0, 1], [-50, 0])
  const sceneIn = interpolate(frame, [96, 140], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })

  return (
    <AbsoluteFill style={{ background: `radial-gradient(ellipse at 85% 0%, rgba(72,106,116,0.30), transparent 45%), linear-gradient(135deg, ${TOKENS.night}, ${TOKENS.nightDeep})` }}>
      <AbsoluteFill style={{ opacity: sceneIn }}>
        <WireframeScene spec={VISION} colors={SCENE_COLORS} frame={frame} width={width} height={height} />
      </AbsoluteFill>
      <div style={{
        position: 'absolute', left, top, transform: `translate(${shift}%, ${shift}%)`,
        fontFamily: serif, fontSize: size, lineHeight: 1.02, letterSpacing: '-0.035em', color: TOKENS.paperLight,
        textAlign: shrink < 0.5 ? 'center' : 'left', whiteSpace: 'nowrap',
      }}>
        <div style={{ opacity: line1, transform: `translateY(${(1 - line1) * 24}px)` }}>Digital twins of everything.</div>
        <div style={{ opacity: line2, transform: `translateY(${(1 - line2) * 24}px)` }}>
          Simulated at <span style={{ fontFamily: serifItalic, fontStyle: 'italic', color: TOKENS.orangeBright }}>any scale</span>.
        </div>
      </div>
    </AbsoluteFill>
  )
}
