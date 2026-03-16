import { useState, useEffect } from 'react'
import { Outlet, Link, useLocation } from 'react-router-dom'
import { LayoutDashboard, Radio, ListOrdered, CloudSun, Clock, ArrowRightLeft, Truck, Navigation, Settings, HelpCircle, LogOut } from 'lucide-react'
import FloatingChat from './FloatingChat'
import { fetchFeatures } from '../api'

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

export default function Layout() {
  const { pathname } = useLocation()
  const [features, setFeatures] = useState({})

  const loadFeatures = () => fetchFeatures().then(setFeatures).catch(() => {})
  useEffect(() => {
    loadFeatures()
    // Re-fetch when admin toggles features
    const handler = () => loadFeatures()
    window.addEventListener('featuresChanged', handler)
    return () => window.removeEventListener('featuresChanged', handler)
  }, [])

  const handleLogout = async () => {
    try {
      await fetch('/api/auth/logout', { method: 'POST' })
    } catch { /* ignore */ }
    window.location.href = '/login'
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {/* Top nav */}
      <nav className="sticky top-0 z-50 glass border-b border-slate-700/50">
        <div className="max-w-[1600px] mx-auto px-6 h-14 flex items-center gap-6">
          <Link to="/" className="flex items-center gap-2 text-white font-semibold text-lg">
            <Logo className="w-7 h-7" />
            <span>Fleet<span className="text-brand-400">Pulse</span></span>
          </Link>
          <div className="flex items-center gap-1 ml-6">
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
          </div>
          <div className="ml-auto flex items-center gap-1">
            <Link to="/help" title="Help Center"
              className={`p-1.5 rounded-lg transition-all ${
                pathname === '/help' ? 'text-brand-400' : 'text-slate-500 hover:text-slate-300'
              }`}>
              <HelpCircle className="w-4 h-4" />
            </Link>
            <Link to="/admin" title="Settings"
              className={`p-1.5 rounded-lg transition-all ${
                pathname === '/admin' ? 'text-brand-400' : 'text-slate-500 hover:text-slate-300'
              }`}>
              <Settings className="w-4 h-4" />
            </Link>
            <div className="w-px h-5 bg-slate-700/50 mx-1" />
            <button onClick={handleLogout} title="Log out"
              className="p-1.5 rounded-lg text-slate-600 hover:text-red-400 hover:bg-red-500/10 transition-all">
              <LogOut className="w-4 h-4" />
            </button>
            <span className="text-[10px] text-slate-600 ml-2 hidden lg:inline">AAA WCNY</span>
          </div>
        </div>
      </nav>

      <main className="max-w-[1600px] mx-auto px-6 py-6">
        <Outlet />
      </main>

      <FloatingChat />
    </div>
  )
}
