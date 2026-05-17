import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, ReferenceLine, CartesianGrid,
} from 'recharts'
import { useAnalysis } from '../AnalysisContext'
import { useTheme } from '../ThemeContext'
import KPICard from '../components/KPICard'
import EmptyState from '../components/EmptyState'
import { chartTheme, stressImpactColor } from '../theme'
import MetricTooltip from '../components/MetricTooltip'

function pct(v) { return v != null ? (v * 100).toFixed(1) + '%' : '—' }
function eur(v) {
  if (v == null) return '—'
  if (Math.abs(v) >= 1e6) return '€' + (v / 1e6).toFixed(1) + 'M'
  return '€' + v.toFixed(0)
}

const panelStyle = { background: 'var(--bg-panel)', borderColor: 'var(--border)' }
const surfaceStyle = { background: 'var(--bg-surface)' }
const headingStyle = { color: 'var(--text-secondary)' }
const rowEven = { background: 'var(--bg-panel)' }
const rowOdd  = { background: 'var(--bg-surface)' }

export default function StressTests() {
  const { data } = useAnalysis()
  const { theme } = useTheme()
  const ct = chartTheme(theme)
  const stress = data?.stress
  if (!stress) return <EmptyState />

  const results = stress.stress_results || []
  const meta = stress.scenario_metadata || []

  const worstNav = results.reduce((a, b) => (b.nav_impact_pct < a.nav_impact_pct ? b : a), results[0])
  const worstLiq = results.reduce((a, b) => (b.liquid_pct_after < a.liquid_pct_after ? b : a), results[0])
  const worstDays = results.reduce((a, b) => (b.time_to_liquidate_days > a.time_to_liquidate_days ? b : a), results[0])
  const metCount = results.filter((r) => r.can_meet_redemption).length

  const chartData = results.map((r) => ({
    name: r.scenario_name?.replace(' Combined', '').replace('Stress ', '') ?? r.scenario_name,
    'NAV Δ%': +((r.nav_impact_pct || 0) * 100).toFixed(2),
  }))

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>Stress Tests</h1>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard label={<MetricTooltip id="worst_nav_impact">Worst NAV Impact</MetricTooltip>} value={pct(worstNav?.nav_impact_pct)} sub={worstNav?.scenario_name} color="red" />
        <KPICard label={<MetricTooltip id="worst_liq_after">Worst Liquidity After</MetricTooltip>} value={pct(worstLiq?.liquid_pct_after)} sub={worstLiq?.scenario_name} color="amber" />
        <KPICard label={<MetricTooltip id="max_days_to_liq">Max Days to Liquidate</MetricTooltip>} value={worstDays?.time_to_liquidate_days?.toFixed(1) ?? '—'} sub={worstDays?.scenario_name} color="amber" />
        <KPICard label={<MetricTooltip id="redemptions_met">Redemptions Met</MetricTooltip>} value={`${metCount} / ${results.length}`}
          color={metCount === results.length ? 'green' : metCount === 0 ? 'red' : 'amber'} />
      </div>

      <div className="rounded-xl shadow-sm border p-5" style={panelStyle}>
        <h2 className="text-sm font-semibold uppercase tracking-wide mb-4" style={headingStyle}>
          NAV Impact by Scenario
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
            <Bar dataKey="NAV Δ%" radius={[4, 4, 0, 0]}>
              {chartData.map((d, i) => (
                <Cell key={i} fill={stressImpactColor(d['NAV Δ%'])} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="rounded-xl shadow-sm border overflow-auto" style={panelStyle}>
        <h2 className="text-sm font-semibold uppercase tracking-wide p-4 pb-2" style={headingStyle}>
          Scenario Results
        </h2>
        <table className="w-full text-sm">
          <thead style={surfaceStyle}>
            <tr>
              {[
                ['Scenario', null], ['NAV Before', null], ['NAV After', null],
                ['NAV Δ%', 'nav_delta_pct'], ['Equity Loss', 'equity_loss'],
                ['Credit Loss', 'credit_loss'], ['Liq Before', 'liq_before'],
                ['Liq After', 'liq_after'], ['Days to Liq.', 'days_to_liq'],
                ['Meets Redemption', 'meets_redemption'],
              ].map(([h, id]) => (
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
                <td className="px-3 py-2 font-medium">{r.scenario_name}</td>
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
                    {r.can_meet_redemption ? 'Yes' : 'No'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="rounded-xl shadow-sm border overflow-auto" style={panelStyle}>
        <h2 className="text-sm font-semibold uppercase tracking-wide p-4 pb-2" style={headingStyle}>
          Scenario Parameters
        </h2>
        <table className="w-full text-sm">
          <thead style={surfaceStyle}>
            <tr>
              {['Name', 'Equity Shock', 'Credit Δbps', 'Rate Δbps', 'ADV Scalar', 'Haircut Mult.', 'Redemption %', 'Regulatory Basis', 'Worst-Case'].map((h) => (
                <th key={h} className="px-3 py-2 text-left whitespace-nowrap text-xs uppercase"
                  style={{ color: 'var(--text-secondary)' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {meta.map((sc, i) => (
              <tr key={i} style={i % 2 === 0 ? rowEven : rowOdd}>
                <td className="px-3 py-2 font-medium">{sc.name}</td>
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
