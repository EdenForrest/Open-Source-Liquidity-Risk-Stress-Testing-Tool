import { useAnalysis } from '../AnalysisContext'
import EmptyState from '../components/EmptyState'
import MetricTooltip from '../components/MetricTooltip'

function pct(v) { return v != null ? (v * 100).toFixed(1) + '%' : '—' }
function eur(v) {
  if (v == null) return '—'
  if (Math.abs(v) >= 1e6) return '€' + (v / 1e6).toFixed(1) + 'M'
  return '€' + v.toFixed(0)
}

function Flag({ yes }) {
  return (
    <span className="text-xs font-semibold" style={{ color: yes ? 'var(--kpi-green-text)' : 'var(--kpi-red-text)' }}>
      {yes ? 'Yes' : 'No'}
    </span>
  )
}
function Alert({ triggered }) {
  return (
    <span className="text-xs font-semibold" style={{ color: triggered ? 'var(--kpi-red-text)' : 'var(--text-muted)' }}>
      {triggered ? 'Triggered' : '—'}
    </span>
  )
}

function RedemptionTable({ rows, label }) {
  if (!rows?.length) return null
  return (
    <div className="rounded-xl overflow-auto th-panel border" style={{ background: 'var(--bg-panel)' }}>
      <h2 className="text-sm font-semibold uppercase tracking-wide p-4 pb-2" style={{ color: 'var(--text-secondary)' }}>{label}</h2>
      <table className="w-full text-sm">
        <thead className="text-xs uppercase" style={{ background: 'var(--bg-surface)', color: 'var(--text-secondary)' }}>
          <tr>
            {[
              { label: 'Redemption %' },
              { label: 'Amount (€)' },
              { label: 'Liquidity Available' },
              { label: 'Shortfall' },
              { label: 'Can Meet T+1' },
              { label: 'Can Meet T+3' },
              { label: 'Can Meet T+7' },
              { label: 'Gate', id: 'redemption_gate' },
              { label: 'Suspension', id: 'redemption_suspension' },
              { label: 'Days to Clear', id: 'redemption_days_to_clear' },
            ].map(({ label, id }) => (
              <th key={label} className="px-3 py-2 text-left whitespace-nowrap">
                {id ? <MetricTooltip id={id}>{label}</MetricTooltip> : label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} style={{ background: i % 2 === 0 ? 'var(--bg-panel)' : 'var(--bg-surface)' }}>
              <td className="px-3 py-2 font-semibold" style={{ color: 'var(--text-primary)' }}>{pct(r.scenario_pct)}</td>
              <td className="px-3 py-2 text-right" style={{ color: 'var(--text-primary)' }}>{eur(r.redemption_eur)}</td>
              <td className={`px-3 py-2 text-right font-semibold ${r.shortfall_eur > 0 ? 'text-red-600' : 'text-green-600'}`}>
                {pct(r.liquidity_available_pct)}
              </td>
              <td className={`px-3 py-2 text-right ${r.shortfall_eur > 0 ? 'text-red-600 font-semibold' : ''}`} style={r.shortfall_eur > 0 ? {} : { color: 'var(--text-muted)' }}>
                {r.shortfall_eur > 0 ? eur(r.shortfall_eur) : '—'}
              </td>
              <td className="px-3 py-2 text-center"><Flag yes={r.can_meet_t1} /></td>
              <td className="px-3 py-2 text-center"><Flag yes={r.can_meet_t3} /></td>
              <td className="px-3 py-2 text-center"><Flag yes={r.can_meet_t7} /></td>
              <td className="px-3 py-2 text-center"><Alert triggered={r.gate_triggered} /></td>
              <td className="px-3 py-2 text-center"><Alert triggered={r.suspension_triggered} /></td>
              <td className="px-3 py-2 text-right" style={{ color: 'var(--text-primary)' }}>{r.days_to_clear?.toFixed(1) ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function Redemption() {
  const { data } = useAnalysis()
  const redemption = data?.redemption
  if (!redemption) return <EmptyState />

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>Redemption Coverage</h1>
      <RedemptionTable rows={redemption.redemption_results} label="Normal Regime" />
      <RedemptionTable rows={redemption.redemption_stress_results} label="Stressed Regime" />
    </div>
  )
}
