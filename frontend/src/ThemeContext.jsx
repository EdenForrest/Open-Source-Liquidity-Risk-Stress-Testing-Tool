import { createContext, useContext, useState, useEffect } from 'react'

const ThemeContext = createContext(null)

export const THEMES = [
  { id: 'light',     label: 'Light' },
  { id: 'bloomberg', label: 'Dark' },
]

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(() => localStorage.getItem('lrt-theme-v2') || 'bloomberg')

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('lrt-theme-v2', theme)
  }, [theme])

  return (
    <ThemeContext.Provider value={{ theme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme() {
  return useContext(ThemeContext)
}
