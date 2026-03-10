import { useState, useEffect, useCallback } from 'react'
import { Loader2, RefreshCw, ArrowRightLeft, TrendingDown, AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, HelpCircle, X, Calendar, ArrowRight } from 'lucide-react'
import { fetchMatrixHealth } from '../api'

const PERIODS = [
  { key: '2026-01', label: 'January 2026' },
  { key: '2026-02', label: 'February 2026' },
  { key: 'current', label: 'This Month' },
]

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
      {/* Header */}
      <button onClick={onToggle} className="w-full text-left px-5 py-4 flex items-start gap-4">
        <div className="flex-shrink-0 mt-0.5">
          <ArrowRightLeft className="w-5 h-5 text-amber-400" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-white font-semibold">{zone}</span>
            {confidence === 'high' && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400 font-medium uppercase">High confidence</span>
            )}
            {csatWarning && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 font-medium uppercase flex items-center gap-1">
                <AlertTriangle className="w-3 h-3" /> Lower CSAT
              </span>
            )}
          </div>
          <p className="text-sm text-slate-400 mt-1.5 leading-relaxed">
            <span className="text-red-400 font-medium">{current_primary}</span> is the current primary garage but only accepts{' '}
            <span className="text-red-400 font-semibold">{current_accept_pct}%</span> of calls.{' '}
            <span className="text-emerald-400 font-medium">{suggested_primary}</span> accepts{' '}
            <span className="text-emerald-400 font-semibold">{suggested_accept_pct}%</span>{' '}
            — that's <span className="text-white font-semibold">+{improvePct}%</span> better.
          </p>
          <p className="text-xs text-slate-500 mt-1">
            Swapping would avoid ~<span className="text-brand-300 font-medium">{impact.cascades_avoided}</span> cascades
            and save ~<span className="text-brand-300 font-medium">{Math.round(impact.minutes_saved / 60)}</span> hours of member wait time per month.
          </p>
        </div>
        <div className="flex-shrink-0">
          {expanded ? <ChevronUp className="w-4 h-4 text-slate-500" /> : <ChevronDown className="w-4 h-4 text-slate-500" />}
        </div>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-5 pb-5 pt-0 border-t border-slate-800">
          {/* Current vs Suggested */}
          <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_1fr] gap-4 mt-4 items-center">
            {/* Current */}
            <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-4">
              <div className="text-[10px] text-red-400 uppercase tracking-wider font-semibold mb-2">Today — Current Primary</div>
              <div className="text-white font-semibold">{current_primary}</div>
              <div className="mt-2 space-y-1 text-sm">
                <div className="flex justify-between">
                  <span className="text-slate-500">Accept Rate</span>
                  {pctBadge(current_accept_pct, 75)}
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">CSAT Score</span>
                  {csatBadge(current_satisfaction)}
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Monthly Volume</span>
                  <span className="text-slate-300 font-medium">{impact.primary_volume.toLocaleString()} calls</span>
                </div>
              </div>
            </div>

            {/* Arrow */}
            <div className="hidden md:flex flex-col items-center gap-1">
              <ArrowRight className="w-6 h-6 text-amber-400" />
              <span className="text-[10px] text-amber-400 font-medium">SWAP</span>
            </div>

            {/* Suggested */}
            <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-4">
              <div className="text-[10px] text-emerald-400 uppercase tracking-wider font-semibold mb-2">Recommended — New Primary</div>
              <div className="text-white font-semibold">{suggested_primary}</div>
              <div className="mt-2 space-y-1 text-sm">
                <div className="flex justify-between">
                  <span className="text-slate-500">Accept Rate</span>
                  {pctBadge(suggested_accept_pct, 75)}
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">CSAT Score</span>
                  {csatBadge(suggested_satisfaction)}
                </div>
              </div>
            </div>
          </div>

          {/* Impact numbers */}
          <div className="mt-4 flex flex-wrap gap-3">
            {impactTag(impact.cascades_avoided, 'fewer cascades/mo', 'text-emerald-400')}
            {impactTag(Math.round(impact.minutes_saved / 60), 'hours saved/mo', 'text-brand-300')}
            {impactTag(impact.cnw_avoided, 'fewer CNW/mo', 'text-amber-400')}
          </div>

          {/* Action text */}
          <div className="mt-4 rounded-lg bg-slate-800/60 p-3 border border-slate-700/30">
            <div className="text-[10px] text-slate-400 uppercase tracking-wider font-semibold mb-1">Recommended Action</div>
            <p className="text-sm text-slate-300 leading-relaxed">
              In the <span className="text-white font-medium">Territory Priority Matrix</span> for zone{' '}
              <span className="text-white font-medium">{zone}</span>, move{' '}
              <span className="text-emerald-400 font-medium">{suggested_primary}</span> to the primary position (rank 2)
              and move <span className="text-red-400 font-medium">{current_primary}</span> down to a backup position.
              {csatWarning && (
                <span className="text-amber-400"> Note: {suggested_primary} has a lower customer satisfaction score
                  ({suggested_satisfaction}% vs {current_satisfaction}%) — verify service quality before making this change.</span>
              )}
              {!csatWarning && suggested_satisfaction != null && current_satisfaction != null && suggested_satisfaction >= current_satisfaction && (
                <span className="text-emerald-400"> {suggested_primary} also has equal or better customer satisfaction
                  ({suggested_satisfaction}% vs {current_satisfaction}%), further supporting this change.</span>
              )}
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

