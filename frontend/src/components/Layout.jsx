import { Outlet, Link, useLocation } from 'react-router-dom'
import { Truck, LayoutDashboard, Radio, ListOrdered, CloudSun, Clock, Settings } from 'lucide-react'

export default function Layout() {
  const { pathname } = useLocation()

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
