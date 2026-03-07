import { useState, useEffect, useCallback } from 'react'
import { Outlet, Link, useLocation } from 'react-router-dom'
import { Truck, LayoutDashboard, Radio, RefreshCw } from 'lucide-react'
import { fetchHealth, fetchDbStatus, triggerSync } from '../api'

function SyncIndicator() {
  const [syncing, setSyncing] = useState(false)
  const [lastSync, setLastSync] = useState(null)
  const [rowCount, setRowCount] = useState(null)
  const [tooltip, setTooltip] = useState('')

  const checkStatus = useCallback(async () => {
    try {
      const [health, dbStatus] = await Promise.all([fetchHealth(), fetchDbStatus()])
      setSyncing(health.sync_in_progress)
      if (dbStatus.tables?.length) {
        const total = dbStatus.tables.reduce((s, t) => s + (t.row_count || 0), 0)
        setRowCount(total)
        const latest = dbStatus.tables
          .map(t => t.last_sync)
          .filter(Boolean)
          .sort()
          .pop()
        if (latest) {
          const d = new Date(latest + 'Z')
          setLastSync(d)
        }
      }
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    checkStatus()
    const id = setInterval(checkStatus, 15000) // poll every 15s
    return () => clearInterval(id)
  }, [checkStatus])

  const handleSync = async () => {
    setSyncing(true)
    try {
      const result = await triggerSync()
      if (result.status !== 'already_running') {
        setRowCount(prev => {
          const added = (result.service_appointments || 0) + (result.assigned_resources || 0) +
            (result.work_orders || 0) + (result.shifts || 0) + (result.absences || 0) + (result.surveys || 0)
          return (prev || 0) + added
        })
        setLastSync(new Date())
      }
    } catch { /* ignore */ }
    finally { setSyncing(false); checkStatus() }
  }

  const ago = lastSync
    ? Math.round((Date.now() - lastSync.getTime()) / 60000)
    : null

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={handleSync}
        disabled={syncing}
        title={syncing ? 'Syncing...' : 'Force sync from Salesforce'}
        className="p-1.5 rounded-lg transition-all hover:bg-slate-800 disabled:opacity-50"
      >
        <RefreshCw className={`w-4 h-4 ${syncing ? 'animate-spin text-brand-400' : 'text-slate-400 hover:text-white'}`} />
      </button>
      <div className="text-xs text-slate-500 leading-tight">
        {syncing ? (
          <span className="text-brand-400">Syncing...</span>
        ) : (
          <>
            {rowCount != null && <span>{rowCount.toLocaleString()} records</span>}
            {ago != null && <span className="ml-1.5 text-slate-600">{ago < 1 ? 'just now' : `${ago}m ago`}</span>}
          </>
        )}
      </div>
    </div>
  )
}

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
          </div>
          <div className="ml-auto flex items-center gap-4">
            <SyncIndicator />
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
