import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAnalysis } from '../AnalysisContext'
import EmptyState from '../components/EmptyState'
import StatusBanner from '../components/StatusBanner'

// Checks that matter most — regulatory filings, fund-level reconciliation, compliance
const CRITICAL_CHECKS = new Set([
  'NAV vs position sum (exact reconciliation)',
  'Waterfall nav_before = total NAV',
  'LCR T+1 matches ladder (T+0 + T+1)',
  'LCR T+3 matches ladder (T+0 + T+1 + T+3)',
  'LCR T+7 matches ladder (T+0 through T+7)',
  'Illiquid % matches ladder >T+7 bucket',
  'Redemption amounts = position sum × scenario%',
  'Shortfall = max(0, redemption − liquidity_available)',
  'LMT configuration declared (≥2 tools, AIFMD II Art. 16)',
  'AIF LEI present',
  'AIF identification complete',
  'Leverage computed',
  'All stress nav_before values = position sum',
  'Stress result count matches scenario metadata',
])

// Display order for the grouped sections
const SECTION_META = [
  { key: 'critical', label: 'Critical', color: 'var(--kpi-red-text)', subtle: 'color-mix(in srgb, var(--kpi-red-text) 8%, transparent)' },
  { key: 'warning', label: 'Warnings', color: 'var(--kpi-amber, #d97706)', subtle: 'color-mix(in srgb, #d97706 8%, transparent)' },
  { key: 'pass', label: 'Passing', color: 'var(--kpi-green-text)', subtle: 'transparent' },
]

// Category groupings — determines which section non-critical checks land in
const REGULATORY_CATEGORIES = new Set(['Annex IV', 'Reconciliation'])
const ANALYTICAL_CATEGORIES = new Set(['Stress', 'Redemption', 'Liquidity Metrics', 'Liquidity Ladder', 'Waterfall'])

function PassIcon({ size = 15 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" style={{ color: 'var(--kpi-green-text)', flexShrink: 0 }}>
      <circle cx="8" cy="8" r="7" />
      <polyline points="5,8 7,10 11,6" />
    </svg>
  )
}

function FailIcon({ size = 15 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" style={{ color: 'var(--kpi-red-text)', flexShrink: 0 }}>
      <circle cx="8" cy="8" r="7" />
      <line x1="5.5" y1="5.5" x2="10.5" y2="10.5" />
      <line x1="10.5" y1="5.5" x2="5.5" y2="10.5" />
    </svg>
  )
}

function WarnIcon({ size = 15 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="#d97706" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
      <path d="M8 2L14.5 13H1.5L8 2Z" />
      <line x1="8" y1="7" x2="8" y2="10" />
      <circle cx="8" cy="12" r="0.5" fill="#d97706" />
    </svg>
  )
}

function ChevronIcon({ open }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" style={{ transition: 'transform 0.15s', transform: open ? 'rotate(90deg)' : 'rotate(0deg)', flexShrink: 0 }}>
      <polyline points="4,3 10,7 4,11" />
    </svg>
  )
}

function CheckRow({ check, isCritical }) {
  const isPass = check.passed
  return (
    <tr style={{
      borderBottom: '1px solid var(--border)',
      background: isPass ? 'transparent' : isCritical
        ? 'color-mix(in srgb, var(--kpi-red-text) 6%, transparent)'
        : 'color-mix(in srgb, #d97706 5%, transparent)',
    }}>
      <td className="px-3 py-1.5 w-5" style={{ verticalAlign: 'middle' }}>
        {isPass ? <PassIcon /> : isCritical ? <FailIcon /> : <WarnIcon />}
      </td>
      <td className="px-2 py-1.5" style={{ color: 'var(--text-primary)', fontSize: '0.8rem', verticalAlign: 'middle' }}>
        <span className="font-medium">{check.name}</span>
        <span className="ml-2" style={{ color: 'var(--text-muted)', fontSize: '0.72rem' }}>
          {check.category}
        </span>
      </td>
      <td className="px-3 py-1.5 text-right" style={{ color: isPass ? 'var(--text-muted)' : isCritical ? 'var(--kpi-red-text)' : '#d97706', fontSize: '0.75rem', verticalAlign: 'middle', maxWidth: '38ch', wordBreak: 'break-word' }}>
        {check.message}
      </td>
    </tr>
  )
}

