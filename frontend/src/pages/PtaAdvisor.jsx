import { useState, useEffect, useCallback, useRef } from 'react'
import { RefreshCw, Loader2, Clock, AlertTriangle, ArrowUp, ArrowDown, Check, Minus, Truck, Zap, Wrench, ChevronDown, ChevronUp, Shield, Anchor, HelpCircle, X } from 'lucide-react'
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
            <span className={`text-[9px] px-1.5 py-0.5 rounded font-medium ${
              g.has_fleet_drivers
                ? 'bg-brand-500/10 text-brand-400 border border-brand-500/20'
                : 'bg-slate-700/50 text-slate-500'
            }`}>{g.has_fleet_drivers ? 'Fleet' : 'Contractor'}</span>
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
            {g.has_fleet_drivers ? (
              <>
                <span>{g.drivers.total} driver{g.drivers.total !== 1 ? 's' : ''} ({g.drivers.idle} idle)</span>
                {(g.drivers.idle_by_tier?.tow > 0 || g.drivers.busy_by_tier?.tow > 0) && (
                  <span className="text-brand-400 font-medium">
                    <Truck className="w-3 h-3 inline -mt-0.5 mr-0.5" />
                    {(g.drivers.idle_by_tier?.tow || 0) + (g.drivers.busy_by_tier?.tow || 0)} tow
                  </span>
                )}
              </>
            ) : (
              <>
                {g.drivers.tb_seen_today > 0 && (
                  <span>{g.drivers.tb_seen_today} driver{g.drivers.tb_seen_today !== 1 ? 's' : ''} seen today</span>
                )}
                {g.drivers.tb_active > 0 && (
                  <span className="text-amber-400 font-medium">{g.drivers.tb_active} on calls</span>
                )}
                {!g.drivers.tb_seen_today && !g.drivers.tb_active && (
                  <span className="text-slate-600">no driver data</span>
                )}
              </>
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
              const idleCount = g.drivers.capable_idle?.[tier] ?? g.drivers.idle_by_tier?.[tier] ?? 0
              const busyCount = g.drivers.capable_busy?.[tier] ?? g.drivers.busy_by_tier?.[tier] ?? 0
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
                      {g.drivers.is_towbook ? (
                        <div className="flex justify-between">
                          <span className="text-slate-600">Active drivers</span>
                          <span className="text-slate-400">{busyCount} on calls</span>
                        </div>
                      ) : (
                        <>
                          <div className="flex justify-between">
                            <span className="text-slate-600">Idle drivers</span>
                            <span className="text-slate-400">{idleCount}</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-slate-600">Busy drivers</span>
                            <span className="text-slate-400">{busyCount}</span>
                          </div>
                        </>
                      )}
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


function HowItWorks({ onClose }) {
  return (
    <div className="glass rounded-xl border border-slate-700/50 p-5 relative">
      <button onClick={onClose}
        className="absolute top-3 right-3 p-1 rounded-lg text-slate-500 hover:text-white hover:bg-slate-800 transition-colors">
        <X className="w-4 h-4" />
      </button>

      <div className="flex items-center gap-2 mb-4">
        <HelpCircle className="w-5 h-5 text-brand-400" />
        <h2 className="text-base font-bold text-white">How PTA Advisor Works</h2>
      </div>

      <div className="space-y-4 text-xs text-slate-300 leading-relaxed">
        {/* What is PTA */}
        <div>
          <h3 className="text-sm font-semibold text-white mb-1">What is PTA?</h3>
          <p className="text-slate-400">
            <strong className="text-slate-300">Promised Time to Arrival (PTA)</strong> is the time promised to the member when they call for roadside assistance.
            Each garage has a PTA setting in Salesforce (<code className="text-brand-400 bg-slate-800 px-1 rounded">ERS_Service_Appointment_PTA__c</code>) that Mulesoft quotes to members.
            This page projects what the <em>actual</em> wait time would be right now, and compares it to the current setting.
          </p>
        </div>

        {/* 4 Call Types */}
        <div>
          <h3 className="text-sm font-semibold text-white mb-1">4 Call Types</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <div className="bg-slate-800/50 rounded-lg p-2">
              <div className="flex items-center gap-1.5 mb-1">
                <Truck className="w-3.5 h-3.5 text-brand-400" />
                <span className="font-semibold text-white">Tow</span>
              </div>
              <p className="text-[10px] text-slate-500">Tow, Flat Bed, Wheel Lift. Cycle: 115 min. Buffer: 30 min.</p>
            </div>
            <div className="bg-slate-800/50 rounded-lg p-2">
              <div className="flex items-center gap-1.5 mb-1">
                <Anchor className="w-3.5 h-3.5 text-purple-400" />
                <span className="font-semibold text-white">Winch</span>
              </div>
              <p className="text-[10px] text-slate-500">Winch Out recovery. Cycle: 40 min. Buffer: 25 min.</p>
            </div>
            <div className="bg-slate-800/50 rounded-lg p-2">
              <div className="flex items-center gap-1.5 mb-1">
                <Zap className="w-3.5 h-3.5 text-amber-400" />
                <span className="font-semibold text-white">Battery</span>
              </div>
              <p className="text-[10px] text-slate-500">Battery, Jumpstart. Cycle: 38 min. Buffer: 25 min.</p>
            </div>
            <div className="bg-slate-800/50 rounded-lg p-2">
              <div className="flex items-center gap-1.5 mb-1">
                <Wrench className="w-3.5 h-3.5 text-emerald-400" />
                <span className="font-semibold text-white">Light</span>
              </div>
              <p className="text-[10px] text-slate-500">Tire, Lockout, Fuel, etc. Cycle: 33 min. Buffer: 25 min.</p>
            </div>
          </div>
        </div>

        {/* Projection Logic */}
        <div>
          <h3 className="text-sm font-semibold text-white mb-1">How Projections Are Calculated</h3>
          <div className="space-y-2">
            <div>
              <p className="text-slate-300 font-medium text-[11px] mb-1">Fleet Garages (Internal Drivers)</p>
              <p className="text-slate-400 mb-1">Uses a <strong className="text-slate-300">heap-based FIFO simulation</strong> per call type:</p>
              <ol className="list-decimal list-inside space-y-1 text-slate-400">
                <li><strong className="text-slate-300">Idle drivers</strong> — If a driver matching this call type is idle, projected PTA uses the garage's setting scaled by type (Tow: 1.0x, Winch: 0.75x, Battery: 0.65x, Light: 0.7x).</li>
                <li><strong className="text-slate-300">Busy drivers</strong> — Estimates each driver's remaining time (cycle time minus time on-site), then simulates draining the queue. Each driver finishes their job, picks up the next queued call, and so on.</li>
                <li><strong className="text-slate-300">Queue depth</strong> — Unassigned SAs are queued calls. Assigned SAs count toward the driver's current workload.</li>
                <li><strong className="text-slate-300">Buffer</strong> — Dispatch + travel buffer added (Tow: 30 min, others: 25 min).</li>
              </ol>
            </div>
            <div>
              <p className="text-slate-300 font-medium text-[11px] mb-1">Contractor Garages (Towbook)</p>
              <p className="text-slate-400">Uses the <strong className="text-slate-300">actual PTA from live Service Appointments</strong> (<code className="text-brand-400 bg-slate-800 px-1 rounded">ERS_PTA__c</code>). This is the real promise the dispatch system gave the member. If a garage has open SAs, the projected PTA = average of their ERS_PTA__c values. If no open SAs, falls back to the garage's PTA setting. Drivers are identified from the <code className="text-brand-400 bg-slate-800 px-1 rounded">Off_Platform_Driver__r</code> field on each SA.</p>
            </div>
          </div>
        </div>

        {/* Driver Skill Hierarchy */}
        <div>
          <h3 className="text-sm font-semibold text-white mb-1">Driver Skill Hierarchy</h3>
          <p className="text-slate-400 mb-2">Drivers are classified by their truck capabilities. Skills overlap — higher-tier drivers can cover lower-tier calls:</p>
          <div className="bg-slate-800/50 rounded-lg p-3 font-mono text-[10px] text-slate-400">
            <div><span className="text-brand-400">Tow driver</span> → can do: Tow, Winch, Light, Battery</div>
            <div><span className="text-emerald-400">Light driver</span> → can do: Winch, Light, Battery</div>
            <div><span className="text-amber-400">Battery driver</span> → can do: Battery only</div>
          </div>
          <p className="text-slate-500 mt-1">An idle tow driver can cover a battery call. This cross-skill capability is factored into projections.</p>
        </div>

        {/* Fleet vs Contractor */}
        <div>
          <h3 className="text-sm font-semibold text-white mb-1">Fleet vs Contractor Garages</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="bg-slate-800/50 rounded-lg p-3">
              <div className="flex items-center gap-1.5 mb-1">
                <span className="text-[9px] px-1.5 py-0.5 rounded font-medium bg-brand-500/10 text-brand-400 border border-brand-500/20">Fleet</span>
              </div>
              <ul className="text-[10px] text-slate-500 space-y-0.5 list-disc list-inside">
                <li>Internal AAA drivers with real-time GPS</li>
                <li>Driver count = logged into a vehicle (Asset table)</li>
                <li>Shows idle/busy counts and tow-capable driver count</li>
                <li>Full queue simulation with skill-based projection</li>
                <li>If no drivers for a call type → shows "No Drivers"</li>
              </ul>
            </div>
            <div className="bg-slate-800/50 rounded-lg p-3">
              <div className="flex items-center gap-1.5 mb-1">
                <span className="text-[9px] px-1.5 py-0.5 rounded font-medium bg-slate-700/50 text-slate-500">Contractor</span>
              </div>
              <ul className="text-[10px] text-slate-500 space-y-0.5 list-disc list-inside">
                <li>External garages dispatched via Towbook</li>
                <li>Drivers identified from Off_Platform_Driver__r on each SA</li>
                <li>"Drivers seen today" = unique drivers on today's SAs</li>
                <li>"Active drivers" = currently on a dispatched call</li>
                <li>Projected PTA = actual ERS_PTA__c from live SAs (not simulated)</li>
                <li>Falls back to PTA setting when no open SAs</li>
              </ul>
            </div>
          </div>
        </div>

        {/* Recommendations */}
        <div>
          <h3 className="text-sm font-semibold text-white mb-1">Recommendation Labels</h3>
          <div className="flex flex-wrap gap-2">
            {Object.entries(REC_STYLES).map(([key, s]) => (
              <div key={key} className={`flex items-center gap-1.5 px-2 py-1 rounded-lg border ${s.bg} ${s.border}`}>
                <span className={s.text}>{s.icon}</span>
                <span className={`text-[10px] font-medium ${s.text}`}>{s.label}</span>
                <span className="text-[10px] text-slate-500">
                  {key === 'increase' && '— projected > setting, PTA too optimistic'}
                  {key === 'decrease' && '— projected < setting, PTA could be lowered'}
                  {key === 'ok' && '— projected ≈ setting, within tolerance'}
                  {key === 'no_coverage' && '— Fleet garage, no drivers for this type'}
                  {key === 'no_setting' && '— no PTA configured in Salesforce'}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Reading the Cards */}
        <div>
          <h3 className="text-sm font-semibold text-white mb-1">Reading the Garage Cards</h3>
          <ul className="text-slate-400 space-y-1 list-disc list-inside">
            <li><strong className="text-slate-300">PTA pills</strong> — Each call type shows: projected time / current setting. Color = recommendation.</li>
            <li><strong className="text-slate-300">~Xm avg</strong> — Average projected PTA across all call types for that garage.</li>
            <li><strong className="text-slate-300">Queue depth</strong> — Unassigned SAs waiting for dispatch at this garage.</li>
            <li><strong className="text-slate-300">Expanded view</strong> — Click a garage to see per-type breakdown, delta from setting, and individual driver queue details.</li>
            <li><strong className="text-slate-300">Driver Queue</strong> — Shows each busy driver, their skill tier, current job(s), and estimated time remaining.</li>
          </ul>
        </div>

        {/* Salesforce Fields Reference */}
        <div>
          <h3 className="text-sm font-semibold text-white mb-1">Salesforce Fields Used</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-[10px] mt-2">
              <thead>
                <tr className="border-b border-slate-700/50">
                  <th className="text-left py-1.5 px-2 text-slate-500 font-bold uppercase">Data Point</th>
                  <th className="text-left py-1.5 px-2 text-slate-500 font-bold uppercase">Salesforce Field(s)</th>
                  <th className="text-left py-1.5 px-2 text-slate-500 font-bold uppercase">How It's Used</th>
                </tr>
              </thead>
              <tbody className="text-slate-400">
                <tr className="border-b border-slate-800/50">
                  <td className="py-1.5 px-2 text-slate-300">PTA Setting</td>
                  <td className="py-1.5 px-2"><code className="text-brand-300 bg-slate-800 px-1 rounded">ServiceTerritory.ERS_Service_Appointment_PTA__c</code></td>
                  <td className="py-1.5 px-2">Current PTA promise (minutes) configured per garage. This is what Mulesoft quotes to members.</td>
                </tr>
                <tr className="border-b border-slate-800/50">
                  <td className="py-1.5 px-2 text-slate-300">Live PTA per call</td>
                  <td className="py-1.5 px-2"><code className="text-brand-300 bg-slate-800 px-1 rounded">ServiceAppointment.ERS_PTA__c</code></td>
                  <td className="py-1.5 px-2">Actual PTA promised for each SA at dispatch time. For contractor garages, AVG of this field on open SAs = projected PTA.</td>
                </tr>
                <tr className="border-b border-slate-800/50">
                  <td className="py-1.5 px-2 text-slate-300">Call type</td>
                  <td className="py-1.5 px-2"><code className="text-brand-300 bg-slate-800 px-1 rounded">WorkType.Name</code> via <code className="text-brand-300 bg-slate-800 px-1 rounded">ServiceAppointment.WorkTypeId</code></td>
                  <td className="py-1.5 px-2">Maps to tier: Tow/Flat Bed/Wheel Lift → tow, Winch Out → winch, Battery/Jumpstart → battery, Tire/Lockout/Fuel → light.</td>
                </tr>
                <tr className="border-b border-slate-800/50">
                  <td className="py-1.5 px-2 text-slate-300">Queue depth</td>
                  <td className="py-1.5 px-2"><code className="text-brand-300 bg-slate-800 px-1 rounded">ServiceAppointment.StatusCategory</code> = "None" (unassigned)</td>
                  <td className="py-1.5 px-2">COUNT of today's SAs with no driver assigned yet = calls waiting in queue.</td>
                </tr>
                <tr className="border-b border-slate-800/50">
                  <td className="py-1.5 px-2 text-slate-300">Fleet drivers</td>
                  <td className="py-1.5 px-2"><code className="text-brand-300 bg-slate-800 px-1 rounded">ServiceResource</code> + <code className="text-brand-300 bg-slate-800 px-1 rounded">Asset</code> (vehicle login)</td>
                  <td className="py-1.5 px-2">Driver is "online" if they have an active Asset record (logged into a truck). Truck capabilities determine skill tier.</td>
                </tr>
                <tr className="border-b border-slate-800/50">
                  <td className="py-1.5 px-2 text-slate-300">Contractor drivers</td>
                  <td className="py-1.5 px-2"><code className="text-brand-300 bg-slate-800 px-1 rounded">ServiceAppointment.Off_Platform_Driver__r.Name</code></td>
                  <td className="py-1.5 px-2">Towbook drivers identified from this field. Unique names on today's SAs = "drivers seen today".</td>
                </tr>
                <tr className="border-b border-slate-800/50">
                  <td className="py-1.5 px-2 text-slate-300">Driver on-site?</td>
                  <td className="py-1.5 px-2"><code className="text-brand-300 bg-slate-800 px-1 rounded">ServiceAppointment.ActualStartTime</code></td>
                  <td className="py-1.5 px-2">If ActualStartTime is set, driver has arrived. Remaining time = cycle time − (NOW − ActualStartTime).</td>
                </tr>
                <tr>
                  <td className="py-1.5 px-2 text-slate-300">Dispatch method</td>
                  <td className="py-1.5 px-2"><code className="text-brand-300 bg-slate-800 px-1 rounded">ServiceAppointment.ERS_Dispatch_Method__c</code></td>
                  <td className="py-1.5 px-2">"Field Services" = internal fleet, "Towbook" = external contractor. Determines fleet vs contractor logic.</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        {/* Data Sources */}
        <div>
          <h3 className="text-sm font-semibold text-white mb-1">SOQL Queries (5 Parallel)</h3>
          <ol className="list-decimal list-inside space-y-0.5 text-slate-500 text-[10px]">
            <li><strong className="text-slate-400">ServiceAppointment</strong> — Today's SAs with Status, PTA, WorkType, Off_Platform_Driver, ActualStartTime, ActualEndTime</li>
            <li><strong className="text-slate-400">AssignedResource</strong> — Links ServiceResource to SA (driver-to-call assignments)</li>
            <li><strong className="text-slate-400">Asset</strong> — Fleet drivers logged into vehicles + truck capabilities (AccountId matches ServiceResource)</li>
            <li><strong className="text-slate-400">ServiceTerritoryMember</strong> — Driver-to-garage assignments (which drivers belong to which territory)</li>
            <li><strong className="text-slate-400">ServiceTerritory</strong> — ERS_Service_Appointment_PTA__c (current PTA settings per garage)</li>
          </ol>
        </div>
      </div>
    </div>
  )
}
