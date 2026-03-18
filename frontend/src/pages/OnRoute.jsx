import { useState, useEffect, useRef } from 'react'
import { fetchOnRoute, createTrackingLink } from '../api'
import { Search, Truck, MapPin, Clock, Copy, Check, ExternalLink, RefreshCw, Phone, User, Navigation, AlertTriangle } from 'lucide-react'

const fmtPhone = (raw) => {
  if (!raw) return null
  const d = raw.replace(/\D/g, '')
  if (d.length === 10) return `(${d.slice(0,3)}) ${d.slice(3,6)}-${d.slice(6)}`
  if (d.length === 11 && d[0] === '1') return `(${d.slice(1,4)}) ${d.slice(4,7)}-${d.slice(7)}`
  return raw
}
import { clsx } from 'clsx'

const STATUS_COLORS = {
  'Dispatched': 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  'En Route': 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  'Travel': 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  'Accepted': 'bg-amber-500/15 text-amber-400 border-amber-500/30',
}

const WT_ICONS = {
  'Battery': '🔋',
  'Tow - Pick Up': '🚛',
  'Tow - Drop Off': '📦',
  'Tire': '⚫',
  'Lockout': '🔑',
  'Fuel Delivery': '⛽',
}

export default function OnRoute() {
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [trackingState, setTrackingState] = useState({}) // sa_id -> {loading, url, copied}
  const [now, setNow] = useState(Date.now())
  const timerRef = useRef(null)
  const tickRef = useRef(null)
  const searchRef = useRef(null)

  const load = async (showSpinner = false) => {
    if (showSpinner) setRefreshing(true)
    try {
      const rows = await fetchOnRoute()
      setData(rows)
      setError(null)
    } catch (e) {
      setError(e.response?.data?.detail || e.message)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    load()
    timerRef.current = setInterval(() => load(), 60000)
    tickRef.current = setInterval(() => setNow(Date.now()), 30000) // update elapsed every 30s
    return () => { clearInterval(timerRef.current); clearInterval(tickRef.current) }
  }, [])

  // Focus search on load
  useEffect(() => { searchRef.current?.focus() }, [loading])

  const filtered = data.filter(sa => {
    if (!search) return true
    const q = search.toLowerCase()
    return (
      (sa.sa_number || '').toLowerCase().includes(q) ||
      (sa.address || '').toLowerCase().includes(q) ||
      (sa.driver_name || '').toLowerCase().includes(q) ||
      (sa.territory_name || '').toLowerCase().includes(q) ||
      (sa.work_type || '').toLowerCase().includes(q)
    )
  })

  const handleTrack = async (sa) => {
    if (!sa.has_driver) return
    // If tracking URL already exists, just show it
    if (sa.tracking_full_url) {
      setTrackingState(s => ({ ...s, [sa.sa_id]: { url: sa.tracking_full_url } }))
      return
    }
    if (sa.tracking_url) {
      const fullUrl = window.location.origin + sa.tracking_url
      setTrackingState(s => ({ ...s, [sa.sa_id]: { url: fullUrl } }))
      return
    }
    setTrackingState(s => ({ ...s, [sa.sa_id]: { loading: true } }))
    try {
      const res = await createTrackingLink(sa.sa_id)
      const fullUrl = window.location.origin + res.url
      // Update the sa in data to reflect new tracking_url
      setData(prev => prev.map(r => r.sa_id === sa.sa_id ? { ...r, tracking_url: res.url, tracking_full_url: fullUrl } : r))
      setTrackingState(s => ({ ...s, [sa.sa_id]: { url: fullUrl } }))
    } catch (e) {
      const msg = e.response?.data?.detail || e.message
      setTrackingState(s => ({ ...s, [sa.sa_id]: { error: msg } }))
    }
  }

  const handleCopy = async (saId, url) => {
    try {
      await navigator.clipboard.writeText(url)
      setTrackingState(s => ({ ...s, [saId]: { ...s[saId], copied: true } }))
      setTimeout(() => setTrackingState(s => ({ ...s, [saId]: { ...s[saId], copied: false } })), 2000)
    } catch {
      // Fallback for non-HTTPS
      const ta = document.createElement('textarea')
      ta.value = url
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      setTrackingState(s => ({ ...s, [saId]: { ...s[saId], copied: true } }))
      setTimeout(() => setTrackingState(s => ({ ...s, [saId]: { ...s[saId], copied: false } })), 2000)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <div className="text-center">
          <RefreshCw className="w-8 h-8 text-brand-400 animate-spin mx-auto" />
          <p className="text-slate-400 mt-3 text-sm">Loading en-route appointments...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <div className="text-center">
          <p className="text-red-400 text-lg font-semibold">Failed to load</p>
          <p className="text-slate-500 text-sm mt-1">{error}</p>
          <button onClick={() => { setLoading(true); load() }}
            className="mt-4 px-4 py-2 bg-brand-600 text-white rounded-lg text-sm hover:bg-brand-500 transition">
            Retry
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <Truck className="w-6 h-6 text-emerald-400" />
            Route Tracker
            <span className="text-base font-medium text-slate-400 bg-slate-800 px-3 py-0.5 rounded-full">
              {data.length} active
            </span>
          </h1>
          <p className="text-sm text-slate-500 mt-1">Track en-route drivers and share live tracking links with customers</p>
        </div>
        <button onClick={() => load(true)} disabled={refreshing}
          className="flex items-center gap-2 px-3 py-2 bg-slate-800 text-slate-300 rounded-lg text-sm hover:bg-slate-700 transition disabled:opacity-50">
          <RefreshCw className={clsx('w-4 h-4', refreshing && 'animate-spin')} />
          {refreshing ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-500" />
        <input ref={searchRef} type="text" placeholder="Search by SA#, address, driver, territory, work type..."
          value={search} onChange={e => setSearch(e.target.value)}
          className="w-full pl-10 pr-4 py-3 bg-slate-900 border border-slate-700/50 rounded-xl text-white
            placeholder:text-slate-500 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500/30
            text-sm" />
        {search && (
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-slate-500">
            {filtered.length} result{filtered.length !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      {/* Cards */}
      {filtered.length === 0 ? (
        <div className="text-center py-16 text-slate-500">
          {search ? 'No appointments match your search.' : 'No en-route appointments right now.'}
        </div>
      ) : (
        <div className="grid gap-3">
          {filtered.map(sa => {
            const ts = trackingState[sa.sa_id] || {}
            const wtIcon = Object.entries(WT_ICONS).find(([k]) => (sa.work_type || '').includes(k))?.[1] || '🔧'
            return (
              <div key={sa.sa_id}
                className={clsx('bg-slate-900/60 border rounded-xl p-4 hover:border-slate-700/60 transition',
                  sa.is_urgent ? 'border-red-500/40 bg-red-950/20' : 'border-slate-800/60')}>
                <div className="flex items-start gap-4">
                  {/* Left: work type icon */}
                  <div className="text-2xl flex-shrink-0 mt-0.5">{wtIcon}</div>

                  {/* Middle: SA info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-bold text-white text-sm">{sa.sa_number}</span>
                      <span className={clsx('text-[10px] font-semibold px-2 py-0.5 rounded-full border',
                        STATUS_COLORS[sa.status] || 'bg-slate-700/30 text-slate-400 border-slate-600/30')}>
                        {sa.status}
                      </span>
                      {sa.is_fleet ? (
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-purple-500/15 text-purple-400 border border-purple-500/30">
                          Fleet
                        </span>
                      ) : (
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-400 border border-amber-500/30">
                          Towbook
                        </span>
                      )}
                      <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-slate-700/30 text-slate-300 border border-slate-600/30">
                        {sa.work_type || 'Unknown'}
                      </span>
                      {sa.is_urgent && (
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-red-500/15 text-red-400 border border-red-500/30 flex items-center gap-1">
                          <AlertTriangle className="w-3 h-3" />URGENT
                        </span>
                      )}
                    </div>

                    {sa.is_urgent && sa.urgent_reason && (
                      <div className="mt-1.5 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-md px-2.5 py-1">
                        {sa.urgent_reason}
                      </div>
                    )}

                    <div className="flex items-center gap-1.5 mt-1.5 text-sm text-slate-300">
                      <MapPin className="w-3.5 h-3.5 text-slate-500 flex-shrink-0" />
                      <span className="truncate">{sa.address || 'No address'}</span>
                    </div>

                    <div className="flex items-center gap-4 mt-1.5 text-xs text-slate-500 flex-wrap">
                      <span className="flex items-center gap-1">
                        <User className="w-3 h-3" />
                        <span className={sa.has_driver ? 'text-slate-300' : 'text-amber-500'}>{sa.driver_name}</span>
                      </span>
                      <span className="flex items-center gap-1">
                        <Truck className="w-3 h-3" />{sa.territory_name}
                      </span>
                      <span className="flex items-center gap-1">
                        <Clock className="w-3 h-3" />{sa.created_time}
                      </span>
                      {sa.customer_phone && (
                        <a href={`tel:${sa.customer_phone}`} className="flex items-center gap-1 text-brand-400 hover:text-brand-300">
                          <Phone className="w-3 h-3" />{fmtPhone(sa.customer_phone)}
                        </a>
                      )}
                      {(() => {
                        const elapsed = sa.created_iso ? Math.floor((now - new Date(sa.created_iso).getTime()) / 60000) : null
                        const pta = sa.pta_minutes
                        const breached = elapsed != null && pta && elapsed > pta
                        const remaining = pta && elapsed != null ? Math.round(pta - elapsed) : null
                        return (
                          <>
                            {elapsed != null && (
                              <span className={clsx('font-semibold', breached ? 'text-red-400' : elapsed > (pta || 999) * 0.8 ? 'text-amber-400' : 'text-slate-400')}>
                                {elapsed}m elapsed
                              </span>
                            )}
                            {pta && (
                              <span className={clsx(breached ? 'text-red-400 font-bold' : 'text-slate-500')}>
                                PTA {pta}m
                                {breached ? ` (BREACHED +${Math.abs(remaining)}m)` : remaining != null ? ` (${remaining}m left)` : ''}
                              </span>
                            )}
                          </>
                        )
                      })()}
                    </div>

                    {/* Tracking link result */}
                    {ts.url && (
                      <div className="mt-3 flex items-center gap-2 bg-emerald-500/10 border border-emerald-500/20 rounded-lg px-3 py-2">
                        <span className="text-xs text-emerald-400 truncate flex-1 font-mono">{ts.url}</span>
                        <button onClick={() => handleCopy(sa.sa_id, ts.url)}
                          className="flex-shrink-0 p-1.5 rounded-md bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30 transition"
                          title="Copy link">
                          {ts.copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                        </button>
                        <a href={sa.tracking_url || ts.url.replace(window.location.origin, '')} target="_blank" rel="noopener"
                          className="flex-shrink-0 p-1.5 rounded-md bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30 transition"
                          title="Open tracking page">
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      </div>
                    )}
                    {ts.error && (
                      <p className="mt-2 text-xs text-red-400">{ts.error}</p>
                    )}
                  </div>

                  {/* Right: Track button */}
                  <div className="flex-shrink-0">
                    {ts.url ? (
                      <button onClick={() => handleCopy(sa.sa_id, ts.url)}
                        className="px-3 py-2 rounded-lg text-xs font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/25 transition flex items-center gap-1.5">
                        {ts.copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                        {ts.copied ? 'Copied!' : 'Copy Link'}
                      </button>
                    ) : (
                      <button onClick={() => handleTrack(sa)} disabled={!sa.has_driver || !sa.is_fleet || ts.loading}
                        className={clsx(
                          'px-3 py-2 rounded-lg text-xs font-semibold transition flex items-center gap-1.5',
                          !sa.is_fleet
                            ? 'bg-slate-800/50 text-slate-600 border border-slate-700/30 cursor-not-allowed'
                            : sa.has_driver
                              ? 'bg-brand-600/20 text-brand-300 border border-brand-500/30 hover:bg-brand-600/30'
                              : 'bg-slate-800/50 text-slate-600 border border-slate-700/30 cursor-not-allowed'
                        )}
                        title={!sa.is_fleet ? 'GPS tracking available for Fleet drivers only' : !sa.has_driver ? 'No driver assigned' : ''}>
                        {ts.loading ? (
                          <><RefreshCw className="w-3.5 h-3.5 animate-spin" />Generating...</>
                        ) : !sa.is_fleet ? (
                          <><Truck className="w-3.5 h-3.5" />No GPS</>
                        ) : (
                          <><Truck className="w-3.5 h-3.5" />Track Driver</>
                        )}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Auto-refresh indicator */}
      <p className="text-center text-[10px] text-slate-600 pb-4">
        Auto-refreshes every 60 seconds
      </p>
    </div>
  )
}
