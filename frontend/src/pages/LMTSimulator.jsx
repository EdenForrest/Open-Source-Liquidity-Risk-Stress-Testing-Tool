import { useState, useCallback, useEffect } from 'react'
import { useAnalysis } from '../AnalysisContext'
import EmptyState from '../components/EmptyState'
import { pct, eur } from '../utils/formatters'
import client from '../api/client'

// ---------------------------------------------------------------------------
// AIFMD II tool taxonomy
// ---------------------------------------------------------------------------

const ALWAYS_AVAILABLE = [
  {
    id: 'suspension',
    label: 'Temporary Suspension',
    description: 'Fully halts redemptions during severe market dislocations. Always available; requires regulatory notification.',
    informational: true,
  },
  {
    id: 'side_pockets',
    label: 'Side Pockets',
    description: 'Segregates illiquid assets from the liquid portfolio, protecting continuing investors from dilution.',
    informational: true,
  },
]

const QUANTITATIVE_TOOLS = [
  {
    id: 'gate',
    label: 'Redemption Gate',
    description: 'Limits redemptions to a maximum percentage of NAV per dealing day.',
    param: { key: 'gate_threshold', label: 'Gate threshold (% NAV)', type: 'pct', min: 2, max: 25, step: 1, defaultVal: 10 },
  },
  {
    id: 'notice_period_extension',
    label: 'Notice Period Extension',
    description: 'Extends the notice period before redemption payment is due, giving the fund more time to liquidate.',
    param: { key: 'notice_extension_days', label: 'Extension (days)', type: 'int', min: 0, max: 30, step: 1, defaultVal: 7 },
  },
  {
    id: 'redemption_in_kind',
    label: 'Redemptions in Kind',
    description: 'Satisfies a portion of redemptions via asset transfer instead of cash. Professional investors only.',
    param: { key: 'in_kind_pct', label: 'In-kind fraction (% of redemption)', type: 'pct', min: 0, max: 100, step: 5, defaultVal: 25 },
  },
]

const ANTIDILUTION_TOOLS = [
  {
    id: 'redemption_fee',
    label: 'Redemption Fee',
    description: 'A fee charged to redeeming investors, retained in the fund to offset liquidation costs.',
    param: { key: 'fee_rate', label: 'Fee rate (bps)', type: 'bps', min: 0, max: 200, step: 5, defaultVal: 50 },
  },
  {
    id: 'swing_pricing',
    label: 'Swing Pricing',
    description: 'Adjusts NAV to reflect transaction costs when net flows exceed a threshold.',
    param: { key: 'swing_threshold', label: 'Swing threshold (% NAV)', type: 'pct', min: 1, max: 20, step: 1, defaultVal: 5 },
  },
  {
    id: 'dual_pricing',
    label: 'Dual Pricing',
    description: 'Publishes separate bid/offer prices; subscriptions/redemptions transact at the corresponding price.',
    param: { key: 'dual_spread_bps', label: 'Bid/ask spread (bps)', type: 'bps', min: 0, max: 150, step: 5, defaultVal: 30 },
  },
  {
    id: 'adl',
    label: 'Anti-Dilution Levy (ADL)',
    description: 'An explicit charge to redeeming investors equal to the estimated cost of liquidating assets.',
    param: { key: 'adl_rate', label: 'ADL rate (bps)', type: 'bps', min: 0, max: 200, step: 5, defaultVal: 50 },
  },
]

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function paramDisplay(tool, paramValues) {
  if (!tool.param) return null
  const v = paramValues[tool.param.key] ?? tool.param.defaultVal
  if (tool.param.type === 'pct') return `${v}%`
  if (tool.param.type === 'bps') return `${v} bps`
  return `${v} days`
}

function buildLmtConfig(enabled, paramValues) {
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
// Sub-components
// ---------------------------------------------------------------------------

function InfoCard({ tool }) {
  return (
    <div className="rounded border p-3" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border)' }}>
      <div className="font-semibold text-xs" style={{ color: 'var(--text-primary)' }}>{tool.label}</div>
      <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>{tool.description}</div>
      <div className="mt-1 text-xs font-medium" style={{ color: 'var(--text-accent)' }}>Always available — no selection required</div>
    </div>
  )
}

