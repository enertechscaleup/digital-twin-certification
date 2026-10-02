import { Composition } from 'remotion'
import { Section1 } from './Section1.jsx'
import { Section2 } from './Section2.jsx'

export const FPS = 30

export function Root() {
  return (
    <>
      <Composition id="Section1" component={Section1} durationInFrames={30 * FPS} fps={FPS} width={1920} height={1080} />
      <Composition id="Section2" component={Section2} durationInFrames={30 * FPS} fps={FPS} width={1920} height={1080} />
    </>
  )
}
