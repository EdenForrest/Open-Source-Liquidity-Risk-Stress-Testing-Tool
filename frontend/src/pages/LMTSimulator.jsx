import { useTranslation } from 'react-i18next'
import { pct, eur } from '../utils/formatters'

// ---------------------------------------------------------------------------
// AIFMD II tool taxonomy (IDs only — labels/descriptions come from i18n)
// ---------------------------------------------------------------------------

export const ALWAYS_AVAILABLE = [
  {
    id: 'suspension',
    informational: true,
  },
  {
    id: 'side_pockets',
    informational: true,
  },
]

export const QUANTITATIVE_TOOLS = [
  {
    id: 'gate',
    param: { key: 'gate_threshold', type: 'pct', min: 2, max: 25, step: 1, defaultVal: 10 },
  },
  {
    id: 'notice_period_extension',
    param: { key: 'notice_extension_days', type: 'int', min: 0, max: 30, step: 1, defaultVal: 7 },
  },
  {
    id: 'redemption_in_kind',
    param: { key: 'in_kind_pct', type: 'pct', min: 0, max: 100, step: 5, defaultVal: 25 },
  },
]

export const ANTIDILUTION_TOOLS = [
  {
    id: 'redemption_fee',
    param: { key: 'fee_rate', type: 'bps', min: 0, max: 200, step: 5, defaultVal: 50 },
  },
  {
    id: 'swing_pricing',
    param: { key: 'swing_threshold', type: 'pct', min: 1, max: 20, step: 1, defaultVal: 5 },
  },
  {
    id: 'dual_pricing',
    param: { key: 'dual_spread_frac', type: 'bps', min: 0, max: 150, step: 5, defaultVal: 30 },
  },
  {
    id: 'adl',
    param: { key: 'adl_rate', type: 'bps', min: 0, max: 200, step: 5, defaultVal: 50 },
  },
]

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function paramDisplay(tool, paramValues) {
  if (!tool.param) return null
  const v = paramValues[tool.param.key] ?? tool.param.defaultVal
  if (tool.param.type === 'pct') return `${v}%`
  if (tool.param.type === 'bps') return `${v} bps`
  return `${v} days`
}

export function buildLmtConfig(enabled, paramValues) {
  const activeTools = Object.entries(enabled)
    .filter(([, on]) => on)
    .map(([id]) => id)

  const cfg = { active_tools: activeTools }

  ;[...QUANTITATIVE_TOOLS, ...ANTIDILUTION_TOOLS].forEach(tool => {
    if (enabled[tool.id] && tool.param) {
      let val = paramValues[tool.param.key] ?? tool.param.defaultVal
      if (tool.param.type === 'pct') val = val / 100
      if (tool.param.type === 'bps') val = val / 10_000
      cfg[tool.param.key] = val
    }
  })

  return cfg
}

function shortfallColor(eur_val) {
  if (eur_val <= 0) return 'var(--kpi-green-text)'
  return 'var(--kpi-red-text)'
}

function deltaColor(delta) {
  if (delta < 0) return 'var(--kpi-green-text)'
  if (delta > 0) return 'var(--kpi-red-text)'
  return 'var(--text-muted)'
}

// ---------------------------------------------------------------------------
// Sub-components (named exports)
// ---------------------------------------------------------------------------

export function InfoCard({ tool }) {
  const { t } = useTranslation()
  const toolData = t(`lmt.tools.${tool.id}`, { returnObjects: true })
  return (
    <div className="rounded border p-3" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border)' }}>
      <div className="font-semibold text-xs" style={{ color: 'var(--text-primary)' }}>{toolData.label}</div>
      <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>{toolData.description}</div>
      <div className="mt-1 text-xs font-medium" style={{ color: 'var(--text-accent)' }}>{t('lmt.alwaysAvailableNote')}</div>
    </div>
  )
}

