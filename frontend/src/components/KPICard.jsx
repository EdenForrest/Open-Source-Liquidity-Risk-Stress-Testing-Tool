export default function KPICard({ label, value, sub, color = 'blue', alert = false }) {
  const key = alert ? 'red' : (color || 'slate')
  const style = {
    background:  `var(--kpi-${key}-bg)`,
    borderColor: `var(--kpi-${key}-border)`,
    color:       `var(--kpi-${key}-text)`,
  }

  return (
    <div className="border-l-2 p-2 shadow-sm" style={style}>
      <p className="bb-kpi-label text-xs font-semibold uppercase tracking-widest" style={{ opacity: 0.85 }}>{label}</p>
      <p className="mt-0.5 text-xl font-bold bb-num">{value}</p>
      {sub && <p className="text-xs" style={{ opacity: 0.55 }}>{sub}</p>}
    </div>
  )
}
