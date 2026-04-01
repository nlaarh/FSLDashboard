import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import ReactDOM from 'react-dom'
import { clsx } from 'clsx'
import { Loader2, RefreshCw, CheckCircle2, AlertTriangle, Clock, Users, ArrowRight, ArrowLeft, ChevronRight, Maximize2, X, MessageSquare, Star } from 'lucide-react'
import { ComposedChart, Bar, Line, XAxis, YAxis, Tooltip as RechartsTooltip, CartesianGrid, Area, Cell } from 'recharts'
import { MapContainer, TileLayer, CircleMarker, Tooltip, GeoJSON, useMap } from 'react-leaflet'
import { fetchSatisfactionOverview, refreshSatisfactionOverview, fetchSatisfactionGarage, fetchSatisfactionDetail, fetchSatisfactionDay, fetchMapGrids } from '../api'
import SALink from '../components/SALink'
import { InfoTip, TrendChart, CHART_COLORS } from './CommandCenterUtils'
import { getMapConfig } from '../mapStyles'

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
    return <SatisfactionDayAnalysis date={selectedDay} onBack={() => setSelectedDay(null)} onGarage={(g) => { setSelectedDay(null); setSelectedGarage(g) }} />
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
        <div className="text-xs text-slate-600 mt-1">Surveys typically arrive 1–3 days after the call</div>
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

  // Tier grouping for garage performance map (exclude garages with no satisfaction data)
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
                // Poll until regeneration completes
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
                // Stop polling after 3 minutes
                setTimeout(() => { clearInterval(poll); setRefreshing(false); setLoading(false) }, 180000)
              })
              .catch(() => setRefreshing(false))
          }}
          disabled={refreshing}
          title="Refresh satisfaction data for this month"
          className="ml-auto flex items-center gap-1.5 text-[11px] text-slate-400 hover:text-white transition disabled:opacity-40 bg-slate-800 hover:bg-slate-700 px-2.5 py-1 rounded-lg border border-slate-700/50"
        >
          <RefreshCw className={clsx('w-3.5 h-3.5', refreshing && 'animate-spin')} />
          {refreshing ? 'Refreshing…' : 'Refresh'}
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

      {/* Executive Insight — VP summary */}
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

      {/* Trend chart — click any bar to drill into that day */}
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

  // Garages with location data
  const mappableGarages = useMemo(() => garages.filter(g => g.lat && g.lon), [garages])

  // Zone style: light gray boundaries for geographic context
  const zoneStyle = useCallback(() => ({
    color: '#475569',
    weight: 1,
    opacity: 0.3,
    fillColor: '#1e293b',
    fillOpacity: 0.05,
  }), [])

  // Zone tooltip: just the zone name
  const onEachZone = useCallback((feature, layer) => {
    const name = feature.properties?.name || ''
    if (name) {
      layer.bindTooltip(name, { sticky: true, className: 'cc-tooltip', opacity: 0.85 })
    }
  }, [])

  // Garage dot color based on satisfaction
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

  // Scale circles proportionally: more surveys = bigger circle
  const maxSurveys = Math.max(...mappableGarages.map(g => g.surveys || 0), 1)
  const circleRadius = (surveys) => {
    const ratio = (surveys || 0) / maxSurveys
    return Math.max(5, Math.round(ratio * 30 + 5))  // 5px min, 35px max
  }

  // Invalidate map size when expanding/collapsing
  function MapResizer() {
    const map = useMap()
    useEffect(() => {
      const t1 = setTimeout(() => map.invalidateSize(), 50)
      const t2 = setTimeout(() => map.invalidateSize(), 300)
      return () => { clearTimeout(t1); clearTimeout(t2) }
    }, [expanded, map])
    return null
  }

  // Fullscreen overlay rendered via portal
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


