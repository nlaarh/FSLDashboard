import React from 'react'
import ReactDOM from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { MapContainer, TileLayer, CircleMarker, Popup, Tooltip, Marker, Polyline, useMap, GeoJSON } from 'react-leaflet'
import L from 'leaflet'
import { clsx } from 'clsx'
import { lookupSA } from '../api'
import SALink from '../components/SALink'
import {
  Loader2, RefreshCw, Radio, CheckCircle2, AlertTriangle,
  ChevronRight, Search, MapPin, Clock, FileText,
  ChevronDown, ChevronUp, Crosshair, X, Truck, Layers,
  Zap, Shield, Navigation, Users, TrendingUp, AlertCircle, ArrowRight,
  Maximize2, Minimize2, GripVertical, BarChart3, XCircle, ThumbsDown, Activity, Eye, Star, MessageSquare, ArrowLeft
} from 'lucide-react'
import { StatChip, Div, LegendDot, LegendSmall, fmtPhone, fmtWait } from '../components/CommandCenterUtils'
import DispatchInsightsFullView, { SuggestionCard } from '../components/DispatchInsights'
import SAWatchlist from '../components/SAWatchlist'
import useCommandCenterData from '../hooks/useCommandCenterData'
import {
  STATUS_COLORS, SA_COLORS, WINDOWS, customerIcon,
  makeDriverCarIcon, makeWeatherMarkerIcon, makeGarageIcon,
  gridFeatureStyle, onEachGridFeature, driverIcon,
  AutoBounds, FlyTo, TerritoryCard, TerritoryPopup, OpsCockpitPanel,
} from '../components/CommandCenterCards'