function ZoneHealthRow({ zone, expanded, onToggle }) {
  const { zone: name, primary_garage, primary_accept_pct, primary_volume,
    cascade_pct, chain } = zone

  const healthy = primary_accept_pct != null && primary_accept_pct >= 75
  return (
    <div className={`rounded-lg border ${healthy ? 'border-slate-800' : 'border-amber-500/20'} bg-slate-900/40 overflow-hidden`}>
      <button onClick={onToggle} className="w-full text-left px-4 py-3 flex items-center gap-3 text-sm">
        <div className={`w-2 h-2 rounded-full flex-shrink-0 ${healthy ? 'bg-emerald-500' : 'bg-amber-500'}`} />
        <span className="text-slate-300 font-medium flex-1 truncate">{name}</span>
        <span className="text-slate-500 text-xs hidden sm:inline">{primary_garage}</span>
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

function HowItWorks({ onClose }) {
  return (
    <div className="rounded-xl border border-slate-700/50 bg-slate-900/80 p-6 mb-6">
      <div className="flex items-start justify-between mb-4">
        <h3 className="text-white font-semibold">How Matrix Advisor Works</h3>
        <button onClick={onClose} className="text-slate-500 hover:text-white"><X className="w-4 h-4" /></button>
      </div>
      <div className="space-y-3 text-sm text-slate-400 leading-relaxed">
        <div>
          <span className="text-brand-300 font-semibold">Purpose:</span>{' '}
          The Territory Priority Matrix defines which garage handles calls first in each dispatch zone.
          When the primary garage declines, calls cascade to the next garage in the chain — adding ~8 minutes of member wait time per step.
          This page analyzes decline patterns and recommends where to re-order the matrix to reduce cascades.
        </div>
        <div>
          <span className="text-brand-300 font-semibold">What to look for:</span>{' '}
          Zones where the primary garage has a low accept rate (&lt;75%) but another garage in the same chain has a much higher
          accept rate. Swapping their positions in the matrix means more calls get accepted on the first try.
        </div>
        <div>
          <span className="text-brand-300 font-semibold">How recommendations work:</span>{' '}
          A swap is recommended when the primary garage accepts less than 75% of calls, and another garage in the chain
          accepts 10%+ more, with at least 10 calls to back it up. Customer satisfaction (CSAT) is shown as a safety check —
          if the suggested garage has worse satisfaction, you'll see a warning.
        </div>
        <div>
          <span className="text-brand-300 font-semibold">Decisions you can make:</span>{' '}
          Update the Territory Priority Matrix in Salesforce to swap the primary garage for flagged zones.
          Review each recommendation — check the accept rate improvement, time saved, and CSAT scores before acting.
          This should be reviewed monthly after each period closes.
        </div>
      </div>
    </div>
  )
}

export default function MatrixAdvisor() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [period, setPeriod] = useState('2026-02')
  const [expandedRec, setExpandedRec] = useState(null)
  const [expandedZone, setExpandedZone] = useState(null)
  const [showHelp, setShowHelp] = useState(false)
  const [showAllZones, setShowAllZones] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const d = await fetchMatrixHealth(period)
      setData(d)
      if (d.recommendations?.length > 0) setExpandedRec(0)
    } catch {
      setError('Failed to load matrix data. The first load may take 15-20 seconds.')
    } finally {
      setLoading(false)
    }
  }, [period])

  useEffect(() => { load() }, [load])

  const today = new Date().toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] gap-4">
        <Loader2 className="w-8 h-8 text-brand-400 animate-spin" />
        <p className="text-slate-500 text-sm">Loading matrix analysis... first load may take 15-20s</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] gap-4">
        <AlertTriangle className="w-8 h-8 text-red-400" />
        <p className="text-red-400 text-sm">{error}</p>
        <button onClick={load} className="text-brand-400 text-sm hover:underline">Retry</button>
      </div>
    )
  }

  const recs = data?.recommendations || []
  const zones = data?.zones || []
  const summary = data?.summary || {}
  const problemZones = zones.filter(z => z.primary_accept_pct != null && z.primary_accept_pct < 75)
  const healthyZones = zones.filter(z => z.primary_accept_pct == null || z.primary_accept_pct >= 75)
  const displayZones = showAllZones ? zones : problemZones.slice(0, 15)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <ArrowRightLeft className="w-6 h-6 text-brand-400" />
            Priority Matrix Insight
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Recommendations to optimize zone-to-garage assignments — reviewed {today}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={() => setShowHelp(!showHelp)}
            className="p-2 rounded-lg text-slate-500 hover:text-brand-400 hover:bg-slate-800 transition-all"
            title="How it works">
            <HelpCircle className="w-4 h-4" />
          </button>
          <div className="flex items-center gap-1.5 bg-slate-800/60 rounded-lg p-1">
            {PERIODS.map(p => (
              <button key={p.key} onClick={() => setPeriod(p.key)}
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                  period === p.key ? 'bg-brand-600/20 text-brand-300' : 'text-slate-500 hover:text-white'
                }`}>
                <Calendar className="w-3 h-3 inline mr-1 -mt-0.5" />{p.label}
              </button>
            ))}
          </div>
          <button onClick={load} className="p-2 rounded-lg text-slate-500 hover:text-white hover:bg-slate-800 transition-all">
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {showHelp && <HowItWorks onClose={() => setShowHelp(false)} />}

      {/* Summary bar */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {[
          { label: 'Zones Analyzed', value: summary.zones_analyzed, color: 'text-white' },
          { label: 'Total Calls', value: summary.total_calls?.toLocaleString(), color: 'text-white' },
          { label: 'Total Declined', value: summary.total_declined?.toLocaleString(), color: 'text-red-400' },
          { label: 'Problem Zones', value: problemZones.length, color: problemZones.length > 0 ? 'text-amber-400' : 'text-emerald-400' },
          { label: 'Recommendations', value: recs.length, color: recs.length > 0 ? 'text-brand-300' : 'text-slate-400' },
        ].map((s, i) => (
          <div key={i} className="rounded-lg bg-slate-900/60 border border-slate-800 px-4 py-3">
            <div className="text-[10px] text-slate-500 uppercase tracking-wider">{s.label}</div>
            <div className={`text-xl font-bold mt-1 ${s.color}`}>{s.value ?? '—'}</div>
          </div>
        ))}
      </div>

      {/* Recommendations */}
      <div>
        <h2 className="text-lg font-semibold text-white mb-3 flex items-center gap-2">
          <TrendingDown className="w-5 h-5 text-amber-400" />
          Recommended Matrix Adjustments
          <span className="text-xs text-slate-500 font-normal ml-2">
            {recs.length === 0 ? 'No adjustments needed this period' : `${recs.length} zone${recs.length > 1 ? 's' : ''} flagged`}
          </span>
        </h2>

        {recs.length === 0 ? (
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-8 text-center">
            <CheckCircle2 className="w-10 h-10 text-emerald-500 mx-auto mb-3" />
            <p className="text-slate-400">All zones are performing well — no matrix adjustments recommended for this period.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {recs.map((rec, i) => (
              <RecommendationCard
                key={i}
                rec={rec}
                expanded={expandedRec === i}
                onToggle={() => setExpandedRec(expandedRec === i ? null : i)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Zone Overview */}
      <div>
        <h2 className="text-lg font-semibold text-white mb-3 flex items-center gap-2">
          <AlertTriangle className="w-5 h-5 text-slate-500" />
          Zone Health Overview
          <span className="text-xs text-slate-500 font-normal ml-2">
            {problemZones.length} problem zone{problemZones.length !== 1 ? 's' : ''} • {healthyZones.length} healthy
          </span>
        </h2>

        {/* Column headers */}
        <div className="flex items-center gap-3 px-4 py-2 text-[10px] text-slate-600 uppercase tracking-wider">
          <span className="w-2" />
          <span className="flex-1">Zone</span>
          <span className="text-xs hidden sm:inline text-slate-600 flex-shrink-0">Primary Garage</span>
          <span className="w-14 text-right">Accept</span>
          <span className="w-14 text-right">Volume</span>
          <span className="w-10 text-right">Cascade</span>
          <span className="w-3.5" />
        </div>

        <div className="space-y-1.5">
          {displayZones.map((z, i) => (
            <ZoneHealthRow
              key={i}
              zone={z}
              expanded={expandedZone === i}
              onToggle={() => setExpandedZone(expandedZone === i ? null : i)}
            />
          ))}
        </div>

        {!showAllZones && zones.length > 15 && (
          <button onClick={() => setShowAllZones(true)}
            className="mt-3 text-sm text-brand-400 hover:text-brand-300 transition-colors">
            Show all {zones.length} zones →
          </button>
        )}
        {showAllZones && zones.length > 15 && (
          <button onClick={() => setShowAllZones(false)}
            className="mt-3 text-sm text-brand-400 hover:text-brand-300 transition-colors">
            Show problem zones only
          </button>
        )}
      </div>

      {/* Computed timestamp */}
      {data?.computed_at && (
        <p className="text-xs text-slate-600 text-right">
          Analysis computed {new Date(data.computed_at).toLocaleString()}
        </p>
      )}
    </div>
  )
}
