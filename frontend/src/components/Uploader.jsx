import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAnalysis } from '../AnalysisContext'
import InfoModal from './InfoModal'

const FORMAT_OPTIONS = [
  { value: 'excel', label: 'Excel (.xlsx)' },
  { value: 'pdf',   label: 'PDF' },
  { value: 'xml',   label: 'XML' },
]

export default function Uploader() {
  const { upload, markError, status, runId } = useAnalysis()
  const { t } = useTranslation()
  const [holdings, setHoldings] = useState(null)
  const [nav, setNav] = useState(null)
  const [mkt, setMkt] = useState(null)
  const [dlFormat, setDlFormat] = useState('excel')
  const [downloadingAll, setDownloadingAll] = useState(false)
  const [downloadingSample, setDownloadingSample] = useState(false)
  const busy = status === 'uploading' || status === 'running'
  const canDownload = status === 'complete' && !!runId

  async function handleRun() {
    if (!holdings || !nav) return
    try {
      await upload(holdings, nav, mkt)
    } catch (e) {
      markError(e.message)
    }
  }

  async function handleDownloadAll() {
    if (!canDownload || downloadingAll) return
    setDownloadingAll(true)
    try {
      const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '') + '/api'
      const url = `${base}/run/${runId}/export/all?format=${encodeURIComponent(dlFormat)}`
      const resp = await fetch(url)
      if (!resp.ok) throw new Error(`Server returned ${resp.status}`)
      const blob = await resp.blob()
      const objUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = objUrl
      a.download = `liquidity_reports_${runId.slice(0, 8)}.zip`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(objUrl)
    } finally {
      setDownloadingAll(false)
    }
  }

  async function handleDownloadSample() {
    if (downloadingSample) return
    setDownloadingSample(true)
    try {
      const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '') + '/api'
      const resp = await fetch(`${base}/sample-data`)
      if (!resp.ok) throw new Error(`Server returned ${resp.status}`)
      const blob = await resp.blob()
      const objUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = objUrl
      a.download = 'sample_data.zip'
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(objUrl)
    } finally {
      setDownloadingSample(false)
    }
  }

  return (
    <div className="flex flex-wrap items-end gap-2">
      <FileInput label={t('uploader.holdingsCsv')} accept=".csv" onChange={setHoldings} />
      <FileInput label={t('uploader.navCsv')} accept=".csv" onChange={setNav} />
      <FileInput label={t('uploader.marketData')} accept=".csv" onChange={setMkt} />
      <InfoModal />
      <button
        onClick={handleRun}
        disabled={!holdings || !nav || busy}
        className="rounded px-3 py-1 text-xs font-semibold text-white shadow disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        style={{ background: 'var(--text-accent)' }}
      >
        {busy ? t('uploader.running') : t('uploader.runAnalysis')}
      </button>
      {/* Download All — format selector + zip download button */}
      <div className="flex items-end gap-1">
        <div>
          <p className="mb-1 text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>{t('uploader.format', 'Format')}</p>
          <select
            value={dlFormat}
            onChange={e => setDlFormat(e.target.value)}
            disabled={!canDownload}
            className="rounded border px-2 py-1 text-xs disabled:opacity-40"
            style={{ background: 'var(--bg-surface)', borderColor: 'var(--border)', color: 'var(--text-primary)', cursor: canDownload ? 'pointer' : 'not-allowed' }}
          >
            {FORMAT_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>
        <button
          onClick={handleDownloadAll}
          disabled={!canDownload || downloadingAll}
          className="flex items-center gap-1.5 rounded px-3 py-1 text-xs font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)', cursor: canDownload && !downloadingAll ? 'pointer' : 'not-allowed' }}
          title={t('allPortfolios.downloadAll', 'Download all portfolios as zip')}
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
          {downloadingAll ? t('export.downloading') : t('allPortfolios.downloadAll', 'Download All')}
        </button>
      </div>
      {/* Download sample data — always available; synthetic demo files + Annex IV */}
      <button
        onClick={handleDownloadSample}
        disabled={downloadingSample}
        className="flex items-center gap-1.5 rounded px-3 py-1 text-xs font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)', cursor: downloadingSample ? 'not-allowed' : 'pointer' }}
        title={t('uploader.downloadSampleHint', 'Download all synthetic demo files (incl. Annex IV) as a zip')}
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
        {downloadingSample ? t('export.downloading') : t('uploader.downloadSample', 'Download sample data')}
      </button>
    </div>
  )
}

function FileInput({ label, accept, onChange }) {
  const ref = useRef()
  const { t } = useTranslation()
  const [name, setName] = useState(null)
  return (
    <div>
      <p className="mb-1 text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>{label}</p>
      <button
        onClick={() => ref.current.click()}
        style={{ background: 'var(--bg-surface)', borderColor: 'var(--border)', color: 'var(--text-primary)' }}
        className="rounded border px-2 py-1 text-xs hover:opacity-80 transition-colors"
      >
        {name || t('uploader.chooseFile')}
      </button>
      <input
        ref={ref}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => {
          const f = e.target.files[0]
          if (f) { setName(f.name); onChange(f) }
        }}
      />
    </div>
  )
}
