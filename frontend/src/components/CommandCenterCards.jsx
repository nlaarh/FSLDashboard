import React, { useEffect, useRef } from 'react'
import { useMap } from 'react-leaflet'
import L from 'leaflet'
import { clsx } from 'clsx'
import {
  ChevronRight, ChevronUp, ChevronDown, Shield, Zap, Clock, MapPin,
  Crosshair, Loader2, CheckCircle2, TrendingUp, Search, X,
} from 'lucide-react'
import SALink from './SALink'
import { SuggestionCard } from './DispatchInsights'
import { fmtPhone, fmtWait } from './CommandCenterUtils'


export const STATUS_COLORS = {
  good:     { fill: '#22c55e', border: '#16a34a', bg: 'bg-emerald-500' },
  behind:   { fill: '#f59e0b', border: '#d97706', bg: 'bg-amber-500' },
  critical: { fill: '#ef4444', border: '#dc2626', bg: 'bg-red-500' },
}
export const SA_COLORS = { Dispatched: '#3b82f6', Assigned: '#8b5cf6', Completed: '#22c55e', 'No-Show': '#f97316' }

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

export const WINDOWS = [
  { label: '2h', hours: 2 }, { label: '4h', hours: 4 }, { label: '8h', hours: 8 },
  { label: '12h', hours: 12 }, { label: '24h', hours: 24 },
  { label: '48h', hours: 48 }, { label: '7d',  hours: 168 },
]


const WMO_EMOJI = {
  0:'☀️',1:'🌤️',2:'⛅',3:'☁️',45:'🌫️',48:'🌫️',
  51:'🌦️',53:'🌦️',55:'🌧️',61:'🌧️',63:'🌧️',65:'⛈️',
  66:'🌧️',67:'⛈️',71:'🌨️',73:'❄️',75:'❄️',77:'🌨️',
  80:'🌦️',81:'🌧️',82:'⛈️',85:'🌨️',86:'❄️',
  95:'⛈️',96:'⛈️',99:'⛈️',
}

export function makeDriverCarIcon(driverType, isIdle) {
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

export function makeWeatherMarkerIcon(s) {
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

export function makeGarageIcon(primaryZones, secondaryZones, isTowbook) {
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

export function gridFeatureStyle(isDark) {
  return (feature) => ({
    color: isDark ? '#818cf8' : '#4f46e5',
    weight: isDark ? 1 : 1.5,
    opacity: isDark ? 0.4 : 0.5,
    fillOpacity: isDark ? 0.04 : 0.06,
    fillColor: isDark ? '#818cf8' : '#4f46e5',
    dashArray: '6,4',
  })
}
export function onEachGridFeature(feature, layer) {
  if (feature.properties?.Name) {
    layer.bindTooltip(feature.properties.Name, { sticky: true, className: 'cc-tooltip', opacity: 0.95 })
  }
}

// Driver truck icon for SA lookup
export function driverIcon(dist, isClosest) {
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

export const customerIcon = L.divIcon({
  className: '',
  iconSize: [20, 28], iconAnchor: [10, 28], popupAnchor: [0, -28],
  html: `<div style="text-align:center">
    <svg width="20" height="28" viewBox="0 0 20 28">
      <path d="M10 0C4.5 0 0 4.5 0 10c0 7 10 18 10 18s10-11 10-18C20 4.5 15.5 0 10 0z" fill="#ef4444" stroke="#fff" stroke-width="1.5"/>
      <circle cx="10" cy="10" r="4" fill="#fff"/>
    </svg>
  </div>`,
})


export function AutoBounds({ territories }) {
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

export function FlyTo({ center }) {
  const map = useMap()
  useEffect(() => { if (center) map.flyTo(center, 11, { duration: 1 }) }, [center])
  return null
}

export function TerritoryCard({ t, onFocus, onNavigate }) {
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

export function TerritoryPopup({ t }) {
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

export function OpsCockpitPanel({
  data, panelOpen, setPanelOpen, panelTab, setPanelTab,
  atRisk, fleet, demand, suggestions, briefLoading, lastRefresh, countdown,
  openCalls, zones, saQuery, setSaQuery, saResult, saLoading, saError,
  searchSA, clearSA, setFocusCenter,
}) {
  if (!data) return null
  return (
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
                                    <SALink number={c.number} className="text-[10px] font-mono" />
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
                            <div className="text-sm font-bold text-white mb-1">
                              {saResult.sa.customer || 'Member'} — SA# <SALink number={saResult.sa.number} />
                            </div>
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
                                    <div className="mt-1 text-[10px] text-amber-400">Busy: SA# <SALink number={d.next_job.number} style={{ fontSize: 10 }} /></div>
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
  )
}
