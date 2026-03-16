import { useState, useEffect, useCallback } from 'react'
import {
  Loader2, RefreshCw, ArrowRightLeft, TrendingDown, AlertTriangle,
  CheckCircle2, ChevronDown, ChevronUp, HelpCircle, X, ArrowRight,
  Lightbulb, Truck, Users, Zap, Bot, ShieldAlert, Clock, Navigation,
} from 'lucide-react'
import { clsx } from 'clsx'
import { fetchMatrixHealth, fetchInsights } from '../api'

// ═══════════════════════════════════════════════════════════════════════════════
// TAB DEFINITIONS
// ═══════════════════════════════════════════════════════════════════════════════

const TABS = [
  { id: 'territory', label: 'Territory Rebalancing',  icon: ArrowRightLeft, color: 'text-brand-400', desc: 'Zone-to-garage assignment optimization based on acceptance rates and cascade patterns.' },
  { id: 'garage',    label: 'Garage Action Plan',     icon: ShieldAlert, color: 'text-red-400',     desc: 'Performance review of high-volume garages — completion rates, decline patterns, response times.' },
  { id: 'driver',    label: 'Driver Optimization',    icon: Navigation,  color: 'text-amber-400',   desc: 'Fleet driver performance — slow response, GPS issues, low completion rates.' },
  { id: 'dispatch',  label: 'Dispatch Efficiency',    icon: Zap,         color: 'text-cyan-400',    desc: 'System-level dispatch patterns — cascade rates, completion by method, work type distribution.' },
]

// ═══════════════════════════════════════════════════════════════════════════════
// AI INSIGHT CARD — Generic renderer for LLM recommendations
// ═══════════════════════════════════════════════════════════════════════════════

const SEV_STYLES = {
  critical: { border: 'border-red-500/30', bg: 'bg-red-950/20', badge: 'bg-red-500/20 text-red-400', dot: 'bg-red-500' },
  warning:  { border: 'border-amber-500/30', bg: 'bg-amber-950/15', badge: 'bg-amber-500/20 text-amber-400', dot: 'bg-amber-500' },
  monitor:  { border: 'border-slate-700/30', bg: 'bg-slate-900/40', badge: 'bg-slate-700/30 text-slate-400', dot: 'bg-slate-500' },
  info:     { border: 'border-blue-500/20', bg: 'bg-blue-950/10', badge: 'bg-blue-500/20 text-blue-400', dot: 'bg-blue-500' },
}

