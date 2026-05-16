// ── Color System ─────────────────────────────────────────────────────────────
// Bloomberg keyboard logic:
//   🟡 Yellow  → equity / market sectors
//   🔵 Blue    → analytical / rates / baseline
//   🟢 Green   → execute / T+0 / positive / safe
//   🔴 Red     → cancel / danger / stressed / illiquid
//   🟠 Orange  → warning / partial / credit

// Liquidity bucket severity — green → yellow → orange → red
export const BUCKET_COLORS = {
  'T+0':  '#00cc66',   // green  — safe, execute
  'T+1':  '#ffe033',   // yellow — equity-like (Bloomberg yellow key)
  'T+3':  '#ff8800',   // amber  — caution
  'T+7':  '#ff4400',   // orange-red — elevated risk
  '>T+7': '#ff1a1a',   // red    — cancel / illiquid danger
}

// Normal (blue = analytical baseline) vs Stressed (red = cancel/risk)
export const SERIES_COLORS = {
  normal:   '#3b9eff',   // blue   — analytical function key
  stressed: '#ff4400',   // orange-red — stressed/danger
}

// Asset class palette — mapped to Bloomberg keyboard color logic
// Equity → yellow, Bonds → blue variants, Cash/safe → green, Alts → purple, etc.
export const CATEGORY_COLORS = [
  '#ffe033',   // yellow  — equity
  '#3b9eff',   // blue    — govt bond / rates
  '#00c8ff',   // cyan    — corp bond
  '#00cc66',   // green   — cash / MMF
  '#a855f7',   // purple  — alternatives
  '#ff8800',   // amber   — real assets
  '#ff4400',   // orange-red — HY / distressed
  '#f472b6',   // pink    — structured
  '#7a8fa8',   // slate   — other
]

// Asset class → color lookup (for deterministic coloring by name)
const ASSET_CLASS_COLORS = {
  'listed_equity':    '#ffe033',   // yellow
  'equity':           '#ffe033',
  'government_bond':  '#3b9eff',   // blue
  'govt':             '#3b9eff',
  'corporate_bond':   '#00c8ff',   // cyan
  'corp':             '#00c8ff',
  'cash':             '#00cc66',   // green
  'mmf':              '#00cc66',
  'money_market':     '#00cc66',
  'alternative':      '#a855f7',   // purple
  'real_estate':      '#ff8800',   // amber
  'high_yield':       '#ff4400',   // orange-red
  'structured':       '#f472b6',   // pink
}

export function assetClassColor(cls, fallbackIndex = 0) {
  const key = (cls || '').toLowerCase().replace(/\s+/g, '_')
  return ASSET_CLASS_COLORS[key] || CATEGORY_COLORS[fallbackIndex % CATEGORY_COLORS.length]
}

// Dual chart theme — light vs dark
export const CHART_THEME = {
  light: {
    axisColor:      '#94a3b8',
    gridColor:      '#e2e8f0',
    tickColor:      '#64748b',
    tooltipBg:      '#ffffff',
    tooltipBorder:  '#3b9eff',
    tooltipText:    '#1e293b',
  },
  dark: {
    axisColor:      '#3d5068',
    gridColor:      '#1e2a38',
    tickColor:      '#7a8fa8',
    tooltipBg:      '#0d1117',
    tooltipBorder:  '#ff6600',
    tooltipText:    '#e8ecf0',
  },
}

// Helper — pick chart theme by app theme id
export function chartTheme(themeId) {
  return themeId === 'bloomberg' ? CHART_THEME.dark : CHART_THEME.light
}

// Stress NAV impact coloring
export function stressImpactColor(navDeltaPct) {
  if (navDeltaPct < -10) return BUCKET_COLORS['>T+7']   // red
  if (navDeltaPct < -5)  return BUCKET_COLORS['T+7']    // orange-red
  if (navDeltaPct < 0)   return BUCKET_COLORS['T+3']    // amber
  return SERIES_COLORS.normal                            // blue — positive
}

// Bucket badge — inline style, exact hex match with chart bars
export function bucketBadgeStyle(bucket) {
  const hex = BUCKET_COLORS[bucket] || '#7a8fa8'
  return {
    backgroundColor: hex + '22',
    color: hex,
    border: `1px solid ${hex}55`,
  }
}
