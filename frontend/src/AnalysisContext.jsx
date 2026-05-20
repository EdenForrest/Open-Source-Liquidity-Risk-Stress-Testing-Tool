import { createContext, useContext, useState, useCallback, useRef, useEffect } from 'react'
import client from './api/client'

const AnalysisContext = createContext(null)

export function useAnalysis() {
  return useContext(AnalysisContext)
}

export function AnalysisProvider({ children }) {
  const [runId, setRunId] = useState(null)
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState(null)
  const [portfolioCodes, setPortfolioCodes] = useState([])
  const [selectedPortfolio, setSelectedPortfolioState] = useState(null)

  const allDataRef = useRef({})
  const [allData, setAllDataState] = useState({})
  const [data, setData] = useState({ liquidity: null, stress: null, redemption: null, waterfall: null, validation: null, aifmd2: null })

  const _setAllData = (updater) => {
    allDataRef.current = typeof updater === 'function' ? updater(allDataRef.current) : updater
    setAllDataState({ ...allDataRef.current })
  }

  const upload = useCallback(async (holdingsFile, navFile, marketDataFile) => {
    setStatus('uploading')
    setError(null)
    const form = new FormData()
    form.append('holdings_file', holdingsFile)
    form.append('nav_file', navFile)
    if (marketDataFile) form.append('market_data_file', marketDataFile)
    const res = await client.post('/upload', form)
    setRunId(res.data.run_id)
    setStatus('running')
    return res.data.run_id
  }, [])

  const fetchPortfolioData = useCallback(async (id, code) => {
    const params = { portfolio: code }
    const [liq, stress, redemption, wf, validation, leverage] = await Promise.all([
      client.get(`/run/${id}/liquidity`, { params }),
      client.get(`/run/${id}/stress`, { params }),
      client.get(`/run/${id}/redemption`, { params }),
      client.get(`/run/${id}/waterfall`, { params }),
      client.get(`/run/${id}/validation`, { params }),
      client.get(`/run/${id}/leverage`, { params }),
    ])
    const entry = {
      liquidity: liq.data,
      stress: stress.data,
      redemption: redemption.data,
      waterfall: wf.data,
      validation: validation.data,
      aifmd2: leverage.data,
    }
    _setAllData(prev => ({ ...prev, [code]: entry }))
    return entry
  }, [])

  const fetchPortfolios = useCallback(async (id) => {
    const codesRes = await client.get(`/run/${id}/portfolios`)
    const codes = codesRes.data.portfolio_codes
    setPortfolioCodes(codes)
    const entries = await Promise.all(codes.map(code => fetchPortfolioData(id, code)))
    setSelectedPortfolioState(codes[0])
    setData(entries[0])
    setStatus('complete')
  }, [fetchPortfolioData])

  const selectPortfolio = useCallback(async (code) => {
    setSelectedPortfolioState(code)
    const cached = allDataRef.current[code]
    if (cached) {
      setData(cached)
    } else {
      const entry = await fetchPortfolioData(runId, code)
      setData(entry)
    }
  }, [fetchPortfolioData, runId])

  const markError = useCallback((msg) => {
    setStatus('error')
    setError(msg)
  }, [])

  useEffect(() => {
    let cancelled = false
    let pollTimer = null

    async function waitForBackend(retries = 20, delayMs = 3000) {
      for (let i = 0; i < retries; i++) {
        if (cancelled) return false
        try {
          await client.get('/health')
          return true
        } catch {
          await new Promise(r => setTimeout(r, delayMs))
        }
      }
      return false
    }

    async function loadDemo() {
      try {
        setStatus('running')
        const alive = await waitForBackend()
        if (cancelled) return
        if (!alive) { markError('Backend is not responding. Please try again in a moment.'); return }

        const res = await client.post('/demo')
        const id = res.data.run_id
        if (cancelled) return
        setRunId(id)

        pollTimer = setInterval(async () => {
          try {
            const s = await client.get(`/run/${id}/status`)
            if (cancelled) return
            if (s.data.status === 'complete') {
              clearInterval(pollTimer)
              await fetchPortfolios(id)
            } else if (s.data.status === 'error') {
              clearInterval(pollTimer)
              markError(s.data.error ?? 'Demo run failed')
            }
          } catch (e) {
            clearInterval(pollTimer)
            if (!cancelled) markError(e.message)
          }
        }, 1500)
      } catch (e) {
        if (!cancelled) markError(e.message)
      }
    }

    loadDemo()
    return () => {
      cancelled = true
      if (pollTimer) clearInterval(pollTimer)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <AnalysisContext.Provider
      value={{
        runId, status, error,
        portfolioCodes, selectedPortfolio, selectPortfolio,
        allData, data, upload,
        fetchPortfolios,
        markError, setStatus,
      }}
    >
      {children}
    </AnalysisContext.Provider>
  )
}
