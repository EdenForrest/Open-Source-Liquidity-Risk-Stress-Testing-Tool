import {
  BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { useAnalysis } from '../AnalysisContext'
import { useTheme } from '../ThemeContext'
import KPICard from '../components/KPICard'
import EmptyState from '../components/EmptyState'
import { SERIES_COLORS, bucketBadgeStyle, chartTheme } from '../theme'
import MetricTooltip from '../components/MetricTooltip'

function fmt(n, digits = 1) {
  if (n == null) return '—'
  return (n * 100).toFixed(digits) + '%'
}
function fmtEur(n) {
  if (n == null) return '—'
  if (n >= 1e9) return '€' + (n / 1e9).toFixed(2) + 'B'
  if (n >= 1e6) return '€' + (n / 1e6).toFixed(1) + 'M'
  return '€' + n.toFixed(0)
}

export default function Dashboard() {
  const { data } = useAnalysis()
  const { theme } = useTheme()
  const ct = chartTheme(theme)
  const liq = data?.liquidity
  if (!liq) return <EmptyState />

  const m = liq.liquidity_metrics

  const ladderData = (liq.liquidity_ladder || []).map((row) => ({
    bucket: row.bucket,
    Normal: +(row.nav_pct * 100).toFixed(2),
    Stressed: +((liq.stress_ladder?.find((s) => s.bucket === row.bucket)?.nav_pct || 0) * 100).toFixed(2),
  }))

  const panelStyle = { background: 'var(--bg-panel)', borderColor: 'var(--border)' }
  const surfaceStyle = { background: 'var(--bg-surface)' }
  const rowEven = { background: 'var(--bg-panel)' }
  const rowOdd  = { background: 'var(--bg-surface)' }

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>
        {liq.fund_name} — {liq.reporting_date}
      </h1>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <KPICard label={<MetricTooltip id="lcr_t1">LCR T+1</MetricTooltip>} value={fmt(m.lcr_t1)} color="blue" />
        <KPICard label={<MetricTooltip id="lcr_t3">LCR T+3</MetricTooltip>} value={fmt(m.lcr_t3)} color="blue" />
        <KPICard label={<MetricTooltip id="lcr_t7">LCR T+7</MetricTooltip>} value={fmt(m.lcr_t7)} color="blue" />
        <KPICard label={<MetricTooltip id="illiquid_pct">Illiquid</MetricTooltip>} value={fmt(m.illiquid_pct)} color={m.illiquid_pct > 0.2 ? 'red' : 'slate'} />
        <KPICard label={<MetricTooltip id="total_nav">Total NAV</MetricTooltip>} value={fmtEur(liq.total_nav_eur)} color="slate" />
        <KPICard
          label={<MetricTooltip id="status">Status</MetricTooltip>}
          value={m.breach_flag ? 'BREACH' : m.warning_flag ? 'WARNING' : 'OK'}
          color={m.breach_flag ? 'red' : m.warning_flag ? 'amber' : 'green'}
          alert={m.breach_flag}
        />
      </div>

      <div className="rounded-xl shadow-sm border p-5" style={panelStyle}>
        <h2 className="text-sm font-semibold uppercase tracking-wide mb-4" style={{ color: 'var(--text-secondary)' }}>
          Liquidity Ladder — Normal vs Stressed (% NAV)
        </h2>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={ladderData} margin={{ top: 4, right: 16, bottom: 4, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={ct.gridColor} vertical={false} />
            <XAxis dataKey="bucket" tick={{ fontSize: 12, fill: ct.tickColor }} axisLine={{ stroke: ct.axisColor }} tickLine={false} />
            <YAxis unit="%" tick={{ fontSize: 11, fill: ct.tickColor }} axisLine={false} tickLine={false} />
            <Tooltip
              formatter={(v) => v.toFixed(1) + '%'}
              contentStyle={{ background: ct.tooltipBg, borderColor: ct.tooltipBorder, color: ct.tooltipText }}
              labelStyle={{ color: ct.tooltipText }}
              itemStyle={{ color: ct.tooltipText }}
            />
            <Legend />
            <Bar dataKey="Normal" fill={SERIES_COLORS.normal} radius={[4, 4, 0, 0]} />
            <Bar dataKey="Stressed" fill={SERIES_COLORS.stressed} radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KPICard label={<MetricTooltip id="days_to_50pct">Days to 50% NAV</MetricTooltip>} value={m.days_to_50pct?.toFixed(1) ?? '—'} color="slate" />
        <KPICard label={<MetricTooltip id="days_to_75pct">Days to 75% NAV</MetricTooltip>} value={m.days_to_75pct?.toFixed(1) ?? '—'} color="slate" />
        <KPICard label={<MetricTooltip id="days_to_90pct">Days to 90% NAV</MetricTooltip>} value={m.days_to_90pct?.toFixed(1) ?? '—'} color="slate" />
        <KPICard label={<MetricTooltip id="top10_concentration">Top-10 Concentration</MetricTooltip>} value={fmt(m.top10_concentration)} color="slate" />
      </div>

      <div className="rounded-xl shadow-sm border overflow-auto" style={panelStyle}>
        <h2 className="text-sm font-semibold uppercase tracking-wide p-4 pb-2" style={{ color: 'var(--text-secondary)' }}>
          Positions
        </h2>
        <table className="w-full text-sm">
          <thead style={surfaceStyle}>
            <tr>
              {[
                ['ISIN', null], ['Name', null], ['Asset Class', null],
                ['Market Value (€)', null], ['Weight', null],
                ['Bucket', 'bucket'], ['Haircut', 'haircut'],
                ['Realisable (€)', 'realisable_value'], ['Days to Liq.', 'pos_days_to_liq'],
              ].map(([h, id]) => (
                <th key={h} className="px-3 py-2 text-left whitespace-nowrap text-xs uppercase"
                  style={{ color: 'var(--text-secondary)' }}>
                  {id ? <MetricTooltip id={id}>{h}</MetricTooltip> : h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(liq.position_buckets || []).map((pos, i) => (
              <tr key={i} style={i % 2 === 0 ? rowEven : rowOdd}>
                <td className="px-3 py-1.5 font-mono text-xs">{pos.isin}</td>
                <td className="px-3 py-1.5 max-w-[180px] truncate">{pos.name}</td>
                <td className="px-3 py-1.5">{pos.asset_class}</td>
                <td className="px-3 py-1.5 text-right">{fmtEur(pos.market_value_eur)}</td>
                <td className="px-3 py-1.5 text-right">{fmt(pos.weight)}</td>
                <td className="px-3 py-1.5">
                  <span className="rounded-full px-2 py-0.5 text-xs font-semibold" style={bucketBadgeStyle(pos.bucket)}>{pos.bucket}</span>
                </td>
                <td className="px-3 py-1.5 text-right">{pos.haircut != null ? (pos.haircut * 100).toFixed(1) + '%' : '—'}</td>
                <td className="px-3 py-1.5 text-right">{fmtEur(pos.realisable_value)}</td>
                <td className="px-3 py-1.5 text-right">{pos.days_to_liquidate?.toFixed(1) ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
