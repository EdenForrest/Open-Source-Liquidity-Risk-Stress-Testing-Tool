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

function Badge({ ok, warn, label }) {
  if (ok)   return <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">{label}</span>
  if (warn) return <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">{label}</span>
  return       <span className="inline-flex items-center rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">{label}</span>
}

function StatusBadge({ warning_flag, breach_flag }) {
  if (breach_flag) return <Badge label="BREACH" ok={false} warn={false} />
  if (warning_flag) return <Badge label="Warning" ok={false} warn />
  return <Badge label="OK" ok warn={false} />
}

function LcrCell({ value, threshold = 0.1 }) {
  const pct = value ?? 0
  const color = pct >= 0.3 ? 'text-green-700' : pct >= threshold ? 'text-amber-700' : 'text-red-700'
  return <span className={`font-semibold ${color}`}>{fmt(value)}</span>
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
    return { code, entry, m }
  })

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">All Portfolios</h1>
        <p className="text-sm text-slate-500 mt-1">
          {portfolioCodes.length} portfolio{portfolioCodes.length !== 1 ? 's' : ''} — click a row to drill into that portfolio
        </p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-4">
        {rows.map(({ code, m }) => (
          <button
            key={code}
            onClick={() => selectPortfolio(code)}
            className={`text-left rounded-xl border p-4 shadow-sm transition-all hover:shadow-md ${
              code === selectedPortfolio
                ? 'border-blue-500 bg-blue-50'
                : 'border-slate-200 bg-white hover:border-slate-300'
            }`}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-bold text-slate-600 truncate">{code}</span>
              {m && <StatusBadge warning_flag={m.warning_flag} breach_flag={m.breach_flag} />}
            </div>
            <div className="text-lg font-bold text-slate-900">{fmtEur(m?.total_nav_eur)}</div>
            <div className="text-xs text-slate-400 mt-0.5">
              LCR T+1: <span className="font-semibold text-slate-700">{fmt(m?.lcr_t1)}</span>
            </div>
            <div className="text-xs text-slate-400">
              Illiquid: <span className="font-semibold text-slate-700">{fmt(m?.illiquid_pct)}</span>
            </div>
          </button>
        ))}
      </div>

      {/* Detail table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="px-5 py-3 border-b border-slate-100">
          <h2 className="text-sm font-semibold text-slate-700">Metric Comparison</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs text-slate-500 uppercase tracking-wide">
              <tr>
                <th className="px-4 py-3 text-left sticky left-0 bg-slate-50">Metric</th>
                {portfolioCodes.map(code => (
                  <th key={code} className="px-4 py-3 text-right whitespace-nowrap">{code}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              <MetricRow label="NAV (EUR)" codes={portfolioCodes} allData={allData} getter={m => fmtEur(m?.total_nav_eur)} />
              <MetricRow label="Reporting Date" codes={portfolioCodes} allData={allData} getter={m => m?.reporting_date ?? '—'} />
              <MetricRow label="Status" codes={portfolioCodes} allData={allData} getter={(m) => (
                <StatusBadge warning_flag={m?.warning_flag} breach_flag={m?.breach_flag} />
              )} />
              <MetricRow label="LCR T+1" codes={portfolioCodes} allData={allData} getter={m => <LcrCell value={m?.lcr_t1} />} />
              <MetricRow label="LCR T+3" codes={portfolioCodes} allData={allData} getter={m => <LcrCell value={m?.lcr_t3} />} />
              <MetricRow label="LCR T+7" codes={portfolioCodes} allData={allData} getter={m => <LcrCell value={m?.lcr_t7} />} />
              <MetricRow label="Illiquid (>T+7)" codes={portfolioCodes} allData={allData} getter={m => fmt(m?.illiquid_pct)} />
              <MetricRow label="Top-10 Concentration" codes={portfolioCodes} allData={allData} getter={m => fmt(m?.top10_concentration)} />
              <MetricRow label="Liq / Concentration" codes={portfolioCodes} allData={allData} getter={m => (m?.liquidity_vs_concentration ?? null) != null ? m.liquidity_vs_concentration.toFixed(2) + 'x' : '—'} />
              <MetricRow label="Days to 50% liquidated" codes={portfolioCodes} allData={allData} getter={m => fmtDays(m?.days_to_50pct)} />
              <MetricRow label="Days to 75% liquidated" codes={portfolioCodes} allData={allData} getter={m => fmtDays(m?.days_to_75pct)} />
              <MetricRow label="Days to 90% liquidated" codes={portfolioCodes} allData={allData} getter={m => fmtDays(m?.days_to_90pct)} />
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function MetricRow({ label, codes, allData, getter }) {
  return (
    <tr className="hover:bg-slate-50">
      <td className="px-4 py-2.5 font-medium text-slate-600 sticky left-0 bg-white whitespace-nowrap">{label}</td>
      {codes.map(code => {
        const m = allData[code]?.liquidity?.liquidity_metrics
        return (
          <td key={code} className="px-4 py-2.5 text-right text-slate-800">
            {getter(m)}
          </td>
        )
      })}
    </tr>
  )
}
