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

// A fund is an AIF when it is a loan-origination AIF or carries leverage above
// 100% NAV (derivatives/loans → AIFMD II regime). Otherwise it is treated as a
// UCITS. UCITS issuer-concentration rows are hidden for AIFs, and AIFMD II
// leverage/LMT rows are hidden for UCITS — a fund is one or the other.
//
// Plain long-only funds compute gross leverage of exactly 1.0 in theory, but
// floating-point summation leaves dust just above 1.0 (e.g. 1.0000000000002).
// A small tolerance keeps unlevered funds classified as UCITS instead of being
// misread as AIFs on rounding error.
const _LEVERAGE_AIF_TOL = 1e-6
function isAif(a) {
  if (!a) return false
  return !!a.is_loan_origination_aif || (a.gross_leverage != null && a.gross_leverage > 1.0 + _LEVERAGE_AIF_TOL)
}
const naCell = <span style={{ color: 'var(--text-muted)' }}>—</span>

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

export default function AllPortfolios() {
  const { allData, portfolioCodes, status, selectedPortfolio, selectPortfolio, runId } = useAnalysis()
  const { t } = useTranslation()
  const [exportOpen, setExportOpen] = useState(false)

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
          <p className="text-xs mt-0.5" style={{ color: 'var(--text-secondary)', opacity: 0.7 }}>
            Realisable figures (LCR, illiquid realisable) are shown net of liquidation haircut.
          </p>
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
              <RegimeRow codes={portfolioCodes} allData={allData} />
              <MetricRow label={t('allPortfolios.metrics.totalNav')} codes={portfolioCodes} allData={allData} getter={m => fmtEur(m?.total_nav_eur)} />
              <MetricRow label="Reporting Date" codes={portfolioCodes} allData={allData} getter={m => m?.reporting_date ?? '—'} />
              <MetricRow label={t('allPortfolios.metrics.lcrT1')} codes={portfolioCodes} allData={allData} getter={m => <LcrCell value={m?.lcr_t1} />} />
              <MetricRow label={t('allPortfolios.metrics.lcrT3')} codes={portfolioCodes} allData={allData} getter={m => <LcrCell value={m?.lcr_t3} />} />
              <MetricRow label={t('allPortfolios.metrics.lcrT7')} codes={portfolioCodes} allData={allData} getter={m => <LcrCell value={m?.lcr_t7} />} />
              <MetricRow label={t('allPortfolios.metrics.illiquidPct')} codes={portfolioCodes} allData={allData} getter={m => (
                <RiskCell value={m?.illiquid_realisable} warnAt={0.1} redAt={0.2} display={fmt(m?.illiquid_realisable)} />
              )} />
              <MetricRow label="Top-10 Concentration" codes={portfolioCodes} allData={allData} getter={m => (
                <RiskCell value={m?.top10_concentration} warnAt={0.4} redAt={0.6} display={fmt(m?.top10_concentration)} />
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
              <MetricRow label="UCITS Status" codes={portfolioCodes} allData={allData} regime="ucits" getter={m => {
                if (m?.ucits_single_breach || m?.ucits_aggregate_breach)
                  return <span className="font-semibold" style={{ color: 'var(--kpi-red-text)' }}>BREACH</span>
                return <span className="font-semibold" style={{ color: 'var(--kpi-green-text)' }}>OK</span>
              }} />
              <MetricRow label="UCITS 5–10% Bucket" codes={portfolioCodes} allData={allData} regime="ucits" getter={m => (
                <RiskCell value={m?.ucits_aggregate_5_10} warnAt={0.30} redAt={0.40} display={m?.ucits_aggregate_5_10 != null ? (m.ucits_aggregate_5_10 * 100).toFixed(1) + '%' : null} />
              )} />
              <LeverageMetricRow label={t('dashboard.aifmd.status')} codes={portfolioCodes} allData={allData} getter={a => {
                if (!a) return <span style={{ color: 'var(--text-muted)' }}>—</span>
                if (a.leverage_breach) return <span className="font-semibold" style={{ color: 'var(--kpi-red-text)' }}>{t('allPortfolios.breach')}</span>
                if (!a.lmt_compliant) return <span className="font-semibold" style={{ color: 'var(--kpi-amber-text)' }}>INCOMPLETE</span>
                return <span className="font-semibold" style={{ color: 'var(--kpi-green-text)' }}>{t('allPortfolios.ok')}</span>
              }} />
              <LeverageMetricRow label={t('allPortfolios.metrics.grossLev')} codes={portfolioCodes} allData={allData} getter={a => (
                a?.gross_leverage == null ? <span style={{ color: 'var(--text-muted)' }}>—</span> : (
                  <span>
                    <RiskCell value={a.gross_leverage} warnAt={1.5} redAt={1.75} display={(a.gross_leverage * 100).toFixed(1) + '%'} />
                    {a.leverage_cap != null && <span className="ml-1 text-xs font-normal opacity-60">/ cap {(a.leverage_cap * 100).toFixed(0)}%</span>}
                  </span>
                )
              )} />
              <LeverageMetricRow label={t('allPortfolios.metrics.commitLev')} codes={portfolioCodes} allData={allData} getter={a => (
                <RiskCell value={a?.commitment_leverage} warnAt={1.5} redAt={1.75} display={a?.commitment_leverage != null ? (a.commitment_leverage * 100).toFixed(1) + '%' : null} />
              )} />
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

// Labels each portfolio's regulatory regime so the n/a cells in the
// regime-specific rows below read clearly (UCITS rows blank for AIFs, and the
// AIFMD II leverage/LMT rows blank for UCITS).
function RegimeRow({ codes, allData }) {
  return (
    <tr style={{ borderBottom: '1px solid var(--border)' }} className="transition-colors hover:opacity-80">
      <td className="px-3 py-1.5 font-medium whitespace-nowrap" style={{ color: 'var(--text-secondary)', background: 'var(--bg-panel)' }}>
        Regime
      </td>
      {codes.map(code => (
        <td key={code} className="px-3 py-1.5 text-right text-xs font-semibold" style={{ color: 'var(--text-secondary)' }}>
          {isAif(allData[code]?.aifmd2) ? 'AIF' : 'UCITS'}
        </td>
      ))}
    </tr>
  )
}

// `regime` (optional): 'ucits' shows the cell only for UCITS funds, 'aif' only
// for AIFs. Cells for the opposite regime render n/a — a fund is one or the other.
function MetricRow({ label, codes, allData, getter, regime }) {
  return (
    <tr style={{ borderBottom: '1px solid var(--border)' }}
      className="transition-colors hover:opacity-80">
      <td className="px-3 py-1.5 font-medium whitespace-nowrap" style={{ color: 'var(--text-secondary)', background: 'var(--bg-panel)' }}>{label}</td>
      {codes.map(code => {
        const m = allData[code]?.liquidity?.liquidity_metrics
        const aif = isAif(allData[code]?.aifmd2)
        const hide = regime === 'ucits' ? aif : regime === 'aif' ? !aif : false
        return (
          <td key={code} className="px-3 py-1.5 text-right" style={{ color: 'var(--text-primary)' }}>
            {hide ? naCell : getter(m)}
          </td>
        )
      })}
    </tr>
  )
}

// AIFMD II rows: shown only for AIFs (UCITS funds render n/a).
function LeverageMetricRow({ label, codes, allData, getter }) {
  return (
    <tr style={{ borderBottom: '1px solid var(--border)' }}
      className="transition-colors hover:opacity-80">
      <td className="px-3 py-1.5 font-medium whitespace-nowrap" style={{ color: 'var(--text-secondary)', background: 'var(--bg-panel)' }}>{label}</td>
      {codes.map(code => {
        const a = allData[code]?.aifmd2
        return (
          <td key={code} className="px-3 py-1.5 text-right" style={{ color: 'var(--text-primary)' }}>
            {isAif(a) ? getter(a) : naCell}
          </td>
        )
      })}
    </tr>
  )
}
