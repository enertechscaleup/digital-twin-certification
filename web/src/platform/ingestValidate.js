// "Check a sample message": the Dataflow validator's shape rules, run in the browser with no network
// call. It mirrors ingest/pipeline.py: classify() step by step, in the same order, with the same
// reject codes; the rules themselves (fields, schema, attributes, timestamp, codes) come from
// ingestion-rules.json, written by ingest/export_rules.py. tests/test_connect_step.py runs this file
// and the pipeline on the same messages and fails if they ever disagree.

const hex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('')
export const sha256Hex = async (text) => hex(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)))
export const readingKey = async (replayId, runId, tick, twinId, channelId) =>
  (await sha256Hex(`${replayId}|${runId}|${tick}|${twinId}|${channelId}`)).slice(0, 32)

// Python tells 3 from 3.0 (and booleans from numbers); JSON.parse does not, so keep each number's
// source text (the reviver's context where the browser gives it, a text search otherwise).
function parseWithNumberSources(text) {
  const sources = {}
  const value = JSON.parse(text, function (key, v, context) {
    if (typeof v === 'number' && context && typeof context.source === 'string' && !(key in sources)) sources[key] = context.source
    return v
  })
  return { value, sources }
}
const numberSource = (text, sources, key) => {
  if (key in sources) return sources[key]
  const m = text.match(new RegExp(`"${key}"\\s*:\\s*(-?[0-9][0-9.eE+-]*)`))
  return m ? m[1] : ''
}
// Python's re, which the pipeline uses: \d is any Unicode digit, and $ also matches before a final "\n".
const pythonMatch = (pattern, text) => {
  const re = new RegExp(pattern.replaceAll('\\d', '\\p{Nd}'), 'u')
  return re.test(text) || (text.endsWith('\n') && !text.slice(0, -1).includes('\n') && re.test(text.slice(0, -1)))
}
const isNumber = (v) => typeof v === 'number' && Number.isFinite(v)
const isNumberOrNull = (v) => v === null || isNumber(v)
const isText = (v) => typeof v === 'string' && v.length > 0

/** Returns { kind: 'valid' | 'invalid' | 'control', reason }. ``channels``: [{ twin_id, channel_id, direction, unit }]. */
export async function classify(dataText, attributes, channels, rules) {
  const a = attributes || {}
  if (a.kind === 'control') return { kind: 'control', reason: null }
  if (a.schema !== rules.schema || !rules.required_attributes.every((k) => a[k])) return { kind: 'invalid', reason: 'bad_attributes' }
  if ((await sha256Hex(dataText)) !== a.content_sha256) return { kind: 'invalid', reason: 'content_hash_mismatch' }
  let r, sources
  try {
    ({ value: r, sources } = parseWithNumberSources(dataText))
  } catch {
    return { kind: 'invalid', reason: 'malformed_json' }
  }
  if (r === null || typeof r !== 'object' || Array.isArray(r)) return { kind: 'invalid', reason: 'malformed_json' }
  const fields = rules.allowed_fields
  if (Object.keys(r).some((k) => !fields.includes(k))) return { kind: 'invalid', reason: 'forbidden_field' }
  if (fields.some((k) => !(k in r))) return { kind: 'invalid', reason: 'missing_field' }
  if (r.kind !== 'field' || r.test_point !== null) return { kind: 'invalid', reason: 'wrong_kind' }
  const tickIsInt = Number.isInteger(r.tick) && !/[.eE]/.test(numberSource(dataText, sources, 'tick'))
  if (!(tickIsInt && r.tick >= 0
        && typeof r.timestamp === 'string' && pythonMatch(rules.timestamp_pattern, r.timestamp)
        && ['run_id', 'twin_id', 'twin_version', 'channel_id', 'direction', 'unit'].every((k) => isText(r[k]))
        && isNumber(r.operational_hours)
        && isNumberOrNull(r.physical_value) && isNumberOrNull(r.predicted_value))) return { kind: 'invalid', reason: 'bad_type' }
  const ch = channels.find((c) => c.twin_id === r.twin_id && c.channel_id === r.channel_id)
  if (!ch || ch.direction !== r.direction || ch.unit !== r.unit) return { kind: 'invalid', reason: 'unknown_channel' }
  if (a.reading_key !== (await readingKey(a.replay_id, r.run_id, r.tick, r.twin_id, r.channel_id))) return { kind: 'invalid', reason: 'bad_attributes' }
  return { kind: 'valid', reason: null }
}
