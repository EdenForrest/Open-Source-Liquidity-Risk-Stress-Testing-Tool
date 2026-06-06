import { useTranslation } from 'react-i18next'
import { useAnalysis } from '../AnalysisContext'
import EmptyState from '../components/EmptyState'
import StatusBanner from '../components/StatusBanner'
import { pct, eur } from '../utils/formatters'

function buildNarrative(t, { liq, stress, redemption, waterfall, aifmd2 }) {
  if (!liq) return ''
  const m = liq.liquidity_metrics
  const stressResults = stress?.stress_results || []
  const worst = stressResults.length
    ? stressResults.reduce((a, b) => (b.nav_impact_pct < a.nav_impact_pct ? b : a), stressResults[0])
    : null
  const normalRed = redemption?.redemption_results || []
  const wfMeta = waterfall?.waterfall_meta || {}

  const flagLine = m.breach_flag
    ? t('riskStory.statusBreach')
    : m.warning_flag
    ? t('riskStory.statusWarning')
    : t('riskStory.statusOk')

  const sep = '──────────────────────────────────────────'

  const lines = [
    t('riskStory.header', { fundName: liq.fund_name }),
    `${t('riskStory.reportingDate', { date: liq.reporting_date })}   |   ${t('riskStory.totalNav', { nav: eur(liq.total_nav_eur) })}`,
    '',
    flagLine,
    '',
    sep,
    t('riskStory.section1'),
    sep,
    t('riskStory.lcrT1', { value: pct(m.lcr_t1) }),
    t('riskStory.lcrT3', { value: pct(m.lcr_t3) }),
    t('riskStory.lcrT7', { value: pct(m.lcr_t7) }),
    t('riskStory.illiquid', { value: pct(m.illiquid_pct) }),
    t('riskStory.days50', { value: m.days_to_50pct?.toFixed(1) ?? '—' }),
    t('riskStory.days75', { value: m.days_to_75pct?.toFixed(1) ?? '—' }),
    t('riskStory.days90', { value: m.days_to_90pct?.toFixed(1) ?? '—' }),
    t('riskStory.top10', { value: pct(m.top10_concentration) }),
    t('riskStory.liqVsConc', { value: m.liquidity_vs_concentration?.toFixed(2) ?? '—' }),
    '',
    sep,
    t('riskStory.section2'),
    sep,
    t('riskStory.stressScenarios', { count: stressResults.length }),
    worst
      ? [
          t('riskStory.worstCase', { name: worst.scenario_name }),
          t('riskStory.navImpact', { pct: pct(worst.nav_impact_pct), eur: eur(worst.nav_impact_eur) }),
          t('riskStory.equityLoss', { value: eur(worst.equity_loss_eur) }),
          t('riskStory.creditLoss', { value: eur(worst.credit_loss_eur) }),
          t('riskStory.liqAfterShock', { after: pct(worst.liquid_pct_after), before: pct(worst.liquid_pct_before) }),
          t('riskStory.daysToLiq', { value: worst.time_to_liquidate_days?.toFixed(1) ?? '—' }),
          t('riskStory.canMeetRedemption', { value: worst.can_meet_redemption ? t('riskStory.canMeetYes') : t('riskStory.canMeetNo') }),
        ].join('\n')
      : t('riskStory.noStress'),
    '',
    sep,
    t('riskStory.section3'),
    sep,
    normalRed.length
      ? normalRed.map(r =>
          t('riskStory.redemptionLine', {
            pct: pct(r.scenario_pct),
            liq: pct(r.liquidity_available_pct),
            shortfall: r.shortfall_eur > 0 ? eur(r.shortfall_eur) : t('riskStory.shortfallNone'),
            t1: r.can_meet_t1 ? t('riskStory.t1Met') : t('riskStory.t1NotMet'),
            gate: r.gate_triggered ? t('riskStory.gateTriggered') : t('riskStory.gateNo'),
          })
        ).join('\n')
      : t('riskStory.noRedemption'),
    '',
    sep,
    t('riskStory.section4'),
    sep,
    t('riskStory.wfTarget', { value: eur(wfMeta.target_eur) }),
    t('riskStory.wfProceeds', { value: eur(wfMeta.total_proceeds_eur) }),
    t('riskStory.wfTargetMet', { value: wfMeta.target_met ? t('riskStory.wfTargetMetYes') : t('riskStory.wfTargetMetNo') }),
    t('riskStory.wfDays', { value: wfMeta.days_to_target?.toFixed(1) ?? '—' }),
    t('riskStory.wfShortfall', { value: eur(wfMeta.residual_shortfall_eur) }),
    t('riskStory.wfNavImpact', { value: wfMeta.nav_impact_pct != null ? (wfMeta.nav_impact_pct * 100).toFixed(2) + '%' : '—' }),
    '',
    sep,
    t('riskStory.section5'),
    sep,
    aifmd2
      ? [
          t('riskStory.aifmdBasis', { value: aifmd2.regulatory_basis }),
          t('riskStory.aifmdGross', {
            value: aifmd2.gross_leverage != null ? (aifmd2.gross_leverage * 100).toFixed(1) + '%' : '—',
            cap: aifmd2.leverage_cap != null ? (aifmd2.leverage_cap * 100).toFixed(0) + '%' : '—',
          }),
          t('riskStory.aifmdCommit', { value: aifmd2.commitment_leverage != null ? (aifmd2.commitment_leverage * 100).toFixed(1) + '%' : '—' }),
          t('riskStory.aifmdBreach', { value: aifmd2.leverage_breach ? t('riskStory.aifmdBreachYes') : t('riskStory.aifmdBreachNo') }),
          t('riskStory.aifmdLoan', { value: aifmd2.is_loan_origination_aif
            ? t('riskStory.aifmdLoanYes', { pct: (aifmd2.loan_pct_nav * 100).toFixed(1) })
            : t('riskStory.aifmdLoanNo') }),
          t('riskStory.aifmdRetention', { value: aifmd2.risk_retention_ok ? t('riskStory.aifmdRetentionOk') : t('riskStory.aifmdRetentionBreach') }),
          t('riskStory.aifmdBorrower', { value: aifmd2.borrower_breaches || t('common.na') }),
          t('riskStory.aifmdLmts', {
            tools: Array.isArray(aifmd2.lmt_preselected) ? aifmd2.lmt_preselected.join(', ') : (aifmd2.lmt_preselected || '—'),
            count: aifmd2.lmt_count ?? '—',
            status: aifmd2.lmt_compliant ? t('riskStory.aifmdLmtCompliant') : t('riskStory.aifmdLmtNonCompliant'),
          }),
          aifmd2.warnings ? t('riskStory.aifmdWarnings', { value: aifmd2.warnings }) : '',
        ].filter(Boolean).join('\n')
      : t('riskStory.aifmdNoData'),
    '',
    sep,
    t('riskStory.footer'),
    '',
  ]

  return lines.join('\n')
}

