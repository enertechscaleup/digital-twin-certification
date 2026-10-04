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
//   objects:    [{ id, kind, at: [x, z], scale, yaw, draw: [f0, f1],
//                  graph: { offset: [dx, dy, dz], nodes, seed, appear: [f0, f1] },
//                  focus: [[f, brightness], ...] }],          // optional: dim/highlight over time
//   links:      [{ from, to, appear: [f0, f1], hide: [f0, f1] }],   // hide is optional
//   governance: [{ members: [ids], appear: [f0, f1], hide: [f0, f1], height, z, terminus }],  // optional
//     terminus: an x past the last member where the rail ends and its pulses land (an evidence store)
//   camera:     [{ f, pos: [x, y, z], look: [x, y, z] }],
//   flow:       { speed },         // data pulses per frame along each curve (0..1 of its length)
//   grid:       { size },          // optional, default 40
// }
// colors = { line, graph, flow, grid, governance }  (hex strings)
//
// The governance layer belongs to the system owner, not to any vendor: it is drawn as a
// separate dashed rail raised above the member twins' graphs, with dashed drops to each
// graph, so it never sits inside a vendor's twin.

const clamp01 = (v) => Math.max(0, Math.min(1, v))
const ramp = ([f0, f1], f) => clamp01((f - f0) / Math.max(1, f1 - f0))
const ease = (t) => t * t * (3 - 2 * t)
const shown = (s, frame) => ease(ramp(s.appear, frame)) * (s.hide ? 1 - ease(ramp(s.hide, frame)) : 1)

/** Piecewise-linear value from [[frame, value], ...] keyframes; 1 when there are none. */
export function keyed(keys, frame) {
  if (!keys?.length) return 1
  if (frame <= keys[0][0]) return keys[0][1]
  for (let i = 1; i < keys.length; i++) {
    if (frame <= keys[i][0]) {
      const [f0, v0] = keys[i - 1], [f1, v1] = keys[i]
      return v0 + (v1 - v0) * ease(clamp01((frame - f0) / Math.max(1, f1 - f0)))
    }
  }
  return keys[keys.length - 1][1]
}

/** Camera position and target at ``frame``, eased between keyframes. */
export function cameraAt(spec, frame) {
  const keys = spec.camera
  let i = keys.findIndex((k) => k.f > frame)
  if (i === -1) i = keys.length
  const a = keys[Math.max(0, i - 1)], b = keys[Math.min(keys.length - 1, i)]
  const t = a === b ? 0 : ease(clamp01((frame - a.f) / (b.f - a.f)))
  const lerp = (u, v) => u.map((x, j) => x + (v[j] - x) * t)
  return { pos: lerp(a.pos, b.pos), look: lerp(a.look, b.look) }
}

