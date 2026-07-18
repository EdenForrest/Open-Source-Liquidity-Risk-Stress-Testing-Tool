export default function KPICard({ label, value, sub, color = 'blue', alert = false }) {
  const key = alert ? 'red' : (color || 'slate')
  const style = {
    background:  `var(--kpi-${key}-bg)`,
    borderColor: `var(--kpi-${key}-border)`,
    color:       `var(--kpi-${key}-text)`,
  }

  return (
    <div className="border-l-2 p-3 shadow-sm" style={style}>
      <p className="bb-kpi-label text-sm font-semibold uppercase tracking-wide" style={{ opacity: 0.85 }}>{label}</p>
      <p className="mt-1 text-2xl font-bold bb-num">{value}</p>
      {sub && <p className="text-sm" style={{ opacity: 0.55 }}>{sub}</p>}
    </div>
  )
}
