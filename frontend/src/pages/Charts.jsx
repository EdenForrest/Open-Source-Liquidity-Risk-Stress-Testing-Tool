import { useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, CartesianGrid,
  Cell, LineChart, Line,
  PieChart, Pie,
} from 'recharts'
import { ComposableMap, Geographies, Geography, ZoomableGroup } from 'react-simple-maps'
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

// ---------------------------------------------------------------------------
// Geo concentration chart components
// ---------------------------------------------------------------------------

const GEO_URL = 'https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json'

const EU_ALPHA2 = new Set(['DE','FR','NL','BE','AT','ES','IT','FI','IE','LU','SE','DK'])

const NUMERIC_TO_ALPHA2 = {
  '276':'DE','250':'FR','528':'NL','56':'BE','40':'AT','724':'ES',
  '380':'IT','246':'FI','372':'IE','442':'LU','752':'SE','208':'DK',
  '840':'US','826':'GB','392':'JP','756':'CH','36':'AU','156':'CN',
  '124':'CA','76':'BR','356':'IN','410':'KR','702':'SG','578':'NO',
  '620':'PT','300':'GR','616':'PL','203':'CZ','348':'HU','642':'RO',
  '703':'SK','705':'SI','100':'BG','191':'HR','440':'LT','428':'LV',
  '233':'EE','196':'CY','470':'MT','352':'IS','438':'LI','792':'TR',
  '710':'ZA','484':'MX','32':'AR','152':'CL','170':'CO','604':'PE',
  '360':'ID','764':'TH','458':'MY','608':'PH','704':'VN','158':'TW',
  '682':'SA','784':'AE','634':'QA','818':'EG','566':'NG','376':'IL',
  '643':'RU','804':'UA','344':'HK','554':'NZ','764':'TH',
}

function geoFill(pct) {
  if (pct == null) return '#2a3550'
  if (pct > 0.35)  return '#ef4444'
  if (pct > 0.15)  return '#f59e0b'
  if (pct > 0)     return '#fde68a'
  return '#2a3550'
}

export function GeoWorldMap({ topCountries = {} }) {
  const [tip, setTip] = useState(null)
  const [pos, setPos] = useState({ x: 0, y: 0 })

  return (
    <div style={{ position: 'relative', width: '100%' }}>
      <ComposableMap projectionConfig={{ scale: 130 }} style={{ width: '100%', height: 280, display: 'block' }}>
        <ZoomableGroup>
          <Geographies geography={GEO_URL}>
            {({ geographies }) =>
              geographies.map((geo) => {
                const a2  = NUMERIC_TO_ALPHA2[String(geo.id)]
                const pct = a2 != null ? topCountries[a2] : undefined
                return (
                  <Geography
                    key={geo.rsmKey}
                    geography={geo}
                    fill={geoFill(pct)}
                    stroke="#1a2035"
                    strokeWidth={0.4}
                    style={{
                      default: { outline: 'none', transition: 'fill 0.15s' },
                      hover:   { outline: 'none', fill: pct != null ? '#60a5fa' : '#3d4f6e', cursor: 'pointer' },
                      pressed: { outline: 'none' },
                    }}
                    onMouseEnter={(e) => { setPos({ x: e.clientX, y: e.clientY }); setTip({ name: geo.properties.name, a2, pct }) }}
                    onMouseMove={(e) => setPos({ x: e.clientX, y: e.clientY })}
                    onMouseLeave={() => setTip(null)}
                  />
                )
              })
            }
          </Geographies>
        </ZoomableGroup>
      </ComposableMap>

      {tip && (
        <div style={{
          position: 'fixed', left: pos.x + 14, top: pos.y - 54, zIndex: 9999,
          background: 'var(--bg-panel)', border: '1px solid var(--border)',
          borderRadius: 6, padding: '6px 10px', pointerEvents: 'none',
          fontSize: 12, color: 'var(--text-primary)', minWidth: 140,
          boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
        }}>
          <div style={{ fontWeight: 700, marginBottom: 3 }}>
            {tip.name}{tip.a2 ? ` (${tip.a2})` : ''}
          </div>
          {tip.pct != null
            ? <>
                <div style={{ color: 'var(--text-secondary)' }}>
                  NAV: <strong style={{ color: 'var(--text-primary)' }}>{(tip.pct * 100).toFixed(1)}%</strong>
                </div>
                <div style={{ marginTop: 2 }}>
                  <span style={{
                    color: tip.pct > 0.35 ? '#ef4444' : '#f59e0b',
                    fontWeight: 700, fontSize: 11,
                  }}>
                    {tip.pct > 0.35 ? 'WARNING' : 'ELEVATED'}
                  </span>
                </div>
              </>
            : <div style={{ color: 'var(--text-secondary)' }}>No exposure</div>
          }
        </div>
      )}
    </div>
  )
}