export function SatisfactionDayAnalysis({ date, onBack, onGarage }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    setLoading(true)
    fetchSatisfactionDay(date)
      .then(setData)
      .catch(e => setError(e.response?.data?.detail || e.message || 'Failed'))
      .finally(() => setLoading(false))
  }, [date])

  const dayLabel = new Date(date + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })

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
      <span className="ml-2 text-sm text-slate-500">Analyzing {dayLabel}...</span>
    </div>
  )
  if (error) return <div className="max-w-5xl mx-auto text-center text-red-400 py-10 text-sm">{error}</div>

  const s = data?.summary || {}
  const insights = data?.insights || []
  const allGarages = data?.garage_breakdown || []
  const garagesWithSurveys = allGarages.filter(g => g.surveys > 0)
  const problems = data?.problem_surveys || []
  const longAta = data?.long_ata_sas || []
  const cancels = data?.cancel_reasons || []

  // Tier grouping for visual scorecard
  const tiers = {
    excellent: { label: 'Excellent', range: '90-100%', textCls: 'text-emerald-400', bg: 'bg-emerald-500', border: 'border-emerald-500/30', garages: garagesWithSurveys.filter(g => g.tier === 'excellent') },
    ok:        { label: 'On Target', range: '82-89%',  textCls: 'text-blue-400',    bg: 'bg-blue-500',    border: 'border-blue-500/30',    garages: garagesWithSurveys.filter(g => g.tier === 'ok') },
    below:     { label: 'Below Target', range: '60-81%', textCls: 'text-amber-400', bg: 'bg-amber-500',   border: 'border-amber-500/30',   garages: garagesWithSurveys.filter(g => g.tier === 'below') },
    critical:  { label: 'Critical', range: '<60%',    textCls: 'text-red-400',     bg: 'bg-red-500',      border: 'border-red-500/30',     garages: garagesWithSurveys.filter(g => g.tier === 'critical') },
  }

  const metTarget = s.totally_satisfied_pct != null && s.totally_satisfied_pct >= 82

  return (
    <div className="max-w-5xl mx-auto space-y-5">
      {/* ── Header ── */}
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="p-1.5 rounded-lg hover:bg-slate-800/60 transition text-slate-400 hover:text-white">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div className="flex-1">
          <div className="text-base font-bold text-white">{dayLabel}</div>
          <div className="text-[11px] text-slate-500">Satisfaction Day Report</div>
        </div>
        {/* Big score badge */}
        <div className={clsx('px-5 py-2 rounded-xl text-center border',
          metTarget ? 'bg-emerald-950/30 border-emerald-500/30' : 'bg-red-950/30 border-red-500/30'
        )}>
          <div className={clsx('text-2xl font-black', metTarget ? 'text-emerald-400' : 'text-red-400')}>
            {s.totally_satisfied_pct != null ? `${s.totally_satisfied_pct}%` : '--'}
          </div>
          <div className={clsx('text-[9px] uppercase font-semibold', metTarget ? 'text-emerald-500/70' : 'text-red-500/70')}>
            {metTarget ? 'Target Met' : 'Below 82% Target'}
          </div>
        </div>
      </div>

      {/* ── Executive Summary — the full story ── */}
      <div className={clsx('glass rounded-xl border p-5', metTarget ? 'border-emerald-800/20' : 'border-red-800/20')}>
        <div className="text-xs font-bold text-white uppercase tracking-wide mb-3">Executive Summary</div>
        <div className="text-sm text-slate-300 leading-relaxed space-y-2">
          {/* Survey results narrative */}
          <p>
            {s.totally_satisfied_pct != null && s.totally_satisfied_pct < 82
              ? <><span className="text-red-400 font-semibold">{s.totally_satisfied_pct}%</span> of {s.total_surveys} survey responses for calls made this day were Totally Satisfied — <span className="text-red-400 font-semibold">{82 - s.totally_satisfied_pct} points below</span> the 82% AAA target. {s.dissatisfied_count > 0 && <><span className="text-red-400 font-semibold">{s.dissatisfied_count}</span> members reported dissatisfaction.</>}</>
              : <><span className="text-emerald-400 font-semibold">{s.totally_satisfied_pct}%</span> of {s.total_surveys} survey responses for calls made this day were Totally Satisfied — meeting the 82% AAA accreditation target.</>
            }
          </p>
          {/* Same-day operations context */}
          <p className="text-slate-400">
            <span className="text-slate-500 text-[11px] uppercase font-semibold">Same-day operations:</span>{' '}
            <span className="text-white font-medium">{s.total_sas?.toLocaleString()}</span> new service calls created with{' '}
            <span className={clsx('font-medium', (s.completion_pct || 0) >= 85 ? 'text-emerald-400' : 'text-amber-400')}>{s.completion_pct}%</span> completion rate.
            {s.cancelled > 0 && <> <span className="text-red-400 font-medium">{s.cancelled}</span> cancelled.</>}
            {s.avg_ata != null && <> Avg response time <span className={clsx('font-medium', s.avg_ata <= 45 ? 'text-emerald-400' : 'text-amber-400')}>{s.avg_ata}m</span>.</>}
            {s.sla_pct != null && <> 45-min SLA: <span className={clsx('font-medium', s.sla_pct >= 50 ? 'text-emerald-400' : 'text-red-400')}>{s.sla_pct}%</span> ({s.sla_hits}/{s.sla_eligible}).</>}
          </p>
          {/* ATA distribution */}
          {s.ata_under_30 != null && s.sla_eligible > 0 && (
            <div className="flex items-center gap-3 mt-1">
              <span className="text-[10px] text-slate-500 w-24">Response Time:</span>
              <div className="flex-1 flex h-5 rounded-lg overflow-hidden text-[9px] font-bold">
                {s.ata_under_30 > 0 && <div className="bg-emerald-600 flex items-center justify-center text-white" style={{ width: `${100 * s.ata_under_30 / s.sla_eligible}%` }}>{s.ata_under_30 > 3 ? `<30m (${s.ata_under_30})` : ''}</div>}
                {s.ata_30_45 > 0 && <div className="bg-emerald-800 flex items-center justify-center text-emerald-200" style={{ width: `${100 * s.ata_30_45 / s.sla_eligible}%` }}>{s.ata_30_45 > 3 ? `30-45m (${s.ata_30_45})` : ''}</div>}
                {s.ata_45_60 > 0 && <div className="bg-amber-700 flex items-center justify-center text-amber-100" style={{ width: `${100 * s.ata_45_60 / s.sla_eligible}%` }}>{s.ata_45_60 > 3 ? `45-60m (${s.ata_45_60})` : ''}</div>}
                {s.ata_over_60 > 0 && <div className="bg-red-700 flex items-center justify-center text-red-100" style={{ width: `${100 * s.ata_over_60 / s.sla_eligible}%` }}>{s.ata_over_60 > 3 ? `>60m (${s.ata_over_60})` : ''}</div>}
              </div>
            </div>
          )}
          {/* Survey distribution */}
          {s.total_surveys > 0 && (
            <div className="flex items-center gap-3 mt-1">
              <span className="text-[10px] text-slate-500 w-24 shrink-0">Survey Scores:</span>
              <div className="flex-1 flex h-6 rounded-lg overflow-hidden text-[9px] font-bold">
                {[
                  { count: s.totally_satisfied_count, label: 'Totally Sat', bg: 'bg-emerald-600', text: 'text-white' },
                  { count: s.satisfied_count, label: 'Sat', bg: 'bg-green-700', text: 'text-green-100' },
                  { count: s.neither_count, label: 'Neutral', bg: 'bg-slate-600', text: 'text-slate-200' },
                  { count: s.dissatisfied_count, label: 'Dissat', bg: 'bg-red-700', text: 'text-red-100' },
                ].filter(seg => seg.count > 0).map(seg => {
                  const pct = 100 * seg.count / s.total_surveys
                  return (
                    <div key={seg.label} className={clsx(seg.bg, seg.text, 'flex items-center justify-center overflow-hidden whitespace-nowrap px-1')}
                      style={{ width: `${Math.max(pct, 4)}%` }}
                      title={`${seg.label}: ${seg.count} (${Math.round(pct)}%)`}>
                      {pct > 8 ? `${seg.label} (${seg.count})` : seg.count}
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>

        {/* Insight pills */}
        {insights.length > 0 && (
          <div className="mt-4 pt-3 border-t border-slate-800/50 space-y-1.5">
            {insights.map((ins, i) => (
              <div key={i} className={clsx('text-xs px-3 py-2 rounded-lg',
                ins.type === 'critical' ? 'bg-red-950/30 text-red-300' :
                ins.type === 'warning' ? 'bg-amber-950/30 text-amber-300' :
                ins.type === 'success' ? 'bg-emerald-950/30 text-emerald-300' :
                'bg-blue-950/30 text-blue-300'
              )}>
                {ins.text}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Customer Voice — dissatisfied comments first ── */}
      {problems.length > 0 && (
        <div className="glass rounded-xl border border-red-800/20 p-5">
          <div className="text-xs font-bold text-white uppercase tracking-wide mb-3">
            Voice of the Customer
            <span className="text-red-400 font-normal normal-case ml-2">{problems.length} dissatisfied responses</span>
          </div>
          <div className="space-y-2">
            {problems.filter(sv => sv.comment).map((sv, i) => (
              <div key={i} className="bg-slate-900/40 rounded-lg p-3 space-y-1.5 border-l-2 border-red-500/40">
                <div className="flex items-center gap-2 flex-wrap text-[10px]">
                  <span className="text-slate-500 truncate max-w-[200px]">{sv.garage}</span>
                  {sv.sa_number && <SALink number={sv.sa_number} style={{ fontFamily: 'monospace', fontSize: 10 }} />}
                  {sv.call_date && <span className="text-slate-600">Call: {sv.call_date}</span>}
                  {sv.driver && <span className="text-slate-500">{sv.driver}</span>}
                  {!sv.sa_number && sv.wo_number && <span className="text-slate-600 font-mono">WO {sv.wo_number}</span>}
                  <div className="flex items-center gap-1.5 ml-auto">
                    {satBadge(sv.overall)}
                  </div>
                </div>
                <div className="text-xs text-slate-300 italic leading-relaxed pl-1">"{sv.comment}"</div>
              </div>
            ))}
            {problems.filter(sv => !sv.comment).length > 0 && (
              <div className="text-[10px] text-slate-600 pt-1">+ {problems.filter(sv => !sv.comment).length} dissatisfied responses without comments</div>
            )}
          </div>
        </div>
      )}

      {/* ── Garage Performance Map — dots at garage locations ── */}
      {garagesWithSurveys.length > 0 && (
        <div className="glass rounded-xl border border-slate-700/30 p-4 space-y-3">
          <div className="text-xs font-bold text-white uppercase tracking-wide">Garage Performance Map</div>
          <SatisfactionGarageMap garages={allGarages} onGarage={onGarage} />
        </div>
      )}

      {/* ── Slow Responses ── */}
      {longAta.length > 0 && (
        <div className="glass rounded-xl border border-amber-800/20 p-5">
          <div className="text-xs font-bold text-white uppercase tracking-wide mb-3">
            Slow Responses
            <span className="text-amber-400 font-normal normal-case ml-2">{longAta.length} calls over 60 minutes</span>
          </div>
          <div className="space-y-0.5 max-h-[300px] overflow-y-auto">
            {longAta.map((sa, i) => (
              <div key={i} className="flex items-center gap-3 px-3 py-1.5 rounded-lg text-[11px] bg-slate-900/30">
                {sa.number && <SALink number={sa.number} style={{ fontFamily: 'monospace', fontSize: 10 }} />}
                <span className="text-slate-400 flex-1 truncate">{sa.garage}</span>
                <span className="text-slate-500">{sa.work_type}</span>
                <span className={clsx('font-bold', sa.ata_min > 90 ? 'text-red-400' : 'text-amber-400')}>{sa.ata_min}m</span>
                <span className={clsx('text-[9px] px-1 py-0.5 rounded',
                  sa.dispatch_method === 'Field Services' ? 'bg-blue-950/40 text-blue-400' : 'bg-fuchsia-950/40 text-fuchsia-400'
                )}>{sa.dispatch_method === 'Field Services' ? 'Fleet' : 'TB'}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Cancellation Reasons ── */}
      {cancels.length > 0 && (
        <div className="glass rounded-xl border border-slate-700/30 p-5">
          <div className="text-xs font-bold text-white uppercase tracking-wide mb-3">Cancellation Breakdown</div>
          <div className="flex gap-3 flex-wrap">
            {cancels.map((cr, i) => (
              <div key={i} className="bg-slate-900/40 rounded-lg px-3 py-2 text-center border border-slate-800/50">
                <div className="text-lg font-bold text-red-400">{cr.count}</div>
                <div className="text-[9px] text-slate-500 max-w-[120px] truncate">{cr.reason}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export function SatisfactionGarageDetail({ garage, month, onBack }) {
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
    return <SatisfactionDayDetail garage={garage} date={selectedDay} onBack={() => setSelectedDay(null)} />
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

export function SatisfactionDayDetail({ garage, date, onBack }) {
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
