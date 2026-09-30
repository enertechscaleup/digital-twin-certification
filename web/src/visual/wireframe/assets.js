// Stylized wireframe assets, shared by the platform (twin registry) and the demo
// video's stage page. Each asset is a few primitives drawn as outlines only:
// deliberately low-fidelity, so they read as "a motor", "a robot", not as CAD.
// Units are arbitrary; every asset fits roughly inside a 2 × 1.4 × 1.4 box.

import * as THREE from 'three'

const line = (geometry, material, threshold = 12) => new THREE.LineSegments(new THREE.EdgesGeometry(geometry, threshold), material)

function part(group, geometry, material, { at = [0, 0, 0], rot = [0, 0, 0], threshold } = {}) {
  const m = line(geometry, material, threshold)
  m.position.set(...at)
  m.rotation.set(...rot)
  group.add(m)
  return m
}

const box = (w, h, d) => new THREE.BoxGeometry(w, h, d)
const cyl = (r, h, seg = 14, r2 = r) => new THREE.CylinderGeometry(r2, r, h, seg, 1)
const AX = [0, 0, Math.PI / 2] // lay a cylinder along x
const AZ = [Math.PI / 2, 0, 0] // lay a cylinder along z

function electricMotor(g, ink, accent) {
  part(g, cyl(0.52, 1.25, 16), ink, { rot: AX, threshold: 1 })
  for (let i = 0; i < 6; i++) part(g, cyl(0.6, 0.05, 16), ink, { at: [-0.5 + i * 0.2, 0, 0], rot: AX })
  part(g, cyl(0.42, 0.18, 16), ink, { at: [0.72, 0, 0], rot: AX })
  part(g, cyl(0.42, 0.18, 16), ink, { at: [-0.72, 0, 0], rot: AX })
  part(g, cyl(0.07, 0.55, 10), accent, { at: [1.07, 0, 0], rot: AX })
  part(g, box(0.34, 0.2, 0.34), ink, { at: [0, 0.66, 0] })
  part(g, box(1.3, 0.08, 0.9), ink, { at: [0, -0.62, 0] })
  for (const x of [-0.45, 0.45]) part(g, box(0.12, 0.14, 0.8), ink, { at: [x, -0.51, 0] })
}

function compressor(g, ink, accent) {
  part(g, new THREE.TorusGeometry(0.5, 0.22, 8, 18), ink, { rot: [0, Math.PI / 2, 0], threshold: 20 })
  part(g, cyl(0.28, 0.35, 14), ink, { at: [0, 0, 0], rot: AX, threshold: 1 })
  part(g, cyl(0.2, 0.7, 12), ink, { at: [-0.5, 0, 0], rot: AX, threshold: 1 })
  part(g, cyl(0.28, 0.06, 14), accent, { at: [-0.86, 0, 0], rot: AX })
  part(g, cyl(0.15, 0.6, 12), ink, { at: [0, 0.55, 0.55], rot: [0, 0, 0], threshold: 1 })
  part(g, cyl(0.21, 0.06, 12), accent, { at: [0, 0.86, 0.55] })
  part(g, cyl(0.09, 0.5, 10), ink, { at: [0.35, 0, 0], rot: AX })
  part(g, box(1.6, 0.08, 1.0), ink, { at: [0, -0.78, 0] })
  part(g, box(0.5, 0.16, 0.6), ink, { at: [0, -0.66, 0] })
}

function amr(g, ink, accent) {
  part(g, box(1.5, 0.32, 1.0), ink, { at: [0, -0.2, 0] })
  part(g, box(1.3, 0.05, 0.86), ink, { at: [0, 0, 0] })
  for (const x of [-0.5, 0.5]) for (const z of [-0.52, 0.52]) part(g, cyl(0.17, 0.1, 14), ink, { at: [x, -0.36, z], rot: AZ })
  part(g, cyl(0.12, 0.12, 14), accent, { at: [0.58, 0.09, 0] })
  part(g, box(0.06, 0.12, 0.5), accent, { at: [0.76, -0.2, 0] })
  part(g, box(0.8, 0.45, 0.6), ink, { at: [-0.15, 0.25, 0] })
  part(g, box(0.72, 0.02, 0.52), ink, { at: [-0.15, 0.38, 0] })
}

