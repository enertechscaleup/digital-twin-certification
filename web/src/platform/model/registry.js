// The twin registry. Vendors publish a twin's interface here (its channels and the
// ranges they validated it for); projects connect to an entry rather than describing
// a twin themselves. The platform never builds a twin.
//
// Real entries come from /api/registry (read from the twins' own config files).
// PREVIEW_REGISTRY below is hand-typed: entries with no real twin behind them yet are
// shown as "Preview listing"; the motor and compressor entries here are replaced by
// their real counterparts. Vendors and twin names are fictional.
import { getJson } from '../api.js'

const ch = (id, name, unit, direction, min, max) => ({ id, name, unit, direction, declared_range: [min, max] })

export const PREVIEW_REGISTRY = [
  {
    registry_id: 'vendor-a/em-400', vendor: 'Synthetic vendor A', name: 'EM-400 motor twin', asset_kind: 'electric_motor',
    domain: 'Oil & gas', role: 'product', modes: ['observational', 'semi_autonomous'],
    summary: 'Induction motor. Predicts shaft speed and vibration from supply voltage and current.',
    characteristic: { channel: 'speed', shape: 'ramp_hold' },
    channels: [ch('volt', 'Supply voltage', 'V', 'input', 380, 420), ch('current', 'Supply current', 'A', 'input', 10, 30),
      ch('speed', 'Shaft speed', 'rpm', 'output', 1250, 1600), ch('vibration', 'Vibration', 'mm/s', 'output', 1.5, 5.0)],
  },
  {
    registry_id: 'vendor-b/rc-12', vendor: 'Synthetic vendor B', name: 'RC-12 compressor twin', asset_kind: 'compressor',
    domain: 'Oil & gas', role: 'product', modes: ['observational'],
    summary: 'Gas compressor. Predicts outlet pressure and temperature from drive speed and air flow.',
    characteristic: { channel: 'pressure', shape: 'load_steps' },
    channels: [ch('speed', 'Drive speed', 'rpm', 'input', 1250, 1600), ch('flow', 'Air flow', 'm³/min', 'input', 8, 16),
      ch('pressure', 'Outlet pressure', 'bar', 'output', 3.0, 6.5), ch('temperature', 'Outlet temperature', '°C', 'output', 50, 95)],
  },
  {
    registry_id: 'vendor-c/fleetflow', vendor: 'Synthetic vendor C', name: 'FleetFlow dispatcher twin', asset_kind: 'fleet_dispatcher',
    domain: 'Warehousing & robotics', role: 'controller', modes: ['observational'],
    summary: 'Fleet controller. Predicts the task rate it will assign to each robot from incoming order lines.',
    characteristic: { channel: 'tasks_1', shape: 'shift' },
    channels: [ch('order_rate', 'Order lines', 'lines/h', 'input', 300, 900),
      ch('tasks_1', 'Tasks to AMR 1', 'tasks/h', 'output', 40, 110), ch('tasks_2', 'Tasks to AMR 2', 'tasks/h', 'output', 40, 110)],
  },
  {
    registry_id: 'vendor-d/amr-600', vendor: 'Synthetic vendor D', name: 'AMR-600 drive twin', asset_kind: 'amr',
    domain: 'Warehousing & robotics', role: 'product', modes: ['observational', 'semi_autonomous'],
    summary: 'Autonomous mobile robot. Predicts travel speed and tote deliveries from tasks, battery and payload.',
    characteristic: { channel: 'speed', shape: 'trips' },
    channels: [ch('task_rate', 'Assigned tasks', 'tasks/h', 'input', 40, 110), ch('battery', 'Battery voltage', 'V', 'input', 44, 52),
      ch('payload', 'Payload', 'kg', 'input', 0, 600), ch('speed', 'Travel speed', 'm/s', 'output', 1.2, 2.0),
      ch('deliveries', 'Tote deliveries', 'totes/h', 'output', 40, 110)],
  },
  {
    registry_id: 'vendor-e/ps-2', vendor: 'Synthetic vendor E', name: 'PS-2 pick station twin', asset_kind: 'pick_station',
    domain: 'Warehousing & robotics', role: 'product', modes: ['observational'],
    summary: 'Goods-to-person pick station. Predicts pick rate and cycle time from tote arrivals.',
    characteristic: { channel: 'pick_rate', shape: 'shift' },
    channels: [ch('arrivals_1', 'Tote arrivals, AMR 1', 'totes/h', 'input', 55, 110), ch('arrivals_2', 'Tote arrivals, AMR 2', 'totes/h', 'input', 55, 110),
      ch('pick_rate', 'Pick rate', 'picks/h', 'output', 300, 900), ch('cycle_time', 'Cycle time', 's', 'output', 6, 14)],
  },
  {
    registry_id: 'vendor-f/beltline', vendor: 'Synthetic vendor F', name: 'BeltLine conveyor twin', asset_kind: 'conveyor',
    domain: 'Manufacturing', role: 'product', modes: ['observational'],
    summary: 'Belt conveyor. Predicts belt speed from drive frequency.',
    characteristic: { channel: 'belt_speed', shape: 'ramp_hold' },
    channels: [ch('drive_frequency', 'Drive frequency', 'Hz', 'input', 30, 60), ch('belt_speed', 'Belt speed', 'm/s', 'output', 0.5, 1.5)],
  },
  {
    registry_id: 'vendor-g/cp-30', vendor: 'Synthetic vendor G', name: 'CP-30 case packer twin', asset_kind: 'case_packer',
    domain: 'Manufacturing', role: 'product', modes: ['observational', 'semi_autonomous'],
    summary: 'Case packer. Predicts cases per minute and motor temperature from infeed speed.',
    characteristic: { channel: 'cases_per_minute', shape: 'load_steps' },
    channels: [ch('infeed_speed', 'Infeed speed', 'm/s', 'input', 0.5, 1.5), ch('cases_per_minute', 'Cases per minute', 'cases/min', 'output', 10, 30),
      ch('motor_temperature', 'Motor temperature', '°C', 'output', 30, 80)],
  },
]

