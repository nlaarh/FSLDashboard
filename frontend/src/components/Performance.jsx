import { useState, useEffect } from 'react'
import {
  ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, Legend, Cell, PieChart, Pie,
} from 'recharts'
import { clsx } from 'clsx'
import {
  TrendingDown, TrendingUp, CheckCircle2, XCircle, Clock, ThumbsUp,
  AlertTriangle, Target, Activity, Users, ArrowRight, ChevronLeft, ChevronRight,
  Calendar, Minus,
} from 'lucide-react'
import { fetchPerformance, fetchDecomposition } from '../api'

// ── Period helpers ────────────────────────────────────────────────────────────

function today() {
  return new Date().toISOString().split('T')[0]
}

import { getWeek, getMonth } from '../utils/dateHelpers'

// ── Sub-components ────────────────────────────────────────────────────────────

function KPI({ label, value, sub, color = 'text-white', icon: Icon, trend, border = '' }) {
  return (
    <div className={clsx('rounded-xl p-4 bg-slate-800/50 border', border || 'border-slate-700/30')}>
      <div className="flex items-start justify-between mb-2">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{label}</div>
        {Icon && <Icon className="w-4 h-4 text-slate-500" />}
      </div>
      <div className={clsx('text-2xl font-black', color)}>{value}</div>
      {sub && <div className="text-xs text-slate-500 mt-0.5">{sub}</div>}
      {trend != null && (
        <div className={clsx('flex items-center gap-1 mt-1 text-xs font-medium',
          trend > 0 ? 'text-emerald-400' : trend < 0 ? 'text-red-400' : 'text-slate-500')}>
          {trend > 0 ? <TrendingUp className="w-3 h-3" /> : trend < 0 ? <TrendingDown className="w-3 h-3" /> : <Minus className="w-3 h-3" />}
          {trend > 0 ? `+${trend}%` : `${trend}%`}
        </div>
      )}
    </div>
  )
}

function BucketBar({ label, count, total, colorClass, pct }) {
  const p = pct ?? (total > 0 ? Math.round(100 * count / total) : 0)
  return (
    <div className="flex items-center gap-2">
      <div className="w-28 text-xs text-slate-400 text-right shrink-0">{label}</div>
      <div className="flex-1 h-5 bg-slate-900 rounded-full overflow-hidden">
        <div className={clsx('h-full rounded-full transition-all', colorClass)}
          style={{ width: `${Math.max(p, 1)}%` }} />
      </div>
      <div className="w-20 text-xs text-slate-400 shrink-0">{count.toLocaleString()} ({p}%)</div>
    </div>
  )
}

// ── Supervisor Analysis (narrative) ──────────────────────────────────────────

