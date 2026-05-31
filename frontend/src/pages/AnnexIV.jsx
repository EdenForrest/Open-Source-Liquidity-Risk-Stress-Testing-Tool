import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useAnalysis } from '../AnalysisContext'
import EmptyState from '../components/EmptyState'

const PERIODS = [
  '2026Q1', '2026Q2', '2026Q3', '2026Q4',
  '2026H1', '2026H2', '2026',
]

const ESMA_HORIZON_LABELS = {
  DAY_1:        '1 day',
  DAY_2_7:      '2–7 days',
  DAY_8_30:     '8–30 days',
  DAY_31_90:    '31–90 days',
  DAY_91_180:   '91–180 days',
  DAY_181_365:  '181–365 days',
  DAY_MORE_365: '> 365 days',
}

function SectionHeader({ children }) {
  return (
    <tr>
      <td colSpan={4} className="px-3 py-1.5 text-xs font-bold uppercase tracking-wide"
        style={{ background: 'var(--bg-surface)', color: 'var(--text-accent)', borderBottom: '1px solid var(--border)' }}>
        {children}
      </td>
    </tr>
  )
}

function DataRow({ label, value, highlight, indent }) {
  const bg = highlight === 'red' ? 'var(--kpi-red-bg)' : highlight === 'amber' ? 'var(--kpi-amber-bg)' : highlight === 'green' ? 'var(--kpi-green-bg)' : undefined
  const color = highlight === 'red' ? 'var(--kpi-red-text)' : highlight === 'amber' ? 'var(--kpi-amber-text)' : highlight === 'green' ? 'var(--kpi-green-text)' : 'var(--text-primary)'
  return (
    <tr style={bg ? { background: bg } : {}}>
      <td className="px-3 py-1.5 text-xs" style={{ color: 'var(--text-secondary)', paddingLeft: indent ? '1.5rem' : undefined }}>{label}</td>
      <td className="px-3 py-1.5 text-xs font-semibold text-right" style={{ color }}>{value ?? '—'}</td>
    </tr>
  )
}

function GapBadge({ passed }) {
  const { t } = useTranslation()
  return (
    <span className="px-1.5 py-0.5 rounded text-xs font-bold"
      style={passed
        ? { background: 'var(--kpi-green-bg)', color: 'var(--kpi-green-text)' }
        : { background: 'var(--kpi-red-bg)', color: 'var(--kpi-red-text)' }}>
      {passed ? t('annexIv.passed') : t('annexIv.failed')}
    </span>
  )
}

function pctFmt(v) {
  if (v == null) return '—'
  return (parseFloat(v) * 100).toFixed(2) + '%'
}

function leveragePct(v) {
  if (v == null) return '—'
  return (parseFloat(v) * 100).toFixed(1) + '%'
}

