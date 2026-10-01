import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { buildAsset } from './assets.js'
import { applyDraw, createRenderer, disposeTree, lineParts, readTokens } from './renderer.js'

// One asset per canvas, as in the platform's twin registry. The demo video draws the
// same geometry (assets.js) through WireframeScene. Colours come from the page's tokens.

/**
 * kind:   an ASSET_KINDS key (e.g. "electric_motor")
 * height: canvas height in px (width fills the container)
 * spin:   slow turntable rotation (ignored when the viewer prefers reduced motion)
 * yaw:    fixed rotation in radians, for scripted camera moves (overrides spin)
 * draw:   0–1, how much of the outline is drawn (1 = complete)
 */
export default function WireframeAsset({ kind, height = 150, spin = true, yaw, draw = 1, label }) {
  const ref = useRef(null)
  const spinRef = useRef(spin)
  const startRef = useRef(() => {})
  const yawRef = useRef(yaw)
  const poseRef = useRef(() => {})
  const drawRef = useRef(draw)
  const drawFnRef = useRef(() => {})

  useEffect(() => {
    const el = ref.current
    const renderer = createRenderer()
    if (!renderer) {
      el.innerHTML = '<span class="hint">3D preview unavailable in this browser</span>'
      return
    }
    el.appendChild(renderer.domElement)

    const scene = new THREE.Scene()
    const colors = readTokens()
    const asset = buildAsset(kind, colors)
    const parts = lineParts(asset)
    applyDraw(parts, drawRef.current)
    scene.add(asset)
    const ground = new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.RingGeometry(1.15, 1.16, 48)),
      new THREE.LineBasicMaterial({ color: colors.rule }),
    )
    ground.rotation.x = -Math.PI / 2
    ground.position.y = -0.95
    scene.add(ground)

    const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 50)
    camera.position.set(3.9, 2.1, 4.5)
    camera.lookAt(0, -0.02, 0)

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    asset.rotation.y = yawRef.current ?? -0.5

    const resize = () => {
      const w = el.clientWidth || 1
      renderer.setSize(w, height, false)
      renderer.domElement.style.width = '100%'
      renderer.domElement.style.height = `${height}px`
      camera.aspect = w / height
      camera.updateProjectionMatrix()
      renderer.render(scene, camera)
    }
    const ro = new ResizeObserver(resize)
    ro.observe(el)
    resize()

    let visible = false
    let frame = 0
    let last = performance.now()
    const loop = (now) => {
      frame = 0
      if (!visible || !spinRef.current) return
      asset.rotation.y += ((now - last) / 1000) * 0.35
      last = now
      renderer.render(scene, camera)
      frame = requestAnimationFrame(loop)
    }
    const start = () => {
      if (visible && spinRef.current && yawRef.current == null && !reduced && !frame) { last = performance.now(); frame = requestAnimationFrame(loop) }
    }
    startRef.current = start
    poseRef.current = (y) => { asset.rotation.y = y; renderer.render(scene, camera) }
    drawFnRef.current = (p) => { applyDraw(parts, p); renderer.render(scene, camera) }
    const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; start() })
    io.observe(el)

    return () => {
      io.disconnect()
      ro.disconnect()
      cancelAnimationFrame(frame)
      disposeTree(scene)
      renderer.dispose()
      renderer.domElement.remove()
    }
  }, [kind, height])

  // Starting or stopping the turntable must not rebuild the scene.
  useEffect(() => { spinRef.current = spin; startRef.current() }, [spin])
  // A controlled yaw (the video's scripted camera) updates the existing scene in place.
  useEffect(() => { yawRef.current = yaw; if (yaw != null) poseRef.current(yaw) }, [yaw])
  useEffect(() => { drawRef.current = draw; drawFnRef.current(draw) }, [draw])

  return (
    <div ref={ref} className="wireframe" role="img" aria-label={label || `Wireframe of ${kind.replace('_', ' ')}`} style={{ height }}>
    </div>
  )
}
