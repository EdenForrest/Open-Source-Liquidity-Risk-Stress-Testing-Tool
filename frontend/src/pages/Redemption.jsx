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
// Helpers
// ---------------------------------------------------------------------------

function Flag({ yes }) {
  return (
    <span className="text-xs font-semibold" style={{ color: yes ? 'var(--kpi-green-text)' : 'var(--kpi-red-text)' }}>
      {yes ? 'Yes' : 'No'}
    </span>
  )
}
function Alert({ triggered }) {
  return (
    <span className="text-xs font-semibold" style={{ color: triggered ? 'var(--kpi-red-text)' : 'var(--text-muted)' }}>
      {triggered ? 'Triggered' : '—'}
    </span>
  )
}

function RedemptionTable({ rows, label }) {
  if (!rows?.length) return null
  return (
    <div className="rounded overflow-auto th-panel border" style={{ background: 'var(--bg-panel)' }}>
      <h2 className="text-sm font-semibold uppercase tracking-wide bb-head p-2 pb-1" style={{ color: 'var(--text-secondary)' }}>{label}</h2>
      <table className="w-full text-sm">
        <thead className="text-xs uppercase" style={{ background: 'var(--bg-surface)', color: 'var(--text-secondary)' }}>
          <tr>
            {[
              { label: 'Redemption %' },
              { label: 'Amount (€)' },
              { label: 'Liquidity Available' },
              { label: 'Shortfall' },
              { label: 'Can Meet T+1' },
              { label: 'Can Meet T+3' },
              { label: 'Can Meet T+7' },
              { label: 'Gate', id: 'redemption_gate' },
              { label: 'Suspension', id: 'redemption_suspension' },
              { label: 'Days to Clear', id: 'redemption_days_to_clear' },
              { label: 'Swing Factor' },
              { label: 'ADL (bps)' },
              { label: 'LMT Status' },
            ].map(({ label, id }) => (
              <th key={label} className="px-3 py-2 text-left whitespace-nowrap">
                {id ? <MetricTooltip id={id}>{label}</MetricTooltip> : label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} style={{ background: i % 2 === 0 ? 'var(--bg-panel)' : 'var(--bg-surface)' }}>
              <td className="px-3 py-2 font-semibold" style={{ color: 'var(--text-primary)' }}>{pct(r.scenario_pct)}</td>
              <td className="px-3 py-2 text-right" style={{ color: 'var(--text-primary)' }}>{eur(r.redemption_eur)}</td>
              <td className={`px-3 py-2 text-right font-semibold ${r.shortfall_eur > 0 ? 'text-red-600' : 'text-green-600'}`}>
                {pct(r.liquidity_available_pct)}
              </td>
              <td className={`px-3 py-2 text-right ${r.shortfall_eur > 0 ? 'text-red-600 font-semibold' : ''}`} style={r.shortfall_eur > 0 ? {} : { color: 'var(--text-muted)' }}>
                {r.shortfall_eur > 0 ? eur(r.shortfall_eur) : '—'}
              </td>
              <td className="px-3 py-2 text-center"><Flag yes={r.can_meet_t1} /></td>
              <td className="px-3 py-2 text-center"><Flag yes={r.can_meet_t3} /></td>
              <td className="px-3 py-2 text-center"><Flag yes={r.can_meet_t7} /></td>
              <td className="px-3 py-2 text-center"><Alert triggered={r.gate_triggered} /></td>
              <td className="px-3 py-2 text-center"><Alert triggered={r.suspension_triggered} /></td>
              <td className="px-3 py-2 text-right" style={{ color: 'var(--text-primary)' }}>{r.days_to_clear?.toFixed(1) ?? '—'}</td>
              <td className="px-3 py-2 text-right" style={{ color: r.swing_factor > 0 ? 'var(--kpi-amber-text)' : 'var(--text-muted)' }}>
                {r.swing_factor > 0 ? pct(r.swing_factor) : '—'}
              </td>
              <td className="px-3 py-2 text-right" style={{ color: r.adl_bps > 0 ? 'var(--kpi-amber-text)' : 'var(--text-muted)' }}>
                {r.adl_bps > 0 ? r.adl_bps.toFixed(0) : '—'}
              </td>
              <td className="px-3 py-2 text-xs" style={{ color: r.lmt_activated ? 'var(--kpi-amber-text)' : 'var(--text-muted)', minWidth: '120px' }}>
                {r.lmt_tools_used || '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
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
  const [simResults, setSimResults] = useState(null)   // { normal, stress } from lmt-simulate
  const [baseResults, setBaseResults] = useState(null) // same, but with empty lmt_config
  const [loading, setLoading] = useState(false)
  const [simError, setSimError] = useState(null)

  // Auto-load baseline (no tools) when run is ready
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

  // When LMT sim has been applied, show adjusted rows in Coverage tab
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
          <button
            onClick={handleClear}
            className="ml-2 text-xs underline cursor-pointer"
            style={{ color: 'var(--text-muted)' }}
          >
            Clear
          </button>
        )}
      </div>

      {/* Coverage tab */}
      {tab === 'coverage' && (
        <div className="space-y-3">
          <RedemptionTable rows={normalRows} label="Normal Regime" />
          <RedemptionTable rows={stressRows} label="Stressed Regime" />
        </div>
      )}

      {/* LMT Simulator tab */}
      {tab === 'lmt' && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {/* Left — configurator */}
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
            {simError && (
              <div className="text-xs text-red-500 mt-1">{simError}</div>
            )}
          </div>

          {/* Right — impact dashboard */}
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