export default function AnnexIV() {
  const { runId, selectedPortfolio, status } = useAnalysis()
  const { t } = useTranslation()
  const [period, setPeriod] = useState('2026Q1')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const apiBase = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '') + '/api'

  useEffect(() => {
    if (!runId || status !== 'complete') {
      setData(null)
      return
    }
    setLoading(true)
    setError(null)
    const params = new URLSearchParams({ period })
    if (selectedPortfolio) params.set('portfolio', selectedPortfolio)
    fetch(`${apiBase}/run/${runId}/annex-iv?${params}`)
      .then((r) => {
        if (!r.ok) throw new Error(`Status ${r.status}`)
        return r.json()
      })
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [runId, selectedPortfolio, status, period])

  if (status !== 'complete') return <EmptyState />

  function buildDownloadUrl(fmt) {
    const params = new URLSearchParams({ period })
    if (selectedPortfolio) params.set('portfolio', selectedPortfolio)
    const endpoint = fmt === 'excel' ? 'annex-iv-excel' : fmt
    return `${apiBase}/run/${runId}/export/${endpoint}?${params}`
  }

  async function download(fmt) {
    const resp = await fetch(buildDownloadUrl(fmt))
    if (!resp.ok) {
      if (resp.status === 409) {
        alert(t('annexIv.metadataNotUploaded'))
        return
      }
      alert(t('annexIv.downloadFailed', { status: resp.status })); return
    }
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    const code = selectedPortfolio || 'portfolio'
    a.download = fmt === 'xml'
      ? `annex_iv_${code}_${period}.xml`
      : `annex_iv_${code}_${period}.xlsx`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  const panelStyle = { background: 'var(--bg-panel)', border: '1px solid var(--border)' }

  // Regulatory export (XML/Excel) is gated on uploaded AIFM/AIF/share-class
  // metadata. Preview always renders; export is blocked until ready.
  const exportBlocked = data?.annex_iv_ready === false

  return (
    <div className="p-3 space-y-3">

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>
            {t('annexIv.title')}
          </h1>
          <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
            {t('annexIv.subtitle')}
          </p>
        </div>

        {/* Controls */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex flex-col gap-0.5">
            <label className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>
              {t('annexIv.periodLabel')}
            </label>
            <select
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              className="rounded border px-2 py-1 text-xs"
              style={{ background: 'var(--bg-surface)', borderColor: 'var(--border)', color: 'var(--text-primary)' }}
            >
              {PERIODS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>

          <button
            onClick={() => download('xml')}
            disabled={exportBlocked}
            className="px-3 py-1.5 rounded text-xs font-semibold text-white mt-4"
            style={{ background: 'var(--text-accent)', cursor: exportBlocked ? 'not-allowed' : 'pointer', opacity: exportBlocked ? 0.5 : 1 }}
          >
            {t('annexIv.downloadXml')}
          </button>
          <button
            onClick={() => download('excel')}
            disabled={exportBlocked}
            className="px-3 py-1.5 rounded text-xs font-semibold mt-4"
            style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)', cursor: exportBlocked ? 'not-allowed' : 'pointer', opacity: exportBlocked ? 0.5 : 1 }}
          >
            {t('annexIv.downloadExcel')}
          </button>
        </div>
      </div>

      {exportBlocked && (
        <div className="rounded border px-3 py-2 text-xs"
          style={{ background: 'var(--kpi-amber-bg)', color: 'var(--kpi-amber-text)', borderColor: 'var(--border)' }}>
          {t('annexIv.exportDisabled')}
        </div>
      )}

      <p className="text-xs" style={{ color: 'var(--text-muted)' }}>{t('annexIv.periodNote')}</p>

      {loading && (
        <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>{t('annexIv.loading')}</p>
      )}
      {error && (
        <p className="text-xs" style={{ color: 'var(--kpi-red-text)' }}>{t('annexIv.error', { error })}</p>
      )}

      {data && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">

          {/* Gap analysis */}
          <div className="rounded border" style={panelStyle}>
            <div className="px-3 py-2 border-b" style={{ borderColor: 'var(--border)' }}>
              <h2 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                {t('annexIv.gaps')}
              </h2>
              <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>{t('annexIv.gapsDesc')}</p>
            </div>
            <div className="divide-y" style={{ borderColor: 'var(--border)' }}>
              {data.gaps && Object.entries(data.gaps).map(([key, failed]) => (
                <div key={key} className="flex items-center justify-between px-3 py-1.5">
                  <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                    {key.replace(/_/g, ' ')}
                  </span>
                  <GapBadge passed={!failed} />
                </div>
              ))}
            </div>
          </div>

          {/* AIF identification */}
          <div className="rounded border" style={panelStyle}>
            <div className="px-3 py-2 border-b" style={{ borderColor: 'var(--border)' }}>
              <h2 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                {t('annexIv.aifIdentification')}
              </h2>
            </div>
            <table className="w-full text-xs">
              <tbody>
                <DataRow label={t('annexIv.fundName')} value={data.aif?.name} />
                <DataRow label={t('annexIv.reportingDate')} value={data.aif?.reporting_date} />
                <DataRow label={t('annexIv.totalNav')} value={data.aif?.total_nav_eur != null ? `€${parseFloat(data.aif.total_nav_eur).toLocaleString()}` : '—'} />
                <DataRow label={t('annexIv.aifLei')} value={data.aif?.lei || '—'} highlight={!data.aif?.lei ? 'amber' : undefined} />
                <DataRow label={t('annexIv.aifmName')} value={data.aifm?.name || '—'} />
                <DataRow label={t('annexIv.aifmLei')} value={data.aifm?.lei || '—'} highlight={!data.aifm?.lei ? 'amber' : undefined} />
                <DataRow label={t('annexIv.reportingMemberState')} value={data.aifm?.reporting_member_state} />
                <DataRow label={t('annexIv.period')} value={`${data.period_type} (${data.period_start} – ${data.period_end})`} />
              </tbody>
            </table>
          </div>

          {/* Asset liquidity profile */}
          <div className="rounded border" style={panelStyle}>
            <div className="px-3 py-2 border-b" style={{ borderColor: 'var(--border)' }}>
              <h2 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                {t('annexIv.assetLiquidity')}
              </h2>
            </div>
            <table className="w-full text-xs">
              <thead>
                <tr style={{ background: 'var(--bg-surface)' }}>
                  <th className="px-3 py-1.5 text-left font-medium" style={{ color: 'var(--text-secondary)' }}>{t('annexIv.horizon')}</th>
                  <th className="px-3 py-1.5 text-right font-medium" style={{ color: 'var(--text-secondary)' }}>{t('annexIv.navPct')}</th>
                </tr>
              </thead>
              <tbody>
                {data.asset_liquidity_profile && Object.entries(data.asset_liquidity_profile).map(([hz, pct]) => (
                  <tr key={hz}>
                    <td className="px-3 py-1 text-xs" style={{ color: 'var(--text-secondary)' }}>{ESMA_HORIZON_LABELS[hz] ?? hz}</td>
                    <td className="px-3 py-1 text-xs font-semibold text-right" style={{ color: 'var(--text-primary)' }}>
                      {pctFmt(pct)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Leverage */}
          <div className="rounded border" style={panelStyle}>
            <div className="px-3 py-2 border-b" style={{ borderColor: 'var(--border)' }}>
              <h2 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                {t('annexIv.leverage')}
              </h2>
            </div>
            <table className="w-full text-xs">
              <tbody>
                <DataRow label={t('annexIv.grossLeverage')} value={leveragePct(data.leverage?.gross_leverage)} />
                <DataRow label={t('annexIv.commitmentLeverage')} value={leveragePct(data.leverage?.commitment_leverage)} />
                <DataRow label={t('annexIv.leverageCap')} value={leveragePct(data.leverage?.leverage_cap)} />
                <DataRow label={t('annexIv.capUtilization')} value={leveragePct(data.leverage?.cap_utilization_pct)} />
                <DataRow
                  label={t('annexIv.leverageBreach')}
                  value={data.leverage?.leverage_breach ? 'YES' : 'No'}
                  highlight={data.leverage?.leverage_breach ? 'red' : 'green'}
                />
              </tbody>
            </table>
          </div>

          {/* Special arrangements */}
          <div className="rounded border" style={panelStyle}>
            <div className="px-3 py-2 border-b" style={{ borderColor: 'var(--border)' }}>
              <h2 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                {t('annexIv.specialArrangements')}
              </h2>
            </div>
            <table className="w-full text-xs">
              <tbody>
                {data.special_arrangements && ['gate', 'suspension', 'swing_pricing', 'side_pocket'].map((tool) => (
                  <DataRow
                    key={tool}
                    label={tool.replace(/_/g, ' ')}
                    value={data.special_arrangements[tool] ? t('annexIv.active') : t('annexIv.inactive')}
                    highlight={data.special_arrangements[tool] ? 'green' : undefined}
                  />
                ))}
                <DataRow label={t('annexIv.lmtCount')} value={data.special_arrangements?.lmt_count ?? '—'} />
                <DataRow
                  label={t('annexIv.aifmdCompliant')}
                  value={data.special_arrangements?.lmt_compliant ? t('common.yes') : t('common.no')}
                  highlight={data.special_arrangements?.lmt_compliant ? 'green' : 'red'}
                />
              </tbody>
            </table>
          </div>

          {/* Investor liquidity profile */}
          <div className="rounded border" style={panelStyle}>
            <div className="px-3 py-2 border-b" style={{ borderColor: 'var(--border)' }}>
              <h2 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                {t('annexIv.investorLiquidity')}
              </h2>
            </div>
            <table className="w-full text-xs">
              <tbody>
                <DataRow label={t('annexIv.minNoticeDays')} value={data.investor_liquidity_profile?.min_notice_period_days != null ? `${data.investor_liquidity_profile.min_notice_period_days} ${t('annexIv.days')}` : '—'} />
                <DataRow label={t('annexIv.redemptionFrequency')} value={data.investor_liquidity_profile?.redemption_frequency} />
                <DataRow
                  label={t('annexIv.dataComplete')}
                  value={data.investor_liquidity_profile?.data_complete ? t('common.yes') : t('annexIv.usingDefaults')}
                  highlight={data.investor_liquidity_profile?.data_complete ? 'green' : 'amber'}
                />
              </tbody>
            </table>
          </div>

          {/* Geographical concentration */}
          <div className="rounded border" style={panelStyle}>
            <div className="px-3 py-2 border-b" style={{ borderColor: 'var(--border)' }}>
              <h2 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                {t('annexIv.geoConcentration')}
              </h2>
            </div>
            <table className="w-full text-xs">
              <tbody>
                <DataRow label={t('annexIv.euPct')} value={pctFmt(data.geographical_concentration?.eu_pct)} />
                <DataRow label={t('annexIv.nonEuPct')} value={pctFmt(data.geographical_concentration?.non_eu_pct)} />
              </tbody>
            </table>
            {data.geographical_concentration?.top_countries?.length > 0 && (
              <table className="w-full text-xs mt-1">
                <thead>
                  <tr style={{ background: 'var(--bg-surface)' }}>
                    <th className="px-3 py-1 text-left font-medium" style={{ color: 'var(--text-secondary)' }}>{t('annexIv.country')}</th>
                    <th className="px-3 py-1 text-right font-medium" style={{ color: 'var(--text-secondary)' }}>{t('annexIv.navPct')}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.geographical_concentration.top_countries.map((c, i) => (
                    <tr key={i}>
                      <td className="px-3 py-1 text-xs" style={{ color: 'var(--text-secondary)' }}>{c.country_code}</td>
                      <td className="px-3 py-1 text-xs font-semibold text-right" style={{ color: 'var(--text-primary)' }}>{pctFmt(c.nav_pct)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Principal markets */}
          <div className="rounded border" style={panelStyle}>
            <div className="px-3 py-2 border-b" style={{ borderColor: 'var(--border)' }}>
              <h2 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                {t('annexIv.principalMarkets')}
              </h2>
            </div>
            <table className="w-full text-xs">
              <thead>
                <tr style={{ background: 'var(--bg-surface)' }}>
                  <th className="px-3 py-1 text-left font-medium" style={{ color: 'var(--text-secondary)' }}>{t('annexIv.country')}</th>
                  <th className="px-3 py-1 text-right font-medium" style={{ color: 'var(--text-secondary)' }}>{t('annexIv.navPct')}</th>
                </tr>
              </thead>
              <tbody>
                {(data.principal_markets ?? []).map((m, i) => (
                  <tr key={i} style={i % 2 === 1 ? { background: 'var(--bg-surface)' } : {}}>
                    <td className="px-3 py-1 text-xs" style={{ color: 'var(--text-secondary)' }}>{m.country_code}</td>
                    <td className="px-3 py-1 text-xs font-semibold text-right" style={{ color: 'var(--text-primary)' }}>{pctFmt(m.nav_pct)}</td>
                  </tr>
                ))}
                {(data.principal_markets ?? []).length === 0 && (
                  <tr><td colSpan={2} className="px-3 py-2 text-xs" style={{ color: 'var(--text-muted)' }}>{t('annexIv.noCountryData')}</td></tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Principal instruments */}
          <div className="rounded border lg:col-span-2" style={panelStyle}>
            <div className="px-3 py-2 border-b" style={{ borderColor: 'var(--border)' }}>
              <h2 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                {t('annexIv.principalInstruments')}
              </h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr style={{ background: 'var(--bg-surface)' }}>
                    <th className="px-3 py-1.5 text-left font-medium" style={{ color: 'var(--text-secondary)' }}>{t('annexIv.isin')}</th>
                    <th className="px-3 py-1.5 text-left font-medium" style={{ color: 'var(--text-secondary)' }}>{t('annexIv.name')}</th>
                    <th className="px-3 py-1.5 text-left font-medium" style={{ color: 'var(--text-secondary)' }}>{t('annexIv.assetClass')}</th>
                    <th className="px-3 py-1.5 text-left font-medium" style={{ color: 'var(--text-secondary)' }}>{t('annexIv.bucket')}</th>
                    <th className="px-3 py-1.5 text-right font-medium" style={{ color: 'var(--text-secondary)' }}>{t('annexIv.navPct')}</th>
                  </tr>
                </thead>
                <tbody>
                  {(data.principal_instruments ?? []).map((inst, i) => (
                    <tr key={i} style={i % 2 === 1 ? { background: 'var(--bg-surface)' } : {}}>
                      <td className="px-3 py-1 font-mono text-xs" style={{ color: 'var(--text-secondary)' }}>{inst.isin || '—'}</td>
                      <td className="px-3 py-1 text-xs" style={{ color: 'var(--text-primary)' }}>{inst.name || '—'}</td>
                      <td className="px-3 py-1 text-xs" style={{ color: 'var(--text-secondary)' }}>{inst.asset_class}</td>
                      <td className="px-3 py-1 text-xs" style={{ color: 'var(--text-secondary)' }}>{inst.bucket}</td>
                      <td className="px-3 py-1 text-xs font-semibold text-right" style={{ color: 'var(--text-primary)' }}>{pctFmt(inst.nav_pct)}</td>
                    </tr>
                  ))}
                  {(data.principal_instruments ?? []).length === 0 && (
                    <tr><td colSpan={5} className="px-3 py-2 text-xs" style={{ color: 'var(--text-muted)' }}>{t('annexIv.noInstruments')}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

        </div>
      )}
    </div>
  )
}
