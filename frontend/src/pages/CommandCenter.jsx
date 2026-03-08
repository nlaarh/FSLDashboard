import React, { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { MapContainer, TileLayer, CircleMarker, Popup, Tooltip, Marker, Polyline, useMap, GeoJSON } from 'react-leaflet'
import L from 'leaflet'
import { clsx } from 'clsx'
import { fetchCommandCenter, lookupSA, fetchMapGrids, fetchMapDrivers, fetchMapWeather, fetchOpsGarages, fetchOpsBrief } from '../api'
import { getMapConfig } from '../mapStyles'
import {
  Loader2, RefreshCw, Radio, CheckCircle2, AlertTriangle,
  ChevronRight, Search, MapPin, Clock, FileText,
  ChevronDown, ChevronUp, Crosshair, X, Truck, Layers,
  Zap, Shield, Navigation, Users, TrendingUp, AlertCircle, ArrowRight
} from 'lucide-react'

// ── Constants ────────────────────────────────────────────────────────────────

const STATUS_COLORS = {
  good:     { fill: '#22c55e', border: '#16a34a', bg: 'bg-emerald-500' },
  behind:   { fill: '#f59e0b', border: '#d97706', bg: 'bg-amber-500' },
  critical: { fill: '#ef4444', border: '#dc2626', bg: 'bg-red-500' },
}
const SA_COLORS = { Dispatched: '#3b82f6', Assigned: '#8b5cf6', Completed: '#22c55e', 'No-Show': '#f97316' }

const TERRITORY_LEGEND = [
  { color: '#22c55e', label: 'On Track' },
  { color: '#f59e0b', label: 'Behind' },
  { color: '#ef4444', label: 'Critical' },
]
const MAP_LEGEND = [
  { color: '#3b82f6', label: 'Dispatched' },
  { color: '#8b5cf6', label: 'Assigned' },
  { color: '#22c55e', label: 'Completed' },
  { color: '#ef4444', label: 'Critical' },
]

const WINDOWS = [
  { label: '2h', hours: 2 }, { label: '4h', hours: 4 }, { label: '8h', hours: 8 },
  { label: '12h', hours: 12 }, { label: '24h', hours: 24 },
  { label: '48h', hours: 48 }, { label: '7d',  hours: 168 },
]

// Map tiles from shared config (changeable in Admin)
const REFRESH_MS = 60 * 1000 // 1 min for ops brief

function fmtPhone(p) {
  if (!p) return null
  const d = p.replace(/\D/g, '')
  if (d.length === 10) return `(${d.slice(0,3)}) ${d.slice(3,6)}-${d.slice(6)}`
  return p
}

function fmtWait(min) {
  if (!min || min <= 0) return '—'
  const h = Math.floor(min / 60)
  const m = min % 60
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

// ── Map icon helpers ─────────────────────────────────────────────────────────

const WMO_EMOJI = {
  0:'☀️',1:'🌤️',2:'⛅',3:'☁️',45:'🌫️',48:'🌫️',
  51:'🌦️',53:'🌦️',55:'🌧️',61:'🌧️',63:'🌧️',65:'⛈️',
  66:'🌧️',67:'⛈️',71:'🌨️',73:'❄️',75:'❄️',77:'🌨️',
  80:'🌦️',81:'🌧️',82:'⛈️',85:'🌨️',86:'❄️',
  95:'⛈️',96:'⛈️',99:'⛈️',
}

function makeDriverCarIcon(driverType, isIdle) {
  const color = isIdle ? '#22c55e' : (driverType || '').toLowerCase().includes('tow') ? '#f59e0b' : '#818cf8'
  return L.divIcon({
    className: '',
    iconSize: [24, 20], iconAnchor: [12, 10], popupAnchor: [0, -12],
    html: `<svg width="24" height="20" viewBox="0 0 24 20" fill="none">
      <path d="M3 12h18v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4z" fill="${color}" stroke="#0f172a" stroke-width="1"/>
      <path d="M5 12l2-6h10l2 6" fill="${color}" stroke="#0f172a" stroke-width="1"/>
      <rect x="6" y="7" width="4" height="3" rx="0.5" fill="#0f172a" opacity="0.5"/>
      <rect x="14" y="7" width="4" height="3" rx="0.5" fill="#0f172a" opacity="0.5"/>
      <circle cx="7" cy="18" r="2" fill="#0f172a" stroke="${color}" stroke-width="1"/>
      <circle cx="17" cy="18" r="2" fill="#0f172a" stroke="${color}" stroke-width="1"/>
      ${isIdle ? '<circle cx="22" cy="2" r="3" fill="#22c55e" stroke="#0f172a" stroke-width="1"/>' : ''}
    </svg>`,
  })
}

function makeWeatherMarkerIcon(s) {
  const emoji = WMO_EMOJI[s.weather_code] || '🌡️'
  return L.divIcon({
    className: '',
    iconSize: [50, 30], iconAnchor: [25, 15],
    html: `<div style="background:rgba(15,23,42,0.85);border:1px solid rgba(71,85,105,0.5);border-radius:8px;padding:2px 6px;text-align:center;white-space:nowrap;font-size:11px;color:#e2e8f0;backdrop-filter:blur(4px)">
      ${emoji} ${s.temp_f != null ? Math.round(s.temp_f) + '°' : ''}
      ${s.wind_mph ? `<span style="color:#94a3b8;font-size:9px">${Math.round(s.wind_mph)}mph</span>` : ''}
    </div>`,
  })
}

function makeGarageIcon(isPrimary, isTowbook) {
  if (isTowbook) {
    // Towbook = wrench/garage icon in orange tones
    const color = isPrimary ? '#f97316' : '#78716c'
    return L.divIcon({
      className: '',
      iconSize: [22, 22], iconAnchor: [11, 11], popupAnchor: [0, -12],
      html: `<div style="width:20px;height:20px;background:${color}22;border:2px solid ${color};border-radius:50%;display:flex;align-items:center;justify-content:center">
        <svg width="10" height="10" viewBox="0 0 16 16" fill="${color}">
          <path d="M14.7 6.3a1 1 0 0 0 0-1.4l-3.6-3.6a1 1 0 0 0-1.4 0L8.3 2.7 6.6 1H4v2.6l1.7 1.7-5.4 5.4a1 1 0 0 0 0 1.4l2.6 2.6a1 1 0 0 0 1.4 0l5.4-5.4 1.7 1.7H14v-2.6l-1.7-1.7z"/>
        </svg>
      </div>`,
    })
  }
  // Fleet = square garage icon in green tones
  const color = isPrimary ? '#22c55e' : '#64748b'
  return L.divIcon({
    className: '',
    iconSize: [18, 18], iconAnchor: [9, 9], popupAnchor: [0, -10],
    html: `<div style="width:16px;height:16px;background:${color}22;border:2px solid ${color};border-radius:3px;display:flex;align-items:center;justify-content:center">
      <div style="width:6px;height:6px;background:${color};border-radius:1px"></div>
    </div>`,
  })
}

function gridFeatureStyle(isDark) {
  return (feature) => ({
    color: isDark ? '#818cf8' : '#4f46e5',
    weight: isDark ? 1 : 1.5,
    opacity: isDark ? 0.4 : 0.5,
    fillOpacity: isDark ? 0.04 : 0.06,
    fillColor: isDark ? '#818cf8' : '#4f46e5',
    dashArray: '6,4',
  })
}
function onEachGridFeature(feature, layer) {
  if (feature.properties?.Name) {
    layer.bindTooltip(feature.properties.Name, { sticky: true, className: 'cc-tooltip', opacity: 0.95 })
  }
}

// Driver truck icon for SA lookup
function driverIcon(dist, isClosest) {
  const color = isClosest ? '#22c55e' : '#94a3b8'
  return L.divIcon({
    className: '',
    iconSize: [28, 34], iconAnchor: [14, 34], popupAnchor: [0, -34],
    html: `<div style="position:relative;text-align:center">
      <svg width="28" height="24" viewBox="0 0 28 24">
        <rect x="2" y="6" width="24" height="14" rx="3" fill="${color}" stroke="#fff" stroke-width="1.5"/>
        <rect x="18" y="3" width="10" height="10" rx="2" fill="${color}" stroke="#fff" stroke-width="1.5"/>
        <circle cx="8" cy="22" r="3" fill="#334155" stroke="${color}" stroke-width="1.5"/>
        <circle cx="20" cy="22" r="3" fill="#334155" stroke="${color}" stroke-width="1.5"/>
      </svg>
      ${dist != null ? `<div style="font-size:8px;color:${color};font-weight:700;margin-top:-2px">${dist} mi</div>` : ''}
    </div>`,
  })
}

const customerIcon = L.divIcon({
  className: '',
  iconSize: [20, 28], iconAnchor: [10, 28], popupAnchor: [0, -28],
  html: `<div style="text-align:center">
    <svg width="20" height="28" viewBox="0 0 20 28">
      <path d="M10 0C4.5 0 0 4.5 0 10c0 7 10 18 10 18s10-11 10-18C20 4.5 15.5 0 10 0z" fill="#ef4444" stroke="#fff" stroke-width="1.5"/>
      <circle cx="10" cy="10" r="4" fill="#fff"/>
    </svg>
  </div>`,
})

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════════════════════

export default function CommandCenter() {
  const navigate = useNavigate()

  // ── Map style (from Admin settings)
  const [mapConfig, setMapConfig] = useState(getMapConfig)
  useEffect(() => {
    const handler = () => setMapConfig(getMapConfig())
    window.addEventListener('mapStyleChanged', handler)
    return () => window.removeEventListener('mapStyleChanged', handler)
  }, [])

  // ── Core data
  const [data, setData] = useState(null)        // command-center territories
  const [brief, setBrief] = useState(null)       // ops brief
  const [loading, setLoading] = useState(true)
  const [briefLoading, setBriefLoading] = useState(true)
  const [error, setError] = useState(null)
  const [hours, setHours] = useState(4)
  const [lastRefresh, setLastRefresh] = useState(null)
  const [countdown, setCountdown] = useState(60)

  // ── Panel state
  const [panelTab, setPanelTab] = useState('ops')    // ops | queue | zones | search
  const [panelOpen, setPanelOpen] = useState(true)
  const [focusCenter, setFocusCenter] = useState(null)

  // ── SA lookup
  const [saQuery, setSaQuery] = useState('')
  const [saResult, setSaResult] = useState(null)
  const [saLoading, setSaLoading] = useState(false)
  const [saError, setSaError] = useState(null)

  // ── Map layers
  const [layers, setLayers] = useState({ grid: false, drivers: true, weather: false, activeSAs: true, garages: false, towbook: false })
  const [grids, setGrids] = useState(null)
  const [allDrivers, setAllDrivers] = useState([])
  const [mapWeather, setMapWeather] = useState([])
  const [allGarages, setAllGarages] = useState([])
  const [layerLoading, setLayerLoading] = useState({})

  // ── Filters
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [showSADots, setShowSADots] = useState(true)
  const [saStatusFilter, setSaStatusFilter] = useState('open')

  // ── Load command center data + ops brief in parallel
  const load = useCallback(() => {
    setLoading(true)
    setBriefLoading(true)
    setError(null)
    fetchCommandCenter(hours)
      .then(d => { setData(d); setLastRefresh(new Date()); setCountdown(60) })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
    fetchOpsBrief()
      .then(setBrief)
      .catch(() => {})
      .finally(() => setBriefLoading(false))
  }, [hours])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    const iv = setInterval(load, REFRESH_MS)
    return () => clearInterval(iv)
  }, [load])
  useEffect(() => {
    const t = setInterval(() => setCountdown(c => Math.max(0, c - 1)), 1000)
    return () => clearInterval(t)
  }, [])

  // ── Layer lazy-loading
  useEffect(() => {
    if (!layers.grid || grids !== null) return
    setLayerLoading(l => ({ ...l, grid: true }))
    fetchMapGrids().then(d => { setGrids(d); setLayerLoading(l => ({ ...l, grid: false })) }).catch(() => setLayerLoading(l => ({ ...l, grid: false })))
  }, [layers.grid])
  useEffect(() => {
    if (!layers.drivers || allDrivers.length > 0) return
    setLayerLoading(l => ({ ...l, drivers: true }))
    fetchMapDrivers().then(d => { setAllDrivers(d); setLayerLoading(l => ({ ...l, drivers: false })) }).catch(() => setLayerLoading(l => ({ ...l, drivers: false })))
  }, [layers.drivers])
  useEffect(() => {
    if (!layers.weather || mapWeather.length > 0) return
    setLayerLoading(l => ({ ...l, weather: true }))
    fetchMapWeather().then(d => { setMapWeather(d); setLayerLoading(l => ({ ...l, weather: false })) }).catch(() => setLayerLoading(l => ({ ...l, weather: false })))
  }, [layers.weather])
  useEffect(() => {
    if ((!layers.garages && !layers.towbook) || allGarages.length > 0) return
    setLayerLoading(l => ({ ...l, garages: true }))
    fetchOpsGarages().then(d => { setAllGarages(d); setLayerLoading(l => ({ ...l, garages: false })) }).catch(() => setLayerLoading(l => ({ ...l, garages: false })))
  }, [layers.garages, layers.towbook])

  const searchSA = () => {
    if (!saQuery.trim()) return
    setSaLoading(true); setSaError(null); setSaResult(null)
    lookupSA(saQuery.trim())
      .then(r => { setSaResult(r); if (r.sa.lat && r.sa.lon) setFocusCenter([r.sa.lat, r.sa.lon]) })
      .catch(e => setSaError(e.response?.data?.detail || e.message))
      .finally(() => setSaLoading(false))
  }
  const clearSA = () => { setSaResult(null); setSaError(null); setSaQuery('') }

  const territories = data?.territories || []
  const summary = data?.summary || {}
  const fleet = brief?.fleet || {}
  const demand = brief?.demand || {}
  const suggestions = brief?.suggestions || []
  const openCalls = brief?.open_calls || []
  const atRisk = brief?.at_risk || []
  const zones = brief?.zones || []

  const filtered = territories.filter(t => {
    if (statusFilter !== 'all' && t.status !== statusFilter) return false
    if (search && !t.name.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  // Build idle driver set for map highlighting
  const idleDriverIds = new Set((fleet.idle_drivers || []).map(d => d.id))

  return (
    <div className="-mx-6 -mt-6 flex" style={{ height: 'calc(100vh - 56px)' }}>

      {/* ══════════════════════════════════════════════════════════════════════ */}
      {/* MAP                                                                  */}
      {/* ══════════════════════════════════════════════════════════════════════ */}
      <div className="flex-1 relative cc-map">
        <MapContainer center={[42.9, -78.8]} zoom={9} className="w-full h-full"
                      zoomControl={false} attributionControl={false}>
          <TileLayer key={mapConfig.url} url={mapConfig.url}
            className={mapConfig.filter ? 'dynamic-map-tiles' : ''}
            {...(mapConfig.noSubdomains ? { subdomains: [] } : {})} />
          {mapConfig.filter && (
            <style>{`.dynamic-map-tiles { filter: ${mapConfig.filter}; }`}</style>
          )}
          <AutoBounds territories={territories} />
          <FlyTo center={focusCenter} />

          {/* Territory circles */}
          {territories.map(t => (
            <CircleMarker key={t.id} center={[t.lat, t.lon]}
              radius={Math.max(8, Math.min(35, Math.sqrt(t.total) * 2.5))}
              pathOptions={{
                color: STATUS_COLORS[t.status]?.border || '#6b7280',
                fillColor: STATUS_COLORS[t.status]?.fill || '#6b7280',
                fillOpacity: 0.25, weight: 2, opacity: 0.8,
              }}
              eventHandlers={{ click: () => navigate(`/garage/${t.id}`) }}
            >
              <Popup><TerritoryPopup t={t} /></Popup>
            </CircleMarker>
          ))}

          {/* SA dots */}
          {showSADots && !saResult && territories.flatMap(t =>
            (t.sa_points || []).filter(sa => saStatusFilter === 'all' || ['Dispatched', 'Assigned'].includes(sa.status)).map((sa, i) => (
              <CircleMarker key={`${t.id}-${i}`} center={[sa.lat, sa.lon]} radius={3}
                pathOptions={{
                  color: SA_COLORS[sa.status] || '#6b7280',
                  fillColor: SA_COLORS[sa.status] || '#6b7280',
                  fillOpacity: 0.7, weight: 1, opacity: 0.9,
                }}>
                <Popup>
                  <div style={{ fontSize: 12, color: '#e2e8f0' }}>
                    <div style={{ fontWeight: 700 }}>{sa.work_type}</div>
                    <div>{sa.status} at {sa.time}</div>
                  </div>
                </Popup>
              </CircleMarker>
            ))
          )}

          {/* SA Lookup markers */}
          {saResult && saResult.sa.lat && saResult.sa.lon && (() => {
            const closestDriver = saResult.drivers.find(d => d.lat && d.lon)
            return (
              <>
                <Marker position={[saResult.sa.lat, saResult.sa.lon]} icon={customerIcon}>
                  <Tooltip direction="top" offset={[0, -30]} opacity={0.95} className="cc-tooltip">
                    <div style={{ fontSize: 12, color: '#e2e8f0', minWidth: 220, padding: 2 }}>
                      <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 3 }}>{saResult.sa.customer || 'Member'}</div>
                      <div style={{ color: '#94a3b8' }}>
                        {saResult.sa.address}{saResult.sa.zip && ` (${saResult.sa.zip})`}<br />
                        SA# <span style={{ color: '#e2e8f0', fontWeight: 600 }}>{saResult.sa.number}</span>
                        {' — '}<span style={{ color: '#e2e8f0' }}>{saResult.sa.work_type}</span><br />
                        Status: <span style={{ color: '#e2e8f0', fontWeight: 600 }}>{saResult.sa.status}</span>
                        {saResult.sa.response_min && (
                          <><br />Response: <span style={{ color: saResult.sa.response_min <= 45 ? '#22c55e' : '#ef4444', fontWeight: 700 }}>{saResult.sa.response_min} min</span></>
                        )}
                      </div>
                      {closestDriver && (
                        <div style={{ marginTop: 5, padding: '3px 6px', background: 'rgba(34,197,94,0.1)', borderRadius: 5, border: '1px solid rgba(34,197,94,0.25)' }}>
                          <span style={{ color: '#22c55e', fontWeight: 700, fontSize: 11 }}>Closest: </span>
                          <span style={{ color: '#22c55e', fontWeight: 600 }}>{closestDriver.name}</span>
                          <span style={{ color: '#e2e8f0', fontWeight: 700 }}> — {closestDriver.distance ?? '?'} mi</span>
                        </div>
                      )}
                    </div>
                  </Tooltip>
                </Marker>
                {closestDriver && (
                  <>
                    <Polyline positions={[[closestDriver.lat, closestDriver.lon], [saResult.sa.lat, saResult.sa.lon]]}
                      pathOptions={{ color: '#22c55e', weight: 3, opacity: 0.7, dashArray: '8,6' }} />
                    <CircleMarker center={[closestDriver.lat, closestDriver.lon]} radius={18}
                      pathOptions={{ color: '#22c55e', weight: 2, fillOpacity: 0.06, opacity: 0.35 }} />
                  </>
                )}
              </>
            )
          })()}

          {saResult && saResult.drivers.filter(d => d.lat && d.lon).map((d, i) => (
            <React.Fragment key={d.id}>
              <Marker position={[d.lat, d.lon]} icon={driverIcon(d.distance, i === 0)}>
                <Tooltip direction="top" offset={[0, -36]} opacity={0.95} className="cc-tooltip">
                  <div style={{ fontSize: 12, color: '#e2e8f0', minWidth: 210, padding: 2 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
                      <strong style={{ fontSize: 14, color: i === 0 ? '#22c55e' : '#e2e8f0' }}>{d.name}</strong>
                      {i === 0 && <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: 'rgba(34,197,94,0.15)', color: '#22c55e', border: '1px solid rgba(34,197,94,0.3)' }}>CLOSEST</span>}
                    </div>
                    <div style={{ color: '#94a3b8' }}>
                      Distance: <span style={{ color: '#e2e8f0', fontWeight: 700 }}>{d.distance ?? '?'} mi</span><br />
                      GPS: {d.gps_time} — {d.territory_type}
                    </div>
                    {d.next_job ? (
                      <div style={{ marginTop: 4, padding: '3px 6px', background: 'rgba(234,179,8,0.08)', borderRadius: 5, border: '1px solid rgba(234,179,8,0.2)' }}>
                        <span style={{ color: '#eab308', fontWeight: 700, fontSize: 10 }}>NEXT: </span>
                        <span style={{ color: '#94a3b8' }}>SA# {d.next_job.number} — {d.next_job.work_type}</span>
                      </div>
                    ) : (
                      <div style={{ marginTop: 3, color: '#22c55e', fontSize: 11, fontWeight: 600 }}>Available</div>
                    )}
                  </div>
                </Tooltip>
              </Marker>
              {d.next_job && d.next_job.lat && d.next_job.lon && (
                <Polyline positions={[[d.lat, d.lon], [d.next_job.lat, d.next_job.lon]]}
                  pathOptions={{ color: '#eab308', weight: 2, opacity: 0.5, dashArray: '6,4' }} />
              )}
            </React.Fragment>
          ))}

          {/* Grid layer */}
          {layers.grid && grids && grids.features.length > 0 && (
            <GeoJSON key={`grids-${mapConfig.dark ? 'dark' : 'light'}`} data={grids} style={gridFeatureStyle(mapConfig.dark !== false)} onEachFeature={onEachGridFeature} />
          )}

          {/* Driver layer (green dot = idle, colored = busy) */}
          {layers.drivers && !saResult && allDrivers.map(d => (
            <Marker key={d.id} position={[d.lat, d.lon]} icon={makeDriverCarIcon(d.driver_type, idleDriverIds.has(d.id))}>
              <Tooltip direction="top" offset={[0, -14]} sticky>
                <div style={{ fontSize: 11, lineHeight: 1.6, minWidth: 170 }}>
                  <div style={{ fontWeight: 700, fontSize: 12, marginBottom: 2 }}>{d.name}</div>
                  {d.truck && <div style={{ color: '#94a3b8', fontSize: 10 }}>Truck: {d.truck}</div>}
                  {d.truck_capabilities && <div style={{ color: '#94a3b8', fontSize: 10 }}>Cap: {d.truck_capabilities}</div>}
                  {d.phone && <div>{fmtPhone(d.phone)}</div>}
                  {d.driver_type && <div style={{ color: '#94a3b8' }}>{d.driver_type}</div>}
                  <div style={{ color: idleDriverIds.has(d.id) ? '#22c55e' : '#64748b', fontSize: 10, fontWeight: 600, marginTop: 2 }}>
                    {idleDriverIds.has(d.id) ? 'IDLE — Available' : 'Busy'}
                  </div>
                  <div style={{ color: '#64748b', fontSize: 10 }}>GPS: {d.gps_time}</div>
                  <div style={{ color: '#64748b', fontSize: 9 }}>{d.lat.toFixed(4)}, {d.lon.toFixed(4)}</div>
                </div>
              </Tooltip>
            </Marker>
          ))}

          {/* Weather layer */}
          {layers.weather && mapWeather.map((s, i) => (
            !s.error && s.temp_f != null && (
              <Marker key={i} position={[s.lat, s.lon]} icon={makeWeatherMarkerIcon(s)}>
                <Popup>
                  <div style={{ fontSize: 12, color: '#e2e8f0' }}>
                    <strong>{s.name}</strong><br />
                    {s.temp_f}°F — {s.condition}<br />
                    Wind: {s.wind_mph} mph
                    {s.snowfall_cm > 0 && <><br />Snow: {s.snowfall_cm} cm</>}
                  </div>
                </Popup>
              </Marker>
            )
          ))}

          {/* Fleet Garages layer */}
          {layers.garages && allGarages.filter(g => g.dispatch_method !== 'Towbook').map(g => {
            if (!g.lat || !g.lon) return null
            return (
              <Marker key={`garage-${g.id}`} position={[g.lat, g.lon]} icon={makeGarageIcon(g.primary_zones > 0, false)}>
                <Tooltip direction="top" offset={[0, -10]} sticky className="cc-tooltip">
                  <div style={{ fontSize: 11, lineHeight: 1.5, minWidth: 160 }}>
                    <div style={{ fontWeight: 700, fontSize: 12 }}>{g.name}</div>
                    {g.address && <div style={{ color: '#94a3b8', fontSize: 10 }}>{g.address}</div>}
                    <div style={{ color: '#22c55e', fontSize: 10 }}>Fleet (Field Services)</div>
                    {g.phone && <div style={{ fontSize: 10 }}>{fmtPhone(g.phone)}</div>}
                    <div style={{ color: '#94a3b8', fontSize: 10 }}>P: {g.primary_zones} · S: {g.secondary_zones} zones</div>
                  </div>
                </Tooltip>
              </Marker>
            )
          })}

          {/* Towbook Garages layer */}
          {layers.towbook && allGarages.filter(g => g.dispatch_method === 'Towbook').map(g => {
            if (!g.lat || !g.lon) return null
            return (
              <Marker key={`tb-${g.id}`} position={[g.lat, g.lon]} icon={makeGarageIcon(g.primary_zones > 0, true)}>
                <Tooltip direction="top" offset={[0, -12]} sticky className="cc-tooltip">
                  <div style={{ fontSize: 11, lineHeight: 1.5, minWidth: 160 }}>
                    <div style={{ fontWeight: 700, fontSize: 12 }}>{g.name}</div>
                    {g.address && <div style={{ color: '#94a3b8', fontSize: 10 }}>{g.address}</div>}
                    <div style={{ color: '#f97316', fontSize: 10 }}>Towbook (Contractor)</div>
                    {g.phone && <div style={{ fontSize: 10 }}>{fmtPhone(g.phone)}</div>}
                    <div style={{ color: '#94a3b8', fontSize: 10 }}>P: {g.primary_zones} · S: {g.secondary_zones} zones</div>
                  </div>
                </Tooltip>
              </Marker>
            )
          })}

          {/* Active SAs layer */}
          {layers.activeSAs && data && territories.flatMap(t =>
            (t.sa_points || []).map((pt, i) => {
              if (!pt.lat || !pt.lon) return null
              const isOpen = ['Dispatched', 'Assigned'].includes(pt.status)
              const color = isOpen ? '#3b82f6' : pt.status === 'Completed' ? '#10b981' : '#ef4444'
              return (
                <CircleMarker key={`sa-${t.id}-${i}`} center={[pt.lat, pt.lon]}
                  radius={isOpen ? 5 : 3} pathOptions={{ color, fillColor: color, fillOpacity: isOpen ? 0.9 : 0.5, weight: 1 }}>
                  <Tooltip direction="top" offset={[0, -5]}>
                    <span style={{ fontSize: 11 }}>{pt.work_type || 'SA'} — {pt.status}<br />{pt.time || ''} · {t.name}</span>
                  </Tooltip>
                </CircleMarker>
              )
            })
          )}
        </MapContainer>

        {/* ── Top Stats Bar ──────────────────────────────────────────── */}
        <div className="absolute top-3 left-3 right-3 z-[1000] pointer-events-none">
          <div className="pointer-events-auto inline-flex items-center gap-3 bg-slate-900/90 backdrop-blur-md
                          border border-slate-700/50 rounded-xl px-4 py-2.5 shadow-2xl">
            {loading && !data ? (
              <div className="flex items-center gap-2 text-sm text-slate-400">
                <Loader2 className="w-4 h-4 animate-spin" /> Loading...
              </div>
            ) : (
              <>
                {/* Fleet status */}
                <div className="flex items-center gap-1.5">
                  <Truck className="w-3.5 h-3.5 text-amber-400" />
                  <span className="text-sm font-bold text-white">{fleet.total || '—'}</span>
                  <span className="text-[9px] text-slate-500">drivers</span>
                </div>
                {fleet.idle != null && (
                  <>
                    <span className="text-emerald-400 text-xs font-bold">{fleet.idle} idle</span>
                    <span className="text-amber-400 text-xs font-bold">{fleet.busy} busy</span>
                  </>
                )}
                <Div />
                <StatChip icon={Radio} label="Open" value={summary.total_open} color="text-blue-400" />
                <StatChip icon={CheckCircle2} label="Done" value={summary.total_completed} color="text-emerald-400" />
                <StatChip label="Total" value={summary.total_sas} color="text-slate-300" />
                <Div />
                {/* Demand indicator */}
                {demand.trend && (
                  <div className={clsx('flex items-center gap-1 px-2 py-0.5 rounded-lg text-[10px] font-bold',
                    demand.trend === 'surge' ? 'bg-red-950/60 text-red-400 border border-red-800/40' :
                    demand.trend === 'above' ? 'bg-amber-950/60 text-amber-400 border border-amber-800/40' :
                    demand.trend === 'quiet' ? 'bg-blue-950/60 text-blue-400 border border-blue-800/40' :
                    'bg-slate-800/60 text-slate-400 border border-slate-700/40')}>
                    <TrendingUp className="w-3 h-3" />
                    {demand.pct_vs_normal > 0 ? '+' : ''}{demand.pct_vs_normal}% vs normal
                  </div>
                )}
                <Div />
                <div className="flex gap-0.5">
                  {WINDOWS.map(w => (
                    <button key={w.hours} onClick={() => setHours(w.hours)}
                      className={clsx('px-2 py-0.5 rounded text-[10px] font-semibold transition-all',
                        hours === w.hours ? 'bg-brand-600 text-white' : 'text-slate-500 hover:text-white hover:bg-slate-700'
                      )}>{w.label}</button>
                  ))}
                </div>
                <button onClick={load} className="p-1.5 rounded-lg hover:bg-slate-700 transition-colors"
                  title={`Refresh (${countdown}s)`}>
                  <RefreshCw className={clsx('w-3.5 h-3.5 text-slate-400', loading && 'animate-spin')} />
                </button>
                <span className="text-[9px] text-slate-600 font-mono">{countdown}s</span>
              </>
            )}
          </div>
        </div>

        {/* ══════════════════════════════════════════════════════════════ */}
        {/* LEFT PANEL — Ops Brief                                        */}
        {/* ══════════════════════════════════════════════════════════════ */}
        {data && (
          <div className="absolute top-16 left-3 z-[1000] w-[340px]">
            <div className="bg-slate-900/95 backdrop-blur-xl border border-slate-600/40 rounded-t-xl
                            shadow-[0_8px_32px_rgba(0,0,0,0.5)] px-3 py-2 flex items-center gap-2">
              <button onClick={() => setPanelOpen(p => !p)} className="flex items-center gap-2 flex-1 text-left">
                <Shield className="w-4 h-4 text-brand-400" />
                <span className="text-xs font-bold text-white tracking-wide uppercase">Ops Cockpit</span>
                {atRisk.length > 0 && (
                  <span className="px-1.5 py-0.5 rounded-full bg-red-500/20 text-red-400 text-[9px] font-bold animate-pulse">
                    {atRisk.length} at risk
                  </span>
                )}
                {panelOpen ? <ChevronUp className="w-3 h-3 text-slate-400 ml-auto" /> : <ChevronDown className="w-3 h-3 text-slate-400 ml-auto" />}
              </button>
            </div>

            {panelOpen && (
              <div className="bg-slate-900/95 backdrop-blur-xl border border-t-0 border-slate-600/40 rounded-b-xl
                              shadow-[0_8px_32px_rgba(0,0,0,0.5)]">
                {/* Tab bar */}
                <div className="flex border-b border-slate-800/60 px-1 pt-1">
                  {[
                    { key: 'ops', label: 'Actions', icon: Zap },
                    { key: 'queue', label: `Queue (${openCalls.length})`, icon: Clock },
                    { key: 'zones', label: `Zones (${zones.length})`, icon: MapPin },
                    { key: 'search', label: 'Lookup', icon: Crosshair },
                  ].map(tab => (
                    <button key={tab.key} onClick={() => setPanelTab(tab.key)}
                      className={clsx('flex items-center gap-1 px-2 py-1.5 text-[10px] font-semibold rounded-t-lg transition-all',
                        panelTab === tab.key
                          ? 'bg-slate-800/60 text-white border-b-2 border-brand-500'
                          : 'text-slate-500 hover:text-slate-300'
                      )}>
                      <tab.icon className="w-3 h-3" />
                      {tab.label}
                    </button>
                  ))}
                </div>

                <div className="max-h-[60vh] overflow-y-auto">

                  {/* ── ACTIONS TAB ──────────────────────────────────── */}
                  {panelTab === 'ops' && (
                    <div className="px-3 py-3 space-y-3">
                      {/* Fleet status bar */}
                      <div className="flex items-center gap-2">
                        <div className="flex-1 flex gap-1 h-3 rounded-full overflow-hidden bg-slate-800">
                          {fleet.busy > 0 && <div className="bg-amber-500 transition-all" style={{ width: `${100*fleet.busy/Math.max(fleet.total,1)}%` }} />}
                          {fleet.idle > 0 && <div className="bg-emerald-500 transition-all" style={{ width: `${100*fleet.idle/Math.max(fleet.total,1)}%` }} />}
                        </div>
                        <span className="text-[10px] text-slate-400 whitespace-nowrap">
                          <span className="text-emerald-400 font-bold">{fleet.idle}</span> idle / <span className="text-amber-400 font-bold">{fleet.busy}</span> busy
                        </span>
                      </div>

                      {/* Demand vs baseline */}
                      {demand.normal_for_hour > 0 && (
                        <div className={clsx('rounded-lg px-3 py-2 text-xs border',
                          demand.trend === 'surge' ? 'bg-red-950/40 border-red-800/30 text-red-300' :
                          demand.trend === 'above' ? 'bg-amber-950/40 border-amber-800/30 text-amber-300' :
                          demand.trend === 'quiet' ? 'bg-blue-950/40 border-blue-800/30 text-blue-300' :
                          'bg-slate-800/40 border-slate-700/30 text-slate-300')}>
                          <div className="flex items-center gap-1.5">
                            <TrendingUp className="w-3.5 h-3.5" />
                            <span className="font-bold">{demand.current_hour_calls}</span> calls this hour
                            <span className="text-slate-500 ml-auto">norm: {demand.normal_for_hour}</span>
                          </div>
                          {demand.trend === 'surge' && <div className="text-[10px] mt-1">Volume {demand.pct_vs_normal}% above normal — consider activating backup drivers</div>}
                        </div>
                      )}

                      {/* Suggestions */}
                      {suggestions.length === 0 && !briefLoading && (
                        <div className="text-center py-4 text-xs text-emerald-400/80">
                          <CheckCircle2 className="w-5 h-5 mx-auto mb-1 text-emerald-500" />
                          All clear — no actions needed right now
                        </div>
                      )}
                      {briefLoading && suggestions.length === 0 && (
                        <div className="text-center py-4 text-xs text-slate-500">
                          <Loader2 className="w-4 h-4 animate-spin mx-auto mb-1" /> Analyzing fleet...
                        </div>
                      )}
                      {suggestions.map((s, i) => (
                        <SuggestionCard key={i} s={s} />
                      ))}

                      <div className="text-[10px] text-slate-600 pt-1 border-t border-slate-800/50">
                        {lastRefresh && <>Updated: {lastRefresh.toLocaleTimeString()}</>}
                        {' · '}Auto-refresh {countdown}s
                      </div>
                    </div>
                  )}

                  {/* ── QUEUE TAB ────────────────────────────────────── */}
                  {panelTab === 'queue' && (
                    <div>
                      {openCalls.length === 0 ? (
                        <div className="text-center py-8 text-xs text-slate-500">No open calls waiting</div>
                      ) : (
                        <>
                          <div className="px-3 pt-2 pb-1 flex items-center gap-3 text-[9px]">
                            <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-red-400" />Past SLA</span>
                            <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-amber-400" />&gt;30 min</span>
                            <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-blue-400" />&lt;30 min</span>
                          </div>
                          <div className="divide-y divide-slate-800/40">
                            {openCalls.slice(0, 25).map((c, i) => {
                              const sla = c.pta_min || 45
                              const pct = Math.min(c.wait_min / sla, 1.5)
                              const barColor = pct >= 1 ? 'bg-red-500' : pct >= 0.67 ? 'bg-amber-500' : 'bg-blue-500'
                              const textColor = pct >= 1 ? 'text-red-400' : pct >= 0.67 ? 'text-amber-400' : 'text-blue-400'
                              return (
                                <div key={i} className={clsx('px-3 py-2', pct >= 1 && 'bg-red-950/20')}>
                                  <div className="flex items-center gap-2">
                                    <span className={clsx('text-sm font-bold tabular-nums', textColor)}>{fmtWait(c.wait_min)}</span>
                                    <span className="text-[10px] text-slate-500 truncate flex-1">{c.work_type?.replace('Tow ', 'T-')}</span>
                                    <span className="text-[10px] text-slate-600 font-mono">{c.number}</span>
                                  </div>
                                  {/* SLA progress bar */}
                                  <div className="h-1 bg-slate-800 rounded-full mt-1 overflow-hidden">
                                    <div className={clsx('h-full rounded-full transition-all', barColor)}
                                         style={{ width: `${Math.min(pct * 100, 100)}%` }} />
                                  </div>
                                  <div className="flex items-center gap-2 mt-0.5">
                                    <span className="text-[9px] text-slate-600">{c.territory}</span>
                                    <span className="text-[9px] text-slate-600 ml-auto">SLA: {sla}m</span>
                                  </div>
                                </div>
                              )
                            })}
                          </div>
                        </>
                      )}
                    </div>
                  )}

                  {/* ── ZONES TAB ────────────────────────────────────── */}
                  {panelTab === 'zones' && (
                    <div>
                      {zones.length === 0 ? (
                        <div className="text-center py-8 text-xs text-slate-500">No active zones</div>
                      ) : (
                        <div className="divide-y divide-slate-800/40">
                          {zones.map(z => {
                            const covColor = z.coverage === 'covered' ? 'text-emerald-400 bg-emerald-950/30 border-emerald-800/30'
                              : z.coverage === 'thin' ? 'text-amber-400 bg-amber-950/30 border-amber-800/30'
                              : 'text-red-400 bg-red-950/30 border-red-800/30'
                            return (
                              <div key={z.zone_id} className="px-3 py-2.5">
                                <div className="flex items-center gap-2">
                                  <span className={clsx('w-2 h-2 rounded-full',
                                    z.status === 'critical' ? 'bg-red-500' : z.status === 'strained' ? 'bg-amber-500' :
                                    z.status === 'active' ? 'bg-blue-500' : 'bg-slate-600')} />
                                  <span className="text-xs font-medium text-white truncate flex-1">{z.zone_name}</span>
                                  {z.open_calls > 0 && (
                                    <span className="text-xs font-bold text-blue-400">{z.open_calls} open</span>
                                  )}
                                </div>
                                <div className="flex items-center gap-3 mt-1 ml-4">
                                  <span className="text-[10px] text-emerald-400">{z.completed_today} done</span>
                                  <span className="text-[10px] text-slate-500">{z.total_today} total</span>
                                  {z.max_wait_min > 0 && (
                                    <span className={clsx('text-[10px] font-medium',
                                      z.max_wait_min > 45 ? 'text-red-400' : z.max_wait_min > 30 ? 'text-amber-400' : 'text-slate-400')}>
                                      max wait: {fmtWait(z.max_wait_min)}
                                    </span>
                                  )}
                                </div>
                                <div className="mt-1.5 ml-4 flex items-center gap-2">
                                  <span className={clsx('text-[9px] font-bold px-1.5 py-0.5 rounded border', covColor)}>
                                    {z.coverage === 'covered' ? 'COVERED' : z.coverage === 'thin' ? 'THIN' : 'GAP'}
                                  </span>
                                  {z.nearest_idle_driver && (
                                    <span className="text-[9px] text-slate-500">
                                      Nearest idle: {z.nearest_idle_driver} ({z.nearest_idle_dist_mi} mi)
                                    </span>
                                  )}
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      )}
                    </div>
                  )}

                  {/* ── SEARCH TAB ───────────────────────────────────── */}
                  {panelTab === 'search' && (
                    <div className="px-4 py-3 space-y-3">
                      <div className="flex gap-2">
                        <input type="text" placeholder="SA-12345678" value={saQuery}
                          onChange={e => setSaQuery(e.target.value)}
                          onKeyDown={e => e.key === 'Enter' && searchSA()}
                          className="flex-1 px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-xs
                                     placeholder:text-slate-500 focus:outline-none focus:ring-1 focus:ring-brand-500/40" />
                        <button onClick={searchSA} disabled={saLoading}
                          className="px-3 py-1.5 bg-brand-600 hover:bg-brand-500 rounded-lg text-[10px] font-bold text-white transition-colors disabled:opacity-50">
                          {saLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Crosshair className="w-3 h-3" />}
                        </button>
                        {saResult && (
                          <button onClick={clearSA} className="p-1.5 rounded-lg hover:bg-slate-700"><X className="w-3 h-3 text-slate-400" /></button>
                        )}
                      </div>
                      {saError && <div className="text-xs text-red-400">{saError}</div>}
                      {saResult && (
                        <div className="space-y-3">
                          <div className="bg-slate-800/60 rounded-lg p-3">
                            <div className="text-sm font-bold text-white mb-1">{saResult.sa.customer || 'Member'} — SA# {saResult.sa.number}</div>
                            <div className="text-xs text-slate-400 space-y-0.5">
                              <div>{saResult.sa.work_type} — <span className="font-semibold text-white">{saResult.sa.status}</span></div>
                              <div>{saResult.sa.address}</div>
                              <div>Territory: {saResult.sa.territory}</div>
                              {saResult.sa.response_min && (
                                <div className={saResult.sa.response_min <= 45 ? 'text-emerald-400' : 'text-red-400'}>
                                  Response: {saResult.sa.response_min} min
                                </div>
                              )}
                            </div>
                          </div>
                          <div>
                            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1.5">
                              Drivers ({saResult.drivers.length})
                            </div>
                            <div className="space-y-1">
                              {saResult.drivers.map((d, i) => (
                                <div key={d.id} className={clsx('rounded-lg px-3 py-2 text-xs border',
                                  i === 0 ? 'bg-emerald-950/30 border-emerald-800/30' : 'bg-slate-800/40 border-slate-700/20')}>
                                  <div className="flex items-center justify-between">
                                    <span className={clsx('font-semibold', i === 0 ? 'text-emerald-400' : 'text-white')}>
                                      {d.name} {i === 0 && '(Closest)'}
                                    </span>
                                    <span className={clsx('font-bold', i === 0 ? 'text-emerald-400' : 'text-slate-300')}>
                                      {d.distance != null ? `${d.distance} mi` : 'No GPS'}
                                    </span>
                                  </div>
                                  {d.next_job ? (
                                    <div className="mt-1 text-[10px] text-amber-400">Busy: SA# {d.next_job.number}</div>
                                  ) : (
                                    <div className="mt-1 text-[10px] text-emerald-400 font-medium">Available</div>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                        </div>
                      )}
                      {!saResult && !saError && (
                        <div className="text-xs text-slate-500 text-center py-4">
                          Enter SA number to locate on map<br />with all territory drivers
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Bottom Legend ──────────────────────────────────────────── */}
        <div className="absolute bottom-4 left-4 z-[1000]">
          <div className="bg-slate-900/90 backdrop-blur-md border border-slate-700/50 rounded-xl px-4 py-3 shadow-xl">
            <div className="flex items-center gap-4 text-xs">
              <LegendDot border="border-emerald-500" fill="bg-emerald-500/25" label="On Track" />
              <LegendDot border="border-amber-500" fill="bg-amber-500/25" label="Behind" />
              <LegendDot border="border-red-500" fill="bg-red-500/25" label="Critical" />
              <span className="text-slate-700">|</span>
              <LegendSmall color="bg-blue-500" label="Open" />
              <LegendSmall color="bg-emerald-500" label="Done" />
              <span className="text-slate-700">|</span>
              <label className="flex items-center gap-1.5 cursor-pointer select-none">
                <input type="checkbox" checked={showSADots} onChange={e => setShowSADots(e.target.checked)}
                       className="w-3 h-3 rounded accent-brand-500" />
                <span className="text-slate-400">Dots</span>
              </label>
              {showSADots && (
                <>
                  <span className="text-slate-700">|</span>
                  {['open', 'all'].map(f => (
                    <button key={f} onClick={() => setSaStatusFilter(f)}
                      className={clsx('px-1.5 py-0.5 rounded text-[10px] font-semibold',
                        saStatusFilter === f ? 'bg-slate-700 text-white' : 'text-slate-500 hover:text-white')}>
                      {f === 'open' ? 'Open' : 'All'}
                    </button>
                  ))}
                </>
              )}
            </div>
          </div>
        </div>

        {error && (
          <div className="absolute top-16 right-4 z-[1000] bg-red-950/90 border border-red-800/50
                          rounded-xl px-4 py-2 text-sm text-red-300 shadow-xl max-w-xs">{error}</div>
        )}

        {/* ── Layer toggle (top-right) ────────────────────────────────── */}
        <div className="absolute top-16 right-3 z-[1000]" style={{ minWidth: 150 }}>
          <div className="bg-slate-900/95 backdrop-blur-xl border border-slate-600/40 rounded-xl shadow-2xl overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-800/60">
              <Layers className="w-3.5 h-3.5 text-brand-400" />
              <span className="text-[10px] font-bold text-white uppercase tracking-wide">Layers</span>
            </div>
            <div className="px-3 py-2.5 space-y-2">
              {[
                { key: 'activeSAs', emoji: '📍', label: 'Active SAs', color: 'text-blue-400' },
                { key: 'drivers', emoji: '🚛', label: 'Fleet Drivers', color: 'text-amber-400' },
                { key: 'garages',  emoji: '🏢', label: 'Fleet Garages',  color: 'text-emerald-400' },
                { key: 'towbook', emoji: '🔧', label: 'Towbook Garages', color: 'text-orange-400' },
                { key: 'grid',    emoji: '🗺️', label: 'Grid',    color: 'text-indigo-400' },
                { key: 'weather', emoji: '🌡️', label: 'Weather', color: 'text-cyan-400' },
              ].map(({ key, emoji, label, color }) => (
                <label key={key} className="flex items-center gap-2 cursor-pointer select-none">
                  <input type="checkbox" checked={layers[key]}
                    onChange={e => setLayers(l => ({ ...l, [key]: e.target.checked }))}
                    className="w-3 h-3 rounded accent-indigo-500" />
                  <span className="text-sm leading-none">{emoji}</span>
                  <span className={`text-[10px] font-medium flex-1 ${layers[key] ? color : 'text-slate-500'}`}>{label}</span>
                  {layerLoading[key] && <Loader2 className="w-2.5 h-2.5 text-brand-400 animate-spin" />}
                </label>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ══════════════════════════════════════════════════════════════════════ */}
      {/* RIGHT PANEL — Territory List                                         */}
      {/* ══════════════════════════════════════════════════════════════════════ */}
      <div className="w-80 bg-slate-900/95 border-l border-slate-700/50 flex flex-col">
        <div className="p-3 border-b border-slate-800">
          <div className="text-sm font-semibold text-white mb-2">Territories</div>
          <div className="relative mb-2">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
            <input type="text" placeholder="Filter..." value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full pl-8 pr-3 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-xs
                         placeholder:text-slate-500 focus:outline-none focus:ring-1 focus:ring-brand-500/40" />
          </div>
          <div className="flex gap-1">
            {['all', 'critical', 'behind', 'good'].map(f => (
              <button key={f} onClick={() => setStatusFilter(f)}
                className={clsx('px-2 py-0.5 rounded text-[10px] font-semibold transition-all',
                  statusFilter === f ? 'bg-slate-700 text-white' : 'text-slate-500 hover:text-white')}>
                {f === 'all' ? `All (${territories.length})` :
                 f === 'critical' ? `Crit (${summary.critical||0})` :
                 f === 'behind' ? `Behind (${summary.behind||0})` :
                 `Good (${summary.good||0})`}
              </button>
            ))}
          </div>
        </div>
        <div className="flex-1 overflow-y-auto">
          {loading && !data && (
            <div className="flex items-center justify-center py-12"><Loader2 className="w-5 h-5 animate-spin text-slate-500" /></div>
          )}
          {!loading && filtered.length === 0 && (
            <div className="text-center py-12 text-xs text-slate-500">No territories match</div>
          )}
          {filtered.map(t => (
            <TerritoryCard key={t.id} t={t}
              onFocus={() => setFocusCenter([t.lat, t.lon])}
              onNavigate={() => navigate(`/garage/${t.id}`)} />
          ))}
        </div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// HELPER COMPONENTS
// ═══════════════════════════════════════════════════════════════════════════════

function AutoBounds({ territories }) {
  const map = useMap()
  const fitted = useRef(false)
  useEffect(() => {
    if (territories.length > 0 && !fitted.current) {
      const bounds = L.latLngBounds(territories.filter(t => t.lat && t.lon).map(t => [t.lat, t.lon]))
      if (bounds.isValid()) { map.fitBounds(bounds, { padding: [60, 60] }); fitted.current = true }
    }
  }, [territories.length])
  return null
}

function FlyTo({ center }) {
  const map = useMap()
  useEffect(() => { if (center) map.flyTo(center, 11, { duration: 1 }) }, [center])
  return null
}

function StatChip({ icon: Icon, label, value, color }) {
  return (
    <div className="flex items-center gap-1.5">
      {Icon && <Icon className={clsx('w-3.5 h-3.5', color)} />}
      <div className="text-right">
        <div className={clsx('text-sm font-bold leading-none', color)}>{value?.toLocaleString() ?? '—'}</div>
        <div className="text-[9px] text-slate-500 leading-none mt-0.5">{label}</div>
      </div>
    </div>
  )
}

function Div() { return <div className="w-px h-8 bg-slate-700/50" /> }

function LegendDot({ border, fill, label }) {
  return <span className="flex items-center gap-1.5">
    <span className={clsx('w-3 h-3 rounded-full border-2', border, fill)} />
    <span className="text-slate-400">{label}</span>
  </span>
}
function LegendSmall({ color, label }) {
  return <span className="flex items-center gap-1.5">
    <span className={clsx('w-2 h-2 rounded-full', color)} />
    <span className="text-slate-400">{label}</span>
  </span>
}

function SuggestionCard({ s }) {
  const config = {
    escalate:   { icon: AlertCircle, color: 'bg-red-950/40 border-red-800/30', iconColor: 'text-red-400', badge: 'ESCALATE' },
    reposition: { icon: Navigation,  color: 'bg-blue-950/40 border-blue-800/30', iconColor: 'text-blue-400', badge: 'REPOSITION' },
    surge:      { icon: TrendingUp,  color: 'bg-amber-950/40 border-amber-800/30', iconColor: 'text-amber-400', badge: 'SURGE' },
    coverage:   { icon: Shield,      color: 'bg-purple-950/40 border-purple-800/30', iconColor: 'text-purple-400', badge: 'COVERAGE' },
  }
  const c = config[s.type] || config.coverage
  const Icon = c.icon
  return (
    <div className={clsx('rounded-lg px-3 py-2.5 border text-xs', c.color)}>
      <div className="flex items-start gap-2">
        <Icon className={clsx('w-3.5 h-3.5 mt-0.5 shrink-0', c.iconColor)} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-0.5">
            <span className={clsx('text-[9px] font-bold uppercase tracking-wider', c.iconColor)}>{c.badge}</span>
            {s.priority === 'critical' && <span className="text-[8px] px-1 py-0.5 rounded bg-red-500/30 text-red-300 font-bold animate-pulse">URGENT</span>}
          </div>
          <div className="text-slate-300 leading-relaxed">{s.reason}</div>
          {s.type === 'reposition' && s.driver && (
            <div className="flex items-center gap-1 mt-1 text-blue-300">
              <ArrowRight className="w-3 h-3" />
              <span className="font-medium">{s.driver}</span>
              <span className="text-slate-500">→</span>
              <span>{s.to_zone}</span>
              <span className="text-slate-500">({s.distance_mi} mi)</span>
            </div>
          )}
          {s.type === 'escalate' && s.nearest_driver && (
            <div className="mt-1 text-slate-400">
              Nearest idle: <span className="text-emerald-400 font-medium">{s.nearest_driver}</span>
              {s.nearest_dist_mi && <span> ({s.nearest_dist_mi} mi)</span>}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function TerritoryCard({ t, onFocus, onNavigate }) {
  const sc = STATUS_COLORS[t.status] || STATUS_COLORS.good
  return (
    <div className="px-3 py-2.5 border-b border-slate-800/60 hover:bg-slate-800/40 cursor-pointer transition-colors group"
         onClick={onFocus} onDoubleClick={onNavigate}>
      <div className="flex items-center gap-2">
        <div className={clsx('w-2 h-2 rounded-full flex-shrink-0', sc.bg)} />
        <span className="text-sm font-medium text-white truncate flex-1 group-hover:text-brand-300 transition-colors">{t.name}</span>
        <ChevronRight className="w-3.5 h-3.5 text-slate-600 group-hover:text-brand-400 flex-shrink-0 transition-colors" />
      </div>
      <div className="flex items-center gap-3 mt-1.5 ml-4">
        <span className="text-[11px] text-blue-400 font-medium">{t.open} open</span>
        <span className="text-[11px] text-emerald-400">{t.completed} done</span>
        <span className="text-[11px] text-slate-500">{t.total} total</span>
      </div>
      <div className="flex items-center gap-3 mt-1 ml-4">
        {t.sla_pct != null && (
          <span className={clsx('text-[10px] font-medium',
            t.sla_pct >= 50 ? 'text-emerald-500' : t.sla_pct >= 30 ? 'text-amber-500' : 'text-red-500'
          )}>SLA: {t.sla_pct}%</span>
        )}
        {t.avg_response != null && <span className="text-[10px] text-slate-500">Avg: {t.avg_response}m</span>}
        {t.completion_rate != null && <span className="text-[10px] text-slate-500">Comp: {t.completion_rate}%</span>}
      </div>
    </div>
  )
}

function TerritoryPopup({ t }) {
  return (
    <div style={{ minWidth: 200 }}>
      <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 6, color: '#e2e8f0' }}>{t.name}</div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 4 }}>
        <span style={{ color: '#3b82f6', fontWeight: 600, fontSize: 13 }}>{t.open} open</span>
        <span style={{ color: '#22c55e', fontSize: 13 }}>{t.completed} done</span>
        <span style={{ color: '#f97316', fontSize: 13 }}>{t.canceled} canceled</span>
      </div>
      <div style={{ fontSize: 12, color: '#94a3b8' }}>
        <div>Total: {t.total} SAs</div>
        {t.sla_pct != null && <div>SLA (≤45 min): {t.sla_pct}%</div>}
        {t.avg_response != null && <div>Avg Response: {t.avg_response} min</div>}
        {t.avg_wait > 0 && <div>Avg Wait: {fmtWait(t.avg_wait)}</div>}
        <div>Completion: {t.completion_rate}%</div>
      </div>
    </div>
  )
}
