import { useState, useMemo, useEffect } from 'react'
import { MapContainer, TileLayer, Marker, Popup, Polyline, CircleMarker, GeoJSON } from 'react-leaflet'
import L from 'leaflet'
import { clsx } from 'clsx'
import { CheckCircle2, XCircle, ChevronDown, ChevronUp, Clock, Truck, Navigation, AlertTriangle, Zap, Layers, Loader2 } from 'lucide-react'
import { fetchMapGrids, fetchMapWeather } from '../api'
import { getMapConfig } from '../mapStyles'

const _WMO_EMOJI = {
  0:'☀️',1:'🌤️',2:'⛅',3:'☁️',45:'🌫️',48:'🌫️',
  51:'🌦️',53:'🌦️',55:'🌧️',61:'🌧️',63:'🌧️',65:'⛈️',
  66:'🌧️',67:'⛈️',71:'🌨️',73:'❄️',75:'❄️',77:'🌨️',
  80:'🌦️',81:'🌧️',82:'⛈️',85:'🌨️',86:'❄️',95:'⛈️',96:'⛈️',99:'⛈️',
}
const _gridStyle = (f) => ({
  color: f.properties.color || '#818cf8', weight: 1.5, opacity: 0.85,
  fillColor: f.properties.color || '#818cf8', fillOpacity: 0.1,
})
function _onEachGrid(feature, layer) {
  layer.bindTooltip(feature.properties.name, { permanent: false, direction: 'center', className: 'cc-tooltip' })
  layer.bindPopup(`<strong>${feature.properties.name}</strong><br/>${feature.properties.territory_name}`)
}
function _makeWeatherIcon(s) {
  const emoji = _WMO_EMOJI[s.weather_code] ?? '🌡️'
  return L.divIcon({
    className: '',
    iconSize: [72, 44], iconAnchor: [36, 44], popupAnchor: [0, -44],
    html: `<div style="background:#0f172a;border:1px solid #334155;border-radius:8px;
      padding:4px 8px;text-align:center;color:white;font-family:-apple-system,sans-serif;
      white-space:nowrap;box-shadow:0 4px 12px rgba(0,0,0,0.6)">
      <div style="font-size:13px;font-weight:700">${emoji} ${s.temp_f}°F</div>
      <div style="font-size:10px;color:#94a3b8;margin-top:1px">${s.name}</div>
    </div>`,
  })
}

// ── Truck SVG icon ──────────────────────────────────────────────────────────
const TRUCK_SVG = (fill, stroke = '#fff') => `
<svg xmlns="http://www.w3.org/2000/svg" width="28" height="20" viewBox="0 0 28 20">
  <rect x="1" y="4" width="18" height="12" rx="2" fill="${fill}" stroke="${stroke}" stroke-width="1.5"/>
  <path d="M19 8h5l3 4v4h-8V8z" fill="${fill}" stroke="${stroke}" stroke-width="1.5"/>
  <circle cx="7" cy="17" r="2.5" fill="#1e293b" stroke="${stroke}" stroke-width="1"/>
  <circle cx="23" cy="17" r="2.5" fill="#1e293b" stroke="${stroke}" stroke-width="1"/>
</svg>`

function truckIcon(color, label, glow = false) {
  const colors = {
    closest:    { fill: '#22c55e', bg: 'rgba(34,197,94,0.15)',  border: '#22c55e' },
    dispatched: { fill: '#f97316', bg: 'rgba(249,115,22,0.15)', border: '#f97316' },
    eligible:   { fill: '#64748b', bg: 'rgba(100,116,139,0.08)', border: '#475569' },
    ineligible: { fill: '#334155', bg: 'rgba(51,65,85,0.08)',   border: '#1e293b' },
  }
  const c = colors[color] || colors.eligible
  const glowStyle = glow ? `box-shadow:0 0 14px 5px ${c.fill}50;` : ''
  return L.divIcon({
    className: '',
    iconSize: [56, 44],
    iconAnchor: [28, 22],
    html: `<div style="display:flex;flex-direction:column;align-items:center;${glowStyle}">
      ${TRUCK_SVG(c.fill)}
      <div style="margin-top:1px;padding:0 4px;border-radius:4px;font-size:9px;font-weight:700;
                  color:${c.fill};background:${c.bg};border:1px solid ${c.border};white-space:nowrap;
                  line-height:14px;letter-spacing:0.3px">${label}</div>
    </div>`,
  })
}