export default function RiskStory() {
  const { t } = useTranslation()
  const { data, error } = useAnalysis()
  const liq = data?.liquidity
  if (error) return <StatusBanner />
  if (!liq) return <EmptyState />

  const narrative = buildNarrative(t, {
    liq,
    stress: data.stress,
    redemption: data.redemption,
    waterfall: data.waterfall,
    aifmd2: data.aifmd2,
  })

  async function copy() {
    try {
      await navigator.clipboard.writeText(narrative)
    } catch {
      alert(t('riskStory.copyError'))
    }
  }

  function downloadJSON() {
    try {
      const blob = new Blob([JSON.stringify({ ...data }, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = 'liquidity_report.json'; a.click()
      URL.revokeObjectURL(url)
    } catch {
      alert(t('riskStory.downloadError'))
    }
  }

  return (
    <div className="p-3 space-y-3">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>{t('riskStory.title')}</h1>
        <div className="flex gap-2">
          <button
            onClick={copy}
            className="rounded border px-3 py-1 text-xs transition-colors"
            style={{ borderColor: 'var(--border)', color: 'var(--text-secondary)', background: 'var(--bg-surface)' }}
          >
            {t('riskStory.copyText')}
          </button>
          <button
            onClick={downloadJSON}
            className="rounded px-3 py-1 text-xs font-semibold text-white transition-colors"
            style={{ background: 'var(--text-accent)' }}
          >
            {t('riskStory.downloadJson')}
          </button>
        </div>
      </div>

      <pre className="rounded border text-xs leading-relaxed overflow-auto whitespace-pre-wrap font-mono p-4"
        style={{ background: 'var(--bg-panel)', borderColor: 'var(--border)', color: 'var(--kpi-green-text)' }}>
        {narrative}
      </pre>
    </div>
  )
}