export function GeoLegend() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 10, color: 'var(--text-secondary)', marginTop: 6 }}>
      <span>0%</span>
      <div style={{ flex: 1, height: 7, borderRadius: 4, background: 'linear-gradient(to right, #fde68a, #f59e0b, #ef4444)' }} />
      <span style={{ whiteSpace: 'nowrap' }}>35% <span style={{ color: '#f59e0b', fontWeight: 600 }}>Warn</span></span>
      <span style={{ whiteSpace: 'nowrap' }}>50%+ <span style={{ color: '#ef4444', fontWeight: 700 }}>Breach</span></span>
    </div>
  )
}

export function GeoBarChart({ topCountries = {} }) {
  const entries = Object.entries(topCountries).sort((a, b) => b[1] - a[1]).slice(0, 10)
  const totalShown = entries.reduce((s, [, v]) => s + v, 0)
  const other = Math.max(0, 1 - totalShown)
  const data = [
    ...entries.map(([k, v]) => ({ country: k, pct: +(v * 100).toFixed(1), eu: EU_ALPHA2.has(k) })),
    ...(other > 0.005 ? [{ country: 'Other', pct: +(other * 100).toFixed(1), eu: null }] : []),
  ]
  if (!data.length) return null
  return (
    <ResponsiveContainer width="100%" height={Math.max(180, data.length * 28)}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
        <XAxis type="number" unit="%" tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} axisLine={false} tickLine={false} />
        <YAxis type="category" dataKey="country" width={52} tick={{ fontSize: 11, fill: 'var(--text-secondary)' }} axisLine={false} tickLine={false} />
        <Tooltip formatter={(v) => v.toFixed(1) + '%'}
          contentStyle={{ background: 'var(--bg-panel)', borderColor: 'var(--border)', color: 'var(--text-primary)' }} />
        <Bar dataKey="pct" radius={[0, 4, 4, 0]}>
          {data.map((d, i) => (
            <Cell key={i} fill={d.country === 'Other' ? '#64748b' : d.eu ? '#3b82f6' : '#f59e0b'} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

export function GeoDonut({ euPct = 0, nonEuPct = 0 }) {
  const data = [
    { name: 'EU', value: +(euPct * 100).toFixed(1) },
    { name: 'Non-EU', value: +(nonEuPct * 100).toFixed(1) },
  ]
  const nonEuColor = nonEuPct > 0.50 ? '#ef4444' : '#f59e0b'
  return (
    <ResponsiveContainer width="100%" height={180}>
      <PieChart>
        <Pie data={data} dataKey="value" nameKey="name" cx="50%" cy="50%"
          innerRadius={45} outerRadius={70}>
          <Cell key="eu"   fill="#3b82f6" />
          <Cell key="noeu" fill={nonEuColor} />
        </Pie>
        <Tooltip formatter={(v) => v.toFixed(1) + '%'}
          contentStyle={{ background: 'var(--bg-panel)', borderColor: 'var(--border)', color: 'var(--text-primary)' }} />
        <Legend />
      </PieChart>
    </ResponsiveContainer>
  )
}