const previewEntry = (id) => PREVIEW_REGISTRY.find((r) => r.registry_id === id)

/** Real entries first, then preview listings for twins not registered for real. */
export async function loadRegistry() {
  const { entries } = await getJson('/api/registry')
  const real = entries.map((e) => ({
    ...e,
    real: true,
    characteristic: previewEntry(e.registry_id)?.characteristic
      || { channel: e.channels.find((c) => c.direction === 'output').id, shape: 'ramp_hold' },
  }))
  const ids = new Set(real.map((e) => e.registry_id))
  return [...real, ...PREVIEW_REGISTRY.filter((e) => !ids.has(e.registry_id)).map((e) => ({ ...e, real: false }))]
}

/** Lookup that falls back to the preview listing, so saved drafts still resolve before the API answers. */
export const entryLookup = (list) => (id) => list?.find((r) => r.registry_id === id) || previewEntry(id)

const SHAPES = {
  ramp_hold: (t) => (t < 12 ? t / 12 : 1) * 0.72 + 0.06 * Math.sin(t / 4),
  load_steps: (t) => [0.35, 0.55, 0.8, 0.5, 0.65][Math.floor(t / 12) % 5] + 0.03 * Math.sin(t),
  trips: (t) => (t % 12 < 2 ? 0.2 + (t % 12) * 0.25 : t % 12 > 9 ? 0.25 : 0.7 + 0.05 * Math.sin(t / 2)),
  shift: (t) => 0.5 + 0.28 * Math.sin(t / 9) + 0.04 * Math.sin(t * 1.7),
}

/** A vendor-published sample of the twin's characteristic output, as chart rows. */
export function characteristic(entry, ticks = 60) {
  const c = entry.channels.find((x) => x.id === entry.characteristic.channel)
  const [lo, hi] = c.declared_range
  const f = SHAPES[entry.characteristic.shape]
  return { channel: c, ticks, rows: Array.from({ length: ticks }, (_, t) => ({ tick: t, physical: lo + (hi - lo) * Math.min(1, Math.max(0, f(t))) })) }
}

/** A project twin slot filled from a registry entry: interface locked, limits start at the vendor's declared range. */
export function connectTwin(entry, name, key) {
  return {
    key,
    name,
    role: entry.role,
    owner: entry.vendor,
    registry_id: entry.registry_id,
    asset_kind: entry.asset_kind,
    twin_mode: entry.modes[0],
    channels: entry.channels.map((c) => ({
      id: c.id, name: c.name, unit: c.unit, direction: c.direction,
      declared_range: [...c.declared_range], assured_range: [...c.declared_range],
      tolerance_pct: 5, monitored: true,
    })),
  }
}
