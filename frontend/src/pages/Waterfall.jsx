import { useState, useCallback } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { useTranslation } from 'react-i18next'
import { useAnalysis } from '../AnalysisContext'
import { useTheme } from '../ThemeContext'
import client from '../api/client'
import KPICard from '../components/KPICard'
import EmptyState from '../components/EmptyState'
import { BUCKET_COLORS, bucketBadgeStyle, chartTheme } from '../theme'
import MetricTooltip from '../components/MetricTooltip'

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

export default function Waterfall() {
  const { t } = useTranslation()
  const { data, runId, selectedPortfolio } = useAnalysis()
  const { theme } = useTheme()
  const ct = chartTheme(theme)

  // LP optimiser state: when set, the LP-optimised schedule replaces the
  // pipeline's greedy schedule in every panel below.
  const [lpResult, setLpResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [lpError, setLpError] = useState(null)

  const wf = data?.waterfall

  const handleOptimise = useCallback(async () => {
    if (!runId) return
    setLoading(true)
    setLpError(null)
    try {
      const res = await client.post(`/run/${runId}/waterfall-optimise`, {
        portfolio: selectedPortfolio || undefined,
      })
      setLpResult(res.data)
    } catch (e) {
      setLpError(e?.response?.data?.detail || e.message || t('waterfall.lpError'))
    } finally {
      setLoading(false)
    }
  }, [runId, selectedPortfolio, t])

  const handleShowGreedy = useCallback(() => {
    setLpResult(null)
    setLpError(null)
  }, [])

  if (!wf) return <EmptyState />

  const active = lpResult || wf
  const isLp = !!lpResult
  const meta = active.waterfall_meta || {}
  const orders = active.waterfall || []

  const buckets = [...new Set(orders.map((o) => o.bucket))].filter(Boolean)
  const dayMap = {}
  for (const o of orders) {
    if (!dayMap[o.day]) dayMap[o.day] = { day: o.day }
    dayMap[o.day][o.bucket] = (dayMap[o.day][o.bucket] || 0) + (o.net_proceeds_eur || 0)
  }
  const chartData = Object.values(dayMap).sort((a, b) => a.day - b.day)

  const cols = [
    t('waterfall.columns.day'),
    'ISIN',
    t('waterfall.columns.name'),
    t('waterfall.columns.assetClass'),
    t('waterfall.columns.bucket'),
    t('waterfall.columns.grossValue'),
    t('waterfall.columns.marketImpact'),
    t('waterfall.columns.netProceeds'),
    t('waterfall.columns.partial'),
  ]

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>{t('waterfall.title')}</h1>

        {!isLp ? (
          <button
            onClick={handleOptimise}
            disabled={loading || !runId}
            className="rounded border px-3 py-1.5 text-xs font-semibold transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ background: 'var(--text-accent)', color: '#fff', borderColor: 'var(--text-accent)' }}
          >
            {loading ? t('waterfall.optimising') : t('waterfall.activateLp')}
          </button>
        ) : (
          <button
            onClick={handleShowGreedy}
            className="rounded border px-3 py-1.5 text-xs font-semibold transition-colors cursor-pointer"
            style={{ background: 'var(--bg-panel)', color: 'var(--text-secondary)', borderColor: 'var(--border)' }}
          >
            {t('waterfall.showGreedy')}
          </button>
        )}

        <span className="rounded px-2 py-0.5 text-xs font-semibold"
          style={isLp
            ? { background: 'var(--kpi-green-bg, #dcfce7)', color: 'var(--kpi-green-text, #166534)' }
            : { background: 'var(--bg-surface)', color: 'var(--text-secondary)' }
          }>
          {isLp ? t('waterfall.lpActive') : t('waterfall.greedyActive')}
        </span>

        {lpError && (
          <span className="text-xs font-semibold" style={{ color: '#ff3b3b' }}>{lpError}</span>
        )}
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard label={<MetricTooltip id="wf_target">{t('waterfall.kpi.target')}</MetricTooltip>} value={eur(meta.target_eur)} color="slate" />
        <KPICard label={<MetricTooltip id="wf_total_proceeds">{t('waterfall.kpi.totalProceeds')}</MetricTooltip>} value={eur(meta.total_proceeds_eur)} color={meta.target_met ? 'green' : 'red'} />
        <KPICard label={<MetricTooltip id="wf_days_to_target">{t('waterfall.kpi.daysToTarget')}</MetricTooltip>} value={meta.days_to_target?.toFixed(1) ?? '—'} color="slate" />
        <KPICard
          label={<MetricTooltip id="wf_residual_shortfall">{t('waterfall.kpi.residualShortfall')}</MetricTooltip>}
          value={eur(meta.residual_shortfall_eur)}
          color={meta.residual_shortfall_eur > 0 ? 'red' : 'green'}
        />
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
        <KPICard label={<MetricTooltip id="wf_nav_before">{t('waterfall.kpi.navBefore')}</MetricTooltip>} value={eur(meta.nav_before)} color="slate" />
        <KPICard label={<MetricTooltip id="wf_nav_after">{t('waterfall.kpi.navAfter')}</MetricTooltip>} value={eur(meta.nav_after)} color="slate" />
        <KPICard
          label={<MetricTooltip id="wf_nav_impact">{t('waterfall.kpi.navImpact')}</MetricTooltip>}
          value={meta.nav_impact_pct != null ? (meta.nav_impact_pct * 100).toFixed(2) + '%' : '—'}
          color={Math.abs(meta.nav_impact_pct || 0) > 0.05 ? 'red' : 'slate'}
        />
      </div>

      {chartData.length > 0 && (
        <div className="rounded-xl shadow-sm border p-5" style={panelStyle}>
          <h2 className="text-sm font-semibold uppercase tracking-wide mb-4" style={headingStyle}>
            {t('waterfall.dailyProceedsChart')}
          </h2>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={chartData} margin={{ top: 4, right: 16, bottom: 4, left: 0 }}
              barSize={Math.max(20, Math.min(60, 400 / chartData.length))}>
              <CartesianGrid strokeDasharray="3 3" stroke={ct.gridColor} vertical={false} />
              <XAxis dataKey="day" label={{ value: t('waterfall.columns.day'), position: 'insideBottom', offset: -2, fill: ct.tickColor }}
                tick={{ fontSize: 11, fill: ct.tickColor }} axisLine={{ stroke: ct.axisColor }} tickLine={false} />
              <YAxis tickFormatter={(v) => '€' + (v / 1e6).toFixed(1) + 'M'}
                tick={{ fontSize: 11, fill: ct.tickColor }} axisLine={false} tickLine={false} />
              <Tooltip formatter={(v) => eur(v)}
                contentStyle={{ background: ct.tooltipBg, borderColor: ct.tooltipBorder, color: ct.tooltipText }}
                labelStyle={{ color: ct.tooltipText }}
                itemStyle={{ color: ct.tooltipText }} />
              <Legend />
              {buckets.map((b) => (
                <Bar key={b} dataKey={b} stackId="a" fill={BUCKET_COLORS[b] || '#94a3b8'}
                  radius={b === buckets[buckets.length - 1] ? [4, 4, 0, 0] : [0, 0, 0, 0]} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="rounded-xl shadow-sm border overflow-auto" style={panelStyle}>
        <h2 className="text-sm font-semibold uppercase tracking-wide p-4 pb-2" style={headingStyle}>
          {t('waterfall.sellOrders')}
        </h2>
        <table className="w-full text-sm">
          <thead style={surfaceStyle}>
            <tr>
              {cols.map((h) => (
                <th key={h} className="px-3 py-2 text-left whitespace-nowrap text-xs uppercase"
                  style={{ color: 'var(--text-secondary)' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {orders.map((o, i) => (
              <tr key={i} style={i % 2 === 0 ? rowEven : rowOdd}>
                <td className="px-3 py-1.5 font-semibold text-center">{o.day}</td>
                <td className="px-3 py-1.5 font-mono text-xs">{o.isin}</td>
                <td className="px-3 py-1.5 max-w-[160px] truncate">{o.name}</td>
                <td className="px-3 py-1.5">{o.asset_class}</td>
                <td className="px-3 py-1.5">
                  <span className="rounded-full px-2 py-0.5 text-xs font-semibold" style={bucketBadgeStyle(o.bucket)}>{o.bucket}</span>
                </td>
                <td className="px-3 py-1.5 text-right">{eur(o.gross_value_eur)}</td>
                <td className="px-3 py-1.5 text-right" style={{ color: '#ff3b3b' }}>{eur(o.market_impact_eur)}</td>
                <td className="px-3 py-1.5 text-right font-semibold">{eur(o.net_proceeds_eur)}</td>
                <td className="px-3 py-1.5 text-center">
                  {o.is_partial ? <span style={{ color: '#ffaa00' }} className="font-semibold">{t('waterfall.partialBadge')}</span> : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
