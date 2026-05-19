import { useAnalysis } from '../AnalysisContext'
import EmptyState from '../components/EmptyState'
import StatusBanner from '../components/StatusBanner'

const CATEGORY_ORDER = [
  'Portfolio',
  'Reconciliation',
  'Market Data',
  'Liquidity Metrics',
  'Liquidity Ladder',
  'Redemption',
  'Stress',
  'Waterfall',
]

function PassIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: 'var(--kpi-green-text)', flexShrink: 0 }}>
      <circle cx="8" cy="8" r="7" />
      <polyline points="5,8 7,10 11,6" />
    </svg>
  )
}

function FailIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: 'var(--kpi-red-text)', flexShrink: 0 }}>
      <circle cx="8" cy="8" r="7" />
      <line x1="5.5" y1="5.5" x2="10.5" y2="10.5" />
      <line x1="10.5" y1="5.5" x2="5.5" y2="10.5" />
    </svg>
  )
}

function ScoreBadge({ passed, total }) {
  const failed = total - passed
  const allPassed = failed === 0
  return (
    <div className="flex items-center gap-3">
      <span className="text-3xl font-bold tabular-nums" style={{ color: allPassed ? 'var(--kpi-green-text)' : 'var(--kpi-red-text)' }}>
        {passed}/{total}
      </span>
      <div className="text-sm" style={{ color: 'var(--text-secondary)' }}>
        <div style={{ color: 'var(--kpi-green-text)' }} className="font-semibold">{passed} passed</div>
        {failed > 0 && <div style={{ color: 'var(--kpi-red-text)' }} className="font-semibold">{failed} failed</div>}
      </div>
    </div>
  )
}

function CategorySection({ category, checks }) {
  const passed = checks.filter(c => c.passed).length
  const allOk = passed === checks.length

  return (
    <div className="rounded-xl border overflow-hidden" style={{ background: 'var(--bg-panel)', borderColor: 'var(--border)' }}>
      <div className="px-5 py-3 flex items-center justify-between" style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg-surface)' }}>
        <h2 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>{category}</h2>
        <span className="text-xs font-semibold tabular-nums" style={{ color: allOk ? 'var(--kpi-green-text)' : 'var(--kpi-red-text)' }}>
          {passed}/{checks.length}
        </span>
      </div>
      <table className="w-full text-sm">
        <tbody>
          {checks.map((check, i) => (
            <tr
              key={i}
              style={{
                borderBottom: i < checks.length - 1 ? '1px solid var(--border)' : 'none',
                background: check.passed ? 'transparent' : 'color-mix(in srgb, var(--kpi-red-text) 6%, transparent)',
              }}
            >
              <td className="px-4 py-2.5 w-6">
                {check.passed ? <PassIcon /> : <FailIcon />}
              </td>
              <td className="px-2 py-2.5 font-medium whitespace-nowrap" style={{ color: 'var(--text-primary)' }}>
                {check.name}
              </td>
              <td className="px-4 py-2.5 text-right" style={{ color: check.passed ? 'var(--text-muted)' : 'var(--kpi-red-text)' }}>
                {check.message}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function Validation() {
  const { data, error } = useAnalysis()
  const v = data?.validation
  if (error) return <StatusBanner />
  if (!v) return <EmptyState />

  const byCategory = {}
  for (const check of v.checks) {
    if (!byCategory[check.category]) byCategory[check.category] = []
    byCategory[check.category].push(check)
  }

  const orderedCategories = [
    ...CATEGORY_ORDER.filter(c => byCategory[c]),
    ...Object.keys(byCategory).filter(c => !CATEGORY_ORDER.includes(c)),
  ]

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>Validation Report</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--text-secondary)' }}>
            Business-logic integrity checks on the computed pipeline output
          </p>
        </div>
        <div className="rounded-xl border px-5 py-4 shrink-0" style={{ background: 'var(--bg-panel)', borderColor: 'var(--border)' }}>
          <ScoreBadge passed={v.passed} total={v.total} />
        </div>
      </div>

      {orderedCategories.map(cat => (
        <CategorySection key={cat} category={cat} checks={byCategory[cat]} />
      ))}
    </div>
  )
}
