// Plain-English wording for evidence, used across the dashboard.

export const TWIN_NAMES = {
  'motor-op-001': 'Motor',
  'compressor-op-001': 'Compressor',
  'compressor-system-op-001': 'Compressor system',
  'motor-design': 'Motor (design twin)',
  'compressor-design': 'Compressor (design twin)',
  'compressor-system-design': 'Compressor system (design)',
}

export const twinName = (id) => TWIN_NAMES[id] || id

export const CAUSES = {
  gap_exceedance: 'Twin and reality disagree beyond tolerance',
  envelope_violation: 'Input outside its assured range',
  cascade: 'Cascade: a constituent twin is nullified',
  own_output: 'Output constituent is not assured',
}

export const short = (h, n = 10) => (h ? `${h.slice(0, n)}…` : '')

export function fmtNum(v, digits = 1) {
  if (v == null || Number.isNaN(v)) return '—'
  return Number(v).toLocaleString('en-GB', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function anomalyLabel(p) {
  if (p.type === 'data_quality') return `Sensor fault: ${p.subtype}`
  if (p.type === 'envelope_violation') return 'Input outside assured range'
  return 'Gap beyond tolerance'
}

export function anomalyClass(p) {
  return p.type === 'data_quality' ? 'dq' : p.type === 'envelope_violation' ? 'env' : 'gap'
}

// Which twins an entry concerns, for the "motor only" opening view.
export function entryTwins(e) {
  const p = e.payload || {}
  const ids = [p.twin_id, p.system_twin_id].filter(Boolean)
  return ids
}

export function summarize(e) {
  const p = e.payload
  const who = (id) => twinName(id)
  switch (e.entry_type) {
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
    case 'recalibration_data_sealed': return `Both data parts sealed before release`
    case 'recalibration_data_released': return `Earlier part released to the twin owner. Held-out part released: no`
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
