import { useState, useEffect, useCallback, useRef } from 'react'
import { RefreshCw, Loader2, Clock, AlertTriangle, ArrowUp, ArrowDown, Check, Minus, Truck, Zap, Wrench, ChevronDown, ChevronUp, Shield, Anchor } from 'lucide-react'
import { fetchPtaAdvisor, refreshPtaAdvisor, adminGetSettings, adminUpdateSettings } from '../api'

const TIER_ICONS = {
  tow: <Truck className="w-3.5 h-3.5" />,
  winch: <Anchor className="w-3.5 h-3.5" />,
  battery: <Zap className="w-3.5 h-3.5" />,
  light: <Wrench className="w-3.5 h-3.5" />,
}

const TIER_LABELS = { tow: 'Tow', winch: 'Winch', battery: 'Battery', light: 'Light' }
const CALL_TYPES = ['tow', 'winch', 'battery', 'light']

const REC_STYLES = {
  increase: { bg: 'bg-red-500/10', text: 'text-red-400', border: 'border-red-500/20', icon: <ArrowUp className="w-3 h-3" />, label: 'Increase' },
  decrease: { bg: 'bg-emerald-500/10', text: 'text-emerald-400', border: 'border-emerald-500/20', icon: <ArrowDown className="w-3 h-3" />, label: 'Decrease' },
  ok: { bg: 'bg-slate-500/10', text: 'text-slate-400', border: 'border-slate-500/20', icon: <Check className="w-3 h-3" />, label: 'OK' },
  no_coverage: { bg: 'bg-amber-500/10', text: 'text-amber-400', border: 'border-amber-500/20', icon: <Minus className="w-3 h-3" />, label: 'No Drivers' },
  no_setting: { bg: 'bg-slate-500/10', text: 'text-slate-500', border: 'border-slate-500/20', icon: <Minus className="w-3 h-3" />, label: 'No Setting' },
}

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


