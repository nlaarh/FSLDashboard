import React, { useState, useEffect, useCallback, useRef } from 'react'
import { clsx } from 'clsx'
import { Loader2, ArrowLeft, ChevronRight, MessageSquare, Clock } from 'lucide-react'
import { ComposedChart, Line, XAxis, YAxis, Tooltip as RechartsTooltip, CartesianGrid, Area } from 'recharts'
import { fetchSatisfactionGarage, fetchSatisfactionDetail } from '../api'
import SALink from '../components/SALink'
import { TrendChart } from './CommandCenterUtils'

// ── Garage Detail (monthly view with daily breakdown) ────────────────────────

export default function SatisfactionGarageDetail({ garage, month, onBack }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedDay, setSelectedDay] = useState(null)
  const retryRef = useRef(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    fetchSatisfactionGarage(garage, month)
      .then(res => {
        if (res?.loading) {
          setData(null)
          setLoading(false)
          retryRef.current = setTimeout(load, 6000)
        } else {
          setData(res)
          setLoading(false)
        }
      })
      .catch(e => {
        setError(e.response?.data?.detail || e.message || 'Failed')
        setLoading(false)
      })
  }, [garage, month])

  useEffect(() => {
    setSelectedDay(null)
    if (retryRef.current) clearTimeout(retryRef.current)
    load()
    return () => { if (retryRef.current) clearTimeout(retryRef.current) }
  }, [load])

  const monthLabel = (() => {
    const [y, m] = month.split('-')
    return new Date(+y, +m - 1, 2).toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
  })()

  if (selectedDay) {
    return <GarageDayDetail garage={garage} date={selectedDay} onBack={() => setSelectedDay(null)} />
  }

  if (loading) return (
    <div className="max-w-5xl mx-auto flex items-center justify-center py-20">
      <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
      <span className="ml-2 text-sm text-slate-500">Loading {garage}...</span>
    </div>
  )
  if (error) return <div className="max-w-5xl mx-auto text-center text-red-400 py-10 text-sm">{error}</div>
  if (!data?.daily?.length && !data?.loading) return (
    <div className="max-w-5xl mx-auto text-center py-10">
      <Loader2 className="w-5 h-5 animate-spin text-blue-500 mx-auto mb-2" />
      <div className="text-sm text-slate-500">Generating data for {garage}...</div>
      <div className="text-xs text-slate-600 mt-1">Auto-checking every 6 seconds</div>
    </div>
  )

  const s = data.summary || {}
  const daily = (data.daily || []).map(d => ({ ...d, label: d.date.slice(8) }))

  return (
    <div className="max-w-5xl mx-auto space-y-4">
      {/* Header with back button */}
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="p-1.5 rounded-lg hover:bg-slate-800/60 transition text-slate-400 hover:text-white">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div>
          <div className="text-sm font-bold text-white">{garage}</div>
          <div className="text-[10px] text-slate-500">{monthLabel} · Satisfaction Detail</div>
        </div>
      </div>

      {/* Summary row */}
      <div className="grid grid-cols-4 gap-3">
        {[
          ['Totally Satisfied', s.totally_satisfied_pct != null ? `${s.totally_satisfied_pct}%` : '--', s.totally_satisfied_pct != null && s.totally_satisfied_pct >= 82 ? 'text-emerald-400' : s.totally_satisfied_pct != null && s.totally_satisfied_pct >= 70 ? 'text-amber-400' : 'text-red-400'],
          ['Response Time', s.response_time_pct != null ? `${s.response_time_pct}%` : '--', 'text-blue-400'],
          ['Avg ATA', s.avg_ata != null ? `${s.avg_ata}m` : '--', s.avg_ata != null && s.avg_ata <= 45 ? 'text-emerald-400' : 'text-amber-400'],
          ['Surveys', s.total_surveys?.toLocaleString() || '0', 'text-slate-200'],
        ].map(([lbl, val, clr]) => (
          <div key={lbl} className="glass rounded-xl border border-slate-700/30 p-3 text-center">
            <div className="text-[9px] text-slate-500 uppercase tracking-wide mb-1">{lbl}</div>
            <div className={clsx('text-xl font-bold', clr)}>{val}</div>
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

      {/* Correlation chart: Satisfaction + ATA + PTA miss */}
      <TrendChart title="Satisfaction vs ATA Correlation" tip="Purple = Totally Satisfied %. Blue = Avg ATA (min). Red area = PTA miss %." aspect={2.5}>
        <ComposedChart data={daily}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 10 }} interval={2} />
          <YAxis yAxisId="pct" domain={[0, 100]} tick={{ fill: '#64748b', fontSize: 10 }} tickFormatter={v => `${v}%`} />
          <YAxis yAxisId="ata" orientation="right" tick={{ fill: '#64748b', fontSize: 10 }} tickFormatter={v => `${v}m`} />
          <RechartsTooltip content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null
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
              </div>
            )
          }} />
          <Area yAxisId="pct" dataKey="pta_miss_pct" name="PTA Miss" stroke="#ef4444" fill="#ef4444" fillOpacity={0.08} strokeWidth={1.5} dot={false} unit="%" />
          <Line yAxisId="pct" dataKey="totally_satisfied_pct" name="Totally Satisfied" stroke="#a855f7" strokeWidth={2.5} dot={false} unit="%" />
          <Line yAxisId="pct" dataKey="response_time_pct" name="RT Satisfaction" stroke="#3b82f6" strokeWidth={1.5} dot={false} strokeDasharray="4 2" unit="%" />
          <Line yAxisId="ata" dataKey="avg_ata" name="Avg ATA" stroke="#06b6d4" strokeWidth={2} dot={false} unit="m" />
          <Line yAxisId="pct" dataKey={() => 82} name="Target" stroke="#475569" strokeDasharray="5 5" strokeWidth={1} dot={false} />
        </ComposedChart>
      </TrendChart>

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
                <span className={clsx('font-bold w-10 text-right',
                  d.totally_satisfied_pct != null && d.totally_satisfied_pct >= 82 ? 'text-emerald-400' :
                  d.totally_satisfied_pct != null && d.totally_satisfied_pct >= 70 ? 'text-amber-400' :
                  d.totally_satisfied_pct != null ? 'text-red-400' : 'text-slate-600'
                )}>{d.totally_satisfied_pct != null ? `${d.totally_satisfied_pct}%` : '--'}</span>
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