function pickStation(g, ink, accent) {
  part(g, box(1.3, 0.05, 0.7), ink, { at: [0, 0, 0.1] })
  for (const x of [-0.6, 0.6]) for (const z of [-0.2, 0.4]) part(g, box(0.05, 0.75, 0.05), ink, { at: [x, -0.4, z] })
  part(g, box(1.3, 1.3, 0.35), ink, { at: [0, 0.25, -0.55] })
  for (const y of [-0.1, 0.3, 0.7]) part(g, box(1.3, 0.02, 0.35), ink, { at: [0, y, -0.55] })
  part(g, box(0.5, 0.25, 0.35), ink, { at: [-0.25, 0.15, 0.15] })
  for (const x of [-0.72, 0.72]) part(g, box(0.05, 1.1, 0.05), accent, { at: [x, 0.3, 0.5] })
}

function fleetDispatcher(g, ink, accent) {
  part(g, box(0.8, 1.35, 0.55), ink, { at: [0, -0.1, 0] })
  part(g, box(0.02, 1.2, 0.5), ink, { at: [0.41, -0.1, 0] })
  for (const y of [0.25, 0.05, -0.15]) part(g, box(0.5, 0.1, 0.02), ink, { at: [0, y, 0.28] })
  part(g, cyl(0.02, 0.5, 6), accent, { at: [0.2, 0.82, 0] })
  for (const r of [0.14, 0.24, 0.34]) part(g, new THREE.TorusGeometry(r, 0.004, 3, 24, Math.PI / 2), accent, { at: [0.2, 1.07, 0], rot: [0, 0, Math.PI / 4] })
  part(g, box(1.1, 0.05, 0.8), ink, { at: [0, -0.8, 0] })
}

function conveyor(g, ink, accent) {
  for (const z of [-0.36, 0.36]) part(g, box(1.9, 0.12, 0.05), ink, { at: [0, 0, z] })
  for (let i = 0; i < 9; i++) part(g, cyl(0.05, 0.7, 8), ink, { at: [-0.88 + i * 0.22, 0.02, 0], rot: AZ })
  for (const x of [-0.8, 0.8]) for (const z of [-0.36, 0.36]) part(g, box(0.05, 0.6, 0.05), ink, { at: [x, -0.35, z] })
  part(g, cyl(0.15, 0.3, 12), accent, { at: [0.95, -0.12, 0.52], rot: AZ, threshold: 1 })
  part(g, box(0.34, 0.2, 0.3), ink, { at: [-0.3, 0.16, 0] })
}

function casePacker(g, ink, accent) {
  part(g, box(1.3, 1.1, 0.9), ink, { at: [0, 0, 0] })
  part(g, box(1.3, 0.05, 0.9), ink, { at: [0, -0.3, 0] })
  part(g, box(1.2, 0.05, 0.08), accent, { at: [0, 0.42, 0] })
  part(g, box(0.06, 0.4, 0.06), accent, { at: [0.1, 0.2, 0] })
  part(g, box(0.6, 0.08, 0.3), ink, { at: [-0.95, -0.3, 0] })
  for (const [x, y] of [[0.3, -0.18], [0.3, 0.02], [-0.1, -0.18]]) part(g, box(0.28, 0.2, 0.3), ink, { at: [x, y, 0] })
}

export const ASSET_KINDS = {
  electric_motor: { label: 'Electric motor', build: electricMotor },
  compressor: { label: 'Gas compressor', build: compressor },
  amr: { label: 'Autonomous mobile robot', build: amr },
  pick_station: { label: 'Pick station', build: pickStation },
  fleet_dispatcher: { label: 'Fleet dispatcher', build: fleetDispatcher },
  conveyor: { label: 'Belt conveyor', build: conveyor },
  case_packer: { label: 'Case packer', build: casePacker },
}

/** Build one asset as a THREE.Group of line segments, centred on the origin. */
export function buildAsset(kind, colors) {
  const group = new THREE.Group()
  const ink = new THREE.LineBasicMaterial({ color: colors.ink })
  const accent = new THREE.LineBasicMaterial({ color: colors.accent })
  ;(ASSET_KINDS[kind] || ASSET_KINDS.electric_motor).build(group, ink, accent)
  const box3 = new THREE.Box3().setFromObject(group)
  group.position.sub(box3.getCenter(new THREE.Vector3()))
  const holder = new THREE.Group()
  holder.add(group)
  return holder
}
