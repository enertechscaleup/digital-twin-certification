import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from 'remotion'
import WireframeScene from '@visual/wireframe/WireframeScene.jsx'
import { VISION, VISION_END } from './vision.js'
import { SCENE_COLORS, TOKENS, sans, serif } from './theme.js'

const clamp = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }

/** The TwinEvidence wordmark, drawn as on twinevidence.com (ring with three bars, then the name). */
function Wordmark({ size = 54 }) {
  const ring = size * 1.1
  const bar = (h) => <span style={{ display: 'block', width: ring * 0.13, height: ring * h, borderRadius: 4, background: TOKENS.orangeBright }} />
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: size * 0.4, color: TOKENS.paperLight }}>
      <span style={{ width: ring, height: ring, borderRadius: '50%', border: `${Math.max(2, size * 0.05)}px solid currentColor`,
        display: 'flex', alignItems: 'flex-end', justifyContent: 'center', gap: ring * 0.11, paddingBottom: ring * 0.2, boxSizing: 'border-box' }}>
        {bar(0.3)}{bar(0.5)}{bar(0.38)}
      </span>
      <span style={{ fontFamily: sans, fontSize: size, fontWeight: 800, letterSpacing: '-0.055em' }}>
        twin<span style={{ fontWeight: 500, color: 'rgba(244,242,235,0.62)' }}>evidence</span>
      </span>
    </div>
  )
}

// Section 4 — Close (2:33–2:57). Returns to Section 1's closing frame: the same scene and
// camera, held, with data still flowing; now labelled TwinEvidence. The longer message
// in the brief is left for the narration; on screen: the wordmark and the closing line.
export function Section4({ length }) {
  const frame = useCurrentFrame()
  const { width, height, durationInFrames: full } = useVideoConfig()
  const durationInFrames = length || full
  const ease = Easing.bezier(0.23, 1, 0.32, 1)
  const sceneIn = interpolate(frame, [0, 45], [0, 1], clamp)
  const markIn = interpolate(frame, [30, 75], [0, 1], { ...clamp, easing: ease })
  // The closing line lands on the narration's last words (about 20 s in), holds, then fades.
  const line1 = interpolate(frame, [630, 660], [0, 1], { ...clamp, easing: ease })
  const line2 = interpolate(frame, [654, 684], [0, 1], { ...clamp, easing: ease })
  const out = interpolate(frame, [durationInFrames - 36, durationInFrames - 1], [1, 0], clamp)

  return (
    <AbsoluteFill style={{ background: `radial-gradient(ellipse at 85% 0%, rgba(72,106,116,0.30), transparent 45%), linear-gradient(135deg, ${TOKENS.night}, ${TOKENS.nightDeep})` }}>
      <AbsoluteFill style={{ opacity: out }}>
        <AbsoluteFill style={{ opacity: sceneIn }}>
          <WireframeScene spec={VISION} colors={SCENE_COLORS} frame={VISION_END + frame} width={width} height={height} />
        </AbsoluteFill>
        {/* Where Section 1's statement sat, the system is now labelled TwinEvidence. */}
        <div style={{ position: 'absolute', left: 96, top: 90, opacity: markIn, transform: `translateY(${(1 - markIn) * 14}px)` }}>
          <Wordmark size={48} />
        </div>
        <div style={{ position: 'absolute', left: 0, right: 0, top: 176, textAlign: 'center', fontFamily: serif, fontSize: 88,
          lineHeight: 1.05, letterSpacing: '-0.04em', color: TOKENS.paperLight }}>
          <div style={{ opacity: line1, transform: `translateY(${(1 - line1) * 22}px)` }}>Every twin, provable.</div>
          <div style={{ opacity: line2, transform: `translateY(${(1 - line2) * 22}px)` }}>
            Every system, <span style={{ fontStyle: 'italic', color: TOKENS.orangeBright }}>assured</span>.
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  )
}
