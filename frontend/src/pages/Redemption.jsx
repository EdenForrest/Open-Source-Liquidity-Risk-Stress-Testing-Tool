import { useAnalysis } from '../AnalysisContext'
import EmptyState from '../components/EmptyState'

function pct(v) { return v != null ? (v * 100).toFixed(1) + '%' : '—' }
function eur(v) {
  if (v == null) return '—'
  if (Math.abs(v) >= 1e6) return '€' + (v / 1e6).toFixed(1) + 'M'
  return '€' + v.toFixed(0)
}

function Flag({ yes }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${yes ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
      {yes ? 'Yes' : 'No'}
    </span>
  )
}
function Alert({ triggered }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${triggered ? 'bg-red-100 text-red-700' : 'bg-slate-100 text-slate-500'}`}>
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
            {['Redemption %', 'Amount (€)', 'Liquidity Available', 'Shortfall', 'Can Meet T+1', 'Can Meet T+3', 'Can Meet T+7', 'Gate', 'Suspension', 'Days to Clear'].map((h) => (
              <th key={h} className="px-3 py-2 text-left whitespace-nowrap">{h}</th>
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
