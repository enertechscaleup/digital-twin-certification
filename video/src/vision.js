// Section 1 (0:00–0:30): an invented energy-and-compute system assembling itself.
// Geothermal plant → battery array → substation → data center. Not a real project and
// not platform data: generic shapes, no statuses. The final frame (850–900) is reused
// by Section 4.

const S = 30 // frames per second

export const VISION = {
  objects: [
    { id: 'geo', kind: 'geothermal_plant', at: [-9, -1], scale: 1.7, yaw: 0.25, draw: [4 * S, 6.5 * S],
      graph: { offset: [2.4, 3.1, -1.2], scale: 2.1, yaw: -0.35, seed: 11, appear: [6.2 * S, 7.6 * S] } },
    { id: 'bat', kind: 'battery_array', at: [-3.6, 2.6], scale: 1.4, yaw: -0.15, draw: [10 * S, 12 * S],
      graph: { offset: [2.2, 2.6, -1.0], scale: 1.9, yaw: -0.35, seed: 23, appear: [11.8 * S, 13 * S] } },
    { id: 'sub', kind: 'substation', at: [1.2, -1.2], scale: 1.5, yaw: 0.1, draw: [15 * S, 17 * S],
      graph: { offset: [2.0, 3.0, -1.1], scale: 1.9, yaw: -0.35, seed: 37, appear: [16.8 * S, 18 * S] } },
    { id: 'dc', kind: 'data_center', at: [7.8, 1.6], scale: 2.0, yaw: -0.2, draw: [20 * S, 23 * S],
      graph: { offset: [2.8, 3.6, -1.6], scale: 2.4, yaw: -0.35, seed: 53, appear: [22.6 * S, 24 * S] } },
  ],
  links: [
    { from: 'geo', to: 'bat', appear: [12 * S, 13.5 * S] },
    { from: 'bat', to: 'sub', appear: [17 * S, 18.5 * S] },
    { from: 'geo', to: 'sub', appear: [17.5 * S, 19 * S] },
    { from: 'sub', to: 'dc', appear: [23 * S, 24.5 * S] },
    { from: 'bat', to: 'dc', appear: [23.5 * S, 25 * S] },
  ],
  camera: [
    { f: 0, pos: [-8.2, 4.2, 11], look: [-8.4, 1.6, -0.5] },
    { f: 4 * S, pos: [-8.2, 4.2, 11], look: [-8.4, 1.6, -0.5] },
    { f: 9 * S, pos: [-7.4, 4.6, 10.5], look: [-7.6, 2.0, -0.5] },
    { f: 14 * S, pos: [-4.2, 5.2, 12.5], look: [-5.4, 1.8, 0.4] },
    { f: 19 * S, pos: [0.4, 5.8, 13.5], look: [-1.2, 1.8, 0.2] },
    { f: 25 * S, pos: [3.6, 6.4, 15], look: [1.4, 1.8, 0.4] },
    { f: 28.4 * S, pos: [1.3, 12.8, 25.5], look: [1.3, 1.9, 0.2] },
    { f: 30 * S, pos: [1.3, 12.8, 25.5], look: [1.3, 1.9, 0.2] },
  ],
  flow: { speed: 0.011 },
}
