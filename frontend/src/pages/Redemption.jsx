import { useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useAnalysis } from '../AnalysisContext'
import EmptyState from '../components/EmptyState'
import StatusBanner from '../components/StatusBanner'
import MetricTooltip from '../components/MetricTooltip'
import { pct, eur } from '../utils/formatters'
import {
  ALWAYS_AVAILABLE, QUANTITATIVE_TOOLS, ANTIDILUTION_TOOLS,
  InfoCard, ToolCard, ComplianceStrip,
  InvestorCostSummary, RecommendationCard,
  buildLmtConfig,
} from './LMTSimulator'
import client from '../api/client'

// ---------------------------------------------------------------------------
// Coverage display
// ---------------------------------------------------------------------------

function CoverageBar({ t1, t3, t7 }) {
  const isCovered = t1 || t3 || t7
  const color = isCovered ? 'var(--kpi-green-text)' : 'var(--kpi-red-text)'
  return (
    <div style={{ color, fontSize: '1.2rem', textAlign: 'center' }}>
      {isCovered ? '✓' : '✕'}
    </div>
  )
}

function HorizonBadges({ t1, t3, t7 }) {
  const Badge = ({ label, ok }) => (
    <span className="inline-flex items-center rounded px-1.5 py-0.5 text-xs font-semibold"
      style={{
        background: ok ? 'var(--kpi-green-bg, #d1fae5)' : 'var(--kpi-red-bg, #fee2e2)',
        color: ok ? 'var(--kpi-green-text)' : 'var(--kpi-red-text)',
      }}>
      {label}
    </span>
  )
  return (
    <div className="flex gap-1">
      <Badge label="T+1" ok={t1} />
      <Badge label="T+3" ok={t3} />
      <Badge label="T+7" ok={t7} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Triggered badge
// ---------------------------------------------------------------------------

function TriggerBadge({ triggered, label }) {
  if (!triggered) return <span style={{ color: 'var(--text-muted)' }}>—</span>
  return (
    <span className="inline-flex items-center rounded px-1.5 py-0.5 text-xs font-semibold"
      style={{ background: 'var(--kpi-red-bg, #fee2e2)', color: 'var(--kpi-red-text)' }}>
      {label}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Regime summary strip
// ---------------------------------------------------------------------------

function RegimeSummary({ rows, label, isStress }) {
  const { t } = useTranslation()
  if (!rows?.length) return null
  const covered = rows.filter(r => (r.shortfall_eur ?? 0) <= 0).length
  const worst = Math.max(...rows.map(r => r.shortfall_eur ?? 0))
  const maxDays = Math.max(...rows.map(r => r.days_to_clear ?? 0))
  const minCoverage = Math.min(...rows.map(r => {
    const demand = r.redemption_eur ?? 0
    return demand > 0 ? Math.min((r.liquidity_available_eur ?? 0) / demand, 1) : 1
  }))

  const tiles = [
    {
      label: t('redemption.kpi.scenariosCovered'),
      value: `${covered} / ${rows.length}`,
      sub: covered === rows.length
        ? t('redemption.kpi.allClear')
        : t('redemption.kpi.atRisk', { count: rows.length - covered }),
      ok: covered === rows.length,
    },
    {
      label: t('redemption.kpi.minCoverage'),
      value: pct(minCoverage),
      sub: t('redemption.kpi.worstScenario'),
      ok: minCoverage >= 1,
    },
    {
      label: t('redemption.kpi.maxShortfall'),
      value: worst > 0 ? eur(worst) : '—',
      sub: worst > 0 ? t('redemption.kpi.cashDeficit') : t('redemption.kpi.none'),
      ok: worst <= 0,
    },
    {
      label: t('redemption.kpi.daysToClear'),
      value: maxDays > 0 ? maxDays.toFixed(1) : '—',
      sub: t('redemption.kpi.worstCase'),
      ok: maxDays <= 7,
    },
  ]

  return (
    <div className="rounded border overflow-hidden" style={{ borderColor: 'var(--border)' }}>
      <div className="px-4 py-2 flex items-center gap-2" style={{ background: isStress ? 'var(--kpi-red-bg, #fee2e2)' : 'var(--bg-surface)', borderBottom: '1px solid var(--border)' }}>
        <span className="text-xs font-bold uppercase tracking-widest" style={{ color: isStress ? 'var(--kpi-red-text)' : 'var(--text-secondary)' }}>
          {label}
        </span>
        {isStress && (
          <span className="text-xs rounded px-2 py-0.5 font-semibold" style={{ background: 'var(--kpi-red-text)', color: '#fff' }}>
            {t('redemption.stressed')}
          </span>
        )}
      </div>
      <div className="grid grid-cols-4 divide-x" style={{ background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)', divideColor: 'var(--border)' }}>
        {tiles.map(({ label: tl, value, sub, ok }) => (
          <div key={tl} className="px-4 py-3 text-center">
            <div className="text-xs" style={{ color: 'var(--text-muted)' }}>{tl}</div>
            <div className="text-base font-bold mt-0.5" style={{ color: ok ? 'var(--kpi-green-text)' : 'var(--kpi-red-text)' }}>{value}</div>
            <div className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>{sub}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main redesigned table — base mode + before/after mode
// ---------------------------------------------------------------------------

function RedemptionTable({ rows, baseRows, label, isStress, showDelta }) {
  const { t } = useTranslation()
  if (!rows?.length) return null

  const hasBefore = showDelta && baseRows?.length === rows.length

  return (
    <div className="rounded border overflow-hidden" style={{ borderColor: 'var(--border)' }}>
      <div className="overflow-x-auto">
        <table className="w-full text-xs" style={{ background: 'var(--bg-panel)' }}>
          <thead>
            {hasBefore && (
              <tr style={{ background: 'var(--bg-surface)', borderBottom: '1px solid var(--border)' }}>
                <th colSpan={3} className="px-3 py-1.5 text-left" style={{ color: 'var(--text-muted)' }} />
                <th colSpan={4} className="px-3 py-1.5 text-center text-xs font-semibold uppercase tracking-wide border-l"
                  style={{ borderColor: 'var(--border)', color: 'var(--text-muted)', background: 'var(--bg-surface)' }}>
                  {t('redemption.withoutLmt')}
                </th>
                <th colSpan={4} className="px-3 py-1.5 text-center text-xs font-semibold uppercase tracking-wide border-l"
                  style={{ borderColor: 'var(--border)', color: 'var(--text-accent)', background: 'var(--bg-surface)' }}>
                  {t('redemption.withLmt')}
                </th>
                <th colSpan={1} className="px-3 py-1.5 text-center text-xs font-semibold uppercase tracking-wide border-l"
                  style={{ borderColor: 'var(--border)', color: 'var(--text-muted)', background: 'var(--bg-surface)' }}>
                  Δ
                </th>
                <th colSpan={3} className="px-3 py-1.5 text-left border-l" style={{ borderColor: 'var(--border)' }} />
              </tr>
            )}
            <tr className="text-xs font-semibold uppercase tracking-wide" style={{ background: 'var(--bg-surface)', color: 'var(--text-secondary)', borderBottom: '1px solid var(--border)' }}>
              <th className="px-3 py-2 text-left whitespace-nowrap">{t('redemption.columns.scenario')}</th>
              <th className="px-3 py-2 text-right whitespace-nowrap">{t('redemption.columns.demand')}</th>

              {hasBefore ? (
                <>
                  <th className="px-3 py-2 text-center whitespace-nowrap border-l" style={{ borderColor: 'var(--border)' }}>{t('redemption.columns.horizons')}</th>
                  <th className="px-3 py-2 text-left whitespace-nowrap">{t('redemption.columns.coverage')}</th>
                  <th className="px-3 py-2 text-right whitespace-nowrap">{t('redemption.columns.shortfall')}</th>
                  <th className="px-3 py-2 text-right whitespace-nowrap">{t('redemption.columns.days')}</th>
                  <th className="px-3 py-2 text-center whitespace-nowrap border-l" style={{ borderColor: 'var(--border)' }}>{t('redemption.columns.horizons')}</th>
                  <th className="px-3 py-2 text-left whitespace-nowrap">{t('redemption.columns.coverage')}</th>
                  <th className="px-3 py-2 text-right whitespace-nowrap">{t('redemption.columns.shortfall')}</th>
                  <th className="px-3 py-2 text-right whitespace-nowrap">{t('redemption.columns.days')}</th>
                  <th className="px-3 py-2 text-right whitespace-nowrap border-l" style={{ borderColor: 'var(--border)' }}>{t('redemption.columns.deltaShortfall')}</th>
                </>
              ) : (
                <>
                  <th className="px-3 py-2 text-left whitespace-nowrap">
                    {!isStress ? <MetricTooltip id="redemption_coverage">{t('redemption.columns.coverage')}</MetricTooltip> : t('redemption.columns.coverage')}
                  </th>
                  <th className="px-3 py-2 text-right whitespace-nowrap">{t('redemption.columns.daysToClear')}</th>
                  <th className="px-3 py-2 text-right whitespace-nowrap">{t('redemption.columns.shortfall')}</th>
                </>
              )}

              <th className="px-3 py-2 text-center whitespace-nowrap border-l" style={{ borderColor: 'var(--border)' }}>
                {!isStress ? <MetricTooltip id="redemption_gate">{t('redemption.columns.gate')}</MetricTooltip> : t('redemption.columns.gate')}
              </th>
              <th className="px-3 py-2 text-center whitespace-nowrap">
                {!isStress ? <MetricTooltip id="redemption_suspension">{t('redemption.columns.suspend')}</MetricTooltip> : t('redemption.columns.suspend')}
              </th>
              <th className="px-3 py-2 text-right whitespace-nowrap">{t('redemption.columns.costBps')}</th>
              <th className="px-3 py-2 text-left whitespace-nowrap">{t('redemption.columns.activeTools')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const base = hasBefore ? baseRows[i] : null
              const rowBg = i % 2 === 0 ? 'var(--bg-panel)' : 'var(--bg-surface)'
              const sf = r.shortfall_eur ?? 0
              const baseSf = base?.shortfall_eur ?? 0
              const delta = hasBefore ? sf - baseSf : null
              const totalCostBps = (r.adl_bps || 0)
                + (r.fee_bps || 0)
                + ((r.swing_factor || 0) * 10000)
                + (r.dual_spread_bps || 0)

              return (
                <tr key={i} style={{ background: rowBg, borderBottom: '1px solid var(--border)' }}>
                  <td className="px-3 py-2.5">
                    <span className="inline-flex items-center rounded px-2 py-0.5 text-xs font-bold"
                      style={{ background: 'var(--bg-surface)', color: 'var(--text-primary)', border: '1px solid var(--border)' }}>
                      {pct(r.scenario_pct)}
                    </span>
                  </td>

                  <td className="px-3 py-2.5 text-right font-medium" style={{ color: 'var(--text-primary)' }}>
                    {eur(r.redemption_eur)}
                  </td>

                  {hasBefore ? (
                    <>
                      <td className="px-3 py-2.5 text-center border-l" style={{ borderColor: 'var(--border)' }}>
                        <HorizonBadges t1={base.can_meet_t1} t3={base.can_meet_t3} t7={base.can_meet_t7} />
                      </td>
                      <td className="px-3 py-2.5 text-center">
                        <CoverageBar t1={base.can_meet_t1} t3={base.can_meet_t3} t7={base.can_meet_t7} />
                      </td>
                      <td className="px-3 py-2.5 text-right font-medium" style={{ color: baseSf > 0 ? 'var(--kpi-red-text)' : 'var(--text-muted)' }}>
                        {baseSf > 0 ? eur(baseSf) : '—'}
                      </td>
                      <td className="px-3 py-2.5 text-right" style={{ color: 'var(--text-secondary)' }}>
                        {base?.days_to_clear != null ? base.days_to_clear.toFixed(1) : '—'}
                      </td>

                      <td className="px-3 py-2.5 text-center border-l" style={{ borderColor: 'var(--border)' }}>
                        <HorizonBadges t1={r.can_meet_t1} t3={r.can_meet_t3} t7={r.can_meet_t7} />
                      </td>
                      <td className="px-3 py-2.5 text-center">
                        <CoverageBar t1={r.can_meet_t1} t3={r.can_meet_t3} t7={r.can_meet_t7} />
                      </td>
                      <td className="px-3 py-2.5 text-right font-semibold" style={{ color: sf > 0 ? 'var(--kpi-red-text)' : 'var(--kpi-green-text)' }}>
                        {sf > 0 ? eur(sf) : '—'}
                      </td>
                      <td className="px-3 py-2.5 text-right font-medium" style={{ color: 'var(--text-primary)' }}>
                        {r.days_to_clear != null ? r.days_to_clear.toFixed(1) : '—'}
                      </td>

                      <td className="px-3 py-2.5 text-right font-bold border-l" style={{
                        borderColor: 'var(--border)',
                        color: delta < 0 ? 'var(--kpi-green-text)' : delta > 0 ? 'var(--kpi-red-text)' : 'var(--text-muted)',
                      }}>
                        {delta == null || delta === 0 ? '—' : `${delta > 0 ? '+' : ''}${eur(delta)}`}
                      </td>
                    </>
                  ) : (
                    <>
                      <td className="px-3 py-2.5 text-center border-l" style={{ borderColor: 'var(--border)' }}>
                        <HorizonBadges t1={r.can_meet_t1} t3={r.can_meet_t3} t7={r.can_meet_t7} />
                      </td>
                      <td className="px-3 py-2.5 text-center">
                        <CoverageBar t1={r.can_meet_t1} t3={r.can_meet_t3} t7={r.can_meet_t7} />
                      </td>
                      <td className="px-3 py-2.5 text-right font-semibold" style={{ color: sf > 0 ? 'var(--kpi-red-text)' : 'var(--text-muted)' }}>
                        {sf > 0 ? eur(sf) : '—'}
                      </td>
                      <td className="px-3 py-2.5 text-right" style={{ color: 'var(--text-secondary)' }}>
                        {r.days_to_clear != null ? r.days_to_clear.toFixed(1) : '—'}
                      </td>
                    </>
                  )}

                  <td className="px-3 py-2.5 text-center border-l" style={{ borderColor: 'var(--border)' }}>
                    <TriggerBadge triggered={r.gate_triggered} label={t('redemption.triggered')} />
                  </td>
                  <td className="px-3 py-2.5 text-center">
                    <TriggerBadge triggered={r.suspension_triggered} label={t('redemption.triggered')} />
                  </td>

                  <td className="px-3 py-2.5 text-right font-medium" style={{ color: totalCostBps > 0 ? 'var(--kpi-amber-text)' : 'var(--text-muted)' }}>
                    {totalCostBps > 0 ? totalCostBps.toFixed(0) : '—'}
                  </td>

                  <td className="px-3 py-2.5" style={{ color: 'var(--text-muted)', minWidth: '140px' }}>
                    {r.lmt_tools_used
                      ? r.lmt_tools_used.split(',').map(s => s.trim()).filter(Boolean).map(s => (
                          <span key={s} className="inline-block rounded mr-1 px-1.5 py-0.5 text-xs"
                            style={{ background: 'var(--kpi-amber-bg, #fef3c7)', color: 'var(--kpi-amber-text, #92400e)' }}>
                            {s}
                          </span>
                        ))
                      : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Default tool param state
// ---------------------------------------------------------------------------

function defaultParamValues() {
  const vals = {}
  ;[...QUANTITATIVE_TOOLS, ...ANTIDILUTION_TOOLS].forEach(tool => {
    if (tool.param) vals[tool.param.key] = tool.param.defaultVal
  })
  return vals
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function Redemption() {
  const { t } = useTranslation()
  const { data, error, runId, selectedPortfolio } = useAnalysis()
  const redemption = data?.redemption

  const [showLmt, setShowLmt] = useState(false)
  const [enabled, setEnabled] = useState({ gate: true, swing_pricing: true })
  const [paramValues, setParamValues] = useState(defaultParamValues)
  const [simResults, setSimResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [simError, setSimError] = useState(null)

  const handleToggle = useCallback((id) => {
    setEnabled(prev => ({ ...prev, [id]: !prev[id] }))
  }, [])

  const handleParam = useCallback((key, val) => {
    setParamValues(prev => ({ ...prev, [key]: val }))
  }, [])

  const handleRun = useCallback(async () => {
    if (!runId) return
    setLoading(true)
    setSimError(null)
    try {
      const cfg = buildLmtConfig(enabled, paramValues)
      const res = await client.post(`/run/${runId}/lmt-simulate`, {
        lmt_config: cfg,
        portfolio: selectedPortfolio || undefined,
      })
      setSimResults(res.data)
      setShowLmt(false)
    } catch (e) {
      setSimError(e?.response?.data?.detail || e.message || 'Simulation failed')
    } finally {
      setLoading(false)
    }
  }, [runId, enabled, paramValues, selectedPortfolio])

  const handleClear = useCallback(() => {
    setSimResults(null)
    setEnabled({ gate: true, swing_pricing: true })
    setParamValues(defaultParamValues())
  }, [])

  if (error) return <StatusBanner />
  if (!redemption) return <EmptyState />

  const pipelineNormal = redemption.redemption_results
  const pipelineStress = redemption.redemption_stress_results
  const normalRows = simResults ? simResults.normal : pipelineNormal
  const stressRows = simResults ? simResults.stress : pipelineStress
  const hasConfigured = !!simResults

  return (
    <div className="p-3 space-y-3">
      {/* Header bar */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => setShowLmt(v => !v)}
          className="flex items-center gap-1.5 rounded border px-3 py-1.5 text-xs font-semibold transition-colors cursor-pointer"
          style={showLmt
            ? { background: 'var(--text-accent)', color: '#fff', borderColor: 'var(--text-accent)' }
            : { background: 'var(--bg-panel)', color: 'var(--text-secondary)', borderColor: 'var(--border)' }
          }
        >
          <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="8" cy="8" r="3"/><line x1="8" y1="1" x2="8" y2="3"/><line x1="8" y1="13" x2="8" y2="15"/>
            <line x1="1" y1="8" x2="3" y2="8"/><line x1="13" y1="8" x2="15" y2="8"/>
          </svg>
          {t('redemption.configureLmts')}
        </button>
        {hasConfigured && (
          <span className="rounded px-2 py-0.5 text-xs font-semibold"
            style={{ background: 'var(--kpi-amber-bg, #fef3c7)', color: 'var(--kpi-amber-text, #92400e)' }}>
            {t('redemption.lmtActive')}
          </span>
        )}
        {hasConfigured && (
          <button onClick={handleClear} className="text-xs underline cursor-pointer" style={{ color: 'var(--text-muted)' }}>
            {t('redemption.clear')}
          </button>
        )}
      </div>

      {/* Inline LMT configurator — collapsible */}
      {showLmt && (
        <div className="rounded border" style={{ borderColor: 'var(--border)', background: 'var(--bg-surface)' }}>
          <div className="px-4 py-2 border-b flex items-center justify-between" style={{ borderColor: 'var(--border)' }}>
            <span className="text-xs font-bold uppercase tracking-widest" style={{ color: 'var(--text-secondary)' }}>
              {t('lmt.panelTitle')}
            </span>
            <button onClick={() => setShowLmt(false)} className="text-xs cursor-pointer" style={{ color: 'var(--text-muted)' }}>✕</button>
          </div>
          <div className="p-4 grid grid-cols-1 xl:grid-cols-2 gap-4">
            <div className="space-y-3">
              <div className="text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--text-muted)' }}>{t('lmt.alwaysAvailable')}</div>
              {ALWAYS_AVAILABLE.map(tool => <InfoCard key={tool.id} tool={tool} />)}

              <div className="text-xs font-semibold uppercase tracking-wide mt-1" style={{ color: 'var(--text-muted)' }}>{t('lmt.quantitativeTools')}</div>
              {QUANTITATIVE_TOOLS.map(tool => (
                <ToolCard key={tool.id} tool={tool} enabled={enabled} paramValues={paramValues}
                  onToggle={handleToggle} onParam={handleParam} />
              ))}

              <div className="text-xs font-semibold uppercase tracking-wide mt-1" style={{ color: 'var(--text-muted)' }}>{t('lmt.antiDilutionTools')}</div>
              {ANTIDILUTION_TOOLS.map(tool => (
                <ToolCard key={tool.id} tool={tool} enabled={enabled} paramValues={paramValues}
                  onToggle={handleToggle} onParam={handleParam} />
              ))}

              <ComplianceStrip enabled={enabled} onRun={handleRun} loading={loading} />
              {simError && <div className="text-xs mt-1" style={{ color: 'var(--kpi-red-text)' }}>{simError}</div>}
            </div>

            {hasConfigured && (
              <div className="space-y-3">
                <InvestorCostSummary results={simResults.normal} />
                <RecommendationCard normal={simResults.normal} base={pipelineNormal} />
              </div>
            )}
          </div>
        </div>
      )}

      {/* Active LMT strip */}
      {hasConfigured && simResults?.lmt_config_applied && (
        <div className="rounded border px-3 py-2 flex items-center gap-2 flex-wrap"
          style={{ borderColor: 'var(--kpi-amber-text, #92400e)', background: 'var(--kpi-amber-bg, #fef3c7)' }}>
          <span className="text-xs font-bold" style={{ color: 'var(--kpi-amber-text, #92400e)' }}>
            {t('redemption.lmtSimActive')}
          </span>
          {(simResults.lmt_config_applied.active_tools || []).map(tool => (
            <span key={tool} className="rounded px-1.5 py-0.5 text-xs font-semibold"
              style={{ background: 'var(--kpi-amber-text, #92400e)', color: '#fff' }}>
              {tool.replace(/_/g, ' ')}
            </span>
          ))}
        </div>
      )}

      {/* Coverage tables */}
      <div className="space-y-5">
        <div className="space-y-2">
          <RegimeSummary rows={normalRows} label={t('redemption.normalRegime')} isStress={false} />
          <RedemptionTable
            rows={normalRows}
            baseRows={hasConfigured ? pipelineNormal : null}
            label={t('redemption.normalRegime')}
            isStress={false}
            showDelta={hasConfigured}
          />
        </div>

        <div className="space-y-2">
          <RegimeSummary rows={stressRows} label={t('redemption.stressedRegime')} isStress={true} />
          <RedemptionTable
            rows={stressRows}
            baseRows={hasConfigured ? pipelineStress : null}
            label={t('redemption.stressedRegime')}
            isStress={true}
            showDelta={hasConfigured}
          />
        </div>
      </div>
    </div>
  )
}