function ToolCard({ tool, enabled, paramValues, onToggle, onParam }) {
  const isOn = !!enabled[tool.id]
  return (
    <div className="rounded border p-3" style={{
      background: 'var(--bg-surface)',
      borderColor: isOn ? 'var(--text-accent)' : 'var(--border)',
      opacity: 1,
    }}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1">
          <div className="font-semibold text-xs" style={{ color: 'var(--text-primary)' }}>{tool.label}</div>
          <div className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>{tool.description}</div>
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
            {tool.param.label}
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

function ComplianceStrip({ enabled, onRun, loading }) {
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
            AIFMD II Compliance:
          </span>
          <span className="text-xs font-semibold" style={{ color: tooFew ? 'var(--kpi-red-text)' : 'var(--kpi-green-text)' }}>
            {selectedCount} selectable tool{selectedCount !== 1 ? 's' : ''} selected
            {tooFew ? ' (min 2 required)' : ' ✓'}
          </span>
          {swingOnly && (
            <span className="text-xs font-semibold" style={{ color: 'var(--kpi-red-text)' }}>
              ⚠ Swing Pricing + Dual Pricing alone is prohibited under AIFMD II
            </span>
          )}
        </div>
        <button
          onClick={onRun}
          disabled={loading}
          className="rounded px-4 py-1.5 text-xs font-semibold transition-colors cursor-pointer disabled:opacity-50"
          style={{ background: 'var(--text-accent)', color: '#fff' }}
        >
          {loading ? 'Running…' : 'Run Simulation'}
        </button>
      </div>
    </div>
  )
}

function CoverageTable({ normal, stress, baseNormal, baseStress, hasConfigured }) {
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
        Coverage Impact by Scenario
      </div>
      <table className="w-full text-xs">
        <thead style={{ background: 'var(--bg-surface)', color: 'var(--text-secondary)' }}>
          <tr>
            <th className="px-3 py-2 text-left">Scenario</th>
            <th className="px-3 py-2 text-right">Shortfall (Base)</th>
            <th className="px-3 py-2 text-right">Shortfall (Config)</th>
            <th className="px-3 py-2 text-right">Δ</th>
            <th className="px-3 py-2 text-right">Days (Base)</th>
            <th className="px-3 py-2 text-right">Days (Config)</th>
            <th className="px-3 py-2 text-right">Stress Shortfall</th>
            <th className="px-3 py-2 text-left">Tools Active</th>
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

function InvestorCostSummary({ results }) {
  if (!results?.length) return null

  return (
    <div className="rounded border p-3" style={{ background: 'var(--bg-panel)', borderColor: 'var(--border)' }}>
      <div className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: 'var(--text-secondary)' }}>
        Investor Cost Summary (per scenario)
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

function RecommendationCard({ normal, base }) {
  if (!normal?.length) return null

  const allCovered = normal.every(r => (r.shortfall_eur || 0) <= 0)
  const uncovered = normal.filter(r => (r.shortfall_eur || 0) > 0)
  const improved = normal.filter((r, i) => (r.shortfall_eur || 0) < (base?.[i]?.shortfall_eur || 0))

  return (
    <div className="rounded border p-3" style={{ background: 'var(--bg-panel)', borderColor: allCovered ? 'var(--kpi-green-border, var(--border))' : 'var(--kpi-red-border, var(--border))' }}>
      <div className="text-xs font-semibold uppercase tracking-wide mb-1" style={{ color: 'var(--text-secondary)' }}>Recommendation</div>
      {allCovered ? (
        <div className="text-xs font-semibold" style={{ color: 'var(--kpi-green-text)' }}>
          ✓ Selected tools provide full liquidity coverage across all scenarios. AIFMD II minimum tool count met.
        </div>
      ) : (
        <div>
          <div className="text-xs font-semibold mb-1" style={{ color: 'var(--kpi-red-text)' }}>
            ⚠ Shortfall persists in {uncovered.length} scenario{uncovered.length > 1 ? 's' : ''}:
            {' '}{uncovered.map(r => pct(r.scenario_pct)).join(', ')}
          </div>
          {improved.length > 0 && (
            <div className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              {improved.length} scenario{improved.length > 1 ? 's' : ''} improved vs. baseline.
              Consider adding Notice Period Extension or Redemptions in Kind to close the remaining gap.
            </div>
          )}
          {improved.length === 0 && (
            <div className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              Current configuration does not improve on baseline. Consider enabling quantitative tools
              (Gate, Notice Period Extension, or Redemptions in Kind) to reduce cash demand.
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function LMTSimulator() {
  const { runId, selectedPortfolio, status, data } = useAnalysis()

  const [enabled, setEnabled] = useState({})
  const [paramValues, setParamValues] = useState({})
  const [loading, setLoading] = useState(false)
  const [simResults, setSimResults] = useState(null)
  const [baseSimResults, setBaseSimResults] = useState(null)
  const [error, setError] = useState(null)

  // Auto-run baseline (pipeline default tools) whenever runId changes
  useEffect(() => {
    if (!runId) return
    const defaultConfig = { active_tools: ['gate', 'suspension', 'swing_pricing'] }
    client.post(`/run/${runId}/lmt-simulate`, {
      lmt_config: defaultConfig,
      portfolio: selectedPortfolio || null,
    }).then(({ data: json }) => setBaseSimResults(json)).catch(() => {
      // Fall back to stored pipeline results on error
      setBaseSimResults(null)
    })
  }, [runId, selectedPortfolio])

  const baseNormal = baseSimResults?.normal || data?.redemption_results || []
  const baseStress  = baseSimResults?.stress  || data?.redemption_stress_results || []

  const handleToggle = useCallback((id) => {
    setEnabled(prev => ({ ...prev, [id]: !prev[id] }))
  }, [])

  const handleParam = useCallback((key, val) => {
    setParamValues(prev => ({ ...prev, [key]: val }))
  }, [])

  const handleRun = useCallback(async () => {
    if (!runId) return
    setLoading(true)
    setError(null)
    try {
      const lmtConfig = buildLmtConfig(enabled, paramValues)
      const { data: json } = await client.post(`/run/${runId}/lmt-simulate`, {
        lmt_config: lmtConfig,
        portfolio: selectedPortfolio || null,
      })
      setSimResults(json)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [runId, selectedPortfolio, enabled, paramValues])

  if (status !== 'complete') {
    return (
      <div className="p-6">
        <EmptyState message="Upload portfolio data to use the LMT Simulator." />
      </div>
    )
  }

  return (
    <div className="flex gap-4" style={{ height: 'calc(100vh - 90px)', padding: '1rem', overflow: 'hidden' }}>
      {/* Left — Tool Configurator */}
      <div className="w-72 shrink-0 flex flex-col gap-3 overflow-y-auto pr-1">
        <div className="text-sm font-bold uppercase tracking-widest" style={{ color: 'var(--text-secondary)' }}>
          LMT Configurator
        </div>

        <div>
          <div className="text-xs font-semibold uppercase mb-1" style={{ color: 'var(--text-muted)' }}>
            Always Available
          </div>
          <div className="flex flex-col gap-2">
            {ALWAYS_AVAILABLE.map(t => <InfoCard key={t.id} tool={t} />)}
          </div>
        </div>

        <div>
          <div className="text-xs font-semibold uppercase mb-1" style={{ color: 'var(--text-muted)' }}>
            Quantitative Tools
          </div>
          <div className="flex flex-col gap-2">
            {QUANTITATIVE_TOOLS.map(t => (
              <ToolCard
                key={t.id}
                tool={t}
                enabled={enabled}
                paramValues={paramValues}
                onToggle={handleToggle}
                onParam={handleParam}
              />
            ))}
          </div>
        </div>

        <div>
          <div className="text-xs font-semibold uppercase mb-1" style={{ color: 'var(--text-muted)' }}>
            Anti-Dilution Tools
          </div>
          <div className="flex flex-col gap-2">
            {ANTIDILUTION_TOOLS.map(t => (
              <ToolCard
                key={t.id}
                tool={t}
                enabled={enabled}
                paramValues={paramValues}
                onToggle={handleToggle}
                onParam={handleParam}
              />
            ))}
          </div>
        </div>

        <ComplianceStrip enabled={enabled} onRun={handleRun} loading={loading} />
      </div>

      {/* Right — Impact Dashboard */}
      <div className="flex-1 flex flex-col gap-4 min-w-0 overflow-y-auto">
        <div className="text-sm font-bold uppercase tracking-widest" style={{ color: 'var(--text-secondary)' }}>
          Impact Dashboard
        </div>

        {error && (
          <div className="rounded border p-3 text-xs" style={{ background: 'var(--bg-surface)', borderColor: 'var(--kpi-red-border, var(--border))', color: 'var(--kpi-red-text)' }}>
            Error: {error}
          </div>
        )}

        {!baseSimResults && !loading && (
          <div className="rounded border p-6 text-center text-xs" style={{ background: 'var(--bg-panel)', borderColor: 'var(--border)', color: 'var(--text-muted)' }}>
            Loading baseline simulation…
          </div>
        )}

        {loading && (
          <div className="rounded border p-3 text-xs text-center" style={{ background: 'var(--bg-panel)', borderColor: 'var(--border)', color: 'var(--text-muted)' }}>
            Running simulation…
          </div>
        )}

        {baseSimResults && (
          <>
            <CoverageTable
              normal={simResults?.normal}
              stress={simResults?.stress}
              baseNormal={baseNormal}
              baseStress={baseStress}
              hasConfigured={!!simResults}
            />
            {simResults && <InvestorCostSummary results={simResults.normal} />}
            {simResults && <RecommendationCard normal={simResults.normal} base={baseNormal} />}
            {!simResults && (
              <div className="rounded border p-3 text-xs text-center" style={{ background: 'var(--bg-panel)', borderColor: 'var(--border)', color: 'var(--text-muted)' }}>
                Configure tools on the left and click <strong>Run Simulation</strong> to compare impact.
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