function buildInsights(data, garageName) {
  const insights = []
  const actions  = []

  const { acceptance, completion, response_time: rt, pts_ata, satisfaction } = data

  // Completion rate
  const compPct = completion.pct
  if (compPct < 80) {
    insights.push({ type: 'critical', text: `Only ${compPct}% of calls are completed — ${+(100 - compPct).toFixed(1)}% are being lost to cancellations or no-shows.` })
    actions.push({ priority: 'HIGH', text: 'Investigate cancellation reasons. Is it the member canceling (too slow) or the facility declining?' })
  } else if (compPct < 92) {
    insights.push({ type: 'warn', text: `Completion rate is ${compPct}% — slightly below the 95% target.` })
    actions.push({ priority: 'MED', text: 'Review facility decline reasons and "Could Not Wait" cancellations.' })
  } else {
    insights.push({ type: 'good', text: `Strong completion rate: ${compPct}% of calls handled to completion.` })
  }

  // Response time
  const under45 = rt.under_45_pct
  const median  = rt.median
  if (median != null) {
    if (median > 90) {
      insights.push({ type: 'critical', text: `Median response time is ${median} min — ${median - 45} min over the 45-min ATA target. Members are waiting far too long.` })
      actions.push({ priority: 'HIGH', text: `Close the ${median - 45}-min gap: add available drivers during peak hours and enforce closest-driver dispatch.` })
    } else if (median > 45) {
      insights.push({ type: 'warn', text: `Median response is ${median} min — ${median - 45} min over target. ${under45}% of calls are delivered within 45 min.` })
      actions.push({ priority: 'HIGH', text: `To hit 45-min ATA: need ${+(100 - under45).toFixed(1)}% more calls under 45 min. Focus on reducing dispatch queue time.` })
    } else {
      insights.push({ type: 'good', text: `Median response time is ${median} min — meeting the 45-min ATA target. ${under45}% of calls delivered within 45 min.` })
    }
    if (rt.over_120 > 0) {
      insights.push({ type: 'warn', text: `${rt.over_120} calls (${rt.over_120_pct}%) took over 2 hours — these are the members most at risk of canceling.` })
      actions.push({ priority: 'MED', text: `Investigate the ${rt.over_120} 2-hour+ calls. Are they tow drop-offs? Complex jobs? Or dispatch failures?` })
    }
  }

  // PTS-ATA accuracy (promised vs actual arrival)
  if (pts_ata && pts_ata.on_time_pct != null) {
    const latePct = pts_ata.late_pct
    const avgDelta = pts_ata.avg_delta
    if (latePct > 50) {
      insights.push({ type: 'critical', text: `${latePct}% of calls arrived late vs. the promised ETA. Average overrun: ${avgDelta > 0 ? '+' : ''}${avgDelta} min. Promises to members are not being kept.` })
      actions.push({ priority: 'HIGH', text: 'Dispatch is either promising too short ETAs or not dispatching immediately. Review PTA values set at dispatch time.' })
    } else if (latePct > 25) {
      insights.push({ type: 'warn', text: `${latePct}% of calls arrived later than promised ETA (avg ${avgDelta > 0 ? '+' : ''}${avgDelta} min late).` })
      actions.push({ priority: 'MED', text: 'Coach dispatchers to set realistic ETAs — an accurate 60-min promise is better than a broken 45-min one.' })
    } else {
      insights.push({ type: 'good', text: `${pts_ata.on_time_pct}% of calls arrived at or before promised ETA — strong ETA accuracy.` })
    }
  }

  // Acceptance rates
  if (acceptance.primary_total > 0) {
    const primPct = acceptance.primary_pct
    if (primPct < 70) {
      insights.push({ type: 'critical', text: `Only ${primPct}% acceptance rate on auto-dispatched (primary) calls — facility is declining ${+(100 - primPct).toFixed(1)}% of system-assigned work.` })
      actions.push({ priority: 'HIGH', text: 'Identify top decline reasons for primary calls. Driver availability? Truck capability mismatch? Shift coverage gaps?' })
    } else if (primPct < 88) {
      insights.push({ type: 'warn', text: `${primPct}% acceptance on primary (auto-assigned) calls. ${+(100 - primPct).toFixed(1)}% decline rate is above the 5-10% normal range.` })
      actions.push({ priority: 'MED', text: 'Review primary call decline reasons with facility manager.' })
    }
  }

  // Satisfaction
  if (satisfaction) {
    const satPct = satisfaction.total_satisfied_pct
    const disPct = satisfaction.dissatisfied_pct
    if (satPct < 70) {
      insights.push({ type: 'critical', text: `Member satisfaction is ${satPct}% — well below the 82% accreditation requirement. ${disPct}% of members are dissatisfied.` })
      actions.push({ priority: 'HIGH', text: `Satisfaction is the #1 priority — read the comments from the ${satisfaction.dissatisfied + satisfaction.totally_dissatisfied} dissatisfied members to find the common complaint.` })
    } else if (satPct < 82) {
      insights.push({ type: 'warn', text: `Satisfaction at ${satPct}% — ${82 - satPct}% below the 82% accreditation target. ${disPct}% of members are dissatisfied.` })
      actions.push({ priority: 'MED', text: `Needs ${82 - satPct}% lift to meet accreditation. Long waits are typically the #1 driver — closing the ATA gap will help.` })
    } else {
      insights.push({ type: 'good', text: `Satisfaction at ${satPct}% — meeting the 82% accreditation requirement. ${satisfaction.total} members surveyed.` })
    }
  }

  // If no critical/warn issues, add positive framing
  const hasBad = insights.some(i => i.type !== 'good')
  if (!hasBad) {
    actions.push({ priority: 'MAINTAIN', text: 'Performance is strong across all dimensions. Continue monitoring daily and share results with the team.' })
  }

  // Always: path to 45-min ATA
  if (rt.median != null && rt.median > 45) {
    const gap = rt.median - 45
    actions.push({
      priority: 'GOAL',
      text: `PATH TO 45-MIN ATA: Median is ${rt.median} min. Closing the ${gap}-min gap requires: (1) Dispatch closest driver first, (2) Reduce queue wait before dispatch, (3) Ensure driver is en route within 5 min of assignment.`,
    })
  }

  return { insights, actions }
}

// ── Decomposition Panel ──────────────────────────────────────────────────────

