export default function KPICard({ label, value, sub, color = 'blue', alert = false }) {
  const key = alert ? 'red' : (color || 'slate')
  const style = {
    background:  `var(--kpi-${key}-bg)`,
    borderColor: `var(--kpi-${key}-border)`,
    color:       `var(--kpi-${key}-text)`,
  }

  return (
    <div className="rounded-xl border-l-4 p-4 shadow-sm" style={style}>
      <p className="text-xs font-semibold uppercase tracking-wide opacity-70">{label}</p>
      <p className="mt-1 text-2xl font-bold">{value}</p>
      {sub && <p className="mt-0.5 text-xs opacity-60">{sub}</p>}
    </div>
  )
}
