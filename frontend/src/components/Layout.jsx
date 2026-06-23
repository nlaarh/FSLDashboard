import { useState, useEffect, useContext, useRef, useCallback } from 'react'
import { Outlet, Link, useLocation } from 'react-router-dom'
import { LayoutDashboard, Radio, ListOrdered, CloudSun, Clock, ArrowRightLeft, Truck, Navigation, Settings, HelpCircle, LogOut, Bug, Search, Loader2, DollarSign, BrainCircuit, FileText, Sun, Moon, X as XIcon } from 'lucide-react'
import FloatingChat from './FloatingChat'
import { fetchFeatures, searchQuery } from '../api'
import { SAReportContext } from '../contexts/SAReportContext'

/* ── FleetPulse Logo (AI Brain + Fleet Routes) ────────────────────────── */
function Logo({ className = '' }) {
  return (
    <svg viewBox="0 0 32 32" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
      {/* Brain outline — left hemisphere */}
      <path d="M16 4 C12 4 9 5.5 8 8 C6.5 8.2 5 9.5 5 12 C4 12.5 3 14 3 16 C3 18.5 4.5 20 6 20.5 C6.5 22.5 8 24 10 24.5 C11 26.5 13 28 16 28"
        stroke="#60a5fa" strokeWidth="1.8" strokeLinecap="round" fill="none" />
      {/* Brain outline — right hemisphere */}
      <path d="M16 4 C20 4 23 5.5 24 8 C25.5 8.2 27 9.5 27 12 C28 12.5 29 14 29 16 C29 18.5 27.5 20 26 20.5 C25.5 22.5 24 24 22 24.5 C21 26.5 19 28 16 28"
        stroke="#3b82f6" strokeWidth="1.8" strokeLinecap="round" fill="none" />
      {/* Brain center fold */}
      <path d="M16 6 L16 26" stroke="#334155" strokeWidth="0.8" strokeDasharray="2 2" />
      {/* Neural network nodes */}
      <circle cx="10" cy="11" r="1.8" fill="#6366f1" />
      <circle cx="22" cy="11" r="1.8" fill="#6366f1" />
      <circle cx="8" cy="17" r="1.8" fill="#818cf8" />
      <circle cx="24" cy="17" r="1.8" fill="#818cf8" />
      <circle cx="12" cy="22" r="1.8" fill="#a78bfa" />
      <circle cx="20" cy="22" r="1.8" fill="#a78bfa" />
      <circle cx="16" cy="14" r="2" fill="#4f46e5" />
      {/* Neural connections — route-like lines between nodes */}
      <line x1="10" y1="11" x2="16" y2="14" stroke="#818cf8" strokeWidth="0.8" opacity="0.6" />
      <line x1="22" y1="11" x2="16" y2="14" stroke="#818cf8" strokeWidth="0.8" opacity="0.6" />
      <line x1="8" y1="17" x2="16" y2="14" stroke="#818cf8" strokeWidth="0.8" opacity="0.6" />
      <line x1="24" y1="17" x2="16" y2="14" stroke="#818cf8" strokeWidth="0.8" opacity="0.6" />
      <line x1="8" y1="17" x2="12" y2="22" stroke="#a78bfa" strokeWidth="0.8" opacity="0.5" />
      <line x1="24" y1="17" x2="20" y2="22" stroke="#a78bfa" strokeWidth="0.8" opacity="0.5" />
      <line x1="10" y1="11" x2="8" y2="17" stroke="#818cf8" strokeWidth="0.8" opacity="0.5" />
      <line x1="22" y1="11" x2="24" y2="17" stroke="#818cf8" strokeWidth="0.8" opacity="0.5" />
      {/* Small pulse on center node — AI activity */}
      <circle cx="16" cy="14" r="3.5" stroke="#6366f1" strokeWidth="0.6" opacity="0.3">
        <animate attributeName="r" values="2.5;4;2.5" dur="2s" repeatCount="indefinite" />
        <animate attributeName="opacity" values="0.4;0.1;0.4" dur="2s" repeatCount="indefinite" />
      </circle>
    </svg>
  )
}

