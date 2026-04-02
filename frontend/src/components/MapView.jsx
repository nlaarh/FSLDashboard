import { useState, useMemo, useEffect } from 'react'
import { MapContainer, TileLayer, Marker, Popup, Polyline, CircleMarker, GeoJSON, useMap } from 'react-leaflet'
import { clsx } from 'clsx'
import { CheckCircle2, XCircle, ChevronDown, ChevronUp, Clock, Truck, Navigation, AlertTriangle, Zap, Loader2 } from 'lucide-react'
import { fetchMapGrids, fetchMapWeather } from '../api'
import { getMapConfig } from '../mapStyles'
import { TRUCK_SVG, truckIcon, CUSTOMER_ICON, FACILITY_ICON } from '../mapIcons'
import SALink from './SALink'
import { gridStyle, onEachGrid, makeWeatherIcon, getDriverStatus } from './MapLayers'
import { MapLegend, LayerPanel, TimeStep, TimeArrow, SumCard, MiniStat } from './MapLegend'
import MapDriverAnalysis from './MapDriverAnalysis'

// ── View helper ──────────────────────────────────────────────────────────────
function SetView({ center, zoom }) {
  const map = useMap()
  useEffect(() => { map.setView(center, zoom) }, [center[0], center[1], zoom])
  return null
}

