import { useState } from 'react'
import { Outlet, Link, useLocation } from 'react-router-dom'
import { LayoutDashboard, Radio, ListOrdered, CloudSun, Clock, ArrowRightLeft, Settings, HelpCircle, MessageCircle, LogOut } from 'lucide-react'
import ReportIssue from './ReportIssue'
import FloatingChat from './FloatingChat'

/* ── FleetPulse Logo (inline SVG) ──────────────────────────────────────── */
function Logo({ className = '' }) {
  return (
    <svg viewBox="0 0 32 32" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
      {/* Road / base */}
      <rect x="2" y="22" width="28" height="4" rx="2" fill="#334155" />
      <rect x="6" y="23" width="4" height="2" rx="1" fill="#64748b" />
      <rect x="14" y="23" width="4" height="2" rx="1" fill="#64748b" />
      <rect x="22" y="23" width="4" height="2" rx="1" fill="#64748b" />
      {/* Truck body */}
      <rect x="4" y="12" width="16" height="10" rx="2" fill="#3b82f6" />
      <rect x="20" y="15" width="8" height="7" rx="1.5" fill="#2563eb" />
      {/* Windshield */}
      <rect x="21" y="16" width="5" height="4" rx="1" fill="#93c5fd" opacity="0.6" />
      {/* Wheels */}
      <circle cx="10" cy="22" r="3" fill="#1e293b" />
      <circle cx="10" cy="22" r="1.5" fill="#475569" />
      <circle cx="24" cy="22" r="3" fill="#1e293b" />
      <circle cx="24" cy="22" r="1.5" fill="#475569" />
      {/* Pulse line */}
      <polyline points="1,8 7,8 9,4 12,12 15,6 18,8 22,8" stroke="#60a5fa" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      <polyline points="22,8 26,8 28,5 30,8" stroke="#3b82f6" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none" opacity="0.5" />
    </svg>
  )
}

export default function Layout() {
  const { pathname } = useLocation()
  const [chatOpen, setChatOpen] = useState(false)

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
            <Link
              to="/"
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                pathname === '/'
                  ? 'bg-brand-600/20 text-brand-300'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800'
              }`}
            >
              <Radio className="w-4 h-4 inline mr-1.5 -mt-0.5" />
              Command Center
            </Link>
            <Link
              to="/garages"
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                pathname === '/garages' || pathname.startsWith('/garage/')
                  ? 'bg-brand-600/20 text-brand-300'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800'
              }`}
            >
              <LayoutDashboard className="w-4 h-4 inline mr-1.5 -mt-0.5" />
              Garages
            </Link>
            <Link
              to="/queue"
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                pathname === '/queue'
                  ? 'bg-brand-600/20 text-brand-300'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800'
              }`}
            >
              <ListOrdered className="w-4 h-4 inline mr-1.5 -mt-0.5" />
              Queue
            </Link>
            <Link
              to="/pta"
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                pathname === '/pta'
                  ? 'bg-brand-600/20 text-brand-300'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800'
              }`}
            >
              <Clock className="w-4 h-4 inline mr-1.5 -mt-0.5" />
              PTA Advisor
            </Link>
            <Link
              to="/forecast"
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                pathname === '/forecast'
                  ? 'bg-brand-600/20 text-brand-300'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800'
              }`}
            >
              <CloudSun className="w-4 h-4 inline mr-1.5 -mt-0.5" />
              Forecast
            </Link>
            <Link
              to="/matrix"
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                pathname === '/matrix'
                  ? 'bg-brand-600/20 text-brand-300'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800'
              }`}
            >
              <ArrowRightLeft className="w-4 h-4 inline mr-1.5 -mt-0.5" />
              Territory Matrix
            </Link>
          </div>
          <div className="ml-auto flex items-center gap-1">
            <button
              onClick={() => setChatOpen(o => !o)}
              title="AI Assistant"
              className={`p-1.5 rounded-lg transition-all ${
                chatOpen ? 'text-brand-400 bg-brand-600/10' : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              <MessageCircle className="w-4 h-4" />
            </button>
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
            <button
              onClick={handleLogout}
              title="Log out"
              className="p-1.5 rounded-lg text-slate-600 hover:text-red-400 hover:bg-red-500/10 transition-all"
            >
              <LogOut className="w-4 h-4" />
            </button>
            <span className="text-[10px] text-slate-600 ml-2 hidden lg:inline">AAA WCNY</span>
          </div>
        </div>
      </nav>

      {/* Content */}
      <main className="max-w-[1600px] mx-auto px-6 py-6">
        <Outlet />
      </main>

      <ReportIssue />
      <FloatingChat isOpen={chatOpen} onToggle={() => setChatOpen(false)} />
    </div>
  )
}
