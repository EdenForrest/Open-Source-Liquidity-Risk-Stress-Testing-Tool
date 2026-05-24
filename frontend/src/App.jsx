import { BrowserRouter, Routes, Route, NavLink, Navigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
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
import Validation from './pages/Validation'
import Leverage from './pages/Leverage'
import LMTSimulator from './pages/LMTSimulator'

// SVG icon components — 16×16, stroke-based, professional
function IconPortfolios() {
  return <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><rect x="1" y="4" width="14" height="10" rx="1.5"/><path d="M5 4V3a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v1"/><line x1="1" y1="8" x2="15" y2="8"/></svg>
}
function IconDashboard() {
  return <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><rect x="1" y="1" width="6" height="6" rx="1"/><rect x="9" y="1" width="6" height="6" rx="1"/><rect x="1" y="9" width="6" height="6" rx="1"/><rect x="9" y="9" width="6" height="6" rx="1"/></svg>
}
function IconStress() {
  return <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="1,12 5,7 8,10 11,5 15,8"/><line x1="11" y1="5" x2="15" y2="5"/><line x1="15" y1="5" x2="15" y2="8"/></svg>
}
function IconRedemption() {
  return <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M13.5 8A5.5 5.5 0 1 1 8 2.5"/><polyline points="11,1 14,4 11,7"/><line x1="14" y1="4" x2="8" y2="4"/></svg>
}
function IconWaterfall() {
  return <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><rect x="1" y="9" width="3" height="5" rx="0.5"/><rect x="5" y="6" width="3" height="8" rx="0.5"/><rect x="9" y="3" width="3" height="11" rx="0.5"/><rect x="13" y="7" width="2" height="7" rx="0.5"/></svg>
}
function IconCharts() {
  return <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="1,11 5,6 9,9 15,3"/><line x1="1" y1="14" x2="15" y2="14"/></svg>
}
function IconRiskStory() {
  return <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M3 2h10a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z"/><line x1="4" y1="6" x2="12" y2="6"/><line x1="4" y1="9" x2="12" y2="9"/><line x1="4" y1="12" x2="8" y2="12"/></svg>
}
function IconValidation() {
  return <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="8" cy="8" r="7"/><polyline points="5,8 7,10 11,6"/></svg>
}
function IconLeverage() {
  return <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><line x1="1" y1="14" x2="15" y2="2"/><circle cx="4" cy="11" r="2"/><circle cx="12" cy="3" r="2"/></svg>
}
function IconLMT() {
  return <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><rect x="1" y="1" width="6" height="9" rx="1"/><rect x="9" y="6" width="6" height="9" rx="1"/><line x1="4" y1="13" x2="4" y2="15"/><line x1="12" y1="1" x2="12" y2="3"/></svg>
}

const NAV_ITEMS = [
  { to: '/portfolios',  labelKey: 'nav.allPortfolios', Icon: IconPortfolios },
  { to: '/dashboard',   labelKey: 'nav.dashboard',     Icon: IconDashboard  },
  { to: '/stress',      labelKey: 'nav.stressTests',   Icon: IconStress     },
  { to: '/redemption',  labelKey: 'nav.redemption',    Icon: IconRedemption },
  { to: '/waterfall',   labelKey: 'nav.waterfall',     Icon: IconWaterfall  },
  { to: '/charts',      labelKey: 'nav.charts',        Icon: IconCharts     },
  { to: '/leverage',    labelKey: 'nav.leverage',      Icon: IconLeverage   },
  { to: '/risk-story',  labelKey: 'nav.riskSummary',   Icon: IconRiskStory  },
  { to: '/validation',  labelKey: 'nav.validation',    Icon: IconValidation },
  { to: '/lmt',         labelKey: 'nav.lmtSimulator',  Icon: IconLMT        },
]

const LANGUAGES = [
  { code: 'en', label: 'EN' },
  { code: 'fr', label: 'FR' },
  { code: 'de', label: 'DE' },
]

function Sidebar() {
  const { t } = useTranslation()
  return (
    <aside style={{ background: 'var(--sidebar-bg)', borderRightColor: 'var(--sidebar-border)' }}
      className="w-44 min-h-screen flex flex-col shrink-0 border-r">
      <div style={{ borderBottomColor: 'var(--sidebar-border)' }} className="px-3 py-3 border-b">
        <div style={{ color: 'var(--sidebar-logo-text)' }} className="font-bold text-xs tracking-widest leading-tight uppercase">
          {t('sidebar.title')}
        </div>
        <div style={{ color: 'var(--sidebar-logo-sub)' }} className="text-xs mt-0.5">
          {t('sidebar.subtitle')}
        </div>
      </div>
      <nav className="flex-1 py-2 space-y-0.5 px-1">
        {NAV_ITEMS.map(({ to, labelKey, Icon }) => (
          <NavLink
            key={to}
            to={to}
            style={({ isActive }) => isActive
              ? { background: 'var(--nav-active-bg)', color: 'var(--nav-active-text)', borderLeft: '2px solid var(--text-accent)' }
              : { color: 'var(--sidebar-text)' }
            }
            className={({ isActive }) =>
              `flex items-center gap-2 px-3 py-1.5 rounded-sm text-xs transition-colors ` +
              (isActive ? 'font-semibold' : 'hover:bg-[var(--nav-hover-bg)] hover:text-[var(--nav-hover-text)]')
            }
          >
            <Icon />
            {t(labelKey)}
          </NavLink>
        ))}
      </nav>
      <div style={{ borderTopColor: 'var(--sidebar-border)', color: 'var(--sidebar-ver)' }}
        className="px-3 py-2 border-t text-xs">
        {t('sidebar.version')}
      </div>
    </aside>
  )
}

function PortfolioSelector() {
  const { portfolioCodes, selectedPortfolio, selectPortfolio, status } = useAnalysis()
  const { t } = useTranslation()
  if (status !== 'complete' || portfolioCodes.length < 2) return null

  return (
    <div className="flex items-center gap-2 ml-4">
      <label style={{ color: 'var(--text-secondary)' }} className="text-xs font-medium shrink-0">{t('header.portfolio')}</label>
      <select
        value={selectedPortfolio || ''}
        onChange={(e) => selectPortfolio(e.target.value)}
        style={{ background: 'var(--bg-panel)', borderColor: 'var(--border)', color: 'var(--text-primary)' }}
        className="rounded border px-2 py-1 text-xs focus:outline-none"
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
    <div className="flex items-center gap-0 ml-auto rounded overflow-hidden"
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

function LanguageSwitcher() {
  const { i18n } = useTranslation()
  const current = i18n.language?.slice(0, 2)
  return (
    <div className="flex items-center gap-0 rounded overflow-hidden"
      style={{ border: '1px solid var(--border)', background: 'var(--bg-surface)' }}>
      {LANGUAGES.map(({ code, label }) => (
        <button
          key={code}
          onClick={() => i18n.changeLanguage(code)}
          style={current === code
            ? { background: 'var(--text-accent)', color: '#fff' }
            : { background: 'transparent', color: 'var(--text-secondary)' }
          }
          className="px-2.5 py-1.5 text-xs font-semibold transition-colors cursor-pointer"
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
                className="border-b px-3 py-2 flex items-center gap-4 shrink-0 flex-wrap">
                <Uploader />
                <PortfolioSelector />
                <LanguageSwitcher />
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
                  <Route path="/leverage"     element={<Leverage />} />
                  <Route path="/risk-story"  element={<RiskStory />} />
                  <Route path="/validation"  element={<Validation />} />
                  <Route path="/lmt"         element={<LMTSimulator />} />
                </Routes>
              </main>
            </div>
          </div>
        </BrowserRouter>
      </AnalysisProvider>
    </ThemeProvider>
  )
}