export default function CommandCenter() {
  const navigate = useNavigate()
  const {
    mapConfig, data, loading, briefLoading, error, hours, setHours,
    lastRefresh, countdown, load,
    panelTab, setPanelTab, viewMode, setViewMode, panelOpen, setPanelOpen,
    focusCenter, setFocusCenter,
    saQuery, setSaQuery, saResult, setSaResult, saLoading, setSaLoading,
    saError, setSaError, searchSA, clearSA,
    layers, setLayers, grids, allDrivers, mapWeather, allGarages, layerLoading,
    schedulerData, gpsHealth,
    search, setSearch, statusFilter, setStatusFilter,
    showSADots, setShowSADots, saStatusFilter, setSaStatusFilter,
    territories, summary, fleet, demand, suggestions, openCalls, atRisk, zones,
    filtered, idleDriverIds,
  } = useCommandCenterData()

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
        <button onClick={() => setViewMode('watchlist')}
          className={clsx('flex items-center gap-2 px-4 py-2.5 text-xs font-bold uppercase tracking-wide transition-all border-b-2',
            viewMode === 'watchlist'
              ? 'border-amber-500 text-amber-300 bg-amber-600/10'
              : 'border-transparent text-slate-500 hover:text-white hover:bg-slate-800/40')}>
          <Star className="w-4 h-4" /> SA Watchlist
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
            <DispatchInsightsFullView data={schedulerData} gpsHealth={gpsHealth} ccData={data} onViewOnMap={(saNum) => {
              setSaQuery(saNum)
              setSaLoading(true); setSaError(null); setSaResult(null)
              lookupSA(saNum)
                .then(r => { setSaResult(r); if (r.sa.lat && r.sa.lon) setFocusCenter([r.sa.lat, r.sa.lon]) })
                .catch(e => setSaError(e.response?.data?.detail || e.message))
                .finally(() => setSaLoading(false))
              setViewMode('map')
            }} />
          ) : (
            <div className="w-full h-full flex items-center justify-center bg-slate-950">
              <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
            </div>
          )}
        </div>
      )}

      {/* ── SA WATCHLIST ── */}
      {viewMode === 'watchlist' && (
        <div className="flex-1 overflow-hidden">
          <SAWatchlist />
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
            const assignedDriver = saResult.drivers.find(d => d.is_assigned && d.lat && d.lon)
            const closestDriver = assignedDriver || saResult.drivers.find(d => d.lat && d.lon)
            return (
              <>
                <Marker position={[saResult.sa.lat, saResult.sa.lon]} icon={customerIcon}>
                  <Tooltip direction="top" offset={[0, -30]} opacity={0.95} className="cc-tooltip">
                    <div style={{ fontSize: 12, color: '#e2e8f0', minWidth: 220, padding: 2 }}>
                      <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 3 }}>{saResult.sa.customer || 'Member'}</div>
                      <div style={{ color: '#94a3b8' }}>
                        {saResult.sa.address}{saResult.sa.zip && ` (${saResult.sa.zip})`}<br />
                        SA# <SALink number={saResult.sa.number} style={{ color: '#e2e8f0', fontWeight: 600, fontSize: 12 }} />
                        {' — '}<span style={{ color: '#e2e8f0' }}>{saResult.sa.work_type}</span><br />
                        Status: <span style={{ color: '#e2e8f0', fontWeight: 600 }}>{saResult.sa.status}</span>
                        {saResult.sa.response_min && (
                          <><br />Response: <span style={{ color: saResult.sa.response_min <= 45 ? '#22c55e' : '#ef4444', fontWeight: 700 }}>{saResult.sa.response_min} min</span></>
                        )}
                      </div>
                      {assignedDriver && (
                        <div style={{ marginTop: 5, padding: '3px 6px', background: 'rgba(245,158,11,0.1)', borderRadius: 5, border: '1px solid rgba(245,158,11,0.25)' }}>
                          <span style={{ color: '#f59e0b', fontWeight: 700, fontSize: 11 }}>Assigned: </span>
                          <span style={{ color: '#f59e0b', fontWeight: 600 }}>{assignedDriver.name}</span>
                          <span style={{ color: '#e2e8f0', fontWeight: 700 }}> — {assignedDriver.distance ?? '?'} mi</span>
                        </div>
                      )}
                    </div>
                  </Tooltip>
                </Marker>
                {assignedDriver && (
                  <>
                    <Polyline positions={[[assignedDriver.lat, assignedDriver.lon], [saResult.sa.lat, saResult.sa.lon]]}
                      pathOptions={{ color: '#f59e0b', weight: 3, opacity: 0.8, dashArray: '8,6' }} />
                    <CircleMarker center={[assignedDriver.lat, assignedDriver.lon]} radius={20}
                      pathOptions={{ color: '#f59e0b', weight: 2, fillOpacity: 0.08, opacity: 0.4 }} />
                  </>
                )}
              </>
            )
          })()}

          {saResult && saResult.drivers.filter(d => d.lat && d.lon).map((d, i) => (
            <React.Fragment key={d.id}>
              <Marker position={[d.lat, d.lon]} icon={driverIcon(d.distance, d.is_assigned)}>
                <Tooltip direction="top" offset={[0, -36]} opacity={0.95} className="cc-tooltip">
                  <div style={{ fontSize: 12, color: '#e2e8f0', minWidth: 210, padding: 2 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
                      <strong style={{ fontSize: 14, color: d.is_assigned ? '#f59e0b' : '#e2e8f0' }}>{d.name}</strong>
                      {d.is_assigned && <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: 'rgba(245,158,11,0.15)', color: '#f59e0b', border: '1px solid rgba(245,158,11,0.3)' }}>ASSIGNED</span>}
                    </div>
                    <div style={{ color: '#94a3b8' }}>
                      Distance: <span style={{ color: '#e2e8f0', fontWeight: 700 }}>{d.distance ?? '?'} mi</span><br />
                      GPS at: {d.gps_time}{d.territory_type ? ` — ${d.territory_type}` : ''}
                    </div>
                    {!d.is_assigned && (
                      <div style={{ marginTop: 3, color: '#94a3b8', fontSize: 11 }}>Available at dispatch time</div>
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
        <OpsCockpitPanel
          data={data} panelOpen={panelOpen} setPanelOpen={setPanelOpen}
          panelTab={panelTab} setPanelTab={setPanelTab}
          atRisk={atRisk} fleet={fleet} demand={demand}
          suggestions={suggestions} briefLoading={briefLoading}
          lastRefresh={lastRefresh} countdown={countdown}
          openCalls={openCalls} zones={zones}
          saQuery={saQuery} setSaQuery={setSaQuery}
          saResult={saResult} saLoading={saLoading} saError={saError}
          searchSA={searchSA} clearSA={clearSA}
          setFocusCenter={setFocusCenter}
        />

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
                { key: 'drivers', emoji: '🚛', label: 'On-Shift Drivers', color: 'text-amber-400' },
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
