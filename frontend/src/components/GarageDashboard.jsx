import { useState, useEffect } from 'react'
import {
  ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, Legend, BarChart,
} from 'recharts'
import { clsx } from 'clsx'
import {
  TrendingDown, TrendingUp, CheckCircle2, XCircle, Clock, ThumbsUp,
  AlertTriangle, Target, Activity, Users, ArrowRight, ChevronLeft, ChevronRight,
  Calendar, Minus, Award, Truck, Loader2, ChevronRight as ChevronR, Zap,
} from 'lucide-react'
import { fetchPerformance, fetchScorecard, fetchScore, fetchDecomposition } from '../api'
import GaragePerformance from './GaragePerformance'

// ── Helpers ──────────────────────────────────────────────────────────────────

import { getWeek, getMonth } from '../utils/dateHelpers'
import { pct } from '../utils/formatting'
import { TT_STYLE } from '../constants/chartStyles'

// ── Small Components ─────────────────────────────────────────────────────────

function GradeRing({ grade, composite }) {
  const color = grade === 'A' ? 'text-emerald-400 border-emerald-500/40 bg-emerald-950/40'
    : grade === 'B' ? 'text-blue-400 border-blue-500/40 bg-blue-950/40'
    : grade === 'C' ? 'text-amber-400 border-amber-500/40 bg-amber-950/40'
    : 'text-red-400 border-red-500/40 bg-red-950/40'
  return (
    <div className={clsx('w-20 h-20 rounded-2xl flex flex-col items-center justify-center border-2', color)}>
      <div className="text-3xl font-black">{grade}</div>
      <div className="text-xs font-bold text-white/80">{composite}/100</div>
    </div>
  )
}

function MetricCard({ label, value, sub, color = 'text-white', icon: Icon, target, met, border, definition, defId, activeDef, setActiveDef }) {
  const showDef = activeDef === defId
  return (
    <div className={clsx('rounded-xl p-4 bg-slate-800/50 border relative', border || 'border-slate-700/30')}>
      <div className="flex items-center justify-between mb-1.5">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</div>
        <div className="flex items-center gap-1">
          {definition && (
            <button onClick={() => setActiveDef?.(showDef ? null : defId)}
              className="w-4 h-4 rounded-full bg-slate-700/60 hover:bg-slate-600 text-slate-400 hover:text-white text-[9px] font-bold flex items-center justify-center transition-colors"
              title="How this is calculated">?</button>
          )}
          {Icon && <Icon className="w-3.5 h-3.5 text-slate-600" />}
        </div>
      </div>
      {showDef && definition && (
        <div className="absolute top-0 left-0 right-0 z-10 bg-slate-800 border border-slate-600/50 rounded-xl p-3 shadow-xl whitespace-normal break-words overflow-hidden">
          <div className="flex items-center justify-between mb-1 gap-2">
            <span className="text-[10px] font-bold text-brand-400 uppercase truncate">{label}</span>
            <button onClick={() => setActiveDef?.(null)} className="text-slate-400 hover:text-white text-xs shrink-0">✕</button>
          </div>
          <div className="text-[11px] text-slate-300 leading-relaxed break-words">{definition}</div>
        </div>
      )}
      <div className={clsx('text-2xl font-black', color)}>{value}</div>
      {sub && <div className="text-[10px] text-slate-500 mt-0.5">{sub}</div>}
      {target && (
        <div className={clsx('text-[10px] mt-1 font-medium', met ? 'text-emerald-500' : 'text-red-400')}>
          {met ? 'On target' : `Target: ${target}`}
        </div>
      )}
    </div>
  )
}

function ProgressBar({ value, max = 100, color = 'bg-brand-500', height = 'h-2' }) {
  const w = Math.min(Math.max((value / max) * 100, 1), 100)
  return (
    <div className={clsx(height, 'bg-slate-900 rounded-full overflow-hidden')}>
      <div className={clsx('h-full rounded-full transition-all', color)} style={{ width: `${w}%` }} />
    </div>
  )
}

function BucketGrid({ buckets }) {
  const colors = ['bg-emerald-950/30 border-emerald-800/20', 'bg-amber-950/30 border-amber-800/20',
                  'bg-orange-950/30 border-orange-800/20', 'bg-red-950/30 border-red-800/20']
  const textColors = ['text-emerald-400', 'text-amber-400', 'text-orange-400', 'text-red-400']
  return (
    <div className="grid grid-cols-4 gap-2">
      {buckets.map((b, i) => (
        <div key={b.label} className={clsx('text-center rounded-xl p-2.5 border', colors[i])}>
          <div className={clsx('text-lg font-bold', textColors[i])}>{b.count}</div>
          <div className="text-[9px] text-slate-400 mt-0.5 leading-tight">{b.label}</div>
          <div className={clsx('text-[10px] font-medium', textColors[i])}>{b.pct}%</div>
        </div>
      ))}
    </div>
  )
}

function ReasonBars({ items, color = 'bg-red-500' }) {
  return (
    <div className="space-y-1.5">
      {items.map(r => (
        <div key={r.reason} className="flex items-center gap-2">
          <div className="flex-1 text-[11px] text-slate-300 truncate">{r.reason}</div>
          <div className="w-20 h-1.5 bg-slate-900 rounded-full overflow-hidden shrink-0">
            <div className={clsx('h-full rounded-full', color)} style={{ width: `${r.pct}%` }} />
          </div>
          <div className="text-[10px] text-slate-500 w-14 text-right shrink-0">{r.count} ({r.pct}%)</div>
        </div>
      ))}
    </div>
  )
}

// ── Supervisor Insights ──────────────────────────────────────────────────────

