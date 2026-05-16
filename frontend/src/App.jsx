import { BrowserRouter, Routes, Route, NavLink, Navigate } from 'react-router-dom'
import { AnalysisProvider } from './AnalysisContext'
import { useAnalysis } from './AnalysisContext'
import { ThemeProvider, useTheme, THEMES } from './ThemeContext'
import Uploader from './components/Uploader'
import StatusBanner from './components/StatusBanner'
import Dashboard from './pages/Dashboard'
import StressTests from './pages/StressTests'
import Redemption from './pages/Redemption'
import Waterfall from './pages/Waterfall'
import Charts from './pages/Charts'
import RiskStory from './pages/RiskStory'
import AllPortfolios from './pages/AllPortfolios'

const NAV_ITEMS = [
  { to: '/portfolios',  label: 'All Portfolios', icon: '🗂️' },
  { to: '/dashboard',   label: 'Dashboard',      icon: '📊' },
  { to: '/stress',      label: 'Stress Tests',   icon: '⚡' },
  { to: '/redemption',  label: 'Redemption',     icon: '🔄' },
  { to: '/waterfall',   label: 'Waterfall',      icon: '💧' },
  { to: '/charts',      label: 'Charts',         icon: '📈' },
  { to: '/risk-story',  label: 'Risk Story',     icon: '📝' },
]

function Sidebar() {
  return (
    <aside style={{ background: 'var(--sidebar-bg)', borderRightColor: 'var(--sidebar-border)' }}
      className="w-56 min-h-screen flex flex-col shrink-0 border-r">
      <div style={{ borderBottomColor: 'var(--sidebar-border)' }} className="px-5 py-5 border-b">
        <div style={{ color: 'var(--sidebar-logo-text)' }} className="font-bold text-sm leading-tight">
          Liquidity Risk
        </div>
        <div style={{ color: 'var(--sidebar-logo-sub)' }} className="text-xs mt-0.5">
          Analytics Platform
        </div>
      </div>
      <nav className="flex-1 py-4 space-y-0.5 px-2">
        {NAV_ITEMS.map(({ to, label, icon }) => (
          <NavLink
            key={to}
            to={to}
            style={({ isActive }) => isActive
              ? { background: 'var(--nav-active-bg)', color: 'var(--nav-active-text)', borderLeft: '2px solid var(--text-accent)' }
              : { color: 'var(--sidebar-text)' }
            }
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ` +
              (isActive ? 'font-semibold' : 'hover:bg-[var(--nav-hover-bg)] hover:text-[var(--nav-hover-text)]')
            }
          >
            <span className="text-base leading-none">{icon}</span>
            {label}
          </NavLink>
        ))}
      </nav>
      <div style={{ borderTopColor: 'var(--sidebar-border)', color: 'var(--sidebar-ver)' }}
        className="px-5 py-4 border-t text-xs">
        v1.1 — ESMA/AIFMD
      </div>
    </aside>
  )
}

function PortfolioSelector() {
  const { portfolioCodes, selectedPortfolio, selectPortfolio, status } = useAnalysis()
  if (status !== 'complete' || portfolioCodes.length < 2) return null

  return (
    <div className="flex items-center gap-2 ml-4">
      <label style={{ color: 'var(--text-secondary)' }} className="text-xs font-medium shrink-0">Portfolio</label>
      <select
        value={selectedPortfolio || ''}
        onChange={(e) => selectPortfolio(e.target.value)}
        style={{ background: 'var(--bg-panel)', borderColor: 'var(--border)', color: 'var(--text-primary)' }}
        className="rounded-lg border px-3 py-1.5 text-sm focus:outline-none"
      >
        {portfolioCodes.map((code) => (
          <option key={code} value={code}>{code}</option>
        ))}
      </select>
    </div>
  )
}

function ThemeSwitcher() {
  const { theme, setTheme } = useTheme()
  return (
    <div className="flex items-center gap-1 ml-auto rounded-lg overflow-hidden"
      style={{ border: '1px solid var(--border)', background: 'var(--bg-surface)' }}>
      {THEMES.map(({ id, label }) => (
        <button
          key={id}
          onClick={() => setTheme(id)}
          style={theme === id
            ? { background: 'var(--text-accent)', color: '#fff' }
            : { background: 'transparent', color: 'var(--text-secondary)' }
          }
          className="px-3 py-1.5 text-xs font-semibold transition-colors cursor-pointer"
        >
          {label}
        </button>
      ))}
    </div>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <AnalysisProvider>
        <BrowserRouter>
          <div className="flex min-h-screen" style={{ background: 'var(--bg-base)' }}>
            <Sidebar />
            <div className="flex-1 flex flex-col min-w-0">
              <header style={{ background: 'var(--header-bg)', borderBottomColor: 'var(--header-border)' }}
                className="border-b px-6 py-3 flex items-center gap-4 shrink-0 flex-wrap">
                <Uploader />
                <PortfolioSelector />
                <ThemeSwitcher />
              </header>
              <StatusBanner />
              <main className="flex-1 overflow-auto">
                <Routes>
                  <Route path="/" element={<Navigate to="/portfolios" replace />} />
                  <Route path="/portfolios"  element={<AllPortfolios />} />
                  <Route path="/dashboard"   element={<Dashboard />} />
                  <Route path="/stress"      element={<StressTests />} />
                  <Route path="/redemption"  element={<Redemption />} />
                  <Route path="/waterfall"   element={<Waterfall />} />
                  <Route path="/charts"      element={<Charts />} />
                  <Route path="/risk-story"  element={<RiskStory />} />
                </Routes>
              </main>
            </div>
          </div>
        </BrowserRouter>
      </AnalysisProvider>
    </ThemeProvider>
  )
}
