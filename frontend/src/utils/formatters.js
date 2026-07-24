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

/**
 * Format a stress multiplier (e.g. ADV scalar, liquidity-haircut uplift) as a
 * fixed-decimal "×" value. Fixed decimals are important: the raw values come off
 * floating-point arithmetic in the engine, so a true 2.8 can arrive as
 * 2.8000000000000003 and would otherwise render as ">2.8". toFixed both tidies
 * the display and guarantees the cell never shows more precision than the
 * plausible-shock box defines.
 */
export function mult(v, digits = 2) {
  return v != null ? (+v).toFixed(digits) + '×' : '—'
}

/** Alias for pct — some pages use `fmt` for the percentage formatter. */
export function fmt(v, digits = 1) {
  return pct(v, digits)
}

/** Alias for eur — some pages use `fmtEur`. */
export function fmtEur(v) {
  return eur(v)
}