function InsightCard({ item, index, expanded, onToggle }) {
  const sev = SEV_STYLES[item.severity] || SEV_STYLES.monitor
  const name = item.garage || item.driver || item.area || item.title || `Item ${index + 1}`
  const type = item.driver_type || item.type || null

  return (
    <div className={clsx('rounded-xl border overflow-hidden transition-colors', sev.border, sev.bg)}>
      <button onClick={onToggle} className="w-full text-left px-5 py-4 flex items-start gap-3">
        <div className={clsx('w-2.5 h-2.5 rounded-full mt-1.5 shrink-0', sev.dot)} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-white font-semibold text-sm">{name}</span>
            <span className={clsx('text-[10px] px-1.5 py-0.5 rounded font-bold uppercase', sev.badge)}>{item.severity}</span>
            {type && <span className="text-[10px] text-slate-500 bg-slate-800 px-1.5 py-0.5 rounded">{type}</span>}
          </div>
          {item.issues && item.issues.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-1.5">
              {item.issues.map((iss, i) => (
                <span key={i} className="text-[11px] text-slate-400 bg-slate-800/60 px-2 py-0.5 rounded">{iss}</span>
              ))}
            </div>
          )}
        </div>
        <div className="shrink-0">
          {expanded ? <ChevronUp className="w-4 h-4 text-slate-500" /> : <ChevronDown className="w-4 h-4 text-slate-500" />}
        </div>
      </button>

      {expanded && (
        <div className="px-5 pb-5 pt-0 border-t border-slate-800/50 space-y-3">
          {item.recommendations && item.recommendations.length > 0 && (
            <div>
              <div className="text-[10px] text-emerald-400 uppercase tracking-wider font-bold mt-3 mb-2">Recommendations</div>
              <div className="space-y-2">
                {item.recommendations.map((rec, i) => (
                  <div key={i} className="flex gap-2 text-sm text-slate-300 leading-relaxed">
                    <span className="text-emerald-500 mt-0.5 shrink-0">&#x2192;</span>
                    <span>{rec}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {item.impact && (
            <div className="rounded-lg bg-slate-800/40 border border-slate-700/30 px-3 py-2">
              <div className="text-[10px] text-brand-400 uppercase tracking-wider font-bold mb-1">Expected Impact</div>
              <p className="text-sm text-slate-400 leading-relaxed">{item.impact}</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// AI TAB CONTENT — Loads insights from /api/insights/{category}
// ═══════════════════════════════════════════════════════════════════════════════

function AIInsightsTab({ category, description }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [expanded, setExpanded] = useState(0)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const d = await fetchInsights(category)
      setData(d)
      if (d.recommendations?.length > 0) setExpanded(0)
    } catch (e) {
      const detail = e.response?.data?.detail || e.message
      setError(detail || 'Failed to load insights')
    } finally {
      setLoading(false)
    }
  }, [category])

  useEffect(() => { load() }, [load])

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-4">
        <Loader2 className="w-8 h-8 text-brand-400 animate-spin" />
        <p className="text-slate-500 text-sm">Analyzing data and generating recommendations...</p>
        <p className="text-slate-600 text-xs">First load with AI may take 15-30 seconds</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-4">
        <AlertTriangle className="w-8 h-8 text-red-400" />
        <p className="text-red-400 text-sm max-w-md text-center">{error}</p>
        <button onClick={load} className="text-brand-400 text-sm hover:underline">Retry</button>
      </div>
    )
  }

  if (!data) return null

  const recs = data.recommendations || []
  const criticalCount = recs.filter(r => r.severity === 'critical').length
  const warningCount = recs.filter(r => r.severity === 'warning').length

  return (
    <div className="space-y-4">
      {/* Source badge + refresh */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={clsx('flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider px-2.5 py-1 rounded-lg',
            data.source === 'ai' ? 'bg-purple-500/15 text-purple-400' : 'bg-slate-700/30 text-slate-400'
          )}>
            {data.source === 'ai' ? <Bot className="w-3 h-3" /> : <Lightbulb className="w-3 h-3" />}
            {data.source === 'ai' ? `AI Analysis (${data.model})` : 'Rule-Based Analysis'}
          </div>
          <span className="text-[10px] text-slate-600">
            {recs.length} findings • {criticalCount} critical • {warningCount} warning • 7-day window
          </span>
        </div>
        <button onClick={load} className="p-2 rounded-lg text-slate-500 hover:text-white hover:bg-slate-800 transition-all" title="Refresh analysis">
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Description */}
      <p className="text-xs text-slate-500 leading-relaxed">{description}</p>

      {/* Recommendation cards */}
      {recs.length === 0 ? (
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-8 text-center">
          <CheckCircle2 className="w-10 h-10 text-emerald-500 mx-auto mb-3" />
          <p className="text-slate-400">No issues found — everything looks healthy for this category.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {recs.map((item, i) => (
            <InsightCard
              key={i}
              item={item}
              index={i}
              expanded={expanded === i}
              onToggle={() => setExpanded(expanded === i ? null : i)}
            />
          ))}
        </div>
      )}

      {/* Generated timestamp */}
      {data.generated_at && (
        <p className="text-[10px] text-slate-600 text-right">
          Generated {new Date(data.generated_at).toLocaleString()} • Cached 30 min
        </p>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// TERRITORY REBALANCING TAB — Existing matrix content
// ═══════════════════════════════════════════════════════════════════════════════

function pctBadge(val, threshold, inverse = false) {
  if (val == null) return <span className="text-slate-600 text-xs">N/A</span>
  const bad = inverse ? val > threshold : val < threshold
  const warn = inverse ? val > threshold * 0.85 : val < threshold * 1.15
  const color = bad ? 'text-red-400' : warn ? 'text-amber-400' : 'text-emerald-400'
  return <span className={`font-semibold ${color}`}>{val}%</span>
}

function csatBadge(val) {
  if (val == null) return <span className="text-slate-600 text-xs">No surveys</span>
  const color = val >= 82 ? 'text-emerald-400' : val >= 70 ? 'text-amber-400' : 'text-red-400'
  return <span className={`font-semibold ${color}`}>{val}%</span>
}

function impactTag(value, unit, color = 'text-brand-300') {
  return (
    <div className="flex flex-col items-center px-3 py-1.5 rounded-lg bg-slate-800/50">
      <span className={`text-lg font-bold ${color}`}>{value.toLocaleString()}</span>
      <span className="text-[10px] text-slate-500 uppercase tracking-wider">{unit}</span>
    </div>
  )
}

function RecommendationCard({ rec, expanded, onToggle }) {
  const { zone, current_primary, current_accept_pct, current_satisfaction,
    suggested_primary, suggested_accept_pct, suggested_satisfaction, impact, confidence } = rec
  const improvePct = (suggested_accept_pct - current_accept_pct).toFixed(1)
  const csatWarning = suggested_satisfaction != null && current_satisfaction != null && suggested_satisfaction < current_satisfaction

  return (
    <div className="rounded-xl border border-slate-700/50 bg-slate-900/60 overflow-hidden hover:border-slate-600/50 transition-colors">
      <button onClick={onToggle} className="w-full text-left px-5 py-4 flex items-start gap-4">
        <ArrowRightLeft className="w-5 h-5 text-amber-400 mt-0.5 shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-white font-semibold">Zone {zone}</span>
            <span className="text-slate-600">—</span>
            <span className="text-red-400 font-medium">{current_primary}</span>
            <span className="text-slate-500 text-xs">({current_accept_pct}% accept)</span>
            <ArrowRight className="w-3.5 h-3.5 text-amber-400" />
            <span className="text-emerald-400 font-medium">{suggested_primary}</span>
            <span className="text-slate-500 text-xs">({suggested_accept_pct}% accept)</span>
            {confidence === 'high' && <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400 font-medium uppercase">High confidence</span>}
            {csatWarning && <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 font-medium uppercase flex items-center gap-1"><AlertTriangle className="w-3 h-3" /> Lower CSAT</span>}
          </div>
          <p className="text-sm text-slate-400 mt-1.5 leading-relaxed">
            Current primary only accepts <span className="text-red-400 font-semibold">{current_accept_pct}%</span> of calls.{' '}
            Swapping to <span className="text-emerald-400 font-medium">{suggested_primary}</span> would improve acceptance by{' '}
            <span className="text-white font-semibold">+{improvePct}%</span>, avoid ~<span className="text-brand-300 font-medium">{impact.cascades_avoided}</span> cascades,
            and save ~<span className="text-brand-300 font-medium">{Math.round(impact.minutes_saved / 60)}</span> hours of member wait time per month.
          </p>
        </div>
        {expanded ? <ChevronUp className="w-4 h-4 text-slate-500 shrink-0" /> : <ChevronDown className="w-4 h-4 text-slate-500 shrink-0" />}
      </button>
      {expanded && (
        <div className="px-5 pb-5 pt-0 border-t border-slate-800">
          <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_1fr] gap-4 mt-4 items-center">
            <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-4">
              <div className="text-[10px] text-red-400 uppercase tracking-wider font-semibold mb-2">Current Primary</div>
              <div className="text-white font-semibold">{current_primary}</div>
              <div className="mt-2 space-y-1 text-sm">
                <div className="flex justify-between"><span className="text-slate-500">Accept Rate</span>{pctBadge(current_accept_pct, 75)}</div>
                <div className="flex justify-between"><span className="text-slate-500">CSAT Score</span>{csatBadge(current_satisfaction)}</div>
                <div className="flex justify-between"><span className="text-slate-500">Monthly Volume</span><span className="text-slate-300 font-medium">{impact.primary_volume.toLocaleString()} calls</span></div>
              </div>
            </div>
            <div className="hidden md:flex flex-col items-center gap-1">
              <ArrowRight className="w-6 h-6 text-amber-400" />
              <span className="text-[10px] text-amber-400 font-medium">SWAP</span>
            </div>
            <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-4">
              <div className="text-[10px] text-emerald-400 uppercase tracking-wider font-semibold mb-2">Recommended Primary</div>
              <div className="text-white font-semibold">{suggested_primary}</div>
              <div className="mt-2 space-y-1 text-sm">
                <div className="flex justify-between"><span className="text-slate-500">Accept Rate</span>{pctBadge(suggested_accept_pct, 75)}</div>
                <div className="flex justify-between"><span className="text-slate-500">CSAT Score</span>{csatBadge(suggested_satisfaction)}</div>
              </div>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-3">
            {impactTag(impact.cascades_avoided, 'fewer cascades/mo', 'text-emerald-400')}
            {impactTag(Math.round(impact.minutes_saved / 60), 'hours saved/mo', 'text-brand-300')}
            {impactTag(impact.cnw_avoided, 'fewer CNW/mo', 'text-amber-400')}
          </div>
        </div>
      )}
    </div>
  )
}

function ZoneHealthRow({ zone, expanded, onToggle }) {
  const { zone: name, primary_garage, primary_accept_pct, primary_volume, cascade_pct, chain } = zone
  const healthy = primary_accept_pct != null && primary_accept_pct >= 75
  return (
    <div className={`rounded-lg border ${healthy ? 'border-slate-800' : 'border-amber-500/20'} bg-slate-900/40 overflow-hidden`}>
      <button onClick={onToggle} className="w-full text-left px-4 py-3 flex items-center gap-3 text-sm">
        <div className={`w-2 h-2 rounded-full flex-shrink-0 ${healthy ? 'bg-emerald-500' : 'bg-amber-500'}`} />
        <span className="text-slate-300 font-medium w-24 flex-shrink-0">{name}</span>
        <span className="text-slate-400 text-xs flex-1 truncate">{primary_garage}</span>
        <span className="w-14 text-right">{pctBadge(primary_accept_pct, 75)}</span>
        <span className="w-14 text-right text-slate-400 text-xs">{primary_volume?.toLocaleString() || '—'}</span>
        <span className="w-10 text-right">{pctBadge(cascade_pct, 20, true)}</span>
        {expanded ? <ChevronUp className="w-3.5 h-3.5 text-slate-600" /> : <ChevronDown className="w-3.5 h-3.5 text-slate-600" />}
      </button>
      {expanded && chain && chain.length > 0 && (
        <div className="px-4 pb-3 border-t border-slate-800">
          <div className="text-[10px] text-slate-500 uppercase tracking-wider mt-2 mb-1.5">Cascade Chain</div>
          <div className="space-y-1">
            {chain.map((c, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                <span className="w-8 text-slate-600 text-right">#{c.rank}</span>
                <span className={`flex-1 ${i === 0 ? 'text-white font-medium' : 'text-slate-400'}`}>{c.garage}</span>
                <span className="w-12 text-right">{pctBadge(c.accept_pct, 75)}</span>
                <span className="text-slate-600 w-16 text-right">{c.total?.toLocaleString()} calls</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function TerritoryRebalancingTab() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [expandedRec, setExpandedRec] = useState(null)
  const [expandedZone, setExpandedZone] = useState(null)
  const [showAllZones, setShowAllZones] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const d = await fetchMatrixHealth('last_month')
      setData(d)
      if (d.recommendations?.length > 0) setExpandedRec(0)
    } catch {
      setError('Failed to load matrix data. First load may take 15-20 seconds.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return <div className="flex flex-col items-center justify-center py-20 gap-4"><Loader2 className="w-8 h-8 text-brand-400 animate-spin" /><p className="text-slate-500 text-sm">Loading territory analysis...</p></div>
  if (error) return <div className="flex flex-col items-center justify-center py-20 gap-4"><AlertTriangle className="w-8 h-8 text-red-400" /><p className="text-red-400 text-sm">{error}</p><button onClick={load} className="text-brand-400 text-sm hover:underline">Retry</button></div>

  const recs = data?.recommendations || []
  const zones = data?.zones || []
  const summary = data?.summary || {}
  const problemZones = zones.filter(z => z.primary_accept_pct != null && z.primary_accept_pct < 75)
  const healthyZones = zones.filter(z => z.primary_accept_pct == null || z.primary_accept_pct >= 75)
  const displayZones = showAllZones ? zones : problemZones.slice(0, 15)

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-500">Zone-to-garage priority matrix analysis — identifies where swapping the primary garage would reduce cascades and wait times.</p>
        <button onClick={load} className="p-2 rounded-lg text-slate-500 hover:text-white hover:bg-slate-800 transition-all" title="Refresh"><RefreshCw className="w-4 h-4" /></button>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {[
          { label: 'Zones', value: summary.zones_analyzed, color: 'text-white' },
          { label: 'Total Calls', value: summary.total_calls?.toLocaleString(), color: 'text-white' },
          { label: 'Declined', value: summary.total_declined?.toLocaleString(), color: 'text-red-400' },
          { label: 'Problem Zones', value: problemZones.length, color: problemZones.length > 0 ? 'text-amber-400' : 'text-emerald-400' },
          { label: 'Swaps', value: recs.length, color: recs.length > 0 ? 'text-brand-300' : 'text-slate-400' },
        ].map((s, i) => (
          <div key={i} className="rounded-lg bg-slate-900/60 border border-slate-800 px-4 py-3">
            <div className="text-[10px] text-slate-500 uppercase tracking-wider">{s.label}</div>
            <div className={`text-xl font-bold mt-1 ${s.color}`}>{s.value ?? '—'}</div>
          </div>
        ))}
      </div>

      {/* Recommendations */}
      <div>
        <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
          <TrendingDown className="w-4 h-4 text-amber-400" />
          Recommended Swaps
          <span className="text-xs text-slate-500 font-normal ml-2">{recs.length === 0 ? 'No adjustments needed' : `${recs.length} flagged`}</span>
        </h3>
        {recs.length === 0 ? (
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-8 text-center">
            <CheckCircle2 className="w-10 h-10 text-emerald-500 mx-auto mb-3" />
            <p className="text-slate-400">All zones are performing well.</p>
          </div>
        ) : (
          <div className="space-y-3">{recs.map((rec, i) => <RecommendationCard key={i} rec={rec} expanded={expandedRec === i} onToggle={() => setExpandedRec(expandedRec === i ? null : i)} />)}</div>
        )}
      </div>

      {/* Zone Overview */}
      <div>
        <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-slate-500" />
          Zone Health
          <span className="text-xs text-slate-500 font-normal ml-2">{problemZones.length} problem • {healthyZones.length} healthy</span>
        </h3>
        <div className="flex items-center gap-3 px-4 py-2 text-[10px] text-slate-600 uppercase tracking-wider">
          <span className="w-2" /><span className="w-24 flex-shrink-0">Zone</span><span className="flex-1">Primary</span>
          <span className="w-14 text-right">Accept</span><span className="w-14 text-right">Volume</span><span className="w-10 text-right">Cascade</span><span className="w-3.5" />
        </div>
        <div className="space-y-1.5">
          {displayZones.map((z, i) => <ZoneHealthRow key={i} zone={z} expanded={expandedZone === i} onToggle={() => setExpandedZone(expandedZone === i ? null : i)} />)}
        </div>
        {!showAllZones && zones.length > 15 && <button onClick={() => setShowAllZones(true)} className="mt-3 text-sm text-brand-400 hover:text-brand-300">Show all {zones.length} zones</button>}
        {showAllZones && zones.length > 15 && <button onClick={() => setShowAllZones(false)} className="mt-3 text-sm text-brand-400 hover:text-brand-300">Show problem zones only</button>}
      </div>

      {data?.computed_at && <p className="text-[10px] text-slate-600 text-right">Computed {new Date(data.computed_at).toLocaleString()}</p>}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT — Tabbed Actionable Insights
// ═══════════════════════════════════════════════════════════════════════════════

export default function MatrixAdvisor() {
  const [activeTab, setActiveTab] = useState('garage')
  const today = new Date().toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-3">
          <Lightbulb className="w-6 h-6 text-brand-400" />
          Actionable Insights
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          AI-powered recommendations to improve garage performance, driver efficiency, dispatch accuracy, and territory coverage — {today}
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-slate-800/50 pb-1 overflow-x-auto">
        {TABS.map(t => (
          <button key={t.id} onClick={() => setActiveTab(t.id)}
            className={clsx(
              'flex items-center gap-1.5 px-4 py-2 rounded-t-lg text-sm font-medium transition-all whitespace-nowrap shrink-0',
              activeTab === t.id
                ? 'bg-slate-800/80 text-white border border-slate-700/50 border-b-slate-950'
                : 'text-slate-400 hover:text-white hover:bg-slate-800/30 border border-transparent'
            )}>
            <t.icon className={clsx('w-3.5 h-3.5', activeTab === t.id ? t.color : '')} />
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === 'territory' ? (
        <TerritoryRebalancingTab />
      ) : (
        <AIInsightsTab
          key={activeTab}
          category={activeTab}
          description={TABS.find(t => t.id === activeTab)?.desc}
        />
      )}
    </div>
  )
}
