import { useTranslation } from 'react-i18next'
import { useAnalysis } from '../AnalysisContext'
import KPICard from '../components/KPICard'
import EmptyState from '../components/EmptyState'
import StatusBanner from '../components/StatusBanner'
import MetricTooltip from '../components/MetricTooltip'
import { pct, fmtEur } from '../utils/formatters'

function Row({ label, value, sub, highlight }) {
  return (
    <tr style={highlight ? { background: 'var(--kpi-red-bg)' } : {}}>
      <td className="px-3 py-1.5 text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>{label}</td>
      <td className="px-3 py-1.5 text-sm font-semibold text-right" style={{ color: highlight ? 'var(--kpi-red-text)' : 'var(--text-primary)' }}>
        {value}
        {sub && <span className="ml-2 text-xs font-normal opacity-60">{sub}</span>}
      </td>
    </tr>
  )
}

export default function Leverage() {
  const { t } = useTranslation()
  const { data, error } = useAnalysis()
  if (error) return <StatusBanner />
  if (!data?.aifmd2) return <EmptyState />

  const a = data.aifmd2
  const liq = data.liquidity

  const grossPct = a.gross_leverage != null ? (a.gross_leverage * 100).toFixed(1) + '%' : '—'
  const commitPct = a.commitment_leverage != null ? (a.commitment_leverage * 100).toFixed(1) + '%' : '—'
  const capPct = a.leverage_cap != null ? (a.leverage_cap * 100).toFixed(0) + '%' : '—'
  const headroomPct = (a.gross_leverage != null && a.leverage_cap != null)
    ? ((a.leverage_cap - a.gross_leverage) * 100).toFixed(1) + '%'
    : '—'
  const utilizationPct = (a.gross_leverage != null && a.leverage_cap != null && a.leverage_cap > 0)
    ? ((a.gross_leverage / a.leverage_cap) * 100).toFixed(1) + '%'
    : '—'

  const warnings = a.warnings ? a.warnings.split('; ').filter(Boolean) : []
  const lmts = Array.isArray(a.lmt_preselected) ? a.lmt_preselected : (a.lmt_preselected ? [a.lmt_preselected] : [])

  const panelStyle = { background: 'var(--bg-panel)', borderColor: 'var(--border)' }
  const surfaceStyle = { background: 'var(--bg-surface)' }

  return (
    <div className="p-3 space-y-3">
      <div>
        <h1 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>
          {t('leverage.title', { fundName: liq?.fund_name ?? '' })}
        </h1>
        <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
          {a.regulatory_basis}
        </p>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <KPICard
          label={<MetricTooltip id="gross_leverage">{t('leverage.kpi.grossLeverage')}</MetricTooltip>}
          value={grossPct}
          sub={t('leverage.kpiSub.cap', { pct: capPct })}
          color={a.leverage_breach ? 'red' : 'slate'}
          alert={a.leverage_breach}
        />
        <KPICard
          label={t('leverage.kpi.commitmentLeverage')}
          value={commitPct}
          color="slate"
        />
        <KPICard
          label={<MetricTooltip id="cap_utilization">{t('leverage.kpi.capUtilization')}</MetricTooltip>}
          value={utilizationPct}
          sub={t('leverage.kpiSub.headroom', { pct: headroomPct })}
          color={a.leverage_breach ? 'red' : (parseFloat(utilizationPct) > 80 ? 'amber' : 'green')}
        />
        <KPICard
          label={<MetricTooltip id="lmt_count">{t('leverage.kpi.lmtsPreselected')}</MetricTooltip>}
          value={a.lmt_count ?? '—'}
          sub={a.lmt_compliant ? t('leverage.kpiSub.compliant') : t('leverage.kpiSub.insufficient')}
          color={a.lmt_compliant ? 'green' : 'red'}
        />
      </div>

      {/* Warnings */}
      {warnings.length > 0 && (
        <div className="rounded border p-3 space-y-1" style={{ background: 'var(--kpi-amber-bg)', borderColor: 'var(--kpi-amber-border)' }}>
          {warnings.map((w, i) => (
            <p key={i} className="text-sm" style={{ color: 'var(--kpi-amber-text)' }}>⚠ {w}</p>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        {/* Leverage detail table */}
        <div className="rounded shadow-sm border overflow-auto" style={panelStyle}>
          <h2 className="text-sm font-semibold uppercase tracking-wide bb-head px-3 py-2" style={{ ...surfaceStyle, color: 'var(--text-secondary)' }}>
            {t('leverage.section.leverageMetrics')}
          </h2>
          <table className="w-full">
            <tbody>
              <Row label={t('leverage.rows.grossLeverage')} value={grossPct} highlight={a.leverage_breach} />
              <Row label={t('leverage.rows.commitmentLeverage')} value={commitPct} />
              <Row label={t('leverage.rows.applicableCap')} value={capPct} />
              <Row label={t('leverage.rows.capHeadroom')} value={headroomPct} />
              <Row label={t('leverage.rows.capUtilization')} value={utilizationPct} />
              {liq?.total_nav_eur != null && (
                <Row label={t('leverage.rows.nav')} value={fmtEur(liq.total_nav_eur)} />
              )}
            </tbody>
          </table>
        </div>

        {/* Loan origination & constraints */}
        <div className="rounded shadow-sm border overflow-auto" style={panelStyle}>
          <h2 className="text-sm font-semibold uppercase tracking-wide bb-head px-3 py-2" style={{ ...surfaceStyle, color: 'var(--text-secondary)' }}>
            {t('leverage.section.loanOrigination')}
          </h2>
          <table className="w-full">
            <tbody>
              <Row
                label={t('leverage.rows.loanOriginationAif')}
                value={a.is_loan_origination_aif ? t('leverage.values.yesApplies') : t('leverage.values.no')}
                highlight={a.is_loan_origination_aif}
              />
              <Row label={t('leverage.rows.loansPctNav')} value={pct(a.loan_pct_nav)} sub={t('leverage.values.threshold50')} />
              <Row
                label={t('leverage.rows.riskRetention')}
                value={a.risk_retention_ok ? t('leverage.values.ok') : t('leverage.values.breach')}
                highlight={!a.risk_retention_ok}
              />
              <Row
                label={t('leverage.rows.borrowerConcentration')}
                value={a.borrower_breaches ? a.borrower_breaches : t('leverage.values.none')}
                highlight={!!a.borrower_breaches}
              />
            </tbody>
          </table>
        </div>
      </div>

      {/* LMT panel */}
      <div className="rounded shadow-sm border p-3 space-y-2" style={panelStyle}>
        <h2 className="text-sm font-semibold uppercase tracking-wide bb-head" style={{ color: 'var(--text-secondary)' }}>
          {t('leverage.section.lmt')}
        </h2>
        <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
          {a.lmt_count === 1
            ? t('leverage.lmtText', { n: a.lmt_count })
            : t('leverage.lmtTextPlural', {
                n: a.lmt_count ?? '—',
                status: a.lmt_compliant ? t('leverage.lmtCompliant') : t('leverage.lmtNonCompliant'),
              })}
        </p>
        <div className="flex flex-wrap gap-2">
          {lmts.map((tool) => (
            <span
              key={tool}
              className="rounded-full px-3 py-1 text-xs font-semibold"
              style={{ background: 'var(--kpi-green-bg)', color: 'var(--kpi-green-text)', border: '1px solid var(--kpi-green-border)' }}
            >
              {tool}
            </span>
          ))}
        </div>
        <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
          <MetricTooltip id="swing_factor">Swing pricing</MetricTooltip> and{' '}
          <MetricTooltip id="adl_bps">Anti-Dilution Levy (ADL)</MetricTooltip> are pre-selected as anti-dilution tools
          under AIFMD II Art. 16(1)(a). Gates and suspensions are pre-selected as redemption deferral tools.
        </p>
      </div>

      {/* Regulatory basis */}
      <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
        {t('leverage.footer')}
      </p>
    </div>
  )
}
