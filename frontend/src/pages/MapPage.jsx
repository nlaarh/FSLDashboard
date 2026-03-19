import React, { useState, useEffect, useRef } from 'react'
import { MapContainer, TileLayer, GeoJSON, Marker, CircleMarker, Tooltip, Popup, useMap } from 'react-leaflet'
import L from 'leaflet'
import { Layers, Loader2, Search, X } from 'lucide-react'
import { fetchMapGrids, fetchMapDrivers, fetchMapWeather, fetchCommandCenter } from '../api'
import { getMapConfig } from '../mapStyles'
import SALink from '../components/SALink'

const SA_COLORS = {
  Dispatched: '#3b82f6',
  Assigned: '#3b82f6',
  Completed: '#22c55e',
  Canceled: '#6b7280',
  'Cancel Call - Service Not En Route': '#f97316',
  'Cancel Call - Service En Route': '#f97316',
  'Unable to Complete': '#f97316',
  'No-Show': '#6b7280',
}

const WMO_EMOJI = {
  0: '☀️', 1: '🌤️', 2: '⛅', 3: '☁️',
  45: '🌫️', 48: '🌫️',
  51: '🌦️', 53: '🌦️', 55: '🌧️',
  56: '🌧️', 57: '🌧️',
  61: '🌧️', 63: '🌧️', 65: '⛈️',
  66: '🌧️', 67: '⛈️',
  71: '🌨️', 73: '❄️', 75: '❄️', 77: '🌨️',
  80: '🌦️', 81: '🌧️', 82: '⛈️',
  85: '🌨️', 86: '❄️',
  95: '⛈️', 96: '⛈️', 99: '⛈️',
}

function makeTruckIcon(driverType, stale = false) {
  const baseColor = (driverType || '').toLowerCase().includes('tow') ? '#f59e0b' : '#818cf8'
  const color = stale ? '#475569' : baseColor
  const opacity = stale ? 'opacity:0.4;' : ''
  return L.divIcon({
    className: '',
    iconSize: [26, 22],
    iconAnchor: [13, 22],
    popupAnchor: [0, -22],
    html: `<div style="${opacity}"><svg width="26" height="22" viewBox="0 0 26 22">
      <rect x="1" y="5" width="24" height="13" rx="3" fill="${color}" stroke="#0f172a" stroke-width="1.5"/>
      <rect x="17" y="2" width="9" height="9" rx="2" fill="${color}" stroke="#0f172a" stroke-width="1.5"/>
      <circle cx="7"  cy="21" r="2.5" fill="#0f172a" stroke="${color}" stroke-width="1.5"/>
      <circle cx="19" cy="21" r="2.5" fill="#0f172a" stroke="${color}" stroke-width="1.5"/>
    </svg></div>`,
  })
}

function makeWeatherIcon(station) {
  const emoji = WMO_EMOJI[station.weather_code] ?? '🌡️'
  return L.divIcon({
    className: '',
    iconSize: [72, 46],
    iconAnchor: [36, 46],
    popupAnchor: [0, -46],
    html: `<div style="
      background:#0f172a;border:1px solid #334155;border-radius:8px;
      padding:5px 9px;text-align:center;color:white;
      font-family:-apple-system,sans-serif;white-space:nowrap;
      box-shadow:0 4px 12px rgba(0,0,0,0.6)">
      <div style="font-size:13px;font-weight:700">${emoji} ${station.temp_f}°F</div>
      <div style="font-size:10px;color:#94a3b8;margin-top:1px">${station.name}</div>
    </div>`,
  })
}

// Fly map to a position when SA search result arrives
function FlyTo({ pos }) {
  const map = useMap()
  useEffect(() => {
    if (pos) map.flyTo(pos, 13, { duration: 1.2 })
  }, [pos])
  return null
}

function makeSaSearchIcon(color) {
  return L.divIcon({
    className: '',
    iconSize: [28, 36],
    iconAnchor: [14, 36],
    popupAnchor: [0, -36],
    html: `<svg width="28" height="36" viewBox="0 0 28 36">
      <path d="M14 0 C6.3 0 0 6.3 0 14 C0 24.5 14 36 14 36 C14 36 28 24.5 28 14 C28 6.3 21.7 0 14 0Z"
            fill="${color}" stroke="#0f172a" stroke-width="1.5"/>
      <circle cx="14" cy="14" r="6" fill="white" opacity="0.9"/>
    </svg>`,
  })
}