export default function MapView({ data }) {
  const { results, summary } = data
  const [selectedIdx, setSelectedIdx] = useState(0)
  const [showAnalysis, setShowAnalysis] = useState(true)
  const [selectedStep, setSelectedStep] = useState(0)

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
  useEffect(() => setSelectedStep(0), [selectedIdx])

  if (!results || results.length === 0) {
    return <div className="text-center py-16 text-slate-500">No SAs with location data found for this date.</div>
  }
  if (!selected) return null

  const center = selected.sa_lat && selected.sa_lon ? [selected.sa_lat, selected.sa_lon] : [42.9, -78.8]
  const tl = selected.timeline || {}
  const isTowbook = tl.dispatch_method === 'Towbook'

  const assignSteps = selected.assign_steps || []
  const hasSteps = assignSteps.length > 0 && !isTowbook
  const currentStep = hasSteps ? (assignSteps[Math.min(selectedStep, assignSteps.length - 1)]) : null

  const sortedDrivers = useMemo(() =>
    [...(selected.drivers || [])].sort((a, b) => {
      if (a.is_closest) return -1
      if (b.is_closest) return 1
      return (a.distance ?? 999) - (b.distance ?? 999)
    }), [selected])

  const mapDrivers = useMemo(() => {
    if (hasSteps && currentStep) {
      return (currentStep.step_drivers || [])
        .filter(d => d.lat && d.lon)
        .map(d => ({
          ...d, eff_lat: d.lat, eff_lon: d.lon, eligible: d.has_skills, is_actual: d.is_assigned,
        }))
    }
    return sortedDrivers.filter(d => d.eff_lat && d.eff_lon)
  }, [hasSteps, currentStep, sortedDrivers])

  const noGpsDrivers = useMemo(() => {
    if (!hasSteps || !currentStep) return []
    return (currentStep.step_drivers || []).filter(d => d.no_gps && d.is_assigned)
  }, [hasSteps, currentStep])

  const driversWithGPS = mapDrivers
  const closestDist = hasSteps && currentStep
    ? (currentStep.step_drivers?.find(d => d.is_closest)?.distance ?? null)
    : selected.closest_distance

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
        {/* SA list sidebar */}
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
                    <span className={clsx('text-[9px] px-1.5 py-0.5 rounded font-semibold',
                      r.channel === 'Towbook' ? 'bg-fuchsia-950/40 text-fuchsia-400' :
                      r.channel === 'Contractor' ? 'bg-amber-950/40 text-amber-400' :
                      'bg-blue-950/40 text-blue-400'
                    )}>{r.channel}</span>
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
                    {r.closest_driver && r.closest_driver !== '?' && r.timeline?.dispatch_method !== 'Towbook' && (
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

        {/* Map + Analysis */}
        <div className="space-y-4">
          {/* SA Header */}
          <div className="glass rounded-xl p-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <h4 className="text-lg font-bold text-white">
                    <SALink number={selected.appointment_number} />
                  </h4>
                  <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300">{selected.work_type}</span>
                  <span className={clsx('text-xs px-2 py-0.5 rounded-full',
                    selected.status === 'Completed' ? 'bg-emerald-500/10 text-emerald-400' :
                    selected.status?.includes('Cancel') ? 'bg-red-500/10 text-red-400' :
                    'bg-amber-500/10 text-amber-400'
                  )}>{selected.status}</span>
                  <span className={clsx('text-xs px-2 py-0.5 rounded-full font-semibold',
                    selected.channel === 'Towbook' ? 'bg-fuchsia-500/10 text-fuchsia-400' :
                    selected.channel === 'Contractor' ? 'bg-amber-500/10 text-amber-400' :
                    'bg-blue-500/10 text-blue-400'
                  )}>{selected.channel}</span>
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
                <div className="text-[10px] text-slate-500">{tl.dispatch_method} {'\u2022'} {tl.schedule_mode}</div>
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
              <MiniStat label="Closest Driver"
                value={selected.timeline?.dispatch_method === 'Towbook' ? 'N/A' : selected.closest_driver}
                sub={selected.timeline?.dispatch_method === 'Towbook' ? 'Towbook' : (selected.closest_distance ? `${selected.closest_distance.toFixed(1)} mi` : '?')}
                color={selected.timeline?.dispatch_method === 'Towbook' ? 'text-slate-500' : 'text-green-400'} />
              <MiniStat label="Facility Dist" value={selected.facility_distance ? `${selected.facility_distance.toFixed(1)} mi` : '?'} />
              <MiniStat label="Required Skills" value={(selected.required_skills || []).join(', ') || 'None'} />
            </div>
          </div>

          {/* Step slider */}
          {hasSteps && (
            <div className="glass rounded-xl px-4 py-3">
              <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-2">
                Assignment Steps — click to see driver positions at each moment
              </div>
              <div className="flex gap-2 flex-wrap">
                {assignSteps.map((step, i) => (
                  <button
                    key={i}
                    onClick={() => setSelectedStep(i)}
                    className={clsx(
                      'flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors',
                      selectedStep === i
                        ? 'bg-brand-600/30 border-brand-500/50 text-brand-300'
                        : 'bg-slate-800/50 border-slate-700/30 text-slate-400 hover:bg-slate-700/50'
                    )}
                  >
                    <span className={clsx('w-2 h-2 rounded-full', step.is_reassignment ? 'bg-amber-400' : 'bg-orange-400')} />
                    <span>{step.is_reassignment ? 'Reassign' : 'Assign'} {step.time}</span>
                    <span className="text-slate-500">{'\u2192'} {step.driver}</span>
                    {step.reason && <span className="text-[9px] text-amber-400/70">{step.reason}</span>}
                    {step.step_drivers?.length > 0 && (
                      <span className="text-[10px] text-slate-600 ml-1">{step.step_drivers.length} drivers</span>
                    )}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Map */}
          <div className="glass rounded-xl overflow-hidden relative" style={{ height: 440 }}>
            <MapContainer key={`${selected.sa_lat}-${selected.sa_lon}`} center={center} zoom={selected.timeline?.dispatch_method === 'Towbook' ? 13 : 11}
              style={{ height: '100%', width: '100%' }} scrollWheelZoom={true}>
              <SetView center={center} zoom={selected.timeline?.dispatch_method === 'Towbook' ? 13 : 11} />
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
                      SA# <SALink number={selected.appointment_number} style={{fontSize:14}} />
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

              {/* Dispatched GPS position */}
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
                const iconType = hasSteps
                  ? (d.is_assigned && d.is_closest ? 'assigned_closest'
                    : d.is_assigned ? 'dispatched'
                    : d.is_closest ? 'closest'
                    : d.has_skills ? 'eligible' : 'ineligible')
                  : (d.is_closest ? 'closest' : d.eligible ? 'eligible' : 'ineligible')
                const shortName = d.name ? d.name.split(' ')[0] : '?'
                const distLabel = d.distance != null ? `${shortName} \u00B7 ${typeof d.distance === 'number' ? d.distance.toFixed(1) : d.distance}mi` : shortName
                const glow = d.is_assigned || d.is_closest
                const status = hasSteps ? null : getDriverStatus(d, closestDist)
                const roleTag = hasSteps
                  ? (d.is_assigned ? 'ASSIGNED' : d.is_closest ? 'CLOSEST' : 'ELIGIBLE')
                  : status?.tag
                const roleColor = hasSteps
                  ? (d.is_assigned && d.is_closest ? '#facc15' : d.is_assigned ? '#f97316' : d.is_closest ? '#22c55e' : '#94a3b8')
                  : (d.is_closest ? '#22c55e' : '#94a3b8')
                return (
                  <Marker key={d.driver_id} position={[d.eff_lat, d.eff_lon]}
                    icon={truckIcon(iconType, distLabel, glow)}
                    zIndexOffset={d.is_assigned ? 950 : d.is_closest ? 900 : d.eligible || d.has_skills ? 500 : 100}>
                    <Popup>
                      <div style={{fontSize:12, minWidth:230, color:'#e2e8f0'}}>
                        <div style={{display:'flex', alignItems:'center', gap:6, marginBottom:4}}>
                          <strong style={{fontSize:14, color: roleColor}}>{d.name}</strong>
                          <span style={{fontWeight:700, fontSize:10, padding:'1px 6px', borderRadius:4,
                            background: d.is_assigned ? 'rgba(249,115,22,0.15)' : d.is_closest ? 'rgba(34,197,94,0.15)' : 'rgba(100,116,139,0.15)',
                            color: roleColor,
                            border: `1px solid ${d.is_assigned ? 'rgba(249,115,22,0.3)' : d.is_closest ? 'rgba(34,197,94,0.3)' : 'rgba(100,116,139,0.3)'}`}}>
                            {roleTag}
                          </span>
                        </div>
                        <div style={{color:'#94a3b8'}}>
                          Distance to SA: <span style={{color:'#e2e8f0', fontWeight:700}}>{d.distance?.toFixed(1) || '?'} mi</span><br/>
                          {!hasSteps && <>
                            Type: {d.territory_type || '?'}<br/>
                            Skills: {d.skills?.length > 0
                              ? <span style={{color:'#60a5fa'}}>{d.skills.join(', ')}</span>
                              : <span style={{color:'#64748b'}}>None</span>}<br/>
                          </>}
                          {hasSteps && currentStep && <>Step: {currentStep.time}<br/></>}
                        </div>
                        {!hasSteps && status && <>
                          <hr style={{border:'none',borderTop:'1px solid #334155',margin:'5px 0'}}/>
                          <div style={{color:'#94a3b8',fontSize:11}}>{status.reason}</div>
                        </>}
                      </div>
                    </Popup>
                  </Marker>
                )
              })}

              {/* Lines to SA */}
              {driversWithGPS.filter(d => d.is_closest && (hasSteps ? !d.is_assigned : true)).map(d => (
                <Polyline key={`cl-${d.driver_id}`}
                  positions={[[d.eff_lat, d.eff_lon], [selected.sa_lat, selected.sa_lon]]}
                  pathOptions={{ color: '#22c55e', weight: 3, opacity: 0.8 }} />
              ))}
              {hasSteps && driversWithGPS.filter(d => d.is_assigned && !d.is_closest).map(d => (
                <Polyline key={`as-${d.driver_id}`}
                  positions={[[d.eff_lat, d.eff_lon], [selected.sa_lat, selected.sa_lon]]}
                  pathOptions={{ color: '#f97316', weight: 3, dashArray: '6,4', opacity: 0.8 }} />
              ))}
              {hasSteps && driversWithGPS.filter(d => d.is_assigned && d.is_closest).map(d => (
                <Polyline key={`ac-${d.driver_id}`}
                  positions={[[d.eff_lat, d.eff_lon], [selected.sa_lat, selected.sa_lon]]}
                  pathOptions={{ color: '#facc15', weight: 3, opacity: 0.9 }} />
              ))}
              {driversWithGPS.filter(d => d.is_closest).map(d => (
                <CircleMarker key={`glow-${d.driver_id}`} center={[d.eff_lat, d.eff_lon]} radius={22}
                  pathOptions={{ color: '#22c55e', weight: 2, fillOpacity: 0.08, opacity: 0.4 }} />
              ))}

              {/* Grid layer */}
              {layers.grid && grids && grids.features.length > 0 && (
                <GeoJSON key="grids" data={grids} style={gridStyle} onEachFeature={onEachGrid} />
              )}

              {/* Weather layer */}
              {layers.weather && weather.map((s, i) => (
                !s.error && s.temp_f != null && (
                  <Marker key={i} position={[s.lat, s.lon]} icon={makeWeatherIcon(s)}>
                    <Popup>
                      <div style={{ fontSize: 12, color: '#e2e8f0' }}>
                        <strong>{s.name}</strong><br />
                        {s.temp_f}{'\u00B0'}F — {s.condition}<br />
                        Wind: {s.wind} mph
                      </div>
                    </Popup>
                  </Marker>
                )
              ))}
            </MapContainer>

            {/* Floating layer panel */}
            <LayerPanel layers={layers} setLayers={setLayers} layerLoading={layerLoading} />
          </div>

          {/* Legend */}
          <MapLegend selected={selected} />

          {/* No GPS warning */}
          {noGpsDrivers.length > 0 && (
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-500/5 border border-amber-500/20 text-xs text-amber-400">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
              <span>
                {noGpsDrivers.map(d => d.name).join(', ')} — no GPS location at dispatch time.
                Driver was manually assigned by dispatcher but had no FSL Track GPS history at that moment. Not shown on map.
              </span>
            </div>
          )}

          {/* Driver Analysis */}
          <MapDriverAnalysis
            selected={selected} tl={tl} isTowbook={isTowbook}
            hasSteps={hasSteps} assignSteps={assignSteps} currentStep={currentStep}
            sortedDrivers={sortedDrivers} closestDist={closestDist}
            showAnalysis={showAnalysis} setShowAnalysis={setShowAnalysis}
            selectedStep={selectedStep} setSelectedStep={setSelectedStep}
          />
        </div>
      </div>
    </div>
  )
}
