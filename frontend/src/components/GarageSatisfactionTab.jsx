/**
 * GarageSatisfactionTab.jsx — "Satisfaction" tab in Garage Dashboard.
 *
 * Mirrors the overall SatisfactionView pattern (month pills, trend chart,
 * daily breakdown, day drill-down) but scoped to a single garage passed in
 * via prop. Adds a per-driver performance section powered by the new
 * `drivers` array returned by /api/insights/satisfaction/garage/{name}.
 */
import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { clsx } from 'clsx'
import { Loader2, AlertTriangle, ArrowLeft, ChevronRight, MessageSquare, ChevronUp, ChevronDown } from 'lucide-react'
import { ComposedChart, Bar, Line, XAxis, YAxis, Tooltip as RechartsTooltip, CartesianGrid, Legend } from 'recharts'
import { fetchSatisfactionGarage, fetchSatisfactionDetail, fetchSatisfactionDetailAI } from '../api'
import { TrendChart } from './CommandCenterUtils'

const satColor = (pct) => pct == null ? 'text-slate-400'
  : pct >= 82 ? 'text-emerald-400'
  : pct >= 70 ? 'text-amber-400'
  : 'text-red-400'

// ── Survey badges (reused by GarageDayDetail inline) ─────────────────────────
function SatBadge({ val }) {
  if (!val) return null
  const v = val.toLowerCase()
  const color = v === 'totally satisfied' ? 'bg-emerald-950/50 text-emerald-400 border-emerald-800/30' :
                v === 'satisfied' ? 'bg-green-950/50 text-green-400 border-green-800/30' :
                v.includes('neither') ? 'bg-slate-800 text-slate-400 border-slate-700/30' :
                v === 'dissatisfied' ? 'bg-amber-950/50 text-amber-400 border-amber-800/30' :
                'bg-red-950/50 text-red-400 border-red-800/30'
  return <span className={clsx('text-[9px] px-1.5 py-0.5 rounded border font-medium', color)}>{val}</span>
}

