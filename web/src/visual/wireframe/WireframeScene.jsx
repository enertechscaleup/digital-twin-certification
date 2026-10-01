import { useLayoutEffect, useRef } from 'react'
import * as THREE from 'three'
import { createRenderer, disposeTree } from './renderer.js'
import { buildScene, poseScene } from './scene.js'

// Frame-driven canvas for a wireframe scene (see scene.js for the scene description).
// Used by the demo video; renders synchronously whenever ``frame`` changes.

/** A frame-driven canvas for the scene. Renders synchronously on every ``frame`` change. */
export default function WireframeScene({ spec, colors, frame, width, height, fov = 32 }) {
  const ref = useRef(null)
  const state = useRef(null)

  useLayoutEffect(() => {
    const renderer = createRenderer({ preserveDrawingBuffer: true })
    if (!renderer) return
    renderer.setPixelRatio(1)
    renderer.setSize(width, height)
    ref.current.appendChild(renderer.domElement)
    const camera = new THREE.PerspectiveCamera(fov, width / height, 0.1, 200)
    const built = buildScene(spec, colors)
    state.current = { renderer, camera, built }
    return () => {
      disposeTree(built.scene)
      renderer.dispose()
      renderer.domElement.remove()
      state.current = null
    }
  }, [spec, colors, width, height, fov])

  useLayoutEffect(() => {
    const s = state.current
    if (!s) return
    poseScene(s.built, spec, s.camera, frame)
    s.renderer.render(s.built.scene, s.camera)
  }, [frame, spec, colors, width, height, fov])

  return <div ref={ref} style={{ width, height }} />
}
