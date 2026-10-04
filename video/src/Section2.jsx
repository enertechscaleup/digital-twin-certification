import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from 'remotion'
import WireframeScene from '@visual/wireframe/WireframeScene.jsx'
import { keyed, projectPoint } from '@visual/wireframe/scene.js'
import { VISION, VISION_END } from './vision.js'
import { BEATS, CANDIDATES, LIBRARY, TWINS, governanceLabelPoint, sealPoints, terminusPoint } from './library.js'
import { EvidenceStore, Seal } from './seal.jsx'
import { SCENE_COLORS, TOKENS, sans, serif } from './theme.js'

// Section 1's closing system, held a moment longer while the camera pulls back, then
// cross-faded into the library. Frames past Section 1's end keep its data flowing.
const VISION_OUT = { ...VISION, camera: [...VISION.camera, { f: VISION_END + 60, pos: [2.2, 19, 38], look: [2.2, 2.2, 0.2] }] }
const clamp = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }

// Section 2 — TwinEvidence: find, test, combine. The governance layer belongs to the system
// owner; where it touches each vendor's twin it carries TwinEvidence's seal, and its pulses
// land in the evidence store at the end of the rail. Nothing of it sits inside a vendor's twin.
export function Section2() {
  const frame = useCurrentFrame()
  const { width, height } = useVideoConfig()
  const ease = Easing.bezier(0.23, 1, 0.32, 1)
  const visionOut = interpolate(frame, [18, 66], [1, 0], clamp)
  const libraryIn = interpolate(frame, [24, 72], [0, 1], clamp)
  const kickerIn = interpolate(frame, [36, 66], [0, 1], { ...clamp, easing: ease })
  const project = (p) => projectPoint(LIBRARY, frame, p, width, height)
  const live = [...CANDIDATES].reverse().find((c) => frame >= c.gov[0] && (!c.hide || frame < c.hide[1]))
  const liveIndex = CANDIDATES.indexOf(live)
  const govIn = live ? interpolate(frame, [live.gov[0] + 10, live.gov[1]], [0, 1], clamp) * (live.hide ? interpolate(frame, live.hide, [1, 0], clamp) : 1) : 0
  const govAt = live && project(governanceLabelPoint(live))
  const storeAt = live && project(terminusPoint(live))
  // The rail's four pulses arrive in turn; the store brightens as each lands.
  const arrival = (frame * LIBRARY.flow.speed * 0.8 * 4) % 1
  const glow = Math.exp(-arrival * 6)
  const recordedIn = live ? interpolate(frame, [live.gov[1] + 2, live.gov[1] + 16], [0, 1], clamp) * (live.hide ? interpolate(frame, live.hide, [1, 0], clamp) : 1) : 0

  return (
    <AbsoluteFill style={{ background: `radial-gradient(ellipse at 85% 0%, rgba(72,106,116,0.30), transparent 45%), linear-gradient(135deg, ${TOKENS.night}, ${TOKENS.nightDeep})` }}>
      {visionOut > 0 && (
        <AbsoluteFill style={{ opacity: visionOut }}>
          <WireframeScene spec={VISION_OUT} colors={SCENE_COLORS} frame={VISION_END + frame} width={width} height={height} />
        </AbsoluteFill>
      )}
      <AbsoluteFill style={{ opacity: libraryIn }}>
        <WireframeScene spec={LIBRARY} colors={SCENE_COLORS} frame={frame} width={width} height={height} />
      </AbsoluteFill>

      {/* Vendor labels: each twin belongs to its vendor. */}
      {TWINS.map((t, i) => {
        const o = LIBRARY.objects[i]
        const p = project([t.at[0], 0, t.at[1] + 1.25 * t.scale])
        const fade = interpolate(frame, [120 + i * 22, 132 + i * 22], [0, 1], clamp)
        return (
          <div key={t.id} style={{ position: 'absolute', left: p.x, top: p.y, transform: 'translate(-50%, 0)', textAlign: 'center',
            opacity: fade * keyed(o.focus, frame), fontFamily: sans, color: TOKENS.paper, whiteSpace: 'nowrap' }}>
            <div style={{ fontSize: 15, fontWeight: 800, letterSpacing: '0.16em', color: TOKENS.orangeBright }}>{t.vendor.toUpperCase()}</div>
            <div style={{ fontSize: 17, fontWeight: 600, marginTop: 2 }}>{t.label}</div>
          </div>
        )
      })}

      {/* The system owner's governance layer, labelled above its rail. */}
      {live && govIn > 0 && (
        <div style={{ position: 'absolute', left: govAt.x, top: govAt.y, transform: 'translate(-50%, -100%)', textAlign: 'center',
          opacity: govIn, fontFamily: sans, color: SCENE_COLORS.governance, whiteSpace: 'nowrap' }}>
          <div style={{ fontSize: 15, fontWeight: 800, letterSpacing: '0.16em' }}>SYSTEM OWNER · GOVERNANCE &amp; ASSURANCE</div>
          <div style={{ fontSize: 16, fontWeight: 600, marginTop: 4, color: TOKENS.paper, opacity: 0.8 }}>
            Candidate configuration {liveIndex + 1} of {CANDIDATES.length}
          </div>
        </div>
      )}

      {/* Where the layer touches each member: TwinEvidence's seal, on the governance line. */}
      {live && govIn > 0 && sealPoints(live).map((s, i) => {
        const p = project(s.at)
        const at = live.gov[0] + Math.min(18, (live.gov[1] - live.gov[0]) * 0.4) + i * 3
        const o = govIn * interpolate(frame, [at, at + 10], [0, 1], clamp)
        return <Seal key={s.id} size={30} style={{ position: 'absolute', left: p.x - 15, top: p.y - 15, opacity: o }} />
      })}

      {/* The evidence store where the rail ends: what the layer captures is recorded there. */}
      {live && govIn > 0 && (
        <div style={{ position: 'absolute', left: storeAt.x, top: storeAt.y, opacity: govIn }}>
          <div style={{ position: 'absolute', left: -35, top: -50 }}><EvidenceStore size={70} glow={frame >= live.gov[1] ? glow : 0} /></div>
          <div style={{ position: 'absolute', right: -35, bottom: 64, opacity: recordedIn, fontFamily: sans, fontSize: 17, fontWeight: 800,
            letterSpacing: '0.12em', lineHeight: 1.35, color: TOKENS.orangeBright, whiteSpace: 'nowrap', textAlign: 'right' }}>RECORDED AS<br />SYSTEM EVIDENCE</div>
        </div>
      )}
      <div style={{ position: 'absolute', left: 96, top: 92, opacity: kickerIn, transform: `translateY(${(1 - kickerIn) * 14}px)` }}>
        <div style={{ fontFamily: sans, fontSize: 20, fontWeight: 800, letterSpacing: '0.18em', color: TOKENS.orangeBright }}>TWINEVIDENCE</div>
        <div style={{ fontFamily: serif, fontSize: 40, letterSpacing: '-0.03em', color: TOKENS.paperLight, marginTop: 6 }}>A library of vendor-owned twins</div>
      </div>

      {/* Find. Test. Combine. — the current beat bright, earlier ones dimmed. */}
      <div style={{ position: 'absolute', left: 96, bottom: 84, display: 'flex', gap: 34, fontFamily: serif, fontSize: 96, letterSpacing: '-0.04em' }}>
        {BEATS.map((b, i) => {
          const inn = interpolate(frame, [b.at, b.at + 22], [0, 1], { ...clamp, easing: ease })
          const next = BEATS[i + 1]
          const dim = next ? interpolate(frame, [next.at, next.at + 16], [1, 0.32], clamp) : 1
          return (
            <span key={b.word} style={{ opacity: inn * dim, transform: `translateY(${(1 - inn) * 20}px)`, color: i === BEATS.length - 1 ? TOKENS.orangeBright : TOKENS.paperLight }}>
              {b.word}
            </span>
          )
        })}
      </div>
    </AbsoluteFill>
  )
}
