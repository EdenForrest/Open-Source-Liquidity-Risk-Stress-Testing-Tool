import { useRef, useState } from 'react'
import { useAnalysis } from '../AnalysisContext'
import InfoModal from './InfoModal'

export default function Uploader() {
  const { upload, markError, status } = useAnalysis()
  const [holdings, setHoldings] = useState(null)
  const [nav, setNav] = useState(null)
  const [mkt, setMkt] = useState(null)
  const busy = status === 'uploading' || status === 'running'

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