function SASearch() {
  const [query, setQuery]   = useState('')
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [open, setOpen]     = useState(false)
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
      setQuery('')
      setResults(null)
      setOpen(false)
      return
    }
    setLoading(true)
    try {
      const data = await searchQuery(q)
      setResults(data.results || [])
      setOpen(true)
    } catch {
      setResults([])
      setOpen(true)
    } finally {
      setLoading(false)
    }
  }

  const openSA = (saNumber) => {
    ctx?.open(saNumber)
    setQuery('')
    setResults(null)
    setOpen(false)
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

export default function Layout() {
  const { pathname } = useLocation()
  const [features, setFeatures] = useState({})
  const [department, setDepartment] = useState('')
  const [role, setRole] = useState('')
  const [name, setName] = useState('')
  const [impersonating, setImpersonating] = useState(() => {
    try { return JSON.parse(sessionStorage.getItem('impersonating') || 'null') } catch { return null }
  })
  const [theme, setTheme] = useState(() => localStorage.getItem('fp_theme') || 'dark')

  useEffect(() => {
    document.documentElement.classList.toggle('light', theme === 'light')
    localStorage.setItem('fp_theme', theme)
  }, [theme])

  useEffect(() => {
    fetchFeatures().then(setFeatures).catch(() => {})
    fetch('/api/auth/me').then(r => r.json()).then(d => {
      setDepartment(d.department || '')
      setRole(d.role || '')
      setName(d.name || '')
    }).catch(() => {})
    const handler = (e) => {
      if (e.detail) setFeatures(e.detail)
      else fetchFeatures().then(setFeatures).catch(() => {})
    }
    window.addEventListener('featuresChanged', handler)
    return () => window.removeEventListener('featuresChanged', handler)
  }, [])

  // finance = accounting only; supervisor = no accounting/admin; everyone else = everything
  const isFinance = department === 'finance'
  const isSupervisor = role === 'ers-supervisor' || role === 'ers-member-relations'

  const handleLogout = async () => {
    try {
      await fetch('/api/auth/logout', { method: 'POST' })
    } catch { /* ignore */ }
    sessionStorage.removeItem('impersonating')
    window.location.href = '/'
  }

  const returnToSelf = async () => {
    const origin = impersonating
    sessionStorage.removeItem('impersonating')
    setImpersonating(null)
    // Ask server to restore the original httponly cookie
    if (origin?.originCookie) {
      await fetch('/api/admin/impersonate/return', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ origin_cookie: origin.originCookie }),
      }).catch(() => {})
    } else {
      await fetch('/api/auth/logout', { method: 'POST' }).catch(() => {})
    }
    window.location.href = '/admin'
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {impersonating && (
        <div className="bg-amber-500/15 border-b border-amber-500/30 px-6 py-2 flex items-center gap-3 text-xs">
          <span className="text-amber-300 font-semibold">Viewing as {impersonating.name}</span>
          <span className="text-amber-500/70 px-2 py-0.5 rounded bg-amber-500/10 border border-amber-500/20">{impersonating.role}</span>
          <span className="text-slate-500 flex-1">— You are seeing exactly what this user sees</span>
          <button onClick={returnToSelf}
            className="px-3 py-1 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 font-semibold transition-colors border border-amber-500/30">
            ← Return to your account
          </button>
        </div>
      )}
      {/* Top nav */}
      <nav className="sticky top-0 z-50 glass border-b border-slate-700/50">
        <div className="max-w-[1600px] mx-auto px-6 h-14 flex items-center gap-6">
          <Link to="/" className="flex items-center gap-2 text-white font-semibold text-lg">
            <Logo className="w-7 h-7" />
            <span>Fleet<span className="text-brand-400">Pulse</span></span>
          </Link>
          <div className="flex items-center gap-1 ml-6">
            {!isFinance && (<>
            <Link to="/"
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                pathname === '/' ? 'bg-brand-600/20 text-brand-300' : 'text-slate-400 hover:text-white hover:bg-slate-800'
              }`}>
              <Radio className="w-4 h-4 inline mr-1.5 -mt-0.5" />Command Center
            </Link>
            <Link to="/garages"
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                pathname === '/garages' || pathname.startsWith('/garage/') ? 'bg-brand-600/20 text-brand-300' : 'text-slate-400 hover:text-white hover:bg-slate-800'
              }`}>
              <LayoutDashboard className="w-4 h-4 inline mr-1.5 -mt-0.5" />Garages
            </Link>
            <Link to="/queue"
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                pathname === '/queue' ? 'bg-brand-600/20 text-brand-300' : 'text-slate-400 hover:text-white hover:bg-slate-800'
              }`}>
              <ListOrdered className="w-4 h-4 inline mr-1.5 -mt-0.5" />Queue
            </Link>
            <Link to="/forecast"
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                pathname === '/forecast' ? 'bg-brand-600/20 text-brand-300' : 'text-slate-400 hover:text-white hover:bg-slate-800'
              }`}>
              <CloudSun className="w-4 h-4 inline mr-1.5 -mt-0.5" />Forecast
            </Link>
            {features.pta_advisor !== false && (
              <Link to="/pta"
                className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                  pathname === '/pta' ? 'bg-brand-600/20 text-brand-300' : 'text-slate-400 hover:text-white hover:bg-slate-800'
                }`}>
                <Clock className="w-4 h-4 inline mr-1.5 -mt-0.5" />PTA Advisor
              </Link>
            )}
            {features.onroute !== false && (
              <Link to="/onroute"
                className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                  pathname === '/onroute' ? 'bg-brand-600/20 text-brand-300' : 'text-slate-400 hover:text-white hover:bg-slate-800'
                }`}>
                <Truck className="w-4 h-4 inline mr-1.5 -mt-0.5" />Route Tracker
              </Link>
            )}
            {features.matrix !== false && (
              <Link to="/matrix"
                className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                  pathname === '/matrix' ? 'bg-brand-600/20 text-brand-300' : 'text-slate-400 hover:text-white hover:bg-slate-800'
                }`}>
                <ArrowRightLeft className="w-4 h-4 inline mr-1.5 -mt-0.5" />Insights
              </Link>
            )}
            </>)}
            {features.accounting !== false && !isSupervisor && (
            <Link to="/accounting"
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                pathname === '/accounting' ? 'bg-brand-600/20 text-brand-300' : 'text-slate-400 hover:text-white hover:bg-slate-800'
              }`}>
              <DollarSign className="w-4 h-4 inline mr-1.5 -mt-0.5" />Accounting
            </Link>
            )}
            {!isFinance && (
            <Link to="/reporting"
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                pathname === '/reporting' ? 'bg-brand-600/20 text-brand-300' : 'text-slate-400 hover:text-white hover:bg-slate-800'
              }`}>
              <FileText className="w-4 h-4 inline mr-1.5 -mt-0.5" />Reporting
            </Link>
            )}
          </div>
          <div className="ml-auto flex items-center gap-1">
            <SASearch />
            <div className="w-px h-5 bg-slate-700/50 mx-1" />
            <Link to="/issues" title="Report / Track Bugs"
              className={`p-1.5 rounded-lg transition-all ${
                pathname === '/issues' ? 'text-amber-400' : 'text-slate-500 hover:text-amber-400 hover:bg-amber-500/10'
              }`}>
              <Bug className="w-4 h-4" />
            </Link>
            <Link to="/help" title="Help Center"
              className={`p-1.5 rounded-lg transition-all ${
                pathname === '/help' ? 'text-brand-400' : 'text-slate-500 hover:text-slate-300'
              }`}>
              <HelpCircle className="w-4 h-4" />
            </Link>
            {!isFinance && (role === 'superadmin' || role === 'admin' || role === 'executive' || role === 'ers-director') && (
            <Link to="/admin" title="Settings"
              className={`p-1.5 rounded-lg transition-all ${
                pathname === '/admin' ? 'text-brand-400' : 'text-slate-500 hover:text-slate-300'
              }`}>
              <Settings className="w-4 h-4" />
            </Link>
            )}
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

      <main className={`${pathname === '/accounting' ? 'max-w-[1920px]' : 'max-w-[1600px]'} mx-auto px-6 py-6`}>
        <Outlet />
      </main>

      <FloatingChat />
    </div>
  )
}