function DecompositionPanel({ garageId, start, end }) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)
  const [open, setOpen]       = useState(false)

  useEffect(() => {
    if (!open) return
    setLoading(true)
    setError(null)
    fetchDecomposition(garageId, start, end)
      .then(setData)
      .catch(e => setError(e.response?.data?.detail || e.message))
      .finally(() => setLoading(false))
  }, [garageId, start, end, open])

  const decomp = data?.response_decomposition
  const leaderboard = data?.driver_leaderboard || []
  const declines = data?.decline_analysis
  const cancels = data?.cancel_analysis
  const garageType = data?.garage_type || 'fleet'
  const isTowbook = garageType === 'towbook'
  const isFleet = garageType === 'fleet'

  return (
    <div className="glass rounded-xl overflow-hidden">
      <button onClick={() => setOpen(o => !o)}
        className="w-full p-5 flex items-center justify-between hover:bg-slate-800/30 transition-colors">
        <h3 className="font-semibold text-slate-200 flex items-center gap-2">
          <Activity className="w-4 h-4 text-brand-400" />
          Enhanced Analytics
          <span className="text-xs font-normal text-slate-500 ml-2">
            Response decomposition, driver leaderboard, decline analysis
          </span>
        </h3>
        <ChevronRight className={clsx('w-4 h-4 text-slate-500 transition-transform', open && 'rotate-90')} />
      </button>

      {open && (
        <div className="px-5 pb-5 space-y-5 border-t border-slate-800/50">
          {loading && (
            <div className="flex items-center gap-2 py-6 justify-center text-sm text-slate-400">
              <div className="w-4 h-4 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
              Loading enhanced analytics...
            </div>
          )}
          {error && <div className="text-red-400 text-sm py-2">{error}</div>}

          {decomp && (
            <>
              {/* Waterfall chart */}
              <div className="pt-4">
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">
                  Response Time Decomposition ({decomp.sample_size.toLocaleString()} calls)
                </h4>
                <div className="flex items-end gap-1 h-32">
                  {[
                    { label: 'Dispatch', value: decomp.avg_dispatch_min, color: 'bg-red-500', median: decomp.median_dispatch_min },
                    { label: 'Travel', value: decomp.avg_travel_min, color: 'bg-amber-500', median: decomp.median_travel_min },
                    { label: 'On-Site', value: decomp.avg_onsite_min, color: 'bg-emerald-500', median: decomp.median_onsite_min },
                  ].map(seg => {
                    const maxVal = Math.max(decomp.avg_dispatch_min || 1, decomp.avg_travel_min || 1, decomp.avg_onsite_min || 1)
                    const pct = maxVal > 0 ? ((seg.value || 0) / maxVal) * 100 : 0
                    return (
                      <div key={seg.label} className="flex-1 flex flex-col items-center">
                        <div className="text-xs font-bold text-white mb-1">{seg.value ?? 0}m</div>
                        <div className={clsx('w-full rounded-t-md transition-all', seg.color)}
                          style={{ height: `${Math.max(pct, 5)}%` }} />
                        <div className="text-[10px] text-slate-400 mt-1">{seg.label}</div>
                        <div className="text-[10px] text-slate-600">med: {seg.median ?? 0}m</div>
                      </div>
                    )
                  })}
                </div>
              </div>

              {/* By work type */}
              {Object.keys(decomp.by_work_type).length > 0 && (
                <div>
                  <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">By Work Type</h4>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-slate-500 border-b border-slate-800">
                          <th className="text-left py-1.5 px-2">Type</th>
                          <th className="text-right py-1.5 px-2">Dispatch</th>
                          <th className="text-right py-1.5 px-2">Travel</th>
                          <th className="text-right py-1.5 px-2">On-Site</th>
                          <th className="text-right py-1.5 px-2">Total</th>
                          <th className="text-right py-1.5 px-2">Count</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(decomp.by_work_type)
                          .sort((a, b) => b[1].count - a[1].count)
                          .map(([wt, d]) => (
                          <tr key={wt} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                            <td className="py-1.5 px-2 text-slate-300 font-medium">{wt}</td>
                            <td className="py-1.5 px-2 text-right text-red-400">{d.dispatch}m</td>
                            <td className="py-1.5 px-2 text-right text-amber-400">{d.travel}m</td>
                            <td className="py-1.5 px-2 text-right text-emerald-400">{d.onsite}m</td>
                            <td className="py-1.5 px-2 text-right text-white font-bold">{d.total}m</td>
                            <td className="py-1.5 px-2 text-right text-slate-500">{d.count}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Driver leaderboard */}
              {leaderboard.length > 0 && (
                <div>
                  <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">
                    {isFleet ? 'Driver Leaderboard (by avg response time)' : 'Contractor Leaderboard (by volume)'}
                    {!isFleet && <span className={`ml-2 text-[10px] px-1.5 py-0.5 rounded font-medium normal-case ${isTowbook ? 'bg-amber-600/20 text-amber-400' : 'bg-purple-600/20 text-purple-400'}`}>{isTowbook ? 'Towbook' : 'On-Platform'}</span>}
                  </h4>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-slate-500 border-b border-slate-800">
                          <th className="text-left py-1.5 px-2">#</th>
                          <th className="text-left py-1.5 px-2">{isTowbook ? 'Contractor Truck' : 'Driver'}</th>
                          <th className="text-right py-1.5 px-2">Calls</th>
                          <th className="text-right py-1.5 px-2">Avg Resp</th>
                          <th className="text-right py-1.5 px-2">Med Resp</th>
                          <th className="text-right py-1.5 px-2">Avg On-Site</th>
                          <th className="text-right py-1.5 px-2">Declines</th>
                        </tr>
                      </thead>
                      <tbody>
                        {leaderboard.map((d, i) => (
                          <tr key={d.id} className={clsx(
                            'border-b border-slate-800/50 hover:bg-slate-800/30',
                            i < 3 && 'bg-emerald-950/10'
                          )}>
                            <td className="py-1.5 px-2">
                              <span className={clsx('w-5 h-5 rounded-full inline-flex items-center justify-center text-[10px] font-bold',
                                i === 0 ? 'bg-amber-500 text-black' :
                                i === 1 ? 'bg-slate-400 text-black' :
                                i === 2 ? 'bg-amber-700 text-white' :
                                'bg-slate-800 text-slate-400')}>
                                {i + 1}
                              </span>
                            </td>
                            <td className="py-1.5 px-2 text-white font-medium">{d.name}</td>
                            <td className="py-1.5 px-2 text-right text-slate-400">{d.total_calls}</td>
                            <td className={clsx('py-1.5 px-2 text-right font-bold',
                              d.avg_response_min && d.avg_response_min <= 45 ? 'text-emerald-400' :
                              d.avg_response_min && d.avg_response_min <= 90 ? 'text-amber-400' : 'text-red-400')}>
                              {d.avg_response_min ?? '—'}m
                            </td>
                            <td className="py-1.5 px-2 text-right text-slate-300">{d.median_response_min ?? '—'}m</td>
                            <td className="py-1.5 px-2 text-right text-slate-400">{d.avg_onsite_min ?? '—'}m</td>
                            <td className={clsx('py-1.5 px-2 text-right',
                              d.declines > 0 ? 'text-red-400' : 'text-slate-600')}>
                              {d.declines} ({d.decline_rate}%)
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Decline & Cancel analysis side by side */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* Declines */}
                {declines && declines.total_declines > 0 && (
                  <div className="bg-slate-800/30 rounded-lg p-4 border border-slate-700/30">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">
                      Facility Declines ({declines.total_declines} · {declines.decline_rate}% rate)
                    </h4>
                    <div className="space-y-1.5">
                      {declines.by_reason.map(r => (
                        <div key={r.reason} className="flex items-center gap-2">
                          <div className="flex-1 text-xs text-slate-300">{r.reason}</div>
                          <div className="w-24 h-2 bg-slate-900 rounded-full overflow-hidden">
                            <div className="h-full bg-red-500 rounded-full" style={{ width: `${r.pct}%` }} />
                          </div>
                          <div className="text-xs text-slate-500 w-16 text-right">{r.count} ({r.pct}%)</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Cancellations */}
                {cancels && cancels.total_cancellations > 0 && (
                  <div className="bg-slate-800/30 rounded-lg p-4 border border-slate-700/30">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">
                      Cancellations ({cancels.total_cancellations})
                    </h4>
                    <div className="space-y-1.5">
                      {cancels.by_reason.map(r => (
                        <div key={r.reason} className="flex items-center gap-2">
                          <div className="flex-1 text-xs text-slate-300">{r.reason}</div>
                          <div className="w-24 h-2 bg-slate-900 rounded-full overflow-hidden">
                            <div className="h-full bg-amber-500 rounded-full" style={{ width: `${r.pct}%` }} />
                          </div>
                          <div className="text-xs text-slate-500 w-16 text-right">{r.count} ({r.pct}%)</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

const PERIOD_TYPES = ['Daily', 'Weekly', 'Monthly']

export default function Performance({ garageId, garageName }) {
  const [periodType, setPeriodType] = useState('Weekly')
  const [dayDate, setDayDate]       = useState(() => {
    const d = new Date(); d.setDate(d.getDate() - 1); return d.toISOString().split('T')[0]
  })
  const [weekOffset,  setWeekOffset]  = useState(0)
  const [monthOffset, setMonthOffset] = useState(0)
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)

  const week  = getWeek(weekOffset)
  const month = getMonth(monthOffset)

  const { start, end, label } = (() => {
    if (periodType === 'Daily')   return { start: dayDate, end: dayDate, label: dayDate }
    if (periodType === 'Weekly')  return { ...week }
    return { ...month }
  })()

  useEffect(() => {
    setData(null)
    setError(null)
    setLoading(true)
    fetchPerformance(garageId, start, end)
      .then(setData)
      .catch(e => setError(e.response?.data?.detail || e.message))
      .finally(() => setLoading(false))
  }, [garageId, start, end])

  const { insights, actions } = data ? buildInsights(data, garageName) : { insights: [], actions: [] }

  const tooltipStyle = {
    contentStyle: { background: '#1e293b', border: '1px solid #334155', borderRadius: 8 },
    itemStyle: { color: '#e2e8f0' },
    labelStyle: { color: '#94a3b8', fontSize: 11 },
  }

  return (
    <div className="space-y-5">

      {/* ── Period Selector ─────────────────────────────────────────── */}
      <div className="glass rounded-xl p-4">
        <div className="flex flex-wrap items-center gap-4">

          {/* Type toggle */}
          <div className="flex gap-1 p-1 bg-slate-900 rounded-xl">
            {PERIOD_TYPES.map(pt => (
              <button key={pt} onClick={() => setPeriodType(pt)}
                className={clsx('px-3 py-1.5 rounded-lg text-xs font-semibold transition-all',
                  periodType === pt
                    ? 'bg-brand-600 text-white'
                    : 'text-slate-400 hover:text-white hover:bg-slate-800')}>
                {pt}
              </button>
            ))}
          </div>

          {/* Daily picker */}
          {periodType === 'Daily' && (
            <input type="date" value={dayDate} onChange={e => setDayDate(e.target.value)}
              className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-sm
                         focus:outline-none focus:ring-2 focus:ring-brand-500/40" />
          )}

          {/* Weekly nav */}
          {periodType === 'Weekly' && (
            <div className="flex items-center gap-2">
              <button onClick={() => setWeekOffset(w => w - 1)}
                className="p-1.5 rounded-lg hover:bg-slate-800 transition-colors">
                <ChevronLeft className="w-4 h-4 text-slate-400" />
              </button>
              <div className="text-sm font-semibold text-white min-w-[200px] text-center">
                {weekOffset === 0 ? 'This Week' : weekOffset === -1 ? 'Last Week' : weekOffset === 1 ? 'Next Week' : `Week of ${week.start}`}
                <div className="text-xs text-slate-400 font-normal">{week.label}</div>
              </div>
              <button onClick={() => setWeekOffset(w => w + 1)}
                className="p-1.5 rounded-lg hover:bg-slate-800 transition-colors">
                <ChevronRight className="w-4 h-4 text-slate-400" />
              </button>
              <button onClick={() => setWeekOffset(0)}
                className="ml-1 px-2 py-1 text-xs bg-slate-800 text-slate-400 hover:text-white rounded-lg">
                This Week
              </button>
            </div>
          )}

          {/* Monthly nav */}
          {periodType === 'Monthly' && (
            <div className="flex items-center gap-2">
              <button onClick={() => setMonthOffset(m => m - 1)}
                className="p-1.5 rounded-lg hover:bg-slate-800 transition-colors">
                <ChevronLeft className="w-4 h-4 text-slate-400" />
              </button>
              <div className="text-sm font-semibold text-white min-w-[180px] text-center">{month.label}</div>
              <button onClick={() => setMonthOffset(m => m + 1)}
                className="p-1.5 rounded-lg hover:bg-slate-800 transition-colors">
                <ChevronRight className="w-4 h-4 text-slate-400" />
              </button>
              <button onClick={() => setMonthOffset(0)}
                className="ml-1 px-2 py-1 text-xs bg-slate-800 text-slate-400 hover:text-white rounded-lg">
                This Month
              </button>
            </div>
          )}

          {loading && (
            <div className="flex items-center gap-2 text-xs text-slate-400 ml-2">
              <div className="w-3.5 h-3.5 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
              Loading...
            </div>
          )}
        </div>
      </div>

      {error && (
        <div className="rounded-xl bg-red-950/30 border border-red-800/30 p-4 text-red-300 text-sm">{error}</div>
      )}

      {data && (
        <>
          {/* ── KPI Row ─────────────────────────────────────────────── */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            <KPI label="Total SAs" value={data.total_sas.toLocaleString()}
              icon={Activity} color="text-white" />
            <KPI label="Completion Rate"
              value={`${data.completion.pct}%`}
              sub={`${data.completion.completed} of ${data.completion.total}`}
              color={data.completion.pct >= 95 ? 'text-emerald-400' : data.completion.pct >= 80 ? 'text-amber-400' : 'text-red-400'}
              border={data.completion.pct >= 95 ? 'border-emerald-800/30' : data.completion.pct >= 80 ? 'border-amber-800/30' : 'border-red-800/30'}
              icon={CheckCircle2} />
            <KPI label={data.response_time.metric === 'PTA (promised)' ? 'Median PTA' : 'Median Response'}
              value={data.response_time.median ? `${data.response_time.median} min` : 'N/A'}
              sub={`${data.response_time.under_45_pct}% under 45 min${data.response_time.metric === 'PTA (promised)' ? ' · PTA' : ''}`}
              color={data.response_time.median <= 45 ? 'text-emerald-400' : data.response_time.median <= 70 ? 'text-amber-400' : 'text-red-400'}
              border={data.response_time.median <= 45 ? 'border-emerald-800/30' : data.response_time.median <= 70 ? 'border-amber-800/30' : 'border-red-800/30'}
              icon={Clock} />
            <KPI label={data.pts_ata?.metric === 'PTA (promised)' ? 'Avg PTA Promised' : 'ETA Accuracy (PTS-ATA)'}
              value={data.pts_ata?.on_time_pct != null ? `${data.pts_ata.on_time_pct}%` : data.pts_ata?.avg_pta != null ? `${data.pts_ata.avg_pta} min` : 'N/A'}
              sub={data.pts_ata?.on_time_pct != null ? `avg ${data.pts_ata.avg_delta > 0 ? '+' : ''}${data.pts_ata.avg_delta} min vs promise` : data.pts_ata?.metric === 'PTA (promised)' ? 'Towbook — no real arrival data' : 'No PTA data'}
              color={data.pts_ata?.on_time_pct >= 70 ? 'text-emerald-400' : data.pts_ata?.on_time_pct != null ? 'text-red-400' : data.pts_ata?.avg_pta != null ? 'text-brand-400' : 'text-slate-500'}
              border={data.pts_ata?.on_time_pct >= 70 ? 'border-emerald-800/30' : data.pts_ata?.avg_pta != null ? 'border-brand-800/30' : 'border-red-800/30'}
              icon={Target} />
            <KPI label="Primary Acceptance"
              value={`${data.acceptance.primary_pct}%`}
              sub={`${data.acceptance.primary_accepted} / ${data.acceptance.primary_total} auto-assigned`}
              color={data.acceptance.primary_pct >= 90 ? 'text-emerald-400' : data.acceptance.primary_pct >= 75 ? 'text-amber-400' : 'text-red-400'}
              border={data.acceptance.primary_pct >= 90 ? 'border-emerald-800/30' : 'border-amber-800/30'}
              icon={Users} />
            <KPI label="Satisfaction"
              value={data.satisfaction ? `${data.satisfaction.total_satisfied_pct}%` : 'N/A'}
              sub={data.satisfaction ? `${data.satisfaction.total} surveys · target 82%` : 'No surveys'}
              color={data.satisfaction && data.satisfaction.total_satisfied_pct >= 82 ? 'text-emerald-400' : data.satisfaction && data.satisfaction.total_satisfied_pct >= 70 ? 'text-amber-400' : 'text-red-400'}
              border={data.satisfaction && data.satisfaction.meets_target ? 'border-emerald-800/30' : 'border-red-800/30'}
              icon={ThumbsUp} />
          </div>

          {/* ── Trend Chart ─────────────────────────────────────────── */}
          {data.trend && data.trend.length > 0 && (
            <div className="glass rounded-xl p-5">
              <h3 className="font-semibold text-slate-200 mb-4 flex items-center gap-2">
                <Activity className="w-4 h-4 text-brand-400" />
                Volume & Completion Trend
                <span className="ml-auto text-xs text-slate-500 font-normal">
                  {data.period.single_day ? 'Hourly' : 'Daily'} breakdown
                </span>
              </h3>
              <div className="h-52">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={data.trend} margin={{ left: -10, right: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                    <XAxis dataKey="label" stroke="#475569"
                      tick={{ fontSize: 10, fill: '#94a3b8' }}
                      interval={data.trend.length > 14 ? Math.floor(data.trend.length / 10) : 0} />
                    <YAxis yAxisId="vol" stroke="#475569" tick={{ fontSize: 10, fill: '#94a3b8' }} />
                    <YAxis yAxisId="pct" orientation="right" domain={[0, 100]}
                      stroke="#475569" tick={{ fontSize: 10, fill: '#94a3b8' }}
                      tickFormatter={v => `${v}%`} />
                    <Tooltip {...tooltipStyle}
                      formatter={(val, name) => name === 'Completion %' ? `${val}%` : val} />
                    <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
                    <Bar yAxisId="vol" dataKey="total" name="Total SAs" fill="#6366f1" radius={[3,3,0,0]} opacity={0.7} />
                    <Bar yAxisId="vol" dataKey="completed" name="Completed" fill="#10b981" radius={[3,3,0,0]} opacity={0.8} />
                    <Line yAxisId="pct" type="monotone" dataKey="completion_pct"
                      name="Completion %" stroke="#f59e0b" strokeWidth={2}
                      dot={{ fill: '#f59e0b', r: 3 }} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* ── Detail Cards Row ─────────────────────────────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

            {/* Response Time Buckets */}
            <div className="glass rounded-xl p-5 space-y-3">
              <h3 className="font-semibold text-slate-200 flex items-center gap-2">
                <Clock className="w-4 h-4 text-brand-400" /> {data.response_time.metric === 'PTA (promised)' ? 'PTA Breakdown (Towbook)' : 'Response Time Breakdown'}
              </h3>
              <div className="grid grid-cols-2 gap-2 mb-3">
                <div className="text-center bg-emerald-950/30 border border-emerald-800/20 rounded-xl p-3">
                  <div className="text-xl font-bold text-emerald-400">{data.response_time.under_45}</div>
                  <div className="text-[10px] text-slate-400 mt-0.5">Within 45 min</div>
                  <div className="text-xs text-emerald-400">{data.response_time.under_45_pct}%</div>
                </div>
                <div className="text-center bg-amber-950/30 border border-amber-800/20 rounded-xl p-3">
                  <div className="text-xl font-bold text-amber-400">{data.response_time.b45_90}</div>
                  <div className="text-[10px] text-slate-400 mt-0.5">45–90 min</div>
                  <div className="text-xs text-amber-400">{data.response_time.b45_90_pct}%</div>
                </div>
                <div className="text-center bg-orange-950/30 border border-orange-800/20 rounded-xl p-3">
                  <div className="text-xl font-bold text-orange-400">{data.response_time.b90_120}</div>
                  <div className="text-[10px] text-slate-400 mt-0.5">90–120 min</div>
                  <div className="text-xs text-orange-400">{data.response_time.b90_120_pct}%</div>
                </div>
                <div className="text-center bg-red-950/30 border border-red-800/20 rounded-xl p-3">
                  <div className="text-xl font-bold text-red-400">{data.response_time.over_120}</div>
                  <div className="text-[10px] text-slate-400 mt-0.5">Over 2 hours</div>
                  <div className="text-xs text-red-400">{data.response_time.over_120_pct}%</div>
                </div>
              </div>
              <div className="pt-2 border-t border-slate-800/60">
                <div className="flex justify-between text-xs text-slate-400 mb-1">
                  <span>45-min target</span>
                  <span className={data.response_time.median && data.response_time.median <= 45 ? 'text-emerald-400 font-semibold' : 'text-red-400 font-semibold'}>
                    Median: {data.response_time.median ?? 'N/A'} min
                  </span>
                </div>
                {data.response_time.median != null && data.response_time.median > 45 && (
                  <div className="text-[10px] text-red-400 mt-1">
                    ↑ {data.response_time.median - 45} min over target
                  </div>
                )}
              </div>
            </div>

            {/* PTS-ATA Accuracy / Towbook PTA Distribution */}
            <div className="glass rounded-xl p-5 space-y-3">
              <h3 className="font-semibold text-slate-200 flex items-center gap-2">
                <Target className="w-4 h-4 text-brand-400" /> {data.pts_ata?.metric === 'PTA (promised)' ? 'PTA Distribution (Towbook)' : 'PTS-ATA (Promise vs Actual)'}
              </h3>
              {data.pts_ata?.on_time_pct != null ? (
                <>
                  <div className="flex gap-3">
                    <div className="flex-1 text-center bg-emerald-950/20 border border-emerald-800/20 rounded-xl p-3">
                      <div className="text-xl font-bold text-emerald-400">{data.pts_ata.on_time_pct}%</div>
                      <div className="text-[10px] text-slate-400">On Time or Early</div>
                    </div>
                    <div className="flex-1 text-center bg-red-950/20 border border-red-800/20 rounded-xl p-3">
                      <div className="text-xl font-bold text-red-400">{data.pts_ata.late_pct}%</div>
                      <div className="text-[10px] text-slate-400">Late vs Promise</div>
                    </div>
                  </div>
                  <div className="text-center text-sm">
                    <span className="text-slate-400">Avg delta: </span>
                    <span className={clsx('font-bold', data.pts_ata.avg_delta > 0 ? 'text-red-400' : 'text-emerald-400')}>
                      {data.pts_ata.avg_delta > 0 ? '+' : ''}{data.pts_ata.avg_delta} min
                    </span>
                    <span className="text-slate-500 text-xs ml-1">vs. promise</span>
                  </div>
                  <div className="space-y-1.5 mt-1">
                    {data.pts_ata.buckets.map(b => (
                      <BucketBar key={b.label} label={b.label} count={b.count}
                        total={data.pts_ata.total} pct={b.pct}
                        colorClass={
                          b.label.includes('Early') ? 'bg-emerald-500' :
                          b.label.includes('1–10')  ? 'bg-amber-400' :
                          b.label.includes('10–20') ? 'bg-orange-500' :
                          'bg-red-600'
                        } />
                    ))}
                  </div>
                  <div className="text-[10px] text-slate-500 pt-1">
                    Based on {data.pts_ata.total.toLocaleString()} completed SAs with valid ETA data.
                    Positive = arrived after promised time.
                  </div>
                </>
              ) : data.pts_ata?.metric === 'PTA (promised)' ? (
                <>
                  <div className="flex gap-3">
                    <div className="flex-1 text-center bg-brand-950/20 border border-brand-800/20 rounded-xl p-3">
                      <div className="text-xl font-bold text-brand-400">{data.pts_ata.median_pta ?? '?'}</div>
                      <div className="text-[10px] text-slate-400">Median PTA (min)</div>
                    </div>
                    <div className="flex-1 text-center bg-brand-950/20 border border-brand-800/20 rounded-xl p-3">
                      <div className="text-xl font-bold text-brand-400">{data.pts_ata.avg_pta ?? '?'}</div>
                      <div className="text-[10px] text-slate-400">Avg PTA (min)</div>
                    </div>
                  </div>
                  <div className="text-[10px] text-slate-500 pt-2">
                    Towbook garage — actual arrival time is unavailable (bulk-updated at midnight).
                    PTA = promised time to member at dispatch. Based on {data.pts_ata.total?.toLocaleString()} completed SAs.
                  </div>
                </>
              ) : (
                <div className="text-sm text-slate-500 py-4 text-center">
                  No PTA data available for this period.
                </div>
              )}
            </div>

            {/* Acceptance Rates */}
            <div className="glass rounded-xl p-5 space-y-3">
              <h3 className="font-semibold text-slate-200 flex items-center gap-2">
                <Users className="w-4 h-4 text-brand-400" /> Dispatch Acceptance
              </h3>

              {/* Primary */}
              <div>
                <div className="flex justify-between items-center mb-1">
                  <span className="text-xs text-slate-400 font-medium">Primary (Auto-Dispatched)</span>
                  <span className={clsx('text-sm font-bold',
                    data.acceptance.primary_pct >= 90 ? 'text-emerald-400' :
                    data.acceptance.primary_pct >= 75 ? 'text-amber-400' : 'text-red-400')}>
                    {data.acceptance.primary_pct}%
                  </span>
                </div>
                <div className="h-3 bg-slate-900 rounded-full overflow-hidden">
                  <div className={clsx('h-full rounded-full transition-all',
                    data.acceptance.primary_pct >= 90 ? 'bg-emerald-500' :
                    data.acceptance.primary_pct >= 75 ? 'bg-amber-500' : 'bg-red-500')}
                    style={{ width: `${data.acceptance.primary_pct}%` }} />
                </div>
                <div className="text-[10px] text-slate-500 mt-0.5">
                  {data.acceptance.primary_accepted} accepted / {data.acceptance.primary_total} auto-assigned
                </div>
              </div>

              {/* Not primary */}
              <div>
                <div className="flex justify-between items-center mb-1">
                  <span className="text-xs text-slate-400 font-medium">Secondary (Manually Routed)</span>
                  <span className={clsx('text-sm font-bold',
                    data.acceptance.not_primary_pct >= 90 ? 'text-emerald-400' :
                    data.acceptance.not_primary_pct >= 75 ? 'text-amber-400' : 'text-red-400')}>
                    {data.acceptance.not_primary_pct}%
                  </span>
                </div>
                <div className="h-3 bg-slate-900 rounded-full overflow-hidden">
                  <div className={clsx('h-full rounded-full transition-all',
                    data.acceptance.not_primary_pct >= 90 ? 'bg-emerald-500' :
                    data.acceptance.not_primary_pct >= 75 ? 'bg-amber-500' : 'bg-red-500')}
                    style={{ width: `${data.acceptance.not_primary_pct}%` }} />
                </div>
                <div className="text-[10px] text-slate-500 mt-0.5">
                  {data.acceptance.not_primary_accepted} accepted / {data.acceptance.not_primary_total} manual
                </div>
              </div>

              <div className="pt-2 border-t border-slate-800/60 text-[10px] text-slate-500">
                Total facility declines this period: <span className="text-red-400 font-medium">{data.acceptance.total_declined}</span>
              </div>

              {/* Satisfaction mini */}
              {data.satisfaction && (
                <div className="pt-2 border-t border-slate-800/60 space-y-2">
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-slate-400 font-medium">Total Satisfied</span>
                    <span className={clsx('text-sm font-bold',
                      data.satisfaction.meets_target ? 'text-emerald-400' : 'text-amber-400')}>
                      {data.satisfaction.total_satisfied_pct}%
                      {data.satisfaction.meets_target
                        ? ' ✓' : ` (need ${(82 - data.satisfaction.total_satisfied_pct).toFixed(1)}%↑)`}
                    </span>
                  </div>
                  <div className="flex gap-1 text-[10px]">
                    {[
                      { label: 'Totally Satisfied', count: data.satisfaction.totally_satisfied, color: 'bg-emerald-500' },
                      { label: 'Satisfied',          count: data.satisfaction.satisfied,          color: 'bg-teal-500' },
                      { label: 'Neither',            count: data.satisfaction.neither,            color: 'bg-slate-500' },
                      { label: 'Dissatisfied',       count: data.satisfaction.dissatisfied + data.satisfaction.totally_dissatisfied, color: 'bg-red-500' },
                    ].map(s => (
                      <div key={s.label} className="flex-1 text-center">
                        <div className={clsx('h-1.5 rounded-full mb-1', s.color)} />
                        <div className="text-slate-400">{s.count}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* ── Enhanced Decomposition ──────────────────────────────── */}
          <DecompositionPanel garageId={garageId} start={start} end={end} />

          {/* ── Supervisor Analysis ──────────────────────────────────── */}
          <div className="glass rounded-xl p-5">
            <h3 className="font-bold text-slate-200 mb-4 flex items-center gap-2">
              <AlertTriangle className="w-5 h-5 text-amber-400" />
              Supervisor Analysis
              <span className="ml-auto text-xs font-normal text-slate-500">
                {label} · {data.total_sas.toLocaleString()} SAs
              </span>
            </h3>

            {/* Observations */}
            <div className="space-y-2 mb-5">
              <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-2">What the data shows</div>
              {insights.map((ins, i) => (
                <div key={i} className={clsx(
                  'flex items-start gap-3 rounded-lg p-3 text-sm',
                  ins.type === 'critical' ? 'bg-red-950/30 border border-red-800/30' :
                  ins.type === 'warn'     ? 'bg-amber-950/30 border border-amber-800/30' :
                  ins.type === 'info'     ? 'bg-brand-950/20 border border-brand-800/20' :
                                           'bg-emerald-950/20 border border-emerald-800/20'
                )}>
                  {ins.type === 'critical' ? <XCircle className="w-4 h-4 text-red-400 mt-0.5 shrink-0" /> :
                   ins.type === 'warn'     ? <AlertTriangle className="w-4 h-4 text-amber-400 mt-0.5 shrink-0" /> :
                   ins.type === 'info'     ? <AlertTriangle className="w-4 h-4 text-brand-400 mt-0.5 shrink-0" /> :
                                            <CheckCircle2 className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" />}
                  <span className={ins.type === 'critical' ? 'text-red-200' : ins.type === 'warn' ? 'text-amber-200' : ins.type === 'info' ? 'text-brand-200' : 'text-emerald-200'}>
                    {ins.text}
                  </span>
                </div>
              ))}
            </div>

            {/* Actions */}
            <div className="space-y-2">
              <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-2">What the supervisor should do</div>
              {actions.map((act, i) => (
                <div key={i} className={clsx(
                  'flex items-start gap-3 rounded-lg p-3 text-sm border',
                  act.priority === 'HIGH'     ? 'bg-red-950/20 border-red-800/30' :
                  act.priority === 'MED'      ? 'bg-amber-950/20 border-amber-800/30' :
                  act.priority === 'GOAL'     ? 'bg-brand-950/30 border-brand-700/40' :
                                               'bg-slate-800/30 border-slate-700/30'
                )}>
                  <ArrowRight className={clsx('w-4 h-4 mt-0.5 shrink-0',
                    act.priority === 'HIGH'   ? 'text-red-400' :
                    act.priority === 'MED'    ? 'text-amber-400' :
                    act.priority === 'GOAL'   ? 'text-brand-400' : 'text-slate-400')} />
                  <div>
                    <span className={clsx('text-[10px] font-bold uppercase tracking-wider mr-2',
                      act.priority === 'HIGH'   ? 'text-red-500' :
                      act.priority === 'MED'    ? 'text-amber-500' :
                      act.priority === 'GOAL'   ? 'text-brand-400' : 'text-slate-500')}>
                      {act.priority}
                    </span>
                    <span className="text-slate-300">{act.text}</span>
                  </div>
                </div>
              ))}
            </div>

            {/* Path to 45-min ATA progress bar */}
            {data.response_time.median != null && (
              <div className="mt-5 pt-4 border-t border-slate-800/60">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold text-slate-300">Progress to 45-Min ATA Goal</span>
                  <span className="text-xs text-slate-500">
                    {data.response_time.under_45_pct}% of calls within target
                  </span>
                </div>
                <div className="h-3 bg-slate-900 rounded-full overflow-hidden">
                  <div className={clsx('h-full rounded-full transition-all',
                    data.response_time.under_45_pct >= 80 ? 'bg-emerald-500' :
                    data.response_time.under_45_pct >= 50 ? 'bg-amber-500' : 'bg-red-500')}
                    style={{ width: `${data.response_time.under_45_pct}%` }} />
                </div>
                <div className="flex justify-between text-[10px] text-slate-500 mt-1">
                  <span>0%</span>
                  <span className="text-brand-400 font-medium">▲ Target: 80%+ of calls ≤ 45 min</span>
                  <span>100%</span>
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
