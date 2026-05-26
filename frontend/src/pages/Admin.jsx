import { useState, useEffect, useCallback } from 'react'
import { Shield, Database, Trash2, RefreshCw, Loader2, CheckCircle2, Clock, Server, Map, ToggleRight, Save, Users, BrainCircuit, Table2 } from 'lucide-react'
import { adminVerify, adminStatus, adminFlush, adminFlushLive, adminFlushHistorical, adminFlushStatic, adminUpdateSettings, fetchFeatures } from '../api'
import { MAP_STYLES, getMapStyle, setMapStyle as saveMapStyle } from '../mapStyles'
import AdminAI from '../components/AdminAI'
import AdminUsers from '../components/AdminUsers'
import AdminActivityLog from '../components/AdminActivityLog'
import AdminOptimizerSync from '../components/AdminOptimizerSync'
import AdminReferenceData from '../components/AdminReferenceData'
import AdminSystemHealth from '../components/AdminSystemHealth'

// NOTE: AdminAccountingRates and bonus tiers section REMOVED — handled by AdminReferenceData

const SESSION_KEY = 'admin_pin'
const _REFERENCE_ONLY_ROLES = new Set(['executive', 'ers-director'])

export default function Admin({ role = '' }) {
  const isReferenceOnly = _REFERENCE_ONLY_ROLES.has(role)
  const [pin, setPin] = useState(() => isReferenceOnly ? '' : (sessionStorage.getItem(SESSION_KEY) || ''))
  const [authed, setAuthed] = useState(isReferenceOnly)
  const [authError, setAuthError] = useState('')
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(false)
  const [flushing, setFlushing] = useState(null)
  const [lastAction, setLastAction] = useState(null)
  const [activeSection, setActiveSection] = useState('status')
  const [mapStyle, setMapStyleState] = useState(getMapStyle)

  // Feature flags
  const [features, setFeatures] = useState({})
  const [featureSaving, setFeatureSaving] = useState(false)
  const [featureSaved, setFeatureSaved] = useState(false)
  const [helpVideoUrl, setHelpVideoUrl] = useState('')
  const [videoSaving, setVideoSaving] = useState(false)
  const [videoSaved, setVideoSaved] = useState(false)

  // Auto-verify on mount if PIN already in session
  useEffect(() => {
    const saved = sessionStorage.getItem(SESSION_KEY)
    if (saved && !authed) {
      adminVerify(saved).then(() => setAuthed(true)).catch(() => sessionStorage.removeItem(SESSION_KEY))
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const verify = async () => {
    setAuthError('')
    try {
      await adminVerify(pin)
      sessionStorage.setItem(SESSION_KEY, pin)
      setAuthed(true)
    } catch {
      setAuthError('Invalid PIN')
    }
  }

  const refresh = useCallback(async () => {
    if (!authed || isReferenceOnly) return
    setLoading(true)
    try {
      const s = await adminStatus(pin)
      setStatus(s)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [authed, isReferenceOnly, pin])

  useEffect(() => {
    if (authed && !isReferenceOnly) {
      refresh()
      fetchFeatures().then(f => { setFeatures(f); setHelpVideoUrl(f.help_video_url || '') }).catch(() => {})
      const id = setInterval(() => { refresh() }, 5000)
      return () => clearInterval(id)
    }
  }, [authed, isReferenceOnly, refresh])

  const handleFlush = async (type, fn) => {
    setFlushing(type)
    try {
      const result = await fn(pin)
      setStatus(s => s ? { ...s, cache: result.cache_after } : s)
      setLastAction({ type, time: new Date(), flushed: result.flushed })
    } catch { /* ignore */ }
    finally { setFlushing(null) }
  }

  const handleMapStyleChange = (key) => {
    saveMapStyle(key)
    setMapStyleState(key)
    window.dispatchEvent(new Event('mapStyleChanged'))
  }

  // PIN gate
  if (!authed) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="glass rounded-2xl p-8 w-full max-w-sm">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 rounded-xl bg-brand-600/20 flex items-center justify-center">
              <Shield className="w-5 h-5 text-brand-400" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-white">Admin Panel</h1>
              <p className="text-xs text-slate-500">Enter PIN to continue</p>
            </div>
          </div>
          <div className="space-y-3">
            <input
              type="password"
              value={pin}
              onChange={e => setPin(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && verify()}
              placeholder="Enter PIN"
              autoFocus
              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-3 text-center text-lg tracking-[0.3em]
                         focus:outline-none focus:ring-2 focus:ring-brand-500/40 focus:border-brand-500/40"
            />
            {authError && <p className="text-red-400 text-sm text-center">{authError}</p>}
            <button onClick={verify}
              className="w-full py-2.5 bg-brand-600 hover:bg-brand-500 rounded-lg text-sm font-semibold transition-colors">
              Unlock
            </button>
          </div>
        </div>
      </div>
    )
  }

  // Reference-only view for executive / ers-director — no PIN, no sidebar
  if (isReferenceOnly) {
    return (
      <div className="max-w-5xl mx-auto space-y-4">
        <div className="flex items-center gap-3 mb-2">
          <Table2 className="w-5 h-5 text-indigo-400" />
          <h1 className="text-base font-bold text-white">Reference Data</h1>
        </div>
        <AdminReferenceData pin="" />
      </div>
    )
  }

  const uptime = status?.uptime_seconds || 0
  const uptimeStr = uptime >= 3600
    ? `${Math.floor(uptime / 3600)}h ${Math.floor((uptime % 3600) / 60)}m`
    : `${Math.floor(uptime / 60)}m`

  const NAV = [
    { group: 'SYSTEM', items: [
      { key: 'status',   label: 'System Health',   icon: Server },
      { key: 'cache',    label: 'Cache',            icon: Database },
    ]},
    { group: 'PEOPLE', items: [
      { key: 'users',    label: 'Users & Sessions', icon: Users },
    ]},
    { group: 'CONFIGURATION', items: [
      { key: 'settings', label: 'App Settings',     icon: ToggleRight },
      { key: 'ai',       label: 'AI Config',         icon: BrainCircuit },
    ]},
    { group: 'DATA', items: [
      { key: 'reference', label: 'Reference Data',  icon: Table2 },
      { key: 'optimizer', label: 'Optimizer Sync',  icon: RefreshCw },
    ]},
  ]

  return (
    <div className="flex gap-0 min-h-[calc(100vh-120px)]">
      {/* ── Sidebar ── */}
      <aside className="w-52 flex-shrink-0 mr-6">
        <div className="glass rounded-xl overflow-hidden sticky top-20">
          <div className="px-4 py-3 border-b border-slate-700/50 flex items-center gap-2">
            <Shield className="w-4 h-4 text-brand-400" />
            <span className="text-sm font-semibold text-white">Admin</span>
            {loading && <Loader2 className="w-3 h-3 animate-spin text-slate-500 ml-auto" />}
          </div>
          <nav className="p-2 space-y-3">
            {NAV.map(group => (
              <div key={group.group}>
                <div className="px-2 py-1 text-[9px] font-bold uppercase tracking-widest text-slate-600">{group.group}</div>
                {group.items.map(item => {
                  const Icon = item.icon
                  const active = activeSection === item.key
                  return (
                    <button key={item.key} onClick={() => setActiveSection(item.key)}
                      className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-all text-left ${
                        active
                          ? 'bg-brand-600/20 text-brand-300'
                          : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
                      }`}>
                      <Icon className="w-3.5 h-3.5 flex-shrink-0" />
                      {item.label}
                    </button>
                  )
                })}
              </div>
            ))}
          </nav>
          <div className="px-4 py-3 border-t border-slate-700/50 space-y-1.5">
            <div className="flex items-center justify-between">
              <button onClick={refresh}
                className="text-[10px] text-slate-500 hover:text-white flex items-center gap-1 transition-colors">
                <RefreshCw className="w-3 h-3" /> Refresh
              </button>
              <div className="px-1.5 py-0.5 rounded bg-brand-600/20 text-[9px] font-mono text-brand-400">v2.0</div>
            </div>
            <div className="text-[10px] text-slate-600 flex items-center gap-1">
              <Clock className="w-3 h-3" /> Uptime: {uptimeStr}
            </div>
          </div>
        </div>
      </aside>

      {/* ── Content ── */}
      <div className="flex-1 min-w-0">

        {/* Status & Health */}
        {activeSection === 'status' && (
          <AdminSystemHealth pin={pin} />
        )}

        {/* Cache */}
        {activeSection === 'cache' && (
          <div className="space-y-6">
            {/* Flush Controls */}
            <div className="glass rounded-xl overflow-hidden">
              <div className="px-4 py-3 bg-slate-800/50 border-b border-slate-700/50 flex items-center gap-2">
                <Trash2 className="w-4 h-4 text-red-400" />
                <h2 className="text-sm font-semibold text-white">Cache Controls</h2>
              </div>
              <div className="p-4">
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
                  <FlushCard title="Live / Operational"
                    description="Command Center, Queue Board, Driver GPS, SA Lookup, Dispatch Map"
                    ttl="TTL: 30s - 120s" color="blue" loading={flushing === 'live'}
                    onClick={() => handleFlush('live', adminFlushLive)} />
                  <FlushCard title="Historical / Analytics"
                    description="Scorecard, Performance, Decomposition, Forecast, Score"
                    ttl="TTL: 300s - 3600s" color="amber" loading={flushing === 'historical'}
                    onClick={() => handleFlush('historical', adminFlushHistorical)} />
                  <FlushCard title="Static / Reference"
                    description="Garage List, Map Grids, Weather, Skills, Territories"
                    ttl="TTL: 600s - 3600s" color="emerald" loading={flushing === 'static'}
                    onClick={() => handleFlush('static', adminFlushStatic)} />
                  <FlushCard title="Flush Everything"
                    description="Clear all cached data. Next request will fetch fresh from Salesforce."
                    ttl="Nuclear option" color="red" loading={flushing === 'all'}
                    onClick={() => handleFlush('all', (p) => adminFlush(p))} />
                </div>
              </div>
            </div>
            {lastAction && (
              <div className="glass rounded-xl px-4 py-2.5 border-l-2 border-l-emerald-500 flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                <span className="text-sm text-slate-300">
                  Flushed <span className="font-semibold text-white">{lastAction.flushed}</span>
                  {' '}at {lastAction.time.toLocaleTimeString()}
                </span>
              </div>
            )}
            {/* TTL Reference */}
            <div className="glass rounded-xl overflow-hidden">
              <div className="px-4 py-3 bg-slate-800/50 border-b border-slate-700/50">
                <h2 className="text-sm font-semibold text-white">Cache TTL Reference</h2>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-slate-500 border-b border-slate-800">
                      <th className="text-left py-2 px-4 font-medium">Endpoint</th>
                      <th className="text-left py-2 px-4 font-medium">Cache Key</th>
                      <th className="text-center py-2 px-4 font-medium">TTL</th>
                      <th className="text-left py-2 px-4 font-medium">Category</th>
                      <th className="text-left py-2 px-4 font-medium">Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {CACHE_ENTRIES.map((e, i) => (
                      <tr key={i} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                        <td className="py-2 px-4 text-slate-300 font-medium">{e.endpoint}</td>
                        <td className="py-2 px-4 text-slate-500 font-mono text-[10px]">{e.key}</td>
                        <td className="py-2 px-4 text-center">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                            e.ttl <= 60 ? 'bg-blue-500/10 text-blue-400' :
                            e.ttl <= 600 ? 'bg-amber-500/10 text-amber-400' :
                            'bg-emerald-500/10 text-emerald-400'
                          }`}>{e.ttl}s</span>
                        </td>
                        <td className="py-2 px-4 text-slate-500">{e.category}</td>
                        <td className="py-2 px-4 text-slate-600">{e.notes}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* Users & Sessions */}
        {activeSection === 'users' && (
          <div className="space-y-6">
            <AdminUsers pin={pin} />
            <AdminActivityLog pin={pin} defaultCollapsed={true} />
          </div>
        )}

        {/* App Settings */}
        {activeSection === 'settings' && (
          <div className="space-y-6">
            {/* Feature Modules */}
            <div className="glass rounded-xl overflow-hidden">
              <div className="px-4 py-3 bg-slate-800/50 border-b border-slate-700/50 flex items-center gap-2">
                <ToggleRight className="w-4 h-4 text-brand-400" />
                <h2 className="text-sm font-semibold text-white">Feature Modules</h2>
                <span className="text-[10px] text-slate-500 ml-1">Toggle modules on/off — hidden from all users when off</span>
                {featureSaved && <span className="text-[10px] text-emerald-400 ml-auto flex items-center gap-1"><CheckCircle2 className="w-3 h-3" /> Saved</span>}
              </div>
              <div className="p-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                {[
                  { key: 'pta_advisor', label: 'PTA Advisor',  desc: 'Promised time projections' },
                  { key: 'onroute',     label: 'Route Tracker', desc: 'En-route drivers & live tracking links' },
                  { key: 'matrix',      label: 'Insights',      desc: 'Priority matrix advisor' },
                  { key: 'chat',        label: 'AI Chat',       desc: 'Floating chatbot assistant' },
                  { key: 'accounting',  label: 'Accounting',    desc: 'WO Adjustment audit & recommendations' },
                ].map(m => {
                  const on = features[m.key] !== false
                  return (
                    <div key={m.key} className={`flex items-center justify-between rounded-lg border px-4 py-3 transition-colors ${
                      on ? 'bg-slate-800/30 border-slate-700/50' : 'bg-slate-900/50 border-slate-800/30 opacity-60'
                    }`}>
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-slate-200">{m.label}</div>
                        <div className="text-[10px] text-slate-500">{m.desc}</div>
                      </div>
                      <button
                        disabled={featureSaving}
                        onClick={async () => {
                          const next = { ...features, [m.key]: !on }
                          setFeatures(next)
                          setFeatureSaving(true)
                          try {
                            await adminUpdateSettings(pin, { features: next })
                            window.dispatchEvent(new CustomEvent('featuresChanged', { detail: next }))
                            setFeatureSaved(true)
                            setTimeout(() => setFeatureSaved(false), 2000)
                          } catch { /* ignore */ }
                          finally { setFeatureSaving(false) }
                        }}
                        className={`relative w-11 h-6 rounded-full transition-colors flex-shrink-0 ml-3 ${on ? 'bg-emerald-500' : 'bg-slate-600'}`}
                      >
                        <span className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${on ? 'translate-x-5' : ''}`} />
                      </button>
                    </div>
                  )
                })}
              </div>

              {/* Help Video URL */}
              <div className="px-4 pb-4 pt-2 border-t border-slate-700/30 mt-3">
                <label className="text-[10px] text-slate-500 uppercase tracking-wider font-bold block mb-1.5">Help Page Video URL</label>
                <div className="flex items-center gap-2">
                  <input value={helpVideoUrl} onChange={e => setHelpVideoUrl(e.target.value)}
                    placeholder="https://youtu.be/..."
                    className="flex-1 bg-slate-900 border border-slate-700 rounded-lg text-xs px-3 py-2
                               focus:outline-none focus:ring-1 focus:ring-brand-500/40 font-mono text-slate-300 placeholder:text-slate-600" />
                  <button disabled={videoSaving}
                    onClick={async () => {
                      setVideoSaving(true); setVideoSaved(false)
                      try {
                        await adminUpdateSettings(pin, { help_video_url: helpVideoUrl })
                        setVideoSaved(true)
                        setTimeout(() => setVideoSaved(false), 2000)
                      } catch { /* ignore */ }
                      finally { setVideoSaving(false) }
                    }}
                    className="px-3 py-2 bg-brand-600 hover:bg-brand-500 disabled:opacity-40 rounded-lg text-xs font-semibold text-white transition-colors flex items-center gap-1.5">
                    {videoSaving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
                    Save
                  </button>
                  {videoSaved && <span className="text-[10px] text-emerald-400 flex items-center gap-1"><CheckCircle2 className="w-3 h-3" /> Saved</span>}
                </div>
                <p className="text-[10px] text-slate-600 mt-1">YouTube link shown in the Help &gt; How It Works section. Leave blank to hide.</p>
              </div>
            </div>

            {/* Map Style */}
            <div className="glass rounded-xl overflow-hidden">
              <div className="px-4 py-3 bg-slate-800/50 border-b border-slate-700/50 flex items-center gap-2">
                <Map className="w-4 h-4 text-brand-400" />
                <h2 className="text-sm font-semibold text-white">Map Style</h2>
              </div>
              <div className="p-4">
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                  {Object.entries(MAP_STYLES).map(([key, style]) => (
                    <button key={key} onClick={() => handleMapStyleChange(key)}
                      className={`rounded-xl border overflow-hidden text-left transition-all ${
                        mapStyle === key
                          ? 'border-brand-500 ring-2 ring-brand-500/30'
                          : 'border-slate-700/50 hover:border-slate-500'
                      }`}>
                      <div className="relative w-full h-20 bg-slate-800 overflow-hidden">
                        <img src={style.preview} alt={style.name}
                          className="w-full h-full object-cover"
                          style={style.filter ? { filter: style.filter } : {}}
                          loading="lazy" />
                        {mapStyle === key && (
                          <div className="absolute top-1.5 right-1.5 flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-brand-600/90 text-[9px] text-white font-bold">
                            <CheckCircle2 className="w-2.5 h-2.5" /> Active
                          </div>
                        )}
                      </div>
                      <div className="px-2.5 py-2">
                        <div className="text-xs font-semibold text-white">{style.name}</div>
                        <div className="text-[10px] text-slate-500">{style.description}</div>
                      </div>
                    </button>
                  ))}
                </div>
                <p className="text-[10px] text-slate-600 mt-3">Changes apply to all maps immediately. Preference saved in browser.</p>
              </div>
            </div>
          </div>
        )}

        {activeSection === 'ai' && <AdminAI pin={pin} />}
        {activeSection === 'reference' && <AdminReferenceData pin={pin} />}
        {activeSection === 'optimizer' && <AdminOptimizerSync />}
      </div>
    </div>
  )
}


const CACHE_ENTRIES = [
  { endpoint: 'Command Center',  key: 'command_center_{hours}',    ttl: 120,  category: 'Live',       notes: 'Shared across all users' },
  { endpoint: 'Queue Board',     key: 'queue_live',                 ttl: 30,   category: 'Live',       notes: 'Shared, auto-refresh 30s' },
  { endpoint: 'SA Lookup',       key: 'sa_lookup_{number}',         ttl: 30,   category: 'Live',       notes: 'Per SA number' },
  { endpoint: 'Map Drivers',     key: 'map_drivers',                ttl: 120,  category: 'Live',       notes: 'GPS positions' },
  { endpoint: 'Dispatch Map',    key: 'simulate_{tid}_{date}',      ttl: 120,  category: 'Live',       notes: 'Per territory per day' },
  { endpoint: 'Recommend Driver',key: 'recommend_{sa_id}',          ttl: 60,   category: 'Live',       notes: 'Per SA' },
  { endpoint: 'Cascade',         key: 'cascade_{tid}',              ttl: 60,   category: 'Live',       notes: 'Per territory' },
  { endpoint: 'Score',           key: 'scorer_{tid}_{days}',        ttl: 300,  category: 'Historical', notes: 'Composite score' },
  { endpoint: 'Scorecard',       key: 'scorecard_{tid}_{weeks}',    ttl: 3600, category: 'Historical', notes: 'Per territory' },
  { endpoint: 'Performance',     key: 'perf_{tid}_{start}_{end}',   ttl: 3600, category: 'Historical', notes: 'Per territory + period' },
  { endpoint: 'Decomposition',   key: 'decomp_{tid}_{start}_{end}', ttl: 3600, category: 'Historical', notes: 'Response time breakdown' },
  { endpoint: 'Forecast',        key: 'forecast_{tid}_{weeks}',     ttl: 3600, category: 'Historical', notes: 'DOW + weather' },
  { endpoint: 'Garage List',     key: 'garages_list',               ttl: 600,  category: 'Static',     notes: 'All territories' },
  { endpoint: 'Map Grids',       key: 'map_grids',                  ttl: 3600, category: 'Static',     notes: 'Grid geometry' },
  { endpoint: 'Map Weather',     key: 'map_weather',                ttl: 900,  category: 'Static',     notes: 'Weather stations' },
  { endpoint: 'Skills',          key: 'skills_{tid}',               ttl: 3600, category: 'Static',     notes: 'Per territory' },
  { endpoint: 'Priority Matrix', key: 'priority_matrix',            ttl: 600,  category: 'Static',     notes: 'Ops dashboard' },
  { endpoint: 'Ops Territories', key: 'ops_territories',            ttl: 120,  category: 'Live',       notes: 'Territory list with live counts' },
  { endpoint: 'PTA Advisor',     key: 'pta_advisor',                ttl: 900,  category: 'Live',       notes: 'Projected PTA, configurable interval' },
]


function FlushCard({ title, description, ttl, color, loading, onClick }) {
  const colors = {
    blue:   'border-blue-500/20 hover:border-blue-500/40',
    amber:  'border-amber-500/20 hover:border-amber-500/40',
    emerald:'border-emerald-500/20 hover:border-emerald-500/40',
    red:    'border-red-500/20 hover:border-red-500/40',
  }
  const btnColors = {
    blue:   'bg-blue-600 hover:bg-blue-500',
    amber:  'bg-amber-600 hover:bg-amber-500',
    emerald:'bg-emerald-600 hover:bg-emerald-500',
    red:    'bg-red-600 hover:bg-red-500',
  }
  return (
    <div className={`rounded-xl border bg-slate-900/30 p-4 flex flex-col transition-colors ${colors[color]}`}>
      <h3 className="text-sm font-semibold text-white mb-1">{title}</h3>
      <p className="text-[11px] text-slate-500 leading-relaxed mb-1">{description}</p>
      <p className="text-[10px] text-slate-600 mb-3">{ttl}</p>
      <button onClick={onClick} disabled={loading}
        className={`mt-auto w-full py-2 rounded-lg text-xs font-semibold transition-colors disabled:opacity-50
                    flex items-center justify-center gap-1.5 ${btnColors[color]}`}>
        {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
        {loading ? 'Flushing...' : 'Flush'}
      </button>
    </div>
  )
}
