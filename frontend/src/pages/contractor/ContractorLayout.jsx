import { useState, useEffect, useContext, useRef } from 'react'
import { Outlet, Link, useLocation } from 'react-router-dom'
import {
  Star, LayoutDashboard, Clock, DollarSign,
  LogOut, Search, Loader2, Sun, Moon, X as XIcon, Building2,
  Radio, Map as MapIcon,
} from 'lucide-react'
import FloatingChat from '../../components/FloatingChat'
import { searchQuery } from '../../api'
import { SAReportContext } from '../../contexts/SAReportContext'

/* ── Logo (reused from Layout) ─────────────────────────────────────────── */
function Logo({ className = '' }) {
  return (
    <svg viewBox="0 0 32 32" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M16 4 C12 4 9 5.5 8 8 C6.5 8.2 5 9.5 5 12 C4 12.5 3 14 3 16 C3 18.5 4.5 20 6 20.5 C6.5 22.5 8 24 10 24.5 C11 26.5 13 28 16 28"
        stroke="#60a5fa" strokeWidth="1.8" strokeLinecap="round" fill="none" />
      <path d="M16 4 C20 4 23 5.5 24 8 C25.5 8.2 27 9.5 27 12 C28 12.5 29 14 29 16 C29 18.5 27.5 20 26 20.5 C25.5 22.5 24 24 22 24.5 C21 26.5 19 28 16 28"
        stroke="#3b82f6" strokeWidth="1.8" strokeLinecap="round" fill="none" />
      <path d="M16 6 L16 26" stroke="#334155" strokeWidth="0.8" strokeDasharray="2 2" />
      <circle cx="10" cy="11" r="1.8" fill="#6366f1" />
      <circle cx="22" cy="11" r="1.8" fill="#6366f1" />
      <circle cx="8" cy="17" r="1.8" fill="#818cf8" />
      <circle cx="24" cy="17" r="1.8" fill="#818cf8" />
      <circle cx="12" cy="22" r="1.8" fill="#a78bfa" />
      <circle cx="20" cy="22" r="1.8" fill="#a78bfa" />
      <circle cx="16" cy="14" r="2" fill="#4f46e5" />
      <line x1="10" y1="11" x2="16" y2="14" stroke="#818cf8" strokeWidth="0.8" opacity="0.6" />
      <line x1="22" y1="11" x2="16" y2="14" stroke="#818cf8" strokeWidth="0.8" opacity="0.6" />
      <line x1="8" y1="17" x2="16" y2="14" stroke="#818cf8" strokeWidth="0.8" opacity="0.6" />
      <line x1="24" y1="17" x2="16" y2="14" stroke="#818cf8" strokeWidth="0.8" opacity="0.6" />
      <line x1="8" y1="17" x2="12" y2="22" stroke="#a78bfa" strokeWidth="0.8" opacity="0.5" />
      <line x1="24" y1="17" x2="20" y2="22" stroke="#a78bfa" strokeWidth="0.8" opacity="0.5" />
      <line x1="10" y1="11" x2="8" y2="17" stroke="#818cf8" strokeWidth="0.8" opacity="0.5" />
      <line x1="22" y1="11" x2="24" y2="17" stroke="#818cf8" strokeWidth="0.8" opacity="0.5" />
      <circle cx="16" cy="14" r="3.5" stroke="#6366f1" strokeWidth="0.6" opacity="0.3">
        <animate attributeName="r" values="2.5;4;2.5" dur="2s" repeatCount="indefinite" />
        <animate attributeName="opacity" values="0.4;0.1;0.4" dur="2s" repeatCount="indefinite" />
      </circle>
    </svg>
  )
}

