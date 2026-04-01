import React, { useState, useEffect, useRef } from 'react'
import ReactDOM from 'react-dom'
import { clsx } from 'clsx'
import { Loader2, ChevronUp, Eye } from 'lucide-react'
import { ResponsiveContainer } from 'recharts'

export function fmtPhone(p) {
  if (!p) return null
  const d = p.replace(/\D/g, '')
  if (d.length === 10) return `(${d.slice(0,3)}) ${d.slice(3,6)}-${d.slice(6)}`
  return p
}

export function fmtWait(min) {
  if (!min || min <= 0) return '—'
  const h = Math.floor(min / 60)
  const m = min % 60
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

export function fmtMin(m) {
  if (m == null) return null
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  const rem = m % 60
  return rem > 0 ? `${h}h ${rem}m` : `${h}h`
}

export function StatChip({ icon: Icon, label, value, color }) {
  return (
    <div className="flex items-center gap-1.5">
      {Icon && <Icon className={clsx('w-3.5 h-3.5', color)} />}
      <div className="text-right">
        <div className={clsx('text-sm font-bold leading-none', color)}>{value?.toLocaleString() ?? '—'}</div>
        <div className="text-[9px] text-slate-500 leading-none mt-0.5">{label}</div>
      </div>
    </div>
  )
}

export function Div() { return <div className="w-px h-8 bg-slate-700/50" /> }

export function LegendDot({ border, fill, label }) {
  return <span className="flex items-center gap-1.5">
    <span className={clsx('w-3 h-3 rounded-full border-2', border, fill)} />
    <span className="text-slate-400">{label}</span>
  </span>
}
export function LegendSmall({ color, label }) {
  return <span className="flex items-center gap-1.5">
    <span className={clsx('w-2 h-2 rounded-full', color)} />
    <span className="text-slate-400">{label}</span>
  </span>
}

export function MiniDonut({ pct, size = 56, stroke = 6, autoColor = '#6366f1', manualColor = '#334155' }) {
  const r = (size - stroke) / 2
  const circ = 2 * Math.PI * r
  const autoLen = circ * (pct / 100)
  return (
    <svg width={size} height={size} className="block">
      {/* Manual (background) */}
      <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={manualColor} strokeWidth={stroke} />
      {/* Auto (foreground) */}
      <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={autoColor} strokeWidth={stroke}
        strokeDasharray={`${autoLen} ${circ - autoLen}`}
        strokeDashoffset={circ / 4} strokeLinecap="round"
        className="transition-all duration-700" />
      {/* Center text */}
      <text x={size/2} y={size/2} textAnchor="middle" dominantBaseline="central"
        className="fill-white text-[11px] font-bold">{pct}%</text>
    </svg>
  )
}

export function InfoTip({ text }) {
  const [open, setOpen] = useState(false)
  const [style, setStyle] = useState({})
  const btnRef = useRef(null)
  const popRef = useRef(null)
  useEffect(() => {
    if (!open) return
    const close = (e) => {
      if (btnRef.current?.contains(e.target) || popRef.current?.contains(e.target)) return
      setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])
  // Reposition after render so we know the popup's actual height
  useEffect(() => {
    if (!open || !popRef.current || !btnRef.current) return
    const btn = btnRef.current.getBoundingClientRect()
    const pop = popRef.current.getBoundingClientRect()
    const vh = window.innerHeight
    const vw = window.innerWidth
    const pad = 12
    // Horizontal: center on button, clamp to viewport
    let left = Math.max(pad, Math.min(btn.left + btn.width / 2 - pop.width / 2, vw - pop.width - pad))
    // Vertical: prefer below the button; if it won't fit, put it above
    let top
    const maxH = vh - pad * 2
    if (btn.bottom + 8 + pop.height <= vh - pad) {
      top = btn.bottom + 8
    } else if (btn.top - 8 - pop.height >= pad) {
      top = btn.top - 8 - pop.height
    } else {
      // Neither fits fully — anchor to bottom of viewport with scroll
      top = Math.max(pad, vh - pop.height - pad)
    }
    setStyle({ zIndex: 99999, position: 'fixed', left, top, maxHeight: maxH })
  }, [open])
  const handleOpen = (e) => {
    e.stopPropagation()
    // Initial position near button — will be corrected by useEffect above
    const rect = e.currentTarget.getBoundingClientRect()
    setStyle({ zIndex: 99999, position: 'fixed', left: rect.left, top: rect.bottom + 8, maxHeight: window.innerHeight - 24 })
    setOpen(o => !o)
  }
  return (
    <span ref={btnRef} className="relative ml-1 inline-flex">
      <button onClick={handleOpen}
        className="inline-flex items-center justify-center w-4 h-4 rounded-full bg-slate-700/60 text-slate-400 hover:text-white hover:bg-indigo-600 cursor-pointer text-[9px] font-bold leading-none transition-colors">?</button>
      {open && ReactDOM.createPortal(
        <div ref={popRef}
          className="w-72 bg-slate-800 border border-slate-600/50 rounded-xl shadow-2xl shadow-black/60 p-3 text-xs text-slate-300 leading-relaxed overflow-y-auto"
          style={style}
          onClick={e => e.stopPropagation()}>
          <div className="whitespace-pre-wrap">{text}</div>
        </div>,
        document.body
      )}
    </span>
  )
}

// ── Inline Drill-Down: icon on each row, expands detail panel below ─────────
export function DrillDown({ fetchFn, renderRow, emptyMsg = 'No data', children }) {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const toggle = (e) => {
    e.stopPropagation()
    if (!open && !data && !loading) {
      setLoading(true)
      fetchFn()
        .then(setData)
        .catch(e => setError(e.message || 'Failed'))
        .finally(() => setLoading(false))
    }
    setOpen(o => !o)
  }

  return (
    <div>
      <div className="flex items-center gap-0">
        <div className="flex-1 min-w-0">{children}</div>
        <button onClick={toggle} title="View details"
          className={clsx('ml-1 p-1 rounded-md transition-all flex-shrink-0',
            open ? 'bg-blue-600/30 text-blue-400' : 'text-slate-600 hover:text-blue-400 hover:bg-slate-800/60')}>
          {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> :
           open ? <ChevronUp className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
        </button>
      </div>
      {open && (
        <div className="mt-1 mb-1 space-y-0.5 animate-in fade-in duration-200 max-h-[400px] overflow-y-auto rounded-lg border border-slate-800/40 bg-slate-950/30 p-2 ml-2">
          {loading && <div className="flex items-center gap-2 text-xs text-slate-500 py-4 justify-center"><Loader2 className="w-4 h-4 animate-spin" /> Loading...</div>}
          {error && <div className="text-xs text-red-400 py-2 text-center">{error}</div>}
          {data && (Array.isArray(data) ? data : []).length === 0 && !loading && (
            <div className="text-xs text-slate-600 py-3 text-center">{emptyMsg}</div>
          )}
          {data && (Array.isArray(data) ? data : []).map((item, i) => (
            <div key={i}>{renderRow(item, i)}</div>
          ))}
        </div>
      )}
    </div>
  )
}

export const CHART_COLORS = { blue: '#3b82f6', green: '#22c55e', amber: '#f59e0b', red: '#ef4444', cyan: '#06b6d4', purple: '#a855f7', slate: '#64748b' }

export function TrendChart({ title, tip, children, aspect = 2.5 }) {
  return (
    <div className="glass rounded-xl border border-slate-700/30 p-4">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-xs font-bold text-white uppercase tracking-wide">{title}</span>
        {tip && <InfoTip text={tip} />}
      </div>
      <ResponsiveContainer width="100%" aspect={aspect}>
        {children}
      </ResponsiveContainer>
    </div>
  )
}
