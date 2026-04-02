import { useState, useEffect } from 'react'
import { clsx } from 'clsx'
import {
  TrendingDown, TrendingUp, CheckCircle2, XCircle, Clock, ThumbsUp,
  AlertTriangle, Target, Activity, Users, ArrowRight, ChevronLeft, ChevronRight,
  Calendar, Minus,
} from 'lucide-react'
import { fetchPerformance, fetchDecomposition } from '../api'
import PerformanceCharts from './PerformanceCharts'

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

          {/* ── Charts, Detail Cards, Supervisor Analysis (extracted) ── */}
          <PerformanceCharts data={data} label={label} insights={insights} actions={actions} />

          {/* ── Enhanced Decomposition ──────────────────────────────── */}
          <DecompositionPanel garageId={garageId} start={start} end={end} />
        </>
      )}
    </div>
  )
}