/* ── SASearch (self-contained, same as Layout) ─────────────────────────── */
function SASearch() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const ctx = useContext(SAReportContext)
  const wrapRef = useRef(null)

  const isSaDirect = (q) => {
    const u = q.toUpperCase()
    return u.startsWith('SA-') || (/^\d+$/.test(q) && q.length <= 7)
  }

  const handleSubmit = async (e) => {
    e?.preventDefault()
    const q = query.trim()
    if (!q) return
    if (isSaDirect(q)) {
      const num = q.toUpperCase().startsWith('SA-') ? q.toUpperCase() : `SA-${q}`
      ctx?.open(num)
      setQuery(''); setResults(null); setOpen(false)
      return
    }
    setLoading(true)
    try {
      const data = await searchQuery(q)
      setResults(data.results || [])
      setOpen(true)
    } catch {
      setResults([]); setOpen(true)
    } finally {
      setLoading(false)
    }
  }

  const openSA = (saNumber) => {
    ctx?.open(saNumber)
    setQuery(''); setResults(null); setOpen(false)
  }

  const clearResults = () => { setResults(null); setOpen(false); setQuery('') }

  useEffect(() => {
    const handler = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <div ref={wrapRef} style={{ position: 'relative' }}>
      <form onSubmit={handleSubmit} className="flex items-center gap-1">
        <div className="relative">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => results && setOpen(true)}
            placeholder="SA#, WO#, Member # or Name"
            className="w-52 focus:w-72 transition-all bg-slate-800/50 border border-slate-700/50 rounded-lg pl-3 pr-6 py-1 text-[11px] text-slate-300 placeholder-slate-600 focus:outline-none focus:border-indigo-500/50 focus:bg-slate-800"
          />
          {query && (
            <button type="button" onClick={clearResults}
              style={{ position: 'absolute', right: 6, top: '50%', transform: 'translateY(-50%)',
                       background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>
              <XIcon size={11} color="#475569" />
            </button>
          )}
        </div>
        <button type="submit"
          style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '3px 8px',
                   background: 'rgba(99,102,241,0.15)', border: '1px solid rgba(99,102,241,0.3)',
                   borderRadius: 6, cursor: 'pointer', color: '#818cf8', fontSize: 11 }}>
          {loading ? <Loader2 size={12} className="animate-spin" /> : <Search size={12} />}
          {loading ? 'Searching…' : 'Search'}
        </button>
      </form>

      {open && results !== null && (
        <div style={{
          position: 'absolute', right: 0, top: 'calc(100% + 6px)',
          width: 380, maxHeight: 420, overflowY: 'auto',
          background: '#0f172a', border: '1px solid #1e293b',
          borderRadius: 10, boxShadow: '0 12px 32px rgba(0,0,0,0.7)',
          zIndex: 10000,
        }}>
          {results.length === 0 ? (
            <div style={{ padding: '14px 16px', color: '#64748b', fontSize: 12, textAlign: 'center' }}>
              No results found
            </div>
          ) : results.map((r, i) => (
            <div key={i} style={{
              padding: '10px 14px',
              borderBottom: i < results.length - 1 ? '1px solid #1e293b' : 'none',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 3 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: '#e2e8f0' }}>
                  {r.wo_number}
                  {r.customer_name && (
                    <span style={{ fontWeight: 400, color: '#94a3b8', marginLeft: 8, fontSize: 11 }}>
                      {r.customer_name}
                    </span>
                  )}
                </div>
                <span style={{ fontSize: 10, color: '#475569', flexShrink: 0, marginLeft: 8 }}>{r.created}</span>
              </div>
              <div style={{ fontSize: 11, color: '#64748b', marginBottom: 7, display: 'flex', flexWrap: 'wrap', gap: '2px 10px' }}>
                {r.facility && <span>{r.facility}</span>}
                {r.service_datetime && <span>{r.service_datetime}</span>}
                {r.work_type && <span>{r.work_type}</span>}
                {r.status && (
                  <span style={{ color: r.status === 'Completed' ? '#10b981' : r.status === 'Canceled' ? '#ef4444' : '#94a3b8' }}>
                    {r.status}
                  </span>
                )}
              </div>
              <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                {r.sa_numbers.length > 0
                  ? r.sa_numbers.map(saNum => (
                    <button key={saNum} onClick={() => openSA(saNum)}
                      style={{
                        padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 700,
                        background: 'rgba(99,102,241,0.15)', border: '1px solid rgba(99,102,241,0.3)',
                        color: '#818cf8', cursor: 'pointer',
                      }}>
                      {saNum}
                    </button>
                  ))
                  : <span style={{ fontSize: 10, color: '#334155' }}>No SAs</span>
                }
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ── ContractorLayout ──────────────────────────────────────────────────── */
export default function ContractorLayout() {
  const { pathname } = useLocation()
  const [name, setName] = useState('')
  const [garageNames, setGarageNames] = useState([])
  const [theme, setTheme] = useState(() => localStorage.getItem('fp_theme') || 'dark')

  useEffect(() => {
    document.documentElement.classList.toggle('light', theme === 'light')
    localStorage.setItem('fp_theme', theme)
  }, [theme])

  useEffect(() => {
    fetch('/api/auth/me').then(r => r.json()).then(d => {
      setName(d.name || '')
      setGarageNames(d.garage_names || [])
    }).catch(() => {})
  }, [])

  // Dispatch + Map are unreleased: shown only where the backend flag is on.
  const [showDispatch, setShowDispatch] = useState(false)
  useEffect(() => {
    fetch('/api/features').then(r => r.json())
      .then(f => setShowDispatch(!!f.contractor_dispatch))
      .catch(() => {})
  }, [])

  // Map is on-platform only. Off-platform (Towbook) vendors have no driver
  // telemetry, so hide the link rather than let them reach a dead end.
  const [showMap, setShowMap] = useState(false)
  useEffect(() => {
    if (!showDispatch) return
    fetch('/api/contractor/map/available').then(r => r.json())
      .then(d => setShowMap(!!d.available))
      .catch(() => {})
  }, [showDispatch])

  const handleLogout = async () => {
    try { await fetch('/api/auth/logout', { method: 'POST' }) } catch { /* ignore */ }
    window.location.href = '/'
  }

  const navLinks = [
    { to: '/contractor/watchlist', icon: <Star className="w-4 h-4 inline mr-1.5 -mt-0.5" />, label: 'Watchlist' },
    { to: '/contractor/garages',   icon: <LayoutDashboard className="w-4 h-4 inline mr-1.5 -mt-0.5" />, label: 'Garages' },
    { to: '/contractor/pta',       icon: <Clock className="w-4 h-4 inline mr-1.5 -mt-0.5" />, label: 'PTA Advisor' },
    { to: '/contractor/accounting', icon: <DollarSign className="w-4 h-4 inline mr-1.5 -mt-0.5" />, label: 'Accounting' },
    ...(showDispatch ? [
      { to: '/contractor/dispatch', icon: <Radio className="w-4 h-4 inline mr-1.5 -mt-0.5" />, label: 'Dispatch' },
    ] : []),
    ...(showDispatch && showMap ? [
      { to: '/contractor/map',      icon: <MapIcon className="w-4 h-4 inline mr-1.5 -mt-0.5" />, label: 'Map' },
    ] : []),
  ]

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {/* Contractor identity banner */}
      <div className="bg-indigo-600/10 border-b border-indigo-500/20 px-6 py-1.5 flex items-center gap-2 text-xs">
        <Building2 size={13} className="text-indigo-400 flex-shrink-0" />
        <span className="text-indigo-300 font-semibold">Contractor Portal</span>
        {garageNames.length > 0 && (
          <>
            <span className="text-slate-600">—</span>
            <span className="text-slate-400">{garageNames.map(g => typeof g === 'string' ? g : g.name).join(', ')}</span>
          </>
        )}
      </div>

      {/* Top nav */}
      <nav className="sticky top-0 z-50 glass border-b border-slate-700/50">
        <div className="max-w-[1600px] mx-auto px-6 h-14 flex items-center gap-6">
          <Link to="/contractor/watchlist" className="flex items-center gap-2 text-white font-semibold text-lg">
            <Logo className="w-7 h-7" />
            <span>Fleet<span className="text-brand-400">Pulse</span></span>
          </Link>

          <div className="flex items-center gap-1 ml-6">
            {navLinks.map(({ to, icon, label }) => (
              <Link key={to} to={to}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                  pathname === to || (to !== '/contractor/watchlist' && pathname.startsWith(to))
                    ? 'bg-brand-600/20 text-brand-300'
                    : 'text-slate-400 hover:text-white hover:bg-slate-800'
                }`}>
                {icon}{label}
              </Link>
            ))}
          </div>

          <div className="ml-auto flex items-center gap-1">
            <SASearch />
            <div className="w-px h-5 bg-slate-700/50 mx-1" />
            <button onClick={() => setTheme(t => t === 'dark' ? 'light' : 'dark')}
              title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
              className="p-1.5 rounded-lg text-slate-500 hover:text-slate-300 transition-all">
              {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            </button>
            <div className="w-px h-5 bg-slate-700/50 mx-1" />
            <button onClick={handleLogout} title="Log out"
              className="p-1.5 rounded-lg text-slate-600 hover:text-red-400 hover:bg-red-500/10 transition-all">
              <LogOut className="w-4 h-4" />
            </button>
            {name && <span className="text-[10px] text-slate-400 ml-2 hidden lg:inline">{name}</span>}
          </div>
        </div>
      </nav>

      <main className="max-w-[1600px] mx-auto px-6 py-6">
        <Outlet />
      </main>

      {/* Chatbot disabled for all users (per request). Re-add <FloatingChat /> to re-enable. */}
    </div>
  )
}
