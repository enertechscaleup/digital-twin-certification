import * as THREE from 'three'
import { buildAsset } from './assets.js'
import { applyDraw, lineParts } from './renderer.js'

// Several wireframe assets in one canvas, each with its mathematical graph beside it,
// animated data flowing between the physical shape and its graph, and links between
// assets. Used by the demo video; the geometry is the platform's own (assets.js).
//
// Everything on screen is a pure function of ``frame``, so a render is reproducible.
//
// scene = {
//   objects: [{ id, kind, at: [x, z], scale, yaw, draw: [f0, f1],
//               graph: { offset: [dx, dy, dz], nodes, seed, appear: [f0, f1] } }],
//   links:   [{ from, to, appear: [f0, f1] }],
//   camera:  [{ f, pos: [x, y, z], look: [x, y, z] }],
//   flow:    { speed }            // data pulses per frame along each curve (0..1 of its length)
// }
// colors = { line, graph, flow, grid }  (hex strings)

const clamp01 = (v) => Math.max(0, Math.min(1, v))
const ramp = ([f0, f1], f) => clamp01((f - f0) / Math.max(1, f1 - f0))
const ease = (t) => t * t * (3 - 2 * t)

function rng(seed) {
  let s = seed >>> 0 || 1
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32)
}

function dotTexture() {
  const n = 32
  const data = new Uint8Array(n * n * 4)
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
    const d = Math.hypot(x - n / 2 + 0.5, y - n / 2 + 0.5) / (n / 2)
    const a = d < 0.7 ? 255 : d < 1 ? Math.round(255 * (1 - (d - 0.7) / 0.3)) : 0
    data.set([255, 255, 255, a], (y * n + x) * 4)
  }
  const tex = new THREE.DataTexture(data, n, n)
  tex.needsUpdate = true
  return tex
}

/** A small layered graph (nodes as rings, edges as lines) on a vertical plane. */
function buildGraph(spec, colors) {
  const rand = rng(spec.seed || 7)
  const layers = [2, 3, 2].slice(0, Math.max(2, Math.ceil((spec.nodes || 7) / 3)))
  const nodes = []
  layers.forEach((count, li) => {
    for (let i = 0; i < count; i++) {
      nodes.push(new THREE.Vector3(li * 0.42, (i - (count - 1) / 2) * 0.36 + (rand() - 0.5) * 0.08, 0))
    }
  })
  const group = new THREE.Group()
  const mat = new THREE.LineBasicMaterial({ color: colors.graph, transparent: true, opacity: 0 })
  const ring = new THREE.BufferGeometry().setFromPoints(
    Array.from({ length: 17 }, (_, i) => new THREE.Vector3(Math.cos((i / 16) * Math.PI * 2) * 0.05, Math.sin((i / 16) * Math.PI * 2) * 0.05, 0)))
  for (const p of nodes) {
    const r = new THREE.Line(ring, mat)
    r.position.copy(p)
    group.add(r)
  }
  const edges = []
  let start = 0
  for (let li = 0; li < layers.length - 1; li++) {
    for (let i = 0; i < layers[li]; i++) {
      for (let j = 0; j < layers[li + 1]; j++) {
        if (rand() < 0.75 || j === i % layers[li + 1]) edges.push(nodes[start + i], nodes[start + layers[li] + j])
      }
    }
    start += layers[li]
  }
  group.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(edges), mat))
  group.userData = { material: mat, nodes }
  return group
}

function curveLine(curve, material, points = 40) {
  return new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(points)), material)
}

