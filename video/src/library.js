// Section 2 (0:30–1:00): TwinEvidence as a library of vendor-owned twins.
// Find (browse the library), Test (the system owner's governance layer runs across an
// assembled configuration), Combine (several candidate configurations in quick
// succession, the governance layer re-forming across each). Frames are local to the
// section (0–899). Vendors are generic letters, not real companies.

const BASE = 0.42 // brightness of twins that are not in focus
const OFF = 0.22 // brightness of twins outside the candidate being tested

export const TWINS = [
  { id: 'A', vendor: 'Vendor A', label: 'Geothermal plant twin', kind: 'geothermal_plant', at: [-10.5, -4.5], scale: 1.3 },
  { id: 'B', vendor: 'Vendor B', label: 'Battery storage twin', kind: 'battery_array', at: [-3.5, -4.5], scale: 1.1 },
  { id: 'C', vendor: 'Vendor C', label: 'Substation twin', kind: 'substation', at: [3.5, -4.5], scale: 1.2 },
  { id: 'D', vendor: 'Vendor D', label: 'Data center twin', kind: 'data_center', at: [10.5, -4.5], scale: 1.6 },
  { id: 'E', vendor: 'Vendor E', label: 'Battery storage twin', kind: 'battery_array', at: [-5.4, 4.5], scale: 1.1, fresh: true },
  { id: 'F', vendor: 'Vendor F', label: 'Geothermal plant twin', kind: 'geothermal_plant', at: [0, 4.5], scale: 1.3, fresh: true },
  { id: 'G', vendor: 'Vendor G', label: 'Substation twin', kind: 'substation', at: [5.4, 4.5], scale: 1.2, fresh: true },
]

// The three candidate system configurations and their timings.
export const CANDIDATES = [
  { members: ['A', 'B', 'C', 'D'], bright: 300, links: [330, 410], gov: [400, 450], hide: [560, 580] },
  { members: ['A', 'E', 'C', 'D'], bright: 585, links: [600, 650], gov: [640, 680], hide: [720, 738] },
  { members: ['F', 'E', 'G', 'D'], bright: 740, links: [755, 805], gov: [795, 835] },
]
// Within a candidate: geothermal → battery → substation → data center, plus geothermal → substation.
const linkPairs = ([geo, bat, sub, dc]) => [[geo, bat], [bat, sub], [sub, dc], [geo, sub]]

export const BEATS = [
  { word: 'Find.', at: 100 },
  { word: 'Test.', at: 305 },
  { word: 'Combine.', at: 565 },
]

// Back-row graphs stand above and beside their twins. Front-row twins sit in the gaps
// between back-row twins, with their graphs directly above them, so the governance drops
// to the front row fall through those gaps rather than across another vendor's twin.
const graphOffset = (t) => (t.at[1] < 0 ? [1.9, 2.6, -0.8] : [-0.6, 1.8, -0.6])
// The governance rail: one height and depth, high above the gap between the two rows.
const RAIL_Y = 6.6
const RAIL_Z = 0

const SWEEP = ['A', 'B', 'C', 'D', 'E', 'F', 'G']
const sweepAt = (id) => 120 + SWEEP.indexOf(id) * 22

function focusKeys(id) {
  const t = sweepAt(id)
  const keys = [[0, 1], [96, 1], [112, BASE], [t, BASE], [t + 8, 1], [t + 22, 1], [t + 34, BASE], [290, BASE]]
  for (const c of CANDIDATES) {
    const level = c.members.includes(id) ? 1 : OFF
    keys.push([c.bright, keys[keys.length - 1][1]], [c.bright + 16, level])
  }
  return keys
}

export const LIBRARY = {
  grid: { size: 60 },
  objects: TWINS.map((t) => ({
    id: t.id, kind: t.kind, at: t.at, scale: t.scale, yaw: -0.12,
    draw: t.fresh ? [40, 100] : [-2, -1],
    graph: { offset: graphOffset(t), scale: 1.45, yaw: -0.3, seed: 11 + t.id.charCodeAt(0), appear: t.fresh ? [80, 120] : [-2, -1] },
    focus: focusKeys(t.id),
  })),
  links: CANDIDATES.flatMap((c) => linkPairs(c.members).map(([a, b], i) => ({
    from: a, to: b, appear: [c.links[0] + i * 10, c.links[1] + i * 10 - 30], ...(c.hide ? { hide: c.hide } : {}),
  }))),
  governance: CANDIDATES.map((c) => ({ members: c.members, appear: c.gov, ...(c.hide ? { hide: c.hide } : {}), height: RAIL_Y, z: RAIL_Z })),
  camera: [
    { f: 0, pos: [0, 17, 32], look: [0, 0.6, -0.4] },
    { f: 300, pos: [0, 16, 30.5], look: [0, 0.8, -0.4] },
    { f: 900, pos: [0.6, 15.5, 29.5], look: [0.4, 1.0, -0.4] },
  ],
  flow: { speed: 0.011 },
}

/** Where the governance layer's label sits: just above the rail, centred on the candidate's members. */
export function governanceLabelPoint(c) {
  const xs = c.members.map((id) => { const t = TWINS.find((x) => x.id === id); return t.at[0] + graphOffset(t)[0] + 0.6 })
  return [(Math.min(...xs) + Math.max(...xs)) / 2, RAIL_Y + 0.75, RAIL_Z]
}