function CollapsibleSection({ label, checks, criticalFails, defaultOpen = false }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(defaultOpen)
  const failed = checks.filter(c => !c.passed)
  const passed = checks.filter(c => c.passed)

  if (checks.length === 0) return null

  return (
    <div className="rounded border overflow-hidden" style={{ background: 'var(--bg-panel)', borderColor: 'var(--border)' }}>
      <button
        className="w-full px-3 py-2 flex items-center gap-2 text-left"
        style={{ background: 'var(--bg-surface)', borderBottom: open ? '1px solid var(--border)' : 'none', cursor: 'pointer' }}
        onClick={() => setOpen(o => !o)}
      >
        <ChevronIcon open={open} />
        <span className="text-sm font-semibold flex-1" style={{ color: 'var(--text-primary)' }}>{label}</span>
        <div className="flex items-center gap-2 text-xs font-semibold tabular-nums">
          {failed.length > 0 && (
            <span style={{ color: 'var(--kpi-red-text)' }}>{t('validation.failed', { count: failed.length })}</span>
          )}
          <span style={{ color: 'var(--text-muted)' }}>{t('validation.passed', { count: passed.length })}/{checks.length}</span>
        </div>
      </button>

      {open && (
        <table className="w-full">
          <tbody>
            {checks.map((check, i) => (
              <CheckRow key={i} check={check} isCritical={criticalFails} />
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

export default function Validation() {
  const { t } = useTranslation()
  const { data, error } = useAnalysis()
  const v = data?.validation
  if (error) return <StatusBanner />
  if (!v) return <EmptyState />

  const checks = v.checks || []

  // Partition: failures first by criticality, then warnings, then all passing
  const criticalFails = []
  const warningFails = []
  const allPassing = []

  for (const check of checks) {
    if (check.passed) {
      allPassing.push(check)
    } else if (CRITICAL_CHECKS.has(check.name) || REGULATORY_CATEGORIES.has(check.category)) {
      criticalFails.push(check)
    } else {
      warningFails.push(check)
    }
  }

  const totalFailed = checks.filter(c => !c.passed).length
  const allOk = totalFailed === 0

  // Group passing checks by category for the collapsible passing section
  const passingByCategory = {}
  for (const check of allPassing) {
    if (!passingByCategory[check.category]) passingByCategory[check.category] = []
    passingByCategory[check.category].push(check)
  }

  return (
    <div className="p-3 space-y-3">
      {/* Header row */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>{t('validation.title')}</h1>
          <p className="text-sm mt-0.5" style={{ color: 'var(--text-secondary)' }}>
            {t('validation.subtitle')}
          </p>
        </div>
        <div className="rounded border px-4 py-2.5 shrink-0 text-center" style={{ background: 'var(--bg-panel)', borderColor: 'var(--border)' }}>
          <div className="text-2xl font-bold tabular-nums bb-num" style={{ color: allOk ? 'var(--kpi-green-text)' : 'var(--kpi-red-text)' }}>
            {v.passed}/{v.total}
          </div>
          <div className="text-xs mt-0.5" style={{ color: 'var(--text-secondary)' }}>
            {allOk ? t('validation.allPassedShort') : t('validation.someFailedShort', { count: totalFailed })}
          </div>
        </div>
      </div>

      {/* Critical failures — always visible, no collapse */}
      {criticalFails.length > 0 && (
        <div className="rounded border overflow-hidden" style={{ background: 'var(--bg-panel)', borderColor: 'var(--kpi-red-text)' }}>
          <div className="px-3 py-2 flex items-center gap-2" style={{ background: 'color-mix(in srgb, var(--kpi-red-text) 10%, var(--bg-surface))', borderBottom: '1px solid var(--border)' }}>
            <FailIcon size={14} />
            <span className="text-sm font-semibold" style={{ color: 'var(--kpi-red-text)' }}>
              {t('validation.criticalHeader', { count: criticalFails.length })}
            </span>
          </div>
          <table className="w-full">
            <tbody>
              {criticalFails.map((check, i) => (
                <CheckRow key={i} check={check} isCritical={true} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Warning failures — collapsible, open by default */}
      {warningFails.length > 0 && (
        <CollapsibleSection
          label={t('validation.warningsHeader', { count: warningFails.length })}
          checks={warningFails}
          criticalFails={false}
          defaultOpen={true}
        />
      )}

      {/* All passing — grouped by category, collapsed by default */}
      {allPassing.length > 0 && (
        <div className="rounded border overflow-hidden" style={{ background: 'var(--bg-panel)', borderColor: 'var(--border)' }}>
          <CollapsibleSummary
            allPassing={allPassing}
            byCategory={passingByCategory}
            total={v.total}
          />
        </div>
      )}

      {/* All clear state */}
      {allOk && (
        <div className="rounded border px-4 py-3 flex items-center gap-3" style={{ background: 'color-mix(in srgb, var(--kpi-green-text) 8%, var(--bg-panel))', borderColor: 'var(--kpi-green-text)' }}>
          <PassIcon size={18} />
          <span className="text-sm font-semibold" style={{ color: 'var(--kpi-green-text)' }}>{t('validation.allPassed', { total: v.total })}</span>
        </div>
      )}
    </div>
  )
}

function CollapsibleSummary({ allPassing, byCategory, total }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [expandedCats, setExpandedCats] = useState({})

  const toggleCat = (cat) => setExpandedCats(prev => ({ ...prev, [cat]: !prev[cat] }))

  const categoryOrder = [
    'Reconciliation', 'Annex IV', 'Portfolio', 'Liquidity Metrics',
    'Liquidity Ladder', 'Redemption', 'Stress', 'Waterfall', 'Market Data',
  ]
  const orderedCats = [
    ...categoryOrder.filter(c => byCategory[c]),
    ...Object.keys(byCategory).filter(c => !categoryOrder.includes(c)),
  ]

  return (
    <>
      <button
        className="w-full px-3 py-2 flex items-center gap-2 text-left"
        style={{ background: 'var(--bg-surface)', borderBottom: open ? '1px solid var(--border)' : 'none', cursor: 'pointer' }}
        onClick={() => setOpen(o => !o)}
      >
        <ChevronIcon open={open} />
        <span className="text-sm font-semibold flex-1" style={{ color: 'var(--text-primary)' }}>{t('validation.passingHeader')}</span>
        <span className="text-xs font-semibold tabular-nums" style={{ color: 'var(--kpi-green-text)' }}>
          {t('validation.passed', { count: allPassing.length })}/{total}
        </span>
      </button>

      {open && (
        <div className="divide-y" style={{ borderTop: '1px solid var(--border)' }}>
          {orderedCats.map(cat => {
            const catChecks = byCategory[cat] || []
            const catOpen = expandedCats[cat]
            return (
              <div key={cat}>
                <button
                  className="w-full px-4 py-1.5 flex items-center gap-2 text-left"
                  style={{ background: 'transparent', cursor: 'pointer' }}
                  onClick={() => toggleCat(cat)}
                >
                  <ChevronIcon open={catOpen} />
                  <span className="text-xs font-semibold flex-1" style={{ color: 'var(--text-secondary)' }}>{cat}</span>
                  <span className="text-xs tabular-nums" style={{ color: 'var(--kpi-green-text)' }}>
                    {t('validation.passed', { count: catChecks.length })}
                  </span>
                </button>
                {catOpen && (
                  <table className="w-full">
                    <tbody>
                      {catChecks.map((check, i) => (
                        <CheckRow key={i} check={check} isCritical={false} />
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )
          })}
        </div>
      )}
    </>
  )
}