export function ToolCard({ tool, enabled, paramValues, onToggle, onParam }) {
  const { t } = useTranslation()
  const isOn = !!enabled[tool.id]
  const toolData = t(`lmt.tools.${tool.id}`, { returnObjects: true })
  const paramLabel = toolData.paramLabel ?? ''
  return (
    <div className="rounded border p-3" style={{
      background: 'var(--bg-surface)',
      borderColor: isOn ? 'var(--text-accent)' : 'var(--border)',
    }}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1">
          <div className="font-semibold text-xs" style={{ color: 'var(--text-primary)' }}>{toolData.label}</div>
          {isOn && <div className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>{toolData.description}</div>}
        </div>
        <button
          onClick={() => onToggle(tool.id)}
          className="shrink-0 rounded text-xs px-2 py-1 font-semibold transition-colors cursor-pointer"
          style={isOn
            ? { background: 'var(--text-accent)', color: '#fff' }
            : { background: 'var(--bg-panel)', color: 'var(--text-secondary)', border: '1px solid var(--border)' }
          }
        >
          {isOn ? 'ON' : 'OFF'}
        </button>
      </div>
      {isOn && tool.param && (
        <div className="mt-2 flex items-center gap-2">
          <label className="text-xs" style={{ color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
            {paramLabel}
          </label>
          <input
            type="range"
            min={tool.param.min}
            max={tool.param.max}
            step={tool.param.step}
            value={paramValues[tool.param.key] ?? tool.param.defaultVal}
            onChange={e => onParam(tool.param.key, Number(e.target.value))}
            className="flex-1 accent-[var(--text-accent)]"
          />
          <span className="text-xs font-semibold w-14 text-right" style={{ color: 'var(--text-primary)' }}>
            {paramDisplay(tool, paramValues)}
          </span>
        </div>
      )}
    </div>
  )
}

export function ComplianceStrip({ enabled, onRun, loading }) {
  const { t } = useTranslation()
  const selectableIds = [...QUANTITATIVE_TOOLS, ...ANTIDILUTION_TOOLS].map(t => t.id)
  const selectedCount = selectableIds.filter(id => enabled[id]).length
  const swingOnly = enabled['swing_pricing'] && enabled['dual_pricing'] &&
    selectableIds.filter(id => enabled[id] && id !== 'swing_pricing' && id !== 'dual_pricing').length === 0
  const tooFew = selectedCount < 2

  return (
    <div className="rounded border p-3 mt-3" style={{ background: 'var(--bg-panel)', borderColor: 'var(--border)' }}>
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs font-semibold" style={{ color: 'var(--text-secondary)' }}>
            {t('lmt.compliance')}
          </span>
          <span className="text-xs font-semibold" style={{ color: tooFew ? 'var(--kpi-red-text)' : 'var(--kpi-green-text)' }}>
            {t('lmt.toolsSelected', { count: selectedCount })}
            {tooFew ? ` ${t('lmt.minRequired')}` : ' ✓'}
          </span>
          {swingOnly && (
            <span className="text-xs font-semibold" style={{ color: 'var(--kpi-red-text)' }}>
              {t('lmt.swingDualProhibited')}
            </span>
          )}
        </div>
        <button
          onClick={onRun}
          disabled={loading}
          className="rounded px-4 py-1.5 text-xs font-semibold transition-colors cursor-pointer disabled:opacity-50"
          style={{ background: 'var(--text-accent)', color: '#fff' }}
        >
          {loading ? t('lmt.running') : t('lmt.applyToTables')}
        </button>
      </div>
    </div>
  )
}

export function CoverageTable({ normal, stress, baseNormal, baseStress, hasConfigured }) {
  const { t } = useTranslation()
  if (!baseNormal?.length) return null

  const rows = baseNormal.map((bn, i) => {
    const n = (hasConfigured ? normal?.[i] : bn) || bn
    const s = (hasConfigured ? stress?.[i] : baseStress?.[i]) || {}
    const bs = baseStress?.[i] || {}
    return { n, s, bn, bs }
  })

  return (
    <div className="rounded border overflow-auto" style={{ background: 'var(--bg-panel)', borderColor: 'var(--border)' }}>
      <div className="px-3 pt-2 pb-1 text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--text-secondary)' }}>
        {t('lmt.coverageImpact')}
      </div>
      <table className="w-full text-xs">
        <thead style={{ background: 'var(--bg-surface)', color: 'var(--text-secondary)' }}>
          <tr>
            <th className="px-3 py-2 text-left">{t('lmt.columns.scenario')}</th>
            <th className="px-3 py-2 text-right">{t('lmt.columns.shortfallBase')}</th>
            <th className="px-3 py-2 text-right">{t('lmt.columns.shortfallConfig')}</th>
            <th className="px-3 py-2 text-right">{t('lmt.columns.delta')}</th>
            <th className="px-3 py-2 text-right">{t('lmt.columns.daysBase')}</th>
            <th className="px-3 py-2 text-right">{t('lmt.columns.daysConfig')}</th>
            <th className="px-3 py-2 text-right">{t('lmt.columns.stressShortfall')}</th>
            <th className="px-3 py-2 text-left">{t('lmt.columns.toolsActive')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ n, s, bn, bs }, i) => {
            const baseSf = bn.shortfall_eur ?? 0
            const cfgSf = hasConfigured ? (n.shortfall_eur ?? 0) : null
            const delta = cfgSf != null ? cfgSf - baseSf : null
            const rowBg = i % 2 === 0 ? 'var(--bg-panel)' : 'var(--bg-surface)'
            const sfColor = cfgSf != null ? (cfgSf <= 0 ? 'var(--kpi-green-text)' : 'var(--kpi-red-text)') : 'var(--text-muted)'
            const stressSf = (hasConfigured ? s : bs).shortfall_eur ?? 0
            return (
              <tr key={i} style={{ background: rowBg }}>
                <td className="px-3 py-2 font-semibold" style={{ color: 'var(--text-primary)' }}>{pct(bn.scenario_pct)}</td>
                <td className="px-3 py-2 text-right" style={{ color: shortfallColor(baseSf) }}>{baseSf > 0 ? eur(baseSf) : '—'}</td>
                <td className="px-3 py-2 text-right font-semibold" style={{ color: sfColor }}>
                  {cfgSf == null ? <span style={{ color: 'var(--text-muted)' }}>—</span> : cfgSf > 0 ? eur(cfgSf) : '—'}
                </td>
                <td className="px-3 py-2 text-right font-semibold" style={{ color: delta != null ? deltaColor(delta) : 'var(--text-muted)' }}>
                  {delta == null ? '—' : delta === 0 ? '—' : `${delta > 0 ? '+' : ''}${eur(delta)}`}
                </td>
                <td className="px-3 py-2 text-right" style={{ color: 'var(--text-muted)' }}>{bn.days_to_clear != null ? bn.days_to_clear.toFixed(1) : '—'}</td>
                <td className="px-3 py-2 text-right" style={{ color: 'var(--text-primary)' }}>
                  {hasConfigured ? (n.days_to_clear != null ? n.days_to_clear.toFixed(1) : '—') : '—'}
                </td>
                <td className="px-3 py-2 text-right" style={{ color: stressSf > 0 ? 'var(--kpi-red-text)' : 'var(--kpi-green-text)' }}>{stressSf > 0 ? eur(stressSf) : '—'}</td>
                <td className="px-3 py-2" style={{ color: 'var(--text-muted)' }}>{(hasConfigured ? n.lmt_tools_used : bn.lmt_tools_used) || '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function InvestorCostSummary({ results }) {
  const { t } = useTranslation()
  if (!results?.length) return null

  return (
    <div className="rounded border p-3" style={{ background: 'var(--bg-panel)', borderColor: 'var(--border)' }}>
      <div className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: 'var(--text-secondary)' }}>
        {t('lmt.investorCost')}
      </div>
      <div className="flex flex-wrap gap-3">
        {results.map((r, i) => {
          const totalBps = (r.adl_bps || 0) + (r.fee_bps || 0) + (r.swing_factor ? r.swing_factor * 10000 : 0) + (r.dual_spread_bps || 0)
          return (
            <div key={i} className="rounded border px-3 py-2 text-center min-w-20"
              style={{ background: 'var(--bg-surface)', borderColor: 'var(--border)' }}>
              <div className="text-xs" style={{ color: 'var(--text-muted)' }}>{pct(r.scenario_pct)}</div>
              <div className="font-bold text-sm" style={{ color: totalBps > 0 ? 'var(--kpi-amber-text, var(--text-accent))' : 'var(--text-muted)' }}>
                {totalBps > 0 ? `${totalBps.toFixed(0)} bps` : '—'}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function RecommendationCard({ normal, base }) {
  const { t } = useTranslation()
  if (!normal?.length) return null

  const allCovered = normal.every(r => (r.shortfall_eur || 0) <= 0)
  const uncovered = normal.filter(r => (r.shortfall_eur || 0) > 0)
  const improved = normal.filter((r, i) => (r.shortfall_eur || 0) < (base?.[i]?.shortfall_eur || 0))

  const activeToolsRaw = normal[0]?.lmt_tools_used || ''
  const activeTools = new Set(
    activeToolsRaw.split(',').map(s => s.trim().toLowerCase()).filter(Boolean)
  )
  const allToolIds = [...QUANTITATIVE_TOOLS, ...ANTIDILUTION_TOOLS].map(tool => tool.id)
  const suggestToolIds = allToolIds.filter(id => !activeTools.has(id))
  const suggestLabels = suggestToolIds.slice(0, 3).map(id => {
    const td = t(`lmt.tools.${id}`, { returnObjects: true })
    return td.label || id
  })

  return (
    <div className="rounded border p-3" style={{ background: 'var(--bg-panel)', borderColor: allCovered ? 'var(--kpi-green-border, var(--border))' : 'var(--kpi-red-border, var(--border))' }}>
      <div className="text-xs font-semibold uppercase tracking-wide mb-1" style={{ color: 'var(--text-secondary)' }}>{t('lmt.recommendation')}</div>
      {allCovered ? (
        <div className="text-xs font-semibold" style={{ color: 'var(--kpi-green-text)' }}>
          {t('lmt.allCovered')}
        </div>
      ) : (
        <div>
          <div className="text-xs font-semibold mb-1" style={{ color: 'var(--kpi-red-text)' }}>
            {t('lmt.shortfallPersists', { count: uncovered.length })}
            {' '}{uncovered.map(r => pct(r.scenario_pct)).join(', ')}
          </div>
          {improved.length > 0 && suggestToolIds.length > 0 && (
            <div className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              {t('lmt.improved', { count: improved.length })}
              {' '}{t('lmt.considerAdding', { tools: suggestLabels.join(', ') })}
            </div>
          )}
          {improved.length > 0 && suggestToolIds.length === 0 && (
            <div className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              {t('lmt.improved', { count: improved.length })}
              {' '}{t('lmt.allToolsActive')}
            </div>
          )}
          {improved.length === 0 && suggestToolIds.length > 0 && (
            <div className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              {t('lmt.noImprovement', { tools: suggestLabels.join(', ') })}
            </div>
          )}
          {improved.length === 0 && suggestToolIds.length === 0 && (
            <div className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              {t('lmt.allToolsShortfall')}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
