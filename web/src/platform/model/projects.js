// Platform-wide constants and shared helpers for any project in the screens' shape.
// Real projects come from the evidence API
// (api.js, toViewProject); their configuration lives in projects/*.json.

export const TWIN_MODES = {
  observational: { label: 'Observational', note: 'Predicts only. Never recommends an action.' },
  semi_autonomous: { label: 'Semi-autonomous', note: 'May recommend a setpoint change; a named person approves it before it runs once.' },
  autonomous: { label: 'Autonomous', note: 'Not supported in this version.', disabled: true },
}

export const GAP_METRIC = {
  id: 'relative_pct_of_prediction',
  label: 'Relative gap',
  formula: '|measured − predicted| ÷ |predicted| × 100',
  note: 'The same gap definition applies to every project in this version of the platform.',
}

// Platform-wide escalation protocol (engine/protocol.py). Read-only for projects.
export const ESCALATION = { flag_after: 3, nullify_after: 10, nullify_multiple: 2, spike_pct: 20, stuck_readings: 3 }


// Preview projects render from mock data (model/mockRun.js) and are labelled as previews.
// None are listed now: the fulfilment cell is a real project with engine evidence.
export const PREVIEW_PROJECTS = []

// -- helpers shared by every screen ------------------------------------

export const twinByKey = (p, key) => p.twins.find((t) => t.key === key)
export const channelCount = (p) => p.twins.reduce((n, t) => n + t.channels.length, 0)

/** Columns for a left-to-right drawing: each twin sits one column right of everything that feeds it. */
export function layers(p) {
  const depth = Object.fromEntries(p.twins.map((t) => [t.key, 0]))
  for (let i = 0; i < p.twins.length; i++) {
    for (const c of p.composition.connections) depth[c.to[0]] = Math.max(depth[c.to[0]], depth[c.from[0]] + 1)
  }
  const cols = []
  for (const t of p.twins) (cols[depth[t.key]] ||= []).push(t.key)
  return cols
}

/** A plain-language name for the shape of the composition, derived from the connections. */
export function topology(p) {
  const { connections } = p.composition
  if (p.twins.length < 2) return 'Single twin'
  if (!connections.length) return 'Parallel'
  const hasController = p.twins.some((t) => t.role === 'controller')
  const fanOut = Object.values(connections.reduce((m, c) => ({ ...m, [c.from[0]]: (m[c.from[0]] || 0) + 1 }), {})).some((n) => n > 1)
  if (hasController) return 'Controller-led'
  if (fanOut) return 'Branching'
  return 'Sequential'
}

/** Structural checks run on a draft before it can be created (the loader will run the same ones in F1). */
export function validate(p) {
  const issues = []
  const keys = new Set()
  if (!p.name.trim()) issues.push('Give the project a name.')
  if (!p.twins.length) issues.push('Add at least one twin.')
  for (const t of p.twins) {
    if (keys.has(t.key)) issues.push(`Two twins share the id "${t.key}".`)
    keys.add(t.key)
    if (!t.name.trim()) issues.push('Every twin needs a name.')
    if (!t.channels.some((c) => c.direction === 'output' && c.monitored !== false)) issues.push(`${t.name || t.key} needs at least one monitored output channel to compare with reality.`)
    const ids = new Set()
    for (const c of t.channels) {
      if (ids.has(c.id)) issues.push(`${t.name}: two channels share the id "${c.id}".`)
      ids.add(c.id)
      if (!c.name.trim() || !c.unit.trim()) issues.push(`${t.name}: every channel needs a name and a unit.`)
      if (!(Number(c.assured_range[0]) < Number(c.assured_range[1]))) issues.push(`${t.name} · ${c.name}: the assured range minimum must be below the maximum.`)
      if (c.declared_range && (c.assured_range[0] < c.declared_range[0] || c.assured_range[1] > c.declared_range[1]))
        issues.push(`${t.name} · ${c.name}: the assured range must stay within ${c.declared_range[0]}–${c.declared_range[1]} ${c.unit}, the range the twin owner validated.`)
      if (c.direction === 'output' && c.monitored !== false && !(Number(c.tolerance_pct) > 0)) issues.push(`${t.name} · ${c.name}: set a tolerance above 0%.`)
    }
  }
  for (const c of p.composition.connections) {
    const a = twinByKey(p, c.from[0])?.channels.find((x) => x.id === c.from[1])
    const b = twinByKey(p, c.to[0])?.channels.find((x) => x.id === c.to[1])
    if (!a || !b) { issues.push('A connection points at a channel that no longer exists.'); continue }
    if (a.direction !== 'output' || b.direction !== 'input') issues.push(`${a.name} → ${b.name}: connections run from an output to an input.`)
    if (a.unit !== b.unit) issues.push(`${a.name} (${a.unit}) → ${b.name} (${b.unit}): connected channels must share a unit.`)
    if (c.from[0] === c.to[0]) issues.push(`${a.name} → ${b.name}: a twin cannot feed itself.`)
  }
  const d = Object.fromEntries(p.twins.map((t) => [t.key, 0]))
  for (let i = 0; i <= p.twins.length; i++) for (const c of p.composition.connections) d[c.to[0]] = Math.max(d[c.to[0]] ?? 0, (d[c.from[0]] ?? 0) + 1)
  if (Object.values(d).some((v) => v > p.twins.length)) issues.push('The connections form a loop. Twins must feed each other in one direction.')
  if (p.twins.length > 1 && !p.composition.output_constituents.length) issues.push("Choose which twin's outputs are the system's outputs.")
  return [...new Set(issues)]
}
