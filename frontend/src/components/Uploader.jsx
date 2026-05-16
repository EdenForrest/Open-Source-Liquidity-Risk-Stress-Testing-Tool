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
    <div className="flex flex-wrap items-end gap-3 p-4 bg-white border-b border-slate-200">
      <FileInput label="Holdings CSV" accept=".csv" onChange={setHoldings} />
      <FileInput label="NAV CSV" accept=".csv" onChange={setNav} />
      <FileInput label="Market Data (optional)" accept=".csv" onChange={setMkt} />
      <InfoModal />
      <button
        onClick={handleRun}
        disabled={!holdings || !nav || busy}
        className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-semibold text-white shadow hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
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
      <p className="mb-1 text-xs font-medium text-slate-500">{label}</p>
      <button
        onClick={() => ref.current.click()}
        className="rounded-lg border border-slate-300 bg-slate-50 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-100 transition-colors"
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