function buildInsights(perf) {
  const insights = []
  const actions  = []
  const { acceptance, completion, response_time: rt, pts_ata, satisfaction } = perf

  // Completion
  if (completion.pct < 80) {
    insights.push({ type: 'critical', text: `Only ${completion.pct}% completion — ${+(100 - completion.pct).toFixed(1)}% of calls lost to cancellations/no-shows.` })
    actions.push({ priority: 'HIGH', text: 'Investigate cancellation reasons. Member canceling (too slow) or facility declining?' })
  } else if (completion.pct < 92) {
    insights.push({ type: 'warn', text: `Completion rate ${completion.pct}% — below 95% target.` })
    actions.push({ priority: 'MED', text: 'Review "Could Not Wait" cancellations and facility declines.' })
  } else {
    insights.push({ type: 'good', text: `Strong completion: ${completion.pct}% of calls completed.` })
  }

  // Response time
  if (rt.median != null) {
    if (rt.median > 90) {
      insights.push({ type: 'critical', text: `Median response ${rt.median} min — ${rt.median - 45} min over 45-min target.` })
      actions.push({ priority: 'HIGH', text: `Close the ${rt.median - 45}-min gap: closest-driver dispatch + reduce queue wait.` })
    } else if (rt.median > 45) {
      insights.push({ type: 'warn', text: `Median response ${rt.median} min — ${rt.median - 45} min over target. ${rt.under_45_pct}% under 45 min.` })
      actions.push({ priority: 'HIGH', text: `Need ${+(100 - rt.under_45_pct).toFixed(1)}% more calls under 45 min. Focus on dispatch queue time.` })
    } else {
      insights.push({ type: 'good', text: `Median response ${rt.median} min — meeting 45-min target.` })
    }
    if (rt.over_120 > 0) {
      insights.push({ type: 'warn', text: `${rt.over_120} calls (${rt.over_120_pct}%) took over 2 hours — highest cancellation risk.` })
    }
  }

  // PTA accuracy (promised vs actual arrival)
  if (pts_ata && pts_ata.on_time_pct != null) {
    if (pts_ata.late_pct > 50) {
      insights.push({ type: 'critical', text: `${pts_ata.late_pct}% of calls arrived late vs. promised ETA (avg ${pts_ata.avg_delta > 0 ? '+' : ''}${pts_ata.avg_delta} min).` })
      actions.push({ priority: 'HIGH', text: 'Dispatch promising unrealistic ETAs. Review PTA values at dispatch time.' })
    } else if (pts_ata.late_pct > 25) {
      insights.push({ type: 'warn', text: `${pts_ata.late_pct}% late vs. promise (avg ${pts_ata.avg_delta > 0 ? '+' : ''}${pts_ata.avg_delta} min).` })
    } else {
      insights.push({ type: 'good', text: `${pts_ata.on_time_pct}% on time or early — strong ETA accuracy.` })
    }
  }

  // Acceptance
  if (acceptance.primary_total > 0 && acceptance.primary_pct < 70) {
    insights.push({ type: 'critical', text: `Only ${acceptance.primary_pct}% primary acceptance — declining ${+(100 - acceptance.primary_pct).toFixed(1)}% of auto-dispatched work.` })
    actions.push({ priority: 'HIGH', text: 'Identify top decline reasons. Driver availability? Truck mismatch?' })
  }

  // Satisfaction
  if (satisfaction) {
    if (satisfaction.total_satisfied_pct < 70) {
      insights.push({ type: 'critical', text: `Satisfaction ${satisfaction.total_satisfied_pct}% — well below 82% accreditation.` })
      actions.push({ priority: 'HIGH', text: `Read comments from ${satisfaction.dissatisfied + satisfaction.totally_dissatisfied} dissatisfied members.` })
    } else if (satisfaction.total_satisfied_pct < 82) {
      insights.push({ type: 'warn', text: `Satisfaction ${satisfaction.total_satisfied_pct}% — ${82 - satisfaction.total_satisfied_pct}% below accreditation.` })
    } else {
      insights.push({ type: 'good', text: `Satisfaction ${satisfaction.total_satisfied_pct}% — meeting 82% target.` })
    }
  }

  // Path to 45
  if (rt.median != null && rt.median > 45) {
    actions.push({
      priority: 'GOAL',
      text: `PATH TO 45-MIN: Median is ${rt.median} min. Close the ${rt.median - 45}-min gap → dispatch closest driver first, reduce queue wait, ensure driver en route within 5 min of assignment.`,
    })
  }
  if (!insights.some(i => i.type !== 'good')) {
    actions.push({ priority: 'MAINTAIN', text: 'All metrics on target. Continue monitoring daily.' })
  }

  return { insights, actions }
}

// ── Period Selector ──────────────────────────────────────────────────────────

const PERIODS = ['Daily', 'Weekly', 'Monthly']

