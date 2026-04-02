import { useState, useEffect, useCallback, useRef } from 'react'
import { RefreshCw, Loader2, Clock, AlertTriangle, Check, Shield, HelpCircle } from 'lucide-react'
import { fetchPtaAdvisor, refreshPtaAdvisor, adminGetSettings, adminUpdateSettings } from '../api'
import { GarageRow, HowItWorks, REC_STYLES } from '../components/PtaAdvisorDetail'

export default function PtaAdvisor() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState(null)
  const [expandedId, setExpandedId] = useState(null)
  const [filter, setFilter] = useState('all') // all, action, ok
  const [sortBy, setSortBy] = useState('urgency') // urgency, name, queue
  const [showSettings, setShowSettings] = useState(false)
  const [pin, setPin] = useState('')
  const [pinAuthed, setPinAuthed] = useState(false)
  const [refreshInterval, setRefreshInterval] = useState(900)
  const [savingSettings, setSavingSettings] = useState(false)
  const [showHelp, setShowHelp] = useState(false)
  const intervalRef = useRef(null)

  const load = useCallback(async () => {
    try {
      const d = await fetchPtaAdvisor()
      setData(d)
      setError(null)
      if (d.refresh_interval) setRefreshInterval(d.refresh_interval)
    } catch (e) {
      setError('Failed to load PTA data')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [load])

  // Auto-refresh
  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current)
    intervalRef.current = setInterval(load, refreshInterval * 1000)
    return () => clearInterval(intervalRef.current)
  }, [refreshInterval, load])

  const handleForceRefresh = async () => {
    if (!pinAuthed) {
      setShowSettings(true)
      return
    }
    setRefreshing(true)
    try {
      const d = await refreshPtaAdvisor(pin)
      setData(d)
      setError(null)
    } catch {
      setError('Refresh failed — check PIN')
    } finally {
      setRefreshing(false)
    }
  }

  const handleSaveSettings = async () => {
    setSavingSettings(true)
    try {
      await adminUpdateSettings(pin, { pta_refresh_interval: refreshInterval })
      setPinAuthed(true)
      setShowSettings(false)
    } catch {
      setError('Invalid PIN or save failed')
    } finally {
      setSavingSettings(false)
    }
  }

  const handlePinVerify = async () => {
    try {
      await adminGetSettings(pin)
      setPinAuthed(true)
      setShowSettings(false)
    } catch {
      setError('Invalid PIN')
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="w-8 h-8 animate-spin text-brand-400" />
      </div>
    )
  }

  if (error && !data) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <AlertTriangle className="w-8 h-8 text-amber-400 mx-auto mb-3" />
          <p className="text-slate-400">{error}</p>
          <button onClick={load} className="mt-3 px-4 py-2 bg-brand-600 rounded-lg text-sm">Retry</button>
        </div>
      </div>
    )
  }

  const garages = data?.garages || []
  const totals = data?.totals || {}
  const computedAt = data?.computed_at ? new Date(data.computed_at) : null

  // Filter
  const filtered = garages.filter(g => {
    if (filter === 'all') return true
    const hasAction = Object.values(g.projected_pta).some(p => p.recommendation === 'increase' || p.recommendation === 'decrease')
    return filter === 'action' ? hasAction : !hasAction
  })

  // Sort
  const sorted = [...filtered].sort((a, b) => {
    if (sortBy === 'name') return a.name.localeCompare(b.name)
    if (sortBy === 'queue') return b.queue_depth - a.queue_depth
    // urgency: highest projected PTA first
    const aMax = Math.max(...Object.values(a.projected_pta).map(p => p.projected_min || 0))
    const bMax = Math.max(...Object.values(b.projected_pta).map(p => p.projected_min || 0))
    return bMax - aMax
  })

  const actionCount = garages.filter(g =>
    Object.values(g.projected_pta).some(p => p.recommendation === 'increase' || p.recommendation === 'decrease')
  ).length

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-brand-600/20 flex items-center justify-center">
            <Clock className="w-5 h-5 text-brand-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white">PTA Advisor</h1>
            <p className="text-xs text-slate-500">
              Projected PTA vs current settings — {garages.length} garages
              {computedAt && <> — updated {computedAt.toLocaleTimeString()}</>}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button onClick={() => setShowHelp(!showHelp)}
            className="p-2 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors"
            title="How it works">
            <HelpCircle className="w-4 h-4" />
          </button>
          <button onClick={() => setShowSettings(!showSettings)}
            className="p-2 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors"
            title="Settings (PIN required)">
            <Shield className="w-4 h-4" />
          </button>
          <button onClick={handleForceRefresh} disabled={refreshing}
            className="px-3 py-1.5 text-xs bg-brand-600 hover:bg-brand-500 rounded-lg font-semibold
                       flex items-center gap-1.5 transition-colors disabled:opacity-50"
            title={pinAuthed ? 'Force recalculate from Salesforce' : 'Enter PIN first'}>
            {refreshing ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
            Recalculate
          </button>
        </div>
      </div>

      {/* Settings panel (PIN-gated) */}
      {showSettings && (
        <div className="glass rounded-xl p-4 border border-slate-700/50">
          <div className="flex items-center gap-3 mb-3">
            <Shield className="w-4 h-4 text-brand-400" />
            <h3 className="text-sm font-semibold text-white">PTA Advisor Settings</h3>
          </div>
          {!pinAuthed ? (
            <div className="flex items-center gap-3">
              <input type="password" value={pin} onChange={e => setPin(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handlePinVerify()}
                placeholder="Admin PIN" autoFocus
                className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm w-40
                           focus:outline-none focus:ring-1 focus:ring-brand-500/40" />
              <button onClick={handlePinVerify}
                className="px-3 py-2 bg-brand-600 hover:bg-brand-500 rounded-lg text-xs font-semibold">
                Unlock
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-4 flex-wrap">
              <div>
                <label className="text-[10px] text-slate-500 uppercase tracking-wider mb-1 block">Auto-Refresh Interval</label>
                <div className="flex items-center gap-2">
                  <select value={refreshInterval} onChange={e => setRefreshInterval(Number(e.target.value))}
                    className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs
                               focus:outline-none focus:ring-1 focus:ring-brand-500/40">
                    <option value={300}>5 min</option>
                    <option value={600}>10 min</option>
                    <option value={900}>15 min (default)</option>
                    <option value={1800}>30 min</option>
                    <option value={3600}>60 min</option>
                  </select>
                  <button onClick={handleSaveSettings} disabled={savingSettings}
                    className="px-3 py-2 bg-brand-600 hover:bg-brand-500 rounded-lg text-xs font-semibold
                               disabled:opacity-50 flex items-center gap-1">
                    {savingSettings ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                    Save
                  </button>
                </div>
              </div>
              <div className="text-[10px] text-slate-600 max-w-xs">
                Controls how often PTA projections are recalculated from Salesforce.
                Lower values = more SF API calls but fresher data.
              </div>
            </div>
          )}
        </div>
      )}

      {/* How It Works panel */}
      {showHelp && <HowItWorks onClose={() => setShowHelp(false)} />}

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <SummaryCard label="Active Garages" value={totals.garages_active || 0} color="text-white" />
        <SummaryCard label="Total Queue" value={totals.total_queue || 0}
          color={totals.total_queue > 20 ? 'text-red-400' : totals.total_queue > 10 ? 'text-amber-400' : 'text-emerald-400'} />
        <SummaryCard label="Drivers Online" value={`${totals.total_idle || 0} idle / ${totals.total_drivers || 0}`}
          color="text-brand-400" />
        <SummaryCard label="Need Attention" value={actionCount}
          color={actionCount > 5 ? 'text-red-400' : actionCount > 0 ? 'text-amber-400' : 'text-emerald-400'} />
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="flex items-center bg-slate-800/50 rounded-lg p-0.5">
          {[['all', 'All'], ['action', `Action (${actionCount})`], ['ok', 'OK']].map(([key, label]) => (
            <button key={key} onClick={() => setFilter(key)}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                filter === key ? 'bg-brand-600/20 text-brand-300' : 'text-slate-500 hover:text-white'
              }`}>
              {label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1.5 ml-auto">
          <span className="text-[10px] text-slate-600 uppercase">Sort:</span>
          {[['urgency', 'Urgency'], ['queue', 'Queue'], ['name', 'Name']].map(([key, label]) => (
            <button key={key} onClick={() => setSortBy(key)}
              className={`px-2 py-1 rounded text-[11px] font-medium transition-colors ${
                sortBy === key ? 'bg-slate-700 text-white' : 'text-slate-500 hover:text-white'
              }`}>
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Garage list */}
      <div className="space-y-2">
        {sorted.map(g => (
          <GarageRow key={g.id} garage={g}
            expanded={expandedId === g.id}
            onToggle={() => setExpandedId(expandedId === g.id ? null : g.id)} />
        ))}
        {sorted.length === 0 && (
          <div className="glass rounded-xl py-12 text-center text-slate-600">
            No garages match this filter
          </div>
        )}
      </div>

      {/* Auto-refresh indicator */}
      <div className="text-center text-[10px] text-slate-600 py-2">
        Auto-refreshes every {Math.round(refreshInterval / 60)} min
        {' '} — Next: ~{computedAt ? new Date(computedAt.getTime() + refreshInterval * 1000).toLocaleTimeString() : '?'}
      </div>
    </div>
  )
}


function SummaryCard({ label, value, color = 'text-white' }) {
  return (
    <div className="glass rounded-xl p-3">
      <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">{label}</div>
      <div className={`text-lg font-bold ${color}`}>{value}</div>
    </div>
  )
}
