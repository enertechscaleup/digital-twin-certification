// Plain-English wording for engine evidence, ported from the original dashboard
// (web/src/labels.js) with twin names taken from the project instead of a fixed list.

export const CAUSES = {
  gap_exceedance: 'Twin and reality disagree beyond tolerance',
  envelope_violation: 'Input outside its assured range',
  cascade: 'Cascade: a constituent twin is nullified',
  own_output: 'Output constituent is not assured',
  interface_invalid: 'Interface: an upstream prediction leaves the downstream twin\'s assured range',
  interaction_invalid: 'Interaction: the joint prediction misses the combined test bench',
}

export const short = (h, n = 10) => (h ? `${h.slice(0, n)}…` : '')

/** "v1.1.0 · 3fa2c1d09e…": a twin version citation (identity, version, fingerprint). */
export const versionTag = (ref, n = 10) => (ref ? `v${ref.version} · ${short(ref.fingerprint, n)}` : '')

/** The version citation an entry is about, if the run records lineage. */
export const citedVersion = (p) => p?.twin_ref || p?.system_ref || null

/** Display name for any twin id the evidence mentions: operational, design or system. */
export function namer(project) {
  const names = {}
  for (const t of project.twins) {
    names[t.operational_twin_id] = t.name
    names[t.design_twin_id] = `${t.name} (design twin)`
  }
  names[project.composition.system_twin.operational_twin_id] = project.composition.system_twin.name
  return (id) => names[id] || (id?.endsWith('-design') ? `${project.composition.system_twin.name} (design)` : id)
}

export function anomalyLabel(p) {
  if (p.type === 'data_quality') return `Sensor fault: ${p.subtype}`
  if (p.type === 'envelope_violation') return 'Input outside assured range'
  return 'Gap beyond tolerance'
}

export const anomalyKind = (p) => (p.type === 'data_quality' ? 'dq' : p.type === 'envelope_violation' ? 'env' : 'gap')

/** Which twins an entry concerns, for the solo (entry twins only) view. */
export function entryTwins(e) {
  const p = e.payload || {}
  return [p.twin_id, p.system_twin_id, p.operational_twin_id, p.operational_system_twin_id].filter(Boolean)
}

export function summarize(e, who) {
  const p = e.payload
  switch (e.entry_type) {
    case 'twin_version_registered': {
      const id = p.operational_twin_id || p.operational_system_twin_id
      const from = p.parent_fingerprint ? `derived from ${short(p.parent_fingerprint, 8)}` : 'first version'
      const how = p.composition === 'system'
        ? `composed of ${p.constituents.map((c) => `${c.twin_type} v${c.version}`).join(' + ')}`
        : `by ${p.registered_by.replace(/^twin owner /, 'owner ').replace(/[()]/g, '')}`
      return `${who(id)} version ${p.twin.version} registered, ${from}, ${how}`
    }
    case 'probe_set_sealed': return `Probe set sealed for ${p.twin_type}: ${p.probes} inputs, before any version is queried`
    case 'composition_test': return `Joint composition test ${p.test_id} (${p.trigger}): interface ${p.interface.passed ? 'PASS' : 'FAIL'}, interaction ${p.interaction.passed ? 'PASS' : 'FAIL'}`
    case 'composition_refused': return `System composition refused: ${p.reasons.map((r) => (r.cause === 'interface_invalid' ? 'interface' : 'interaction')).join(', ')} check failed`
    case 'run_started': return `Run started: scenario "${p.scenario}", seed ${p.seed}. Escalation rules recorded.`
    case 'verification': return `${p.stage === 're-verification' ? 'Re-verification' : 'Verification'} of ${who(p.twin_id)} (twin ${p.twin_version}): ${p.passed ? 'PASS' : 'FAIL'}, ${p.test_points} test points`
    case 'bench_validation': return `Bench validation of ${who(p.twin_id)}: ${p.passed ? 'PASS' : 'FAIL'}, ${p.readings} bench readings`
    case 'assurance_issued': return `Assurance issued: ${p.assurance_id}${p.supersedes ? ` (supersedes ${p.supersedes})` : ''}`
    case 'assurance_refused': return `Assurance refused for ${who(p.twin_id)}`
    case 'composition_assured': return `System twin composed from assured twins: ${p.composition_assurance_id}`
    case 'assurance_status_changed': return `${who(p.twin_id)}: ${p.from} → ${p.to}`
    case 'assurance_reason_added': return `${who(p.twin_id)}: still ${p.status}, new reason added`
    case 'anomaly_opened': return `${who(p.twin_id)} ${p.channel_id}: ${anomalyLabel(p)} opened`
    case 'anomaly_closed': return `${who(p.twin_id)} ${p.channel_id}: anomaly closed after ${p.readings} reading(s)`
    case 'readings_checkpoint': return `Readings sealed: ticks ${p.from_tick}–${p.to_tick} (${p.readings} readings)`
    case 'recalibration_requested': return `Recalibration requested for ${who(p.twin_id)} (currently ${p.status})`
    case 'recalibration_data_sealed': return 'Both data parts sealed before release'
    case 'recalibration_data_released': return 'Earlier part released to the twin owner. Held-out part released: no'
    case 'recalibration_submitted': return `Twin owner submitted recalibrated twin ${p.submission.twin_version}`
    case 'held_out_validation': return `Held-out validation of twin ${p.twin_version}: ${p.passed ? 'PASS' : 'FAIL'}`
    case 'recalibration_rejected': return `Recalibration rejected; ${who(p.twin_id)} stays ${p.status_unchanged}`
    case 'recalibration_refused': return `Recalibration refused: ${p.reason}`
    case 'assurance_superseded': return `${p.old_assurance_id} superseded by ${p.new_assurance_id}`
    case 'composition_reassessment': return `System reassessed: ${p.result === 'reassured' ? 're-assured' : 'not re-assured'}`
    case 'adjustment_recommended': return `${who(p.twin_id)} twin recommends ${p.recommendation.control_channel} ${p.recommendation.from.toFixed(1)} → ${p.recommendation.to}`
    case 'adjustment_approval': return `Adjustment ${p.decision === 'approve' ? 'approved' : 'declined'} by ${p.approver}`
    case 'adjustment_executed': return `Adjustment executed: ${p.control_channel} set to ${p.setpoint}`
    case 'adjustment_post_state_check': return `Post-state check: Sim2Real ${p.sim2real_passed ? 'PASS' : 'FAIL'}, objective ${p.objective.met ? 'met' : 'not met'}`
    case 'adjustment_refused': return `Adjustment refused: ${p.reason}`
    case 'run_completed': return 'Run completed'
    default: return e.entry_type
  }
}
