import { useState, useEffect } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, ReferenceLine, CartesianGrid,
} from 'recharts'
import { useTranslation } from 'react-i18next'
import { useAnalysis } from '../AnalysisContext'
import { useTheme } from '../ThemeContext'
import client from '../api/client'
import KPICard from '../components/KPICard'
import EmptyState from '../components/EmptyState'
import StatusBanner from '../components/StatusBanner'
import { chartTheme, stressImpactColor } from '../theme'
import MetricTooltip from '../components/MetricTooltip'
import { pct, eur, mult } from '../utils/formatters'

const panelStyle = { background: 'var(--bg-panel)', borderColor: 'var(--border)' }
const surfaceStyle = { background: 'var(--bg-surface)' }
const headingStyle = { color: 'var(--text-secondary)' }
const rowEven = { background: 'var(--bg-panel)' }
const rowOdd  = { background: 'var(--bg-surface)' }

const inputStyle = {
  background: 'var(--bg-surface)',
  borderColor: 'var(--border)',
  color: 'var(--text-primary)',
}

// The liquidity haircut multiplier is bounded by the severe corner of the
// plausible-shock box (ParameterAxis severe=2.8 in reverse_stress_engine.py).
// Custom scenarios must stay inside the same box, so the form input is capped
// here and clamped on submit — otherwise a manual entry could display a
// haircut above the regulatory plausible bound.
const MIN_HAIRCUT_MULTIPLIER = 1
const MAX_HAIRCUT_MULTIPLIER = 2.8

const clampHaircut = (v) =>
  Math.min(MAX_HAIRCUT_MULTIPLIER, Math.max(MIN_HAIRCUT_MULTIPLIER, v))

// Form defaults mirror the backend CustomScenarioRequest defaults. Percentage
// fields are expressed as whole percent in the UI and converted on submit.
const EMPTY_FORM = {
  name: 'My Custom Scenario',
  equity_shock_pct: -20,
  credit_spread_shock_bps: 150,
  rate_shock_bps: 0,
  liquidity_haircut_multiplier: 2,
  redemption_rate_pct: 10,
  adv_stress_scalar: 1,
}

// Reverse-stress severe-endpoint ("ceiling") defaults, expressed in the same
// friendly units the inputs show. These mirror the engine's calibrated
// DEFAULT_AXES; the user may widen or tighten the searched box per axis. Sent
// to the backend only when changed from the default (see runReverse). Min/max
// match the ReverseStressRequest bounds so the box stays severe-but-plausible.
const REVERSE_CEILING_DEFAULTS = {
  equity_shock_pct: -60,        // equity_shock severe = -0.60
  rate_shock_bps: 400,          // rate_shock_bps severe = 400
  adv_stress_scalar: 0.2,       // adv_stress_scalar severe = 0.20
  liquidity_haircut_multiplier: 2.8,  // severe = 2.8
  redemption_rate_pct: 30,      // redemption_rate severe = 0.30
}
const REVERSE_CEILING_FIELDS = [
  { key: 'equity_shock_pct', labelKey: 'equityShock', min: -90, max: -5, step: 1 },
  { key: 'rate_shock_bps', labelKey: 'rateShock', min: 50, max: 800, step: 10 },
  { key: 'adv_stress_scalar', labelKey: 'advScalar', min: 0.05, max: 0.95, step: 0.05 },
  { key: 'liquidity_haircut_multiplier', labelKey: 'haircutMult', min: 1.1, max: 5, step: 0.1 },
  { key: 'redemption_rate_pct', labelKey: 'redemptionRate', min: 5, max: 60, step: 1 },
]

