// Mock replay for design review only. It fabricates readings from a project's
// config and applies simplified versions of the engine's rules so the screens
// have something realistic to show. In F3 the operation view reads the real
// engine evidence instead, and this file is deleted.

import { ESCALATION, layers, twinByKey } from './projects.js'

const LEVEL = { assured: 0, flagged: 1, nullified: 2 }
const worse = (a, b) => (LEVEL[a] >= LEVEL[b] ? a : b)

function rng(seed) {
  let s = seed >>> 0
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32)
}

function profile(c, i) {
  const [lo, hi] = c.assured_range
  const mid = (lo + hi) / 2
  const amp = (hi - lo) * 0.16
  return (t) => mid + amp * Math.sin((t + 5 * i) / (6 + 1.3 * i))
}

export function mockRun(project, run) {
  const { ticks, mock } = run
  const order = layers(project).flat()
  const rand = rng(project.project_id.length * 7919 + ticks)
  const feeds = Object.fromEntries(project.composition.connections.map((c) => [`${c.to[0]}.${c.to[1]}`, c.from]))
  const sysId = project.composition.system_twin.operational_twin_id

  const series = {}
  for (const t of project.twins) series[t.key] = Object.fromEntries(t.channels.map((c) => [c.id, []]))
  const counters = {}
  const level = Object.fromEntries([...project.twins.map((t) => [t.key, 'assured']), [sysId, 'assured']])
  const version = Object.fromEntries(project.twins.map((t) => [t.key, 1]))
  const reasons = Object.fromEntries([...project.twins.map((t) => [t.key, []]), [sysId, []]])
  const snapshots = []
  const ledger = []
  let seq = 0
  const log = (tick, type, text, twin) => ledger.push({ seq: seq++, tick, type, text, twin })

  log(0, 'run_started', `Run started: "${run.name}". Escalation rules recorded.`)
  for (const t of project.twins) {
    log(0, 'verification', `Verification of ${t.name}: PASS`, t.key)
    log(0, 'bench_validation', `Bench validation of ${t.name}: PASS`, t.key)
    log(0, 'assurance_issued', `Assurance issued: ASR-${t.operational_twin_id}-v1`, t.key)
  }
  log(0, 'composition_assured', `${project.composition.system_twin.name} composed from assured twins`)

  const f = mock.fault
  const drift = (tick) => (tick < f.start ? 0 : Math.min(1, (tick - f.start) / f.ramp) * f.cap_pct / 100)
  const recal = mock.recalibration
  const adj = mock.adjustment

  for (let tick = 0; tick < ticks; tick++) {
    for (const key of order) {
      const twin = twinByKey(project, key)
      const rows = series[key]
      let outOfRange = null
      twin.channels.forEach((c, i) => {
        if (c.direction !== 'input') return
        const src = feeds[`${key}.${c.id}`]
        let v = src ? series[src[0]][src[1]][tick].physical : profile(c, i)(tick) * (1 + (rand() - 0.5) * 0.004)
        if (adj && key === adj.twin && c.id === adj.control && tick >= adj.execute) v = adj.to + (rand() - 0.5) * 2
        rows[c.id].push({ tick, physical: v, predicted: null })
        if (v < c.assured_range[0] || v > c.assured_range[1]) outOfRange ||= c
      })
      twin.channels.forEach((c, i) => {
        if (c.direction !== 'output') return
        let predicted = profile(c, i)(tick)
        if (adj && key === adj.twin && tick >= adj.execute && i === twin.channels.findIndex((x) => x.direction === 'output'))
          predicted += (c.assured_range[1] - c.assured_range[0]) * 0.2
        const w = f.twin === key ? (f.channels[c.id] || 0) : 0
        const recalibrated = recal && recal.twin === key && tick >= recal.at
        const physical = predicted * (1 - drift(tick) * w) * (1 + (rand() - 0.5) * 0.012)
        if (recalibrated) predicted = predicted * (1 - drift(tick) * w)
        const gap = (100 * Math.abs(physical - predicted)) / Math.abs(predicted)
        const cls = outOfRange ? 'not_evaluated' : gap > 2 * c.tolerance_pct ? 'beyond_2x' : gap > c.tolerance_pct ? 'exceeds' : 'within'
        rows[c.id].push({ tick, physical, predicted, gap, cls })

        const k = `${key}.${c.id}`
        const s = (counters[k] ||= { over: 0, over2: 0, open: false })
        if (cls !== 'not_evaluated') {
          s.over = cls === 'within' ? 0 : s.over + 1
          s.over2 = cls === 'beyond_2x' ? s.over2 + 1 : 0
        }
        if (s.over === 1 && !s.open) { s.open = true; log(tick, 'anomaly_opened', `${twin.name} ${c.name.toLowerCase()}: gap beyond tolerance opened`, key) }
        if (s.over === 0 && s.open && cls === 'within') { s.open = false; log(tick, 'anomaly_closed', `${twin.name} ${c.name.toLowerCase()}: anomaly closed`, key) }
        if (s.over >= ESCALATION.flag_after) raise(tick, key, 'flagged', { cause: 'gap', channel: c.name, since: tick })
        if (s.over2 >= ESCALATION.nullify_after) raise(tick, key, 'nullified', { cause: 'gap_2x', channel: c.name, since: tick })
      })
      const e = (counters[`${key}.__env`] ||= { n: 0, open: false })
      e.n = outOfRange ? e.n + 1 : 0
      if (outOfRange && !e.open) { e.open = true; log(tick, 'anomaly_opened', `${twin.name} ${outOfRange.name.toLowerCase()}: input outside assured range`, key) }
      if (!outOfRange && e.open) { e.open = false; log(tick, 'anomaly_closed', `${twin.name}: inputs back inside assured range`, key) }
      if (e.n >= ESCALATION.flag_after) raise(tick, key, 'flagged', { cause: 'envelope', channel: outOfRange.name, since: tick })
    }

    if (recal && tick === recal.at) {
      const t = twinByKey(project, recal.twin)
      log(tick, 'recalibration_requested', `Recalibration requested for ${t.name}`, t.key)
      log(tick, 'recalibration_data_sealed', 'Earlier 70% and held-out 30% sealed before release', t.key)
      log(tick, 'held_out_validation', `Held-out validation of ${t.name} v2: PASS`, t.key)
      version[t.key] = 2
      level[t.key] = 'assured'
      reasons[t.key] = reasons[t.key].map((r) => ({ ...r, resolved: true }))
      for (const k of Object.keys(counters)) if (k.startsWith(`${t.key}.`)) counters[k] = { over: 0, over2: 0, open: false, n: 0 }
      log(tick, 'assurance_superseded', `ASR-${t.operational_twin_id}-v1 superseded by v2`, t.key)
      log(tick, 'composition_reassessment', `${project.composition.system_twin.name} reassessed: not re-assured (status is sticky)`)
    }
    if (adj) {
      const t = twinByKey(project, adj.twin)
      if (tick === adj.recommend) log(tick, 'adjustment_recommended', `${t.name} twin recommends ${adj.control} ${adj.from} → ${adj.to}`, t.key)
      if (tick === adj.approve) log(tick, 'adjustment_approval', 'Adjustment approved by Operator (demo)', t.key)
      if (tick === adj.execute) log(tick, 'adjustment_executed', `Adjustment executed: ${adj.control} set to ${adj.to}`, t.key)
      if (tick === adj.execute + 5) log(tick, 'adjustment_post_state_check', 'Post-state check: Sim2Real PASS, objective met', t.key)
    }

    // System twin: any nullified constituent flags it; it also takes its output constituents' status.
    const sys = []
    for (const t of project.twins) if (level[t.key] === 'nullified') sys.push({ level: 'flagged', cause: 'cascade', channel: t.name })
    for (const k of project.composition.output_constituents) if (level[k] !== 'assured') sys.push({ level: level[k], cause: 'own_output', channel: twinByKey(project, k).name })
    for (const r of sys) raise(tick, sysId, r.level, { ...r, since: tick }, true)

    if (tick % 10 === 9) log(tick, 'readings_checkpoint', `Readings sealed: ticks ${tick - 9}–${tick}`)
    snapshots.push({
      tick,
      twins: Object.fromEntries(Object.keys(level).map((k) => [k, { level: level[k], version: version[k] || 1, reasons: [...reasons[k]] }])),
    })
  }

  function raise(tick, key, to, reason, isSystem = false) {
    if (!reasons[key].some((r) => !r.resolved && r.cause === reason.cause && r.channel === reason.channel)) {
      reasons[key].push({ ...reason, seq })
      if (LEVEL[to] <= LEVEL[level[key]]) log(tick, 'assurance_reason_added', `${label(key)}: still ${level[key]}, new reason added`, isSystem ? null : key)
    }
    if (LEVEL[to] > LEVEL[level[key]]) {
      log(tick, 'assurance_status_changed', `${label(key)}: ${level[key]} → ${to}`, isSystem ? null : key)
      level[key] = worse(level[key], to)
    }
  }
  function label(key) {
    return key === sysId ? project.composition.system_twin.name : twinByKey(project, key).name
  }

  log(ticks - 1, 'run_completed', 'Run completed')
  return { series, snapshots, ledger, sysId, ticks }
}
