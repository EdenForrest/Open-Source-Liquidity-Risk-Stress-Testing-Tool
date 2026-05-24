import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAnalysis } from '../AnalysisContext'

const FORMATS = [
  { id: 'excel', labelKey: 'export.excel', ext: '.xlsx' },
  { id: 'pdf',   labelKey: 'export.pdf',   ext: '.pdf'  },
  { id: 'xml',   labelKey: 'export.xml',   ext: '.xml'  },
]

export default function ExportModal({ open, onClose }) {
  const { runId, selectedPortfolio } = useAnalysis()
  const { t } = useTranslation()
  const [selected, setSelected] = useState('excel')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)

  if (!open) return null

  function buildUrl(fmtId) {
    const code = selectedPortfolio || ''
    const base = (import.meta.env.VITE_API_BASE_URL ?? '/api').replace(/\/+$/, '')
    return `${base}/run/${runId}/export/${fmtId}${code ? `?portfolio=${encodeURIComponent(code)}` : ''}`
  }

  async function handleDownload() {
    if (!runId || loading) return
    const fmt = FORMATS.find((f) => f.id === selected)
    setErr(null)
    setLoading(true)
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
      setErr(t('export.failed', { message: e.message }))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.4)' }}
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        className="rounded shadow-lg flex flex-col w-full max-w-xs"
        style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)' }}
      >
        <div className="flex items-center justify-between px-4 pt-3 pb-2"
          style={{ borderBottom: '1px solid var(--border)' }}>
          <h2 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
            {t('export.title')}
          </h2>
          <button
            onClick={onClose}
            style={{ color: 'var(--text-secondary)', cursor: 'pointer', background: 'none', border: 'none', padding: '2px' }}
            title="Close"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24"
              fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>

        <div className="px-4 py-3 flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>
              {t('export.format')}
            </label>
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              className="rounded border px-2 py-1.5 text-sm"
              style={{ background: 'var(--bg-surface)', borderColor: 'var(--border)', color: 'var(--text-primary)', cursor: 'pointer' }}
            >
              {FORMATS.map((f) => (
                <option key={f.id} value={f.id}>{t(f.labelKey)}</option>
              ))}
            </select>
          </div>

          {err && (
            <p className="text-xs" style={{ color: 'var(--kpi-red-text)' }}>{err}</p>
          )}

          <button
            onClick={handleDownload}
            disabled={loading}
            className="rounded px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ background: 'var(--text-accent)', cursor: loading ? 'wait' : 'pointer' }}
          >
            {loading ? t('export.downloading') : t('export.download')}
          </button>
        </div>
      </div>
    </div>
  )
}
