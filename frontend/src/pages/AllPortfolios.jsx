import { useAnalysis } from '../AnalysisContext'
import EmptyState from '../components/EmptyState'

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
function fmtDays(n) {
  if (n == null) return '—'
  return n.toFixed(1) + 'd'
}

function StatusDot({ warning_flag, breach_flag }) {
  if (breach_flag) return <span className="text-xs font-semibold" style={{ color: 'var(--kpi-red-text)' }}>BREACH</span>
  if (warning_flag) return <span className="text-xs font-semibold" style={{ color: 'var(--kpi-amber-text)' }}>Warning</span>
  return <span className="text-xs font-semibold" style={{ color: 'var(--kpi-green-text)' }}>OK</span>
}

// higher = better (LCR, coverage ratios)
function LcrCell({ value, threshold = 0.1 }) {
  const pct = value ?? 0
  const color = pct >= 0.3 ? 'var(--kpi-green-text)' : pct >= threshold ? 'var(--kpi-amber-text)' : 'var(--kpi-red-text)'
  return <span className="font-semibold" style={{ color }}>{fmt(value)}</span>
}

// higher = worse (illiquid %, concentration, days, leverage)
function RiskCell({ value, warnAt, redAt, display }) {
  if (value == null) return <span style={{ color: 'var(--text-muted)' }}>—</span>
  const color = value >= redAt ? 'var(--kpi-red-text)' : value >= warnAt ? 'var(--kpi-amber-text)' : 'var(--kpi-green-text)'
  return <span className="font-semibold" style={{ color }}>{display ?? value}</span>
}

// higher = better (liq/concentration ratio)
function RatioCell({ value }) {
  if (value == null) return <span style={{ color: 'var(--text-muted)' }}>—</span>
  const color = value >= 1.5 ? 'var(--kpi-green-text)' : value >= 0.5 ? 'var(--kpi-amber-text)' : 'var(--kpi-red-text)'
  return <span className="font-semibold" style={{ color }}>{value.toFixed(2)}x</span>
}

