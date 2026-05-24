import { useState } from 'react'
import { useAnalysis } from '../AnalysisContext'

const FORMATS = [
  {
    id: 'excel',
    label: 'Excel',
    ext: '.xlsx',
    mime: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    description: '5-sheet workbook: Summary, Ladder, Scenarios, Positions, Waterfall',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24"
        fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/><path d="m7 13 2 4 2-4"/><path d="M15 13h3m-3 4h3"/>
      </svg>
    ),
    color: 'var(--kpi-green-text)',
    bg: 'var(--kpi-green-bg)',
    border: 'var(--kpi-green-border)',
  },
  {
    id: 'pdf',
    label: 'PDF',
    ext: '.pdf',
    mime: 'application/pdf',
    description: 'Formatted A4 report — suitable for board packs and regulatory submissions',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24"
        fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>
        <line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/>
      </svg>
    ),
    color: 'var(--kpi-red-text)',
    bg: 'var(--kpi-red-bg)',
    border: 'var(--kpi-red-border)',
  },
  {
    id: 'xml',
    label: 'XML',
    ext: '.xml',
    mime: 'application/xml',
    description: 'Machine-readable structured data — for system integrations and audit trails',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24"
        fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>
      </svg>
    ),
    color: 'var(--kpi-blue-text, #2563eb)',
    bg: 'var(--kpi-blue-bg, #eff6ff)',
    border: 'var(--kpi-blue-border, #bfdbfe)',
  },
]

export default function ExportModal({ open, onClose }) {
  const { runId, selectedPortfolio } = useAnalysis()
  const [loading, setLoading] = useState(null)
  const [err, setErr] = useState(null)

  if (!open) return null

  function buildUrl(fmt) {
    const code = selectedPortfolio || ''
    const base = (import.meta.env.VITE_API_BASE_URL ?? '/api').replace(/\/+$/, '')
    return `${base}/run/${runId}/export/${fmt}${code ? `?portfolio=${encodeURIComponent(code)}` : ''}`
  }

  async function handleDownload(fmt) {
    if (!runId || loading) return
    setErr(null)
    setLoading(fmt.id)
    try {
      const resp = await fetch(buildUrl(fmt.id))
      if (!resp.ok) throw new Error(`Server returned ${resp.status}`)
      const blob = await resp.blob()
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href     = url
      a.download = `liquidity_report_${selectedPortfolio || 'portfolio'}${fmt.ext}`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      onClose()
    } catch (e) {
      setErr(`Failed to download ${fmt.label}: ${e.message}`)
    } finally {
      setLoading(null)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.5)' }}
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        className="rounded-xl shadow-2xl flex flex-col w-full max-w-md"
        style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 pt-4 pb-3"
          style={{ borderBottom: '1px solid var(--border)' }}>
          <div>
            <h2 className="text-base font-semibold" style={{ color: 'var(--text-primary)' }}>
              Download Report
            </h2>
            <p className="text-xs mt-0.5" style={{ color: 'var(--text-secondary)' }}>
              Choose a format — your browser will prompt where to save.
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded p-1.5 transition-colors"
            style={{ color: 'var(--text-secondary)', cursor: 'pointer' }}
            title="Close"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"
              fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>

        {/* Format options */}
        <div className="flex flex-col gap-2 p-4">
          {FORMATS.map((fmt) => (
            <button
              key={fmt.id}
              onClick={() => handleDownload(fmt)}
              disabled={!!loading}
              className="flex items-center gap-3 rounded-lg px-4 py-3 text-left transition-opacity"
              style={{
                background: fmt.bg,
                border: `1px solid ${fmt.border}`,
                color: fmt.color,
                cursor: loading ? 'wait' : 'pointer',
                opacity: loading && loading !== fmt.id ? 0.5 : 1,
              }}
            >
              <span style={{ flexShrink: 0 }}>{fmt.icon}</span>
              <span className="flex-1">
                <span className="block font-semibold text-sm">{fmt.label}</span>
                <span className="block text-xs opacity-75 font-normal" style={{ color: 'var(--text-secondary)' }}>
                  {fmt.description}
                </span>
              </span>
              {loading === fmt.id ? (
                <svg className="animate-spin" xmlns="http://www.w3.org/2000/svg" width="16" height="16"
                  viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
                </svg>
              ) : (
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24"
                  fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                  <polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
                </svg>
              )}
            </button>
          ))}
        </div>

        {err && (
          <div className="mx-4 mb-4 rounded p-2 text-xs"
            style={{ background: 'var(--kpi-red-bg)', color: 'var(--kpi-red-text)', border: '1px solid var(--kpi-red-border)' }}>
            {err}
          </div>
        )}
      </div>
    </div>
  )
}
