// The platform's only data source for real projects: the evidence API (app/main.py).
// toViewProject turns a project's API detail into the shape every screen renders from,
// the same shape the preview-only mock projects use.

export async function getJson(url) {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${res.status}: ${(await res.json().catch(() => ({}))).detail || res.statusText}`)
  return res.json()
}

// Display only; the evidence keeps the units exactly as the twin owner declared them.
const UNIT_LABEL = { degC: '°C', m3: 'm³', 'm3/min': 'm³/min' }
export const unitLabel = (u) => UNIT_LABEL[u] || u

export function toViewProject(d, runs) {
  const twins = Object.entries(d.twins).map(([id, t]) => ({
    key: t.twin_type,
    name: t.name,
    role: t.role,
    owner: t.vendor,
    twin_mode: t.twin_mode,
    operational_twin_id: id,
    design_twin_id: t.design_twin_id,
    registry_id: t.registry_id,
    asset_kind: t.asset_kind,
    channels: t.channels.map((c) => ({
      id: c.channel_id, name: c.name, unit: unitLabel(c.unit), direction: c.direction,
      assured_range: c.envelope, tolerance_pct: c.tolerance_pct,
    })),
  }))
  const keyOf = Object.fromEntries(twins.map((t) => [t.operational_twin_id, t.key]))
  return {
    project_id: d.project_id,
    name: d.name,
    domain: d.domain,
    summary: d.summary,
    data: 'evidence',
    gap: { metric: d.gap_metric },
    entry_twins: d.entry_twins.map((id) => keyOf[id]),
    twins,
    composition: {
      system_twin: { name: d.system_twin.name, operational_twin_id: d.system_twin.twin_id },
      output_constituents: d.system_twin.outputs_come_from.map((id) => keyOf[id]),
      connections: d.system_twin.connections.map((c) => ({
        from: [c.from_twin, c.from_channel], to: [c.to_twin, c.to_channel], description: c.description,
      })),
    },
    runs: runs.map((r) => ({ id: r.run, name: r.title, core_ledger_head_hash: r.core_ledger_head_hash })),
  }
}

/** Every project on the platform, with its runs, shaped for the screens. */
export async function loadProjects() {
  const { projects } = await getJson('/api/projects')
  return Promise.all(projects.map(async (p) => {
    const [detail, { runs }] = await Promise.all([
      getJson(`/api/projects/${p.project_id}`),
      getJson(`/api/projects/${p.project_id}/runs`),
    ])
    return toViewProject(detail, runs)
  }))
}

/** Final per-twin status of a run, straight from the engine's own record (state at the last tick). */
export async function finalLevels(project, run) {
  const state = await getJson(`/api/runs/${run.id}/state`)
  const levels = Object.fromEntries(Object.entries(state.twins).map(([id, t]) => [id, t.status]))
  return { levels, system: levels[project.composition.system_twin.operational_twin_id], ticks: state.ticks_total }
}
