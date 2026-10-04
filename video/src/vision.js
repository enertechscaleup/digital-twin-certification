// Section 1 (0:00–0:16.5): an invented energy-and-compute system assembling itself.
// Geothermal plant → battery array → substation → data center. Not a real project and
// not platform data: generic shapes, no statuses. The closing frame (VISION_END) is reused
// by Sections 2 and 4. Timings are written on the original 30 s plan and retimed to the
// 16.5 s section of the v4 narration (same choreography, same order): the opening statement
// keeps its 3.2 s (as in v3), and the build that follows plays faster.

export const VISION_END = Math.round(16.5 * 30)
const OPEN = 4 // original seconds before the first object draws
const at = (s) => (s <= OPEN ? s * 24 : OPEN * 24 + ((s - OPEN) * (VISION_END - OPEN * 24)) / (30 - OPEN))

export const VISION = {
  objects: [
    { id: 'geo', kind: 'geothermal_plant', at: [-9, -1], scale: 1.7, yaw: 0.25, draw: [at(4), at(6.5)],
      graph: { offset: [2.4, 3.1, -1.2], scale: 2.1, yaw: -0.35, seed: 11, appear: [at(6.2), at(7.6)] } },
    { id: 'bat', kind: 'battery_array', at: [-3.6, 2.6], scale: 1.4, yaw: -0.15, draw: [at(10), at(12)],
      graph: { offset: [2.2, 2.6, -1.0], scale: 1.9, yaw: -0.35, seed: 23, appear: [at(11.8), at(13)] } },
    { id: 'sub', kind: 'substation', at: [1.2, -1.2], scale: 1.5, yaw: 0.1, draw: [at(15), at(17)],
      graph: { offset: [2.0, 3.0, -1.1], scale: 1.9, yaw: -0.35, seed: 37, appear: [at(16.8), at(18)] } },
    { id: 'dc', kind: 'data_center', at: [9.2, 1.4], scale: 2.4, yaw: -0.2, draw: [at(20), at(23)],
      graph: { offset: [3.6, 5.0, -2.0], scale: 2.6, yaw: -0.35, seed: 53, appear: [at(22.6), at(24)] } },
  ],
  links: [
    { from: 'geo', to: 'bat', appear: [at(12), at(13.5)] },
    { from: 'bat', to: 'sub', appear: [at(17), at(18.5)] },
    { from: 'geo', to: 'sub', appear: [at(17.5), at(19)] },
    { from: 'sub', to: 'dc', appear: [at(23), at(24.5)] },
    { from: 'bat', to: 'dc', appear: [at(23.5), at(25)] },
  ],
  camera: [
    { f: 0, pos: [-8.2, 4.2, 11], look: [-8.4, 1.6, -0.5] },
    { f: at(4), pos: [-8.2, 4.2, 11], look: [-8.4, 1.6, -0.5] },
    { f: at(9), pos: [-7.4, 4.6, 10.5], look: [-7.6, 2.0, -0.5] },
    { f: at(14), pos: [-4.2, 5.2, 12.5], look: [-5.4, 1.8, 0.4] },
    { f: at(19), pos: [0.4, 5.8, 13.5], look: [-1.2, 1.8, 0.2] },
    { f: at(25), pos: [7.4, 7.6, 19], look: [6.2, 2.4, 0.4] },
    { f: at(28.4), pos: [2.2, 13.6, 27.5], look: [2.2, 2.2, 0.2] },
    { f: at(30), pos: [2.2, 13.6, 27.5], look: [2.2, 2.2, 0.2] },
  ],
  flow: { speed: 0.011 },
}
