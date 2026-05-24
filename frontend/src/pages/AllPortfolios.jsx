import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAnalysis } from '../AnalysisContext'
import EmptyState from '../components/EmptyState'
import ExportModal from '../components/ExportModal'

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
  const { t } = useTranslation()
  if (breach_flag) return <span className="text-xs font-semibold" style={{ color: 'var(--kpi-red-text)' }}>{t('allPortfolios.breach')}</span>
  if (warning_flag) return <span className="text-xs font-semibold" style={{ color: 'var(--kpi-amber-text)' }}>{t('allPortfolios.warning')}</span>
  return <span className="text-xs font-semibold" style={{ color: 'var(--kpi-green-text)' }}>{t('allPortfolios.ok')}</span>
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
  const { allData, portfolioCodes, status, selectedPortfolio, selectPortfolio, runId } = useAnalysis()
  const { t } = useTranslation()
  const [exportOpen, setExportOpen] = useState(false)
  const [downloadingAll, setDownloadingAll] = useState(false)

  if (status === 'idle' || status === 'uploading' || status === 'running') {
    return <EmptyState />
  }

  if (!portfolioCodes || portfolioCodes.length === 0) {
    return <EmptyState />
  }

  const rows = portfolioCodes.map(code => {
    const entry = allData[code]
    const m = entry?.liquidity?.liquidity_metrics
    const a = entry?.aifmd2
    return { code, entry, m, a }
  })

  async function downloadAll() {
    if (!runId || downloadingAll) return
    setDownloadingAll(true)
    const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '') + '/api'
    try {
      await Promise.all(portfolioCodes.map(async (code) => {
        const url = `${base}/run/${runId}/export/excel?portfolio=${encodeURIComponent(code)}`
        const resp = await fetch(url)
        if (!resp.ok) throw new Error(`${code}: server returned ${resp.status}`)
        const blob = await resp.blob()
        const objUrl = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = objUrl
        a.download = `liquidity_report_${code}.xlsx`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(objUrl)
      }))
    } finally {
      setDownloadingAll(false)
    }
  }

  return (
    <div className="p-3 space-y-3">
      <ExportModal open={exportOpen} onClose={() => setExportOpen(false)} />
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>{t('allPortfolios.title')}</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--text-secondary)' }}>
            {t('allPortfolios.portfolioCount', { count: portfolioCodes.length })} — {t('allPortfolios.clickHint', 'click a row to drill into that portfolio')}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setExportOpen(true)}
            className="flex items-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium"
            style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', color: 'var(--text-primary)', cursor: 'pointer' }}
            title={t('uploader.downloadReport')}
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
            {t('uploader.downloadReport')}
          </button>
          <button
            onClick={downloadAll}
            disabled={downloadingAll}
            className="flex items-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium disabled:opacity-50"
            style={{ background: 'var(--text-accent)', border: '1px solid transparent', color: '#fff', cursor: downloadingAll ? 'wait' : 'pointer' }}
            title={t('allPortfolios.downloadAll', 'Download all portfolios')}
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
            {downloadingAll ? t('export.downloading') : t('allPortfolios.downloadAll', 'Download All')}
          </button>
        </div>
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
              {t('allPortfolios.metrics.lcrT1')}: <span className="font-semibold" style={{ color: 'var(--text-primary)' }}>{fmt(m?.lcr_t1)}</span>
            </div>
            <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
              {t('dashboard.kpi.illiquid')}: <span className="font-semibold" style={{ color: 'var(--text-primary)' }}>{fmt(m?.illiquid_pct)}</span>
            </div>
          </button>
        ))}
      </div>

      {/* Detail table */}
      <div className="rounded border overflow-hidden" style={{ background: 'var(--bg-panel)', borderColor: 'var(--border)' }}>
        <div className="bb-head px-3 py-2" style={{ borderBottom: '1px solid var(--border)' }}>
          <h2 className="text-sm font-semibold" style={{ color: 'var(--text-secondary)' }}>{t('allPortfolios.metricComparison')}</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs uppercase tracking-wide" style={{ background: 'var(--bg-surface)', color: 'var(--text-secondary)' }}>
              <tr>
                <th className="px-3 py-2 text-left" style={{ background: 'var(--bg-surface)' }}>{t('allPortfolios.metric')}</th>
                {portfolioCodes.map(code => (
                  <th key={code} className="px-3 py-2 text-right whitespace-nowrap">{code}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              <MetricRow label={t('allPortfolios.metrics.totalNav')} codes={portfolioCodes} allData={allData} getter={m => fmtEur(m?.total_nav_eur)} />
              <MetricRow label="Reporting Date" codes={portfolioCodes} allData={allData} getter={m => m?.reporting_date ?? '—'} />
              <BreachRow codes={portfolioCodes} allData={allData} />
              <MetricRow label={t('allPortfolios.metrics.lcrT1')} codes={portfolioCodes} allData={allData} getter={m => <LcrCell value={m?.lcr_t1} />} />
              <MetricRow label={t('allPortfolios.metrics.lcrT3')} codes={portfolioCodes} allData={allData} getter={m => <LcrCell value={m?.lcr_t3} />} />
              <MetricRow label={t('allPortfolios.metrics.lcrT7')} codes={portfolioCodes} allData={allData} getter={m => <LcrCell value={m?.lcr_t7} />} />
              <MetricRow label={t('allPortfolios.metrics.illiquidPct')} codes={portfolioCodes} allData={allData} getter={m => (
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
              <MetricRow label={t('allPortfolios.metrics.geoTopCountry')} codes={portfolioCodes} allData={allData} getter={m => (
                m?.geo_top_country ? `${m.geo_top_country} ${fmt(m.geo_top_country_pct)}` : '—'
              )} />
              <MetricRow label={t('allPortfolios.metrics.nonEuExposure')} codes={portfolioCodes} allData={allData} getter={m => (
                <RiskCell value={m?.non_eu_pct} warnAt={0.35} redAt={0.50} display={fmt(m?.non_eu_pct)} />
              )} />
              <MetricRow label={t('allPortfolios.metrics.geoStatus')} codes={portfolioCodes} allData={allData} getter={m => {
                if (m?.geo_breach_flag) return <span className="font-semibold" style={{ color: 'var(--kpi-red-text)' }}>{t('allPortfolios.breach')}</span>
                if (m?.geo_warning_flag) return <span className="font-semibold" style={{ color: 'var(--kpi-amber-text)' }}>{t('allPortfolios.warning')}</span>
                return <span className="font-semibold" style={{ color: 'var(--kpi-green-text)' }}>{t('allPortfolios.ok')}</span>
              }} />
              <LeverageMetricRow label={t('dashboard.aifmd.status')} codes={portfolioCodes} allData={allData} getter={a => {
                if (!a) return <span style={{ color: 'var(--text-muted)' }}>—</span>
                if (a.leverage_breach) return <span className="font-semibold" style={{ color: 'var(--kpi-red-text)' }}>{t('allPortfolios.breach')}</span>
                if (!a.lmt_compliant) return <span className="font-semibold" style={{ color: 'var(--kpi-amber-text)' }}>INCOMPLETE</span>
                return <span className="font-semibold" style={{ color: 'var(--kpi-green-text)' }}>{t('allPortfolios.ok')}</span>
              }} />
              <LeverageMetricRow label={t('allPortfolios.metrics.grossLev')} codes={portfolioCodes} allData={allData} getter={a => (
                <RiskCell value={a?.gross_leverage} warnAt={1.5} redAt={1.75} display={a?.gross_leverage != null ? (a.gross_leverage * 100).toFixed(1) + '%' : null} />
              )} />
              <LeverageMetricRow label={t('allPortfolios.metrics.commitLev')} codes={portfolioCodes} allData={allData} getter={a => (
                <RiskCell value={a?.commitment_leverage} warnAt={1.5} redAt={1.75} display={a?.commitment_leverage != null ? (a.commitment_leverage * 100).toFixed(1) + '%' : null} />
              )} />
              <LeverageMetricRow label={t('allPortfolios.metrics.leverageCap')} codes={portfolioCodes} allData={allData} getter={a => a?.leverage_cap != null ? (a.leverage_cap * 100).toFixed(0) + '%' : '—'} />
              <LeverageMetricRow label={t('allPortfolios.metrics.lmtCount')} codes={portfolioCodes} allData={allData} getter={a => {
                if (a?.lmt_count == null) return <span style={{ color: 'var(--text-muted)' }}>—</span>
                const color = a.lmt_compliant ? 'var(--kpi-green-text)' : 'var(--kpi-red-text)'
                return <span className="font-semibold" style={{ color }}>{a.lmt_count} ({a.lmt_compliant ? t('allPortfolios.compliant') : t('allPortfolios.insufficient')})</span>
              }} />
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function BreachRow({ codes, allData }) {
  const { t } = useTranslation()
  return (
    <tr style={{ borderBottom: '1px solid var(--border)' }} className="transition-colors hover:opacity-80">
      <td className="px-3 py-1.5 font-medium whitespace-nowrap" style={{ color: 'var(--text-secondary)', background: 'var(--bg-panel)' }}>
        {t('allPortfolios.breach')} / {t('allPortfolios.warning')}
      </td>
      {codes.map(code => {
        const m = allData[code]?.liquidity?.liquidity_metrics
        const a = allData[code]?.aifmd2
        const isBreach = m?.breach_flag || a?.leverage_breach
        const isWarning = !isBreach && m?.warning_flag
        return (
          <td key={code} className="px-3 py-1.5 text-right">
            {isBreach
              ? <span className="text-xs font-semibold" style={{ color: 'var(--kpi-red-text)' }}>{t('allPortfolios.breach')}</span>
              : isWarning
              ? <span className="text-xs font-semibold" style={{ color: 'var(--kpi-amber-text)' }}>{t('allPortfolios.warning')}</span>
              : <span className="text-xs font-semibold" style={{ color: 'var(--kpi-green-text)' }}>{t('allPortfolios.ok')}</span>
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
