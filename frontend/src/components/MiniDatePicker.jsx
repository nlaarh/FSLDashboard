import { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { Calendar } from 'lucide-react'

const MONTHS    = ['January','February','March','April','May','June','July','August','September','October','November','December']
const DAY_HDR   = ['S','M','T','W','T','F','S']

function toIso(y, m, d) {
  return `${y}-${String(m + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`
}

// Small solid 3-D–style triangle arrows — pure SVG filled polygons, no strokes
function TriLeft()  { return <svg width="7" height="10" viewBox="0 0 7 10"><polygon points="7,0 7,10 0,5" fill="currentColor"/></svg> }
function TriRight() { return <svg width="7" height="10" viewBox="0 0 7 10"><polygon points="0,0 0,10 7,5" fill="currentColor"/></svg> }

export default function MiniDatePicker({ value, onChange, placeholder = 'Select date', min, max }) {
  const todayIso  = toIso(new Date().getFullYear(), new Date().getMonth(), new Date().getDate())
  const parsed    = value ? new Date(value + 'T00:00:00') : null

  const [open, setOpen]           = useState(false)
  const [viewYear, setViewYear]   = useState(parsed?.getFullYear()  ?? new Date().getFullYear())
  const [viewMonth, setViewMonth] = useState(parsed?.getMonth()     ?? new Date().getMonth())
  const [pos, setPos]             = useState({ top: 0, left: 0 })

  const btnRef = useRef(null)
  const popRef = useRef(null)

  // Sync view to external value
  useEffect(() => {
    if (value) {
      const d = new Date(value + 'T00:00:00')
      setViewYear(d.getFullYear())
      setViewMonth(d.getMonth())
    }
  }, [value])

  // Close on outside click
  useEffect(() => {
    const handler = (e) => {
      if (
        btnRef.current && !btnRef.current.contains(e.target) &&
        popRef.current  && !popRef.current.contains(e.target)
      ) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // Compute fixed position when opening
  const handleOpen = () => {
    if (!open && btnRef.current) {
      const r = btnRef.current.getBoundingClientRect()
      setPos({ top: r.bottom + 6, left: r.left })
    }
    setOpen(o => !o)
  }

  const prevMonth = () => {
    if (viewMonth === 0) { setViewMonth(11); setViewYear(y => y - 1) }
    else setViewMonth(m => m - 1)
  }
  const nextMonth = () => {
    if (viewMonth === 11) { setViewMonth(0); setViewYear(y => y + 1) }
    else setViewMonth(m => m + 1)
  }

  // Build 42-cell calendar grid
  const firstDay    = new Date(viewYear, viewMonth, 1).getDay()
  const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate()
  const daysInPrev  = new Date(viewYear, viewMonth, 0).getDate()

  const cells = []
  for (let i = firstDay - 1; i >= 0; i--) {
    const m = viewMonth === 0 ? 11 : viewMonth - 1
    const y = viewMonth === 0 ? viewYear - 1 : viewYear
    cells.push({ day: daysInPrev - i, month: m, year: y, outside: true })
  }
  for (let d = 1; d <= daysInMonth; d++) {
    cells.push({ day: d, month: viewMonth, year: viewYear, outside: false })
  }
  let nxt = 1
  while (cells.length < 42) {
    const m = viewMonth === 11 ? 0 : viewMonth + 1
    const y = viewMonth === 11 ? viewYear + 1 : viewYear
    cells.push({ day: nxt++, month: m, year: y, outside: true })
  }

  const select = (y, m, d) => {
    const iso = toIso(y, m, d)
    if (min && iso < min) return
    if (max && iso > max) return
    onChange(iso)
    setOpen(false)
  }

  const label = parsed
    ? parsed.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
    : ''

  return (
    <>
      {/* ── Trigger button ── */}
      <button
        ref={btnRef}
        type="button"
        onClick={handleOpen}
        className="flex items-center gap-2 bg-slate-800 border border-slate-700 rounded-lg
                   px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/50
                   hover:border-slate-500 transition-colors min-w-[130px]"
      >
        <span className={label ? 'text-slate-200' : 'text-slate-500'}>
          {label || placeholder}
        </span>
        <Calendar size={13} className="text-slate-400 shrink-0 ml-auto" />
      </button>

      {/* ── Dropdown — portal-rendered on document.body so it is never clipped ── */}
      {open && createPortal(
        <div
          ref={popRef}
          style={{
            position: 'fixed',
            top:  pos.top,
            left: pos.left,
            zIndex: 99999,
            background: '#0f172a',
            border: '1px solid #1e293b',
            borderRadius: 12,
            padding: 12,
            boxShadow: '0 16px 48px rgba(0,0,0,0.85)',
            width: 252,
          }}
        >
          {/* Month / year header */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
            <button
              type="button"
              onClick={prevMonth}
              title="Previous month"
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                padding: '4px 8px', color: '#94a3b8', borderRadius: 6,
                display: 'flex', alignItems: 'center',
              }}
              onMouseEnter={e => { e.currentTarget.style.color = '#e2e8f0'; e.currentTarget.style.background = 'rgba(255,255,255,0.06)' }}
              onMouseLeave={e => { e.currentTarget.style.color = '#94a3b8'; e.currentTarget.style.background = 'none' }}
            >
              <TriLeft />
            </button>

            <span style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', userSelect: 'none' }}>
              {MONTHS[viewMonth]} {viewYear}
            </span>

            <button
              type="button"
              onClick={nextMonth}
              title="Next month"
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                padding: '4px 8px', color: '#94a3b8', borderRadius: 6,
                display: 'flex', alignItems: 'center',
              }}
              onMouseEnter={e => { e.currentTarget.style.color = '#e2e8f0'; e.currentTarget.style.background = 'rgba(255,255,255,0.06)' }}
              onMouseLeave={e => { e.currentTarget.style.color = '#94a3b8'; e.currentTarget.style.background = 'none' }}
            >
              <TriRight />
            </button>
          </div>

          {/* Day-of-week headers */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 2, marginBottom: 4 }}>
            {DAY_HDR.map((d, i) => (
              <div key={i} style={{ textAlign: 'center', fontSize: 10, color: '#475569', fontWeight: 600, padding: '2px 0' }}>
                {d}
              </div>
            ))}
          </div>

          {/* Day cells */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 2 }}>
            {cells.map((c, i) => {
              const iso      = toIso(c.year, c.month, c.day)
              const disabled = (min && iso < min) || (max && iso > max)
              const selected = iso === value
              const isToday  = iso === todayIso
              return (
                <button
                  key={i}
                  type="button"
                  disabled={disabled}
                  onClick={() => select(c.year, c.month, c.day)}
                  style={{
                    textAlign: 'center', fontSize: 11, borderRadius: 6, padding: '5px 0',
                    background: selected ? '#4f46e5' : isToday ? 'rgba(79,70,229,0.2)' : 'transparent',
                    color: selected ? '#fff' : c.outside ? '#334155' : disabled ? '#1e293b' : '#e2e8f0',
                    border: isToday && !selected ? '1px solid rgba(99,102,241,0.5)' : '1px solid transparent',
                    cursor: disabled ? 'default' : 'pointer',
                    fontWeight: selected ? 700 : 400,
                    transition: 'background 0.1s',
                  }}
                  onMouseEnter={e => { if (!selected && !disabled) e.currentTarget.style.background = 'rgba(255,255,255,0.07)' }}
                  onMouseLeave={e => { if (!selected && !disabled) e.currentTarget.style.background = isToday ? 'rgba(79,70,229,0.2)' : 'transparent' }}
                >
                  {c.day}
                </button>
              )
            })}
          </div>

          {/* Footer */}
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 10, paddingTop: 8, borderTop: '1px solid #1e293b' }}>
            <button
              type="button"
              onClick={() => { onChange(''); setOpen(false) }}
              style={{ fontSize: 12, color: '#3b82f6', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
              onMouseEnter={e => e.currentTarget.style.color = '#93c5fd'}
              onMouseLeave={e => e.currentTarget.style.color = '#3b82f6'}
            >
              Clear
            </button>
            <button
              type="button"
              onClick={() => { onChange(todayIso); setOpen(false) }}
              style={{ fontSize: 12, color: '#3b82f6', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
              onMouseEnter={e => e.currentTarget.style.color = '#93c5fd'}
              onMouseLeave={e => e.currentTarget.style.color = '#3b82f6'}
            >
              Today
            </button>
          </div>
        </div>
      , document.body)}
    </>
  )
}