// ── Garage Day Detail (individual survey list) ───────────────────────────────

function GarageDayDetail({ garage, date, onBack }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    setLoading(true)
    fetchSatisfactionDetail(garage, date)
      .then(setData)
      .catch(e => setError(e.response?.data?.detail || e.message || 'Failed'))
      .finally(() => setLoading(false))
  }, [garage, date])

  const satBadge = (val) => {
    if (!val) return null
    const v = val.toLowerCase()
    const color = v === 'totally satisfied' ? 'bg-emerald-950/50 text-emerald-400 border-emerald-800/30' :
                  v === 'satisfied' ? 'bg-green-950/50 text-green-400 border-green-800/30' :
                  v.includes('neither') ? 'bg-slate-800 text-slate-400 border-slate-700/30' :
                  v === 'dissatisfied' ? 'bg-amber-950/50 text-amber-400 border-amber-800/30' :
                  'bg-red-950/50 text-red-400 border-red-800/30'
    return <span className={clsx('text-[9px] px-1.5 py-0.5 rounded border font-medium', color)}>{val}</span>
  }

  if (loading) return (
    <div className="max-w-5xl mx-auto flex items-center justify-center py-20">
      <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
      <span className="ml-2 text-sm text-slate-500">Loading surveys...</span>
    </div>
  )
  if (error) return <div className="max-w-5xl mx-auto text-center text-red-400 py-10 text-sm">{error}</div>

  const surveys = data?.surveys || []

  return (
    <div className="max-w-5xl mx-auto space-y-4">
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="p-1.5 rounded-lg hover:bg-slate-800/60 transition text-slate-400 hover:text-white">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div>
          <div className="text-sm font-bold text-white">{garage} — {date}</div>
          <div className="text-[10px] text-slate-500">{surveys.length} survey{surveys.length !== 1 ? 's' : ''}</div>
        </div>
      </div>

      {surveys.length === 0 ? (
        <div className="text-center text-sm text-slate-600 py-10">No surveys for this date</div>
      ) : (
        <div className="space-y-2">
          {surveys.map(sv => (
            <div key={sv.id} className="glass rounded-xl border border-slate-700/30 p-4 space-y-2">
              {/* Header row */}
              <div className="flex items-center gap-3 flex-wrap">
                {sv.wo_number && <span className="text-[10px] text-slate-400 font-mono">WO {sv.wo_number}</span>}
                {sv.created && <span className="text-[10px] text-slate-600 ml-auto">{sv.created}</span>}
              </div>
              {/* Scores */}
              <div className="flex items-center gap-3 flex-wrap">
                <div className="text-[10px] text-slate-500">
                  Overall: {satBadge(sv.overall)}
                </div>
                <div className="text-[10px] text-slate-500">
                  Response Time: {satBadge(sv.response_time)}
                </div>
                <div className="text-[10px] text-slate-500">
                  Technician: {satBadge(sv.technician)}
                </div>
              </div>
              {/* Comment */}
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
  )
}