function PeriodSelector({ periodType, setPeriodType, dayDate, setDayDate, weekOffset, setWeekOffset, monthOffset, setMonthOffset, loading, week, month }) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="flex gap-1 p-1 bg-slate-900 rounded-xl">
        {PERIODS.map(pt => (
          <button key={pt} onClick={() => setPeriodType(pt)}
            className={clsx('px-3 py-1.5 rounded-lg text-xs font-semibold transition-all',
              periodType === pt ? 'bg-brand-600 text-white' : 'text-slate-400 hover:text-white hover:bg-slate-800')}>
            {pt}
          </button>
        ))}
      </div>

      {periodType === 'Daily' && (
        <input type="date" value={dayDate} onChange={e => setDayDate(e.target.value)}
          className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/40" />
      )}

      {periodType === 'Weekly' && (
        <div className="flex items-center gap-2">
          <button onClick={() => setWeekOffset(w => w - 1)} className="p-1.5 rounded-lg hover:bg-slate-800">
            <ChevronLeft className="w-4 h-4 text-slate-400" />
          </button>
          <div className="text-sm font-semibold text-white min-w-[180px] text-center">
            {weekOffset === 0 ? 'This Week' : weekOffset === -1 ? 'Last Week' : `Week of ${week.start}`}
            <div className="text-[10px] text-slate-400 font-normal">{week.label}</div>
          </div>
          <button onClick={() => setWeekOffset(w => w + 1)} className="p-1.5 rounded-lg hover:bg-slate-800">
            <ChevronRight className="w-4 h-4 text-slate-400" />
          </button>
          <button onClick={() => setWeekOffset(0)} className="ml-1 px-2 py-1 text-[10px] bg-slate-800 text-slate-400 hover:text-white rounded-lg">
            This Week
          </button>
        </div>
      )}

      {periodType === 'Monthly' && (
        <div className="flex items-center gap-2">
          <button onClick={() => setMonthOffset(m => m - 1)} className="p-1.5 rounded-lg hover:bg-slate-800">
            <ChevronLeft className="w-4 h-4 text-slate-400" />
          </button>
          <div className="text-sm font-semibold text-white min-w-[160px] text-center">{month.label}</div>
          <button onClick={() => setMonthOffset(m => m + 1)} className="p-1.5 rounded-lg hover:bg-slate-800">
            <ChevronRight className="w-4 h-4 text-slate-400" />
          </button>
          <button onClick={() => setMonthOffset(0)} className="ml-1 px-2 py-1 text-[10px] bg-slate-800 text-slate-400 hover:text-white rounded-lg">
            This Month
          </button>
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-1.5 text-[10px] text-slate-400 ml-2">
          <div className="w-3 h-3 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
          Loading...
        </div>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════════════════════

export default function GarageDashboard({ garageId, garageName }) {
  // ── Shared date range (used by all tabs)
  // Default to last 30 days so there's always data
  const today = new Date()
  const thirtyDaysAgo = new Date(today)
  thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30)
  const [startDate, setStartDate] = useState(thirtyDaysAgo.toISOString().slice(0, 10))
  const [endDate, setEndDate] = useState(today.toISOString().slice(0, 10))

  // Legacy period compat — Overview endpoints use start/end
  const start = startDate
  const end = endDate

  // ── Data state
  const [perf, setPerf]           = useState(null)
  const [scorecard, setScorecard] = useState(null)
  const [score, setScore]         = useState(null)
  const [decomp, setDecomp]       = useState(null)
  const [loading, setLoading]     = useState({ perf: false, scorecard: false, score: false, decomp: false })
  const [error, setError]         = useState(null)
  const [decompError, setDecompError] = useState(null)
  const [scorecardError, setScorecardError] = useState(null)
  const [scoreError, setScoreError] = useState(null)
  const [activeDef, setActiveDef] = useState(null)  // which metric tooltip is open
  const [activeTab, setActiveTab] = useState('performance')  // performance | overview

  // ── Load performance (period-dependent)
  useEffect(() => {
    let ignore = false
    setLoading(p => ({ ...p, perf: true }))
    setError(null)
    setPerf(null)
    fetchPerformance(garageId, start, end)
      .then(d => { if (!ignore) setPerf(d) })
      .catch(e => { if (!ignore) setError(e.response?.data?.detail || e.message) })
      .finally(() => { if (!ignore) setLoading(p => ({ ...p, perf: false })) })
    return () => { ignore = true }
  }, [garageId, start, end])

  // ── Load decomposition (period-dependent)
  useEffect(() => {
    let ignore = false
    setLoading(p => ({ ...p, decomp: true }))
    setDecomp(null)
    setDecompError(null)
    fetchDecomposition(garageId, start, end)
      .then(d => { if (!ignore) setDecomp(d) })
      .catch(e => { if (!ignore) { console.error('Decomposition fetch failed:', e); setDecompError(e.response?.data?.detail || e.message || 'Failed to load') } })
      .finally(() => { if (!ignore) setLoading(p => ({ ...p, decomp: false })) })
    return () => { ignore = true }
  }, [garageId, start, end])

  // ── Load scorecard + score (once, not period-dependent)
  useEffect(() => {
    setLoading(p => ({ ...p, scorecard: true, score: true }))
    fetchScorecard(garageId).then(setScorecard).catch(e => { console.error('Scorecard fetch failed:', e); setScorecardError(e.response?.data?.detail || e.message || 'Failed to load') }).finally(() => setLoading(p => ({ ...p, scorecard: false })))
    fetchScore(garageId).then(setScore).catch(e => { console.error('Score fetch failed:', e); setScoreError(e.response?.data?.detail || e.message || 'Failed to load') }).finally(() => setLoading(p => ({ ...p, score: false })))
  }, [garageId])

  const { insights, actions } = perf ? buildInsights(perf) : { insights: [], actions: [] }
  const rd = decomp?.response_decomposition
  const leaderboard = decomp?.driver_leaderboard || []
  const missingTruckIdCount = decomp?.missing_truck_id_count || 0
  const declines = decomp?.decline_analysis
  const cancels = decomp?.cancel_analysis
  const garageType = decomp?.garage_type || scorecard?.garage_type || 'fleet'
  const isTowbook = garageType === 'towbook'
  const isFleet = garageType === 'fleet'
  const isContractor = garageType !== 'fleet'  // Towbook OR on-platform contractor

  const anyLoading = loading.perf || loading.scorecard || loading.score || loading.decomp
  const isFullLoading = loading.perf && !perf

  return (
    <div className="space-y-5">

      {/* ═══ DATE RANGE + TAB BAR ════════════════════════════════════════════ */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex gap-1 bg-slate-900/50 rounded-lg p-1">
          {[['performance', 'Performance'], ['operations', 'Operations']].map(([key, label]) => (
            <button key={key}
              onClick={() => setActiveTab(key)}
              className={clsx('px-4 py-1.5 rounded-md text-xs font-semibold transition',
                activeTab === key ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white hover:bg-slate-800/50')}>
              {label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)}
            className="bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-blue-500/50 [color-scheme:dark]" />
          <span className="text-slate-600 text-xs">to</span>
          <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)}
            className="bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-blue-500/50 [color-scheme:dark]" />
        </div>
      </div>

      {/* ═══ PERFORMANCE TAB ══════════════════════════════════════════════════ */}
      {activeTab === 'performance' && (
        <GaragePerformance garageId={garageId} garageName={garageName} startDate={startDate} endDate={endDate} />
      )}

      {/* ═══ OPERATIONS TAB ═════════════════════════════════════════════════ */}
      {activeTab === 'operations' && (<>

      {/* Grade badge + dispatch type */}
      <div className="glass rounded-xl p-4 flex items-center gap-4 flex-wrap">
          {score && !score.error && (
            <GradeRing grade={score.grade} composite={score.composite} />
          )}

          {/* Dispatch method badge */}
          {perf?.dispatch_mix && (
            <div className="flex flex-col items-center gap-1">
              <div className={clsx('px-3 py-1.5 rounded-lg text-xs font-bold border',
                isFleet
                  ? 'bg-blue-950/40 border-blue-700/40 text-blue-400'
                  : isTowbook
                    ? 'bg-amber-950/40 border-amber-700/40 text-amber-400'
                    : 'bg-purple-950/40 border-purple-700/40 text-purple-400')}>
                {isFleet ? 'Fleet' : isTowbook ? 'Contractor · Towbook' : 'Contractor · On-Platform'}
              </div>
              <div className="text-[9px] text-slate-500 text-center leading-tight">
                {isTowbook
                  ? `${perf.dispatch_mix.tb_pct}% Towbook`
                  : `${perf.dispatch_mix.fs_pct}% Field Services · ${perf.dispatch_mix.tb_pct}% Towbook`}
              </div>
            </div>
          )}

          {/* Score dimensions mini */}
          {score && score.dimensions && (
            <div className="flex-1 min-w-0">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                {Object.entries(score.dimensions)
                  .filter(([key]) => key !== 'satisfaction')
                  .slice(0, 4).map(([key, dim]) => (
                  <div key={key} className="flex items-center gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="text-[9px] text-slate-500 uppercase tracking-wider truncate">{dim.label}</div>
                      <div className="flex items-baseline gap-1">
                        <span className={clsx('text-sm font-bold',
                          dim.score >= 80 ? 'text-emerald-400' : dim.score >= 60 ? 'text-amber-400' : dim.score != null ? 'text-red-400' : 'text-slate-600')}>
                          {dim.actual_display}
                        </span>
                      </div>
                      <ProgressBar value={dim.score || 0}
                        color={dim.score >= 80 ? 'bg-emerald-500' : dim.score >= 60 ? 'bg-amber-500' : 'bg-red-500'}
                        height="h-1" />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
      </div>

      {error && (
        <div className="rounded-xl bg-red-950/30 border border-red-800/30 p-4 text-red-300 text-sm">{error}</div>
      )}

      {isFullLoading && (
        <div className="space-y-4 animate-pulse">
          {/* Skeleton KPI cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[...Array(8)].map((_, i) => (
              <div key={i} className="glass rounded-xl p-4 space-y-3">
                <div className="flex items-center gap-2">
                  <div className="w-8 h-8 rounded-lg bg-slate-700/50" />
                  <div className="h-3 w-20 rounded bg-slate-700/50" />
                </div>
                <div className="h-7 w-16 rounded bg-slate-700/50" />
                <div className="h-2 w-24 rounded bg-slate-700/50" />
              </div>
            ))}
          </div>
          {/* Skeleton chart */}
          <div className="glass rounded-xl p-5 space-y-3">
            <div className="h-4 w-40 rounded bg-slate-700/50" />
            <div className="h-48 rounded bg-slate-700/30" />
          </div>
          {/* Loading indicator */}
          <div className="flex items-center justify-center py-4 gap-3">
            <Loader2 className="w-5 h-5 animate-spin text-brand-400" />
            <span className="text-slate-400 text-sm">Loading garage data from Salesforce...</span>
          </div>
        </div>
      )}

      {perf && (
        <>
          {/* ═══ KPI STRIP ═══════════════════════════════════════════════════════ */}
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-4 gap-3">
            <MetricCard label="Total Calls" value={perf.total_sas.toLocaleString()} icon={Activity}
              sub={`${perf.completed} completed`}
              definition={perf.definitions?.total_calls} defId="total_calls" activeDef={activeDef} setActiveDef={setActiveDef} />
            <MetricCard label="Completion" value={`${perf.completion.pct}%`} icon={CheckCircle2}
              sub={`${perf.completion.completed} / ${perf.completion.total}`}
              color={perf.completion.pct >= 95 ? 'text-emerald-400' : perf.completion.pct >= 80 ? 'text-amber-400' : 'text-red-400'}
              border={perf.completion.pct >= 95 ? 'border-emerald-800/30' : perf.completion.pct >= 80 ? 'border-amber-800/30' : 'border-red-800/30'}
              target="95%" met={perf.completion.pct >= 95}
              definition={perf.definitions?.completion} defId="completion" activeDef={activeDef} setActiveDef={setActiveDef} />
            <MetricCard label="1st Call Acceptance"
              value={perf.first_call?.first_call_pct != null ? `${perf.first_call.first_call_pct}%` : 'N/A'} icon={Zap}
              sub={perf.first_call?.first_call_total > 0 ? `${perf.first_call.first_call_accepted} / ${perf.first_call.first_call_total} 1st calls` : 'No data'}
              color={perf.first_call?.first_call_pct >= 90 ? 'text-emerald-400' : perf.first_call?.first_call_pct >= 75 ? 'text-amber-400' : perf.first_call?.first_call_pct != null ? 'text-red-400' : 'text-slate-500'}
              border={perf.first_call?.first_call_pct >= 90 ? 'border-emerald-800/30' : 'border-amber-800/30'}
              definition={perf.definitions?.first_call_acceptance} defId="first_call" activeDef={activeDef} setActiveDef={setActiveDef} />
            <MetricCard label="2nd+ Call Acceptance"
              value={perf.first_call?.second_call_pct != null ? `${perf.first_call.second_call_pct}%` : 'N/A'} icon={Zap}
              sub={perf.first_call?.second_call_total > 0 ? `${perf.first_call.second_call_accepted} / ${perf.first_call.second_call_total} reassigned` : 'No reassigned calls'}
              color={perf.first_call?.second_call_pct >= 90 ? 'text-emerald-400' : perf.first_call?.second_call_pct >= 75 ? 'text-amber-400' : perf.first_call?.second_call_pct != null ? 'text-red-400' : 'text-slate-500'}
              border={perf.first_call?.second_call_pct >= 90 ? 'border-emerald-800/30' : 'border-amber-800/30'}
              definition="When this garage was NOT the first territory assigned (SA was reassigned from another garage), what % did they accept? Lower numbers here are expected since these are overflow/backup calls." defId="second_call" activeDef={activeDef} setActiveDef={setActiveDef} />
            <MetricCard label="Completion of Accepted" value={perf.first_call?.accepted_completion_pct != null ? `${perf.first_call.accepted_completion_pct}%` : 'N/A'} icon={CheckCircle2}
              sub={perf.first_call?.accepted_total > 0 ? `${perf.first_call.accepted_completed} / ${perf.first_call.accepted_total} accepted` : ''}
              color={perf.first_call?.accepted_completion_pct >= 95 ? 'text-emerald-400' : perf.first_call?.accepted_completion_pct >= 80 ? 'text-amber-400' : perf.first_call?.accepted_completion_pct != null ? 'text-red-400' : 'text-slate-500'}
              border={perf.first_call?.accepted_completion_pct >= 95 ? 'border-emerald-800/30' : 'border-amber-800/30'}
              definition={perf.definitions?.completion_of_accepted} defId="completion_accepted" activeDef={activeDef} setActiveDef={setActiveDef} />
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-4 gap-3">
            <MetricCard label={perf.response_time.metric === 'PTA (promised)' ? 'Median PTA' : 'Median Response'} value={perf.response_time.median ? `${perf.response_time.median} min` : 'N/A'} icon={Clock}
              sub={perf.response_time.total > 0 ? `${perf.response_time.under_45_pct}% under 45 min${perf.response_time.metric === 'PTA (promised)' ? ' · PTA' : ''}` : 'No arrival data this period'}
              color={perf.response_time.median && perf.response_time.median <= 45 ? 'text-emerald-400' : perf.response_time.median && perf.response_time.median <= 70 ? 'text-amber-400' : !perf.response_time.median ? 'text-slate-500' : 'text-red-400'}
              border={perf.response_time.median && perf.response_time.median <= 45 ? 'border-emerald-800/30' : !perf.response_time.median ? 'border-slate-700/30' : 'border-red-800/30'}
              target="45 min" met={perf.response_time.median && perf.response_time.median <= 45}
              definition={perf.definitions?.median_response} defId="median_response" activeDef={activeDef} setActiveDef={setActiveDef} />
            <MetricCard
              label="ETA Accuracy"
              value={perf.pts_ata?.on_time_pct != null ? `${perf.pts_ata.on_time_pct}%` : 'N/A'}
              icon={Target}
              sub={perf.pts_ata?.on_time_pct != null ? `avg ${perf.pts_ata.avg_delta > 0 ? '+' : ''}${perf.pts_ata.avg_delta} min vs promise` : perf.response_time.total === 0 ? 'No arrival data this period' : ''}
              color={perf.pts_ata?.on_time_pct >= 70 ? 'text-emerald-400' : perf.pts_ata?.on_time_pct != null ? 'text-red-400' : 'text-slate-500'}
              border={perf.pts_ata?.on_time_pct >= 70 ? 'border-emerald-800/30' : 'border-slate-700/30'}
              definition={perf.definitions?.eta_accuracy} defId="eta_accuracy" activeDef={activeDef} setActiveDef={setActiveDef} />
          </div>

          {/* ═══ RESPONSE TIME (left) + DECOMPOSITION (right) ═════════════════ */}
          {perf.response_time.total === 0 ? (
            <div className="glass rounded-xl p-6 text-center">
              <Clock className="w-8 h-8 text-slate-600 mx-auto mb-2" />
              <div className="text-sm font-semibold text-slate-400">Response Time Data Unavailable</div>
              <div className="text-xs text-slate-500 mt-1 max-w-md mx-auto">
                No completed SAs with arrival timestamps found for this period.
                Completion rate, volume, acceptance, and satisfaction metrics are still available above.
              </div>
            </div>
          ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

            {/* Response Time Buckets */}
            <div className="glass rounded-xl p-5 space-y-3">
              <h3 className="font-semibold text-slate-200 flex items-center gap-2 text-sm">
                <Clock className="w-4 h-4 text-brand-400" /> {perf.response_time.metric === 'PTA (promised)' ? 'PTA Breakdown (Towbook)' : 'Response Time Breakdown'}
              </h3>
              <BucketGrid buckets={[
                { label: '< 45 min', count: perf.response_time.under_45, pct: perf.response_time.under_45_pct },
                { label: '45–90 min', count: perf.response_time.b45_90, pct: perf.response_time.b45_90_pct },
                { label: '90–120 min', count: perf.response_time.b90_120, pct: perf.response_time.b90_120_pct },
                { label: '> 2 hours', count: perf.response_time.over_120, pct: perf.response_time.over_120_pct },
              ]} />

              {/* 45-min progress bar */}
              <div className="pt-3 border-t border-slate-800/60">
                <div className="flex justify-between text-[10px] text-slate-400 mb-1.5">
                  <span>Progress to 45-Min Goal</span>
                  <span className={perf.response_time.median && perf.response_time.median <= 45 ? 'text-emerald-400 font-bold' : 'text-red-400 font-bold'}>
                    Median: {perf.response_time.median ?? '?'} min
                  </span>
                </div>
                <ProgressBar value={perf.response_time.under_45_pct}
                  color={perf.response_time.under_45_pct >= 80 ? 'bg-emerald-500' : perf.response_time.under_45_pct >= 50 ? 'bg-amber-500' : 'bg-red-500'}
                  height="h-2.5" />
                <div className="flex justify-between text-[9px] text-slate-600 mt-1">
                  <span>0%</span>
                  <span className="text-brand-400">Target: 80%+ under 45 min</span>
                  <span>100%</span>
                </div>
              </div>

              {/* PTA accuracy — Fleet: Promise vs Actual; Towbook: PTA distribution */}
              {perf.pts_ata && perf.pts_ata.on_time_pct != null && (
                <div className="pt-3 border-t border-slate-800/60">
                  <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">Promise vs Actual</div>
                  <div className="flex gap-3">
                    <div className="flex-1 text-center bg-emerald-950/20 border border-emerald-800/20 rounded-lg p-2">
                      <div className="text-lg font-bold text-emerald-400">{perf.pts_ata.on_time_pct}%</div>
                      <div className="text-[9px] text-slate-400">On Time</div>
                    </div>
                    <div className="flex-1 text-center bg-red-950/20 border border-red-800/20 rounded-lg p-2">
                      <div className="text-lg font-bold text-red-400">{perf.pts_ata.late_pct}%</div>
                      <div className="text-[9px] text-slate-400">Late</div>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Response Time Decomposition Waterfall */}
            <div className="glass rounded-xl p-5 space-y-3">
              <h3 className="font-semibold text-slate-200 flex items-center gap-2 text-sm">
                <Activity className="w-4 h-4 text-brand-400" /> Where Time Is Spent
                {loading.decomp && <Loader2 className="w-3.5 h-3.5 animate-spin text-slate-500 ml-1" />}
              </h3>

              {rd ? (
                <>
                  {/* Two-bar waterfall: Wait + On-Site */}
                  {(() => {
                    const waitAvg = (rd.avg_dispatch_min || 0) + (rd.avg_travel_min || 0)
                    const waitMed = (rd.median_dispatch_min || 0) + (rd.median_travel_min || 0)
                    const onsiteAvg = rd.avg_onsite_min || 0
                    const onsiteMed = rd.median_onsite_min || 0
                    const totalAvg = waitAvg + onsiteAvg
                    const segments = [
                      { label: 'Member Wait', sub: 'Created → Driver Arrives', value: waitAvg, median: waitMed, color: 'bg-red-500' },
                      { label: 'On-Site Service', sub: 'Driver Arrives → Job Done', value: onsiteAvg, median: onsiteMed, color: 'bg-emerald-500' },
                    ]
                    const maxVal = Math.max(waitAvg, onsiteAvg, 1)
                    return (
                      <>
                        <div className="flex items-end gap-4 h-36 px-8">
                          {segments.map(seg => {
                            const h = Math.max((seg.value / maxVal) * 100, 10)
                            return (
                              <div key={seg.label} className="flex-1 flex flex-col items-center">
                                <div className="text-lg font-black text-white mb-1">{seg.value}<span className="text-[10px] font-normal text-slate-500"> min avg</span></div>
                                <div className="text-[10px] text-slate-500 mb-1">median {seg.median} min</div>
                                <div className={clsx('w-full rounded-t-lg transition-all', seg.color)}
                                  style={{ height: `${h}%` }} />
                                <div className="text-[11px] text-slate-300 mt-2 font-medium text-center">{seg.label}</div>
                                <div className="text-[9px] text-slate-500 text-center">{seg.sub}</div>
                              </div>
                            )
                          })}
                        </div>
                        {/* Total bar */}
                        <div className="bg-slate-800/50 rounded-lg p-3 flex items-center gap-3">
                          <span className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">Total Avg</span>
                          <div className="flex-1 h-4 rounded-full overflow-hidden flex">
                            <div className="bg-red-500 h-full" style={{ width: `${pct(waitAvg, totalAvg)}%` }} />
                            <div className="bg-emerald-500 h-full" style={{ width: `${pct(onsiteAvg, totalAvg)}%` }} />
                          </div>
                          <span className="text-sm font-bold text-white">{totalAvg} min</span>
                        </div>
                        <div className="text-[10px] text-slate-600 text-center">
                          Based on {rd.sample_size.toLocaleString()} completed calls (all dispatch methods)
                        </div>
                      </>
                    )
                  })()}

                  {/* By work type mini table */}
                  {Object.keys(rd.by_work_type).length > 0 && (
                    <div className="pt-3 border-t border-slate-800/60">
                      <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">By Work Type</div>
                      <div className="space-y-1">
                        {Object.entries(rd.by_work_type).sort((a, b) => b[1].count - a[1].count).map(([wt, d]) => {
                          const wait = (d.dispatch || 0) + (d.travel || 0)
                          return (
                            <div key={wt} className="flex items-center gap-2 text-[11px]">
                              <span className="w-28 text-slate-300 font-medium truncate">{wt}</span>
                              <div className="flex-1 flex h-3 rounded-full overflow-hidden">
                                <div className="bg-red-500/80 rounded-l" style={{ width: `${pct(wait, d.total)}%` }} />
                                <div className="bg-emerald-500/80 rounded-r" style={{ width: `${pct(d.onsite, d.total)}%` }} />
                              </div>
                              <span className="text-slate-400 w-16 text-right">{d.total} min</span>
                              <span className="text-slate-600 w-10 text-right">({d.count})</span>
                            </div>
                          )
                        })}
                      </div>
                      <div className="flex gap-4 mt-2 text-[9px] text-slate-500">
                        <span><span className="inline-block w-2 h-2 rounded-sm bg-red-500 mr-1" />Member Wait</span>
                        <span><span className="inline-block w-2 h-2 rounded-sm bg-emerald-500 mr-1" />On-Site</span>
                      </div>
                    </div>
                  )}
                </>
              ) : !loading.decomp ? (
                <div className="text-sm py-8 text-center">
                  {decompError
                    ? <span className="text-red-400">Decomposition unavailable: {decompError}</span>
                    : <span className="text-slate-500">No decomposition data available</span>}
                </div>
              ) : null}
            </div>
          </div>
          )}

          {/* ═══ TREND CHART + FLEET ══════════════════════════════════════════ */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

            {/* Volume trend (2/3 width) */}
            {perf.trend && perf.trend.length > 0 && (
              <div className="glass rounded-xl p-5 lg:col-span-2">
                <h3 className="font-semibold text-slate-200 mb-3 flex items-center gap-2 text-sm">
                  <Activity className="w-4 h-4 text-brand-400" />
                  Volume & Completion Trend
                  <span className="ml-auto text-[10px] text-slate-500 font-normal">
                    {perf.period.single_day ? 'Hourly' : 'Daily'}
                  </span>
                </h3>
                <div className="h-48">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={perf.trend} margin={{ left: -10, right: 10 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                      <XAxis dataKey="label" stroke="#475569" tick={{ fontSize: 10, fill: '#94a3b8' }}
                        interval={perf.trend.length > 14 ? Math.floor(perf.trend.length / 10) : 0} />
                      <YAxis yAxisId="vol" stroke="#475569" tick={{ fontSize: 10, fill: '#94a3b8' }} />
                      <YAxis yAxisId="pct" orientation="right" domain={[0, 100]}
                        stroke="#475569" tick={{ fontSize: 10, fill: '#94a3b8' }} tickFormatter={v => `${v}%`} />
                      <Tooltip {...TT_STYLE} formatter={(val, name) => name === 'Completion %' ? `${val}%` : val} />
                      <Legend wrapperStyle={{ fontSize: 10, color: '#94a3b8' }} />
                      <Bar yAxisId="vol" dataKey="total" name="Total SAs" fill="#6366f1" radius={[3,3,0,0]} opacity={0.7} />
                      <Bar yAxisId="vol" dataKey="completed" name="Completed" fill="#10b981" radius={[3,3,0,0]} opacity={0.8} />
                      <Line yAxisId="pct" type="monotone" dataKey="completion_pct" name="Completion %"
                        stroke="#f59e0b" strokeWidth={2} dot={{ fill: '#f59e0b', r: 2 }} />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}

            {/* Fleet + Volume (1/3 width) */}
            {!scorecard && scorecardError && !loading.scorecard && (
              <div className="glass rounded-xl p-5 flex items-center justify-center">
                <span className="text-sm text-red-400">Scorecard unavailable: {scorecardError}</span>
              </div>
            )}
            {scorecard && (
              <div className="glass rounded-xl p-5 space-y-4">
                <h3 className="font-semibold text-slate-200 flex items-center gap-2 text-sm">
                  <Truck className="w-4 h-4 text-brand-400" />
                  {isFleet ? 'Fleet & Volume' : 'Contractors & Volume'}
                  {isContractor && <span className={clsx('text-[10px] px-1.5 py-0.5 rounded font-medium', isTowbook ? 'bg-amber-600/20 text-amber-400' : 'bg-purple-600/20 text-purple-400')}>{isTowbook ? 'TOWBOOK' : 'ON-PLATFORM'}</span>}
                </h3>
                <div className="grid grid-cols-2 gap-2">
                  <div className="bg-slate-800/50 rounded-lg p-3 text-center">
                    <div className="text-2xl font-bold text-white">{scorecard.fleet.total_trucks || 0}</div>
                    <div className="text-[10px] text-slate-400">Trucks</div>
                  </div>
                  <div className="bg-slate-800/50 rounded-lg p-3 text-center">
                    <div className="text-2xl font-bold text-slate-300">
                      {isTowbook ? (scorecard.fleet.total_contractors || scorecard.fleet.total_trucks || 0) : scorecard.fleet.total_members}
                    </div>
                    <div className="text-[10px] text-slate-400">{isTowbook ? 'Contractors' : 'Drivers'}</div>
                  </div>
                  <div className="bg-red-950/20 rounded-lg p-2 text-center border border-red-800/20">
                    <div className="text-lg font-bold text-red-400">{scorecard.fleet.tow_trucks || 0}</div>
                    <div className="text-[9px] text-slate-400">Tow</div>
                  </div>
                  <div className="bg-blue-950/20 rounded-lg p-2 text-center border border-blue-800/20">
                    <div className="text-lg font-bold text-blue-400">{scorecard.fleet.other_trucks || 0}</div>
                    <div className="text-[9px] text-slate-400">Batt/Light</div>
                  </div>
                </div>

                {/* Volume by type */}
                <div className="space-y-1.5">
                  {[
                    { label: 'Tow', count: scorecard.volume.tow_sas, color: 'bg-red-500' },
                    { label: 'Battery', count: scorecard.volume.battery_sas, color: 'bg-blue-500' },
                    { label: 'Light', count: scorecard.volume.light_sas, color: 'bg-teal-500' },
                  ].map(t => {
                    const p = scorecard.volume.total > 0 ? Math.round(100 * t.count / scorecard.volume.total) : 0
                    return (
                      <div key={t.label} className="flex items-center gap-2">
                        <div className="w-14 text-[10px] text-slate-400 text-right">{t.label}</div>
                        <div className="flex-1 h-3 bg-slate-900 rounded-full overflow-hidden">
                          <div className={clsx('h-full rounded-full', t.color)} style={{ width: `${Math.max(p, 1)}%` }} />
                        </div>
                        <div className="w-16 text-[10px] text-slate-400">{t.count.toLocaleString()} ({p}%)</div>
                      </div>
                    )
                  })}
                </div>

                {/* DOW chart */}
                <div>
                  <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Avg Weekly Demand</div>
                  <div className="h-24">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map(d => ({ day: d, count: scorecard.volume.by_dow?.[d] || 0 }))}>
                        <XAxis dataKey="day" stroke="#475569" tick={{ fontSize: 9, fill: '#94a3b8' }} />
                        <YAxis stroke="#475569" tick={{ fontSize: 9, fill: '#94a3b8' }} />
                        <Tooltip {...TT_STYLE} />
                        <Bar dataKey="count" fill="#6366f1" radius={[3,3,0,0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* ═══ DRIVER LEADERBOARD + DECLINE/CANCEL ══════════════════════════ */}
          {(leaderboard.length > 0 || declines?.total_declines > 0 || cancels?.total_cancellations > 0) && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

              {/* Leaderboard (2/3) */}
              {leaderboard.length > 0 && (
                <div className="glass rounded-xl p-5 lg:col-span-2">
                  <h3 className="font-semibold text-slate-200 flex items-center gap-2 text-sm mb-3">
                    <Award className="w-4 h-4 text-amber-400" />
                    {isFleet ? 'Driver Leaderboard' : 'Contractor Leaderboard'}
                    {isContractor && <span className={clsx('text-[10px] px-1.5 py-0.5 rounded font-medium', isTowbook ? 'bg-amber-600/20 text-amber-400' : 'bg-purple-600/20 text-purple-400')}>{isTowbook ? 'TOWBOOK' : 'ON-PLATFORM'}</span>}
                    <span className="text-[10px] text-slate-500 font-normal ml-auto">
                      {isTowbook ? 'Ranked by volume · Response = PTA (promised)' : 'Ranked by avg response time'}
                    </span>
                  </h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-slate-500 border-b border-slate-800">
                          <th className="text-left py-2 px-2 w-8">#</th>
                          <th className="text-left py-2 px-2">{isTowbook ? 'Contractor' : 'Driver'}</th>
                          <th className="text-right py-2 px-2">Calls</th>
                          <th className="text-right py-2 px-2">Avg Response</th>
                          <th className="text-right py-2 px-2">Median</th>
                          <th className="text-right py-2 px-2">On-Site</th>
                          <th className="text-right py-2 px-2">Declines</th>
                        </tr>
                      </thead>
                      <tbody>
                        {leaderboard.slice(0, 15).map((d, i) => (
                          <tr key={d.id} className={clsx('border-b border-slate-800/40 hover:bg-slate-800/30',
                            i < 3 && 'bg-emerald-950/10')}>
                            <td className="py-1.5 px-2">
                              <span className={clsx('w-5 h-5 rounded-full inline-flex items-center justify-center text-[9px] font-bold',
                                i === 0 ? 'bg-amber-500 text-black' : i === 1 ? 'bg-slate-400 text-black' : i === 2 ? 'bg-amber-700 text-white' : 'bg-slate-800 text-slate-500')}>
                                {i + 1}
                              </span>
                            </td>
                            <td className="py-1.5 px-2 text-white font-medium">
                              {d.name}
                            </td>
                            <td className="py-1.5 px-2 text-right text-slate-400">{d.total_calls}</td>
                            <td className={clsx('py-1.5 px-2 text-right font-bold',
                              d.avg_response_min && d.avg_response_min <= 45 ? 'text-emerald-400' :
                              d.avg_response_min && d.avg_response_min <= 90 ? 'text-amber-400' : 'text-red-400')}>
                              {d.avg_response_min ?? '—'} min
                            </td>
                            <td className="py-1.5 px-2 text-right text-slate-300">{d.median_response_min ?? '—'} min</td>
                            <td className="py-1.5 px-2 text-right text-slate-400">{d.avg_onsite_min ?? '—'} min</td>
                            <td className={clsx('py-1.5 px-2 text-right', d.declines > 0 ? 'text-red-400' : 'text-slate-600')}>
                              {d.declines} ({d.decline_rate}%)
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {isTowbook && missingTruckIdCount > 0 && (
                      <p className="text-[10px] text-slate-500 mt-2 px-1">
                        {missingTruckIdCount} call{missingTruckIdCount > 1 ? 's' : ''} missing driver info — not shown in leaderboard
                      </p>
                    )}
                  </div>
                </div>
              )}

              {/* Decline + Cancel stacked (1/3) */}
              <div className="space-y-4">
                {declines && declines.total_declines > 0 && (
                  <div className="glass rounded-xl p-4">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2 flex items-center gap-1.5">
                      <XCircle className="w-3.5 h-3.5 text-red-400" />
                      Facility Declines ({declines.total_declines})
                      <span className="text-red-400 font-normal ml-auto">{declines.decline_rate}% rate</span>
                    </h4>
                    <ReasonBars items={declines.by_reason} color="bg-red-500" />
                  </div>
                )}
                {cancels && cancels.total_cancellations > 0 && (
                  <div className="glass rounded-xl p-4">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2 flex items-center gap-1.5">
                      <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
                      Cancellations ({cancels.total_cancellations})
                    </h4>
                    <ReasonBars items={cancels.by_reason} color="bg-amber-500" />
                  </div>
                )}
              </div>
            </div>
          )}


          {/* ═══ SUPERVISOR ANALYSIS ══════════════════════════════════════════ */}
          <div className="glass rounded-xl p-5">
            <h3 className="font-bold text-slate-200 mb-4 flex items-center gap-2 text-sm">
              <AlertTriangle className="w-5 h-5 text-amber-400" />
              Supervisor Analysis
              <span className="ml-auto text-[10px] font-normal text-slate-500">
                {`${startDate} – ${endDate}`} · {perf.total_sas.toLocaleString()} SAs
              </span>
            </h3>

            {/* Observations */}
            <div className="space-y-2 mb-5">
              <div className="text-[9px] font-bold uppercase tracking-wider text-slate-500 mb-1">What the data shows</div>
              {insights.map((ins, i) => (
                <div key={i} className={clsx('flex items-start gap-2 rounded-lg p-2.5 text-xs',
                  ins.type === 'critical' ? 'bg-red-950/30 border border-red-800/30' :
                  ins.type === 'warn' ? 'bg-amber-950/30 border border-amber-800/30' :
                  ins.type === 'info' ? 'bg-brand-950/20 border border-brand-800/20' :
                  'bg-emerald-950/20 border border-emerald-800/20')}>
                  {ins.type === 'critical' ? <XCircle className="w-3.5 h-3.5 text-red-400 mt-0.5 shrink-0" /> :
                   ins.type === 'warn' ? <AlertTriangle className="w-3.5 h-3.5 text-amber-400 mt-0.5 shrink-0" /> :
                   ins.type === 'info' ? <AlertTriangle className="w-3.5 h-3.5 text-brand-400 mt-0.5 shrink-0" /> :
                   <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 mt-0.5 shrink-0" />}
                  <span className={ins.type === 'critical' ? 'text-red-200' : ins.type === 'warn' ? 'text-amber-200' : ins.type === 'info' ? 'text-brand-200' : 'text-emerald-200'}>
                    {ins.text}
                  </span>
                </div>
              ))}
            </div>

            {/* Actions */}
            <div className="space-y-2">
              <div className="text-[9px] font-bold uppercase tracking-wider text-slate-500 mb-1">Recommended Actions</div>
              {actions.map((act, i) => (
                <div key={i} className={clsx('flex items-start gap-2 rounded-lg p-2.5 text-xs border',
                  act.priority === 'HIGH' ? 'bg-red-950/20 border-red-800/30' :
                  act.priority === 'MED' ? 'bg-amber-950/20 border-amber-800/30' :
                  act.priority === 'GOAL' ? 'bg-brand-950/30 border-brand-700/40' :
                  'bg-slate-800/30 border-slate-700/30')}>
                  <ArrowRight className={clsx('w-3.5 h-3.5 mt-0.5 shrink-0',
                    act.priority === 'HIGH' ? 'text-red-400' : act.priority === 'MED' ? 'text-amber-400' :
                    act.priority === 'GOAL' ? 'text-brand-400' : 'text-slate-400')} />
                  <div>
                    <span className={clsx('text-[9px] font-bold uppercase tracking-wider mr-1.5',
                      act.priority === 'HIGH' ? 'text-red-500' : act.priority === 'MED' ? 'text-amber-500' :
                      act.priority === 'GOAL' ? 'text-brand-400' : 'text-slate-500')}>
                      {act.priority}
                    </span>
                    <span className="text-slate-300">{act.text}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* ═══ GOALS (from scorecard) ═══════════════════════════════════════ */}
          {scorecard && (
            <div className="glass rounded-xl p-5">
              <h3 className="font-semibold text-slate-200 mb-3 flex items-center gap-2 text-sm">
                <Target className="w-4 h-4 text-brand-400" /> How to Meet the 45-Minute Goal
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                {[
                  {
                    num: 1,
                    title: isTowbook ? 'Maximize Contractor Coverage' : 'Deploy Full Fleet',
                    desc: isTowbook
                      ? `${scorecard.fleet.total_contractors || scorecard.fleet.total_trucks || 0} contractor trucks active. Monitor decline rates and PTA compliance.`
                      : `${scorecard.fleet.total_members} drivers on the books (${scorecard.fleet.tow_drivers} tow, ${scorecard.fleet.battery_light_drivers} battery/light). Ensure all on the road at peak.`,
                    impact: isTowbook ? 'Reduces decline-driven delays' : 'Eliminates queue wait',
                  },
                  {
                    num: 2,
                    title: 'Hit 45-Min PTA Target',
                    desc: scorecard.sla.pta_compliance_45min >= 100
                      ? 'All PTAs promised within 45 min — maintain this standard.'
                      : `Only ${scorecard.sla.pta_compliance_45min}% of PTAs promised ≤45 min. ${scorecard.sla.median_pta_promised ? `Median PTA: ${scorecard.sla.median_pta_promised} min.` : ''} Tighten dispatch promises.`,
                    impact: scorecard.sla.pta_compliance_45min >= 100 ? 'On target' : 'Reduces member wait expectations',
                  },
                  {
                    num: 3,
                    title: 'Close Response Gap',
                    desc: scorecard.sla.actual_median_response && scorecard.sla.actual_median_response > 45
                      ? `Median response is ${scorecard.sla.actual_median_response} min — ${scorecard.sla.gap_vs_target} min over target. Only ${scorecard.sla.actual_under_45min_pct}% under 45 min.`
                      : scorecard.sla.actual_median_response
                        ? `Median response ${scorecard.sla.actual_median_response} min — meeting 45-min target. ${scorecard.sla.actual_under_45min_pct}% under 45 min.`
                        : 'Not enough completed calls to measure response time.',
                    impact: scorecard.sla.actual_median_response && scorecard.sla.actual_median_response > 45
                      ? `Closing the ${scorecard.sla.gap_vs_target}-min gap`
                      : 'Maintain current performance',
                  },
                ].map(l => (
                  <div key={l.num} className="bg-slate-800/40 rounded-xl p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="w-6 h-6 rounded-full bg-brand-600 text-white text-xs font-bold flex items-center justify-center">{l.num}</span>
                      <span className="font-semibold text-xs text-slate-200">{l.title}</span>
                    </div>
                    <p className="text-[10px] text-slate-400 leading-relaxed">{l.desc}</p>
                    <div className="mt-2 text-[10px] text-emerald-400 font-medium">{l.impact}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
      </>)} {/* end operations tab */}
    </div>
  )
}
