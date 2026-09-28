export const fmt = (v, d = 1) => (v == null || Number.isNaN(v) ? '—' : Number(v).toLocaleString('en-GB', { minimumFractionDigits: d, maximumFractionDigits: d }))
export const digitsFor = (range) => (range[1] - range[0] >= 100 ? 0 : range[1] - range[0] >= 10 ? 1 : 2)
