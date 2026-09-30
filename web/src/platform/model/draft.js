// Edits to a new-project draft that keep twin keys and connections consistent.

export const slug = (s) => s.toLowerCase().trim().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '')

export function uniqueKey(d, base) {
  const root = slug(base) || 'twin'
  let key = root
  for (let n = 2; d.twins.some((t) => t.key === key); n++) key = `${root}_${n}`
  return key
}

export function removeTwin(d, ti) {
  const key = d.twins[ti].key
  d.twins.splice(ti, 1)
  d.composition.connections = d.composition.connections.filter((c) => c.from[0] !== key && c.to[0] !== key)
  d.composition.output_constituents = d.composition.output_constituents.filter((k) => k !== key)
}
