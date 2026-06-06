import { useState } from 'react'
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
import { pct, eur } from '../utils/formatters'

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

  if (error) return <StatusBanner />
  if (!stress) return <EmptyState />

  const results = [...(stress.stress_results || []), ...customResults]
  const meta = [...(stress.scenario_metadata || []), ...customMeta]

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
        liquidity_haircut_multiplier: num(form.liquidity_haircut_multiplier, 1),
        redemption_rate: num(form.redemption_rate_pct) / 100,
        adv_stress_scalar: num(form.adv_stress_scalar, 1),
        portfolio: selectedPortfolio,
      }
      const res = await client.post(`/run/${runId}/custom-scenario`, payload)
      setCustomResults((rs) => [...rs, { ...res.data.stress_result, _custom: true }])
      setCustomMeta((ms) => [...ms, { ...res.data.scenario_metadata, _custom: true }])
    } catch (err) {
      // The api client interceptor flattens the server detail into err.message.
      setFormError(err?.message || t('stress.creator.error'))
    } finally {
      setRunning(false)
    }
  }

  const clearCustom = () => {
    setCustomResults([])
    setCustomMeta([])
    setFormError(null)
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
            ['liquidity_haircut_multiplier', t('stress.creator.haircutMult'), 'number', '0.1'],
            ['redemption_rate_pct', t('stress.creator.redemptionRate'), 'number', '1'],
            ['adv_stress_scalar', t('stress.creator.advScalar'), 'number', '0.1'],
          ].map(([key, label, type, step]) => (
            <label key={key} className="flex flex-col gap-1 text-xs" style={{ color: 'var(--text-secondary)' }}>
              <span className="whitespace-nowrap overflow-hidden text-ellipsis">{label}</span>
              <input
                type={type}
                step={step}
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
            style={{ background: 'var(--accent)', color: '#fff' }}
          >
            {running ? t('stress.creator.running') : t('stress.creator.run')}
          </button>
          {customResults.length > 0 && (
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
                      style={{ background: 'var(--accent)', color: '#fff' }}>
                      {t('stress.creator.customBadge')}
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
                      style={{ background: 'var(--accent)', color: '#fff' }}>
                      {t('stress.creator.customBadge')}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-right">{pct(sc.equity_shock)}</td>
                <td className="px-3 py-2 text-right">{sc.credit_spread_shock_bps}</td>
                <td className="px-3 py-2 text-right">{sc.rate_shock_bps}</td>
                <td className="px-3 py-2 text-right">{sc.adv_stress_scalar}×</td>
                <td className="px-3 py-2 text-right">{sc.liquidity_haircut_multiplier}×</td>
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
