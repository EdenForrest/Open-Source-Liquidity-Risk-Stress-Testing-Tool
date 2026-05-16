import { useAnalysis } from '../AnalysisContext'
import { useAnalysisPoller } from '../hooks/useAnalysis'

export default function StatusBanner() {
  const { runId, status, error, fetchPortfolios, markError } = useAnalysis()

  useAnalysisPoller(runId, async (statusData) => {
    if (statusData.status === 'complete') {
      try {
        await fetchPortfolios(runId)
      } catch (e) {
        console.error('[fetchPortfolios] failed:', e)
        markError(e.message)
      }
    } else {
      const detail = statusData.error || 'Pipeline failed — check uvicorn terminal for traceback.'
      markError(detail)
    }
  })

  if (status === 'idle') return null

  const states = {
    uploading: { bg: 'bg-blue-50 border-blue-300 text-blue-800', msg: 'Uploading files…' },
    running:   { bg: 'bg-amber-50 border-amber-300 text-amber-800', msg: 'Running pipeline — profiling all portfolios, stress testing, waterfall…' },
    complete:  { bg: 'bg-green-50 border-green-300 text-green-800', msg: 'Analysis complete.' },
    error:     { bg: 'bg-red-50 border-red-300 text-red-800', msg: `Error: ${error}` },
  }

  const { bg, msg } = states[status] || states.running

  return (
    <div className={`border rounded-lg px-4 py-2 text-sm font-medium mx-4 mt-2 ${bg}`}>
      {(status === 'uploading' || status === 'running') && (
        <span className="mr-2 inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
      )}
      {msg}
    </div>
  )
}
