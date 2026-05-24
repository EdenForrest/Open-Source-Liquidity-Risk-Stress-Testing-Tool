import {
  BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { useAnalysis } from '../AnalysisContext'
import { useTheme } from '../ThemeContext'
import KPICard from '../components/KPICard'
import EmptyState from '../components/EmptyState'
import StatusBanner from '../components/StatusBanner'
import { SERIES_COLORS, bucketBadgeStyle, chartTheme } from '../theme'
import MetricTooltip from '../components/MetricTooltip'
import { fmt, fmtEur } from '../utils/formatters'

export default function Dashboard() {
  const { data, error, runId, selectedPortfolio } = useAnalysis()
  const { theme } = useTheme()
  const ct = chartTheme(theme)
  const liq = data?.liquidity
  if (error) return <StatusBanner />
  if (!liq) return <EmptyState />

  const m = liq.liquidity_metrics
  const aifmd2 = data?.aifmd2

  const ladderData = (liq.liquidity_ladder || []).map((row) => ({
    bucket: row.bucket,
    Normal: +(row.nav_pct * 100).toFixed(2),
    Stressed: +((liq.stress_ladder?.find((s) => s.bucket === row.bucket)?.nav_pct || 0) * 100).toFixed(2),
  }))

  const panelStyle = { background: 'var(--bg-panel)', borderColor: 'var(--border)' }
  const surfaceStyle = { background: 'var(--bg-surface)' }
  const rowEven = { background: 'var(--bg-panel)' }
  const rowOdd  = { background: 'var(--bg-surface)' }

  function handleExcel() {
    if (!runId) return
    const code = selectedPortfolio || ''
    const base = (import.meta.env.VITE_API_BASE_URL ?? '/api').replace(/\/+$/, '')
    const url = `${base}/run/${runId}/export/excel${code ? `?portfolio=${encodeURIComponent(code)}` : ''}`
    const a = document.createElement('a')
    a.href = url
    a.download = `liquidity_report_${code || 'portfolio'}.xlsx`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }

  return (
    <div className="p-3 space-y-3">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>
          {liq.fund_name} — {liq.reporting_date}
        </h1>
        <button
          onClick={handleExcel}
          className="flex items-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium"
          style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', color: 'var(--text-primary)', cursor: 'pointer' }}
          title="Export full report as Excel (.xlsx)"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
          Export Excel
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-2">
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
        <KPICard
          label="Geo Status"
          value={m.geo_breach_flag ? 'BREACH' : m.geo_warning_flag ? 'WARNING' : 'OK'}
          color={m.geo_breach_flag ? 'red' : m.geo_warning_flag ? 'amber' : 'green'}
          alert={m.geo_breach_flag}
        />
      </div>

      <div className="rounded shadow-sm border p-3" style={panelStyle}>
        <h2 className="text-sm font-semibold uppercase tracking-wide mb-2 bb-head" style={{ color: 'var(--text-secondary)' }}>
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

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <KPICard label={<MetricTooltip id="days_to_50pct">Days to 50% NAV</MetricTooltip>} value={m.days_to_50pct?.toFixed(1) ?? '—'} color="slate" />
        <KPICard label={<MetricTooltip id="days_to_75pct">Days to 75% NAV</MetricTooltip>} value={m.days_to_75pct?.toFixed(1) ?? '—'} color="slate" />
        <KPICard label={<MetricTooltip id="days_to_90pct">Days to 90% NAV</MetricTooltip>} value={m.days_to_90pct?.toFixed(1) ?? '—'} color="slate" />
        <KPICard label={<MetricTooltip id="top10_concentration">Top-10 Concentration</MetricTooltip>} value={fmt(m.top10_concentration)} color="slate" />
      </div>

      {aifmd2 && aifmd2.gross_leverage != null ? (
        <div className="rounded shadow-sm border overflow-auto" style={panelStyle}>
          <h2 className="text-sm font-semibold uppercase tracking-wide bb-head px-3 py-2" style={{ ...surfaceStyle, color: 'var(--text-secondary)' }}>
            AIFMD II — Directive (EU) 2024/927
          </h2>
          <table className="w-full">
            <tbody>
              <tr>
                <td className="px-3 py-1.5 text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>Status</td>
                <td className="px-3 py-1.5 text-sm font-semibold text-right">
                  {aifmd2.leverage_breach
                    ? <span style={{ color: 'var(--kpi-red-text)' }}>BREACH</span>
                    : !aifmd2.lmt_compliant
                    ? <span style={{ color: 'var(--kpi-amber-text)' }}>INCOMPLETE</span>
                    : <span style={{ color: 'var(--kpi-green-text)' }}>OK</span>}
                </td>
              </tr>
              <tr>
                <td className="px-3 py-1.5 text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>
                  <MetricTooltip id="gross_leverage">Gross Leverage (Art. 7 CDR 231/2013)</MetricTooltip>
                </td>
                <td className="px-3 py-1.5 text-sm font-semibold text-right"
                  style={{ color: aifmd2.leverage_breach ? 'var(--kpi-red-text)' : 'var(--text-primary)' }}>
                  {(aifmd2.gross_leverage * 100).toFixed(1)}%
                  {aifmd2.leverage_cap != null && <span className="ml-2 text-xs font-normal opacity-60">cap {(aifmd2.leverage_cap * 100).toFixed(0)}%</span>}
                </td>
              </tr>
              <tr>
                <td className="px-3 py-1.5 text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>
                  <MetricTooltip id="commitment_leverage">Commitment Leverage</MetricTooltip>
                </td>
                <td className="px-3 py-1.5 text-sm font-semibold text-right" style={{ color: 'var(--text-primary)' }}>
                  {aifmd2.commitment_leverage != null ? (aifmd2.commitment_leverage * 100).toFixed(1) + '%' : '—'}
                </td>
              </tr>
              <tr>
                <td className="px-3 py-1.5 text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>
                  <MetricTooltip id="lmt_count">LMTs Pre-selected</MetricTooltip>
                </td>
                <td className="px-3 py-1.5 text-sm font-semibold text-right"
                  style={{ color: aifmd2.lmt_compliant ? 'var(--kpi-green-text)' : 'var(--kpi-red-text)' }}>
                  {aifmd2.lmt_count ?? '—'}
                  <span className="ml-2 text-xs font-normal opacity-60">{aifmd2.lmt_compliant ? 'compliant' : 'insufficient'}</span>
                </td>
              </tr>
              {aifmd2.warnings && (
                <tr style={{ background: 'var(--kpi-amber-bg)' }}>
                  <td colSpan={2} className="px-3 py-1.5 text-xs" style={{ color: 'var(--kpi-amber-text)' }}>
                    ⚠ {aifmd2.warnings}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="rounded border p-3 flex items-center gap-3"
          style={{ background: 'var(--kpi-amber-bg)', borderColor: 'var(--kpi-amber-border)' }}>
          <span style={{ color: 'var(--kpi-amber-text)' }}>⚠</span>
          <p className="text-sm" style={{ color: 'var(--kpi-amber-text)' }}>
            AIFMD II leverage data is not available for this portfolio. Upload a holdings file with leveraged positions or derivative exposures to enable this section.
          </p>
        </div>
      )}

      <div className="rounded shadow-sm border overflow-auto" style={panelStyle}>
        <h2 className="text-sm font-semibold uppercase tracking-wide bb-head p-2 pb-1" style={{ color: 'var(--text-secondary)' }}>
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
