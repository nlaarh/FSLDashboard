import { useState, useEffect, useCallback } from 'react'
import { fetchQueue, fetchRecommend, fetchCascade, fetchGarages } from '../api'
import {
  Clock, AlertTriangle, CheckCircle2, RefreshCw, Loader2, ChevronDown, ChevronUp,
  MapPin, Zap, Users, ArrowRight, Truck, Battery, Wrench, XCircle, Info,
} from 'lucide-react'
import { clsx } from 'clsx'

const URGENCY_COLORS = {
  green:  'bg-emerald-500/20 text-emerald-400 border-emerald-700/30',
  yellow: 'bg-amber-500/20 text-amber-400 border-amber-700/30',
  orange: 'bg-orange-500/20 text-orange-400 border-orange-700/30',
  red:    'bg-red-500/20 text-red-400 border-red-700/30',
}

const URGENCY_BADGE = {
  green:  'bg-emerald-500',
  yellow: 'bg-amber-500',
  orange: 'bg-orange-500',
  red:    'bg-red-500',
}

const TIER_ICONS = { tow: Truck, light: Wrench, battery: Battery }
const TIER_COLORS = { tow: 'text-blue-400', light: 'text-purple-400', battery: 'text-amber-400' }

function UrgencyDot({ level }) {
  return <span className={clsx('inline-block w-2.5 h-2.5 rounded-full', URGENCY_BADGE[level])} />
}

function TimerBadge({ min, pta, breached }) {
  const color = breached ? 'text-red-400' : min > 45 ? 'text-orange-400' : min > 30 ? 'text-amber-400' : 'text-emerald-400'
  return (
    <div className="text-right">
      <div className={clsx('text-lg font-black tabular-nums', color)}>{min}m</div>
      {pta && <div className="text-[10px] text-slate-500">PTA {pta}m</div>}
    </div>
  )
}

// ── Driver Recommendation Panel ──────────────────────────────────────────────

