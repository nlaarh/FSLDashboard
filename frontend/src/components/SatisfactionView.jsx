import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import ReactDOM from 'react-dom'
import { clsx } from 'clsx'
import { Loader2, RefreshCw, CheckCircle2, AlertTriangle, Clock, Users, ArrowRight, ArrowLeft, ChevronRight, Maximize2, X, MessageSquare, Star } from 'lucide-react'
import { ComposedChart, Bar, Line, XAxis, YAxis, Tooltip as RechartsTooltip, CartesianGrid, Area, Cell } from 'recharts'
import { MapContainer, TileLayer, CircleMarker, Tooltip, GeoJSON, useMap } from 'react-leaflet'
import { fetchSatisfactionOverview, refreshSatisfactionOverview, fetchMapGrids } from '../api'
import SALink from '../components/SALink'
import { InfoTip, TrendChart, CHART_COLORS } from './CommandCenterUtils'
import { getMapConfig } from '../mapStyles'
import SatisfactionDayDetail from './SatisfactionDayDetail'
import SatisfactionGarageDetail from './SatisfactionGarageDetail'

export default function SatisfactionView() {
  const now = new Date()
  const currentMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
  const [month, setMonth] = useState(currentMonth)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedGarage, setSelectedGarage] = useState(null)
  const [selectedDay, setSelectedDay] = useState(null)
  const [refreshing, setRefreshing] = useState(false)
  const retryRef = useRef(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    fetchSatisfactionOverview(month)
      .then(res => {
        if (res?.loading) {
          setData(null)
          setLoading(false)
          retryRef.current = setTimeout(load, 30000)
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
    setSelectedGarage(null)
    setSelectedDay(null)
    if (retryRef.current) clearTimeout(retryRef.current)
    load()
    return () => { if (retryRef.current) clearTimeout(retryRef.current) }
  }, [load])

  const monthLabel = (() => {
    const [y, m] = month.split('-')
    return new Date(+y, +m - 1, 2).toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
  })()

  // Month pills
  const monthPills = (() => {
    const pills = []
    for (let m = 0; m <= now.getMonth(); m++) {
      const key = `${now.getFullYear()}-${String(m + 1).padStart(2, '0')}`
      const label = new Date(now.getFullYear(), m, 1).toLocaleDateString('en-US', { month: 'short' })
      pills.push({ key, label })
    }
    return pills
  })()

  if (selectedDay) {
    return <SatisfactionDayDetail date={selectedDay} onBack={() => setSelectedDay(null)} onGarage={(g) => { setSelectedDay(null); setSelectedGarage(g) }} />
  }

  if (selectedGarage) {
    return <SatisfactionGarageDetail garage={selectedGarage} month={month} onBack={() => setSelectedGarage(null)} />
  }

  if (loading) return (
    <div className="max-w-5xl mx-auto flex items-center justify-center py-20">
      <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
      <span className="ml-2 text-sm text-slate-500">Loading satisfaction data...</span>
    </div>
  )
  if (error) return <div className="max-w-5xl mx-auto text-center text-red-400 py-10 text-sm">{error}</div>
  if (!data?.generated) return (
    <div className="max-w-5xl mx-auto text-center py-10">
      <Loader2 className="w-5 h-5 animate-spin text-blue-500 mx-auto mb-2" />
      <div className="text-sm text-slate-500">Generating satisfaction data for {monthLabel}...</div>
      <div className="text-xs text-slate-600 mt-1">Auto-checking every 30 seconds</div>
    </div>
  )
  if (!data?.daily_trend?.length) return (
    <div className="max-w-5xl mx-auto space-y-4">
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
      <div className="text-center py-10">
        <AlertTriangle className="w-6 h-6 text-slate-600 mx-auto mb-2" />
        <div className="text-sm text-slate-400">No satisfaction surveys yet for {monthLabel}</div>
        <div className="text-xs text-slate-600 mt-1">Surveys typically arrive 1-3 days after the call</div>
      </div>
    </div>
  )

  const s = data.summary || {}
  const trend = (data.daily_trend || []).map(d => ({ ...d, label: d.date.slice(8) }))
  const garages = data.all_garages || []
  const garagesWithSurveys = garages.filter(g => g.surveys > 0)
  const qualified = garages.filter(g => g.surveys >= 5)
  const unqualified = garages.filter(g => g.surveys < 5)

  const satColor = (pct) => pct >= 82 ? 'text-emerald-400' : pct >= 70 ? 'text-amber-400' : 'text-red-400'
  const satBg = (pct) => pct >= 82 ? 'bg-emerald-500' : pct >= 70 ? 'bg-amber-500' : 'bg-red-500'

  // Tier grouping for garage performance map
  const garagesWithScore = garagesWithSurveys.filter(g => g.totally_satisfied_pct != null)
  const tiers = {
    excellent: { label: 'Excellent', range: '90-100%', textCls: 'text-emerald-400', bg: 'bg-emerald-500', border: 'border-emerald-500/30', garages: garagesWithScore.filter(g => g.totally_satisfied_pct >= 90) },
    ok:        { label: 'On Target', range: '82-89%',  textCls: 'text-blue-400',    bg: 'bg-blue-500',    border: 'border-blue-500/30',    garages: garagesWithScore.filter(g => g.totally_satisfied_pct >= 82 && g.totally_satisfied_pct < 90) },
    below:     { label: 'Below Target', range: '60-81%', textCls: 'text-amber-400', bg: 'bg-amber-500',   border: 'border-amber-500/30',   garages: garagesWithScore.filter(g => g.totally_satisfied_pct >= 60 && g.totally_satisfied_pct < 82) },
    critical:  { label: 'Critical', range: '<60%',    textCls: 'text-red-400',     bg: 'bg-red-500',      border: 'border-red-500/30',     garages: garagesWithScore.filter(g => g.totally_satisfied_pct < 60) },
  }

  return (
    <div className="max-w-5xl mx-auto space-y-4">
      {/* Month selector + refresh button */}
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
        <button
          onClick={() => {
            setRefreshing(true)
            refreshSatisfactionOverview(month)
              .then(() => {
                setData(null)
                setLoading(true)
                const poll = setInterval(() => {
                  fetchSatisfactionOverview(month).then(d => {
                    if (d.daily_trend?.length > 0) {
                      clearInterval(poll)
                      setData(d)
                      setLoading(false)
                      setRefreshing(false)
                    }
                  }).catch(() => {})
                }, 10000)
                setTimeout(() => { clearInterval(poll); setRefreshing(false); setLoading(false) }, 180000)
              })
              .catch(() => setRefreshing(false))
          }}
          disabled={refreshing}
          title="Refresh satisfaction data for this month"
          className="ml-auto flex items-center gap-1.5 text-[11px] text-slate-400 hover:text-white transition disabled:opacity-40 bg-slate-800 hover:bg-slate-700 px-2.5 py-1 rounded-lg border border-slate-700/50"
        >
          <RefreshCw className={clsx('w-3.5 h-3.5', refreshing && 'animate-spin')} />
          {refreshing ? 'Refreshing\u2026' : 'Refresh'}
        </button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-4 gap-3">
        {[
          ['Totally Satisfied', s.totally_satisfied_pct != null ? `${s.totally_satisfied_pct}%` : '--', s.totally_satisfied_pct != null ? satColor(s.totally_satisfied_pct) : 'text-slate-400', '82% target', s.totally_satisfied_pct != null && s.totally_satisfied_pct < 82],
          ['Response Time Sat', s.response_time_pct != null ? `${s.response_time_pct}%` : '--', s.response_time_pct != null ? satColor(s.response_time_pct) : 'text-slate-400', null, s.response_time_pct != null && s.response_time_pct < 82],
          ['Technician Sat', s.technician_pct != null ? `${s.technician_pct}%` : '--', s.technician_pct != null ? satColor(s.technician_pct) : 'text-slate-400', null, s.technician_pct != null && s.technician_pct < 82],
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

      {/* Executive Insight */}
      {data.executive_insight?.headline && (
        <div className={clsx('glass rounded-xl border p-4',
          data.executive_insight.diagnosis === 'on_target' ? 'border-emerald-500/30' : 'border-amber-500/30'
        )}>
          <div className="flex items-start gap-3">
            <div className={clsx('mt-0.5 w-8 h-8 rounded-lg flex items-center justify-center text-sm shrink-0',
              data.executive_insight.diagnosis === 'on_target' ? 'bg-emerald-500/20' : 'bg-amber-500/20'
            )}>
              {data.executive_insight.diagnosis === 'on_target' ? <CheckCircle2 className="w-4 h-4 text-emerald-400" /> :
               data.executive_insight.diagnosis === 'wait_time' ? <Clock className="w-4 h-4 text-amber-400" /> :
               data.executive_insight.diagnosis === 'technician' ? <Users className="w-4 h-4 text-amber-400" /> :
               <AlertTriangle className="w-4 h-4 text-amber-400" />}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold text-slate-200 mb-1.5">{data.executive_insight.headline}</div>
              {data.executive_insight.body?.map((line, i) => (
                <div key={i} className="text-xs text-slate-400 leading-relaxed mb-1">{line}</div>
              ))}
              {data.executive_insight.actions?.length > 0 && (
                <div className="mt-2 pt-2 border-t border-slate-700/50">
                  <div className="text-[9px] text-slate-500 uppercase tracking-wide mb-1">Recommended Actions</div>
                  {data.executive_insight.actions.map((action, i) => (
                    <div key={i} className="text-xs text-blue-400 flex items-start gap-1.5 mb-0.5">
                      <ArrowRight className="w-3 h-3 mt-0.5 shrink-0" />
                      <span>{action}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Trend chart */}
      <TrendChart title="Daily Satisfaction Trend" tip="Purple = Totally Satisfied %. Blue = Avg ATA (min). Red area = PTA miss %. Bars = survey volume. Click any day to drill down." aspect={2.8}>
        <ComposedChart data={trend} onClick={(e) => {
          if (e?.activePayload?.[0]?.payload?.date) setSelectedDay(e.activePayload[0].payload.date)
        }} style={{ cursor: 'pointer' }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 10 }} interval={2} />
          <YAxis yAxisId="pct" domain={[0, 100]} tick={{ fill: '#64748b', fontSize: 10 }} tickFormatter={v => `${v}%`}
            label={{ value: '% / Satisfaction', angle: -90, position: 'insideLeft', offset: 5, fill: '#64748b', fontSize: 9 }} />
          <YAxis yAxisId="ata" orientation="right" tick={{ fill: '#64748b', fontSize: 10 }} tickFormatter={v => `${v}m`}
            label={{ value: 'Avg ATA (min)', angle: 90, position: 'insideRight', offset: 5, fill: '#64748b', fontSize: 9 }} />
          <RechartsTooltip content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null
            const entry = payload[0]?.payload
            return (
              <div className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs shadow-xl">
                <div className="font-semibold text-slate-300 mb-1">
                  Day {label}
                  {entry?.incomplete && <span className="ml-1.5 text-amber-400 font-normal text-[9px]">(surveys still arriving)</span>}
                </div>
                {payload.filter(p => !['sa_volume', 'surveys'].includes(p.dataKey)).map((p, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: p.color }} />
                    <span className="text-slate-400">{p.name}:</span>
                    <span className="font-semibold text-white">{p.value != null ? p.value : '--'}{p.unit || ''}</span>
                  </div>
                ))}
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-violet-500" />
                  <span className="text-slate-400">Surveys:</span>
                  <span className="font-semibold text-white">{entry?.surveys?.toLocaleString() || '0'}</span>
                </div>
                {entry?.sa_volume > 0 && (
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-slate-500" />
                    <span className="text-slate-400">SAs Created:</span>
                    <span className="font-semibold text-white">{entry.sa_volume.toLocaleString()}</span>
                  </div>
                )}
                <div className="text-[9px] text-slate-500 mt-1 border-t border-slate-800 pt-1">Click to analyze this day</div>
              </div>
            )
          }} />
          <Bar yAxisId="ata" dataKey="surveys" name="Surveys" radius={[2, 2, 0, 0]} fillOpacity={0.3}>
            {trend.map((entry, i) => (
              <Cell key={i} fill={entry.totally_satisfied_pct != null && entry.totally_satisfied_pct < 82 ? '#ef444480' : '#334155'} />
            ))}
          </Bar>
          <Area yAxisId="pct" dataKey="pta_miss_pct" name="PTA Miss" stroke="#ef4444" fill="#ef4444" fillOpacity={0.1} strokeWidth={1.5} dot={false} unit="%" connectNulls />
          <Line yAxisId="pct" dataKey="totally_satisfied_pct" name="Totally Satisfied" stroke="#a855f7" strokeWidth={2.5} dot={{ r: 3, fill: '#a855f7', stroke: '#a855f7' }} activeDot={{ r: 5, stroke: '#fff', strokeWidth: 2 }} unit="%" />
          <Line yAxisId="ata" dataKey="avg_ata" name="Avg ATA" stroke="#3b82f6" strokeWidth={2} dot={{ r: 2, fill: '#3b82f6' }} unit=" min" connectNulls />
          <Line yAxisId="pct" dataKey={() => 82} name="Target (82%)" stroke="#475569" strokeDasharray="5 5" strokeWidth={1} dot={false} />
        </ComposedChart>
      </TrendChart>

    </div>
  )
}

// ── Satisfaction Zone Map — zones colored by garage satisfaction score ────────

export function SatisfactionGarageMap({ garages, onGarage }) {
  const [grids, setGrids] = useState(null)
  const [expanded, setExpanded] = useState(false)
  const mapConfig = getMapConfig()

  useEffect(() => {
    fetchMapGrids().then(setGrids).catch(() => {})
  }, [])

  const mappableGarages = useMemo(() => garages.filter(g => g.lat && g.lon), [garages])

  const zoneStyle = useCallback(() => ({
    color: '#475569',
    weight: 1,
    opacity: 0.3,
    fillColor: '#1e293b',
    fillOpacity: 0.05,
  }), [])

  const onEachZone = useCallback((feature, layer) => {
    const name = feature.properties?.name || ''
    if (name) {
      layer.bindTooltip(name, { sticky: true, className: 'cc-tooltip', opacity: 0.85 })
    }
  }, [])

  const garageColor = (pct) => {
    if (pct == null) return '#475569'
    if (pct >= 90) return '#22c55e'
    if (pct >= 82) return '#3b82f6'
    if (pct >= 70) return '#f59e0b'
    return '#ef4444'
  }

  if (!grids) return (
    <div className="bg-slate-900/40 rounded-xl border border-slate-800/50 flex items-center justify-center" style={{ height: 400 }}>
      <Loader2 className="w-5 h-5 animate-spin text-slate-600" />
    </div>
  )

  const maxSurveys = Math.max(...mappableGarages.map(g => g.surveys || 0), 1)
  const circleRadius = (surveys) => {
    const ratio = (surveys || 0) / maxSurveys
    return Math.max(5, Math.round(ratio * 30 + 5))
  }

  function MapResizer() {
    const map = useMap()
    useEffect(() => {
      const t1 = setTimeout(() => map.invalidateSize(), 50)
      const t2 = setTimeout(() => map.invalidateSize(), 300)
      return () => { clearTimeout(t1); clearTimeout(t2) }
    }, [expanded, map])
    return null
  }

  if (expanded) {
    return ReactDOM.createPortal(
      <div className="fixed inset-0 z-[9999] bg-slate-950 flex flex-col">
        <div className="flex items-center justify-between px-4 py-2 bg-slate-900 border-b border-slate-800">
          <span className="text-sm font-bold text-white">Garage Performance Map</span>
          <button onClick={() => setExpanded(false)}
            className="p-1.5 rounded-lg hover:bg-slate-800 transition text-slate-400 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="flex-1">
          <MapContainer center={[42.9, -78.8]} zoom={9} className="w-full h-full"
            style={{ background: '#0f172a' }}
            zoomControl={true} attributionControl={false}>
            <MapResizer />
            <TileLayer url={mapConfig.url} />
            {grids && <GeoJSON key="zones-exp" data={grids} style={zoneStyle} onEachFeature={onEachZone} />}
            {mappableGarages.map(g => (
              <CircleMarker key={g.name} center={[g.lat, g.lon]}
                radius={circleRadius(g.surveys)}
                pathOptions={{
                  color: garageColor(g.totally_satisfied_pct),
                  fillColor: garageColor(g.totally_satisfied_pct),
                  fillOpacity: 0.6, weight: 2, opacity: 0.9,
                }}>
                <Tooltip direction="top" offset={[0, -8]} sticky className="cc-tooltip">
                  <div style={{ fontSize: 11, lineHeight: 1.5, minWidth: 160 }}>
                    <div style={{ fontWeight: 700, fontSize: 12 }}>{g.name}</div>
                    <div style={{ color: garageColor(g.totally_satisfied_pct), fontWeight: 800, fontSize: 16, margin: '2px 0' }}>
                      {g.totally_satisfied_pct != null ? `${g.totally_satisfied_pct}%` : 'No surveys'}
                    </div>
                    {g.surveys > 0 && <div style={{ color: '#94a3b8' }}>{g.surveys} surveys · {g.dissatisfied || 0} dissatisfied</div>}
                    {g.avg_ata != null && <div style={{ color: g.avg_ata > 45 ? '#f59e0b' : '#94a3b8' }}>Avg ATA: {g.avg_ata}m</div>}
                    {g.sa_total > 0 && <div style={{ color: '#94a3b8' }}>{g.sa_total} calls · {g.sa_completed} completed</div>}
                  </div>
                </Tooltip>
              </CircleMarker>
            ))}
          </MapContainer>
        </div>
        <div className="flex items-center justify-center gap-5 py-2 text-[10px] bg-slate-900 border-t border-slate-800">
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full" style={{ background: '#22c55e' }} /> 90%+ Excellent</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full" style={{ background: '#3b82f6' }} /> 82-89% On Target</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full" style={{ background: '#f59e0b' }} /> 70-81% Below</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full" style={{ background: '#ef4444' }} /> &lt;70% Critical</span>
          <span className="text-slate-500">Dot size = survey volume</span>
        </div>
      </div>,
      document.body
    )
  }

  return (
    <div className="rounded-xl border border-slate-800/50 overflow-hidden relative" style={{ height: 420 }}>
      <button onClick={() => setExpanded(true)}
        className="absolute top-3 right-3 z-[1000] bg-slate-900/90 border border-slate-700/50 rounded-lg p-2 hover:bg-slate-800 transition"
        title="Full screen">
        <Maximize2 className="w-4 h-4 text-slate-300" />
      </button>
      <MapContainer center={[42.9, -78.8]} zoom={8} className="w-full"
        style={{ background: '#0f172a', height: '390px' }}
        zoomControl={true} attributionControl={false}>
        <TileLayer url={mapConfig.url} />
        {grids && <GeoJSON key="zones-bg" data={grids} style={zoneStyle} onEachFeature={onEachZone} />}
        {mappableGarages.map(g => (
          <CircleMarker key={g.name} center={[g.lat, g.lon]}
            radius={circleRadius(g.surveys)}
            pathOptions={{
              color: garageColor(g.totally_satisfied_pct),
              fillColor: garageColor(g.totally_satisfied_pct),
              fillOpacity: 0.6, weight: 2, opacity: 0.9,
            }}
            eventHandlers={{ click: () => onGarage && onGarage(g.name) }}
          >
            <Tooltip direction="top" offset={[0, -8]} sticky className="cc-tooltip">
              <div style={{ fontSize: 11, lineHeight: 1.5, minWidth: 160 }}>
                <div style={{ fontWeight: 700, fontSize: 12 }}>{g.name}</div>
                <div style={{
                  color: garageColor(g.totally_satisfied_pct),
                  fontWeight: 800, fontSize: 16, margin: '2px 0'
                }}>
                  {g.totally_satisfied_pct != null ? `${g.totally_satisfied_pct}%` : 'No surveys'}
                </div>
                {g.surveys > 0 && <div style={{ color: '#94a3b8' }}>{g.surveys} surveys · {g.dissatisfied || 0} dissatisfied</div>}
                {g.avg_ata != null && <div style={{ color: g.avg_ata > 45 ? '#f59e0b' : '#94a3b8' }}>Avg ATA: {g.avg_ata}m</div>}
                {g.sa_total > 0 && <div style={{ color: '#94a3b8' }}>{g.sa_total} calls · {g.sa_completed} completed</div>}
              </div>
            </Tooltip>
          </CircleMarker>
        ))}
      </MapContainer>
      <div className="flex items-center justify-center gap-5 py-1.5 text-[9px] bg-slate-900/80 border-t border-slate-800/50">
        <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full" style={{ background: '#22c55e' }} /> 90%+ Excellent</span>
        <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full" style={{ background: '#3b82f6' }} /> 82-89% On Target</span>
        <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full" style={{ background: '#f59e0b' }} /> 70-81% Below</span>
        <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full" style={{ background: '#ef4444' }} /> &lt;70% Critical</span>
        <span className="text-slate-600">Dot size = survey volume</span>
      </div>
    </div>
  )
}
