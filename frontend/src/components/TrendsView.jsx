import React, { useState, useEffect, useCallback, useRef } from 'react'
import { clsx } from 'clsx'
import { Loader2, RefreshCw, CheckCircle2, AlertTriangle } from 'lucide-react'
import { ComposedChart, Bar, Line, XAxis, YAxis, Tooltip as RechartsTooltip, CartesianGrid, Area } from 'recharts'
import { fetchTrends, forceTrendsRefresh, fetchMonthTrends, refreshMonthTrends } from '../api'
import { InfoTip, TrendChart, CHART_COLORS } from './CommandCenterUtils'

export default function TrendsView() {
  const [trends, setTrends] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [refreshing, setRefreshing] = useState(false)
  const [refreshMsg, setRefreshMsg] = useState(null)

  useEffect(() => {
    fetchTrends()
      .then(setTrends)
      .catch(e => setError(e.message || 'Failed to load trends'))
      .finally(() => setLoading(false))
  }, [])

  const handleForceRefresh = async () => {
    setRefreshing(true)
    setRefreshMsg(null)
    try {
      const res = await forceTrendsRefresh()
      if (res.status === 'up_to_date') {
        // Cache is fresh — reload to make sure displayed data matches
        const fresh = await fetchTrends()
        if (fresh && !fresh.loading && fresh.days?.length) setTrends(fresh)
        setRefreshMsg({ type: 'ok', text: 'Already up to date.' })
      } else if (res.status === 'updated') {
        setRefreshMsg({ type: 'ok', text: `Added ${res.new_days} missing day${res.new_days !== 1 ? 's' : ''}.` })
        setTrends(res.data)
      } else {
        // full_refresh_triggered — poll until cache is populated
        setRefreshMsg({ type: 'info', text: 'Full refresh triggered — checking in 30s…' })
        await new Promise(r => setTimeout(r, 30000))
        const fresh = await fetchTrends()
        if (fresh && !fresh.loading && fresh.days?.length) {
          setTrends(fresh)
          setRefreshMsg({ type: 'ok', text: 'Refreshed successfully.' })
        } else {
          setRefreshMsg({ type: 'warn', text: 'Still generating — check back in 1–2 min.' })
        }
      }
    } catch (e) {
      setRefreshMsg({ type: 'err', text: e.response?.data?.detail || e.message })
    } finally {
      setRefreshing(false)
    }
  }

  if (loading) return (
    <div className="max-w-5xl mx-auto flex items-center justify-center py-20">
      <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
      <span className="ml-2 text-sm text-slate-500">Loading 30-day trends...</span>
    </div>
  )
  if (error) return <div className="max-w-5xl mx-auto text-center text-red-400 py-10 text-sm">{error}</div>
  if (trends?.loading) return (
    <div className="max-w-5xl mx-auto text-center py-10">
      <Loader2 className="w-5 h-5 animate-spin text-blue-500 mx-auto mb-2" />
      <div className="text-sm text-slate-500">Generating 30-day trends in background...</div>
      <div className="text-xs text-slate-600 mt-1">Refresh in 1-2 minutes. Data is pre-computed nightly after midnight.</div>
    </div>
  )
  if (!trends?.days?.length) return <div className="max-w-5xl mx-auto text-center text-slate-600 py-10 text-sm">No trend data available</div>

  const days = trends.days.map(d => ({ ...d, label: d.date.slice(5) })) // "03-15"

  const monthlyData = (() => {
    const byMonth = {}
    trends.days.forEach(d => {
      const key = d.date.slice(0, 7)
      if (!byMonth[key]) byMonth[key] = []
      byMonth[key].push(d)
    })
    return Object.keys(byMonth).sort().map(key => {
      const ds = byMonth[key]
      const label = new Date(key + '-02').toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
      const vol = ds.reduce((s, d) => s + (d.volume || 0), 0)
      const completed = ds.reduce((s, d) => s + (d.completed || 0), 0)
      const avg = f => { const vs = ds.map(d => d[f]).filter(v => v != null && !isNaN(v)); return vs.length ? vs.reduce((s, v) => s + v, 0) / vs.length : null }
      return {
        label, days: ds.length, vol, completed,
        completion: vol > 0 ? (completed / vol * 100) : null,
        auto: avg('auto_pct'), sla: avg('sla_pct'),
        fleet_ata: avg('fleet_ata'), towbook_ata: avg('towbook_ata'),
        reassignments: ds.reduce((s, d) => s + (d.reassignments || 0), 0),
        satisfaction: avg('satisfaction_pct'),
      }
    })
  })()

  const customTooltip = ({ active, payload, label }) => {
    if (!active || !payload?.length) return null
    return (
      <div className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs shadow-xl">
        <div className="font-semibold text-slate-300 mb-1">{label}</div>
        {payload.map((p, i) => (
          <div key={i} className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: p.color }} />
            <span className="text-slate-400">{p.name}:</span>
            <span className="font-semibold text-white">{p.value != null ? (typeof p.value === 'number' && p.value % 1 !== 0 ? p.value.toFixed(1) : p.value) : '—'}{p.unit || ''}</span>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="max-w-5xl mx-auto space-y-4">

      {/* Header: title + refresh button */}
      <div className="flex items-center justify-between">
        <div className="text-xs text-slate-500">Last 30 complete days · Excludes today &amp; Tow Drop-Off</div>
        <div className="flex items-center gap-2">
          {refreshMsg && (
            <span className={clsx('text-[11px]',
              refreshMsg.type === 'ok' ? 'text-emerald-400' :
              refreshMsg.type === 'warn' ? 'text-amber-400' :
              refreshMsg.type === 'err' ? 'text-red-400' : 'text-slate-400'
            )}>{refreshMsg.text}</span>
          )}
          <button
            onClick={handleForceRefresh}
            disabled={refreshing}
            title="Fetch only missing days (smart incremental refresh)"
            className="flex items-center gap-1.5 text-xs text-slate-300 hover:text-white transition disabled:opacity-40 bg-slate-800 hover:bg-slate-700 px-3 py-1.5 rounded-lg border border-slate-700/50"
          >
            <RefreshCw className={clsx('w-3.5 h-3.5', refreshing && 'animate-spin')} />
            {refreshing ? 'Refreshing…' : 'Refresh Data'}
          </button>
        </div>
      </div>

      {/* Row 1: Volume + Completion | Auto Dispatch % */}
      <div className="grid grid-cols-2 gap-4">
        <TrendChart title="Daily Volume + Completion Rate"
          tip="Gray bars = total calls. Green bars = completed.\nGreen line = completion %.\nGap between bars = canceled + in-progress.\nMonday is typically the busiest day (1.8x Sunday).">
          <ComposedChart data={days}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 10 }} interval={4} />
            <YAxis yAxisId="vol" tick={{ fill: '#64748b', fontSize: 10 }} />
            <YAxis yAxisId="pct" orientation="right" domain={[0, 100]} tick={{ fill: '#64748b', fontSize: 10 }} tickFormatter={v => `${v}%`} />
            <RechartsTooltip content={customTooltip} />
            <Bar yAxisId="vol" dataKey="volume" name="Total" fill="#334155" radius={[2, 2, 0, 0]} />
            <Bar yAxisId="vol" dataKey="completed" name="Completed" fill={CHART_COLORS.green} fillOpacity={0.5} radius={[2, 2, 0, 0]} />
            <Line yAxisId="pct" dataKey="completion_pct" name="Completion %" stroke={CHART_COLORS.green} strokeWidth={2} dot={false} unit="%" />
          </ComposedChart>
        </TrendChart>

        <TrendChart title="Auto Dispatch %"
          tip="% of all calls (Fleet + Towbook) dispatched without a human reassignment.\nManual = SA was assigned 2+ times AND a human dispatcher was involved in the reassignment.\nSingle-assignment calls (even if created by a human) count as Auto.\nTarget: 60%+. Higher = more efficient operation.">
          <ComposedChart data={days}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 10 }} interval={4} />
            <YAxis domain={[0, 100]} tick={{ fill: '#64748b', fontSize: 10 }} tickFormatter={v => `${v}%`} />
            <RechartsTooltip content={customTooltip} />
            <Area dataKey="auto_pct" name="Auto %" stroke={CHART_COLORS.blue} fill={CHART_COLORS.blue} fillOpacity={0.1} strokeWidth={2} dot={false} unit="%" />
            <Line dataKey={() => 60} name="Target" stroke="#475569" strokeDasharray="5 5" strokeWidth={1} dot={false} />
          </ComposedChart>
        </TrendChart>
      </div>

      {/* Row 2: SLA % | Response Time */}
      <div className="grid grid-cols-2 gap-4">
        <TrendChart title="45-min SLA Hit Rate"
          tip="% of Fleet calls where the driver arrived within 45 minutes.\nFleet only — Towbook uses SAHistory for arrival time (less consistent for SLA tracking).\nTarget: AAA accreditation standard.">
          <ComposedChart data={days}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 10 }} interval={4} />
            <YAxis domain={[0, 100]} tick={{ fill: '#64748b', fontSize: 10 }} tickFormatter={v => `${v}%`} />
            <RechartsTooltip content={customTooltip} />
            <Area dataKey="sla_pct" name="SLA %" stroke={CHART_COLORS.green} fill={CHART_COLORS.green} fillOpacity={0.1} strokeWidth={2} dot={false} unit="%" />
          </ComposedChart>
        </TrendChart>

        <TrendChart title="Avg Response Time (ATA)"
          tip="Average minutes from call creation to driver arriving on scene.\nBlue = Fleet (ActualStartTime, reliable).\nAmber = Towbook (SAHistory 'On Location' timestamp).\nGuardrail: 0-480 min, excludes outliers.">
          <ComposedChart data={days}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 10 }} interval={4} />
            <YAxis tick={{ fill: '#64748b', fontSize: 10 }} tickFormatter={v => `${v}m`} />
            <RechartsTooltip content={customTooltip} />
            <Line dataKey="fleet_ata" name="Fleet" stroke={CHART_COLORS.blue} strokeWidth={2} dot={false} unit=" min" />
            <Line dataKey="towbook_ata" name="Towbook" stroke={CHART_COLORS.amber} strokeWidth={2} dot={false} unit=" min" />
            <Line dataKey={() => 45} name="45-min target" stroke="#475569" strokeDasharray="5 5" strokeWidth={1} dot={false} />
          </ComposedChart>
        </TrendChart>
      </div>

      {/* Row 3: Reassignments | Satisfaction */}
      <div className="grid grid-cols-2 gap-4">
        <TrendChart title="Reassignments / Day"
          tip="Number of driver/garage reassignment changes per day.\nSource: SAHistory ERS_Assigned_Resource__c changes (deduplicated).\nHigh count = calls bouncing, garages declining, longer member wait times.\nLower is better — means calls get accepted on first try.">
          <ComposedChart data={days}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 10 }} interval={4} />
            <YAxis tick={{ fill: '#64748b', fontSize: 10 }} />
            <RechartsTooltip content={customTooltip} />
            <Bar dataKey="reassignments" name="Reassignments" fill={CHART_COLORS.red} fillOpacity={0.6} radius={[2, 2, 0, 0]} />
          </ComposedChart>
        </TrendChart>

        <TrendChart title="Member Satisfaction"
          tip="% of survey respondents who selected 'Totally Satisfied'.\nSurveys arrive days after the call, so recent days may have fewer responses.\nShown as 7-day rolling average to smooth the lag.\nTarget: ~82% (accreditation standard).">
          <ComposedChart data={days}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 10 }} interval={4} />
            <YAxis domain={[0, 100]} tick={{ fill: '#64748b', fontSize: 10 }} tickFormatter={v => `${v}%`} />
            <RechartsTooltip content={customTooltip} />
            <Area dataKey="satisfaction_pct" name="Totally Satisfied %" stroke={CHART_COLORS.purple} fill={CHART_COLORS.purple} fillOpacity={0.1} strokeWidth={2} dot={false} unit="%" connectNulls />
          </ComposedChart>
        </TrendChart>
      </div>

      {/* Monthly Summary Table */}
      {monthlyData.length > 0 && (
        <div className="glass rounded-xl border border-slate-700/30 p-4">
          <div className="text-xs font-bold text-white uppercase tracking-wide mb-3">Monthly Summary</div>
          <div className="overflow-x-auto">
            <table className="w-full text-[10px]">
              <thead>
                <tr className="text-slate-500 border-b border-slate-700/50">
                  <th className="text-left pb-2 pr-4 font-medium">Month</th>
                  <th className="text-right pb-2 px-2 font-medium">Days</th>
                  <th className="text-right pb-2 px-2 font-medium">Calls</th>
                  <th className="text-right pb-2 px-2 font-medium">Completed</th>
                  <th className="text-right pb-2 px-2 font-medium">Complt%</th>
                  <th className="text-right pb-2 px-2 font-medium">Auto%</th>
                  <th className="text-right pb-2 px-2 font-medium">SLA%</th>
                  <th className="text-right pb-2 px-2 font-medium">Fleet ATA</th>
                  <th className="text-right pb-2 px-2 font-medium">TB ATA</th>
                  <th className="text-right pb-2 px-2 font-medium">Reassign</th>
                  <th className="text-right pb-2 pl-2 font-medium">Satisf%</th>
                </tr>
              </thead>
              <tbody>
                {monthlyData.map((m, i) => {
                  const fmt1 = v => v != null ? v.toFixed(1) : '—'
                  const fmt0 = v => v != null ? Math.round(v) : '—'
                  const isLast = i === monthlyData.length - 1
                  return (
                    <tr key={m.label} className={clsx('border-b border-slate-800/40 hover:bg-slate-800/20', isLast && 'text-slate-200')}>
                      <td className="py-1.5 pr-4 text-slate-300 font-medium whitespace-nowrap">{m.label}</td>
                      <td className="py-1.5 px-2 text-right text-slate-500">{m.days}</td>
                      <td className="py-1.5 px-2 text-right text-slate-300">{m.vol.toLocaleString()}</td>
                      <td className="py-1.5 px-2 text-right text-slate-400">{m.completed.toLocaleString()}</td>
                      <td className="py-1.5 px-2 text-right text-emerald-400">{fmt1(m.completion)}%</td>
                      <td className="py-1.5 px-2 text-right text-blue-400">{fmt1(m.auto)}%</td>
                      <td className="py-1.5 px-2 text-right text-green-400">{fmt1(m.sla)}%</td>
                      <td className="py-1.5 px-2 text-right text-blue-300">{fmt0(m.fleet_ata)}m</td>
                      <td className="py-1.5 px-2 text-right text-amber-400">{fmt0(m.towbook_ata)}m</td>
                      <td className="py-1.5 px-2 text-right text-red-400">{m.reassignments.toLocaleString()}</td>
                      <td className="py-1.5 pl-2 text-right text-purple-400">{fmt1(m.satisfaction)}%</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Row 4: Top & Bottom Garages */}
      {(trends.top_garages?.length > 0 || trends.bottom_garages?.length > 0) && (
        <div className="grid grid-cols-2 gap-4">
          {trends.top_garages?.length > 0 && (
            <div className="glass rounded-xl border border-slate-700/30 p-4">
              <div className="flex items-center gap-2 mb-3">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                <span className="text-xs font-bold text-white uppercase tracking-wide">Top Garages (30d)</span>
                <InfoTip text="Best garages by response time (ATA) with >85% completion rate.\nMinimum 20 calls to qualify." />
              </div>
              <div className="space-y-1.5">
                {trends.top_garages.map((g, i) => (
                  <div key={i} className="flex items-center gap-2 text-[10px] bg-emerald-950/20 rounded px-3 py-1.5">
                    <span className="text-emerald-400 font-bold w-4">#{i + 1}</span>
                    <span className="text-slate-300 flex-1 truncate" title={g.name}>{g.name}</span>
                    <span className="text-emerald-400 font-semibold">{g.ata}m</span>
                    <span className="text-slate-500">{g.completion_pct}%</span>
                    <span className="text-slate-600">{g.volume} calls</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {trends.bottom_garages?.length > 0 && (
            <div className="glass rounded-xl border border-slate-700/30 p-4">
              <div className="flex items-center gap-2 mb-3">
                <AlertTriangle className="w-4 h-4 text-red-400" />
                <span className="text-xs font-bold text-white uppercase tracking-wide">Needs Improvement (30d)</span>
                <InfoTip text="Garages with highest response times or lowest completion rates.\nMinimum 20 calls to qualify." />
              </div>
              <div className="space-y-1.5">
                {trends.bottom_garages.map((g, i) => (
                  <div key={i} className="flex items-center gap-2 text-[10px] bg-red-950/20 rounded px-3 py-1.5">
                    <span className="text-red-400 font-bold w-4">#{i + 1}</span>
                    <span className="text-slate-300 flex-1 truncate" title={g.name}>{g.name}</span>
                    <span className="text-red-400 font-semibold">{g.ata}m</span>
                    <span className="text-slate-500">{g.completion_pct}%</span>
                    <span className="text-slate-600">{g.volume} calls</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      <div className="text-[10px] text-slate-600 text-center">
        Refreshes nightly at 12:05 AM ET
      </div>
    </div>
  )
}

export function MonthTrendsView({ month }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [refreshing, setRefreshing] = useState(false)
  const retryRef = useRef(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    fetchMonthTrends(month)
      .then(res => {
          if (res?.loading) {
            // Backend is generating — auto-retry in 10s
            setData(null)
            setLoading(false)
            retryRef.current = setTimeout(() => load(), 10000)
          } else {
            setData(res)
            setLoading(false)
          }
        })
        .catch(e => {
            setError(e.response?.data?.detail || e.message || 'Failed to load')
            setLoading(false)
        })
  }, [month])

  useEffect(() => {
    let cancelled = false
    if (retryRef.current) clearTimeout(retryRef.current)
    const wrapped = () => { if (!cancelled) load() }
    wrapped()
    return () => { cancelled = true; if (retryRef.current) clearTimeout(retryRef.current) }
  }, [load])

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      await refreshMonthTrends(month)
      // Backend clears cache and starts regeneration — poll until ready
      const poll = () => {
        fetchMonthTrends(month).then(res => {
          if (res?.loading) {
            retryRef.current = setTimeout(poll, 5000)
          } else {
            setData(res)
            setRefreshing(false)
          }
        }).catch(() => setRefreshing(false))
      }
      retryRef.current = setTimeout(poll, 3000)
    } catch {
      setRefreshing(false)
    }
  }

  const monthLabel = (() => {
    const [y, m] = month.split('-')
    return new Date(+y, +m - 1, 2).toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
  })()

  if (loading) return (
    <div className="max-w-5xl mx-auto flex items-center justify-center py-20">
      <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
      <span className="ml-2 text-sm text-slate-500">Loading {monthLabel}...</span>
    </div>
  )
  if (error) return <div className="max-w-5xl mx-auto text-center text-red-400 py-10 text-sm">{error}</div>
  if (!data?.days?.length) return (
    <div className="max-w-5xl mx-auto text-center py-10">
      <Loader2 className="w-5 h-5 animate-spin text-blue-500 mx-auto mb-2" />
      <div className="text-sm text-slate-500">Generating {monthLabel} data in the background...</div>
      <div className="text-xs text-slate-600 mt-1">This takes about 1 minute. You can navigate to other screens — data will be ready when you come back.</div>
      <div className="text-[10px] text-slate-700 mt-2">Auto-checking every 10 seconds</div>
    </div>
  )

  const days = data.days.map(d => ({ ...d, label: d.date.slice(8) })) // day of month "01", "02"

  // Aggregate summary for the month
  const summary = (() => {
    const ds = data.days
    const vol = ds.reduce((s, d) => s + (d.volume || 0), 0)
    const completed = ds.reduce((s, d) => s + (d.completed || 0), 0)
    const avg = f => { const vs = ds.map(d => d[f]).filter(v => v != null && !isNaN(v)); return vs.length ? Math.round(vs.reduce((s, v) => s + v, 0) / vs.length) : null }
    return {
      vol, completed,
      completion: vol > 0 ? Math.round(100 * completed / vol) : null,
      auto: avg('auto_pct'), sla: avg('sla_pct'),
      fleet_ata: avg('fleet_ata'), towbook_ata: avg('towbook_ata'),
      reassignments: ds.reduce((s, d) => s + (d.reassignments || 0), 0),
      satisfaction: avg('satisfaction_pct'),
    }
  })()

  const customTooltip = ({ active, payload, label }) => {
    if (!active || !payload?.length) return null
    return (
      <div className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs shadow-xl">
        <div className="font-semibold text-slate-300 mb-1">Day {label}</div>
        {payload.map((p, i) => (
          <div key={i} className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: p.color }} />
            <span className="text-slate-400">{p.name}:</span>
            <span className="font-semibold text-white">{p.value != null ? (typeof p.value === 'number' && p.value % 1 !== 0 ? p.value.toFixed(1) : p.value) : '—'}{p.unit || ''}</span>
          </div>
        ))}
      </div>
    )
  }

  const fmt0 = v => v != null ? Math.round(v) : '—'

  return (
    <div className="max-w-5xl mx-auto space-y-4">

      {/* Header + Summary Stats */}
      <div className="flex items-center justify-between">
        <div className="text-xs text-slate-500">{monthLabel} · Excludes Tow Drop-Off</div>
        <div className="flex items-center gap-3">
          {refreshing && <span className="text-[10px] text-slate-500">Calculating in background — you can navigate away</span>}
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="flex items-center gap-1.5 text-xs text-slate-300 hover:text-white transition disabled:opacity-40 bg-slate-800 hover:bg-slate-700 px-3 py-1.5 rounded-lg border border-slate-700/50"
          >
            <RefreshCw className={clsx('w-3.5 h-3.5', refreshing && 'animate-spin')} />
            {refreshing ? 'Recalculating…' : 'Refresh Data'}
          </button>
        </div>
      </div>

      {/* Summary row */}
      <div className="grid grid-cols-5 gap-3">
        {[
          ['Calls', summary.vol?.toLocaleString(), 'text-slate-200'],
          ['Completion', summary.completion != null ? `${summary.completion}%` : '—', 'text-emerald-400'],
          ['Auto %', summary.auto != null ? `${summary.auto}%` : '—', 'text-blue-400'],
          ['Fleet ATA', summary.fleet_ata != null ? `${summary.fleet_ata}m` : '—', 'text-blue-300'],
          ['SLA %', summary.sla != null ? `${summary.sla}%` : '—', 'text-green-400'],
        ].map(([lbl, val, clr]) => (
          <div key={lbl} className="glass rounded-xl border border-slate-700/30 p-3 text-center">
            <div className="text-[9px] text-slate-500 uppercase tracking-wide mb-1">{lbl}</div>
            <div className={clsx('text-xl font-bold', clr)}>{val}</div>
          </div>
        ))}
      </div>

      {/* Row 1: Volume + Completion | Auto % */}
      <div className="grid grid-cols-2 gap-4">
        <TrendChart title="Daily Volume + Completion Rate"
          tip="Gray bars = total calls. Green bars = completed.\nGreen line = completion %.">
          <ComposedChart data={days}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 10 }} interval={2} />
            <YAxis yAxisId="vol" tick={{ fill: '#64748b', fontSize: 10 }} />
            <YAxis yAxisId="pct" orientation="right" domain={[0, 100]} tick={{ fill: '#64748b', fontSize: 10 }} tickFormatter={v => `${v}%`} />
            <RechartsTooltip content={customTooltip} />
            <Bar yAxisId="vol" dataKey="volume" name="Total" fill="#334155" radius={[2, 2, 0, 0]} />
            <Bar yAxisId="vol" dataKey="completed" name="Completed" fill={CHART_COLORS.green} fillOpacity={0.5} radius={[2, 2, 0, 0]} />
            <Line yAxisId="pct" dataKey="completion_pct" name="Completion %" stroke={CHART_COLORS.green} strokeWidth={2} dot={false} unit="%" />
          </ComposedChart>
        </TrendChart>

        <TrendChart title="Auto Dispatch %"
          tip="% of calls dispatched without a human reassignment.\nManual = SA was assigned 2+ times AND a human dispatcher was involved.\nTarget: 60%+.">
          <ComposedChart data={days}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 10 }} interval={2} />
            <YAxis domain={[0, 100]} tick={{ fill: '#64748b', fontSize: 10 }} tickFormatter={v => `${v}%`} />
            <RechartsTooltip content={customTooltip} />
            <Area dataKey="auto_pct" name="Auto %" stroke={CHART_COLORS.blue} fill={CHART_COLORS.blue} fillOpacity={0.1} strokeWidth={2} dot={false} unit="%" />
            <Line dataKey={() => 60} name="Target" stroke="#475569" strokeDasharray="5 5" strokeWidth={1} dot={false} />
          </ComposedChart>
        </TrendChart>
      </div>

      {/* Row 2: SLA % | ATA */}
      <div className="grid grid-cols-2 gap-4">
        <TrendChart title="45-min SLA Hit Rate"
          tip="% of Fleet calls where the driver arrived within 45 minutes.">
          <ComposedChart data={days}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 10 }} interval={2} />
            <YAxis domain={[0, 100]} tick={{ fill: '#64748b', fontSize: 10 }} tickFormatter={v => `${v}%`} />
            <RechartsTooltip content={customTooltip} />
            <Area dataKey="sla_pct" name="SLA %" stroke={CHART_COLORS.green} fill={CHART_COLORS.green} fillOpacity={0.1} strokeWidth={2} dot={false} unit="%" />
          </ComposedChart>
        </TrendChart>

        <TrendChart title="Avg Response Time (ATA)"
          tip="Blue = Fleet (ActualStartTime). Amber = Towbook (SAHistory 'On Location').">
          <ComposedChart data={days}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 10 }} interval={2} />
            <YAxis tick={{ fill: '#64748b', fontSize: 10 }} tickFormatter={v => `${v}m`} />
            <RechartsTooltip content={customTooltip} />
            <Line dataKey="fleet_ata" name="Fleet" stroke={CHART_COLORS.blue} strokeWidth={2} dot={false} unit=" min" />
            <Line dataKey="towbook_ata" name="Towbook" stroke={CHART_COLORS.amber} strokeWidth={2} dot={false} unit=" min" />
            <Line dataKey={() => 45} name="45-min target" stroke="#475569" strokeDasharray="5 5" strokeWidth={1} dot={false} />
          </ComposedChart>
        </TrendChart>
      </div>

      {/* Row 3: Reassignments | Satisfaction */}
      <div className="grid grid-cols-2 gap-4">
        <TrendChart title="Reassignments / Day"
          tip="Number of driver/garage reassignment changes per day.">
          <ComposedChart data={days}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 10 }} interval={2} />
            <YAxis tick={{ fill: '#64748b', fontSize: 10 }} />
            <RechartsTooltip content={customTooltip} />
            <Bar dataKey="reassignments" name="Reassignments" fill={CHART_COLORS.red} fillOpacity={0.6} radius={[2, 2, 0, 0]} />
          </ComposedChart>
        </TrendChart>

        <TrendChart title="Member Satisfaction"
          tip="% of survey respondents who selected 'Totally Satisfied'.">
          <ComposedChart data={days}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 10 }} interval={2} />
            <YAxis domain={[0, 100]} tick={{ fill: '#64748b', fontSize: 10 }} tickFormatter={v => `${v}%`} />
            <RechartsTooltip content={customTooltip} />
            <Area dataKey="satisfaction_pct" name="Totally Satisfied %" stroke={CHART_COLORS.purple} fill={CHART_COLORS.purple} fillOpacity={0.1} strokeWidth={2} dot={false} unit="%" connectNulls />
          </ComposedChart>
        </TrendChart>
      </div>

      {/* Top & Bottom Garages */}
      {(data.top_garages?.length > 0 || data.bottom_garages?.length > 0) && (
        <div className="grid grid-cols-2 gap-4">
          {data.top_garages?.length > 0 && (
            <div className="glass rounded-xl border border-slate-700/30 p-4">
              <div className="flex items-center gap-2 mb-3">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                <span className="text-xs font-bold text-white uppercase tracking-wide">Top Garages ({monthLabel})</span>
              </div>
              <div className="space-y-1.5">
                {data.top_garages.map((g, i) => (
                  <div key={i} className="flex items-center gap-2 text-[10px] bg-emerald-950/20 rounded px-3 py-1.5">
                    <span className="text-emerald-400 font-bold w-4">#{i + 1}</span>
                    <span className="text-slate-300 flex-1 truncate" title={g.name}>{g.name}</span>
                    <span className="text-emerald-400 font-semibold">{g.ata}m</span>
                    <span className="text-slate-500">{g.completion_pct}%</span>
                    <span className="text-slate-600">{g.volume} calls</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {data.bottom_garages?.length > 0 && (
            <div className="glass rounded-xl border border-slate-700/30 p-4">
              <div className="flex items-center gap-2 mb-3">
                <AlertTriangle className="w-4 h-4 text-red-400" />
                <span className="text-xs font-bold text-white uppercase tracking-wide">Needs Improvement ({monthLabel})</span>
              </div>
              <div className="space-y-1.5">
                {data.bottom_garages.map((g, i) => (
                  <div key={i} className="flex items-center gap-2 text-[10px] bg-red-950/20 rounded px-3 py-1.5">
                    <span className="text-red-400 font-bold w-4">#{i + 1}</span>
                    <span className="text-slate-300 flex-1 truncate" title={g.name}>{g.name}</span>
                    <span className="text-red-400 font-semibold">{g.ata}m</span>
                    <span className="text-slate-500">{g.completion_pct}%</span>
                    <span className="text-slate-600">{g.volume} calls</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