function DriverPanel({ saId, onClose }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    setLoading(true)
    fetchRecommend(saId)
      .then(setData)
      .catch(e => setError(e.response?.data?.detail || e.message))
      .finally(() => setLoading(false))
  }, [saId])

  if (loading) return (
    <div className="p-4 flex items-center gap-2 text-slate-400 text-sm">
      <Loader2 className="w-4 h-4 animate-spin" /> Finding best drivers...
    </div>
  )
  if (error) return <div className="p-4 text-red-400 text-sm">{error}</div>
  if (!data || data.error) return <div className="p-4 text-slate-500 text-sm">{data?.error || 'No data'}</div>

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold text-white flex items-center gap-2">
          <Users className="w-4 h-4 text-brand-400" />
          Top {data.recommendations.length} Drivers for {data.sa.work_type}
        </h4>
        <span className="text-[10px] text-slate-500">{data.total_eligible} eligible of {data.total_evaluated} evaluated</span>
      </div>
      {data.recommendations.map((d, i) => (
        <div key={d.driver_id}
          className={clsx('rounded-lg p-3 border transition-all',
            i === 0 ? 'bg-brand-950/30 border-brand-700/40' : 'bg-slate-800/30 border-slate-700/30')}>
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className={clsx('w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold',
                i === 0 ? 'bg-brand-600 text-white' : 'bg-slate-700 text-slate-300')}>
                {i + 1}
              </span>
              <span className="font-semibold text-white text-sm">{d.driver_name}</span>
              <span className={clsx('text-[10px] px-1.5 py-0.5 rounded font-medium',
                d.skill_match === 'full' ? 'bg-emerald-900/40 text-emerald-400' : 'bg-amber-900/40 text-amber-400')}>
                {d.skill_match === 'full' ? 'Full Match' : 'Cross-Skill'}
              </span>
            </div>
            <div className="text-lg font-black text-brand-400">{d.composite_score}</div>
          </div>
          <div className="grid grid-cols-4 gap-2 text-center">
            {[
              { label: 'ETA', value: d.eta_min ? `${d.eta_min}m` : '?', score: d.scores.eta },
              { label: 'Skill', value: d.driver_tier, score: d.scores.skill },
              { label: 'Load', value: `${d.active_jobs} jobs`, score: d.scores.workload },
              { label: 'Shift', value: d.active_jobs === 0 ? 'Fresh' : 'Active', score: d.scores.shift },
            ].map(s => (
              <div key={s.label}>
                <div className="text-[10px] text-slate-500">{s.label}</div>
                <div className="text-xs text-slate-300 font-medium">{s.value}</div>
                <div className="h-1 bg-slate-800 rounded-full mt-1 overflow-hidden">
                  <div className="h-full bg-brand-500 rounded-full" style={{ width: `${s.score}%` }} />
                </div>
              </div>
            ))}
          </div>
          {d.distance_mi && (
            <div className="text-[10px] text-slate-500 mt-1 flex items-center gap-1">
              <MapPin className="w-3 h-3" /> {d.distance_mi} mi away
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

// ── Cascade Panel ────────────────────────────────────────────────────────────

function CascadeSection({ territories }) {
  const [selectedTerritory, setSelectedTerritory] = useState(null)
  const [cascadeData, setCascadeData] = useState(null)
  const [loading, setLoading] = useState(false)

  const loadCascade = (tid) => {
    setSelectedTerritory(tid)
    setLoading(true)
    fetchCascade(tid)
      .then(setCascadeData)
      .catch(() => setCascadeData(null))
      .finally(() => setLoading(false))
  }

  if (!territories?.length) return null

  return (
    <div className="glass rounded-xl p-5 space-y-4">
      <h3 className="font-semibold text-slate-200 flex items-center gap-2">
        <Zap className="w-4 h-4 text-amber-400" />
        Cross-Skill Cascade
        <span className="ml-auto text-xs text-slate-500 font-normal">Select a territory to analyze</span>
      </h3>

      <div className="flex flex-wrap gap-2">
        {territories.map(t => (
          <button key={t.id} onClick={() => loadCascade(t.id)}
            className={clsx('px-3 py-1.5 rounded-lg text-xs font-medium transition-all border',
              selectedTerritory === t.id
                ? 'bg-brand-600/20 text-brand-300 border-brand-700/40'
                : 'bg-slate-800/50 text-slate-400 hover:text-white border-slate-700/30 hover:border-slate-600')}>
            {t.name} ({t.count})
          </button>
        ))}
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-slate-400 text-sm py-4">
          <Loader2 className="w-4 h-4 animate-spin" /> Analyzing skill utilization...
        </div>
      )}

      {cascadeData && !loading && (
        <div className="space-y-4">
          {/* Utilization bars */}
          <div className="grid grid-cols-3 gap-3">
            {['tow', 'light', 'battery'].map(tier => {
              const u = cascadeData.utilization[tier]
              const Icon = TIER_ICONS[tier]
              return (
                <div key={tier} className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/30">
                  <div className="flex items-center gap-2 mb-2">
                    <Icon className={clsx('w-4 h-4', TIER_COLORS[tier])} />
                    <span className="text-xs font-semibold text-slate-300 capitalize">{tier}</span>
                  </div>
                  <div className="text-lg font-black text-white">{u.total}</div>
                  <div className="flex gap-2 text-[10px] text-slate-500 mt-1">
                    <span className="text-emerald-400">{u.idle} idle</span>
                    <span className="text-red-400">{u.busy} busy</span>
                  </div>
                  <div className="h-1.5 bg-slate-900 rounded-full mt-2 overflow-hidden">
                    <div className="h-full bg-brand-500 rounded-full"
                      style={{ width: `${u.utilization_pct}%` }} />
                  </div>
                  <div className="text-[10px] text-slate-500 mt-0.5">{u.utilization_pct}% utilized</div>
                </div>
              )
            })}
          </div>

          {/* Cross-skill arrows */}
          {cascadeData.cross_skill_available.length > 0 && (
            <div className="space-y-2">
              <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Available Cross-Skill Coverage</div>
              {cascadeData.cross_skill_available.map((cs, i) => (
                <div key={i} className="flex items-center gap-2 bg-amber-950/20 border border-amber-800/20 rounded-lg p-2 text-sm">
                  <ArrowRight className="w-4 h-4 text-amber-400" />
                  <span className="text-amber-200">
                    {cs.idle_count} idle <span className="font-bold capitalize">{cs.from}</span> drivers can cover{' '}
                    <span className="font-bold capitalize">{cs.to}</span> calls
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* Cascade opportunities */}
          {cascadeData.cascade_opportunities.length > 0 && (
            <div className="space-y-2">
              <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                Active Cascade Opportunities ({cascadeData.cascade_opportunities.length})
              </div>
              {cascadeData.cascade_opportunities.map(opp => (
                <div key={opp.sa_id} className="bg-slate-800/30 border border-slate-700/30 rounded-lg p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-white">
                      {opp.work_type} · {opp.sa_number}
                    </span>
                    <span className="text-xs text-orange-400 font-medium">{opp.wait_min}m waiting</span>
                  </div>
                  <div className="text-xs text-emerald-400">{opp.recommendation}</div>
                </div>
              ))}
            </div>
          )}

          {cascadeData.cascade_opportunities.length === 0 && (
            <div className="text-sm text-slate-500 text-center py-2">
              No cascade needed — primary drivers available for all open calls
            </div>
          )}

          <div className="text-[10px] text-slate-600">
            Potential time saved: {cascadeData.summary.potential_time_saved_min} min across {cascadeData.summary.cascade_eligible} calls
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main Queue Board ─────────────────────────────────────────────────────────

export default function QueueBoard() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [expandedSa, setExpandedSa] = useState(null)
  const [sortBy, setSortBy] = useState('wait')
  const [filterUrgency, setFilterUrgency] = useState('all')
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [lastRefresh, setLastRefresh] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    fetchQueue()
      .then(d => { setData(d); setLastRefresh(new Date()) })
      .catch(e => setError(e.response?.data?.detail || e.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (!autoRefresh) return
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [autoRefresh, load])

  const queue = data?.queue || []
  const summary = data?.summary || {}

  // Filter & sort
  const filtered = queue
    .filter(q => filterUrgency === 'all' || q.urgency === filterUrgency)
    .sort((a, b) => {
      if (sortBy === 'wait') return b.wait_min - a.wait_min
      if (sortBy === 'urgency') {
        const order = { red: 0, orange: 1, yellow: 2, green: 3 }
        return (order[a.urgency] ?? 4) - (order[b.urgency] ?? 4)
      }
      return 0
    })

  // Territory list for cascade panel
  const territories = summary.by_territory || []

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Live Queue Board</h1>
          <p className="text-sm text-slate-500 mt-0.5">Real-time open service appointments with aging and urgency</p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
            <input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)}
              className="rounded border-slate-600" />
            Auto-refresh (30s)
          </label>
          <button onClick={load} disabled={loading}
            className="p-2 rounded-lg hover:bg-slate-800 transition-colors disabled:opacity-50">
            <RefreshCw className={clsx('w-4 h-4', loading ? 'animate-spin text-brand-400' : 'text-slate-400')} />
          </button>
          {lastRefresh && (
            <span className="text-[10px] text-slate-600">
              {lastRefresh.toLocaleTimeString()}
            </span>
          )}
        </div>
      </div>

      {error && (
        <div className="rounded-xl bg-red-950/30 border border-red-800/30 p-4 text-red-300 text-sm">{error}</div>
      )}

      {/* Summary strip */}
      {summary.total_open != null && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <div className="glass rounded-xl p-4 border border-slate-700/30">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Open Calls</div>
            <div className="text-2xl font-black text-white">{summary.total_open}</div>
          </div>
          <div className={clsx('glass rounded-xl p-4 border',
            summary.breached_count > 0 ? 'border-red-800/30' : 'border-slate-700/30')}>
            <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">PTA Breached</div>
            <div className={clsx('text-2xl font-black',
              summary.breached_count > 0 ? 'text-red-400' : 'text-emerald-400')}>
              {summary.breached_count}
            </div>
          </div>
          <div className="glass rounded-xl p-4 border border-slate-700/30">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Avg Wait</div>
            <div className={clsx('text-2xl font-black',
              summary.avg_wait > 45 ? 'text-red-400' : summary.avg_wait > 30 ? 'text-amber-400' : 'text-emerald-400')}>
              {summary.avg_wait}m
            </div>
          </div>
          <div className="glass rounded-xl p-4 border border-slate-700/30">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Max Wait</div>
            <div className="text-2xl font-black text-red-400">{summary.max_wait}m</div>
          </div>
          <div className="glass rounded-xl p-4 border border-slate-700/30">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">By Urgency</div>
            <div className="flex items-center gap-2 mt-1">
              {['red', 'orange', 'yellow', 'green'].map(u => (
                <div key={u} className="flex items-center gap-1">
                  <UrgencyDot level={u} />
                  <span className="text-xs text-slate-400">{summary.by_urgency?.[u] || 0}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex gap-1 p-1 bg-slate-900 rounded-lg">
          {['all', 'red', 'orange', 'yellow', 'green'].map(u => (
            <button key={u} onClick={() => setFilterUrgency(u)}
              className={clsx('px-2.5 py-1 rounded-md text-xs font-medium transition-all',
                filterUrgency === u
                  ? 'bg-slate-700 text-white'
                  : 'text-slate-500 hover:text-white')}>
              {u === 'all' ? 'All' : <><UrgencyDot level={u} /> <span className="ml-1 capitalize">{u}</span></>}
            </button>
          ))}
        </div>
        <div className="flex gap-1 p-1 bg-slate-900 rounded-lg">
          {[{ key: 'wait', label: 'Wait Time' }, { key: 'urgency', label: 'Urgency' }].map(s => (
            <button key={s.key} onClick={() => setSortBy(s.key)}
              className={clsx('px-2.5 py-1 rounded-md text-xs font-medium transition-all',
                sortBy === s.key ? 'bg-slate-700 text-white' : 'text-slate-500 hover:text-white')}>
              {s.label}
            </button>
          ))}
        </div>
        <span className="text-xs text-slate-600 ml-auto">{filtered.length} calls shown</span>
      </div>

      {/* Queue rows */}
      {loading && !data && (
        <div className="flex items-center justify-center py-20 gap-3">
          <Loader2 className="w-6 h-6 animate-spin text-brand-400" />
          <span className="text-slate-400">Loading live queue...</span>
        </div>
      )}

      <div className="space-y-2">
        {filtered.map(item => {
          const TierIcon = TIER_ICONS[item.call_tier] || Wrench
          const isExpanded = expandedSa === item.sa_id
          return (
            <div key={item.sa_id}>
              <div
                onClick={() => setExpandedSa(isExpanded ? null : item.sa_id)}
                className={clsx(
                  'glass rounded-xl p-4 border cursor-pointer transition-all hover:border-slate-600',
                  URGENCY_COLORS[item.urgency]
                )}
              >
                <div className="flex items-center gap-4">
                  {/* Urgency dot */}
                  <UrgencyDot level={item.urgency} />

                  {/* Call info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <TierIcon className={clsx('w-4 h-4', TIER_COLORS[item.call_tier])} />
                      <span className="font-semibold text-white text-sm">{item.work_type}</span>
                      <span className="text-[10px] text-slate-500">#{item.number}</span>
                      {item.pta_breached && (
                        <span className="text-[10px] px-1.5 py-0.5 bg-red-900/40 text-red-400 rounded font-medium">
                          PTA BREACHED
                        </span>
                      )}
                      {item.declined && (
                        <span className="text-[10px] px-1.5 py-0.5 bg-amber-900/40 text-amber-400 rounded font-medium">
                          DECLINED
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-slate-500 mt-0.5 flex items-center gap-3">
                      <span>{item.territory_name}</span>
                      {item.address && <span className="flex items-center gap-1"><MapPin className="w-3 h-3" />{item.address}</span>}
                      <span>Created {item.created}</span>
                      <span className="text-slate-600">{item.dispatch_method}</span>
                    </div>
                  </div>

                  {/* Timer */}
                  <TimerBadge min={item.wait_min} pta={item.pta_promise} breached={item.pta_breached} />

                  {/* Suggestion */}
                  {item.escalation_suggestion && (
                    <div className="hidden lg:block max-w-[240px] text-[10px] text-amber-400 leading-tight pl-3 border-l border-slate-700">
                      {item.escalation_suggestion}
                    </div>
                  )}

                  {/* Expand */}
                  {isExpanded ? <ChevronUp className="w-4 h-4 text-slate-500" /> : <ChevronDown className="w-4 h-4 text-slate-500" />}
                </div>

                {/* Mobile suggestion */}
                {item.escalation_suggestion && (
                  <div className="lg:hidden text-[10px] text-amber-400 mt-2 pl-6">
                    {item.escalation_suggestion}
                  </div>
                )}
              </div>

              {/* Expanded: Driver Recommendations */}
              {isExpanded && (
                <div className="ml-6 mt-1 glass rounded-xl border border-brand-700/30 overflow-hidden">
                  <DriverPanel saId={item.sa_id} />
                </div>
              )}
            </div>
          )
        })}
      </div>

      {filtered.length === 0 && data && (
        <div className="text-center py-12 text-slate-500">
          <CheckCircle2 className="w-8 h-8 mx-auto mb-2 text-emerald-500" />
          <div className="text-sm">No open calls matching filter</div>
        </div>
      )}

      {/* Cross-Skill Cascade */}
      <CascadeSection territories={territories} />
    </div>
  )
}
