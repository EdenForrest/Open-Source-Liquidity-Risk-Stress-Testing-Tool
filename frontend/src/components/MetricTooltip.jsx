import { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { DEFINITIONS } from '../definitions'
import { useTheme } from '../ThemeContext'

const BG = {
  light:     '#ffffff',
  bloomberg: '#111820',
  dark:      '#1e2535',
}
const BORDER_COLOR = {
  light:     '#3b82f6',
  bloomberg: '#ff6600',
  dark:      '#3b82f6',
}
const TEXT = {
  light:     '#1e293b',
  bloomberg: '#e8ecf0',
  dark:      '#e2e8f0',
}
const SUBTEXT = {
  light:     '#64748b',
  bloomberg: '#7a8fa8',
  dark:      '#94a3b8',
}

export default function MetricTooltip({ id, children, className = '' }) {
  const def = DEFINITIONS[id]
  const { theme } = useTheme()
  const [pos, setPos] = useState(null)
  const btnRef = useRef(null)

  useEffect(() => {
    if (!pos) return
    function handler(e) {
      if (!btnRef.current?.contains(e.target)) setPos(null)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [pos])

  if (!def) return <span className={className}>{children}</span>

  function toggle() {
    if (pos) { setPos(null); return }
    const r = btnRef.current.getBoundingClientRect()
    const width = 320
    const margin = 8
    const estimatedHeight = 160
    let left = r.left + r.width / 2 - width / 2
    if (left + width + margin > window.innerWidth) left = window.innerWidth - width - margin
    if (left < margin) left = margin
    const spaceBelow = window.innerHeight - r.bottom
    const top = spaceBelow < estimatedHeight + margin
      ? Math.max(margin, r.top - estimatedHeight - 8)
      : r.bottom + 8
    setPos({ top, left })
  }

  const bg = BG[theme] || BG.light
  const border = BORDER_COLOR[theme] || BORDER_COLOR.light
  const color = TEXT[theme] || TEXT.light
  const subcolor = SUBTEXT[theme] || SUBTEXT.light

  return (
    <span className={'relative inline-flex items-center gap-1 ' + className}>
      <span>{children}</span>
      <button
        ref={btnRef}
        onClick={toggle}
        title="Model definition"
        style={{
          color: subcolor,
          background: 'none',
          border: 'none',
          padding: 0,
          cursor: 'pointer',
          lineHeight: 1,
          fontSize: '0.7rem',
          opacity: 0.7,
        }}
        onMouseEnter={(e) => (e.currentTarget.style.opacity = 1)}
        onMouseLeave={(e) => (e.currentTarget.style.opacity = 0.7)}
      >
        ⓘ
      </button>

      {pos && createPortal(
        <div
          onMouseDown={(e) => e.stopPropagation()}
          style={{
            position: 'fixed',
            top: pos.top,
            left: pos.left,
            zIndex: 999999,
            width: 320,
            backgroundColor: bg,
            border: `2px solid ${border}`,
            borderRadius: 8,
            padding: '10px 14px',
            boxShadow: '0 16px 48px rgba(0,0,0,0.9)',
            color,
            fontSize: '0.78rem',
            lineHeight: 1.55,
            whiteSpace: 'pre-wrap',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
            <span style={{ fontWeight: 700, fontSize: '0.8rem', color: border }}>{def.label}</span>
            <span style={{ fontSize: '0.68rem', color: subcolor, fontFamily: 'monospace' }}>MODEL.md {def.section}</span>
          </div>
          <p style={{ margin: 0, color: subcolor }}>{def.body}</p>
        </div>,
        document.body
      )}
    </span>
  )
}
