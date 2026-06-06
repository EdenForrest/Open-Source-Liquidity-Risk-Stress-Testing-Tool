export function pct(v, digits = 1) {
  return v != null ? (v * 100).toFixed(digits) + '%' : '—'
}

export function eur(v) {
  if (v == null) return '—'
  if (Math.abs(v) >= 1e9) return '€' + (v / 1e9).toFixed(2) + 'B'
  if (Math.abs(v) >= 1e6) return '€' + (v / 1e6).toFixed(1) + 'M'
  if (Math.abs(v) >= 1e3) return '€' + (v / 1e3).toFixed(0) + 'K'
  return '€' + v.toFixed(0)
}

/** Alias for pct — some pages use `fmt` for the percentage formatter. */
export function fmt(v, digits = 1) {
  return pct(v, digits)
}

/** Alias for eur — some pages use `fmtEur`. */
export function fmtEur(v) {
  return eur(v)
}