function GarageRow({ garage: g, expanded, onToggle }) {
  const hasAction = Object.values(g.projected_pta).some(
    p => p.recommendation === 'increase' || p.recommendation === 'decrease'
  )

  return (
    <div className={`glass rounded-xl overflow-hidden transition-colors ${
      hasAction ? 'border border-amber-500/20' : ''
    }`}>
      {/* Main row */}
      <button onClick={onToggle}
        className="w-full px-4 py-3 flex items-center gap-4 text-left hover:bg-slate-800/30 transition-colors">
        {/* Garage name + avg PTA */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-white truncate">{g.name}</span>
            {!g.has_fleet_drivers && (
              <span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-700/50 text-slate-500 font-medium">Towbook</span>
            )}
            {g.avg_projected_pta != null && (
              <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                g.avg_projected_pta > 120 ? 'bg-red-500/10 text-red-400' :
                g.avg_projected_pta > 60 ? 'bg-amber-500/10 text-amber-400' :
                'bg-emerald-500/10 text-emerald-400'
              }`}>
                ~{g.avg_projected_pta}m avg
              </span>
            )}
          </div>
          <div className="text-[10px] text-slate-500 flex items-center gap-3">
            <span>{g.drivers.total} driver{g.drivers.total !== 1 ? 's' : ''} ({g.drivers.idle} idle)</span>
            {(g.drivers.idle_by_tier?.tow > 0 || g.drivers.busy_by_tier?.tow > 0) && (
              <span className="text-brand-400 font-medium">
                <Truck className="w-3 h-3 inline -mt-0.5 mr-0.5" />
                {(g.drivers.idle_by_tier?.tow || 0) + (g.drivers.busy_by_tier?.tow || 0)} tow
              </span>
            )}
            <span>{g.completed_today} done</span>
            {g.queue_depth > 0 && (
              <span className={g.queue_depth > 5 ? 'text-red-400' : 'text-amber-400'}>
                {g.queue_depth} in queue
              </span>
            )}
          </div>
        </div>

        {/* PTA pills for each type */}
        <div className="flex items-center gap-2">
          {CALL_TYPES.map(tier => {
            const p = g.projected_pta[tier]
            if (!p) return null
            const rec = REC_STYLES[p.recommendation] || REC_STYLES.ok
            return (
              <div key={tier}
                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border ${rec.bg} ${rec.border}`}>
                <span className="text-slate-500">{TIER_ICONS[tier]}</span>
                <span className="text-[10px] text-slate-400 font-medium">{TIER_LABELS[tier]}</span>
                <span className={`text-xs font-bold ${rec.text}`}>
                  {p.projected_min != null ? `${p.projected_min}m` : '—'}
                </span>
                {p.current_setting_min != null && (
                  <span className="text-[10px] text-slate-600">/ {p.current_setting_min}m</span>
                )}
                <span className={rec.text}>{rec.icon}</span>
              </div>
            )
          })}
        </div>

        {/* Expand */}
        <div className="text-slate-600">
          {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </div>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-4 pb-4 border-t border-slate-800/50 pt-3">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            {CALL_TYPES.map(tier => {
              const p = g.projected_pta[tier]
              if (!p) return null
              const rec = REC_STYLES[p.recommendation] || REC_STYLES.ok
              const queueCount = g.queue_by_type?.[tier] || 0
              const idleCount = g.drivers.idle_by_tier?.[tier] || 0
              const busyCount = g.drivers.busy_by_tier?.[tier] || 0
              return (
                <div key={tier} className={`rounded-xl border p-3 ${rec.bg} ${rec.border}`}>
                  <div className="flex items-center gap-2 mb-2">
                    <span className={rec.text}>{TIER_ICONS[tier]}</span>
                    <span className="text-sm font-semibold text-white">{TIER_LABELS[tier]}</span>
                    <span className={`ml-auto text-xs font-bold ${rec.text} flex items-center gap-1`}>
                      {rec.icon} {rec.label}
                    </span>
                  </div>
                  <div className="space-y-1.5 text-xs">
                    <div className="flex justify-between">
                      <span className="text-slate-500">Projected PTA</span>
                      <span className={`font-bold ${rec.text}`}>
                        {p.projected_min != null ? `${p.projected_min} min` : 'No coverage'}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">Current Setting</span>
                      <span className="text-slate-300">
                        {p.current_setting_min != null ? `${p.current_setting_min} min` : 'Not set'}
                      </span>
                    </div>
                    {p.projected_min != null && p.current_setting_min != null && (
                      <div className="flex justify-between">
                        <span className="text-slate-500">Delta</span>
                        <span className={`font-medium ${
                          p.projected_min > p.current_setting_min ? 'text-red-400' :
                          p.projected_min < p.current_setting_min ? 'text-emerald-400' : 'text-slate-400'
                        }`}>
                          {p.projected_min > p.current_setting_min ? '+' : ''}
                          {p.projected_min - p.current_setting_min} min
                        </span>
                      </div>
                    )}
                    <div className="border-t border-slate-700/30 pt-1.5 mt-1.5">
                      <div className="flex justify-between">
                        <span className="text-slate-600">Queue</span>
                        <span className="text-slate-400">{queueCount} calls</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-slate-600">Idle drivers</span>
                        <span className="text-slate-400">{idleCount}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-slate-600">Busy drivers</span>
                        <span className="text-slate-400">{busyCount}</span>
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
          {/* Driver Queue Detail */}
          {g.drivers.busy_details?.length > 0 && (
            <div className="mt-4">
              <h4 className="text-xs font-semibold text-slate-400 mb-2">Driver Queue</h4>
              <div className="space-y-2">
                {g.drivers.busy_details.map((d, i) => (
                  <div key={i} className="rounded-lg bg-slate-800/40 p-2.5">
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className="text-xs font-semibold text-white">{d.name}</span>
                      <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                        d.tier === 'tow' ? 'bg-brand-500/10 text-brand-400 border border-brand-500/20' :
                        d.tier === 'winch' ? 'bg-purple-500/10 text-purple-400 border border-purple-500/20' :
                        d.tier === 'battery' ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' :
                        'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                      }`}>{d.tier}</span>
                      {d.towbook && <span className="text-[9px] px-1 py-0.5 rounded bg-slate-700/50 text-slate-500">TB</span>}
                      <span className="ml-auto text-[10px] text-slate-500">{d.jobs} job{d.jobs !== 1 ? 's' : ''}</span>
                      <span className={`text-[10px] font-bold ${d.remaining_min > 60 ? 'text-red-400' : d.remaining_min > 30 ? 'text-amber-400' : 'text-emerald-400'}`}>
                        {d.remaining_min} min left
                      </span>
                    </div>
                    {d.job_details?.length > 0 && (
                      <div className="space-y-0.5">
                        {d.job_details.map((j, ji) => (
                          <div key={ji} className="flex items-center gap-2 text-[10px] pl-2 border-l border-slate-700/50">
                            <span className={j.has_arrived ? 'text-emerald-400' : 'text-slate-500'}>
                              {j.has_arrived ? 'On-site' : 'Waiting'}
                            </span>
                            <span className="text-slate-400">{j.work_type}</span>
                            <span className="text-slate-600">{j.wait_min}m ago</span>
                            {j.pta_min != null && (
                              <span className={`ml-auto ${j.wait_min > j.pta_min ? 'text-red-400 font-bold' : 'text-slate-600'}`}>
                                PTA {j.pta_min}m
                                {j.wait_min > j.pta_min && ' (overdue)'}
                              </span>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {g.longest_wait > 0 && (
            <div className="mt-3 text-[11px] text-slate-500">
              Longest waiting: <span className={`font-medium ${g.longest_wait > 60 ? 'text-red-400' : 'text-amber-400'}`}>
                {g.longest_wait} min
              </span>
              {' '} — Avg wait: {g.avg_wait} min
            </div>
          )}
        </div>
      )}
    </div>
  )
}
