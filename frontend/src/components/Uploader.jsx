import { useRef, useState } from 'react'
import { useAnalysis } from '../AnalysisContext'
import InfoModal from './InfoModal'
import ExportModal from './ExportModal'

export default function Uploader() {
  const { upload, markError, status, runId } = useAnalysis()
  const [holdings, setHoldings] = useState(null)
  const [nav, setNav] = useState(null)
  const [mkt, setMkt] = useState(null)
  const [exportOpen, setExportOpen] = useState(false)
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

  return (
    <div className="flex flex-wrap items-end gap-2">
      <ExportModal open={exportOpen} onClose={() => setExportOpen(false)} />
      <FileInput label="Holdings CSV" accept=".csv" onChange={setHoldings} />
      <FileInput label="NAV CSV" accept=".csv" onChange={setNav} />
      <FileInput label="Market Data (optional)" accept=".csv" onChange={setMkt} />
      <InfoModal />
      <button
        onClick={handleRun}
        disabled={!holdings || !nav || busy}
        className="rounded px-3 py-1 text-xs font-semibold text-white shadow disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        style={{ background: 'var(--text-accent)' }}
      >
        {busy ? 'Running…' : 'Run Analysis'}
      </button>
      <button
        onClick={() => setExportOpen(true)}
        disabled={!canDownload}
        className="flex items-center gap-1.5 rounded px-3 py-1 text-xs font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)', cursor: canDownload ? 'pointer' : 'not-allowed' }}
        title={canDownload ? 'Download report (Excel, PDF, or XML)' : 'Run analysis first'}
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
        Download Report
      </button>
    </div>
  )
}

function FileInput({ label, accept, onChange }) {
  const ref = useRef()
  const [name, setName] = useState(null)
  return (
    <div>
      <p className="mb-1 text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>{label}</p>
      <button
        onClick={() => ref.current.click()}
        style={{ background: 'var(--bg-surface)', borderColor: 'var(--border)', color: 'var(--text-primary)' }}
        className="rounded border px-2 py-1 text-xs hover:opacity-80 transition-colors"
      >
        {name || 'Choose file…'}
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