export default function AllPortfolios() {
  const { allData, portfolioCodes, status, selectedPortfolio, selectPortfolio } = useAnalysis()

  if (status === 'idle' || status === 'uploading' || status === 'running') {
    return <EmptyState message="Upload files and run the analysis to see all portfolios." />
  }

  if (!portfolioCodes || portfolioCodes.length === 0) {
    return <EmptyState message="No portfolio data available." />
  }

  const rows = portfolioCodes.map(code => {
    const entry = allData[code]
    const m = entry?.liquidity?.liquidity_metrics
    const a = entry?.aifmd2
    return { code, entry, m, a }
  })

  return (
    <div className="p-3 space-y-3">
      <div>
        <h1 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>All Portfolios</h1>
        <p className="text-sm mt-1" style={{ color: 'var(--text-secondary)' }}>
          {portfolioCodes.length} portfolio{portfolioCodes.length !== 1 ? 's' : ''} — click a row to drill into that portfolio
        </p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-2">
        {rows.map(({ code, m, a }) => (
          <button
            key={code}
            onClick={() => selectPortfolio(code)}
            style={code === selectedPortfolio
              ? { background: 'var(--bg-surface)', border: '1px solid var(--text-accent)' }
              : { background: 'var(--bg-panel)', border: '1px solid var(--border)' }
            }
            className="text-left rounded p-3 shadow-sm transition-all hover:opacity-80"
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-bold truncate" style={{ color: 'var(--text-secondary)' }}>{code}</span>
              {m && <StatusDot warning_flag={m.warning_flag} breach_flag={m.breach_flag || a?.leverage_breach} />}
            </div>
            <div className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>{fmtEur(m?.total_nav_eur)}</div>
            <div className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
              LCR T+1: <span className="font-semibold" style={{ color: 'var(--text-primary)' }}>{fmt(m?.lcr_t1)}</span>
            </div>
            <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
              Illiquid: <span className="font-semibold" style={{ color: 'var(--text-primary)' }}>{fmt(m?.illiquid_pct)}</span>
            </div>
          </button>
        ))}
      </div>

      {/* Detail table */}
      <div className="rounded border overflow-hidden" style={{ background: 'var(--bg-panel)', borderColor: 'var(--border)' }}>
        <div className="bb-head px-3 py-2" style={{ borderBottom: '1px solid var(--border)' }}>
          <h2 className="text-sm font-semibold" style={{ color: 'var(--text-secondary)' }}>Metric Comparison</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs uppercase tracking-wide" style={{ background: 'var(--bg-surface)', color: 'var(--text-secondary)' }}>
              <tr>
                <th className="px-3 py-2 text-left" style={{ background: 'var(--bg-surface)' }}>Metric</th>
                {portfolioCodes.map(code => (
                  <th key={code} className="px-3 py-2 text-right whitespace-nowrap">{code}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              <MetricRow label="NAV (EUR)" codes={portfolioCodes} allData={allData} getter={m => fmtEur(m?.total_nav_eur)} />
              <MetricRow label="Reporting Date" codes={portfolioCodes} allData={allData} getter={m => m?.reporting_date ?? '—'} />
              <BreachRow codes={portfolioCodes} allData={allData} />
              <MetricRow label="LCR T+1" codes={portfolioCodes} allData={allData} getter={m => <LcrCell value={m?.lcr_t1} />} />
              <MetricRow label="LCR T+3" codes={portfolioCodes} allData={allData} getter={m => <LcrCell value={m?.lcr_t3} />} />
              <MetricRow label="LCR T+7" codes={portfolioCodes} allData={allData} getter={m => <LcrCell value={m?.lcr_t7} />} />
              <MetricRow label="Illiquid (>T+7)" codes={portfolioCodes} allData={allData} getter={m => (
                <RiskCell value={m?.illiquid_pct} warnAt={0.1} redAt={0.2} display={fmt(m?.illiquid_pct)} />
              )} />
              <MetricRow label="Top-10 Concentration" codes={portfolioCodes} allData={allData} getter={m => (
                <RiskCell value={m?.top10_concentration} warnAt={0.4} redAt={0.6} display={fmt(m?.top10_concentration)} />
              )} />
              <MetricRow label="Liq / Concentration" codes={portfolioCodes} allData={allData} getter={m => (
                <RatioCell value={m?.liquidity_vs_concentration} />
              )} />
              <MetricRow label="Days to 50% liquidated" codes={portfolioCodes} allData={allData} getter={m => (
                <RiskCell value={m?.days_to_50pct} warnAt={3} redAt={7} display={fmtDays(m?.days_to_50pct)} />
              )} />
              <MetricRow label="Days to 75% liquidated" codes={portfolioCodes} allData={allData} getter={m => (
                <RiskCell value={m?.days_to_75pct} warnAt={7} redAt={14} display={fmtDays(m?.days_to_75pct)} />
              )} />
              <MetricRow label="Days to 90% liquidated" codes={portfolioCodes} allData={allData} getter={m => (
                <RiskCell value={m?.days_to_90pct} warnAt={14} redAt={30} display={fmtDays(m?.days_to_90pct)} />
              )} />
              <MetricRow label="Geo Top Country" codes={portfolioCodes} allData={allData} getter={m => (
                m?.geo_top_country
                  ? `${m.geo_top_country} ${fmt(m.geo_top_country_pct)}`
                  : '—'
              )} />
              <MetricRow label="Non-EU Exposure" codes={portfolioCodes} allData={allData} getter={m => (
                <RiskCell value={m?.non_eu_pct} warnAt={0.35} redAt={0.50} display={fmt(m?.non_eu_pct)} />
              )} />
              <MetricRow label="Geo Status" codes={portfolioCodes} allData={allData} getter={m => {
                if (m?.geo_breach_flag) return <span className="font-semibold" style={{ color: 'var(--kpi-red-text)' }}>BREACH</span>
                if (m?.geo_warning_flag) return <span className="font-semibold" style={{ color: 'var(--kpi-amber-text)' }}>Warning</span>
                return <span className="font-semibold" style={{ color: 'var(--kpi-green-text)' }}>OK</span>
              }} />
              <LeverageMetricRow label="AIFMD II Status" codes={portfolioCodes} allData={allData} getter={a => {
                if (!a) return <span style={{ color: 'var(--text-muted)' }}>—</span>
                if (a.leverage_breach) return <span className="font-semibold" style={{ color: 'var(--kpi-red-text)' }}>BREACH</span>
                if (!a.lmt_compliant) return <span className="font-semibold" style={{ color: 'var(--kpi-amber-text)' }}>INCOMPLETE</span>
                return <span className="font-semibold" style={{ color: 'var(--kpi-green-text)' }}>OK</span>
              }} />
              <LeverageMetricRow label="Gross Leverage" codes={portfolioCodes} allData={allData} getter={a => (
                <RiskCell value={a?.gross_leverage} warnAt={1.5} redAt={1.75} display={a?.gross_leverage != null ? (a.gross_leverage * 100).toFixed(1) + '%' : null} />
              )} />
              <LeverageMetricRow label="Commitment Leverage" codes={portfolioCodes} allData={allData} getter={a => (
                <RiskCell value={a?.commitment_leverage} warnAt={1.5} redAt={1.75} display={a?.commitment_leverage != null ? (a.commitment_leverage * 100).toFixed(1) + '%' : null} />
              )} />
              <LeverageMetricRow label="Leverage Cap" codes={portfolioCodes} allData={allData} getter={a => a?.leverage_cap != null ? (a.leverage_cap * 100).toFixed(0) + '%' : '—'} />
              <LeverageMetricRow label="LMTs Pre-selected" codes={portfolioCodes} allData={allData} getter={a => {
                if (a?.lmt_count == null) return <span style={{ color: 'var(--text-muted)' }}>—</span>
                const color = a.lmt_compliant ? 'var(--kpi-green-text)' : 'var(--kpi-red-text)'
                return <span className="font-semibold" style={{ color }}>{a.lmt_count} ({a.lmt_compliant ? 'compliant' : 'insufficient'})</span>
              }} />
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function BreachRow({ codes, allData }) {
  return (
    <tr style={{ borderBottom: '1px solid var(--border)' }} className="transition-colors hover:opacity-80">
      <td className="px-3 py-1.5 font-medium whitespace-nowrap" style={{ color: 'var(--text-secondary)', background: 'var(--bg-panel)' }}>Breach / Warning</td>
      {codes.map(code => {
        const m = allData[code]?.liquidity?.liquidity_metrics
        const a = allData[code]?.aifmd2
        const isBreach = m?.breach_flag || a?.leverage_breach
        const isWarning = !isBreach && m?.warning_flag
        return (
          <td key={code} className="px-3 py-1.5 text-right">
            {isBreach
              ? <span className="text-xs font-semibold" style={{ color: 'var(--kpi-red-text)' }}>BREACH</span>
              : isWarning
              ? <span className="text-xs font-semibold" style={{ color: 'var(--kpi-amber-text)' }}>Warning</span>
              : <span className="text-xs font-semibold" style={{ color: 'var(--kpi-green-text)' }}>OK</span>
            }
          </td>
        )
      })}
    </tr>
  )
}

function MetricRow({ label, codes, allData, getter }) {
  return (
    <tr style={{ borderBottom: '1px solid var(--border)' }}
      className="transition-colors hover:opacity-80">
      <td className="px-3 py-1.5 font-medium whitespace-nowrap" style={{ color: 'var(--text-secondary)', background: 'var(--bg-panel)' }}>{label}</td>
      {codes.map(code => {
        const m = allData[code]?.liquidity?.liquidity_metrics
        return (
          <td key={code} className="px-3 py-1.5 text-right" style={{ color: 'var(--text-primary)' }}>
            {getter(m)}
          </td>
        )
      })}
    </tr>
  )
}

function LeverageMetricRow({ label, codes, allData, getter }) {
  return (
    <tr style={{ borderBottom: '1px solid var(--border)' }}
      className="transition-colors hover:opacity-80">
      <td className="px-3 py-1.5 font-medium whitespace-nowrap" style={{ color: 'var(--text-secondary)', background: 'var(--bg-panel)' }}>{label}</td>
      {codes.map(code => {
        const a = allData[code]?.aifmd2
        return (
          <td key={code} className="px-3 py-1.5 text-right" style={{ color: 'var(--text-primary)' }}>
            {getter(a)}
          </td>
        )
      })}
    </tr>
  )
}
