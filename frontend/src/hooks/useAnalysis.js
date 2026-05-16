import { useEffect, useRef } from 'react'
import client from '../api/client'

/**
 * Polls /api/run/{runId}/status every 1.5 s until the run is no longer "running".
 * Calls onComplete(status) when done.
 */
export function useAnalysisPoller(runId, onComplete) {
  const intervalRef = useRef(null)

  useEffect(() => {
    if (!runId) return
    intervalRef.current = setInterval(async () => {
      try {
        const res = await client.get(`/run/${runId}/status`)
        const statusData = res.data  // { run_id, status, error }
        if (statusData.status !== 'running' && statusData.status !== 'pending') {
          clearInterval(intervalRef.current)
          onComplete(statusData)
        }
      } catch (err) {
        console.error('[poller] status check failed:', err)
        clearInterval(intervalRef.current)
        onComplete({ status: 'error', error: err.message })
      }
    }, 1500)

    return () => clearInterval(intervalRef.current)
  }, [runId]) // eslint-disable-line react-hooks/exhaustive-deps
}
