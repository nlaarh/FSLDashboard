import { Outlet, Link, useLocation } from 'react-router-dom'
import { Truck, LayoutDashboard, Radio, Map } from 'lucide-react'

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
              <LayoutDashboard className="w-4 h-4 inline mr-1.5 -mt-0.5" />
              Garages
            </Link>
            <Link
              to="/command-center"
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                pathname === '/command-center'
                  ? 'bg-brand-600/20 text-brand-300'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800'
              }`}
            >
              <Radio className="w-4 h-4 inline mr-1.5 -mt-0.5" />
              Command Center
            </Link>
            <Link
              to="/map"
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                pathname === '/map'
                  ? 'bg-brand-600/20 text-brand-300'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800'
              }`}
            >
              <Map className="w-4 h-4 inline mr-1.5 -mt-0.5" />
              Map
            </Link>
          </div>
          <div className="ml-auto text-xs text-slate-500">AAA WNYC Field Service</div>
        </div>
      </nav>

      {/* Content */}
      <main className="max-w-[1600px] mx-auto px-6 py-6">
        <Outlet />
      </main>
    </div>
  )
}
