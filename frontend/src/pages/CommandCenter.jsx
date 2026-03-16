import React, { useState, useEffect, useCallback, useRef } from 'react'
import ReactDOM from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { MapContainer, TileLayer, CircleMarker, Popup, Tooltip, Marker, Polyline, useMap, GeoJSON } from 'react-leaflet'
import L from 'leaflet'
import { clsx } from 'clsx'
import { fetchCommandCenter, lookupSA, fetchMapGrids, fetchMapDrivers, fetchMapWeather, fetchOpsGarages, fetchOpsBrief, fetchSchedulerInsights, fetchGpsHealth } from '../api'
import { getMapConfig } from '../mapStyles'
import {
  Loader2, RefreshCw, Radio, CheckCircle2, AlertTriangle,
  ChevronRight, Search, MapPin, Clock, FileText,
  ChevronDown, ChevronUp, Crosshair, X, Truck, Layers,
  Zap, Shield, Navigation, Users, TrendingUp, AlertCircle, ArrowRight,
  Maximize2, Minimize2, GripVertical, BarChart3, XCircle, ThumbsDown, Activity
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

function makeGarageIcon(primaryZones, secondaryZones, isTowbook) {
  const isPrimary = primaryZones > 0
  const badge = isPrimary
    ? `<div style="position:absolute;top:-8px;right:-8px;min-width:14px;height:14px;background:#22c55e;border:1.5px solid #0f172a;border-radius:7px;font-size:8px;font-weight:800;color:#fff;display:flex;align-items:center;justify-content:center;padding:0 2px;line-height:1">P${primaryZones > 1 ? primaryZones : ''}</div>`
    : secondaryZones > 0
    ? `<div style="position:absolute;top:-8px;right:-8px;min-width:14px;height:14px;background:#f59e0b;border:1.5px solid #0f172a;border-radius:7px;font-size:8px;font-weight:800;color:#fff;display:flex;align-items:center;justify-content:center;padding:0 2px;line-height:1">S${secondaryZones > 1 ? secondaryZones : ''}</div>`
    : ''
  if (isTowbook) {
    const color = isPrimary ? '#f97316' : '#78716c'
    return L.divIcon({
      className: '',
      iconSize: [22, 22], iconAnchor: [11, 11], popupAnchor: [0, -12],
      html: `<div style="position:relative;width:20px;height:20px;background:${color}22;border:2px solid ${color};border-radius:50%;display:flex;align-items:center;justify-content:center">
        <svg width="10" height="10" viewBox="0 0 16 16" fill="${color}">
          <path d="M14.7 6.3a1 1 0 0 0 0-1.4l-3.6-3.6a1 1 0 0 0-1.4 0L8.3 2.7 6.6 1H4v2.6l1.7 1.7-5.4 5.4a1 1 0 0 0 0 1.4l2.6 2.6a1 1 0 0 0 1.4 0l5.4-5.4 1.7 1.7H14v-2.6l-1.7-1.7z"/>
        </svg>
        ${badge}
      </div>`,
    })
  }
  const color = isPrimary ? '#22c55e' : '#64748b'
  return L.divIcon({
    className: '',
    iconSize: [18, 18], iconAnchor: [9, 9], popupAnchor: [0, -10],
    html: `<div style="position:relative;width:16px;height:16px;background:${color}22;border:2px solid ${color};border-radius:3px;display:flex;align-items:center;justify-content:center">
      <div style="width:6px;height:6px;background:${color};border-radius:1px"></div>
      ${badge}
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
  const [viewMode, setViewMode] = useState('insights')    // insights | map
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

  // ── Scheduler insights + GPS health (1-hour refresh)
  const [schedulerData, setSchedulerData] = useState(null)
  const [gpsHealth, setGpsHealth] = useState(null)

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
      .catch(e => console.error('Ops brief fetch failed:', e))
      .finally(() => setBriefLoading(false))
  }, [hours])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    const iv = setInterval(load, REFRESH_MS)
    return () => clearInterval(iv)
  }, [load])
  // Scheduler insights — today's data, refresh every hour
  const loadScheduler = useCallback(() => {
    fetchSchedulerInsights().then(setSchedulerData).catch(() => {})
    fetchGpsHealth().then(setGpsHealth).catch(() => {})
  }, [])
  useEffect(() => { loadScheduler() }, [loadScheduler])
  useEffect(() => {
    const iv = setInterval(loadScheduler, 3600_000)
    return () => clearInterval(iv)
  }, [loadScheduler])
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
    <div className="-mx-6 -mt-6 flex flex-col" style={{ height: 'calc(100vh - 56px)' }}>

      {/* ══════════════════════════════════════════════════════════════════════ */}
      {/* VIEW TABS — full-width tab bar                                       */}
      {/* ══════════════════════════════════════════════════════════════════════ */}
      <div className="flex-shrink-0 bg-slate-900/95 border-b border-slate-700/50 px-6 flex items-center gap-1">
        <button onClick={() => setViewMode('insights')}
          className={clsx('flex items-center gap-2 px-4 py-2.5 text-xs font-bold uppercase tracking-wide transition-all border-b-2',
            viewMode === 'insights'
              ? 'border-indigo-500 text-indigo-300 bg-indigo-600/10'
              : 'border-transparent text-slate-500 hover:text-white hover:bg-slate-800/40')}>
          <Zap className="w-4 h-4" /> Dispatch Insights
        </button>
        <button onClick={() => setViewMode('map')}
          className={clsx('flex items-center gap-2 px-4 py-2.5 text-xs font-bold uppercase tracking-wide transition-all border-b-2',
            viewMode === 'map'
              ? 'border-brand-500 text-brand-300 bg-brand-600/10'
              : 'border-transparent text-slate-500 hover:text-white hover:bg-slate-800/40')}>
          <MapPin className="w-4 h-4" /> Map
        </button>
      </div>

      {/* ══════════════════════════════════════════════════════════════════════ */}
      {/* VIEW CONTENT                                                         */}
      {/* ══════════════════════════════════════════════════════════════════════ */}

      {/* ── INSIGHTS FULL VIEW (takes all space, no sidebar) ── */}
      {viewMode === 'insights' && (
        <div className="flex-1 overflow-hidden">
          {schedulerData ? (
            <DispatchInsightsFullView data={schedulerData} gpsHealth={gpsHealth} ccData={data} />
          ) : (
            <div className="w-full h-full flex items-center justify-center bg-slate-950">
              <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
            </div>
          )}
        </div>
      )}

      {/* ── MAP VIEW (with ops cockpit + territory sidebar) ── */}
      {viewMode === 'map' && (
      <div className="flex-1 flex overflow-hidden">
      <div className="flex-1 relative cc-map">

        {/* ── MAP ── */}
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
              <Marker key={`garage-${g.id}`} position={[g.lat, g.lon]} icon={makeGarageIcon(g.primary_zones || 0, g.secondary_zones || 0, false)}>
                <Tooltip direction="top" offset={[0, -10]} sticky className="cc-tooltip">
                  <div style={{ fontSize: 11, lineHeight: 1.5, minWidth: 160 }}>
                    <div style={{ fontWeight: 700, fontSize: 12 }}>{g.name}</div>
                    {g.address && <div style={{ color: '#94a3b8', fontSize: 10 }}>{g.address}</div>}
                    <div style={{ color: '#22c55e', fontSize: 10 }}>Fleet (Field Services)</div>
                    {g.phone && <div style={{ fontSize: 10 }}>{fmtPhone(g.phone)}</div>}
                    <div style={{ fontSize: 10, marginTop: 2 }}>
                      {g.primary_zones > 0 && <span style={{ color: '#22c55e', fontWeight: 700 }}>Primary: {g.primary_zones} zones</span>}
                      {g.primary_zones > 0 && g.secondary_zones > 0 && <span style={{ color: '#475569' }}> · </span>}
                      {g.secondary_zones > 0 && <span style={{ color: '#f59e0b', fontWeight: 600 }}>Secondary: {g.secondary_zones} zones</span>}
                      {!g.primary_zones && !g.secondary_zones && <span style={{ color: '#64748b' }}>No matrix zones</span>}
                    </div>
                  </div>
                </Tooltip>
              </Marker>
            )
          })}

          {/* Towbook Garages layer */}
          {layers.towbook && allGarages.filter(g => g.dispatch_method === 'Towbook').map(g => {
            if (!g.lat || !g.lon) return null
            return (
              <Marker key={`tb-${g.id}`} position={[g.lat, g.lon]} icon={makeGarageIcon(g.primary_zones || 0, g.secondary_zones || 0, true)}>
                <Tooltip direction="top" offset={[0, -12]} sticky className="cc-tooltip">
                  <div style={{ fontSize: 11, lineHeight: 1.5, minWidth: 160 }}>
                    <div style={{ fontWeight: 700, fontSize: 12 }}>{g.name}</div>
                    {g.address && <div style={{ color: '#94a3b8', fontSize: 10 }}>{g.address}</div>}
                    <div style={{ color: '#f97316', fontSize: 10 }}>Towbook (Contractor)</div>
                    {g.phone && <div style={{ fontSize: 10 }}>{fmtPhone(g.phone)}</div>}
                    <div style={{ fontSize: 10, marginTop: 2 }}>
                      {g.primary_zones > 0 && <span style={{ color: '#22c55e', fontWeight: 700 }}>Primary: {g.primary_zones} zones</span>}
                      {g.primary_zones > 0 && g.secondary_zones > 0 && <span style={{ color: '#475569' }}> · </span>}
                      {g.secondary_zones > 0 && <span style={{ color: '#f59e0b', fontWeight: 600 }}>Secondary: {g.secondary_zones} zones</span>}
                      {!g.primary_zones && !g.secondary_zones && <span style={{ color: '#64748b' }}>No matrix zones</span>}
                    </div>
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
                {(summary.over_capacity > 0 || summary.busy > 0) && (
                  <>
                    <Div />
                    {summary.over_capacity > 0 && (
                      <div className="flex items-center gap-1 px-2 py-0.5 rounded-lg text-[10px] font-bold bg-red-950/60 text-red-400 border border-red-800/40">
                        {summary.over_capacity} Over Cap
                      </div>
                    )}
                    {summary.busy > 0 && (
                      <div className="flex items-center gap-1 px-2 py-0.5 rounded-lg text-[10px] font-bold bg-amber-950/50 text-amber-400 border border-amber-800/40">
                        {summary.busy} Busy
                      </div>
                    )}
                  </>
                )}
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

      {/* ── RIGHT PANEL — Territory List ── */}
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
      )}
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

function MiniDonut({ pct, size = 56, stroke = 6, autoColor = '#6366f1', manualColor = '#334155' }) {
  const r = (size - stroke) / 2
  const circ = 2 * Math.PI * r
  const autoLen = circ * (pct / 100)
  return (
    <svg width={size} height={size} className="block">
      {/* Manual (background) */}
      <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={manualColor} strokeWidth={stroke} />
      {/* Auto (foreground) */}
      <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={autoColor} strokeWidth={stroke}
        strokeDasharray={`${autoLen} ${circ - autoLen}`}
        strokeDashoffset={circ / 4} strokeLinecap="round"
        className="transition-all duration-700" />
      {/* Center text */}
      <text x={size/2} y={size/2} textAnchor="middle" dominantBaseline="central"
        className="fill-white text-[11px] font-bold">{pct}%</text>
    </svg>
  )
}

function InfoTip({ text }) {
  const [open, setOpen] = useState(false)
  const [style, setStyle] = useState({})
  const btnRef = useRef(null)
  const popRef = useRef(null)
  useEffect(() => {
    if (!open) return
    const close = (e) => {
      if (btnRef.current?.contains(e.target) || popRef.current?.contains(e.target)) return
      setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])
  // Reposition after render so we know the popup's actual height
  useEffect(() => {
    if (!open || !popRef.current || !btnRef.current) return
    const btn = btnRef.current.getBoundingClientRect()
    const pop = popRef.current.getBoundingClientRect()
    const vh = window.innerHeight
    const vw = window.innerWidth
    const pad = 12
    // Horizontal: center on button, clamp to viewport
    let left = Math.max(pad, Math.min(btn.left + btn.width / 2 - pop.width / 2, vw - pop.width - pad))
    // Vertical: prefer below the button; if it won't fit, put it above
    let top
    const maxH = vh - pad * 2
    if (btn.bottom + 8 + pop.height <= vh - pad) {
      top = btn.bottom + 8
    } else if (btn.top - 8 - pop.height >= pad) {
      top = btn.top - 8 - pop.height
    } else {
      // Neither fits fully — anchor to bottom of viewport with scroll
      top = Math.max(pad, vh - pop.height - pad)
    }
    setStyle({ zIndex: 99999, position: 'fixed', left, top, maxHeight: maxH })
  }, [open])
  const handleOpen = (e) => {
    e.stopPropagation()
    // Initial position near button — will be corrected by useEffect above
    const rect = e.currentTarget.getBoundingClientRect()
    setStyle({ zIndex: 99999, position: 'fixed', left: rect.left, top: rect.bottom + 8, maxHeight: window.innerHeight - 24 })
    setOpen(o => !o)
  }
  return (
    <span ref={btnRef} className="relative ml-1 inline-flex">
      <button onClick={handleOpen}
        className="inline-flex items-center justify-center w-4 h-4 rounded-full bg-slate-700/60 text-slate-400 hover:text-white hover:bg-indigo-600 cursor-pointer text-[9px] font-bold leading-none transition-colors">?</button>
      {open && ReactDOM.createPortal(
        <div ref={popRef}
          className="w-72 bg-slate-800 border border-slate-600/50 rounded-xl shadow-2xl shadow-black/60 p-3 text-xs text-slate-300 leading-relaxed overflow-y-auto"
          style={style}
          onClick={e => e.stopPropagation()}>
          <div className="whitespace-pre-wrap">{text}</div>
        </div>,
        document.body
      )}
    </span>
  )
}

function DispatchInsightsFullView({ data, gpsHealth, ccData }) {
  const { auto_count, manual_count, towbook_count, auto_pct, auto_avg_response, manual_avg_response, auto_avg_speed, manual_avg_speed, auto_sla, manual_sla, auto_closest_pct, auto_closest_eval, auto_extra_miles, auto_wrong, manual_closest_pct, manual_closest_eval, manual_extra_miles, manual_wrong, towbook_closest_pct, towbook_closest_eval, towbook_extra_miles, towbook_wrong, total_extra_miles, dispatchers, total, fleet_total } = data
  const fg = ccData?.fleet_gps
  const ts = ccData?.today_status
  const sp = ccData?.today_split
  const lb = ccData?.fleet_leaderboard
  const ra = ccData?.reassignment
  const cb = ccData?.cancel_breakdown
  const db = ccData?.decline_breakdown
  const fu = ccData?.fleet_utilization
  const hv = ccData?.hourly_volume
  const overCap = (ccData?.territories || []).filter(t =>
      (t.capacity === 'over' || t.capacity === 'busy')
      && !t.name.startsWith('000')
      && !/SPOT/i.test(t.name)
    )
    .sort((a, b) => {
      // Prioritize by impact: open calls × max wait time
      const scoreA = (a.open || 0) * Math.max(a.max_wait || 1, 1)
      const scoreB = (b.open || 0) * Math.max(b.max_wait || 1, 1)
      return scoreB - scoreA
    })

  return (
    <div className="w-full h-full bg-slate-950 overflow-y-auto pt-6 pb-6 px-6">
      <div className="max-w-5xl mx-auto space-y-6">

        {/* ── Row 1: Dispatch Split + Closest Driver + Stats ── */}
        <div className="grid grid-cols-3 gap-4">
          {/* Dispatch Split */}
          <div className="glass rounded-xl border border-slate-700/30 p-4">
            <div className="flex items-center gap-2 mb-3">
              <Zap className="w-4 h-4 text-indigo-400" />
              <span className="text-xs font-bold text-white uppercase tracking-wide">Dispatch Split</span>
              <InfoTip text={"HOW TO READ THIS CARD:\n\n• Top-right number (e.g. '175 fleet') = total completed fleet calls today.\n• Donut chart % = share handled by the auto-scheduler.\n• Blue dot / 'System' number = calls the FSL Enhanced Scheduler auto-assigned (no human involved).\n• Orange dot / 'Dispatcher' number = calls a human dispatcher manually assigned.\n• Pink dot / 'Contractor' number (below the line) = Towbook contractor calls, dispatched outside FSL.\n\nSystem + Dispatcher = total fleet calls. Contractor is separate.\n\nWHAT IT MEANS:\nSystem = the scheduler picked the driver automatically.\nDispatcher = a person chose who to send.\n\nHOW IT'S CALCULATED:\nWe check who created the 'Assigned' status in ServiceAppointmentHistory. System accounts (Automated Process, Data Loader, FSL Enhanced) = System. Human names = Dispatcher.\n\nGOAL: Higher System % = the auto-scheduler is handling more fleet work without human intervention."} />
              <span className="text-[10px] text-slate-500 ml-auto">{fleet_total || total} fleet</span>
            </div>
            <div className="flex items-center gap-4">
              <MiniDonut pct={auto_pct} size={72} stroke={7} />
              <div className="flex-1 space-y-2">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-indigo-500" />
                  <span className="text-xs text-slate-300 flex-1">System</span>
                  <span className="text-sm font-bold text-white">{auto_count}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-amber-500" />
                  <span className="text-xs text-slate-300 flex-1">Dispatcher</span>
                  <span className="text-sm font-bold text-white">{manual_count}</span>
                </div>
                {towbook_count > 0 && (
                  <>
                    <div className="border-t border-slate-700/30 my-1" />
                    <div className="flex items-center gap-2">
                      <span className="w-2.5 h-2.5 rounded-full bg-fuchsia-500" />
                      <span className="text-xs text-slate-400 flex-1">Contractor (Towbook)</span>
                      <span className="text-sm font-bold text-slate-400">{towbook_count}</span>
                    </div>
                  </>
                )}
              </div>
            </div>
            {total === 0 && <div className="text-xs text-slate-600 text-center mt-3">No fleet dispatches yet today</div>}
          </div>

          {/* Closest Driver */}
          <div className="glass rounded-xl border border-slate-700/30 p-4">
            <div className="flex items-center gap-2 mb-3">
              <Navigation className="w-4 h-4 text-emerald-400" />
              <span className="text-xs font-bold text-white uppercase tracking-wide">Closest Driver Dispatched</span>
              <InfoTip text={"HOW TO READ THIS CARD:\n\n• Each donut shows the % of calls where the closest available driver was sent.\n• Blue donut / 'System' = auto-scheduled calls.\n• Orange donut / 'Dispatcher' = manually dispatched calls.\n• 'eval' below each = how many calls had enough GPS data to evaluate (not all calls can be measured).\n\nFleet calls only — contractors don't have GPS in Salesforce.\n\nHOW IT'S CALCULATED:\nFor each completed fleet call, we compare the assigned driver's GPS distance to the member vs all other available drivers in that territory. Closest match = hit.\n\nGOAL: 100% = always sent the nearest driver. Lower % = wasted miles, longer wait for members."} />
            </div>
            <div className="flex items-center justify-around">
              {auto_closest_pct != null && (
                <div className="text-center">
                  <MiniDonut pct={auto_closest_pct} size={56} stroke={6} autoColor="#22c55e" manualColor="#1e293b" />
                  <div className="text-[10px] text-indigo-400 mt-1">System</div>
                  <div className="text-[9px] text-slate-600">{auto_closest_eval} eval</div>
                </div>
              )}
              {manual_closest_pct != null && (
                <div className="text-center">
                  <MiniDonut pct={manual_closest_pct} size={56} stroke={6} autoColor="#f59e0b" manualColor="#1e293b" />
                  <div className="text-[10px] text-amber-500 mt-1">Dispatcher</div>
                  <div className="text-[9px] text-slate-600">{manual_closest_eval} eval</div>
                </div>
              )}
              {auto_closest_pct == null && manual_closest_pct == null && (
                <div className="text-xs text-slate-600 text-center py-4">No fleet GPS data available yet</div>
              )}
            </div>
            {total_extra_miles != null && total_extra_miles > 0 && (
              <div className="mt-3 bg-red-950/30 border border-red-800/30 rounded-lg px-3 py-2">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-red-400 font-medium">Extra Miles (wrong picks)<InfoTip text={"WHAT: Wasted mileage from wrong driver picks.\n\nWhen a farther driver is sent instead of the closest one, the difference in miles is the 'extra miles'. This adds up across all wrong picks.\n\nHOW: For each call where the closest driver wasn't sent, we calculate: (assigned driver distance) - (closest driver distance) = extra miles.\n\nGOAL: Zero extra miles means perfect dispatch. High numbers mean significant fuel, time, and member wait time wasted."} /></span>
                  <span className="text-sm font-bold text-red-300">+{total_extra_miles} mi</span>
                </div>
                <div className="flex gap-3 mt-1 text-[9px] text-slate-500">
                  {auto_wrong > 0 && <span>Sys: {auto_extra_miles}mi ({auto_wrong})</span>}
                  {manual_wrong > 0 && <span>Disp: {manual_extra_miles}mi ({manual_wrong})</span>}
                </div>
              </div>
            )}
          </div>

          {/* Performance Stats */}
          <div className="glass rounded-xl border border-slate-700/30 p-4">
            <div className="flex items-center gap-2 mb-3">
              <TrendingUp className="w-4 h-4 text-cyan-400" />
              <span className="text-xs font-bold text-white uppercase tracking-wide">System vs Dispatcher</span>
              <InfoTip text={"HOW TO READ THIS CARD:\n\nCompares System (auto-scheduler) vs Dispatcher (human) side by side on 3 metrics. Blue row = System, Orange row = Dispatcher. Lower is better for time metrics, higher is better for SLA %.\n\n• Avg Response: Average time from call creation to driver arriving on scene (ATA). This is how long the member waited.\n• Sched ETA: Average time from call creation to the scheduled arrival window. How far out was the appointment set.\n• 45-min SLA: % of calls where the driver arrived within 45 minutes (AAA's standard).\n\nFleet calls only (Towbook excluded).\n\nGOAL: System should match or beat Dispatcher on all 3 metrics. If Dispatcher is faster, the scheduler may need tuning."} />
            </div>
            <table className="w-full text-center border-separate" style={{ borderSpacing: '0 4px' }}>
              <thead>
                <tr>
                  <th className="w-16" />
                  <th className="text-[9px] text-slate-500 uppercase tracking-wider font-medium pb-1">
                    Avg Response<InfoTip text={"WHAT: Average time a member waits from calling AAA to the driver arriving on scene.\n\nHOW: For each completed call: ActualStartTime (driver marked 'On Location' in Towbook) minus CreatedDate (call entered Salesforce). Averaged across all completed calls.\n\nGOAL: Under 45 minutes. This is the #1 member experience metric."} />
                  </th>
                  <th className="text-[9px] text-slate-500 uppercase tracking-wider font-medium pb-1">
                    Sched ETA<InfoTip text={"WHAT: How quickly a call gets a scheduled arrival window.\n\nHOW: SchedStartTime minus CreatedDate. Measures how far out the scheduled appointment is from creation.\n\nGOAL: Lower is better — means calls are being scheduled with short ETAs."} />
                  </th>
                  <th className="text-[9px] text-slate-500 uppercase tracking-wider font-medium pb-1">
                    45-min SLA<InfoTip text={"WHAT: % of calls where the driver arrived within 45 minutes.\n\nHOW: If (ActualStartTime - CreatedDate) ≤ 45 min, it passes.\n\nGOAL: AAA standard is 45 min. Higher % = better. Below 80% is a red flag."} />
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="text-[9px] text-indigo-400/60 font-medium text-left">System</td>
                  <td className="text-sm font-bold text-indigo-400">{auto_avg_response != null ? `${auto_avg_response}m` : '—'}</td>
                  <td className="text-sm font-bold text-indigo-400">{auto_avg_speed != null ? `${auto_avg_speed}m` : '—'}</td>
                  <td className="text-sm font-bold text-indigo-400">{auto_sla != null ? `${auto_sla}%` : '—'}</td>
                </tr>
                <tr>
                  <td className="text-[9px] text-amber-500/50 font-medium text-left">Dispatcher</td>
                  <td className="text-sm font-bold text-amber-500/80">{manual_avg_response != null ? `${manual_avg_response}m` : '—'}</td>
                  <td className="text-sm font-bold text-amber-500/80">{manual_avg_speed != null ? `${manual_avg_speed}m` : '—'}</td>
                  <td className="text-sm font-bold text-amber-500/80">{manual_sla != null ? `${manual_sla}%` : '—'}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        {/* ── Row 2: Fleet GPS + Today's Calls + Fleet vs Contractor ── */}
        <div className="grid grid-cols-3 gap-4">
          {/* Fleet GPS Health */}
          {fg && fg.total > 0 && (
            <div className="glass rounded-xl border border-slate-700/30 p-4">
              <div className="flex items-center gap-2 mb-3">
                <Truck className="w-4 h-4 text-blue-400" />
                <span className="text-xs font-bold text-white uppercase tracking-wide">Fleet Drivers</span>
                <InfoTip text={"HOW TO READ THIS CARD:\n\n• Drivers: Total active fleet drivers in Salesforce (excludes test accounts, SPOT placeholders, office staff).\n• GPS Tracking: % of fleet drivers the scheduler can currently locate (GPS updated within 4 hours).\n• On GPS: Drivers whose GPS is reporting right now (fresh + recent).\n\nBAR BREAKDOWN:\n• Green (fresh): GPS updated < 1 hour ago — trackable, likely on shift.\n• Dark green (recent): 1-4 hours — recently active, still trackable.\n• Amber (stale): GPS > 4 hours old — has GPS hardware but not reporting now.\n• Red (no GPS): Never reported GPS — may not have the FSL app installed.\n\nWHY IT MATTERS:\nThe scheduler needs live GPS to calculate travel times and pick the closest driver. Drivers without GPS get assigned based on territory only, which leads to longer ETAs and wasted miles.\n\nGOAL: During business hours, GPS Tracking should be 40%+. If most drivers show stale or no GPS, the scheduler is dispatching blind."} />
              </div>
              <div className="flex items-center gap-4 mb-3">
                <div className="text-center flex-1">
                  <div className="text-2xl font-bold text-white">{fg.total}</div>
                  <div className="text-[10px] text-slate-500">Drivers</div>
                </div>
                <div className="text-center flex-1">
                  <div className={clsx('text-2xl font-bold', fg.pct >= 40 ? 'text-emerald-400' : fg.pct >= 20 ? 'text-amber-400' : 'text-red-400')}>
                    {fg.pct}%
                  </div>
                  <div className="text-[10px] text-slate-500">GPS Tracking</div>
                </div>
                <div className="text-center flex-1">
                  <div className="text-2xl font-bold text-emerald-400">{fg.active}</div>
                  <div className="text-[10px] text-slate-500">On GPS</div>
                </div>
              </div>
              <div className="h-3 rounded-full bg-slate-800 overflow-hidden flex">
                {fg.fresh > 0 && <div className="bg-emerald-500" style={{ width: `${100*fg.fresh/fg.total}%` }} title={`Fresh: ${fg.fresh}`} />}
                {fg.recent > 0 && <div className="bg-emerald-700" style={{ width: `${100*fg.recent/fg.total}%` }} title={`Recent: ${fg.recent}`} />}
                {fg.stale > 0 && <div className="bg-amber-600" style={{ width: `${100*fg.stale/fg.total}%` }} title={`Stale: ${fg.stale}`} />}
                {fg.no_gps > 0 && <div className="bg-red-800" style={{ width: `${100*fg.no_gps/fg.total}%` }} title={`No GPS: ${fg.no_gps}`} />}
              </div>
              <div className="flex justify-between text-[9px] text-slate-500 mt-1">
                <span className="text-emerald-500">{fg.fresh} fresh</span>
                <span className="text-emerald-700">{fg.recent} recent</span>
                <span className="text-amber-600">{fg.stale} stale</span>
                {fg.no_gps > 0 && <span className="text-red-700">{fg.no_gps} no GPS</span>}
              </div>
            </div>
          )}

          {/* Today's Calls */}
          {ts && (
            <div className="glass rounded-xl border border-slate-700/30 p-4">
              <div className="flex items-center gap-2 mb-3">
                <FileText className="w-4 h-4 text-cyan-400" />
                <span className="text-xs font-bold text-white uppercase tracking-wide">Today's Calls</span>
                <span className="text-sm font-bold text-white ml-auto">{ts.total || 0}</span>
                <InfoTip text={"WHAT: All roadside calls created today broken into pipeline stages and outcomes.\n\nPIPELINE (active calls):\n• Dispatched — Call entered, waiting for driver assignment\n• Accepted — Driver accepted, preparing to leave\n• Assigned — Driver assigned, not yet en route\n• En Route — Driver traveling to member\n• On Location — Driver arrived, working on site\n\nOUTCOMES (finished calls):\n• Completed — Service finished successfully\n• Canceled — Call canceled by member or dispatcher\n• No-Show — Driver arrived but member not present\n• Unable — Driver couldn't complete the service\n\nTow Drop-Offs excluded (second leg of a tow, not a new call)."} />
              </div>
              {/* Active pipeline */}
              <div className="text-[9px] text-slate-600 uppercase tracking-wider font-bold mb-1">Active Pipeline</div>
              <div className="grid grid-cols-5 gap-1.5 mb-2">
                {[
                  { label: 'Dispatched', val: ts.Dispatched, color: 'text-blue-400' },
                  { label: 'Accepted', val: ts.Accepted, color: 'text-sky-400' },
                  { label: 'Assigned', val: ts.Assigned, color: 'text-violet-400' },
                  { label: 'En Route', val: ts['En Route'], color: 'text-amber-400' },
                  { label: 'On Location', val: ts['On Location'], color: 'text-cyan-400' },
                ].map(s => (
                  <div key={s.label} className="text-center bg-slate-800/30 rounded-lg py-1.5">
                    <div className={clsx('text-sm font-bold', s.color)}>{s.val || 0}</div>
                    <div className="text-[8px] text-slate-500 leading-tight">{s.label}</div>
                  </div>
                ))}
              </div>
              {/* Outcomes */}
              <div className="text-[9px] text-slate-600 uppercase tracking-wider font-bold mb-1">Outcomes</div>
              <div className="grid grid-cols-4 gap-1.5">
                {[
                  { label: 'Completed', val: ts.Completed, color: 'text-emerald-400' },
                  { label: 'Canceled', val: ts.Canceled, color: 'text-slate-500' },
                  { label: 'No-Show', val: ts['No-Show'], color: 'text-orange-400' },
                  { label: 'Unable', val: ts['Unable to Complete'], color: 'text-red-400' },
                ].map(s => (
                  <div key={s.label} className="text-center bg-slate-800/30 rounded-lg py-1.5">
                    <div className={clsx('text-sm font-bold', s.color)}>{s.val || 0}</div>
                    <div className="text-[8px] text-slate-500 leading-tight">{s.label}</div>
                  </div>
                ))}
              </div>
              {/* Fleet vs Contractor */}
              {sp && sp.total_completed > 0 && (
                <div className="mt-3 pt-3 border-t border-slate-800/60">
                  <div className="flex justify-between text-[10px] mb-1">
                    <span className="text-blue-400 font-medium">Fleet {sp.fleet_pct}%</span>
                    <span className="text-slate-600">{sp.total_completed} completed</span>
                    <span className="text-fuchsia-400 font-medium">Contractor {sp.contractor_pct}%</span>
                  </div>
                  <div className="h-3 rounded-full bg-slate-800 overflow-hidden flex">
                    <div className="bg-blue-500" style={{ width: `${sp.fleet_pct}%` }} />
                    <div className="bg-fuchsia-600" style={{ width: `${sp.contractor_pct}%` }} />
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Fleet ATA Leaderboard */}
          {lb && (lb.top?.length > 0 || lb.bottom?.length > 0) && (
            <div className="glass rounded-xl border border-slate-700/30 p-4">
              <div className="flex items-center gap-2 mb-3">
                <TrendingUp className="w-4 h-4 text-emerald-400" />
                <span className="text-xs font-bold text-white uppercase tracking-wide">Fleet ATA Today</span>
                <InfoTip text={"WHAT: Which fleet drivers are fastest and slowest today.\n\nHOW: For each fleet driver's completed calls today, we calculate their average ATA (time from call creation to driver on scene). Then rank all drivers.\n\nFastest: Top 3 drivers with the lowest average ATA.\nSlowest: Bottom 3 drivers with the highest average ATA.\nThe number in parentheses is how many calls that driver completed.\n\nGOAL: Identifies top performers and drivers who may need route optimization or are covering difficult areas."} />
              </div>
              {lb.top?.length > 0 && (
                <div className="mb-3">
                  <div className="text-[9px] text-emerald-500/70 uppercase tracking-wider mb-1">Fastest</div>
                  {lb.top.map((d, i) => (
                    <div key={i} className="flex items-center justify-between text-xs py-0.5">
                      <span className="text-slate-300 truncate mr-2">{d.name}</span>
                      <span className="text-emerald-400 font-semibold whitespace-nowrap">{d.avg_ata}m <span className="text-slate-600 font-normal">({d.calls})</span></span>
                    </div>
                  ))}
                </div>
              )}
              {lb.bottom?.length > 0 && (
                <div>
                  <div className="text-[9px] text-red-500/70 uppercase tracking-wider mb-1">Slowest</div>
                  {lb.bottom.map((d, i) => (
                    <div key={i} className="flex items-center justify-between text-xs py-0.5">
                      <span className="text-slate-300 truncate mr-2">{d.name}</span>
                      <span className="text-red-400 font-semibold whitespace-nowrap">{d.avg_ata}m <span className="text-slate-600 font-normal">({d.calls})</span></span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── Row 3: Reassignment Cost ── */}
        {ra && (
          <div className={clsx('glass rounded-xl p-4', ra.total_bounces > 0 ? 'border border-red-800/30 bg-red-950/10' : 'border border-slate-700/30')}>
            <div className="flex items-center gap-2 mb-4">
              <RefreshCw className="w-4 h-4 text-red-400" />
              <span className="text-xs font-bold text-white uppercase tracking-wide">Reassignment Cost</span>
              <InfoTip text={"WHAT: Time lost when a garage gets assigned a call but doesn't respond, forcing a reassignment.\n\nHOW: We track every time a Service Appointment goes from 'Assigned' back to 'Dispatched' in Salesforce history. Each bounce = the garage received the call but didn't accept it. We measure the exact time between assignment and bounce-back.\n\nThe 'Top Offenders' shows which garages are bouncing the most calls today and how much total time was wasted waiting for them.\n\nGOAL: Zero bounces. Every bounce adds ~10+ minutes of wait time for the member. Chronic offenders may need follow-up or removal from rotation."} />
              <div className="ml-auto flex items-center gap-4">
                <div className="text-center">
                  <div className="text-xl font-bold text-red-400">{ra.total_bounces}</div>
                  <div className="text-[9px] text-slate-500">Bounces</div>
                </div>
                <div className="text-center">
                  <div className="text-xl font-bold text-red-400">{ra.affected_calls}</div>
                  <div className="text-[9px] text-slate-500">Calls Affected</div>
                </div>
                <div className="text-center">
                  <div className="text-xl font-bold text-red-300">{ra.minutes_lost >= 60 ? `${Math.floor(ra.minutes_lost/60)}h ${ra.minutes_lost%60}m` : `${ra.minutes_lost}m`}</div>
                  <div className="text-[9px] text-slate-500">Total Time Lost</div>
                </div>
                <div className="text-center">
                  <div className="text-xl font-bold text-amber-400">{ra.avg_bounce_min}m</div>
                  <div className="text-[9px] text-slate-500">Avg per Bounce</div>
                </div>
              </div>
            </div>
            {ra.total_bounces === 0 && (
              <div className="text-xs text-emerald-400/70 text-center py-2">No reassignment delays today</div>
            )}
            {ra.top_offenders?.length > 0 && (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <div className="text-[9px] text-red-400/70 uppercase tracking-wider font-bold">Top Offenders — Sorted by Time Lost</div>
                  <div className="text-[9px] text-slate-600">Avg delay = time garage sat on call before bouncing</div>
                </div>
                <div className="grid grid-cols-1 gap-1">
                  {ra.top_offenders.slice(0, 5).map((g, i) => (
                    <div key={i} className="flex items-center gap-3 text-xs bg-slate-900/40 rounded-lg px-3 py-2">
                      <span className="w-5 h-5 rounded-full bg-red-950/60 border border-red-800/40 flex items-center justify-center text-[10px] font-bold text-red-400">{i+1}</span>
                      <span className="text-slate-300 flex-1 truncate">{g.name}</span>
                      <span className="text-red-400 font-bold">{g.count} bounce{g.count !== 1 ? 's' : ''}</span>
                      <span className="text-amber-400 font-medium">{g.avg_delay || Math.round(g.minutes / Math.max(g.count, 1))}m avg</span>
                      <span className="text-red-300 font-bold">{g.minutes}m lost</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Row 4: Dispatchers + Capacity Alerts ── */}
        <div className="grid grid-cols-2 gap-4">
          {/* Top Dispatchers */}
          {dispatchers && dispatchers.length > 0 && (
            <div className="glass rounded-xl border border-slate-700/30 p-4">
              <div className="flex items-center gap-2 mb-3">
                <Users className="w-4 h-4 text-amber-400" />
                <span className="text-xs font-bold text-white uppercase tracking-wide">Top Dispatchers</span>
                <InfoTip text={"WHAT: Which dispatchers are manually assigning the most fleet calls today.\n\nHOW: When a call's dispatch method is not 'Field Services' (auto-scheduler), it was manually assigned. We look at who last modified the assignment to identify the dispatcher.\n\nGOAL: High manual counts may indicate the auto-scheduler isn't covering enough, or that dispatchers are overriding system assignments."} />
              </div>
              <div className="space-y-1">
                {dispatchers.map((d, i) => (
                  <div key={i} className="flex items-center justify-between text-xs py-1 border-b border-slate-800/30 last:border-0">
                    <span className="text-slate-300">{d.name}</span>
                    <span className="text-white font-bold">{d.count}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Capacity Alerts */}
          {overCap.length > 0 && (
            <div className="glass rounded-xl border border-slate-700/30 p-4">
              <div className="flex items-center gap-2 mb-3">
                <AlertCircle className="w-4 h-4 text-red-400" />
                <span className="text-xs font-bold text-white uppercase tracking-wide">Capacity Alerts</span>
                <InfoTip text={"WHAT: Garages struggling with call volume right now.\n\nFleet garages: flagged when open calls outnumber GPS-active drivers (open/drv ratio).\nContractor garages (ⓒ): flagged by open call count + wait time, since their real driver count isn't tracked in Salesforce.\n\nOver = significantly overloaded. Busy = near capacity.\n\nGOAL: No garage should stay 'Over' for long."} />
              </div>
              <div className="space-y-1.5">
                {overCap.slice(0, 8).map(t => (
                  <div key={t.id} className="flex items-center gap-2 text-xs">
                    <span className={clsx('px-1.5 py-0.5 rounded text-[8px] font-bold uppercase',
                      t.capacity === 'over' ? 'bg-red-950/60 text-red-400' : 'bg-amber-950/50 text-amber-400'
                    )}>{t.capacity === 'over' ? 'Over' : 'Busy'}</span>
                    <span className="text-slate-300 truncate flex-1">{t.name}{t.is_contractor ? ' ⓒ' : ''}</span>
                    <span className="text-slate-500 whitespace-nowrap">
                      {t.is_contractor
                        ? `${t.open} open${t.max_wait ? ` · ${t.max_wait}m wait` : ''}`
                        : `${t.open} open / ${t.avail_drivers} drv`}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ── Row 5: Cancellation Breakdown + Decline Reasons ── */}
        <div className="grid grid-cols-2 gap-4">
          {/* Cancellation Breakdown */}
          {cb && cb.total > 0 && (
            <div className="glass rounded-xl border border-slate-700/30 p-4">
              <div className="flex items-center gap-2 mb-3">
                <XCircle className="w-4 h-4 text-orange-400" />
                <span className="text-xs font-bold text-white uppercase tracking-wide">Cancel Reasons</span>
                <InfoTip text={"WHY calls are being canceled today.\n\n• 'Member Could Not Wait' = member gave up waiting → response time too slow. This is the #1 actionable cancel.\n• 'Member Got Going' = self-resolved (flat fixed, car started). Not your fault.\n• 'Facility Initiated' = garage canceled the call. Investigate why.\n• 'Duplicate Call' = double entry, ignore.\n\nGOAL: Keep 'Could Not Wait' < 3% of total calls. High rate = members are abandoning."} />
                <span className="text-sm font-bold text-orange-400 ml-auto">{cb.total}</span>
              </div>
              <div className="space-y-1.5">
                {cb.reasons.map((r, i) => {
                  const isCnw = r.reason.toLowerCase().includes('could not wait')
                  return (
                    <div key={i} className="flex items-center gap-2 text-xs">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between mb-0.5">
                          <span className={clsx('truncate', isCnw ? 'text-red-400 font-medium' : 'text-slate-300')}>{r.reason}</span>
                          <span className={clsx('font-bold ml-2 whitespace-nowrap', isCnw ? 'text-red-400' : 'text-slate-400')}>{r.count} <span className="text-slate-600 font-normal">({r.pct}%)</span></span>
                        </div>
                        <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
                          <div className={clsx('h-full rounded-full', isCnw ? 'bg-red-500' : 'bg-orange-600/60')}
                               style={{ width: `${r.pct}%` }} />
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Decline/Rejection Reasons */}
          {db && db.total > 0 && (
            <div className="glass rounded-xl border border-slate-700/30 p-4">
              <div className="flex items-center gap-2 mb-3">
                <ThumbsDown className="w-4 h-4 text-rose-400" />
                <span className="text-xs font-bold text-white uppercase tracking-wide">Decline Reasons</span>
                <InfoTip text={"WHY garages are declining assigned calls today.\n\n• 'End of Shift' = timing gap. Garage closed but still getting calls.\n• 'Meal/Break' = driver unavailable temporarily.\n• 'Out of Area' = routing problem. Call sent to wrong zone.\n• 'Truck not capable' = skill mismatch. Battery truck sent to tow call.\n• 'Towbook Decline' = external contractor refusing work.\n\nEach decline adds ~10 min delay (call cascades to next garage).\nGOAL: Reduce declines by fixing routing and shift alignment."} />
                <span className="text-sm font-bold text-rose-400 ml-auto">{db.total}</span>
              </div>
              <div className="space-y-1.5">
                {db.reasons.map((r, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between mb-0.5">
                        <span className="text-slate-300 truncate">{r.reason}</span>
                        <span className="text-slate-400 font-bold ml-2 whitespace-nowrap">{r.count} <span className="text-slate-600 font-normal">({r.pct}%)</span></span>
                      </div>
                      <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
                        <div className="h-full rounded-full bg-rose-600/60" style={{ width: `${r.pct}%` }} />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ── Row 6: Fleet Utilization + Hourly Volume ── */}
        <div className="grid grid-cols-2 gap-4">
          {/* Fleet Utilization Gauge */}
          {fu && fu.total_on_shift > 0 && (
            <div className="glass rounded-xl border border-slate-700/30 p-4">
              <div className="flex items-center gap-2 mb-3">
                <Activity className="w-4 h-4 text-violet-400" />
                <span className="text-xs font-bold text-white uppercase tracking-wide">Fleet Utilization</span>
                <InfoTip text={"WHAT: How much of your on-shift fleet is currently busy vs idle.\n\nOn Shift = drivers logged into a truck (Asset). Busy = on an active SA (Dispatched/Assigned/In Progress/En Route/On Location).\n\nBroken down by tier:\n• Tow = can do tow + light service + battery\n• Light = tire/lockout/fuel/winch + battery\n• Battery = battery-only trucks\n\nGOAL: 60-80% utilization is healthy. Below 50% = overstaffed. Above 90% = no capacity buffer for surges."} />
              </div>
              {/* Big gauge */}
              <div className="flex items-center gap-4 mb-3">
                <div className="relative w-20 h-20">
                  <svg viewBox="0 0 36 36" className="w-20 h-20 -rotate-90">
                    <circle cx="18" cy="18" r="14" fill="none" stroke="#1e293b" strokeWidth="4" />
                    <circle cx="18" cy="18" r="14" fill="none"
                      stroke={fu.utilization_pct >= 90 ? '#ef4444' : fu.utilization_pct >= 60 ? '#a78bfa' : '#22c55e'}
                      strokeWidth="4" strokeDasharray={`${fu.utilization_pct * 0.88} 88`} strokeLinecap="round" />
                  </svg>
                  <div className="absolute inset-0 flex items-center justify-center">
                    <span className={clsx('text-lg font-bold',
                      fu.utilization_pct >= 90 ? 'text-red-400' : fu.utilization_pct >= 60 ? 'text-violet-400' : 'text-emerald-400'
                    )}>{fu.utilization_pct}%</span>
                  </div>
                </div>
                <div className="flex-1 space-y-1">
                  <div className="flex justify-between text-xs">
                    <span className="text-slate-500">On Shift</span>
                    <span className="text-white font-bold">{fu.total_on_shift}</span>
                  </div>
                  <div className="flex justify-between text-xs">
                    <span className="text-slate-500">Busy</span>
                    <span className="text-violet-400 font-bold">{fu.total_busy}</span>
                  </div>
                  <div className="flex justify-between text-xs">
                    <span className="text-slate-500">Idle</span>
                    <span className="text-emerald-400 font-bold">{fu.total_on_shift - fu.total_busy}</span>
                  </div>
                </div>
              </div>
              {/* Tier breakdown */}
              <div className="border-t border-slate-800/50 pt-2 space-y-1">
                {['tow', 'light', 'battery'].map(tier => {
                  const t = fu.by_tier?.[tier]
                  if (!t || t.on_shift === 0) return null
                  const pct = Math.round(100 * t.busy / Math.max(t.on_shift, 1))
                  return (
                    <div key={tier} className="flex items-center gap-2 text-[10px]">
                      <span className="text-slate-500 w-12 uppercase font-medium">{tier}</span>
                      <div className="flex-1 h-2 rounded-full bg-slate-800 overflow-hidden">
                        <div className={clsx('h-full rounded-full',
                          pct >= 90 ? 'bg-red-500' : pct >= 60 ? 'bg-violet-500' : 'bg-emerald-500'
                        )} style={{ width: `${pct}%` }} />
                      </div>
                      <span className="text-slate-400 w-16 text-right">{t.busy}/{t.on_shift} <span className="text-slate-600">({pct}%)</span></span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Hourly Volume */}
          {hv && hv.length > 0 && (
            <div className="glass rounded-xl border border-slate-700/30 p-4">
              <div className="flex items-center gap-2 mb-3">
                <BarChart3 className="w-4 h-4 text-sky-400" />
                <span className="text-xs font-bold text-white uppercase tracking-wide">Hourly Volume</span>
                <InfoTip text={"WHAT: Call volume by hour today (Eastern Time).\n\nShows when calls are coming in so you can spot peak hours and staffing gaps.\n\nPeak hours are highlighted. If peaks don't align with your shift coverage, you may need to adjust driver start times.\n\nGOAL: Smooth coverage across peak hours. No hour should have 3x the average without extra drivers available."} />
              </div>
              {(() => {
                const maxCount = Math.max(...hv.map(h => h.count), 1)
                const nowHour = new Date().getHours()
                // Only show 6am-11pm (business hours) to save space
                const filtered = hv.filter(h => h.hour >= 6 && h.hour <= 23)
                return (
                  <div className="flex items-end gap-px h-24">
                    {filtered.map(h => {
                      const pct = Math.max(h.count / maxCount * 100, 2)
                      const isPeak = h.count >= maxCount * 0.7
                      const isCurrent = h.hour === nowHour
                      return (
                        <div key={h.hour} className="flex-1 flex flex-col items-center justify-end h-full group relative">
                          <div className={clsx('w-full rounded-t-sm transition-colors',
                            isCurrent ? 'bg-sky-400' : isPeak ? 'bg-sky-500/80' : 'bg-slate-700/60'
                          )} style={{ height: `${pct}%` }} />
                          {h.hour % 3 === 0 && (
                            <span className="text-[7px] text-slate-600 mt-0.5">
                              {h.hour > 12 ? `${h.hour - 12}p` : h.hour === 0 ? '12a' : h.hour === 12 ? '12p' : `${h.hour}a`}
                            </span>
                          )}
                          {/* Tooltip on hover */}
                          <div className="absolute bottom-full mb-1 bg-slate-800 border border-slate-700 rounded px-1.5 py-0.5 text-[9px] text-white whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-10">
                            {h.hour > 12 ? `${h.hour - 12}:00 PM` : h.hour === 0 ? '12:00 AM' : h.hour === 12 ? '12:00 PM' : `${h.hour}:00 AM`}: {h.count} calls
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )
              })()}
              <div className="flex justify-between text-[9px] text-slate-600 mt-1">
                <span>Total: {hv.reduce((s, h) => s + h.count, 0)} calls</span>
                <span>Peak: {Math.max(...hv.map(h => h.count))}</span>
              </div>
            </div>
          )}

        </div>

        <div className="text-[10px] text-slate-600 text-center">
          Fleet · {data.is_fallback ? 'Last 24h' : 'Today'} · 2m auto-refresh
        </div>
      </div>
    </div>
  )
}

function InsightStat({ label, auto, manual }) {
  return (
    <div className="text-center">
      <div className="text-[8px] text-slate-500 uppercase tracking-wider mb-0.5">{label}</div>
      <div className="flex items-center justify-center gap-1">
        <span className="text-[7px] text-indigo-400/70">Sys</span>
        <span className="text-[10px] font-bold text-indigo-400">{auto}</span>
      </div>
      <div className="flex items-center justify-center gap-1">
        <span className="text-[7px] text-amber-500/50">Dsp</span>
        <span className="text-[10px] font-medium text-amber-500/70">{manual}</span>
      </div>
    </div>
  )
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
        {t.avail_drivers != null && <span className="text-[10px] text-slate-500">{t.avail_drivers} drv</span>}
        {t.capacity === 'over' && <span className="text-[8px] font-bold uppercase px-1 py-0.5 rounded bg-red-950/60 text-red-400 border border-red-800/30">Over Cap</span>}
        {t.capacity === 'busy' && <span className="text-[8px] font-bold uppercase px-1 py-0.5 rounded bg-amber-950/50 text-amber-400 border border-amber-800/30">Busy</span>}
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