const CUSTOMER_ICON = L.divIcon({
  className: '',
  iconSize: [36, 44],
  iconAnchor: [18, 44],
  html: `<div style="display:flex;flex-direction:column;align-items:center">
    <div style="width:36px;height:36px;border-radius:50% 50% 50% 0;transform:rotate(-45deg);
                background:#ef4444;border:3px solid white;box-shadow:0 3px 12px rgba(239,68,68,0.5);
                display:flex;align-items:center;justify-content:center">
      <span style="color:white;font-size:18px;font-weight:bold;transform:rotate(45deg)">&#9733;</span>
    </div>
  </div>`,
})

const FACILITY_ICON = L.divIcon({
  className: '',
  iconSize: [32, 32],
  iconAnchor: [16, 16],
  html: `<div style="width:32px;height:32px;border-radius:6px;background:#a855f7;border:2px solid white;
                      box-shadow:0 2px 8px rgba(168,85,247,0.4);display:flex;align-items:center;justify-content:center">
    <span style="color:white;font-size:18px">&#8962;</span>
  </div>`,
})

// ── Driver status helper ────────────────────────────────────────────────────
function getDriverStatus(d, closestDist) {
  if (d.is_closest) return { tag: 'CLOSEST', color: 'text-green-400', bg: 'bg-green-500/10 border-green-500/20', reason: 'Nearest eligible driver — should have been dispatched' }
  if (!d.has_gps) return { tag: 'NO GPS', color: 'text-red-400', bg: 'bg-red-500/10 border-red-500/20', reason: 'No GPS position — cannot determine distance' }
  if (!d.has_skills) return { tag: 'WRONG SKILL', color: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/20', reason: 'Missing required skills for this call type' }
  if (d.distance != null && closestDist != null) {
    const extra = (d.distance - closestDist).toFixed(1)
    return { tag: `+${extra} mi`, color: 'text-slate-400', bg: 'bg-slate-500/10 border-slate-600/20', reason: `${extra} miles farther than closest eligible driver` }
  }
  return { tag: 'ELIGIBLE', color: 'text-slate-400', bg: 'bg-slate-500/10 border-slate-600/20', reason: 'Eligible but not closest' }
}


export default function MapView({ data }) {
  const { results, summary } = data
  const [selectedIdx, setSelectedIdx] = useState(0)
  const [showAnalysis, setShowAnalysis] = useState(true)

  // Map style (from Admin settings)
  const [mapConfig, setMapCfg] = useState(getMapConfig)
  useEffect(() => {
    const handler = () => setMapCfg(getMapConfig())
    window.addEventListener('mapStyleChanged', handler)
    return () => window.removeEventListener('mapStyleChanged', handler)
  }, [])

  // Map overlay layers
  const [layers, setLayers] = useState({ grid: false, weather: false })
  const [grids, setGrids] = useState(null)
  const [weather, setWeather] = useState([])
  const [layerLoading, setLayerLoading] = useState({ grid: false, weather: false })

  useEffect(() => {
    if (!layers.grid || grids !== null) return
    setLayerLoading(l => ({ ...l, grid: true }))
    fetchMapGrids().then(d => { setGrids(d); setLayerLoading(l => ({ ...l, grid: false })) })
      .catch(() => setLayerLoading(l => ({ ...l, grid: false })))
  }, [layers.grid])

  useEffect(() => {
    if (!layers.weather || weather.length > 0) return
    setLayerLoading(l => ({ ...l, weather: true }))
    fetchMapWeather().then(d => { setWeather(d); setLayerLoading(l => ({ ...l, weather: false })) })
      .catch(() => setLayerLoading(l => ({ ...l, weather: false })))
  }, [layers.weather])

  const selected = results?.[selectedIdx]

  if (!results || results.length === 0) {
    return <div className="text-center py-16 text-slate-500">No SAs with location data found for this date.</div>
  }
  if (!selected) return null

  const center = selected.sa_lat && selected.sa_lon ? [selected.sa_lat, selected.sa_lon] : [42.9, -78.8]
  const tl = selected.timeline || {}

  const sortedDrivers = useMemo(() =>
    [...(selected.drivers || [])].sort((a, b) => {
      if (a.is_closest) return -1
      if (b.is_closest) return 1
      return (a.distance ?? 999) - (b.distance ?? 999)
    }), [selected])

  const driversWithGPS = useMemo(() => sortedDrivers.filter(d => d.eff_lat && d.eff_lon), [sortedDrivers])
  const closestDist = selected.closest_distance

  return (
    <div className="space-y-4">
      {/* Summary bar */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <SumCard label="Total SAs" value={summary.total_sas} />
        <SumCard label="Dispatch" value={summary.dispatched_via || '?'} color="text-brand-400" />
        <SumCard label="Avg Closest" value={summary.avg_closest_distance != null ? `${summary.avg_closest_distance} mi` : '?'} color="text-green-400" />
        <SumCard label="Drivers in Territory" value={`${selected.eligible_count} / ${selected.total_drivers}`} sub="eligible" color="text-slate-300" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[340px_1fr] gap-4">
        {/* ── SA list sidebar ──────────────────────────────────────── */}
        <div className="glass rounded-xl overflow-hidden flex flex-col max-h-[900px]">
          <div className="px-3 py-2 bg-slate-800/50 border-b border-slate-700/50 text-xs font-semibold text-slate-400">
            Service Appointments ({results.length})
          </div>
          <div className="overflow-y-auto flex-1">
            {results.map((r, i) => {
              const rtl = r.timeline || {}
              return (
                <button
                  key={r.sa_id}
                  onClick={() => setSelectedIdx(i)}
                  className={clsx(
                    'w-full px-3 py-2.5 text-left border-b border-slate-800/50 transition-colors',
                    i === selectedIdx ? 'bg-brand-600/20 border-l-2 border-l-brand-500' : 'hover:bg-slate-800/40'
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-slate-200">{r.appointment_number}</span>
                    <span className="text-[10px] text-slate-500">{r.created_time}</span>
                  </div>
                  <div className="text-xs text-slate-500 mt-0.5 truncate">{r.address}</div>
                  <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">{r.work_type}</span>
                    {r.truck_id && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-orange-500/10 text-orange-400 border border-orange-500/20">
                        {r.truck_id.split('-').pop()}
                      </span>
                    )}
                    {rtl.sla_met === true && <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />}
                    {rtl.sla_met === false && rtl.response_min && <span className="text-[10px] text-red-400">{rtl.response_min}m</span>}
                    {r.status?.includes('Cancel') && <XCircle className="w-3.5 h-3.5 text-red-400" />}
                  </div>
                  {/* Driver info */}
                  <div className="mt-1.5 space-y-0.5">
                    {r.actual_driver && (
                      <div className="text-[10px] text-slate-500 flex items-center gap-1">
                        <Truck className="w-3 h-3 text-orange-400 shrink-0" />
                        <span className="text-slate-400">Assigned:</span>
                        <span className="text-orange-300 font-medium truncate">{r.actual_driver}</span>
                      </div>
                    )}
                    {r.closest_driver && r.closest_driver !== '?' && (
                      <div className="text-[10px] text-slate-500 flex items-center gap-1">
                        <Navigation className="w-3 h-3 text-green-400 shrink-0" />
                        <span className="text-slate-400">Closest:</span>
                        <span className="text-green-300 font-medium truncate">{r.closest_driver}</span>
                        {r.closest_distance != null && (
                          <span className="text-green-400 font-bold ml-auto shrink-0">{r.closest_distance.toFixed(1)} mi</span>
                        )}
                      </div>
                    )}
                  </div>
                </button>
              )
            })}
          </div>
        </div>

        {/* ── Map + Analysis ──────────────────────────────────── */}
        <div className="space-y-4">
          {/* SA Header */}
          <div className="glass rounded-xl p-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <h4 className="text-lg font-bold text-white">{selected.appointment_number}</h4>
                  <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300">{selected.work_type}</span>
                  <span className={clsx('text-xs px-2 py-0.5 rounded-full',
                    selected.status === 'Completed' ? 'bg-emerald-500/10 text-emerald-400' :
                    selected.status?.includes('Cancel') ? 'bg-red-500/10 text-red-400' :
                    'bg-amber-500/10 text-amber-400'
                  )}>{selected.status}</span>
                  {tl.sla_met === true && <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">SLA MET</span>}
                  {tl.sla_met === false && tl.response_min && <span className="text-xs px-2 py-0.5 rounded-full bg-red-500/10 text-red-400 border border-red-500/20">SLA MISSED +{tl.response_min - 45}min</span>}
                </div>
                <div className="flex items-center gap-2 mt-1 text-sm text-slate-400">
                  <Navigation className="w-3.5 h-3.5" />
                  <span>{selected.address || 'No address'}</span>
                </div>
              </div>
              <div className="text-right shrink-0">
                {selected.truck_id && <div className="text-sm text-orange-400 font-bold">Truck {selected.truck_id.split('-').pop()}</div>}
                <div className="text-[10px] text-slate-500">{tl.dispatch_method} • {tl.schedule_mode}</div>
              </div>
            </div>

            {/* Timeline bar */}
            <div className="flex items-center gap-1 mt-3 overflow-x-auto">
              <TimeStep icon={<Zap className="w-3 h-3" />} label="Received" time={tl.created} />
              <TimeArrow label={tl.dispatch_min != null ? `${tl.dispatch_min}m` : '?'} />
              <TimeStep icon={<Truck className="w-3 h-3" />} label="Dispatched" time={tl.scheduled} sub={tl.auto_assign ? 'Auto' : 'Manual'} />
              <TimeArrow label={tl.response_min != null && tl.dispatch_min != null ? `${tl.response_min - (tl.dispatch_min || 0)}m` : '?'} />
              <TimeStep icon={<Navigation className="w-3 h-3" />} label="On Location" time={tl.on_location}
                color={tl.sla_met ? 'text-emerald-400' : tl.response_min ? 'text-red-400' : 'text-slate-400'} />
              <TimeArrow label={tl.service_min != null ? `${tl.service_min}m` : '?'} />
              <TimeStep icon={<CheckCircle2 className="w-3 h-3" />} label="Completed" time={tl.completed} />
              {tl.total_min && (
                <div className="ml-2 px-2 py-1 rounded bg-slate-800/50 text-xs text-slate-400">
                  Total: <span className="font-bold text-white">{tl.total_min} min</span>
                </div>
              )}
            </div>

            {/* Key metrics row */}
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mt-3">
              <MiniStat label="PTA Promised" value={tl.pta_promised ? `${tl.pta_promised} min` : 'N/A'}
                color={tl.pta_promised && tl.pta_promised <= 45 ? 'text-emerald-400' : 'text-amber-400'} />
              <MiniStat label="Actual Response" value={tl.response_min ? `${tl.response_min} min` : 'N/A'}
                color={tl.sla_met ? 'text-emerald-400' : 'text-red-400'} />
              <MiniStat label="Closest Driver" value={selected.closest_driver}
                sub={selected.closest_distance ? `${selected.closest_distance.toFixed(1)} mi` : '?'}
                color="text-green-400" />
              <MiniStat label="Facility Dist" value={selected.facility_distance ? `${selected.facility_distance.toFixed(1)} mi` : '?'} />
              <MiniStat label="Required Skills" value={(selected.required_skills || []).join(', ') || 'None'} />
            </div>
          </div>

          {/* Map */}
          <div className="glass rounded-xl overflow-hidden relative" style={{ height: 440 }}>
            <MapContainer key={`${selected.sa_lat}-${selected.sa_lon}`} center={center} zoom={11}
              style={{ height: '100%', width: '100%' }} scrollWheelZoom={true}>
              <TileLayer key={mapConfig.url} url={mapConfig.url}
                className={mapConfig.filter ? 'dynamic-map-tiles' : ''}
                {...(mapConfig.noSubdomains ? { subdomains: [] } : {})} />
              {mapConfig.filter && (
                <style>{`.dynamic-map-tiles { filter: ${mapConfig.filter}; }`}</style>
              )}

              {/* Customer */}
              <Marker position={[selected.sa_lat, selected.sa_lon]} icon={CUSTOMER_ICON} zIndexOffset={1000}>
                <Popup>
                  <div style={{fontSize:12, minWidth:220, color:'#e2e8f0'}}>
                    <div style={{fontWeight:700, fontSize:14, marginBottom:4}}>
                      SA# {selected.appointment_number}
                    </div>
                    <div style={{color:'#94a3b8'}}>
                      <strong style={{color:'#e2e8f0'}}>{selected.work_type}</strong> — {selected.status}<br/>
                      {selected.address}<br/>
                      {selected.required_skills?.length > 0 && (
                        <>Skills: <span style={{color:'#60a5fa'}}>{selected.required_skills.join(', ')}</span><br/></>
                      )}
                      {tl.response_min && (
                        <>Response: <span style={{color: tl.sla_met ? '#22c55e' : '#ef4444', fontWeight:700}}>{tl.response_min} min</span><br/></>
                      )}
                      {tl.pta_promised && <>PTA: {tl.pta_promised} min<br/></>}
                      {selected.truck_id && <>Truck: <span style={{color:'#f97316'}}>{selected.truck_id}</span><br/></>}
                      {selected.closest_driver && selected.closest_driver !== '?' && (
                        <>Closest: <span style={{color:'#22c55e', fontWeight:600}}>{selected.closest_driver}</span>
                        {selected.closest_distance != null && ` (${selected.closest_distance.toFixed(1)} mi)`}<br/></>
                      )}
                    </div>
                  </div>
                </Popup>
              </Marker>

              {/* Facility */}
              {selected.facility_lat && selected.facility_lon && (
                <>
                  <Marker position={[selected.facility_lat, selected.facility_lon]} icon={FACILITY_ICON}>
                    <Popup>
                      <div style={{fontSize:12, color:'#e2e8f0', minWidth:160}}>
                        <div style={{fontWeight:700, fontSize:14, marginBottom:4}}>Facility / Garage</div>
                        <div style={{color:'#94a3b8'}}>
                          Distance to SA: <span style={{color:'#e2e8f0', fontWeight:600}}>{selected.facility_distance?.toFixed(1)} mi</span><br/>
                          SA# {selected.appointment_number}
                        </div>
                      </div>
                    </Popup>
                  </Marker>
                  <Polyline positions={[[selected.facility_lat, selected.facility_lon], [selected.sa_lat, selected.sa_lon]]}
                    pathOptions={{ color: '#a855f7', weight: 1, dashArray: '6,6', opacity: 0.3 }} />
                </>
              )}

              {/* Dispatched GPS position (where truck was) */}
              {tl.dispatched_lat && tl.dispatched_lon && (
                <>
                  <CircleMarker center={[tl.dispatched_lat, tl.dispatched_lon]} radius={8}
                    pathOptions={{ color: '#f97316', weight: 2, fillColor: '#f97316', fillOpacity: 0.3 }}>
                    <Popup>
                      <div style={{fontSize:12, color:'#e2e8f0', minWidth:180}}>
                        <div style={{fontWeight:700, fontSize:13, marginBottom:4, color:'#f97316'}}>Truck at Dispatch</div>
                        <div style={{color:'#94a3b8'}}>
                          {selected.truck_id && <>Truck: <span style={{color:'#f97316'}}>{selected.truck_id}</span><br/></>}
                          Distance to SA: <span style={{color:'#e2e8f0', fontWeight:600}}>{tl.dispatched_distance?.toFixed(1)} mi</span><br/>
                          SA# {selected.appointment_number}
                        </div>
                      </div>
                    </Popup>
                  </CircleMarker>
                  <Polyline positions={[[tl.dispatched_lat, tl.dispatched_lon], [selected.sa_lat, selected.sa_lon]]}
                    pathOptions={{ color: '#f97316', weight: 2, dashArray: '6,4', opacity: 0.5 }} />
                </>
              )}

              {/* Driver trucks */}
              {driversWithGPS.map(d => {
                const status = getDriverStatus(d, closestDist)
                const iconType = d.is_closest ? 'closest' : d.eligible ? 'eligible' : 'ineligible'
                const distLabel = d.distance != null ? `${d.distance.toFixed(1)} mi` : 'N/A'
                return (
                  <Marker key={d.driver_id} position={[d.eff_lat, d.eff_lon]}
                    icon={truckIcon(iconType, distLabel, d.is_closest)}
                    zIndexOffset={d.is_closest ? 900 : d.eligible ? 500 : 100}>
                    <Popup>
                      <div style={{fontSize:12, minWidth:230, color:'#e2e8f0'}}>
                        <div style={{display:'flex', alignItems:'center', gap:6, marginBottom:4}}>
                          <strong style={{fontSize:14, color: d.is_closest ? '#22c55e' : '#e2e8f0'}}>{d.name}</strong>
                          <span style={{fontWeight:700, fontSize:10, padding:'1px 6px', borderRadius:4,
                            background: d.is_closest ? 'rgba(34,197,94,0.15)' : d.eligible ? 'rgba(100,116,139,0.15)' : 'rgba(239,68,68,0.15)',
                            color: d.is_closest ? '#22c55e' : d.eligible ? '#94a3b8' : '#ef4444',
                            border: `1px solid ${d.is_closest ? 'rgba(34,197,94,0.3)' : d.eligible ? 'rgba(100,116,139,0.3)' : 'rgba(239,68,68,0.3)'}`}}>
                            {status.tag}
                          </span>
                        </div>
                        <div style={{color:'#94a3b8'}}>
                          SA# <span style={{color:'#e2e8f0', fontWeight:600}}>{selected.appointment_number}</span>
                          {' — '}{selected.work_type}<br/>
                          Distance: <span style={{color:'#e2e8f0', fontWeight:700}}>{d.distance?.toFixed(1) || '?'} mi</span><br/>
                          Position: <span style={{color:'#cbd5e1', fontSize:11}}>{d.eff_lat?.toFixed(4)}, {d.eff_lon?.toFixed(4)}</span><br/>
                          Type: {d.territory_type || '?'}<br/>
                          Skills: {d.skills?.length > 0
                            ? <span style={{color:'#60a5fa'}}>{d.skills.join(', ')}</span>
                            : <span style={{color:'#64748b'}}>None</span>}
                        </div>
                        <hr style={{border:'none',borderTop:'1px solid #334155',margin:'5px 0'}}/>
                        <div style={{color:'#94a3b8',fontSize:11}}>{status.reason}</div>
                      </div>
                    </Popup>
                  </Marker>
                )
              })}

              {/* Line from closest to SA */}
              {driversWithGPS.filter(d => d.is_closest).map(d => (
                <Polyline key={`cl-${d.driver_id}`}
                  positions={[[d.eff_lat, d.eff_lon], [selected.sa_lat, selected.sa_lon]]}
                  pathOptions={{ color: '#22c55e', weight: 3, opacity: 0.8 }} />
              ))}
              {driversWithGPS.filter(d => d.is_closest).map(d => (
                <CircleMarker key={`glow-${d.driver_id}`} center={[d.eff_lat, d.eff_lon]} radius={22}
                  pathOptions={{ color: '#22c55e', weight: 2, fillOpacity: 0.08, opacity: 0.4 }} />
              ))}

              {/* ── Grid layer ── */}
              {layers.grid && grids && grids.features.length > 0 && (
                <GeoJSON key="grids" data={grids} style={_gridStyle} onEachFeature={_onEachGrid} />
              )}

              {/* ── Weather layer ── */}
              {layers.weather && weather.map((s, i) => (
                !s.error && s.temp_f != null && (
                  <Marker key={i} position={[s.lat, s.lon]} icon={_makeWeatherIcon(s)}>
                    <Popup>
                      <div style={{ fontSize: 12, color: '#e2e8f0' }}>
                        <strong>{s.name}</strong><br />
                        {s.temp_f}°F — {s.condition}<br />
                        Wind: {s.wind} mph
                      </div>
                    </Popup>
                  </Marker>
                )
              ))}
            </MapContainer>

            {/* ── Floating layer panel ── */}
            <div className="absolute top-3 right-3 z-[1000]" style={{ minWidth: 130 }}>
              <div className="bg-slate-900/95 backdrop-blur-xl border border-slate-600/40 rounded-xl shadow-2xl overflow-hidden">
                <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-800/60">
                  <Layers className="w-3.5 h-3.5 text-brand-400" />
                  <span className="text-[10px] font-bold text-white uppercase tracking-wide">Layers</span>
                </div>
                <div className="px-3 py-2.5 space-y-2">
                  {[
                    { key: 'grid',    emoji: '🗺️', label: 'Grid',    color: 'text-indigo-400' },
                    { key: 'weather', emoji: '🌡️', label: 'Weather', color: 'text-cyan-400' },
                  ].map(({ key, emoji, label, color }) => (
                    <label key={key} className="flex items-center gap-2 cursor-pointer select-none">
                      <input
                        type="checkbox"
                        checked={layers[key]}
                        onChange={e => setLayers(l => ({ ...l, [key]: e.target.checked }))}
                        className="w-3 h-3 rounded accent-indigo-500"
                      />
                      <span className="text-sm leading-none">{emoji}</span>
                      <span className={`text-[10px] font-medium flex-1 ${layers[key] ? color : 'text-slate-500'}`}>
                        {label}
                      </span>
                      {layerLoading[key] && <Loader2 className="w-2.5 h-2.5 text-brand-400 animate-spin" />}
                    </label>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Legend */}
          <div className="flex flex-wrap gap-4 text-xs text-slate-400">
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded" style={{background:'#ef4444'}} /> Customer</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded" style={{background:'#22c55e'}} /> Closest Driver</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded" style={{background:'#f97316'}} /> Dispatched Position</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded" style={{background:'#64748b'}} /> Eligible</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded" style={{background:'#334155'}} /> Not Eligible</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded" style={{background:'#a855f7'}} /> Facility</span>
          </div>

          {/* ── Collapsible Analysis ────────────────────────────────── */}
          <div className="glass rounded-xl overflow-hidden">
            <button
              onClick={() => setShowAnalysis(v => !v)}
              className="w-full px-4 py-3 bg-slate-800/50 border-b border-slate-700/50 flex items-center justify-between hover:bg-slate-800/70 transition-colors"
            >
              <h4 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                Driver Analysis — {selected.eligible_count} eligible of {selected.total_drivers} drivers
              </h4>
              <div className="flex items-center gap-3">
                <span className="text-xs text-green-400 font-semibold">Closest: {selected.closest_driver} ({selected.closest_distance?.toFixed(1)} mi)</span>
                {showAnalysis ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
              </div>
            </button>

            {showAnalysis && (
              <>
                {/* Narrative */}
                <div className="px-4 py-3 bg-slate-900/50 border-b border-slate-800/50">
                  <NarrativeBlock selected={selected} tl={tl} />
                </div>

                {/* Driver table */}
                <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-slate-900/95 backdrop-blur">
                      <tr className="text-slate-500 border-b border-slate-700">
                        <th className="text-left py-2 px-3 font-medium">#</th>
                        <th className="text-left py-2 px-3 font-medium">Driver</th>
                        <th className="text-center py-2 px-3 font-medium">Distance</th>
                        <th className="text-center py-2 px-3 font-medium">GPS</th>
                        <th className="text-left py-2 px-3 font-medium">Skills</th>
                        <th className="text-center py-2 px-3 font-medium">Eligible</th>
                        <th className="text-left py-2 px-3 font-medium">Why Not Picked</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sortedDrivers.map((d, i) => {
                        const status = getDriverStatus(d, closestDist)
                        return (
                          <tr key={d.driver_id} className={clsx(
                            'border-b border-slate-800/50',
                            d.is_closest && 'bg-green-500/5',
                          )}>
                            <td className="py-2 px-3 text-slate-600">{i + 1}</td>
                            <td className="py-2 px-3">
                              <div className="flex items-center gap-2">
                                <span className={clsx('w-2 h-2 rounded-full shrink-0',
                                  d.is_closest ? 'bg-green-400' : d.eligible ? 'bg-slate-500' : 'bg-slate-700')} />
                                <span className={clsx('font-medium', d.is_closest ? 'text-green-300' : 'text-slate-300')}>
                                  {d.name}
                                </span>
                              </div>
                              <div className="text-[10px] text-slate-600 ml-4">{d.territory_type}</div>
                            </td>
                            <td className="py-2 px-3 text-center">
                              {d.distance != null ? (
                                <span className={clsx('font-bold',
                                  d.is_closest ? 'text-green-400' :
                                  d.distance < 5 ? 'text-slate-300' : d.distance < 10 ? 'text-slate-400' : 'text-slate-500'
                                )}>{d.distance.toFixed(1)} mi</span>
                              ) : <span className="text-slate-600">—</span>}
                            </td>
                            <td className="py-2 px-3 text-center">
                              {d.has_gps ? <span className="text-emerald-400">Yes</span> : <span className="text-red-400">No</span>}
                            </td>
                            <td className="py-2 px-3">
                              <div className="flex flex-wrap gap-1">
                                {d.skills?.length > 0 ? d.skills.map(s => (
                                  <span key={s} className={clsx('px-1.5 py-0.5 rounded text-[9px] font-medium border',
                                    s.toLowerCase().includes('tow') ? 'bg-red-500/10 text-red-400 border-red-500/20' :
                                    s.toLowerCase().includes('batt') ? 'bg-blue-500/10 text-blue-400 border-blue-500/20' :
                                    'bg-slate-700/50 text-slate-400 border-slate-600/30'
                                  )}>{s}</span>
                                )) : <span className="text-slate-600">None</span>}
                              </div>
                            </td>
                            <td className="py-2 px-3 text-center">
                              {d.eligible ? <CheckCircle2 className="w-4 h-4 text-emerald-400 inline" />
                                          : <XCircle className="w-4 h-4 text-slate-600 inline" />}
                            </td>
                            <td className="py-2 px-3">
                              <span className={clsx('inline-block px-2 py-0.5 rounded text-[10px] font-semibold border', status.bg, status.color)}>
                                {status.tag}
                              </span>
                              <div className="text-[10px] text-slate-600 mt-0.5">{status.reason}</div>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}


// ── Narrative Block ─────────────────────────────────────────────────────────
function NarrativeBlock({ selected, tl }) {
  const lines = []

  // 1. Call received
  lines.push(`Call received at ${tl.created || '?'} for a ${selected.work_type} service at ${selected.address || 'unknown location'}.`)

  // 2. Required skills
  const skills = selected.required_skills || []
  if (skills.length > 0) {
    lines.push(`This call requires: ${skills.join(', ')}.`)
  }

  // 3. Dispatch
  const method = tl.dispatch_method || 'Unknown'
  const mode = tl.auto_assign ? 'automatically' : 'manually'
  if (selected.truck_id) {
    lines.push(`Dispatched via ${method} (${mode}) to Truck ${selected.truck_id.split('-').pop()}.`)
  } else {
    lines.push(`Dispatched via ${method} (${mode}).`)
  }

  // 4. PTA
  if (tl.pta_promised) {
    lines.push(`Member was promised a ${tl.pta_promised}-minute ETA${tl.pta_promised > 45 ? ` (exceeds 45-min SLA target by ${Math.round(tl.pta_promised - 45)} min)` : ' (within SLA target)'}.`)
  }

  // 5. Closest driver analysis
  if (selected.closest_driver && selected.closest_driver !== '?') {
    lines.push(`Closest eligible driver was ${selected.closest_driver} at ${selected.closest_distance?.toFixed(1) || '?'} miles away.`)
    if (tl.dispatched_distance != null) {
      lines.push(`The dispatched truck was ${tl.dispatched_distance.toFixed(1)} mi from the customer when dispatched.`)
    }
  }

  // 6. Driver availability
  const eligible = selected.eligible_count
  const total = selected.total_drivers
  const noGps = (selected.drivers || []).filter(d => !d.has_gps).length
  const noSkill = (selected.drivers || []).filter(d => d.has_gps && !d.has_skills).length
  lines.push(`Of ${total} territory drivers: ${eligible} eligible, ${noGps} without GPS, ${noSkill} missing required skills.`)

  // 7. Response time
  if (tl.response_min) {
    if (tl.sla_met) {
      lines.push(`Driver arrived on location at ${tl.on_location || '?'} — response time was ${tl.response_min} minutes (within 45-min SLA).`)
    } else {
      lines.push(`Driver arrived on location at ${tl.on_location || '?'} — response time was ${tl.response_min} minutes (${tl.response_min - 45} minutes over SLA target).`)
    }
  }

  // 8. Service completion
  if (tl.service_min && selected.status === 'Completed') {
    lines.push(`Service completed at ${tl.completed || '?'} after ${tl.service_min} minutes on-site. Total call time: ${tl.total_min || '?'} minutes.`)
  }

  // 9. Cancellation
  if (tl.cancel_reason) {
    lines.push(`Call was canceled: ${tl.cancel_reason}.`)
  }

  return (
    <div className="space-y-1.5 text-sm text-slate-300 leading-relaxed">
      {lines.map((line, i) => (
        <p key={i} className="flex gap-2">
          <span className="text-slate-600 shrink-0">{i + 1}.</span>
          <span>{line}</span>
        </p>
      ))}
    </div>
  )
}


// ── Timeline Components ─────────────────────────────────────────────────────
function TimeStep({ icon, label, time, sub, color = 'text-slate-400' }) {
  return (
    <div className="flex flex-col items-center min-w-[70px]">
      <div className={clsx('flex items-center gap-1 text-[10px] uppercase tracking-wider', color)}>{icon} {label}</div>
      <div className="text-xs font-bold text-white mt-0.5">{time || '—'}</div>
      {sub && <div className="text-[9px] text-slate-500">{sub}</div>}
    </div>
  )
}

function TimeArrow({ label }) {
  return (
    <div className="flex flex-col items-center px-1">
      <div className="text-[9px] text-slate-500 mb-0.5">{label}</div>
      <div className="w-8 h-px bg-slate-700 relative">
        <div className="absolute right-0 top-[-2px] w-0 h-0 border-l-4 border-l-slate-700 border-y-2 border-y-transparent" />
      </div>
    </div>
  )
}

function SumCard({ label, value, sub, color = 'text-white' }) {
  return (
    <div className="glass rounded-xl p-3">
      <div className="text-[10px] text-slate-400 uppercase tracking-wider">{label}</div>
      <div className={clsx('text-xl font-bold mt-0.5', color)}>
        {value}{sub && <span className="text-sm font-normal text-slate-500 ml-1">{sub}</span>}
      </div>
    </div>
  )
}

function MiniStat({ label, value, sub, color = 'text-slate-200' }) {
  return (
    <div>
      <div className="text-[10px] text-slate-500 uppercase">{label}</div>
      <div className={clsx('text-sm font-semibold', color)}>{value}</div>
      {sub && <div className="text-[10px] text-slate-500">{sub}</div>}
    </div>
  )
}