/** Where a world point lands on screen at ``frame`` (for text labels laid over the canvas). */
export function projectPoint(spec, frame, point, width, height, fov = 32) {
  const cam = new THREE.PerspectiveCamera(fov, width / height, 0.1, 200)
  const { pos, look } = cameraAt(spec, frame)
  cam.position.set(...pos)
  cam.lookAt(...look)
  cam.updateMatrixWorld()
  const v = new THREE.Vector3(...point).project(cam)
  return { x: ((v.x + 1) / 2) * width, y: ((1 - v.y) / 2) * height, visible: v.z < 1 }
}

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
  const size = spec.grid?.size || 40
  const grid = new THREE.GridHelper(size, size, colors.grid, colors.grid)
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
    const materials = [...new Set(parts.map((p) => p.material))]
    if (o.focus) for (const m of materials) m.transparent = true
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
        flows.push({ curve, appear: o.graph.appear, phase: i / 3, reverse: i === 1, owner: o.id })
      })
      graph.userData.flowMat = flowMat
    }
    objects[o.id] = { spec: o, holder, parts, materials, graph, box }
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
    flows.push({ curve, appear: l.appear, hide: l.hide, phase: 0, reverse: false, link: true })
  }

  const governance = []
  for (const g of spec.governance || []) {
    const mat = new THREE.LineDashedMaterial({ color: colors.governance, dashSize: 0.32, gapSize: 0.18, transparent: true, opacity: 0 })
    const tops = g.members.map((id) => {
      const m = objects[id]
      const b = new THREE.Box3().setFromObject(m.graph || m.holder)
      return new THREE.Vector3((b.min.x + b.max.x) / 2, b.max.y, (b.min.z + b.max.z) / 2)
    }).sort((p, q) => p.x - q.x)
    // One straight rail at a single height and depth, behind the members: it never weaves
    // between (or appears to pass through) the vendors' twins.
    const railY = g.height ?? Math.max(...tops.map((p) => p.y)) + (g.lift ?? 1.4)
    const railZ = g.z ?? Math.min(...tops.map((p) => p.z)) - 0.8
    const railPts = tops.map((p) => new THREE.Vector3(p.x, railY, railZ))
    const railEnd = g.terminus != null && g.terminus > railPts[railPts.length - 1].x
      ? new THREE.Vector3(g.terminus, railY, railZ) : railPts[railPts.length - 1]
    const railCurve = new THREE.LineCurve3(railPts[0], railEnd)
    const group = new THREE.Group()
    for (const dy of [0, 0.32]) {
      const rail = new THREE.Line(new THREE.BufferGeometry().setFromPoints(railCurve.getPoints(80).map((p) => p.clone().setY(p.y + dy))), mat)
      rail.computeLineDistances()
      group.add(rail)
    }
    const drops = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(
      tops.flatMap((p) => [new THREE.Vector3(p.x, railY, railZ), new THREE.Vector3(p.x, p.y + 0.15, p.z)])), mat)
    drops.computeLineDistances()
    group.add(drops)
    for (const p of railPts) {
      const d = 0.16
      const diamond = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(p.x - d, p.y + 0.16, p.z), new THREE.Vector3(p.x, p.y + 0.16 + d, p.z),
        new THREE.Vector3(p.x + d, p.y + 0.16, p.z), new THREE.Vector3(p.x, p.y + 0.16 - d, p.z)]), mat)
      group.add(diamond)
    }
    scene.add(group)
    governance.push({ spec: g, group, mat, curve: railCurve, parts: lineParts(group), railY })
  }
  const govPositions = new Float32Array(Math.max(1, governance.length) * 4 * 3)
  const govGeo = new THREE.BufferGeometry()
  govGeo.setAttribute('position', new THREE.BufferAttribute(govPositions, 3))
  const govPulses = new THREE.Points(govGeo, new THREE.PointsMaterial({
    color: colors.governance || colors.flow, size: 10, sizeAttenuation: false, map: pulseTex, transparent: true, alphaTest: 0.05, depthWrite: false,
  }))
  govPulses.frustumCulled = false
  if (governance.length) scene.add(govPulses)

  const pulsePositions = new Float32Array(flows.length * 3 * 3)
  const pulseGeo = new THREE.BufferGeometry()
  pulseGeo.setAttribute('position', new THREE.BufferAttribute(pulsePositions, 3))
  const pulses = new THREE.Points(pulseGeo, new THREE.PointsMaterial({
    color: colors.flow, size: 9, sizeAttenuation: false, map: pulseTex, transparent: true, alphaTest: 0.05, depthWrite: false,
  }))
  pulses.frustumCulled = false
  scene.add(pulses)

  return { scene, objects, links, flows, pulses, pulsePositions, governance, govPulses, govPositions }
}

/** Put the built scene into its state at ``frame`` (and the camera into position). */
export function poseScene(built, spec, camera, frame) {
  const focus = {}
  for (const { spec: o, parts, materials, graph } of Object.values(built.objects)) {
    applyDraw(parts, ease(ramp(o.draw, frame)))
    const b = focus[o.id] = keyed(o.focus, frame)
    if (o.focus) for (const m of materials) m.opacity = b
    if (graph) {
      const g = ease(ramp(o.graph.appear, frame))
      graph.userData.material.opacity = 0.85 * g * b
      graph.userData.flowMat.opacity = 0.55 * g * b
    }
  }
  for (const { spec: l, line } of built.links) {
    const n = line.geometry.getAttribute('position').count
    line.geometry.setDrawRange(0, Math.round((l.hide ? shown(l, frame) : ease(ramp(l.appear, frame))) * n))
  }
  const speed = spec.flow?.speed ?? 0.012
  built.governance.forEach(({ spec: g, mat, parts, curve }, gi) => {
    applyDraw(parts, ease(ramp(g.appear, frame)))
    const v = shown(g, frame)
    mat.opacity = v
    const on = frame >= g.appear[1] && v > 0.5
    for (let k = 0; k < 4; k++) {
      const t = (frame * speed * 0.8 + k / 4) % 1
      const p = on ? curve.getPoint(t).setY(curve.getPoint(t).y + 0.16) : new THREE.Vector3(0, -100, 0)
      built.govPositions.set([p.x, p.y, p.z], (gi * 4 + k) * 3)
    }
  })
  if (built.governance.length) built.govPulses.geometry.getAttribute('position').needsUpdate = true
  built.flows.forEach((f, i) => {
    const on = frame >= f.appear[1] && (!f.hide || frame < f.hide[0]) && (!f.owner || focus[f.owner] > 0.6)
    for (let k = 0; k < 3; k++) {
      let t = (frame * speed * (f.link ? 0.7 : 1) + f.phase + k / 3) % 1
      if (f.reverse) t = 1 - t
      const p = on ? f.curve.getPoint(t) : new THREE.Vector3(0, -100, 0)
      built.pulsePositions.set([p.x, p.y, p.z], (i * 3 + k) * 3)
    }
  })
  built.pulses.geometry.getAttribute('position').needsUpdate = true

  const { pos, look } = cameraAt(spec, frame)
  camera.position.set(...pos)
  camera.lookAt(...look)
}