function makeDriverHistIcon(isAssigned) {
  const color = isAssigned ? '#f59e0b' : '#818cf8'
  return L.divIcon({
    className: '',
    iconSize: [22, 18],
    iconAnchor: [11, 18],
    popupAnchor: [0, -18],
    html: `<div style="opacity:0.85"><svg width="22" height="18" viewBox="0 0 22 18">
      <rect x="1" y="4" width="20" height="11" rx="2.5" fill="${color}" stroke="#0f172a" stroke-width="1.2"/>
      <rect x="14" y="1.5" width="8" height="7" rx="1.5" fill="${color}" stroke="#0f172a" stroke-width="1.2"/>
      <circle cx="6"  cy="17" r="2" fill="#0f172a" stroke="${color}" stroke-width="1.2"/>
      <circle cx="16" cy="17" r="2" fill="#0f172a" stroke="${color}" stroke-width="1.2"/>
    </svg></div>`,
  })
}

const LAYER_DEFS = [
  { key: 'grid',    emoji: '🗺️', label: 'Grid Boundaries', color: 'text-indigo-400' },
  { key: 'drivers', emoji: '🚛', label: 'Drivers (GPS)',    color: 'text-amber-400' },
  { key: 'sas',     emoji: '📍', label: 'Service Calls',   color: 'text-green-400' },
  { key: 'weather', emoji: '🌡️', label: 'Weather',         color: 'text-cyan-400' },
]

const SA_LEGEND = [
  { color: '#3b82f6', label: 'Dispatched / Assigned' },
  { color: '#22c55e', label: 'Completed' },
  { color: '#f97316', label: 'Canceled En Route / Unable' },
  { color: '#6b7280', label: 'Canceled / No-Show' },
]