export function buildScene(spec, colors) {
  const scene = new THREE.Scene()
  const grid = new THREE.GridHelper(40, 40, colors.grid, colors.grid)
  grid.material.transparent = true
  grid.material.opacity = 0.22
  scene.add(grid)

  const pulseTex = dotTexture()
  const flows = [] // { curve, start, points, phase, reverse }
  const objects = {}

  for (const o of spec.objects) {
    const holder = buildAsset(o.kind, { ink: colors.line, accent: colors.flow }, { ground: true })
    holder.scale.setScalar(o.scale || 1)
    holder.position.set(o.at[0], 0, o.at[1])
    holder.rotation.y = o.yaw || 0
    scene.add(holder)
    const parts = lineParts(holder)
    applyDraw(parts, 0)
    const box = new THREE.Box3().setFromObject(holder)

    let graph = null
    const curves = []
    if (o.graph) {
      graph = buildGraph(o.graph, colors)
      const [dx, dy, dz] = o.graph.offset || [0, 1.4, 0]
      graph.position.set(o.at[0] + dx, dy, o.at[1] + dz)
      graph.scale.setScalar(o.graph.scale || 1)
      graph.rotation.y = o.graph.yaw || 0
      scene.add(graph)
      graph.updateMatrixWorld(true)
      const flowMat = new THREE.LineBasicMaterial({ color: colors.flow, transparent: true, opacity: 0 })
      const top = box.max.y
      const anchors = [0.25, 0.5, 0.75].map((t) => new THREE.Vector3(box.min.x + (box.max.x - box.min.x) * t, top, (box.min.z + box.max.z) / 2))
      const targets = [0, 1].map((i) => graph.userData.nodes[i].clone().applyMatrix4(graph.matrixWorld))
      anchors.forEach((a, i) => {
        const b = targets[i % targets.length]
        const mid = a.clone().lerp(b, 0.5).add(new THREE.Vector3(0, 0.6, 0))
        const curve = new THREE.QuadraticBezierCurve3(a, mid, b)
        const line = curveLine(curve, flowMat)
        scene.add(line)
        curves.push(curve)
        flows.push({ curve, appear: o.graph.appear, phase: i / 3, reverse: i === 1 })
      })
      graph.userData.flowMat = flowMat
    }
    objects[o.id] = { spec: o, holder, parts, graph, box }
  }

  const links = []
  for (const l of spec.links || []) {
    const a = objects[l.from].box, b = objects[l.to].box
    const pa = new THREE.Vector3((a.min.x + a.max.x) / 2, 0.05, (a.min.z + a.max.z) / 2)
    const pb = new THREE.Vector3((b.min.x + b.max.x) / 2, 0.05, (b.min.z + b.max.z) / 2)
    const mid = pa.clone().lerp(pb, 0.5).add(new THREE.Vector3(0, 0.9 + pa.distanceTo(pb) * 0.08, 0))
    const curve = new THREE.QuadraticBezierCurve3(pa, mid, pb)
    const line = curveLine(curve, new THREE.LineBasicMaterial({ color: colors.line, transparent: true, opacity: 0.75 }), 60)
    scene.add(line)
    links.push({ spec: l, line })
    flows.push({ curve, appear: l.appear, phase: 0, reverse: false, link: true })
  }

  const pulsePositions = new Float32Array(flows.length * 3 * 3)
  const pulseGeo = new THREE.BufferGeometry()
  pulseGeo.setAttribute('position', new THREE.BufferAttribute(pulsePositions, 3))
  const pulses = new THREE.Points(pulseGeo, new THREE.PointsMaterial({
    color: colors.flow, size: 9, sizeAttenuation: false, map: pulseTex, transparent: true, alphaTest: 0.05, depthWrite: false,
  }))
  pulses.frustumCulled = false
  scene.add(pulses)

  return { scene, objects, links, flows, pulses, pulsePositions }
}

/** Put the built scene into its state at ``frame`` (and the camera into position). */
export function poseScene(built, spec, camera, frame) {
  for (const { spec: o, parts, graph } of Object.values(built.objects)) {
    applyDraw(parts, ease(ramp(o.draw, frame)))
    if (graph) {
      const g = ease(ramp(o.graph.appear, frame))
      graph.userData.material.opacity = 0.85 * g
      graph.userData.flowMat.opacity = 0.55 * g
    }
  }
  for (const { spec: l, line } of built.links) {
    const n = line.geometry.getAttribute('position').count
    line.geometry.setDrawRange(0, Math.round(ease(ramp(l.appear, frame)) * n))
  }
  const speed = spec.flow?.speed ?? 0.012
  built.flows.forEach((f, i) => {
    const on = frame >= f.appear[1]
    for (let k = 0; k < 3; k++) {
      let t = (frame * speed * (f.link ? 0.7 : 1) + f.phase + k / 3) % 1
      if (f.reverse) t = 1 - t
      const p = on ? f.curve.getPoint(t) : new THREE.Vector3(0, -100, 0)
      built.pulsePositions.set([p.x, p.y, p.z], (i * 3 + k) * 3)
    }
  })
  built.pulses.geometry.getAttribute('position').needsUpdate = true

  const keys = spec.camera
  let i = keys.findIndex((k) => k.f > frame)
  if (i === -1) i = keys.length
  const a = keys[Math.max(0, i - 1)], b = keys[Math.min(keys.length - 1, i)]
  const t = a === b ? 0 : ease(clamp01((frame - a.f) / (b.f - a.f)))
  const lerp = (u, v) => u.map((x, j) => x + (v[j] - x) * t)
  camera.position.set(...lerp(a.pos, b.pos))
  camera.lookAt(...lerp(a.look, b.look))
}
