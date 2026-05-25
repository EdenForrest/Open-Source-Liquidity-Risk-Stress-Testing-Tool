import { useState, useEffect, useCallback } from 'react'
import { useAnalysis } from '../AnalysisContext'
import EmptyState from '../components/EmptyState'
import StatusBanner from '../components/StatusBanner'
import MetricTooltip from '../components/MetricTooltip'
import { pct, eur } from '../utils/formatters'
import {
  ALWAYS_AVAILABLE, QUANTITATIVE_TOOLS, ANTIDILUTION_TOOLS,
  InfoCard, ToolCard, ComplianceStrip, CoverageTable,
  InvestorCostSummary, RecommendationCard,
  buildLmtConfig,
} from './LMTSimulator'
import client from '../api/client'

// ---------------------------------------------------------------------------
// Coverage bar
// ---------------------------------------------------------------------------

function CoverageBar({ pctVal }) {
  const clamped = Math.min(Math.max(pctVal ?? 0, 0), 1)
  const w = `${(clamped * 100).toFixed(1)}%`
  const color = clamped >= 1 ? 'var(--kpi-green-text)' : clamped >= 0.7 ? 'var(--kpi-amber-text)' : 'var(--kpi-red-text)'
  const bg = clamped >= 1 ? 'var(--kpi-green-bg, #d1fae5)' : clamped >= 0.7 ? 'var(--kpi-amber-bg, #fef3c7)' : 'var(--kpi-red-bg, #fee2e2)'
  return (
    <div className="flex items-center gap-2 min-w-28">
      <div className="flex-1 rounded-full overflow-hidden h-1.5" style={{ background: 'var(--bg-surface)' }}>
        <div className="h-full rounded-full transition-all" style={{ width: w, background: color }} />
      </div>
      <span className="text-xs font-semibold tabular-nums" style={{ color, minWidth: '3rem', textAlign: 'right' }}>{pct(pctVal)}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Horizon badges
// ---------------------------------------------------------------------------

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
  if (!rows?.length) return null
  const covered = rows.filter(r => (r.shortfall_eur ?? 0) <= 0).length
  const worst = Math.max(...rows.map(r => r.shortfall_eur ?? 0))
  const maxDays = Math.max(...rows.map(r => r.days_to_clear ?? 0))
  const minCoverage = Math.min(...rows.map(r => r.liquidity_available_pct ?? 0))

  const tiles = [
    {
      label: 'Scenarios Covered',
      value: `${covered} / ${rows.length}`,
      sub: covered === rows.length ? 'All clear' : `${rows.length - covered} at risk`,
      ok: covered === rows.length,
    },
    {
      label: 'Min Coverage',
      value: pct(minCoverage),
      sub: 'Worst scenario',
      ok: minCoverage >= 1,
    },
    {
      label: 'Max Shortfall',
      value: worst > 0 ? eur(worst) : '—',
      sub: worst > 0 ? 'cash deficit' : 'none',
      ok: worst <= 0,
    },
    {
      label: 'Days to Clear',
      value: maxDays > 0 ? maxDays.toFixed(1) : '—',
      sub: 'worst case',
      ok: maxDays <= 7,
    },
  ]

  return (
    <div className="rounded border overflow-hidden" style={{ borderColor: 'var(--border)' }}>
      {/* Regime header */}
      <div className="px-4 py-2 flex items-center gap-2" style={{ background: isStress ? 'var(--kpi-red-bg, #fee2e2)' : 'var(--bg-surface)', borderBottom: '1px solid var(--border)' }}>
        <span className="text-xs font-bold uppercase tracking-widest" style={{ color: isStress ? 'var(--kpi-red-text)' : 'var(--text-secondary)' }}>
          {label}
        </span>
        {isStress && (
          <span className="text-xs rounded px-2 py-0.5 font-semibold" style={{ background: 'var(--kpi-red-text)', color: '#fff' }}>
            Stressed
          </span>
        )}
      </div>
      {/* KPI strip */}
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
                <th colSpan={3} className="px-3 py-1.5 text-center text-xs font-semibold uppercase tracking-wide border-l"
                  style={{ borderColor: 'var(--border)', color: 'var(--text-muted)', background: 'var(--bg-surface)' }}>
                  Without LMT
                </th>
                <th colSpan={3} className="px-3 py-1.5 text-center text-xs font-semibold uppercase tracking-wide border-l"
                  style={{ borderColor: 'var(--border)', color: 'var(--text-accent)', background: 'var(--bg-surface)' }}>
                  With LMT
                </th>
                <th colSpan={1} className="px-3 py-1.5 text-center text-xs font-semibold uppercase tracking-wide border-l"
                  style={{ borderColor: 'var(--border)', color: 'var(--text-muted)', background: 'var(--bg-surface)' }}>
                  Δ
                </th>
                <th colSpan={3} className="px-3 py-1.5 text-left border-l" style={{ borderColor: 'var(--border)' }} />
              </tr>
            )}
            <tr className="text-xs font-semibold uppercase tracking-wide" style={{ background: 'var(--bg-surface)', color: 'var(--text-secondary)', borderBottom: '1px solid var(--border)' }}>
              <th className="px-3 py-2 text-left whitespace-nowrap">Scenario</th>
              <th className="px-3 py-2 text-right whitespace-nowrap">Demand (€)</th>
              <th className="px-3 py-2 text-center whitespace-nowrap">Horizons</th>

              {hasBefore ? (
                <>
                  {/* Without LMT */}
                  <th className="px-3 py-2 text-left whitespace-nowrap border-l" style={{ borderColor: 'var(--border)' }}>Coverage</th>
                  <th className="px-3 py-2 text-right whitespace-nowrap">Shortfall</th>
                  <th className="px-3 py-2 text-right whitespace-nowrap">Days</th>
                  {/* With LMT */}
                  <th className="px-3 py-2 text-left whitespace-nowrap border-l" style={{ borderColor: 'var(--border)' }}>Coverage</th>
                  <th className="px-3 py-2 text-right whitespace-nowrap">Shortfall</th>
                  <th className="px-3 py-2 text-right whitespace-nowrap">Days</th>
                  {/* Delta */}
                  <th className="px-3 py-2 text-right whitespace-nowrap border-l" style={{ borderColor: 'var(--border)' }}>Δ Shortfall</th>
                </>
              ) : (
                <>
                  <th className="px-3 py-2 text-left whitespace-nowrap">Coverage</th>
                  <th className="px-3 py-2 text-right whitespace-nowrap">
                    <MetricTooltip id="redemption_days_to_clear">Days to Clear</MetricTooltip>
                  </th>
                  <th className="px-3 py-2 text-right whitespace-nowrap">Shortfall</th>
                </>
              )}

              <th className="px-3 py-2 text-center whitespace-nowrap border-l" style={{ borderColor: 'var(--border)' }}>
                <MetricTooltip id="redemption_gate">Gate</MetricTooltip>
              </th>
              <th className="px-3 py-2 text-center whitespace-nowrap">
                <MetricTooltip id="redemption_suspension">Suspend</MetricTooltip>
              </th>
              <th className="px-3 py-2 text-right whitespace-nowrap">Cost (bps)</th>
              <th className="px-3 py-2 text-left whitespace-nowrap">Active Tools</th>
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
                + ((r.fee_rate || 0) * 10000)
                + ((r.swing_factor || 0) * 10000)
                + (r.dual_spread_bps || 0)

              return (
                <tr key={i} style={{ background: rowBg, borderBottom: '1px solid var(--border)' }}>
                  {/* Scenario */}
                  <td className="px-3 py-2.5">
                    <span className="inline-flex items-center rounded px-2 py-0.5 text-xs font-bold"
                      style={{ background: 'var(--bg-surface)', color: 'var(--text-primary)', border: '1px solid var(--border)' }}>
                      {pct(r.scenario_pct)}
                    </span>
                  </td>

                  {/* Demand */}
                  <td className="px-3 py-2.5 text-right font-medium" style={{ color: 'var(--text-primary)' }}>
                    {eur(r.redemption_eur)}
                  </td>

                  {/* Horizons */}
                  <td className="px-3 py-2.5 text-center">
                    <HorizonBadges t1={r.can_meet_t1} t3={r.can_meet_t3} t7={r.can_meet_t7} />
                  </td>

                  {hasBefore ? (
                    <>
                      {/* Without LMT — coverage */}
                      <td className="px-3 py-2.5 border-l" style={{ borderColor: 'var(--border)' }}>
                        <CoverageBar pctVal={base?.liquidity_available_pct} />
                      </td>
                      <td className="px-3 py-2.5 text-right font-medium" style={{ color: baseSf > 0 ? 'var(--kpi-red-text)' : 'var(--text-muted)' }}>
                        {baseSf > 0 ? eur(baseSf) : '—'}
                      </td>
                      <td className="px-3 py-2.5 text-right" style={{ color: 'var(--text-secondary)' }}>
                        {base?.days_to_clear != null ? base.days_to_clear.toFixed(1) : '—'}
                      </td>

                      {/* With LMT — coverage */}
                      <td className="px-3 py-2.5 border-l" style={{ borderColor: 'var(--border)' }}>
                        <CoverageBar pctVal={r.liquidity_available_pct} />
                      </td>
                      <td className="px-3 py-2.5 text-right font-semibold" style={{ color: sf > 0 ? 'var(--kpi-red-text)' : 'var(--kpi-green-text)' }}>
                        {sf > 0 ? eur(sf) : '—'}
                      </td>
                      <td className="px-3 py-2.5 text-right font-medium" style={{ color: 'var(--text-primary)' }}>
                        {r.days_to_clear != null ? r.days_to_clear.toFixed(1) : '—'}
                      </td>

                      {/* Delta */}
                      <td className="px-3 py-2.5 text-right font-bold border-l" style={{
                        borderColor: 'var(--border)',
                        color: delta < 0 ? 'var(--kpi-green-text)' : delta > 0 ? 'var(--kpi-red-text)' : 'var(--text-muted)',
                      }}>
                        {delta == null || delta === 0 ? '—' : `${delta > 0 ? '+' : ''}${eur(delta)}`}
                      </td>
                    </>
                  ) : (
                    <>
                      <td className="px-3 py-2.5">
                        <CoverageBar pctVal={r.liquidity_available_pct} />
                      </td>
                      <td className="px-3 py-2.5 text-right" style={{ color: 'var(--text-secondary)' }}>
                        {r.days_to_clear != null ? r.days_to_clear.toFixed(1) : '—'}
                      </td>
                      <td className="px-3 py-2.5 text-right font-semibold" style={{ color: sf > 0 ? 'var(--kpi-red-text)' : 'var(--text-muted)' }}>
                        {sf > 0 ? eur(sf) : '—'}
                      </td>
                    </>
                  )}

                  {/* Gate + Suspend */}
                  <td className="px-3 py-2.5 text-center border-l" style={{ borderColor: 'var(--border)' }}>
                    <TriggerBadge triggered={r.gate_triggered} label="Gate" />
                  </td>
                  <td className="px-3 py-2.5 text-center">
                    <TriggerBadge triggered={r.suspension_triggered} label="Suspend" />
                  </td>

                  {/* Cost */}
                  <td className="px-3 py-2.5 text-right font-medium" style={{ color: totalCostBps > 0 ? 'var(--kpi-amber-text)' : 'var(--text-muted)' }}>
                    {totalCostBps > 0 ? totalCostBps.toFixed(0) : '—'}
                  </td>

                  {/* Active tools */}
                  <td className="px-3 py-2.5" style={{ color: 'var(--text-muted)', minWidth: '140px' }}>
                    {r.lmt_tools_used
                      ? r.lmt_tools_used.split(',').map(t => t.trim()).filter(Boolean).map(t => (
                          <span key={t} className="inline-block rounded mr-1 px-1.5 py-0.5 text-xs"
                            style={{ background: 'var(--kpi-amber-bg, #fef3c7)', color: 'var(--kpi-amber-text, #92400e)' }}>
                            {t}
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
  ;[...QUANTITATIVE_TOOLS, ...ANTIDILUTION_TOOLS].forEach(t => {
    if (t.param) vals[t.param.key] = t.param.defaultVal
  })
  return vals
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function Redemption() {
  const { data, error, runId, selectedPortfolio } = useAnalysis()
  const redemption = data?.redemption

  const [tab, setTab] = useState('coverage')
  const [enabled, setEnabled] = useState({ gate: true, swing_pricing: true })
  const [paramValues, setParamValues] = useState(defaultParamValues)
  const [simResults, setSimResults] = useState(null)
  const [baseResults, setBaseResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [simError, setSimError] = useState(null)

  useEffect(() => {
    if (!runId || !redemption) return
    let cancelled = false
    client.post(`/api/run/${runId}/lmt-simulate`, {
      lmt_config: { active_tools: [] },
      portfolio: selectedPortfolio || undefined,
    }).then(res => {
      if (!cancelled) setBaseResults(res.data)
    }).catch(() => {})
    return () => { cancelled = true }
  }, [runId, redemption, selectedPortfolio])

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
      const res = await client.post(`/api/run/${runId}/lmt-simulate`, {
        lmt_config: cfg,
        portfolio: selectedPortfolio || undefined,
      })
      setSimResults(res.data)
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

  const normalRows = simResults ? simResults.normal : redemption.redemption_results
  const stressRows = simResults ? simResults.stress : redemption.redemption_stress_results
  const hasConfigured = !!simResults

  const TABS = [
    { id: 'coverage', label: 'Coverage' },
    { id: 'lmt', label: 'LMT Simulator' },
  ]

  return (
    <div className="p-3 space-y-3">
      {/* Tab bar */}
      <div className="flex items-center gap-0 border-b" style={{ borderColor: 'var(--border)' }}>
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className="px-4 py-2 text-sm font-semibold transition-colors cursor-pointer"
            style={tab === t.id
              ? { color: 'var(--text-accent)', borderBottom: '2px solid var(--text-accent)', marginBottom: '-1px' }
              : { color: 'var(--text-secondary)', borderBottom: '2px solid transparent' }
            }
          >
            {t.label}
          </button>
        ))}
        {hasConfigured && (
          <span className="ml-3 rounded px-2 py-0.5 text-xs font-semibold"
            style={{ background: 'var(--kpi-amber-bg, #fef3c7)', color: 'var(--kpi-amber-text, #92400e)' }}>
            LMT Active
          </span>
        )}
        {hasConfigured && (
          <button onClick={handleClear} className="ml-2 text-xs underline cursor-pointer" style={{ color: 'var(--text-muted)' }}>
            Clear
          </button>
        )}
      </div>

      {/* Coverage tab */}
      {tab === 'coverage' && (
        <div className="space-y-5">
          {/* Normal regime */}
          <div className="space-y-2">
            <RegimeSummary rows={normalRows} label="Normal Regime" isStress={false} />
            <RedemptionTable
              rows={normalRows}
              baseRows={hasConfigured ? baseResults?.normal : null}
              label="Normal Regime"
              isStress={false}
              showDelta={hasConfigured}
            />
          </div>

          {/* Stressed regime */}
          <div className="space-y-2">
            <RegimeSummary rows={stressRows} label="Stressed Regime" isStress={true} />
            <RedemptionTable
              rows={stressRows}
              baseRows={hasConfigured ? baseResults?.stress : null}
              label="Stressed Regime"
              isStress={true}
              showDelta={hasConfigured}
            />
          </div>
        </div>
      )}

      {/* LMT Simulator tab */}
      {tab === 'lmt' && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <div className="space-y-3">
            <div className="text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--text-secondary)' }}>
              Always Available
            </div>
            {ALWAYS_AVAILABLE.map(t => <InfoCard key={t.id} tool={t} />)}

            <div className="text-xs font-semibold uppercase tracking-wide mt-2" style={{ color: 'var(--text-secondary)' }}>
              Quantitative Tools
            </div>
            {QUANTITATIVE_TOOLS.map(t => (
              <ToolCard key={t.id} tool={t} enabled={enabled} paramValues={paramValues}
                onToggle={handleToggle} onParam={handleParam} />
            ))}

            <div className="text-xs font-semibold uppercase tracking-wide mt-2" style={{ color: 'var(--text-secondary)' }}>
              Anti-Dilution Tools
            </div>
            {ANTIDILUTION_TOOLS.map(t => (
              <ToolCard key={t.id} tool={t} enabled={enabled} paramValues={paramValues}
                onToggle={handleToggle} onParam={handleParam} />
            ))}

            <ComplianceStrip enabled={enabled} onRun={handleRun} loading={loading} />
            {simError && <div className="text-xs text-red-500 mt-1">{simError}</div>}
          </div>

          <div className="space-y-3">
            <CoverageTable
              normal={simResults?.normal}
              stress={simResults?.stress}
              baseNormal={baseResults?.normal}
              baseStress={baseResults?.stress}
              hasConfigured={hasConfigured}
            />
            {hasConfigured && (
              <>
                <InvestorCostSummary results={simResults.normal} />
                <RecommendationCard normal={simResults.normal} base={baseResults?.normal} />
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