export default function MapPage() {
  const [mapConfig, setMapCfg] = useState(getMapConfig)
  useEffect(() => {
    const handler = () => setMapCfg(getMapConfig())
    window.addEventListener('mapStyleChanged', handler)
    return () => window.removeEventListener('mapStyleChanged', handler)
  }, [])

  const [layers, setLayers] = useState({ grid: true, drivers: true, sas: true, weather: true })
  const [panelOpen, setPanelOpen] = useState(true)

  const [grids, setGrids]     = useState(null)
  const [drivers, setDrivers] = useState([])
  const [saPoints, setSaPoints] = useState([])
  const [weather, setWeather] = useState([])

  const [loading, setLoading] = useState({ grid: false, drivers: false, sas: false, weather: false })
  const [errors,  setErrors]  = useState({ grid: null,  drivers: null,  sas: null,  weather: null })

  // SA search
  const [searchInput, setSearchInput] = useState('')
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchError, setSearchError] = useState(null)
  const [searchResult, setSearchResult] = useState(null)  // { sa, drivers }
  const searchRef = useRef(null)

  function handleSearch(e) {
    e.preventDefault()
    const num = searchInput.trim()
    if (!num) return
    setSearchLoading(true)
    setSearchError(null)
    setSearchResult(null)
    fetch(`/api/sa/${encodeURIComponent(num)}`)
      .then(r => {
        if (!r.ok) throw new Error(r.status === 404 ? `SA ${num} not found` : `Error ${r.status}`)
        return r.json()
      })
      .then(data => { setSearchResult(data); setSearchLoading(false) })
      .catch(err => { setSearchError(err.message); setSearchLoading(false) })
  }

  function clearSearch() {
    setSearchInput('')
    setSearchResult(null)
    setSearchError(null)
  }

  // Load grid data once
  useEffect(() => {
    if (!layers.grid || grids !== null) return
    setLoading(l => ({ ...l, grid: true }))
    fetchMapGrids()
      .then(d => { setGrids(d); setLoading(l => ({ ...l, grid: false })) })
      .catch(e => { setErrors(l => ({ ...l, grid: e.message })); setLoading(l => ({ ...l, grid: false })) })
  }, [layers.grid])

  // Load drivers
  useEffect(() => {
    if (!layers.drivers || drivers.length > 0) return
    setLoading(l => ({ ...l, drivers: true }))
    fetchMapDrivers()
      .then(d => { setDrivers(d); setLoading(l => ({ ...l, drivers: false })) })
      .catch(e => { setErrors(l => ({ ...l, drivers: e.message })); setLoading(l => ({ ...l, drivers: false })) })
  }, [layers.drivers])

  // Load SAs (last 8h from command center)
  useEffect(() => {
    if (!layers.sas || saPoints.length > 0) return
    setLoading(l => ({ ...l, sas: true }))
    fetchCommandCenter(8)
      .then(d => {
        const pts = d.territories.flatMap(t => t.sa_points || [])
        setSaPoints(pts)
        setLoading(l => ({ ...l, sas: false }))
      })
      .catch(e => { setErrors(l => ({ ...l, sas: e.message })); setLoading(l => ({ ...l, sas: false })) })
  }, [layers.sas])

  // Load weather
  useEffect(() => {
    if (!layers.weather || weather.length > 0) return
    setLoading(l => ({ ...l, weather: true }))
    fetchMapWeather()
      .then(d => { setWeather(d); setLoading(l => ({ ...l, weather: false })) })
      .catch(e => { setErrors(l => ({ ...l, weather: e.message })); setLoading(l => ({ ...l, weather: false })) })
  }, [layers.weather])

  const isDark = mapConfig.dark !== false
  const gridStyle = (feature) => ({
    color: feature.properties.color || (isDark ? '#818cf8' : '#4f46e5'),
    weight: isDark ? 1.5 : 2,
    opacity: isDark ? 0.85 : 0.6,
    fillColor: feature.properties.color || (isDark ? '#818cf8' : '#4f46e5'),
    fillOpacity: isDark ? 0.1 : 0.08,
  })

  const onEachGrid = (feature, layer) => {
    layer.bindTooltip(feature.properties.name, {
      permanent: false,
      direction: 'center',
      className: 'cc-tooltip',
    })
    layer.bindPopup(
      `<strong>${feature.properties.name}</strong><br/>${feature.properties.territory_name}`,
      { className: '' }
    )
  }

  const anyLoading = Object.values(loading).some(Boolean)

  return (
    /* -mx-6 -my-6 cancels the Layout's px-6 py-6 padding */
    <div className="-mx-6 -my-6 relative" style={{ height: 'calc(100vh - 3.5rem)' }}>

      <MapContainer
        center={[42.95, -77.8]}
        zoom={9}
        style={{ width: '100%', height: '100%', borderRadius: 0 }}
        zoomControl={true}
      >
        <TileLayer key={mapConfig.url} url={mapConfig.url}
          className={mapConfig.filter ? 'dynamic-map-tiles' : ''}
          {...(mapConfig.noSubdomains ? { subdomains: [] } : {})} />
        {mapConfig.filter && (
          <style>{`.dynamic-map-tiles { filter: ${mapConfig.filter}; }`}</style>
        )}

        {/* ── Grid layer ── */}
        {layers.grid && grids && grids.features.length > 0 && (
          <GeoJSON
            key={`grids-${isDark ? 'dark' : 'light'}`}
            data={grids}
            style={gridStyle}
            onEachFeature={onEachGrid}
          />
        )}

        {/* ── Drivers layer ── */}
        {layers.drivers && drivers.map(d => (
          <Marker key={d.id} position={[d.lat, d.lon]}
            icon={makeTruckIcon(d.driver_type, d.gps_stale)}
            zIndexOffset={d.gps_stale ? -100 : 0}>
            <Popup>
              <strong>{d.name}</strong>{d.gps_stale && <span style={{color:'#f59e0b',fontSize:10,marginLeft:4}}>STALE GPS</span>}<br />
              {d.driver_type && <>{d.driver_type}<br /></>}
              {d.truck && <>Truck: {d.truck}<br /></>}
              GPS: {d.gps_time}
            </Popup>
          </Marker>
        ))}

        {/* ── SAs layer ── */}
        {layers.sas && saPoints.map((sa, i) => {
          if (!sa.lat || !sa.lon) return null
          const color = SA_COLORS[sa.status] || '#6b7280'
          return (
            <CircleMarker
              key={i}
              center={[sa.lat, sa.lon]}
              radius={5}
              pathOptions={{ color, fillColor: color, fillOpacity: 0.85, weight: 1 }}
            >
              <Tooltip className="cc-tooltip">
                {sa.work_type} — {sa.status} ({sa.time})
              </Tooltip>
            </CircleMarker>
          )
        })}

        {/* ── SA Search result ── */}
        {searchResult?.sa?.lat && searchResult?.sa?.lon && (() => {
          const sa = searchResult.sa
          const color = sa.status === 'Completed' ? '#22c55e' : sa.status === 'Canceled' ? '#6b7280' : '#f59e0b'
          return <>
            <FlyTo pos={[sa.lat, sa.lon]} />
            {/* SA pin */}
            <Marker position={[sa.lat, sa.lon]} icon={makeSaSearchIcon(color)} zIndexOffset={1000}>
              <Popup maxWidth={280}>
                <div style={{fontFamily:'system-ui',fontSize:13}}>
                  <div style={{fontWeight:700,fontSize:14,marginBottom:4}}>SA <SALink number={sa.number} style={{fontSize:14}} /></div>
                  <div><b>Status:</b> {sa.status}</div>
                  <div><b>Work Type:</b> {sa.work_type}</div>
                  <div><b>Territory:</b> {sa.territory}</div>
                  <div><b>Created:</b> {sa.created}</div>
                  {sa.started && <div><b>Arrived:</b> {sa.started}</div>}
                  {sa.response_min != null && <div><b>Response:</b> {sa.response_min} min</div>}
                  {sa.address && <div style={{marginTop:4,color:'#64748b'}}>{sa.address}</div>}
                  {sa.dispatched_lat && <div style={{marginTop:4,fontSize:11,color:'#94a3b8'}}>Dispatch GPS available</div>}
                </div>
              </Popup>
            </Marker>
            {/* Drivers at dispatch time */}
            {(searchResult.drivers || []).map((d, i) => {
              if (!d.lat || !d.lon) return null
              return (
                <Marker key={i} position={[d.lat, d.lon]} icon={makeDriverHistIcon(d.is_assigned)} zIndexOffset={500}>
                  <Popup>
                    <div style={{fontFamily:'system-ui',fontSize:12}}>
                      <div style={{fontWeight:700}}>{d.name}{d.is_assigned && ' ★'}</div>
                      {d.truck && <div>Truck: {d.truck}</div>}
                      <div>GPS: {d.gps_time}</div>
                      {d.distance != null && <div>Distance: {d.distance.toFixed(1)} mi</div>}
                      {d.is_assigned && <div style={{color:'#f59e0b',fontWeight:600}}>Assigned driver</div>}
                    </div>
                  </Popup>
                </Marker>
              )
            })}
          </>
        })()}

        {/* ── Weather layer ── */}
        {layers.weather && weather.map((s, i) => {
          if (s.error || s.temp_f == null) return null
          return (
            <Marker key={i} position={[s.lat, s.lon]} icon={makeWeatherIcon(s)}>
              <Popup>
                <strong>{s.name}</strong><br />
                {s.temp_f}°F — {s.condition}<br />
                Wind: {s.wind} mph
                {s.snow > 0 && <><br />Snow: {s.snow}&quot;</>}
                {s.precip > 0 && s.snow === 0 && <><br />Precip: {s.precip}&quot;</>}
              </Popup>
            </Marker>
          )
        })}
      </MapContainer>

      {/* ── SA Search bar (top-left) ── */}
      <div className="absolute top-4 left-4 z-[1000]" style={{ minWidth: 260 }}>
        <form onSubmit={handleSearch} className="flex gap-1.5">
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
            <input
              ref={searchRef}
              type="text"
              value={searchInput}
              onChange={e => setSearchInput(e.target.value)}
              placeholder="Search SA number…"
              className="w-full pl-8 pr-8 py-2 text-sm bg-slate-900/95 border border-slate-700/70 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-brand-500 backdrop-blur"
            />
            {searchInput && (
              <button type="button" onClick={clearSearch}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white">
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
          <button type="submit" disabled={searchLoading}
            className="px-3 py-2 bg-brand-600 hover:bg-brand-500 text-white text-sm rounded-lg font-medium flex items-center gap-1.5 disabled:opacity-50">
            {searchLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Search className="w-3.5 h-3.5" />}
          </button>
        </form>

        {searchError && (
          <div className="mt-1.5 px-3 py-2 bg-red-900/80 border border-red-700/60 rounded-lg text-xs text-red-300 backdrop-blur">
            {searchError}
          </div>
        )}

        {searchResult?.sa && (
          <div className="mt-1.5 bg-slate-900/95 border border-amber-700/60 rounded-lg px-3 py-2.5 text-xs backdrop-blur">
            <div className="flex items-center justify-between mb-1">
              <span className="font-semibold text-amber-400">SA <SALink number={searchResult.sa.number} style={{color:'#fbbf24'}} /></span>
              <button onClick={clearSearch} className="text-slate-500 hover:text-white"><X className="w-3 h-3" /></button>
            </div>
            <div className="text-slate-300">{searchResult.sa.work_type} · {searchResult.sa.status}</div>
            <div className="text-slate-400">{searchResult.sa.territory} · {searchResult.sa.created}</div>
            {searchResult.sa.response_min != null && (
              <div className="text-slate-400">Response: {searchResult.sa.response_min} min</div>
            )}
            {searchResult.drivers?.length > 0 && (
              <div className="mt-1.5 text-slate-500 text-xs">
                {searchResult.drivers.length} driver{searchResult.drivers.length > 1 ? 's' : ''} shown at dispatch time
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Floating layer control panel ── */}
      <div className="absolute top-4 right-4 z-[1000] select-none" style={{ minWidth: 190 }}>

        {/* Layer toggles card */}
        <div className="bg-slate-900/95 border border-slate-700/70 rounded-xl shadow-2xl overflow-hidden backdrop-blur">
          <button
            onClick={() => setPanelOpen(p => !p)}
            className="w-full flex items-center gap-2.5 px-4 py-3 text-sm font-semibold text-white hover:bg-slate-800/80 transition-colors"
          >
            <Layers className="w-4 h-4 text-brand-400 shrink-0" />
            <span>Layers</span>
            {anyLoading
              ? <Loader2 className="w-3 h-3 ml-auto text-brand-400 animate-spin" />
              : <span className="ml-auto text-slate-500 text-xs">{panelOpen ? '▲' : '▼'}</span>
            }
          </button>

          {panelOpen && (
            <div className="border-t border-slate-700/70 px-4 py-3 space-y-2.5">
              {LAYER_DEFS.map(({ key, emoji, label, color }) => (
                <label key={key} className="flex items-center gap-2.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={layers[key]}
                    onChange={e => setLayers(l => ({ ...l, [key]: e.target.checked }))}
                    className="w-3.5 h-3.5 rounded accent-indigo-500 shrink-0"
                  />
                  <span className="text-base leading-none shrink-0">{emoji}</span>
                  <span className={`text-xs font-medium ${layers[key] ? color : 'text-slate-500'} flex-1`}>
                    {label}
                  </span>
                  {loading[key] && (
                    <Loader2 className="w-3 h-3 text-brand-400 animate-spin shrink-0" />
                  )}
                  {errors[key] && !loading[key] && (
                    <span className="text-xs text-red-400 shrink-0">!</span>
                  )}
                </label>
              ))}
            </div>
          )}
        </div>

        {/* SA status legend — shown when SAs layer is active */}
        {panelOpen && layers.sas && (
          <div className="mt-2 bg-slate-900/95 border border-slate-700/70 rounded-xl px-4 py-3 shadow-2xl backdrop-blur">
            <div className="text-xs font-semibold text-slate-400 mb-2">SA Status</div>
            {SA_LEGEND.map(({ color, label }) => (
              <div key={label} className="flex items-center gap-2 mb-1.5">
                <div className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: color }} />
                <span className="text-xs text-slate-400">{label}</span>
              </div>
            ))}
          </div>
        )}

        {/* Counts summary */}
        {panelOpen && (
          <div className="mt-2 bg-slate-900/95 border border-slate-700/70 rounded-xl px-4 py-3 shadow-2xl backdrop-blur">
            <div className="space-y-1">
              {layers.grid && grids && (
                <div className="flex justify-between text-xs">
                  <span className="text-slate-400">Grids</span>
                  <span className="text-indigo-400 font-mono font-semibold">{grids.features.length}</span>
                </div>
              )}
              {layers.drivers && (() => {
                const active = drivers.filter(d => !d.gps_stale).length
                const stale = drivers.filter(d => d.gps_stale).length
                return (<>
                  <div className="flex justify-between text-xs">
                    <span className="text-slate-400">Drivers (active GPS)</span>
                    <span className="text-amber-400 font-mono font-semibold">{active}</span>
                  </div>
                  {stale > 0 && (
                    <div className="flex justify-between text-xs">
                      <span className="text-slate-500">Drivers (stale GPS)</span>
                      <span className="text-slate-500 font-mono font-semibold">{stale}</span>
                    </div>
                  )}
                </>)
              })()}
              {layers.sas && (
                <div className="flex justify-between text-xs">
                  <span className="text-slate-400">SAs (8h)</span>
                  <span className="text-green-400 font-mono font-semibold">{saPoints.length}</span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
