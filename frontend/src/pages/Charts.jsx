import {
  BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, CartesianGrid,
  Cell, LineChart, Line,
  PieChart, Pie,
} from 'recharts'
import { useAnalysis } from '../AnalysisContext'
import { useTheme } from '../ThemeContext'
import EmptyState from '../components/EmptyState'
import { BUCKET_COLORS, SERIES_COLORS, CATEGORY_COLORS, stressImpactColor, chartTheme, assetClassColor } from '../theme'

export default function Charts() {
  const { data } = useAnalysis()
  const { theme } = useTheme()
  const ct = chartTheme(theme)
  const liq = data?.liquidity
  const stress = data?.stress
  const wf = data?.waterfall
  if (!liq) return <EmptyState />

  const ladder = liq.liquidity_ladder || []
  const stressLadder = liq.stress_ladder || []
  const positions = liq.position_buckets || []

  const ladderChart = ladder.map((r) => ({
    bucket: r.bucket,
    Normal: +((r.nav_pct || 0) * 100).toFixed(2),
    Stressed: +((stressLadder.find((s) => s.bucket === r.bucket)?.nav_pct || 0) * 100).toFixed(2),
  }))

  // Asset class composition — deterministic color by class name
  const assetMap = {}
  for (const p of positions) {
    const cls = p.asset_class || 'Other'
    assetMap[cls] = (assetMap[cls] || 0) + (p.market_value_eur || 0)
  }
  const total = Object.values(assetMap).reduce((a, b) => a + b, 0)
  const compositionData = Object.entries(assetMap)
    .map(([k, v], i) => ({ name: k, pct: +((v / total) * 100).toFixed(1), color: assetClassColor(k, i) }))
    .sort((a, b) => b.pct - a.pct)

  const ttlData = positions
    .filter((p) => p.days_to_liquidate != null)
    .map((p) => ({ name: p.name, days: +p.days_to_liquidate.toFixed(1), bucket: p.bucket }))
    .sort((a, b) => a.days - b.days)

  const stressChart = (stress?.stress_results || []).map((r) => ({
    name: r.scenario_name?.replace(' Combined', '').replace('Stress ', '') ?? '',
    'NAV Δ%': +((r.nav_impact_pct || 0) * 100).toFixed(2),
    'Liq Before': +((r.liquid_pct_before || 0) * 100).toFixed(1),
    'Liq After': +((r.liquid_pct_after || 0) * 100).toFixed(1),
  }))

  const wfOrders = wf?.waterfall || []
  let cum = 0
  const byDay = {}
  for (const o of wfOrders) byDay[o.day] = (byDay[o.day] || 0) + (o.net_proceeds_eur || 0)
  const cumulChart = Object.entries(byDay).sort((a, b) => +a[0] - +b[0]).map(([day, proceeds]) => {
    cum += proceeds
    return { day: +day, cumulative: +(cum / 1e6).toFixed(2) }
  })

  const axisTick = { fill: ct.tickColor }
  const tooltip = {
    contentStyle: { background: ct.tooltipBg, borderColor: ct.tooltipBorder, color: ct.tooltipText },
    labelStyle: { color: ct.tooltipText },
    itemStyle: { color: ct.tooltipText },
  }
  const grid = <CartesianGrid strokeDasharray="3 3" stroke={ct.gridColor} vertical={false} />
  const xAxis = (key) => <XAxis dataKey={key} tick={{ fontSize: 11, ...axisTick }} axisLine={{ stroke: ct.axisColor }} tickLine={false} />
  const yAxis = (unit) => <YAxis unit={unit} tick={{ fontSize: 11, ...axisTick }} axisLine={false} tickLine={false} />

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>Charts</h1>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* 1. Liquidity Ladder */}
        <ChartCard title="Liquidity Ladder — Normal vs Stressed">
          <BarChart data={ladderChart}>
            {grid}
            {xAxis('bucket')}
            {yAxis('%')}
            <Tooltip formatter={(v) => v.toFixed(1) + '%'} {...tooltip} />
            <Legend />
            <Bar dataKey="Normal" fill={SERIES_COLORS.normal} radius={[4, 4, 0, 0]} />
            <Bar dataKey="Stressed" fill={SERIES_COLORS.stressed} radius={[4, 4, 0, 0]} fillOpacity={0.9} />
          </BarChart>
        </ChartCard>

        {/* 2. Portfolio Composition */}
        <ChartCard title="Portfolio Composition by Asset Class">
          <PieChart>
            <Pie data={compositionData} dataKey="pct" nameKey="name" cx="50%" cy="45%" outerRadius={75}>
              {compositionData.map((d, i) => (
                <Cell key={i} fill={d.color} />
              ))}
            </Pie>
            <Tooltip formatter={(v) => v.toFixed(1) + '%'} {...tooltip} />
            <Legend />
          </PieChart>
        </ChartCard>

        {/* 3. Stress NAV Impact */}
        {stressChart.length > 0 && (
          <ChartCard title="Stress NAV Impact (%)">
            <BarChart data={stressChart}>
              {grid}
              {xAxis('name')}
              {yAxis('%')}
              <Tooltip formatter={(v) => v.toFixed(2) + '%'} {...tooltip} />
              <Bar dataKey="NAV Δ%" radius={[4, 4, 0, 0]}>
                {stressChart.map((d, i) => (
                  <Cell key={i} fill={stressImpactColor(d['NAV Δ%'])} />
                ))}
              </Bar>
            </BarChart>
          </ChartCard>
        )}

        {/* 4. Liquidity Before vs After */}
        {stressChart.length > 0 && (
          <ChartCard title="Liquidity Before vs After — Each Scenario">
            <BarChart data={stressChart}>
              {grid}
              {xAxis('name')}
              {yAxis('%')}
              <Tooltip formatter={(v) => v.toFixed(1) + '%'} {...tooltip} />
              <Legend />
              <Bar dataKey="Liq Before" fill={SERIES_COLORS.normal} radius={[4, 4, 0, 0]} />
              <Bar dataKey="Liq After" fill={SERIES_COLORS.stressed} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ChartCard>
        )}

        {/* 5. Days to Liquidate — full width */}
        {ttlData.length > 0 && (
          <div className="lg:col-span-2 rounded-xl shadow-sm border p-5"
            style={{ background: 'var(--bg-panel)', borderColor: 'var(--border)' }}>
            <h2 className="text-sm font-semibold uppercase tracking-wide mb-4" style={{ color: 'var(--text-secondary)' }}>
              Days to Liquidate — by Position
            </h2>
            <ResponsiveContainer width="100%" height={Math.max(240, ttlData.slice(0, 20).length * 28)}>
              <BarChart data={ttlData.slice(0, 20)} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={ct.gridColor} horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10, fill: ct.tickColor }} axisLine={{ stroke: ct.axisColor }} tickLine={false}
                  label={{ value: 'days', position: 'insideBottomRight', offset: 0, fill: ct.tickColor }} />
                <YAxis type="category" dataKey="name" width={180} tick={{ fontSize: 11, fill: ct.tickColor }} axisLine={false} tickLine={false} />
                <Tooltip formatter={(v) => v + ' days'} {...tooltip} />
                <Bar dataKey="days" radius={[0, 4, 4, 0]}>
                  {ttlData.slice(0, 20).map((d, i) => (
                    <Cell key={i} fill={BUCKET_COLORS[d.bucket] || '#7a8fa8'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* 6. Waterfall Cumulative */}
        {cumulChart.length > 0 && (
          <ChartCard title="Waterfall — Cumulative Proceeds (€M)">
            <LineChart data={cumulChart}>
              {grid}
              <XAxis dataKey="day" tick={{ fontSize: 11, ...axisTick }} axisLine={{ stroke: ct.axisColor }} tickLine={false}
                label={{ value: 'Day', position: 'insideBottom', offset: -2, fill: ct.tickColor }} />
              <YAxis unit="M" tick={{ fontSize: 11, ...axisTick }} axisLine={false} tickLine={false} />
              <Tooltip formatter={(v) => '€' + v + 'M'} {...tooltip} />
              <Line type="monotone" dataKey="cumulative" stroke={SERIES_COLORS.normal} strokeWidth={2} dot={{ r: 3, fill: SERIES_COLORS.normal }} />
            </LineChart>
          </ChartCard>
        )}
      </div>
    </div>
  )
}

function ChartCard({ title, children }) {
  return (
    <div className="rounded-xl shadow-sm border p-5"
      style={{ background: 'var(--bg-panel)', borderColor: 'var(--border)' }}>
      <h2 className="text-sm font-semibold uppercase tracking-wide mb-4" style={{ color: 'var(--text-secondary)' }}>
        {title}
      </h2>
      <ResponsiveContainer width="100%" height={240}>
        {children}
      </ResponsiveContainer>
    </div>
  )
}
