import React, { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { MapContainer, TileLayer, CircleMarker, Popup, Tooltip, Marker, Polyline, useMap, GeoJSON } from 'react-leaflet'
import L from 'leaflet'
import { clsx } from 'clsx'
import { fetchCommandCenter, lookupSA, fetchMapGrids, fetchMapDrivers, fetchMapWeather } from '../api'
import {
  Loader2, RefreshCw, Radio, CheckCircle2, AlertTriangle,
  ChevronRight, Search, MapPin, Clock, FileText,
  ChevronDown, ChevronUp, Crosshair, X, Truck, Layers
} from 'lucide-react'

// ── Layer helpers ──────────────────────────────────────────────────────────

const WMO_EMOJI = {
  0:'☀️',1:'🌤️',2:'⛅',3:'☁️',45:'🌫️',48:'🌫️',
  51:'🌦️',53:'🌦️',55:'🌧️',61:'🌧️',63:'🌧️',65:'⛈️',
  66:'🌧️',67:'⛈️',71:'🌨️',73:'❄️',75:'❄️',77:'🌨️',
  80:'🌦️',81:'🌧️',82:'⛈️',85:'🌨️',86:'❄️',
  95:'⛈️',96:'⛈️',99:'⛈️',
}

function makeLayerTruckIcon(driverType) {
  const color = (driverType || '').toLowerCase().includes('tow') ? '#f59e0b' : '#818cf8'
  return L.divIcon({
    className: '',
    iconSize: [22, 18], iconAnchor: [11, 18], popupAnchor: [0, -18],
    html: `<svg width="22" height="18" viewBox="0 0 22 18">
      <rect x="1" y="4" width="20" height="11" rx="2.5" fill="${color}" stroke="#0f172a" stroke-width="1.2"/>
      <rect x="14" y="1.5" width="8" height="8" rx="1.5" fill="${color}" stroke="#0f172a" stroke-width="1.2"/>
      <circle cx="6"  cy="17" r="2" fill="#0f172a" stroke="${color}" stroke-width="1.2"/>
      <circle cx="16" cy="17" r="2" fill="#0f172a" stroke="${color}" stroke-width="1.2"/>
    </svg>`,
  })
}

function makeWeatherMarkerIcon(s) {
  const emoji = WMO_EMOJI[s.weather_code] ?? '🌡️'
  return L.divIcon({
    className: '',
    iconSize: [72, 44], iconAnchor: [36, 44], popupAnchor: [0, -44],
    html: `<div style="background:#0f172a;border:1px solid #334155;border-radius:8px;
      padding:4px 8px;text-align:center;color:white;
      font-family:-apple-system,sans-serif;white-space:nowrap;
      box-shadow:0 4px 12px rgba(0,0,0,0.6)">
      <div style="font-size:13px;font-weight:700">${emoji} ${s.temp_f}°F</div>
      <div style="font-size:10px;color:#94a3b8;margin-top:1px">${s.name}</div>
    </div>`,
  })
}

const gridFeatureStyle = (feature) => ({
  color: feature.properties.color || '#818cf8',
  weight: 1.5, opacity: 0.85,
  fillColor: feature.properties.color || '#818cf8',
  fillOpacity: 0.1,
})

function onEachGridFeature(feature, layer) {
  layer.bindTooltip(feature.properties.name, { permanent: false, direction: 'center', className: 'cc-tooltip' })
  layer.bindPopup(`<strong>${feature.properties.name}</strong><br/>${feature.properties.territory_name}`)
}

const STATUS_COLORS = {
  good:     { fill: '#22c55e', border: '#16a34a', bg: 'bg-emerald-500', text: 'text-emerald-400' },
  behind:   { fill: '#eab308', border: '#ca8a04', bg: 'bg-amber-500',   text: 'text-amber-400' },
  critical: { fill: '#ef4444', border: '#dc2626', bg: 'bg-red-500',     text: 'text-red-400' },
}

const SA_COLORS = {
  Dispatched: '#3b82f6', Assigned: '#3b82f6', Completed: '#22c55e',
  Canceled: '#6b7280', 'Cancel Call - Service Not En Route': '#f97316',
  'Cancel Call - Service En Route': '#f97316', 'Unable to Complete': '#f97316', 'No-Show': '#6b7280',
}

const MAP_LEGEND = [
  { color: '#3b82f6', label: 'Dispatched / Assigned' },
  { color: '#22c55e', label: 'Completed' },
  { color: '#f97316', label: 'Canceled En Route / Unable' },
  { color: '#6b7280', label: 'Canceled / No-Show' },
]

const TERRITORY_LEGEND = [
  { color: '#22c55e', label: 'On Track' },
  { color: '#eab308', label: 'Behind' },
  { color: '#ef4444', label: 'Critical' },
]

const WINDOWS = [
  { label: '2h', hours: 2 }, { label: '4h', hours: 4 }, { label: '8h', hours: 8 },
  { label: '12h', hours: 12 }, { label: '24h', hours: 24 },
  { label: '48h', hours: 48 }, { label: '7d',  hours: 168 },
]

const DARK_TILES = 'https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png'
const REFRESH_MS = 5 * 60 * 1000

function fmtWait(min) {
  if (!min || min <= 0) return '—'
  const h = Math.floor(min / 60)
  const m = min % 60
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

// Driver truck icon for SA lookup
function driverIcon(dist, isClosest) {
  const color = isClosest ? '#22c55e' : '#94a3b8'
  return L.divIcon({
    className: '',
    iconSize: [28, 34],
    iconAnchor: [14, 34],
    popupAnchor: [0, -34],
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

// Customer pin for SA lookup
const customerIcon = L.divIcon({
  className: '',
  iconSize: [20, 28],
  iconAnchor: [10, 28],
  popupAnchor: [0, -28],
  html: `<div style="text-align:center">
    <svg width="20" height="28" viewBox="0 0 20 28">
      <path d="M10 0C4.5 0 0 4.5 0 10c0 7 10 18 10 18s10-11 10-18C20 4.5 15.5 0 10 0z" fill="#ef4444" stroke="#fff" stroke-width="1.5"/>
      <circle cx="10" cy="10" r="4" fill="#fff"/>
    </svg>
  </div>`,
})

export default function CommandCenter() {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [hours, setHours] = useState(24)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [focusCenter, setFocusCenter] = useState(null)
  const [showSADots, setShowSADots] = useState(true)
  const [panelOpen, setPanelOpen] = useState(true)
  const [panelTab, setPanelTab] = useState('briefing') // briefing | waiting | search
  const [lastRefresh, setLastRefresh] = useState(null)
  const [countdown, setCountdown] = useState(300)

  // SA search state
  const [saQuery, setSaQuery] = useState('')
  const [saResult, setSaResult] = useState(null)
  const [saLoading, setSaLoading] = useState(false)
  const [saError, setSaError] = useState(null)

  // Map layers state
  const [layers, setLayers] = useState({ grid: false, drivers: false, weather: false })
  const [grids, setGrids] = useState(null)
  const [allDrivers, setAllDrivers] = useState([])
  const [mapWeather, setMapWeather] = useState([])
  const [layerLoading, setLayerLoading] = useState({ grid: false, drivers: false, weather: false })

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    fetchCommandCenter(hours)
      .then(d => { setData(d); setLastRefresh(new Date()); setCountdown(300) })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
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

  useEffect(() => {
    if (!layers.grid || grids !== null) return
    setLayerLoading(l => ({ ...l, grid: true }))
    fetchMapGrids()
      .then(d => { setGrids(d); setLayerLoading(l => ({ ...l, grid: false })) })
      .catch(() => setLayerLoading(l => ({ ...l, grid: false })))
  }, [layers.grid])

  useEffect(() => {
    if (!layers.drivers || allDrivers.length > 0) return
    setLayerLoading(l => ({ ...l, drivers: true }))
    fetchMapDrivers()
      .then(d => { setAllDrivers(d); setLayerLoading(l => ({ ...l, drivers: false })) })
      .catch(() => setLayerLoading(l => ({ ...l, drivers: false })))
  }, [layers.drivers])

  useEffect(() => {
    if (!layers.weather || mapWeather.length > 0) return
    setLayerLoading(l => ({ ...l, weather: true }))
    fetchMapWeather()
      .then(d => { setMapWeather(d); setLayerLoading(l => ({ ...l, weather: false })) })
      .catch(() => setLayerLoading(l => ({ ...l, weather: false })))
  }, [layers.weather])

  const searchSA = () => {
    if (!saQuery.trim()) return
    setSaLoading(true)
    setSaError(null)
    setSaResult(null)
    lookupSA(saQuery.trim())
      .then(r => {
        setSaResult(r)
        if (r.sa.lat && r.sa.lon) setFocusCenter([r.sa.lat, r.sa.lon])
      })
      .catch(e => setSaError(e.response?.data?.detail || e.message))
      .finally(() => setSaLoading(false))
  }

  const clearSA = () => { setSaResult(null); setSaError(null); setSaQuery('') }

  const territories = data?.territories || []
  const openCustomers = data?.open_customers || []
  const summary = data?.summary || {}
  const criticals = territories.filter(t => t.status === 'critical')
  const behinds = territories.filter(t => t.status === 'behind')

  const filtered = territories.filter(t => {
    if (statusFilter !== 'all' && t.status !== statusFilter) return false
    if (search && !t.name.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  return (
    <div className="-mx-6 -mt-6 flex" style={{ height: 'calc(100vh - 56px)' }}>
      {/* ── Map ──────────────────────────────────────────────────────── */}
      <div className="flex-1 relative cc-map">
        {/* Map Legend */}
        <div style={{
          position: 'absolute', bottom: 12, left: 12, zIndex: 1000,
          background: 'rgba(15,23,42,0.85)', backdropFilter: 'blur(8px)',
          border: '1px solid rgba(71,85,105,0.4)', borderRadius: 10,
          padding: '8px 12px', fontSize: 11, color: '#cbd5e1',
          pointerEvents: 'auto',
        }}>
          <div style={{ fontWeight: 600, fontSize: 10, color: '#94a3b8', marginBottom: 4, textTransform: 'uppercase', letterSpacing: 0.5 }}>
            {showSADots ? 'SA Status' : 'Territory Health'}
          </div>
          {(showSADots ? MAP_LEGEND : TERRITORY_LEGEND).map(l => (
            <div key={l.label} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
              <span style={{
                width: 8, height: 8, borderRadius: '50%', display: 'inline-block',
                background: l.color, boxShadow: `0 0 4px ${l.color}50`,
              }} />
              <span>{l.label}</span>
            </div>
          ))}
        </div>

        <MapContainer center={[40, -82]} zoom={5} className="w-full h-full"
                      zoomControl={false} attributionControl={false}>
          <TileLayer url={DARK_TILES} />
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
            t.sa_points.map((sa, i) => (
              <CircleMarker key={`${t.id}-${i}`} center={[sa.lat, sa.lon]} radius={3}
                pathOptions={{
                  color: SA_COLORS[sa.status] || '#6b7280',
                  fillColor: SA_COLORS[sa.status] || '#6b7280',
                  fillOpacity: 0.7, weight: 1, opacity: 0.9,
                }}
              >
                <Popup>
                  <div style={{ fontSize: 12, color: '#e2e8f0' }}>
                    <div style={{ fontWeight: 700 }}>{sa.work_type}</div>
                    <div>{sa.status} at {sa.time}</div>
                  </div>
                </Popup>
              </CircleMarker>
            ))
          )}

          {/* ── SA Lookup markers ──────────────────────────────── */}
          {saResult && saResult.sa.lat && saResult.sa.lon && (() => {
            const closestDriver = saResult.drivers.find(d => d.lat && d.lon)
            return (
              <>
                {/* Customer pin */}
                <Marker position={[saResult.sa.lat, saResult.sa.lon]} icon={customerIcon}>
                  <Tooltip direction="top" offset={[0, -30]} opacity={0.95} permanent={false}
                    className="cc-tooltip">
                    <div style={{ fontSize: 12, color: '#e2e8f0', minWidth: 220, padding: 2 }}>
                      <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 3 }}>
                        {saResult.sa.customer || 'Member'}
                      </div>
                      <div style={{ color: '#94a3b8' }}>
                        {saResult.sa.address}{saResult.sa.zip && ` (${saResult.sa.zip})`}<br />
                        {saResult.sa.phone && (
                          <><span style={{ color: '#60a5fa' }}>{saResult.sa.phone}</span><br /></>
                        )}
                        SA# <span style={{ color: '#e2e8f0', fontWeight: 600 }}>{saResult.sa.number}</span>
                        {' — '}<span style={{ color: '#e2e8f0' }}>{saResult.sa.work_type}</span><br />
                        Status: <span style={{ color: '#e2e8f0', fontWeight: 600 }}>{saResult.sa.status}</span><br />
                        {saResult.sa.response_min && (
                          <>Response: <span style={{ color: saResult.sa.response_min <= 45 ? '#22c55e' : '#ef4444', fontWeight: 700 }}>{saResult.sa.response_min} min</span><br /></>
                        )}
                      </div>
                      {closestDriver && (
                        <div style={{ marginTop: 5, padding: '3px 6px', background: 'rgba(34,197,94,0.1)',
                                      borderRadius: 5, border: '1px solid rgba(34,197,94,0.25)' }}>
                          <span style={{ color: '#22c55e', fontWeight: 700, fontSize: 11 }}>Closest: </span>
                          <span style={{ color: '#22c55e', fontWeight: 600 }}>{closestDriver.name}</span>
                          <span style={{ color: '#e2e8f0', fontWeight: 700 }}> — {closestDriver.distance ?? '?'} mi</span>
                        </div>
                      )}
                    </div>
                  </Tooltip>
                </Marker>

                {/* Line from closest driver to customer */}
                {closestDriver && (
                  <>
                    <Polyline
                      positions={[[closestDriver.lat, closestDriver.lon], [saResult.sa.lat, saResult.sa.lon]]}
                      pathOptions={{ color: '#22c55e', weight: 3, opacity: 0.7, dashArray: '8,6' }}
                    />
                    <CircleMarker center={[closestDriver.lat, closestDriver.lon]} radius={18}
                      pathOptions={{ color: '#22c55e', weight: 2, fillOpacity: 0.06, opacity: 0.35 }} />
                  </>
                )}
              </>
            )
          })()}

          {saResult && saResult.drivers.filter(d => d.lat && d.lon).map((d, i) => (
            <React.Fragment key={d.id}>
              <Marker position={[d.lat, d.lon]}
                      icon={driverIcon(d.distance, i === 0)}>
                <Tooltip direction="top" offset={[0, -36]} opacity={0.95}
                  className="cc-tooltip">
                  <div style={{ fontSize: 12, color: '#e2e8f0', minWidth: 210, padding: 2 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
                      <strong style={{ fontSize: 14, color: i === 0 ? '#22c55e' : '#e2e8f0' }}>
                        {d.name}
                      </strong>
                      {i === 0 && (
                        <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 3,
                          background: 'rgba(34,197,94,0.15)', color: '#22c55e',
                          border: '1px solid rgba(34,197,94,0.3)' }}>CLOSEST</span>
                      )}
                    </div>
                    <div style={{ color: '#94a3b8' }}>
                      Distance: <span style={{ color: '#e2e8f0', fontWeight: 700 }}>{d.distance ?? '?'} mi</span><br />
                      {d.phone && (
                        <><span style={{ color: '#60a5fa' }}>{d.phone}</span><br /></>
                      )}
                      GPS: {d.gps_time} — {d.territory_type}
                    </div>
                    {d.next_job && (
                      <div style={{ marginTop: 4, padding: '3px 6px', background: 'rgba(234,179,8,0.08)',
                                    borderRadius: 5, border: '1px solid rgba(234,179,8,0.2)' }}>
                        <span style={{ color: '#eab308', fontWeight: 700, fontSize: 10 }}>NEXT: </span>
                        <span style={{ color: '#94a3b8' }}>SA# {d.next_job.number} — {d.next_job.work_type}</span><br />
                        <span style={{ color: '#94a3b8', fontSize: 11 }}>{d.next_job.address}</span>
                      </div>
                    )}
                    {!d.next_job && (
                      <div style={{ marginTop: 3, color: '#22c55e', fontSize: 11, fontWeight: 600 }}>Available — no active job</div>
                    )}
                  </div>
                </Tooltip>
              </Marker>

              {/* Line from driver to next job location */}
              {d.next_job && d.next_job.lat && d.next_job.lon && (
                <>
                  <Polyline
                    positions={[[d.lat, d.lon], [d.next_job.lat, d.next_job.lon]]}
                    pathOptions={{ color: '#eab308', weight: 2, opacity: 0.5, dashArray: '6,4' }}
                  />
                  <CircleMarker center={[d.next_job.lat, d.next_job.lon]} radius={5}
                    pathOptions={{ color: '#eab308', fillColor: '#eab308', fillOpacity: 0.4, weight: 1.5 }}>
                    <Tooltip direction="top" offset={[0, -8]} opacity={0.95} className="cc-tooltip">
                      <div style={{ fontSize: 11, color: '#e2e8f0', padding: 2 }}>
                        <strong>{d.name}</strong> next job<br />
                        <span style={{ color: '#94a3b8' }}>SA# {d.next_job.number} — {d.next_job.work_type}<br />{d.next_job.address}</span>
                      </div>
                    </Tooltip>
                  </CircleMarker>
                </>
              )}
            </React.Fragment>
          ))}

          {/* Dispatched position (where truck was) */}
          {saResult && saResult.sa.dispatched_lat && saResult.sa.dispatched_lon && (
            <CircleMarker center={[saResult.sa.dispatched_lat, saResult.sa.dispatched_lon]}
              radius={6} pathOptions={{ color: '#f97316', fillColor: '#f97316', fillOpacity: 0.5, weight: 2 }}>
              <Tooltip direction="top" offset={[0, -8]} opacity={0.95} className="cc-tooltip">
                <div style={{ fontSize: 11, color: '#e2e8f0' }}>
                  <strong style={{ color: '#f97316' }}>Truck at Dispatch</strong><br />
                  <span style={{ color: '#94a3b8' }}>{saResult.sa.truck_id || 'Unknown'}</span>
                </div>
              </Tooltip>
            </CircleMarker>
          )}

          {/* ── Grid layer ── */}
          {layers.grid && grids && grids.features.length > 0 && (
            <GeoJSON key="grids" data={grids} style={gridFeatureStyle} onEachFeature={onEachGridFeature} />
          )}

          {/* ── All-drivers layer (hidden during SA lookup to avoid confusion) ── */}
          {layers.drivers && !saResult && allDrivers.map(d => (
            <Marker key={d.id} position={[d.lat, d.lon]} icon={makeLayerTruckIcon(d.driver_type)}>
              <Popup>
                <div style={{ fontSize: 12, color: '#e2e8f0' }}>
                  <strong>{d.name}</strong><br />
                  {d.driver_type && <>{d.driver_type}<br /></>}
                  GPS: {d.gps_time}
                </div>
              </Popup>
            </Marker>
          ))}

          {/* ── Weather layer ── */}
          {layers.weather && mapWeather.map((s, i) => (
            !s.error && s.temp_f != null && (
              <Marker key={i} position={[s.lat, s.lon]} icon={makeWeatherMarkerIcon(s)}>
                <Popup>
                  <div style={{ fontSize: 12, color: '#e2e8f0' }}>
                    <strong>{s.name}</strong><br />
                    {s.temp_f}°F — {s.condition}<br />
                    Wind: {s.wind} mph
                    {s.snow > 0 && <><br />Snow: {s.snow}&quot;</>}
                  </div>
                </Popup>
              </Marker>
            )
          ))}
        </MapContainer>

        {/* ── Stats bar (top) ──────────────────────────────────── */}
        <div className="absolute top-3 left-3 right-3 z-[1000] pointer-events-none">
          <div className="pointer-events-auto inline-flex items-center gap-3 bg-slate-900/90 backdrop-blur-md
                          border border-slate-700/50 rounded-xl px-4 py-2.5 shadow-2xl">
            {loading && !data ? (
              <div className="flex items-center gap-2 text-sm text-slate-400">
                <Loader2 className="w-4 h-4 animate-spin" /> Loading...
              </div>
            ) : (
              <>
                <StatChip icon={MapPin} label="Territories" value={summary.total_territories} color="text-white" />
                <Div />
                <StatChip icon={Radio} label="Open" value={summary.total_open} color="text-blue-400" />
                <StatChip icon={CheckCircle2} label="Done" value={summary.total_completed} color="text-emerald-400" />
                <StatChip label="Total" value={summary.total_sas} color="text-slate-300" />
                <Div />
                <div className="flex items-center gap-2">
                  <Dot color="bg-emerald-500" n={summary.good} label="On Track" />
                  <Dot color="bg-amber-500" n={summary.behind} label="Behind" />
                  <Dot color="bg-red-500" n={summary.critical} label="Critical" />
                </div>
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
                  title={`Refresh (next: ${Math.floor(countdown/60)}:${String(countdown%60).padStart(2,'0')})`}>
                  <RefreshCw className={clsx('w-3.5 h-3.5 text-slate-400', loading && 'animate-spin')} />
                </button>
                <span className="text-[9px] text-slate-600 font-mono">
                  {Math.floor(countdown/60)}:{String(countdown%60).padStart(2,'0')}
                </span>
              </>
            )}
          </div>
        </div>

        {/* ── Floating Left Panel (3D glass) ────────────────────── */}
        {data && (
          <div className="absolute top-16 left-3 z-[1000] w-80">
            {/* Panel header — always visible */}
            <div className="bg-slate-900/95 backdrop-blur-xl border border-slate-600/40 rounded-t-xl
                            shadow-[0_8px_32px_rgba(0,0,0,0.5),0_0_0_1px_rgba(255,255,255,0.05)_inset]
                            px-3 py-2 flex items-center gap-2">
              <button onClick={() => setPanelOpen(p => !p)}
                className="flex items-center gap-2 flex-1 text-left">
                <FileText className="w-4 h-4 text-brand-400" />
                <span className="text-xs font-bold text-white tracking-wide uppercase">Command Brief</span>
                {panelOpen
                  ? <ChevronUp className="w-3 h-3 text-slate-400 ml-auto" />
                  : <ChevronDown className="w-3 h-3 text-slate-400 ml-auto" />}
              </button>
            </div>

            {panelOpen && (
              <div className="bg-slate-900/95 backdrop-blur-xl border border-t-0 border-slate-600/40 rounded-b-xl
                              shadow-[0_8px_32px_rgba(0,0,0,0.5),0_0_0_1px_rgba(255,255,255,0.05)_inset]">
                {/* Tab bar */}
                <div className="flex border-b border-slate-800/60 px-1 pt-1">
                  {[
                    { key: 'briefing', label: 'Briefing', icon: FileText },
                    { key: 'waiting', label: `Waiting (${openCustomers.length})`, icon: Clock },
                    { key: 'search', label: 'SA Lookup', icon: Crosshair },
                  ].map(tab => (
                    <button key={tab.key} onClick={() => setPanelTab(tab.key)}
                      className={clsx('flex items-center gap-1 px-2.5 py-1.5 text-[10px] font-semibold rounded-t-lg transition-all',
                        panelTab === tab.key
                          ? 'bg-slate-800/60 text-white border-b-2 border-brand-500'
                          : 'text-slate-500 hover:text-slate-300'
                      )}>
                      <tab.icon className="w-3 h-3" />
                      {tab.label}
                    </button>
                  ))}
                </div>

                <div className="max-h-[55vh] overflow-y-auto">
                  {/* ── Briefing Tab ──────────────────────────── */}
                  {panelTab === 'briefing' && (
                    <div className="px-4 py-3 space-y-3">
                      <div className="text-xs text-slate-300 leading-relaxed">
                        <span className="font-bold text-white">{summary.total_territories}</span> territories active with{' '}
                        <span className="font-bold text-white">{summary.total_sas?.toLocaleString()}</span> SAs.{' '}
                        <span className="font-bold text-blue-400">{summary.total_open}</span> open,{' '}
                        <span className="font-bold text-emerald-400">{summary.total_completed?.toLocaleString()}</span> completed.
                      </div>

                      {(summary.critical > 0 || summary.behind > 0) && (
                        <div className="bg-red-950/40 border border-red-800/30 rounded-lg px-3 py-2">
                          <div className="flex items-center gap-1.5 mb-1">
                            <AlertTriangle className="w-3.5 h-3.5 text-red-400" />
                            <span className="text-[10px] font-bold text-red-400 uppercase tracking-wider">Attention</span>
                          </div>
                          <div className="text-xs text-slate-300">
                            {summary.critical > 0 && <><span className="font-bold text-red-400">{summary.critical}</span> critical. </>}
                            {summary.behind > 0 && <><span className="font-bold text-amber-400">{summary.behind}</span> behind. </>}
                            {summary.total_open > 10 && <><span className="font-bold text-blue-400">{summary.total_open}</span> awaiting service.</>}
                          </div>
                        </div>
                      )}

                      {criticals.length > 0 && (
                        <div>
                          <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1.5">Top Concerns</div>
                          <div className="space-y-1.5">
                            {criticals.slice(0, 5).map((t, i) => (
                              <div key={t.id} className="flex items-start gap-2 text-xs">
                                <span className="w-4 h-4 rounded-full bg-red-500/20 text-red-400 text-[10px]
                                                 font-bold flex items-center justify-center flex-shrink-0 mt-0.5">{i+1}</span>
                                <div className="min-w-0">
                                  <div className="font-medium text-white truncate">{t.name}</div>
                                  <div className="text-slate-400">
                                    {t.total} SAs, {t.open} open
                                    {t.sla_pct != null && <span className="text-red-400"> — SLA {t.sla_pct}%</span>}
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {behinds.length > 0 && (
                        <div className="text-xs text-slate-400">
                          <span className="font-bold text-slate-500 text-[10px] uppercase">Behind ({behinds.length}):</span>{' '}
                          {behinds.slice(0, 3).map(t => t.name).join(', ')}{behinds.length > 3 && ` +${behinds.length - 3} more`}
                        </div>
                      )}

                      {summary.good > 0 && (
                        <div className="text-xs text-emerald-400/80">{summary.good} territories on track.</div>
                      )}

                      <div className="text-[10px] text-slate-600 pt-1 border-t border-slate-800/50">
                        {lastRefresh && <>Refreshed: {lastRefresh.toLocaleTimeString()} — </>}
                        Next: {Math.floor(countdown/60)}:{String(countdown%60).padStart(2,'0')} (auto 5m)
                      </div>
                    </div>
                  )}

                  {/* ── Waiting Tab ───────────────────────────── */}
                  {panelTab === 'waiting' && (
                    <div>
                      {openCustomers.length === 0 ? (
                        <div className="text-center py-8 text-xs text-slate-500">No open SAs waiting</div>
                      ) : (
                        <>
                        <div className="px-3 pt-1.5 pb-1 space-y-1">
                          <div className="text-[9px] text-slate-600">ASAP calls only — scheduled-for-later excluded</div>
                          <div className="flex items-center gap-3 text-[9px]">
                            <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-red-400" />2h+ critical</span>
                            <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-amber-400" />1h+ behind</span>
                            <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-blue-400" />&lt;1h</span>
                          </div>
                        </div>
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="text-[10px] text-slate-500 uppercase tracking-wider">
                              <th className="text-left px-2 py-2">#</th>
                              <th className="text-left px-1 py-2">Member</th>
                              <th className="text-right px-1 py-2">Wait</th>
                              <th className="text-left px-2 py-2">Type</th>
                            </tr>
                          </thead>
                          <tbody>
                            {openCustomers.slice(0, 20).map((c, i) => (
                              <tr key={i} className={clsx('border-t border-slate-800/40',
                                c.wait_min > 120 ? 'bg-red-950/20' : c.wait_min > 60 ? 'bg-amber-950/20' : ''
                              )}>
                                <td className="px-2 py-1.5 text-slate-500 font-mono">{i+1}</td>
                                <td className="px-1 py-1.5 max-w-[130px]">
                                  <div className="text-white font-medium truncate">{c.customer || c.address || '—'}</div>
                                  <div className="text-[10px] text-slate-500 font-mono">{c.number}</div>
                                  <div className="flex items-center gap-1.5 mt-0.5">
                                    <span className="text-slate-500 font-mono text-[10px]">{c.zip || '—'}</span>
                                    {c.phone && (
                                      <a href={`tel:${c.phone}`}
                                         className="text-brand-400 hover:text-brand-300 text-[10px] font-mono truncate"
                                         title={c.phone} onClick={e => e.stopPropagation()}>
                                        {c.phone}
                                      </a>
                                    )}
                                  </div>
                                </td>
                                <td className={clsx('px-1 py-1.5 text-right font-bold',
                                  c.wait_min > 120 ? 'text-red-400' : c.wait_min > 60 ? 'text-amber-400' : 'text-blue-400'
                                )}>{fmtWait(c.wait_min)}</td>
                                <td className="px-2 py-1.5 text-slate-500 truncate max-w-[60px] text-[10px]">
                                  {c.work_type?.replace('Tow ', '').replace('Pick-Up', 'PU').replace('Drop-Off', 'DO')}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        </>
                      )}
                    </div>
                  )}

                  {/* ── SA Search Tab ─────────────────────────── */}
                  {panelTab === 'search' && (
                    <div className="px-4 py-3 space-y-3">
                      <div className="flex gap-2">
                        <input type="text" placeholder="SA-12345678" value={saQuery}
                          onChange={e => setSaQuery(e.target.value)}
                          onKeyDown={e => e.key === 'Enter' && searchSA()}
                          className="flex-1 px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-xs
                                     placeholder:text-slate-500 focus:outline-none focus:ring-1 focus:ring-brand-500/40"
                        />
                        <button onClick={searchSA} disabled={saLoading}
                          className="px-3 py-1.5 bg-brand-600 hover:bg-brand-500 rounded-lg text-[10px] font-bold
                                     text-white transition-colors disabled:opacity-50">
                          {saLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Crosshair className="w-3 h-3" />}
                        </button>
                        {saResult && (
                          <button onClick={clearSA} className="p-1.5 rounded-lg hover:bg-slate-700 transition-colors">
                            <X className="w-3 h-3 text-slate-400" />
                          </button>
                        )}
                      </div>

                      {saError && <div className="text-xs text-red-400">{saError}</div>}

                      {saResult && (
                        <div className="space-y-3">
                          {/* SA info */}
                          <div className="bg-slate-800/60 rounded-lg p-3">
                            <div className="text-sm font-bold text-white mb-1">
                              {saResult.sa.customer || 'Member'} — SA# {saResult.sa.number}
                            </div>
                            <div className="text-xs text-slate-400 space-y-0.5">
                              <div>{saResult.sa.work_type} — <span className="font-semibold text-white">{saResult.sa.status}</span></div>
                              <div>{saResult.sa.address} {saResult.sa.zip && `(${saResult.sa.zip})`}</div>
                              <div>Territory: {saResult.sa.territory}</div>
                              {saResult.sa.truck_id && <div>Truck: {saResult.sa.truck_id}</div>}
                              <div>Created: {saResult.sa.created}
                                {saResult.sa.started && <> — On-site: {saResult.sa.started}</>}
                                {saResult.sa.completed && <> — Done: {saResult.sa.completed}</>}
                              </div>
                              {saResult.sa.response_min && (
                                <div className={saResult.sa.response_min <= 45 ? 'text-emerald-400' : 'text-red-400'}>
                                  Response: {saResult.sa.response_min} min
                                </div>
                              )}
                            </div>
                          </div>

                          {/* Drivers */}
                          <div>
                            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1.5">
                              Territory Drivers ({saResult.drivers.length})
                            </div>
                            <div className="space-y-1">
                              {saResult.drivers.map((d, i) => (
                                <div key={d.id} className={clsx(
                                  'rounded-lg px-3 py-2 text-xs border',
                                  i === 0 ? 'bg-emerald-950/30 border-emerald-800/30' : 'bg-slate-800/40 border-slate-700/20'
                                )}>
                                  <div className="flex items-center justify-between">
                                    <span className={clsx('font-semibold', i === 0 ? 'text-emerald-400' : 'text-white')}>
                                      {d.name} {i === 0 && '(Closest)'}
                                    </span>
                                    <span className={clsx('font-bold', i === 0 ? 'text-emerald-400' : 'text-slate-300')}>
                                      {d.distance != null ? `${d.distance} mi` : 'No GPS'}
                                    </span>
                                  </div>
                                  <div className="text-slate-500 mt-0.5">
                                    {d.lat ? `GPS: ${d.gps_time}` : 'No GPS position'} — {d.territory_type}
                                  </div>
                                  {d.next_job ? (
                                    <div className="mt-1 text-[10px] text-amber-400">
                                      Assigned: SA# {d.next_job.number} — {d.next_job.work_type} at {d.next_job.address}
                                    </div>
                                  ) : (
                                    <div className="mt-1 text-[10px] text-emerald-400 font-medium">Available — no active job</div>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                        </div>
                      )}

                      {!saResult && !saError && (
                        <div className="text-xs text-slate-500 text-center py-4">
                          Enter an SA number to locate it on the map<br />
                          and see all territory drivers with positions
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Legend (bottom-left) ──────────────────────────────── */}
        <div className="absolute bottom-4 left-4 z-[1000]">
          <div className="bg-slate-900/90 backdrop-blur-md border border-slate-700/50 rounded-xl px-4 py-3 shadow-xl">
            <div className="flex items-center gap-4 text-xs">
              <LegendDot border="border-emerald-500" fill="bg-emerald-500/25" label="On Track" />
              <LegendDot border="border-amber-500" fill="bg-amber-500/25" label="Behind" />
              <LegendDot border="border-red-500" fill="bg-red-500/25" label="Critical" />
              <span className="text-slate-700">|</span>
              <LegendSmall color="bg-blue-500" label="Open" />
              <LegendSmall color="bg-emerald-500" label="Done" />
              <LegendSmall color="bg-orange-500" label="Canceled" />
              <span className="text-slate-700">|</span>
              <label className="flex items-center gap-1.5 cursor-pointer select-none">
                <input type="checkbox" checked={showSADots}
                       onChange={e => setShowSADots(e.target.checked)}
                       className="w-3 h-3 rounded accent-brand-500" />
                <span className="text-slate-400">Dots</span>
              </label>
            </div>
          </div>
        </div>

        {error && (
          <div className="absolute top-16 right-4 z-[1000] bg-red-950/90 border border-red-800/50
                          rounded-xl px-4 py-2 text-sm text-red-300 shadow-xl max-w-xs">{error}</div>
        )}

        {/* ── Layer toggle panel (top-right) ── */}
        <div className="absolute top-16 right-3 z-[1000]" style={{ minWidth: 150 }}>
          <div className="bg-slate-900/95 backdrop-blur-xl border border-slate-600/40 rounded-xl shadow-2xl overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-800/60">
              <Layers className="w-3.5 h-3.5 text-brand-400" />
              <span className="text-[10px] font-bold text-white uppercase tracking-wide">Layers</span>
            </div>
            <div className="px-3 py-2.5 space-y-2">
              {[
                { key: 'grid',    emoji: '🗺️', label: 'Grid',    color: 'text-indigo-400' },
                { key: 'drivers', emoji: '🚛', label: 'Drivers', color: 'text-amber-400' },
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

      {/* ── Territory Panel (right) ──────────────────────────────── */}
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
                  statusFilter === f ? 'bg-slate-700 text-white' : 'text-slate-500 hover:text-white'
                )}>
                {f === 'all' ? `All (${territories.length})` :
                 f === 'critical' ? `Critical (${summary.critical||0})` :
                 f === 'behind' ? `Behind (${summary.behind||0})` :
                 `Good (${summary.good||0})`}
              </button>
            ))}
          </div>
        </div>
        <div className="flex-1 overflow-y-auto">
          {loading && !data && (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-5 h-5 animate-spin text-slate-500" />
            </div>
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

/* ── Helpers ─────────────────────────────────────────────────────────────── */

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
function Dot({ color, n, label }) {
  return <span className="flex items-center gap-1">
    <span className={clsx('w-2 h-2 rounded-full', color)} />
    <span className="text-xs font-medium text-slate-300">{n}</span>
    {label && <span className="text-[10px] text-slate-500">{label}</span>}
  </span>
}
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
  const sc = STATUS_COLORS[t.status]
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
      <div style={{ marginTop: 6, padding: '3px 8px', borderRadius: 6,
                    background: sc?.fill, color: 'white', fontSize: 11,
                    fontWeight: 600, display: 'inline-block', textTransform: 'uppercase' }}>{t.status}</div>
    </div>
  )
}
