import { useState, useRef, useEffect } from 'react'
import { Outlet, Link, useLocation } from 'react-router-dom'
import { Truck, LayoutDashboard, Radio, ListOrdered, CloudSun, Clock, Settings, Grid3X3, Lightbulb, ChevronDown } from 'lucide-react'

export default function Layout() {
  const { pathname } = useLocation()
  const [insightsOpen, setInsightsOpen] = useState(false)
  const dropdownRef = useRef(null)

  const insightPaths = ['/pta', '/matrix', '/forecast']
  const isInsightActive = insightPaths.some(p => pathname === p)

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setInsightsOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // Close dropdown on navigation
  useEffect(() => { setInsightsOpen(false) }, [pathname])

  const navLink = (to, icon, label, isActive) => (
    <Link to={to}
      className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
        isActive ? 'bg-brand-600/20 text-brand-300' : 'text-slate-400 hover:text-white hover:bg-slate-800'
      }`}>
      {icon}
      {label}
    </Link>
  )

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {/* Top nav */}
      <nav className="sticky top-0 z-50 glass border-b border-slate-700/50">
        <div className="max-w-[1600px] mx-auto px-6 h-14 flex items-center gap-6">
          <Link to="/" className="flex items-center gap-2 text-white font-semibold text-lg">
            <Truck className="w-6 h-6 text-brand-400" />
            <span>FSL<span className="text-brand-400">App</span></span>
          </Link>
          <div className="flex items-center gap-1 ml-6">
            {navLink('/', <Radio className="w-4 h-4 inline mr-1.5 -mt-0.5" />, 'Command Center', pathname === '/')}
            {navLink('/garages', <LayoutDashboard className="w-4 h-4 inline mr-1.5 -mt-0.5" />, 'Garages', pathname === '/garages' || pathname.startsWith('/garage/'))}
            {navLink('/queue', <ListOrdered className="w-4 h-4 inline mr-1.5 -mt-0.5" />, 'Queue', pathname === '/queue')}

            {/* Insights dropdown */}
            <div className="relative" ref={dropdownRef}>
              <button onClick={() => setInsightsOpen(!insightsOpen)}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all flex items-center gap-1 ${
                  isInsightActive ? 'bg-brand-600/20 text-brand-300' : 'text-slate-400 hover:text-white hover:bg-slate-800'
                }`}>
                <Lightbulb className="w-4 h-4 -mt-0.5" />
                Insights
                <ChevronDown className={`w-3 h-3 transition-transform ${insightsOpen ? 'rotate-180' : ''}`} />
              </button>

              {insightsOpen && (
                <div className="absolute top-full left-0 mt-1 w-56 glass rounded-xl border border-slate-700/50 py-1.5 shadow-xl">
                  <Link to="/pta"
                    className={`flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
                      pathname === '/pta' ? 'text-brand-300 bg-brand-600/10' : 'text-slate-400 hover:text-white hover:bg-slate-800/50'
                    }`}>
                    <Clock className="w-4 h-4" />
                    <div>
                      <div className="font-medium">PTA Advisor</div>
                      <div className="text-[10px] text-slate-600">Wait time projections</div>
                    </div>
                  </Link>
                  <Link to="/matrix"
                    className={`flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
                      pathname === '/matrix' ? 'text-brand-300 bg-brand-600/10' : 'text-slate-400 hover:text-white hover:bg-slate-800/50'
                    }`}>
                    <Grid3X3 className="w-4 h-4" />
                    <div>
                      <div className="font-medium">Matrix Advisor</div>
                      <div className="text-[10px] text-slate-600">Priority matrix & cascades</div>
                    </div>
                  </Link>
                  <Link to="/forecast"
                    className={`flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
                      pathname === '/forecast' ? 'text-brand-300 bg-brand-600/10' : 'text-slate-400 hover:text-white hover:bg-slate-800/50'
                    }`}>
                    <CloudSun className="w-4 h-4" />
                    <div>
                      <div className="font-medium">Forecast</div>
                      <div className="text-[10px] text-slate-600">Volume & weather forecast</div>
                    </div>
                  </Link>
                </div>
              )}
            </div>
          </div>
          <div className="ml-auto flex items-center gap-4">
            <Link to="/admin" title="Admin"
              className={`p-1.5 rounded-lg transition-all ${
                pathname === '/admin' ? 'text-brand-400' : 'text-slate-600 hover:text-slate-400'
              }`}>
              <Settings className="w-4 h-4" />
            </Link>
            <span className="text-xs text-slate-600">AAA WNYC Field Service</span>
          </div>
        </div>
      </nav>

      {/* Content */}
      <main className="max-w-[1600px] mx-auto px-6 py-6">
        <Outlet />
      </main>
    </div>
  )
}
