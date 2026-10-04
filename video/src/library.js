// Section 2 (0:24–0:56): TwinEvidence as a library of vendor-owned twins.
// Find (browse the library), Test (the system owner's governance layer runs across an
// assembled configuration, and what it captures lands in the evidence store), Combine
// (several candidate configurations in quick succession, the governance layer re-forming
// across each). Frames are local to the section (0–950), timed to the v3 narration.
// Vendors are generic letters, not real companies.

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
  { members: ['A', 'B', 'C', 'D'], bright: 426, links: [496, 576], gov: [560, 606], hide: [794, 810] },
  { members: ['A', 'E', 'C', 'D'], bright: 810, links: [810, 850], gov: [828, 850], hide: [870, 880] },
  { members: ['F', 'E', 'G', 'D'], bright: 880, links: [880, 920], gov: [898, 920] },
]
export const SECTION2_FRAMES = 951
// Within a candidate: geothermal → battery → substation → data center, plus geothermal → substation.
const linkPairs = ([geo, bat, sub, dc]) => [[geo, bat], [bat, sub], [sub, dc], [geo, sub]]

export const BEATS = [
  { word: 'Find.', at: 425 },
  { word: 'Test.', at: 484 },
  { word: 'Combine.', at: 810 },
]

// Back-row graphs stand above and beside their twins. Front-row twins sit in the gaps
// between back-row twins, with their graphs directly above them, so the governance drops
// to the front row fall through those gaps rather than across another vendor's twin.
const graphOffset = (t) => (t.at[1] < 0 ? [1.9, 2.6, -0.8] : [-0.6, 1.8, -0.6])
// The governance rail: one height and depth, high above the gap between the two rows.
// It runs on past the last member to the evidence store, where its pulses land.
const RAIL_Y = 6.6
const RAIL_Z = 0
const TERMINUS_GAP = 1.5
const topX = (t) => t.at[0] + graphOffset(t)[0] + 0.6
const memberTwins = (c) => c.members.map((id) => TWINS.find((x) => x.id === id))

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
  governance: CANDIDATES.map((c) => ({ members: c.members, appear: c.gov, ...(c.hide ? { hide: c.hide } : {}), height: RAIL_Y, z: RAIL_Z,
    terminus: terminusPoint(c)[0] })),
  camera: [
    { f: 0, pos: [0, 17, 32], look: [0, 0.6, -0.4] },
    { f: 426, pos: [0, 16, 30.5], look: [0, 0.8, -0.4] },
    { f: 951, pos: [0.9, 15.5, 30], look: [0.9, 1.0, -0.4] },
  ],
  flow: { speed: 0.011 },
}

/** Where the governance layer's label sits: just above the rail, centred on the candidate's members. */
export function governanceLabelPoint(c) {
  const xs = memberTwins(c).map(topX)
  return [(Math.min(...xs) + Math.max(...xs)) / 2, RAIL_Y + 0.75, RAIL_Z]
}

/** The evidence store at the end of the rail: where everything the layer captures is recorded. */
export function terminusPoint(c) {
  return [Math.max(...memberTwins(c).map(topX)) + TERMINUS_GAP, RAIL_Y, RAIL_Z]
}

/** Where the layer touches each member: a third of the way down its drop, on the governance
 *  line itself, never inside the vendor's twin. */
export function sealPoints(c) {
  return memberTwins(c).map((t) => {
    const [, gy, gz] = graphOffset(t)
    return { id: t.id, at: [topX(t), RAIL_Y - (RAIL_Y - gy - 1.2) / 3, RAIL_Z + ((t.at[1] + gz) - RAIL_Z) / 3] }
  })
}
