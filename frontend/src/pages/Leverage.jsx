import { useAnalysis } from '../AnalysisContext'
import KPICard from '../components/KPICard'
import EmptyState from '../components/EmptyState'
import StatusBanner from '../components/StatusBanner'
import MetricTooltip from '../components/MetricTooltip'
import { pct, fmtEur } from '../utils/formatters'

function Row({ label, value, sub, highlight }) {
  return (
    <tr style={highlight ? { background: 'var(--kpi-red-bg)' } : {}}>
      <td className="px-4 py-2.5 text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>{label}</td>
      <td className="px-4 py-2.5 text-sm font-semibold text-right" style={{ color: highlight ? 'var(--kpi-red-text)' : 'var(--text-primary)' }}>
        {value}
        {sub && <span className="ml-2 text-xs font-normal opacity-60">{sub}</span>}
      </td>
    </tr>
  )
}

export default function Leverage() {
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
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>
          AIFMD II Leverage — {liq?.fund_name ?? ''}
        </h1>
        <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
          {a.regulatory_basis}
        </p>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KPICard
          label={<MetricTooltip id="gross_leverage">Gross Leverage</MetricTooltip>}
          value={grossPct}
          sub={`cap ${capPct}`}
          color={a.leverage_breach ? 'red' : 'slate'}
          alert={a.leverage_breach}
        />
        <KPICard
          label="Commitment Leverage"
          value={commitPct}
          color="slate"
        />
        <KPICard
          label={<MetricTooltip id="cap_utilization">Cap Utilization</MetricTooltip>}
          value={utilizationPct}
          sub={`headroom ${headroomPct}`}
          color={a.leverage_breach ? 'red' : (parseFloat(utilizationPct) > 80 ? 'amber' : 'green')}
        />
        <KPICard
          label={<MetricTooltip id="lmt_count">LMTs Pre-selected</MetricTooltip>}
          value={a.lmt_count ?? '—'}
          sub={a.lmt_compliant ? 'compliant' : 'insufficient'}
          color={a.lmt_compliant ? 'green' : 'red'}
        />
      </div>

      {/* Warnings */}
      {warnings.length > 0 && (
        <div className="rounded-xl border p-4 space-y-1" style={{ background: 'var(--kpi-amber-bg)', borderColor: 'var(--kpi-amber-border)' }}>
          {warnings.map((w, i) => (
            <p key={i} className="text-sm" style={{ color: 'var(--kpi-amber-text)' }}>⚠ {w}</p>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Leverage detail table */}
        <div className="rounded-xl shadow-sm border overflow-hidden" style={panelStyle}>
          <h2 className="text-sm font-semibold uppercase tracking-wide px-4 py-3" style={{ ...surfaceStyle, color: 'var(--text-secondary)' }}>
            Leverage Metrics
          </h2>
          <table className="w-full">
            <tbody>
              <Row label="Gross Leverage (Art. 7 CDR 231/2013)" value={grossPct} highlight={a.leverage_breach} />
              <Row label="Commitment Leverage" value={commitPct} />
              <Row label="Applicable Cap" value={capPct} />
              <Row label="Cap Headroom" value={headroomPct} />
              <Row label="Cap Utilization" value={utilizationPct} />
              {liq?.total_nav_eur != null && (
                <Row label="NAV" value={fmtEur(liq.total_nav_eur)} />
              )}
            </tbody>
          </table>
        </div>

        {/* Loan origination & constraints */}
        <div className="rounded-xl shadow-sm border overflow-hidden" style={panelStyle}>
          <h2 className="text-sm font-semibold uppercase tracking-wide px-4 py-3" style={{ ...surfaceStyle, color: 'var(--text-secondary)' }}>
            Loan Origination AIF
          </h2>
          <table className="w-full">
            <tbody>
              <Row
                label="Loan Origination AIF Regime"
                value={a.is_loan_origination_aif ? 'YES — applies' : 'No'}
                highlight={a.is_loan_origination_aif}
              />
              <Row label="Loans % NAV" value={pct(a.loan_pct_nav)} sub="threshold 50%" />
              <Row
                label="Risk Retention (≥5%)"
                value={a.risk_retention_ok ? 'OK' : 'BREACH'}
                highlight={!a.risk_retention_ok}
              />
              <Row
                label="Borrower Concentration Breaches"
                value={a.borrower_breaches ? a.borrower_breaches : 'None'}
                highlight={!!a.borrower_breaches}
              />
            </tbody>
          </table>
        </div>
      </div>

      {/* LMT panel */}
      <div className="rounded-xl shadow-sm border p-5 space-y-3" style={panelStyle}>
        <h2 className="text-sm font-semibold uppercase tracking-wide" style={{ color: 'var(--text-secondary)' }}>
          Liquidity Management Tools — AIFMD II Art. 16 &amp; Annex V
        </h2>
        <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
          At least 2 tools must be pre-selected in the fund prospectus (excluding side pockets).
          The fund has <strong>{a.lmt_count ?? '—'}</strong> tool{a.lmt_count !== 1 ? 's' : ''} pre-selected —{' '}
          <span style={{ color: a.lmt_compliant ? 'var(--kpi-green-text)' : 'var(--kpi-red-text)', fontWeight: 600 }}>
            {a.lmt_compliant ? 'compliant' : 'non-compliant'}
          </span>.
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
        Leverage computed per AIFMD II (Directive (EU) 2024/927), Article 15 and Commission Delegated Regulation (EU) 231/2013, Article 7 (Gross Method) and Article 8 (Commitment Method).
      </p>
    </div>
  )
}