export default function StressTests() {
  const { t } = useTranslation()
  const { data, error, runId, selectedPortfolio } = useAnalysis()
  const { theme } = useTheme()
  const ct = chartTheme(theme)
  const stress = data?.stress

  const [form, setForm] = useState(EMPTY_FORM)
  const [customResults, setCustomResults] = useState([])
  const [customMeta, setCustomMeta] = useState([])
  const [running, setRunning] = useState(false)
  const [formError, setFormError] = useState(null)

  // Reverse stress is run on demand only (expensive multi-start optimisation),
  // never inside the pipeline. It appends into the same result/param tables.
  const [reverseRunning, setReverseRunning] = useState(false)
  const [reverseError, setReverseError] = useState(null)
  const [reverseInfo, setReverseInfo] = useState(null)
  // User-tunable severe-endpoint ceilings for the reverse-stress search box.
  const [ceilings, setCeilings] = useState(REVERSE_CEILING_DEFAULTS)

  // The reverse-stress banner reflects the last run for the *currently selected*
  // portfolio. Clear it when the user switches portfolios so a stale "robust" /
  // "breach found" message from another portfolio is never shown.
  useEffect(() => {
    setReverseInfo(null)
    setReverseError(null)
    setFormError(null)
    setCeilings(REVERSE_CEILING_DEFAULTS)
  }, [selectedPortfolio])

  if (error) return <StatusBanner />
  if (!stress) return <EmptyState />

  // Custom + reverse results are tagged with the portfolio they were run for so
  // switching the selected portfolio shows only that portfolio's on-demand runs
  // (the pipeline `stress.stress_results` are already scoped to the selection).
  const scopedCustom = customResults.filter(
    (r) => !selectedPortfolio || !r._portfolio || r._portfolio === selectedPortfolio,
  )
  const scopedMeta = customMeta.filter(
    (m) => !selectedPortfolio || !m._portfolio || m._portfolio === selectedPortfolio,
  )
  const results = [...(stress.stress_results || []), ...scopedCustom]
  const meta = [...(stress.scenario_metadata || []), ...scopedMeta]

  const setField = (key) => (e) => {
    const v = e.target.value
    setForm((f) => ({ ...f, [key]: v }))
  }

  const num = (v, fallback = 0) => {
    const n = Number(v)
    return Number.isFinite(n) ? n : fallback
  }

  const runCustom = async () => {
    if (!runId) return
    setRunning(true)
    setFormError(null)
    try {
      const payload = {
        name: (form.name || '').trim() || 'Custom Scenario',
        equity_shock: num(form.equity_shock_pct) / 100,
        credit_spread_shock_bps: Math.round(num(form.credit_spread_shock_bps)),
        rate_shock_bps: Math.round(num(form.rate_shock_bps)),
        liquidity_haircut_multiplier: clampHaircut(num(form.liquidity_haircut_multiplier, 1)),
        redemption_rate: num(form.redemption_rate_pct) / 100,
        adv_stress_scalar: num(form.adv_stress_scalar, 1),
        portfolio: selectedPortfolio,
      }
      const res = await client.post(`/run/${runId}/custom-scenario`, payload)
      setCustomResults((rs) => [...rs, { ...res.data.stress_result, _custom: true, _portfolio: selectedPortfolio }])
      setCustomMeta((ms) => [...ms, { ...res.data.scenario_metadata, _custom: true, _portfolio: selectedPortfolio }])
    } catch (err) {
      // The api client interceptor flattens the server detail into err.message.
      setFormError(err?.message || t('stress.creator.error'))
    } finally {
      setRunning(false)
    }
  }

  const runReverse = async () => {
    if (!runId) return
    setReverseRunning(true)
    setReverseError(null)
    setReverseInfo(null)
    try {
      // Convert the friendly-unit ceilings to the backend's axis units and send
      // every axis explicitly. The user's selected severe endpoint is what defines
      // the search box, so it must always reach the engine — we do NOT gate on
      // "differs from default", because a value equal to the default is still a
      // deliberate choice and any drift between this table and the engine's
      // DEFAULT_AXES would silently drop it. The backend clamps each value to the
      // ReverseStressRequest bounds, so sending the default is a harmless no-op.
      // A blanked field falls back to that axis's default (never 0).
      const c = ceilings
      const val = (key) => num(c[key], REVERSE_CEILING_DEFAULTS[key])
      const ceilingBody = {
        equity_shock_severe: val('equity_shock_pct') / 100,
        rate_shock_bps_severe: Math.round(val('rate_shock_bps')),
        adv_stress_scalar_severe: val('adv_stress_scalar'),
        liquidity_haircut_multiplier_severe: val('liquidity_haircut_multiplier'),
        redemption_rate_severe: val('redemption_rate_pct') / 100,
      }

      const res = await client.post(`/run/${runId}/reverse-stress`, {
        portfolio: selectedPortfolio,
        // The reverse-stress search always runs the pure-Python reference engine.
        // The optional C++ core can converge to a different local optimum on the
        // non-convex breach boundary, so the Python path is the single source of
        // truth exposed to the UI.
        use_native: false,
        ...ceilingBody,
      })
      const rev = res.data?.reverse_result || {}
      if (res.data?.found && res.data?.stress_result) {
        setCustomResults((rs) => [...rs, { ...res.data.stress_result, _reverse: true, _portfolio: selectedPortfolio }])
        setCustomMeta((ms) => [...ms, { ...res.data.scenario_metadata, _reverse: true, _portfolio: selectedPortfolio }])
        setReverseInfo({ found: true, distance: rev.severity_distance })
      } else if (res.data?.frontier) {
        // A breach exists only at the implausible severe corner of the box
        // (haircut at the 2.8 ceiling). The backend suppresses the row; there is
        // no realistic reverse-stress scenario to plan around.
        setReverseInfo({ found: false, frontier: true })
      } else if (rev.breached_at_baseline) {
        // Already in breach with no shock — reverse stress is ill-posed. Surface
        // this distinctly; do NOT show the "robust" banner.
        setReverseInfo({ found: false, baseline: true, liquid: rev.baseline_liquid_pct, target: rev.target_liquid_pct })
      } else {
        // Robust across the plausible box — no breach reachable.
        setReverseInfo({ found: false })
      }
    } catch (err) {
      setReverseError(err?.message || t('stress.reverse.error'))
    } finally {
      setReverseRunning(false)
    }
  }

  const clearCustom = () => {
    // Clear only the on-demand runs for the currently selected portfolio so other
    // portfolios' results are preserved.
    const keep = (r) => selectedPortfolio && r._portfolio && r._portfolio !== selectedPortfolio
    setCustomResults((rs) => rs.filter(keep))
    setCustomMeta((ms) => ms.filter(keep))
    setFormError(null)
    setReverseError(null)
    setReverseInfo(null)
  }

  const worstNav = results.reduce((a, b) => (b.nav_impact_pct < a.nav_impact_pct ? b : a), results[0])
  const worstLiq = results.reduce((a, b) => (b.liquid_pct_after < a.liquid_pct_after ? b : a), results[0])
  const worstDays = results.reduce((a, b) => (b.time_to_liquidate_days > a.time_to_liquidate_days ? b : a), results[0])
  const metCount = results.filter((r) => r.can_meet_redemption).length

  const navDeltaKey = t('charts.legend.navDelta')
  const chartData = results.map((r) => ({
    name: r.scenario_name?.replace(' Combined', '').replace('Stress ', '') ?? r.scenario_name,
    [navDeltaKey]: +((r.nav_impact_pct || 0) * 100).toFixed(2),
  }))

  const resultsCols = [
    [t('stress.columns.scenario'), null],
    [t('stress.columns.navBefore'), null],
    [t('stress.columns.navAfter'), null],
    [t('stress.columns.navImpact'), 'nav_delta_pct'],
    [t('stress.columns.equityLoss'), 'equity_loss'],
    [t('stress.columns.creditLoss'), 'credit_loss'],
    [t('stress.columns.liquidBefore'), 'liq_before'],
    [t('stress.columns.liquidAfter'), 'liq_after'],
    [t('stress.columns.ttl'), 'days_to_liq'],
    [t('stress.columns.canMeet'), 'meets_redemption'],
  ]

  const paramsCols = [
    t('stress.columns.name'),
    t('stress.columns.equityShock'),
    t('stress.columns.spreadShock'),
    t('stress.columns.rateShock'),
    t('stress.columns.advScalar'),
    t('stress.columns.haircutMult'),
    t('stress.columns.redemptionRate'),
    t('stress.columns.regulatoryBasis'),
    t('stress.columns.worstCase'),
  ]

  return (
    <div className="p-3 space-y-3">
      <h1 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>{t('stress.title')}</h1>

      <div className="rounded shadow-sm border p-3 space-y-2" style={panelStyle}>
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide bb-head" style={headingStyle}>
            {t('stress.creator.title')}
          </h2>
          <p className="text-xs mt-0.5" style={{ color: 'var(--text-secondary)' }}>
            {t('stress.creator.subtitle')}
          </p>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-2">
          {[
            ['name', t('stress.creator.name'), 'text', undefined],
            ['equity_shock_pct', t('stress.creator.equityShock'), 'number', '1'],
            ['credit_spread_shock_bps', t('stress.creator.spreadShock'), 'number', '1'],
            ['rate_shock_bps', t('stress.creator.rateShock'), 'number', '1'],
            ['liquidity_haircut_multiplier', t('stress.creator.haircutMult'), 'number', '0.1', MIN_HAIRCUT_MULTIPLIER, MAX_HAIRCUT_MULTIPLIER],
            ['redemption_rate_pct', t('stress.creator.redemptionRate'), 'number', '1'],
            ['adv_stress_scalar', t('stress.creator.advScalar'), 'number', '0.1'],
          ].map(([key, label, type, step, min, max]) => (
            <label key={key} className="flex flex-col gap-1 text-xs" style={{ color: 'var(--text-secondary)' }}>
              <span className="whitespace-nowrap overflow-hidden text-ellipsis">{label}</span>
              <input
                type={type}
                step={step}
                min={min}
                max={max}
                value={form[key]}
                onChange={setField(key)}
                className="rounded border px-2 py-1 text-sm w-full"
                style={inputStyle}
              />
            </label>
          ))}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={runCustom}
            disabled={running || !runId}
            className="rounded px-3 py-1.5 text-sm font-semibold disabled:opacity-50"
            style={{ background: 'var(--text-accent)', color: '#fff' }}
          >
            {running ? t('stress.creator.running') : t('stress.creator.run')}
          </button>
          {scopedCustom.length > 0 && (
            <button
              onClick={clearCustom}
              className="rounded px-3 py-1.5 text-sm font-medium border"
              style={{ borderColor: 'var(--border)', color: 'var(--text-secondary)' }}
            >
              {t('stress.creator.clear')}
            </button>
          )}
          {formError && (
            <span className="text-xs font-medium" style={{ color: '#ff3b3b' }}>{formError}</span>
          )}
        </div>
      </div>

      <div className="rounded shadow-sm border p-3 space-y-2" style={panelStyle}>
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide bb-head" style={headingStyle}>
            {t('stress.reverse.title')}
          </h2>
          <p className="text-xs mt-0.5" style={{ color: 'var(--text-secondary)' }}>
            {t('stress.reverse.subtitle')}
          </p>
        </div>
        <div>
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--text-secondary)' }}>
              {t('stress.reverse.ceilingsTitle')}
            </span>
            <button
              type="button"
              onClick={() => setCeilings(REVERSE_CEILING_DEFAULTS)}
              disabled={reverseRunning}
              className="text-xs underline disabled:opacity-50"
              style={{ color: 'var(--text-accent)' }}
            >
              {t('stress.reverse.ceilingsReset')}
            </button>
          </div>
          <p className="text-xs mt-0.5 mb-1.5" style={{ color: 'var(--text-secondary)' }}>
            {t('stress.reverse.ceilingsHint')}
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
            {REVERSE_CEILING_FIELDS.map(({ key, labelKey, min, max, step }) => (
              <label key={key} className="flex flex-col gap-0.5">
                <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                  {t(`stress.columns.${labelKey}`)}
                </span>
                <input
                  type="number"
                  min={min}
                  max={max}
                  step={step}
                  value={ceilings[key]}
                  disabled={reverseRunning}
                  onChange={(e) => setCeilings((cc) => ({ ...cc, [key]: e.target.value }))}
                  className="rounded border px-2 py-1 text-sm disabled:opacity-50"
                  style={{ background: 'var(--bg-input)', color: 'var(--text-primary)', borderColor: 'var(--border)' }}
                />
              </label>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={runReverse}
            disabled={reverseRunning || !runId}
            className="rounded px-3 py-1.5 text-sm font-semibold disabled:opacity-50"
            style={{ background: 'var(--text-accent)', color: '#fff' }}
          >
            {reverseRunning ? t('stress.reverse.running') : t('stress.reverse.run')}
          </button>
          {reverseInfo?.found && (
            <span className="text-xs font-medium" style={{ color: 'var(--kpi-amber-text)' }}>
              {t('stress.reverse.foundBanner', {
                distance: reverseInfo.distance != null ? reverseInfo.distance.toFixed(3) : '—',
              })}
            </span>
          )}
          {reverseInfo && !reverseInfo.found && reverseInfo.baseline && (
            <span className="text-xs font-medium" style={{ color: '#ff3b3b' }}>
              {t('stress.reverse.baselineBanner', {
                liquid: reverseInfo.liquid != null ? (reverseInfo.liquid * 100).toFixed(1) : '—',
                target: reverseInfo.target != null ? (reverseInfo.target * 100).toFixed(1) : '—',
              })}
            </span>
          )}
          {reverseInfo && !reverseInfo.found && reverseInfo.frontier && (
            <span className="text-xs font-medium" style={{ color: 'var(--kpi-green-text)' }}>
              {t('stress.reverse.noScenarioBanner')}
            </span>
          )}
          {reverseInfo && !reverseInfo.found && !reverseInfo.baseline && !reverseInfo.frontier && (
            <span className="text-xs font-medium" style={{ color: 'var(--kpi-green-text)' }}>
              {t('stress.reverse.robustBanner')}
            </span>
          )}
          {reverseError && (
            <span className="text-xs font-medium" style={{ color: '#ff3b3b' }}>{reverseError}</span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
        <KPICard label={<MetricTooltip id="worst_nav_impact">{t('stress.kpi.worstNavImpact')}</MetricTooltip>} value={pct(worstNav?.nav_impact_pct)} sub={worstNav?.scenario_name} color="red" />
        <KPICard label={<MetricTooltip id="worst_liq_after">{t('stress.kpi.worstLiqAfter')}</MetricTooltip>} value={pct(worstLiq?.liquid_pct_after)} sub={worstLiq?.scenario_name} color="amber" />
        <KPICard label={<MetricTooltip id="max_days_to_liq">{t('stress.kpi.maxDaysToLiq')}</MetricTooltip>} value={worstDays?.time_to_liquidate_days?.toFixed(1) ?? '—'} sub={worstDays?.scenario_name} color="amber" />
        <KPICard label={<MetricTooltip id="redemptions_met">{t('stress.kpi.redemptionsMet')}</MetricTooltip>} value={`${metCount} / ${results.length}`}
          color={metCount === results.length ? 'green' : metCount === 0 ? 'red' : 'amber'} />
      </div>

      <div className="rounded shadow-sm border p-3" style={panelStyle}>
        <h2 className="text-sm font-semibold uppercase tracking-wide bb-head mb-2" style={headingStyle}>
          {t('stress.navImpactChart')}
        </h2>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={chartData} margin={{ top: 4, right: 16, bottom: 4, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={ct.gridColor} vertical={false} />
            <XAxis dataKey="name" tick={{ fontSize: 11, fill: ct.tickColor }} axisLine={{ stroke: ct.axisColor }} tickLine={false} />
            <YAxis unit="%" tick={{ fontSize: 11, fill: ct.tickColor }} axisLine={false} tickLine={false} />
            <Tooltip formatter={(v) => v.toFixed(2) + '%'}
              contentStyle={{ background: ct.tooltipBg, borderColor: ct.tooltipBorder, color: ct.tooltipText }}
              labelStyle={{ color: ct.tooltipText }}
              itemStyle={{ color: ct.tooltipText }} />
            <ReferenceLine y={0} stroke={ct.axisColor} />
            <Bar dataKey={navDeltaKey} radius={[4, 4, 0, 0]}>
              {chartData.map((d, i) => (
                <Cell key={i} fill={stressImpactColor(d[navDeltaKey])} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="rounded shadow-sm border overflow-auto" style={panelStyle}>
        <h2 className="text-sm font-semibold uppercase tracking-wide bb-head p-2 pb-1" style={headingStyle}>
          {t('stress.resultsTable')}
        </h2>
        <table className="w-full text-sm">
          <thead style={surfaceStyle}>
            <tr>
              {resultsCols.map(([h, id]) => (
                <th key={h} className="px-3 py-2 text-left whitespace-nowrap text-xs uppercase"
                  style={{ color: 'var(--text-secondary)' }}>
                  {id ? <MetricTooltip id={id}>{h}</MetricTooltip> : h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {results.map((r, i) => (
              <tr key={i} style={i % 2 === 0 ? rowEven : rowOdd}>
                <td className="px-3 py-2 font-medium">
                  {r.scenario_name}
                  {r._custom && (
                    <span className="ml-2 rounded-full px-2 py-0.5 text-[10px] font-semibold align-middle"
                      style={{ background: 'var(--text-accent)', color: '#fff' }}>
                      {t('stress.creator.customBadge')}
                    </span>
                  )}
                  {r._reverse && (
                    <span className="ml-2 rounded-full px-2 py-0.5 text-[10px] font-semibold align-middle"
                      style={{ background: 'var(--kpi-amber-bg)', color: 'var(--kpi-amber-text)' }}>
                      {t('stress.reverse.badge')}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-right">{eur(r.nav_before)}</td>
                <td className="px-3 py-2 text-right">{eur(r.nav_after_shock)}</td>
                <td className="px-3 py-2 text-right font-semibold"
                  style={{ color: stressImpactColor((r.nav_impact_pct || 0) * 100) }}>
                  {pct(r.nav_impact_pct)}
                </td>
                <td className="px-3 py-2 text-right" style={{ color: '#ff3b3b' }}>{eur(r.equity_loss_eur)}</td>
                <td className="px-3 py-2 text-right" style={{ color: '#ffaa00' }}>{eur(r.credit_loss_eur)}</td>
                <td className="px-3 py-2 text-right">{pct(r.liquid_pct_before)}</td>
                <td className="px-3 py-2 text-right">{pct(r.liquid_pct_after)}</td>
                <td className="px-3 py-2 text-right">{r.time_to_liquidate_days?.toFixed(1) ?? '—'}</td>
                <td className="px-3 py-2 text-center">
                  <span className="rounded-full px-2 py-0.5 text-xs font-semibold"
                    style={r.can_meet_redemption
                      ? { background: 'var(--kpi-green-bg)', color: 'var(--kpi-green-text)' }
                      : { background: 'var(--kpi-red-bg)', color: 'var(--kpi-red-text)' }}>
                    {r.can_meet_redemption ? t('stress.yes') : t('stress.no')}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="rounded shadow-sm border overflow-auto" style={panelStyle}>
        <h2 className="text-sm font-semibold uppercase tracking-wide bb-head p-2 pb-1" style={headingStyle}>
          {t('stress.paramsTable')}
        </h2>
        <table className="w-full text-sm">
          <thead style={surfaceStyle}>
            <tr>
              {paramsCols.map((h) => (
                <th key={h} className="px-3 py-2 text-left whitespace-nowrap text-xs uppercase"
                  style={{ color: 'var(--text-secondary)' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {meta.map((sc, i) => (
              <tr key={i} style={i % 2 === 0 ? rowEven : rowOdd}>
                <td className="px-3 py-2 font-medium">
                  {sc.name}
                  {sc._custom && (
                    <span className="ml-2 rounded-full px-2 py-0.5 text-[10px] font-semibold align-middle"
                      style={{ background: 'var(--text-accent)', color: '#fff' }}>
                      {t('stress.creator.customBadge')}
                    </span>
                  )}
                  {sc._reverse && (
                    <span className="ml-2 rounded-full px-2 py-0.5 text-[10px] font-semibold align-middle"
                      style={{ background: 'var(--kpi-amber-bg)', color: 'var(--kpi-amber-text)' }}>
                      {t('stress.reverse.badge')}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-right">{pct(sc.equity_shock)}</td>
                <td className="px-3 py-2 text-right">{sc.credit_spread_shock_bps}</td>
                <td className="px-3 py-2 text-right">{sc.rate_shock_bps}</td>
                <td className="px-3 py-2 text-right">{mult(sc.adv_stress_scalar)}</td>
                <td className="px-3 py-2 text-right">{mult(sc.liquidity_haircut_multiplier)}</td>
                <td className="px-3 py-2 text-right">{pct(sc.redemption_rate)}</td>
                <td className="px-3 py-2 text-xs">{sc.regulatory_basis || '—'}</td>
                <td className="px-3 py-2 text-center">
                  {sc.is_worst_case ? <span style={{ color: '#ff3b3b' }} className="font-bold">★</span> : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