// ── Main component ──────────────────────────────────────────────────────────
export default function GarageSatisfactionTab({ garageName, onBack, initialMonth }) {
  const now = new Date()
  const currentMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
  const [month, setMonth] = useState(initialMonth || currentMonth)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedDay, setSelectedDay] = useState(null)
  const retryRef = useRef(null)

  const [generating, setGenerating] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    fetchSatisfactionGarage(garageName, month)
      .then(res => {
        if (res?.loading) {
          setData(null)
          setGenerating(true)
          setLoading(false)
          retryRef.current = setTimeout(load, 6000)
        } else {
          setData(res)
          setGenerating(false)
          setLoading(false)
        }
      })
      .catch(e => {
        setError(e.response?.data?.detail || e.message || 'Failed to load')
        setGenerating(false)
        setLoading(false)
      })
  }, [garageName, month])

  useEffect(() => {
    setSelectedDay(null)
    setGenerating(false)
    if (retryRef.current) clearTimeout(retryRef.current)
    load()
    return () => { if (retryRef.current) clearTimeout(retryRef.current) }
  }, [load])

  const monthLabel = (() => {
    const [y, m] = month.split('-')
    return new Date(+y, +m - 1, 2).toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
  })()

  // Month pills — Jan → current month (same pattern as SatisfactionView)
  const monthPills = (() => {
    const pills = []
    for (let m = 0; m <= now.getMonth(); m++) {
      const key = `${now.getFullYear()}-${String(m + 1).padStart(2, '0')}`
      const label = new Date(now.getFullYear(), m, 1).toLocaleDateString('en-US', { month: 'short' })
      pills.push({ key, label })
    }
    return pills
  })()

  const MonthBar = () => (
    <div className="flex items-center gap-1">
      <span className="text-[10px] text-slate-600 mr-1">{now.getFullYear()}</span>
      {monthPills.map(p => (
        <button key={p.key} onClick={() => setMonth(p.key)}
          className={clsx('px-3 py-1 rounded-md text-[11px] font-medium transition-all',
            month === p.key
              ? 'bg-violet-600/20 text-violet-400 border border-violet-500/30'
              : 'text-slate-600 hover:text-slate-300 hover:bg-slate-800/40'
          )}>{p.label}</button>
      ))}
    </div>
  )

  // ── Day drill-down (same pattern as SatisfactionGarageDetail) ──
  if (selectedDay) {
    return <GarageDayDetail garage={garageName} date={selectedDay} onBack={() => setSelectedDay(null)} />
  }

  if (loading) return (
    <div className="space-y-4">
      <MonthBar />
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
        <span className="ml-2 text-sm text-slate-500">Loading satisfaction data...</span>
      </div>
    </div>
  )
  if (error) return (
    <div className="space-y-4">
      <MonthBar />
      <div className="text-center text-red-400 py-10 text-sm">{error}</div>
    </div>
  )
  if (generating || (!data && !error)) return (
    <div className="space-y-4">
      <MonthBar />
      <div className="text-center py-10">
        <Loader2 className="w-5 h-5 animate-spin text-blue-500 mx-auto mb-2" />
        <div className="text-sm text-slate-500">Generating satisfaction data for {monthLabel}...</div>
        <div className="text-xs text-slate-600 mt-1">Auto-checking every 6 seconds</div>
      </div>
    </div>
  )
  if (!data?.daily?.length) return (
    <div className="space-y-4">
      <MonthBar />
      <div className="text-center py-10">
        <AlertTriangle className="w-6 h-6 text-slate-600 mx-auto mb-2" />
        <div className="text-sm text-slate-400">No satisfaction surveys yet for {monthLabel}</div>
        <div className="text-xs text-slate-600 mt-1">Surveys typically arrive 1-3 days after the call</div>
      </div>
    </div>
  )

  const s = data.summary || {}
  const daily = (data.daily || []).map(d => ({ ...d, label: d.date.slice(8) }))
  const drivers = data.drivers || []

  return (
    <div className="space-y-4">
      {/* Month pills */}
      <MonthBar />

      {/* Summary cards */}
      <div className="grid grid-cols-4 gap-3">
        {[
          ['Totally Satisfied', s.totally_satisfied_pct != null ? `${s.totally_satisfied_pct}%` : '--', satColor(s.totally_satisfied_pct), '82% target', s.totally_satisfied_pct != null && s.totally_satisfied_pct < 82],
          ['Response Time Sat', s.response_time_pct != null ? `${s.response_time_pct}%` : '--', satColor(s.response_time_pct), null, s.response_time_pct != null && s.response_time_pct < 82],
          ['Avg ATA', s.avg_ata != null ? `${s.avg_ata}m` : '--', s.avg_ata != null && s.avg_ata <= 45 ? 'text-emerald-400' : 'text-amber-400', null, false],
          ['Total Surveys', s.total_surveys?.toLocaleString() || '0', 'text-slate-200', null, false],
        ].map(([lbl, val, clr, sub, belowTarget]) => (
          <div key={lbl} className={clsx('glass rounded-xl border p-3 text-center relative',
            belowTarget ? 'border-red-500/40' : 'border-slate-700/30'
          )}>
            {belowTarget && <span className="absolute top-2 right-2 w-2.5 h-2.5 rounded-full bg-red-500 animate-pulse" title="Below 82% target" />}
            <div className="text-[9px] text-slate-500 uppercase tracking-wide mb-1">{lbl}</div>
            <div className={clsx('text-xl font-bold', clr)}>{val}</div>
            {sub && <div className="text-[9px] text-slate-600 mt-0.5">{sub}</div>}
          </div>
        ))}
      </div>

      {/* Garage-level insights */}
      {data.insights?.length > 0 && (
        <div className="space-y-1">
          {data.insights.map((ins, i) => (
            <div key={i} className={clsx('text-xs px-3 py-2 rounded-lg border',
              ins.type === 'critical' ? 'bg-red-950/20 border-red-800/30 text-red-400' :
              ins.type === 'warning' ? 'bg-amber-950/20 border-amber-800/30 text-amber-400' :
              ins.type === 'success' ? 'bg-emerald-950/20 border-emerald-800/30 text-emerald-400' :
              'bg-slate-800/30 border-slate-700/30 text-slate-400'
            )}>
              <span className="mr-1.5">{ins.icon}</span>{ins.text}
            </div>
          ))}
        </div>
      )}

      {/* Trend chart — 4 satisfaction scores + SA count bars */}
      <TrendChart title={`Daily Satisfaction — ${monthLabel}`}
        tip="Click any day to drill down into driver performance and customer feedback."
        aspect={2.8}>
        <ComposedChart data={daily} onClick={(e) => {
          if (e?.activePayload?.[0]?.payload?.date) setSelectedDay(e.activePayload[0].payload.date)
        }} style={{ cursor: 'pointer' }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 10 }} interval={2} />
          <YAxis yAxisId="pct" domain={[0, 100]} tick={{ fill: '#64748b', fontSize: 10 }} tickFormatter={v => `${v}%`}
            label={{ value: 'Totally Satisfied %', angle: -90, position: 'insideLeft', offset: 5, fill: '#64748b', fontSize: 9 }} />
          <YAxis yAxisId="count" orientation="right" tick={{ fill: '#64748b', fontSize: 10 }}
            label={{ value: 'Number of SAs', angle: 90, position: 'insideRight', offset: 5, fill: '#64748b', fontSize: 9 }} />
          <Legend wrapperStyle={{ fontSize: 10, paddingTop: 8 }} iconSize={12} />
          <RechartsTooltip content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null
            const entry = payload[0]?.payload
            return (
              <div className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs shadow-xl">
                <div className="font-semibold text-slate-300 mb-1">Day {label}</div>
                {payload.filter(p => p.value != null).map((p, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: p.color }} />
                    <span className="text-slate-400">{p.name}:</span>
                    <span className="font-semibold text-white">{typeof p.value === 'number' ? Math.round(p.value) : p.value}{p.unit || ''}</span>
                  </div>
                ))}
                <div className="text-[9px] text-slate-500 mt-1 border-t border-slate-800 pt-1">Click to analyze this day</div>
              </div>
            )
          }} />
          <Bar yAxisId="count" dataKey="sa_count" name="SAs" fill="#334155" fillOpacity={0.5} radius={[2, 2, 0, 0]} />
          <Line yAxisId="pct" dataKey="totally_satisfied_pct" name="Overall %" stroke="#a855f7" strokeWidth={2.5} dot={{ r: 3, fill: '#a855f7' }} activeDot={{ r: 5, stroke: '#fff', strokeWidth: 2 }} unit="%" />
          <Line yAxisId="pct" dataKey="technician_pct" name="Technician %" stroke="#22c55e" strokeWidth={2} dot={false} unit="%" connectNulls />
          <Line yAxisId="pct" dataKey="response_time_pct" name="Response Time %" stroke="#3b82f6" strokeWidth={2} dot={false} unit="%" connectNulls />
          <Line yAxisId="pct" dataKey="kept_informed_pct" name="Kept Informed %" stroke="#f59e0b" strokeWidth={2} dot={false} unit="%" connectNulls />
          <Line yAxisId="pct" dataKey={() => 82} name="Target (82%)" stroke="#475569" strokeDasharray="5 5" strokeWidth={1} dot={false} legendType="none" />
        </ComposedChart>
      </TrendChart>

      {/* Driver performance section — sortable table */}
      {drivers.length > 0 && <DriverTable drivers={drivers} />}

      {/* Daily rows */}
      <div className="glass rounded-xl border border-slate-700/30 p-4">
        <div className="text-xs font-bold text-white uppercase tracking-wide mb-3">Daily Breakdown</div>
        <div className="space-y-1">
          {(data.daily || []).map(d => {
            const hasSurveys = d.surveys > 0
            return (
              <button key={d.date} onClick={() => hasSurveys && setSelectedDay(d.date)}
                disabled={!hasSurveys}
                className={clsx('w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left text-[11px]',
                  hasSurveys ? 'hover:bg-slate-800/60 transition-all group cursor-pointer' : 'opacity-50 cursor-default'
                )}>
                <span className={clsx('w-2 h-2 rounded-full flex-shrink-0',
                  d.totally_satisfied_pct != null && d.totally_satisfied_pct >= 82 ? 'bg-emerald-500' :
                  d.totally_satisfied_pct != null ? 'bg-red-500' : 'bg-slate-700'
                )} />
                <span className="text-slate-500 font-mono w-16">{d.date}</span>
                <span className={clsx('font-bold w-10 text-right', satColor(d.totally_satisfied_pct))}>
                  {d.totally_satisfied_pct != null ? `${d.totally_satisfied_pct}%` : '--'}
                </span>
                {d.avg_ata != null && <span className={clsx('w-12', d.avg_ata <= 45 ? 'text-cyan-400' : 'text-amber-400')}>{d.avg_ata}m ATA</span>}
                {d.pta_miss_pct != null && <span className={clsx('w-16', d.pta_miss_pct > 30 ? 'text-red-400' : 'text-slate-500')}>{d.pta_miss_pct}% PTA miss</span>}
                <span className="text-slate-600 w-16">{d.surveys} surveys</span>
                <div className="flex-1 flex items-center gap-1 justify-end">
                  {d.insights?.map((ins, j) => (
                    <span key={j} className={clsx('text-[9px] px-1.5 py-0.5 rounded-full',
                      ins.type === 'critical' ? 'bg-red-950/50 text-red-400' :
                      ins.type === 'warning' ? 'bg-amber-950/50 text-amber-400' :
                      ins.type === 'success' ? 'bg-emerald-950/50 text-emerald-400' :
                      'bg-slate-800 text-slate-400'
                    )}>{ins.icon}</span>
                  ))}
                </div>
                {hasSurveys && <ChevronRight className="w-3.5 h-3.5 text-slate-700 group-hover:text-slate-400 transition" />}
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ── Sortable driver table with 4 sat dimensions ────────────────────────────
const DRIVER_COLS = [
  { key: 'name',                 label: 'Driver',          align: 'left',  fmt: v => v || '—' },
  { key: 'sa_count',             label: 'SAs',             align: 'right', fmt: v => v || '—' },
  { key: 'surveys',              label: 'Surveys',         align: 'right', fmt: v => v || '—' },
  { key: 'totally_satisfied_pct', label: 'Overall %',      align: 'right', fmt: v => v != null ? `${v}%` : '—', color: satColor },
  { key: 'technician_pct',       label: 'Technician %',    align: 'right', fmt: v => v != null ? `${v}%` : '—', color: satColor },
  { key: 'response_time_pct',    label: 'Response Time %', align: 'right', fmt: v => v != null ? `${v}%` : '—', color: satColor },
  { key: 'kept_informed_pct',    label: 'Kept Informed %', align: 'right', fmt: v => v != null ? `${v}%` : '—', color: satColor },
]

function DriverTable({ drivers }) {
  const [sortKey, setSortKey] = useState('totally_satisfied_pct')
  const [sortAsc, setSortAsc] = useState(false)

  const sorted = useMemo(() => {
    return [...drivers].sort((a, b) => {
      const av = a[sortKey], bv = b[sortKey]
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      if (typeof av === 'string') return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av)
      return sortAsc ? av - bv : bv - av
    })
  }, [drivers, sortKey, sortAsc])

  const handleSort = (key) => {
    if (sortKey === key) setSortAsc(!sortAsc)
    else { setSortKey(key); setSortAsc(false) }
  }

  const SortIcon = ({ col }) => {
    if (sortKey !== col) return null
    return sortAsc
      ? <ChevronUp className="w-3 h-3 inline ml-0.5" />
      : <ChevronDown className="w-3 h-3 inline ml-0.5" />
  }

  return (
    <div className="glass rounded-xl border border-slate-700/30 p-4">
      <div className="text-xs font-bold text-white uppercase tracking-wide mb-3">Driver Performance</div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-[9px] text-slate-500 uppercase tracking-wide border-b border-slate-800/80">
              {DRIVER_COLS.map(c => (
                <th key={c.key}
                  onClick={() => handleSort(c.key)}
                  className={clsx('py-2 px-2 font-medium cursor-pointer hover:text-slate-300 transition select-none whitespace-nowrap',
                    c.align === 'left' ? 'text-left' : 'text-right',
                    sortKey === c.key && 'text-blue-400')}>
                  {c.label}<SortIcon col={c.key} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map(d => {
              const flagged = d.totally_satisfied_pct != null && d.totally_satisfied_pct < 82
              return (
                <tr key={d.driver_id} className={clsx(
                  'border-b border-slate-800/40 hover:bg-slate-800/40 transition',
                  flagged && 'bg-red-950/10'
                )}>
                  {DRIVER_COLS.map(c => {
                    const val = d[c.key]
                    const colorCls = c.color ? c.color(val) : (c.key === 'name' ? 'text-slate-200' : 'text-slate-400')
                    return (
                      <td key={c.key} className={clsx('py-2 px-2 whitespace-nowrap',
                        c.align === 'right' && 'text-right',
                        c.key.endsWith('_pct') && 'font-bold',
                        colorCls)}>
                        {c.fmt(val)}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="text-[9px] text-slate-600 mt-2">Click any column header to sort. Red rows = overall sat below 82%.</div>
    </div>
  )
}

// ── Day drill-down: operational context + individual surveys ───────────────
function GarageDayDetail({ garage, date, onBack }) {
  const [data, setData] = useState(null)
  const [aiSummary, setAiSummary] = useState(null)
  const [aiLoading, setAiLoading] = useState(true)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    setLoading(true)
    setAiSummary(null)
    setAiLoading(true)
    // Fetch data immediately
    fetchSatisfactionDetail(garage, date)
      .then(setData)
      .catch(e => setError(e.response?.data?.detail || e.message || 'Failed'))
      .finally(() => setLoading(false))
    // Fetch AI summary in parallel — doesn't block the page
    fetchSatisfactionDetailAI(garage, date)
      .then(r => setAiSummary(r?.ai_summary || null))
      .catch(() => {})
      .finally(() => setAiLoading(false))
  }, [garage, date])

  if (loading) return (
    <div className="flex items-center justify-center py-20">
      <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
      <span className="ml-2 text-sm text-slate-500">Loading day analysis...</span>
    </div>
  )
  if (error) return <div className="text-center text-red-400 py-10 text-sm">{error}</div>

  const surveys = data?.surveys || []
  const drivers = data?.drivers || []
  const s = data?.summary || {}
  const insights = data?.insights || []

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="p-1.5 rounded-lg hover:bg-slate-800/60 transition text-slate-400 hover:text-white">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div>
          <div className="text-sm font-bold text-white">{date} — Day Analysis</div>
          <div className="text-[10px] text-slate-500">
            {s.sa_completed != null ? `${s.sa_completed} SAs completed · ` : ''}{surveys.length} survey{surveys.length !== 1 ? 's' : ''}
          </div>
        </div>
      </div>

      {/* AI Executive Summary — loads async, doesn't block the page */}
      <div className="glass rounded-xl border border-blue-500/20 p-5">
        <div className="text-[10px] text-blue-400 uppercase tracking-wide font-bold mb-3">Executive Summary</div>
        {aiLoading ? (
          <div className="flex items-center gap-2 py-3">
            <Loader2 className="w-4 h-4 animate-spin text-blue-400" />
            <span className="text-xs text-slate-500">Generating AI analysis...</span>
          </div>
        ) : aiSummary ? (
          <div className="text-[13px] text-slate-300 leading-relaxed ai-summary"
            dangerouslySetInnerHTML={{ __html: aiSummary }} />
        ) : (
          <div className="text-xs text-slate-600">AI summary not available</div>
        )}
      </div>

      {/* Day summary — what happened */}
      <div className="grid grid-cols-5 gap-3">
        {[
          ['Totally Satisfied', s.totally_satisfied_pct != null ? `${s.totally_satisfied_pct}%` : '--', satColor(s.totally_satisfied_pct)],
          ['Response Time', s.response_time_pct != null ? `${s.response_time_pct}%` : '--', satColor(s.response_time_pct)],
          ['Avg ATA', s.avg_ata != null ? `${s.avg_ata}m` : '--', s.avg_ata != null && s.avg_ata <= 45 ? 'text-cyan-400' : 'text-amber-400'],
          ['PTA Miss', s.pta_miss_pct != null ? `${s.pta_miss_pct}%` : '--', s.pta_miss_pct != null && s.pta_miss_pct <= 30 ? 'text-slate-300' : 'text-red-400'],
          ['Completed SAs', s.sa_completed != null ? s.sa_completed.toLocaleString() : '--', 'text-slate-200'],
        ].map(([lbl, val, clr]) => (
          <div key={lbl} className="glass rounded-xl border border-slate-700/30 p-3 text-center">
            <div className="text-[9px] text-slate-500 uppercase tracking-wide mb-1">{lbl}</div>
            <div className={clsx('text-lg font-bold', clr)}>{val}</div>
          </div>
        ))}
      </div>

      {/* Narrative insights — "why was the score this way" */}
      {insights.length > 0 && (
        <div className="space-y-1">
          {insights.map((ins, i) => (
            <div key={i} className={clsx('text-xs px-3 py-2 rounded-lg border',
              ins.type === 'critical' ? 'bg-red-950/20 border-red-800/30 text-red-400' :
              ins.type === 'warning' ? 'bg-amber-950/20 border-amber-800/30 text-amber-400' :
              ins.type === 'success' ? 'bg-emerald-950/20 border-emerald-800/30 text-emerald-400' :
              'bg-slate-800/30 border-slate-700/30 text-slate-400'
            )}>
              <span className="mr-1.5">{ins.icon}</span>{ins.text}
            </div>
          ))}
        </div>
      )}

      {/* Per-driver on this day — same sortable table as monthly view */}
      {drivers.length > 0 && <DriverTable drivers={drivers} />}

      {/* Customer feedback */}
      <div className="glass rounded-xl border border-slate-700/30 p-4">
        <div className="text-xs font-bold text-white uppercase tracking-wide mb-3">Customer Feedback ({surveys.length})</div>
        {surveys.length === 0 ? (
          <div className="text-center text-sm text-slate-600 py-6">No surveys for this date</div>
        ) : (
          <div className="space-y-2">
            {surveys.map(sv => (
              <div key={sv.id} className="rounded-lg border border-slate-700/30 p-3 space-y-2 bg-slate-900/30">
                <div className="flex items-center gap-3 flex-wrap">
                  {sv.wo_number && <span className="text-[10px] text-slate-400 font-mono">WO {sv.wo_number}</span>}
                  {sv.driver_name && <span className="text-[10px] text-slate-500">· {sv.driver_name}</span>}
                  {sv.created && <span className="text-[10px] text-slate-600 ml-auto">{sv.created}</span>}
                </div>
                <div className="flex items-center gap-3 flex-wrap">
                  <div className="text-[10px] text-slate-500">Overall: <SatBadge val={sv.overall} /></div>
                  <div className="text-[10px] text-slate-500">Response Time: <SatBadge val={sv.response_time} /></div>
                  <div className="text-[10px] text-slate-500">Technician: <SatBadge val={sv.technician} /></div>
                </div>
                {sv.comment && (
                  <div className="flex items-start gap-2 mt-1">
                    <MessageSquare className="w-3 h-3 text-slate-600 mt-0.5 flex-shrink-0" />
                    <div className="text-xs text-slate-400 italic leading-relaxed">"{sv.comment}"</div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
