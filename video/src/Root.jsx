import { VISION_END } from './vision.js'
import { Composition } from 'remotion'
import { Section1 } from './Section1.jsx'
import { Section2 } from './Section2.jsx'
import { SECTION2_FRAMES } from './library.js'
import { Section3, SECTION3_FRAMES } from './Section3.jsx'
import { Section4 } from './Section4.jsx'
import { Full, FULL_FRAMES } from './Full.jsx'

export const FPS = 30

export function Root() {
  return (
    <>
      <Composition id="Section1" component={Section1} durationInFrames={VISION_END} fps={FPS} width={1920} height={1080} />
      <Composition id="Section2" component={Section2} durationInFrames={SECTION2_FRAMES} fps={FPS} width={1920} height={1080} />
      <Composition id="Section3" component={Section3} durationInFrames={SECTION3_FRAMES} fps={FPS} width={1920} height={1080} />
      <Composition id="Full" component={Full} durationInFrames={FULL_FRAMES} fps={FPS} width={1920} height={1080} />
      <Composition id="Section4" component={Section4} durationInFrames={360} fps={FPS} width={1920} height={1080} />
    </>
  )
}
