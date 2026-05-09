/**
 * DispatchAssistPanel.jsx
 *
 * Normal mode: map + driver list for SA's assigned territory.
 * 000 mode: combined map showing ranked Towbook garages (table) + nearby FSL drivers.
 */

import { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { clsx } from 'clsx'
import { MapContainer, TileLayer, Marker, Popup, Tooltip, useMap } from 'react-leaflet'
import L from 'leaflet'
import {
  X, Truck, MapPin, Phone, Clock, Navigation, Loader2,
  CheckCircle2, AlertCircle, User, Wrench, Building2, Car, AlertTriangle,
} from 'lucide-react'
import { fetchDispatchAssist } from '../api'

// ── Map Icons ──────────────────────────────────────────────────────────────

function customerMarkerIcon(label, memberName, vehicle, plate) {
  const firstName = memberName ? memberName.split(' ')[0] : ''
  const modelShort = vehicle ? vehicle.split(' ').slice(-1)[0] : ''
  const vehicleLine = [modelShort, plate].filter(Boolean).join(' · ')
  const extraCount = (firstName ? 1 : 0) + (vehicleLine ? 1 : 0)
  return L.divIcon({
    className: '',
    html: `<div style="display:flex;flex-direction:column;align-items:center;">
      <div style="width:32px;height:32px;background:#ef4444;border-radius:50%;border:3px solid #fff;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 8px rgba(0,0,0,0.5);">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"><path d="M7 17m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M17 17m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M5 17H3v-6l2-5h9l4 5h1a2 2 0 0 1 2 2v4h-2"/><path d="M9 17h6"/><path d="M14 7l4 4"/></svg>
      </div>
      <div style="margin-top:2px;background:rgba(0,0,0,0.85);color:#fff;font-size:9px;font-weight:bold;padding:1px 5px;border-radius:3px;white-space:nowrap;">${label}</div>
      ${firstName ? `<div style="margin-top:1px;background:rgba(239,68,68,0.85);color:#fff;font-size:8px;font-weight:600;padding:0px 4px;border-radius:2px;white-space:nowrap;">${firstName}</div>` : ''}
      ${vehicleLine ? `<div style="margin-top:1px;background:rgba(0,0,0,0.75);color:#7dd3fc;font-size:7px;font-weight:600;padding:0px 4px;border-radius:2px;white-space:nowrap;">${vehicleLine}</div>` : ''}
    </div>`,
    iconSize: [48, 40 + extraCount * 10],
    iconAnchor: [24, 16],
  })
}

function driverMarkerIcon(tier, isAvailable, name) {
  const colors = {
    tier1: '#22c55e', tier2: '#22c55e',
    tier3: '#eab308', tier4: '#eab308',
    tier5: '#f97316', tier6: '#f97316',
    unknown: '#6b7280',
  }
  const bg = !isAvailable ? '#64748b' : (colors[tier] || '#6b7280')
  const border = isAvailable ? '#fff' : '#94a3b8'
  return L.divIcon({
    className: '',
    html: `<div style="display:flex;flex-direction:column;align-items:center;">
      <div style="width:26px;height:26px;background:${bg};border-radius:50%;border:2px solid ${border};display:flex;align-items:center;justify-content:center;">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"><path d="M7 17m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M17 17m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M5 17H3V6a1 1 0 0 1 1-1h9v12M9 17h6"/><path d="M13 6h5l3 5v6h-2"/></svg>
      </div>
      <div style="margin-top:1px;background:rgba(0,0,0,0.75);color:${bg};font-size:8px;font-weight:bold;padding:0px 3px;border-radius:2px;white-space:nowrap;max-width:80px;overflow:hidden;text-overflow:ellipsis;">${name || ''}</div>
    </div>`,
    iconSize: [26, 36],
    iconAnchor: [13, 18],
  })
}

function garageMarkerIcon(priority, name) {
  const bg = priority <= 3 ? '#3b82f6' : priority <= 6 ? '#8b5cf6' : '#6b7280'
  const code = (name || '').split(' - ')[0].slice(0, 5)
  return L.divIcon({
    className: '',
    html: `<div style="display:flex;flex-direction:column;align-items:center;">
      <div style="width:28px;height:28px;background:${bg};border-radius:4px;border:2px solid #fff;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 6px rgba(0,0,0,0.4);">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9,22 9,12 15,12 15,22"/></svg>
      </div>
      <div style="margin-top:1px;background:rgba(0,0,0,0.75);color:${bg};font-size:7px;font-weight:bold;padding:0px 3px;border-radius:2px;white-space:nowrap;max-width:72px;overflow:hidden;text-overflow:ellipsis;">P${priority} ${code}</div>
    </div>`,
    iconSize: [28, 38],
    iconAnchor: [14, 19],
  })
}

// ── Tooltip CSS (dark theme override for Leaflet tooltips) ────────────────

const TOOLTIP_CSS = `
  .fsl-tooltip {
    background: #0f172a !important;
    border: 1px solid #334155 !important;
    border-radius: 8px !important;
    padding: 0 !important;
    box-shadow: 0 8px 24px rgba(0,0,0,0.75) !important;
  }
  .fsl-tooltip::before { display: none !important; }
`

// ── Driver Hover Tooltip Content ───────────────────────────────────────────

function DriverTooltip({ d }) {
  const dotColor = d.is_available ? '#22c55e' : '#64748b'
  const statusLabel = d.is_available
    ? 'Available'
    : d.current_status === 'InProgress' ? 'On Job' : (d.current_status || 'Busy')
  const busyReason = !d.is_available && d.current_work_type ? ` — ${d.current_work_type}` : ''

  return (
    <div style={{ padding: '10px 12px', minWidth: '195px', maxWidth: '265px', width: '265px', lineHeight: '1.45', boxSizing: 'border-box', overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '3px' }}>
        <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: dotColor, display: 'inline-block', flexShrink: 0 }} />
        <span style={{ fontWeight: '700', fontSize: '12px', color: '#f1f5f9' }}>{d.name}</span>
        {d.tech_id && <span style={{ fontSize: '9px', color: '#475569', fontFamily: 'monospace' }}>#{d.tech_id}</span>}
      </div>
      {d.driver_type && (
        <div style={{ fontSize: '10px', color: '#64748b', marginBottom: '6px', marginLeft: '14px' }}>{d.driver_type}</div>
      )}
      <div style={{ padding: '3px 8px', marginBottom: '6px', borderRadius: '4px', background: d.is_available ? 'rgba(34,197,94,0.12)' : 'rgba(100,116,139,0.18)' }}>
        <span style={{ fontSize: '11px', color: d.is_available ? '#22c55e' : '#94a3b8', fontWeight: '600' }}>
          {d.is_available ? '● Available' : `● ${statusLabel}${busyReason}`}
        </span>
      </div>
      {d.distance_miles != null && (
        <div style={{ fontSize: '11px', color: '#94a3b8', marginBottom: '5px' }}>
          <span style={{ color: '#64748b' }}>↔ </span>
          <span style={{ color: '#e2e8f0', fontWeight: '600' }}>{d.distance_miles} mi</span>
          <span style={{ color: '#64748b' }}> · ~{Math.round(d.travel_min || 0)} min to customer</span>
        </div>
      )}
      {d.skills?.length > 0 && (
        <div style={{ fontSize: '10px', color: '#94a3b8', paddingTop: '5px', borderTop: '1px solid #1e293b', marginBottom: '4px', wordBreak: 'break-word', overflowWrap: 'break-word', whiteSpace: 'normal' }}>
          <span style={{ color: '#64748b' }}>Skills: </span>{d.skills.join(', ')}
        </div>
      )}
      {d.phone && (
        <div style={{ fontSize: '11px', color: '#34d399', paddingTop: '5px', borderTop: '1px solid #1e293b' }}>
          📞 {d.phone}
        </div>
      )}
    </div>
  )
}

// ── Customer Hover Tooltip Content ────────────────────────────────────────

const SA_TIMELINE = [
  { key: 'new',         label: 'New'    },
  { key: 'accepted',    label: 'Acpt'   },
  { key: 'dispatched',  label: 'Disp'   },
  { key: 'en route',    label: 'En Rt'  },
  { key: 'on location', label: 'On Loc' },
  { key: 'complete',    label: 'Done'   },
]

function CustomerTooltip({ sa }) {
  const statusLower = sa.status?.toLowerCase() || ''
  const currentIdx = SA_TIMELINE.findIndex(s => statusLower.includes(s.key))

  return (
    <div style={{ padding: '10px 12px', width: '265px', boxSizing: 'border-box', lineHeight: '1.45', overflow: 'hidden' }}>
      {/* SA number + call type */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '5px' }}>
        <span style={{ fontWeight: '700', fontSize: '12px', color: '#f1f5f9' }}>{sa.number}</span>
        {sa.work_type && (
          <span style={{ fontSize: '10px', background: 'rgba(59,130,246,0.2)', color: '#93c5fd', padding: '1px 6px', borderRadius: '3px', fontWeight: '600' }}>
            {sa.work_type}
          </span>
        )}
      </div>
      {/* Member + phone */}
      {sa.member_name && (
        <div style={{ fontSize: '11px', color: '#cbd5e1', marginBottom: '4px', wordBreak: 'break-word' }}>
          👤 {sa.member_name}
          {sa.phone && <span style={{ color: '#34d399', marginLeft: '8px' }}>📞 {sa.phone}</span>}
        </div>
      )}
      {/* Vehicle: model · color + plate badge */}
      {(sa.vehicle || sa.vehicle_plate || sa.vehicle_color) && (
        <div style={{ fontSize: '11px', color: '#7dd3fc', marginBottom: '6px', wordBreak: 'break-word' }}>
          🚗 {[sa.vehicle, sa.vehicle_color].filter(Boolean).join(' · ')}
          {sa.vehicle_plate && (
            <span style={{ marginLeft: '6px', background: 'rgba(14,165,233,0.15)', color: '#7dd3fc', padding: '1px 5px', borderRadius: '3px', fontFamily: 'monospace', fontWeight: '700', fontSize: '10px' }}>
              {sa.vehicle_plate}
            </span>
          )}
        </div>
      )}
      {/* Timeline strip */}
      <div style={{ paddingTop: '6px', borderTop: '1px solid #1e293b' }}>
        <div style={{ fontSize: '9px', color: '#64748b', marginBottom: '3px', fontWeight: '600', letterSpacing: '0.05em' }}>TIMELINE</div>
        <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'nowrap', overflow: 'hidden' }}>
          {SA_TIMELINE.flatMap((step, i) => {
            const isActive = i === currentIdx
            const isPast = currentIdx >= 0 && i < currentIdx
            const els = [
              <span key={step.key} style={{
                fontSize: '8px',
                color: isActive ? '#22c55e' : isPast ? '#64748b' : '#334155',
                fontWeight: isActive ? '700' : '400',
                background: isActive ? 'rgba(34,197,94,0.12)' : 'transparent',
                padding: '1px 3px', borderRadius: '2px', whiteSpace: 'nowrap',
              }}>
                {step.label}
              </span>,
            ]
            if (i < SA_TIMELINE.length - 1) {
              els.push(<span key={`s${i}`} style={{ color: '#334155', fontSize: '8px', margin: '0 1px', flexShrink: 0 }}>›</span>)
            }
            return els
          })}
        </div>
      </div>
    </div>
  )
}

// ── Fit map to all visible points (runs once on mount) ─────────────────────

function FitBounds({ points }) {
  const map = useMap()
  const [fitted, setFitted] = useState(false)
  useEffect(() => {
    if (fitted || points.length === 0) return
    if (points.length === 1) {
      map.setView(points[0], 13)
    } else {
      map.fitBounds(L.latLngBounds(points), { padding: [40, 40], maxZoom: 13 })
    }
    setFitted(true)
  }, [points, map, fitted])
  return null
}

// ── Tier colors ────────────────────────────────────────────────────────────

const TIER_STYLES = {
  tier1: 'text-emerald-400', tier2: 'text-emerald-400',
  tier3: 'text-yellow-400',  tier4: 'text-yellow-400',
  tier5: 'text-orange-400',  tier6: 'text-orange-400',
  unknown: 'text-slate-500',
}

// ── Main Component ─────────────────────────────────────────────────────────

export default function DispatchAssistPanel({ saId, hints, alertData, onClose }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const sa = alertData ? {
    number:        alertData.sa_number || '',
    status:        alertData.status || '',
    work_type:     alertData.work_type || '',
    latitude:      alertData.latitude,
    longitude:     alertData.longitude,
    city:          alertData.city || '',
    address:       alertData.address || '',
    phone:         alertData.phone || '',
    member_name:   alertData.member_name || '',
    wo_number:     alertData.wo_number || '',
    vehicle:       alertData.vehicle || '',
    vehicle_plate: alertData.vehicle_plate || '',
    vehicle_color: alertData.vehicle_color || '',
    facility_name: alertData.facility_name || '',
    facility_phone: alertData.facility_phone || '',
  } : null

  useEffect(() => {
    if (!saId) return
    setLoading(true)
    setError(null)
    fetchDispatchAssist(saId, hints || {})
      .then(setData)
      .catch(e => setError(e?.response?.data?.detail || 'Failed to load'))
      .finally(() => setLoading(false))
  }, [saId])

  if (!saId) return null

  const is000 = data?.mode === 'geo_search'

  return createPortal(
    <div className="fixed inset-0 z-[9998] flex">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative ml-auto w-full max-w-3xl h-full max-h-screen bg-slate-900 border-l border-slate-700 shadow-2xl flex flex-col overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-700/50 bg-slate-800/50">
          <div className="flex items-center gap-2">
            <Navigation className="w-4 h-4 text-blue-400" />
            <span className="font-bold text-sm text-white">Dispatch Assist</span>
            {sa && (
              <span className="text-[10px] text-slate-400 font-mono ml-2">
                {sa.number}
                {is000
                  ? ' · ⚠ 000 Zone'
                  : ' · 🚛 On-Platform'}
              </span>
            )}
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-slate-700 text-slate-400 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 min-h-0 overflow-y-auto">
          {loading && (
            <div className="flex items-center justify-center h-48">
              <Loader2 className="w-6 h-6 text-blue-400 animate-spin" />
              <span className="ml-2 text-sm text-slate-400">Loading nearby resources…</span>
            </div>
          )}
          {error && (
            <div className="p-6 text-center">
              <AlertCircle className="w-6 h-6 text-red-400 mx-auto mb-2" />
              <p className="text-sm text-red-400">{error}</p>
            </div>
          )}
          {data && !loading && is000 && (
            <ZeroModeView data={{ ...data, sa }} />
          )}
          {data && !loading && !is000 && (
            <OnPlatformView data={{ ...data, sa }} />
          )}
        </div>
      </div>
    </div>,
    document.body
  )
}

// ── SA Info Bar ────────────────────────────────────────────────────────────

function SAInfoBar({ sa, extra }) {
  return (
    <div className="px-4 py-3 bg-slate-800/80 border-b border-slate-700/30 text-[11px] text-slate-300 space-y-1.5">
      <div className="flex items-center gap-3 flex-wrap">
        <span className="font-bold text-white text-sm">{sa.number}</span>
        {sa.wo_number && <span className="text-slate-400 font-mono text-[10px]">WO {sa.wo_number}</span>}
        <span className="text-slate-500">·</span>
        <span><Wrench className="w-3 h-3 inline text-blue-400 mr-1" />{sa.work_type || '—'}</span>
        <span className={clsx('font-bold',
          sa.status === 'Dispatched' ? 'text-blue-400' :
          sa.status === 'En Route'   ? 'text-yellow-400' : 'text-slate-400')}>
          {sa.status}
        </span>
        {extra}
      </div>
      <div className="flex items-center gap-1">
        <MapPin className="w-3 h-3 text-red-400 shrink-0" />
        <span className="text-white font-medium">{sa.address || sa.city || '—'}</span>
      </div>
      <div className="flex items-center gap-4 flex-wrap">
        {sa.member_name && (
          <div className="flex items-center gap-1">
            <User className="w-3 h-3 text-slate-500 shrink-0" />
            <span className="text-slate-200 font-medium">{sa.member_name}</span>
          </div>
        )}
        {sa.phone && (
          <div className="flex items-center gap-1">
            <Phone className="w-3 h-3 text-emerald-400 shrink-0" />
            <a href={`tel:${sa.phone}`} className="text-emerald-400 hover:text-emerald-300 font-mono font-bold">{sa.phone}</a>
          </div>
        )}
      </div>
      {(sa.vehicle || sa.vehicle_plate) && (
        <div className="flex items-center gap-1">
          <Car className="w-3 h-3 text-sky-400 shrink-0" />
          <span className="text-sky-300 font-medium">{sa.vehicle}</span>
          {sa.vehicle_plate && <span className="ml-2 text-[10px] bg-sky-500/15 text-sky-300 px-1.5 py-0.5 rounded font-mono font-bold">{sa.vehicle_plate}</span>}
        </div>
      )}
      {sa.facility_name && (
        <div className="flex items-center gap-1 pt-1 border-t border-slate-700/30">
          <Building2 className="w-3 h-3 text-amber-400 shrink-0" />
          <span className="text-amber-300 font-semibold">Assigned: {sa.facility_name}</span>
          {sa.facility_phone && (
            <a href={`tel:${sa.facility_phone}`} className="ml-2 text-amber-300 hover:text-amber-200 font-mono text-[10px]">
              <Phone className="w-2.5 h-2.5 inline mr-0.5" />{sa.facility_phone}
            </a>
          )}
        </div>
      )}
    </div>
  )
}

// ── Normal Mode ────────────────────────────────────────────────────────────

function OnPlatformView({ data }) {
  const { sa, drivers = [], total_eligible } = data
  const saPos = sa?.latitude && sa?.longitude ? [sa.latitude, sa.longitude] : null

  const mapPoints = []
  if (saPos) mapPoints.push(saPos)
  drivers.forEach(d => { if (d.latitude && d.longitude) mapPoints.push([d.latitude, d.longitude]) })

  const availableCount = drivers.filter(d => d.is_available).length
  const busyCount = drivers.filter(d => !d.is_available).length

  return (
    <div className="flex flex-col h-full">
      <SAInfoBar sa={sa} />
      <div className="px-4 py-2 flex items-center gap-4 text-[11px] border-b border-slate-700/30">
        <span className="text-emerald-400 font-bold">{availableCount} available</span>
        <span className="text-yellow-400">{busyCount} busy</span>
        <span className="text-slate-500">{total_eligible} total in range</span>
      </div>
      {saPos && mapPoints.length > 0 && (
        <div className="h-80 min-h-[320px] border-b border-slate-700/30">
          <style>{TOOLTIP_CSS}</style>
          <MapContainer center={saPos} zoom={11} className="h-full w-full" scrollWheelZoom style={{ background: '#1e293b' }}>
            <TileLayer url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" attribution='&copy; OpenStreetMap' />
            <FitBounds points={mapPoints} />
            <Marker position={saPos} icon={customerMarkerIcon(sa.number, sa.member_name, sa.vehicle, sa.vehicle_plate)}>
              <Tooltip direction="top" offset={[0, -32]} opacity={1} className="fsl-tooltip">
                <CustomerTooltip sa={sa} />
              </Tooltip>
            </Marker>
            {drivers.map(d => d.latitude && d.longitude && (
              <Marker key={d.resource_id} position={[d.latitude, d.longitude]}
                icon={driverMarkerIcon(d.travel_tier, d.is_available, d.name)}>
                <Tooltip direction="top" offset={[0, -22]} opacity={1} className="fsl-tooltip">
                  <DriverTooltip d={d} />
                </Tooltip>
              </Marker>
            ))}
          </MapContainer>
        </div>
      )}
      <div className="flex-1 overflow-y-auto px-2 py-2">
        {drivers.length === 0
          ? <p className="text-center text-slate-500 py-6 text-sm">No drivers within 60 min range</p>
          : drivers.map(d => <DriverCard key={d.resource_id} driver={d} />)
        }
      </div>
    </div>
  )
}

// ── 000 Mode — Combined Garages + Drivers ─────────────────────────────────

function ZeroModeView({ data }) {
  const { sa, drivers = [], garages = [], total_eligible } = data
  const saPos = sa?.latitude && sa?.longitude ? [sa.latitude, sa.longitude] : null

  const mapPoints = []
  if (saPos) mapPoints.push(saPos)
  garages.forEach(g => { if (g.latitude && g.longitude) mapPoints.push([g.latitude, g.longitude]) })
  drivers.forEach(d => { if (d.latitude && d.longitude) mapPoints.push([d.latitude, d.longitude]) })

  const availableDrivers = drivers.filter(d => d.is_available)

  return (
    <div className="flex flex-col h-full">
      <SAInfoBar sa={sa} />

      {/* 000 banner */}
      <div className="px-4 py-2.5 bg-amber-900/30 border-b border-amber-700/40 flex items-start gap-2">
        <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
        <div className="text-[11px] text-amber-300">
          <span className="font-bold">All cascade options exhausted.</span>
          {' '}Showing {garages.length} Towbook garages from the cascade order and {availableDrivers.length} available FSL driver{availableDrivers.length !== 1 ? 's' : ''} within 60 min.
        </div>
      </div>

      {/* Map */}
      {saPos && mapPoints.length > 0 && (
        <div className="h-80 min-h-[320px] border-b border-slate-700/30">
          <style>{TOOLTIP_CSS}</style>
          <MapContainer center={saPos} zoom={10} className="h-full w-full" scrollWheelZoom style={{ background: '#1e293b' }}>
            <TileLayer url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" attribution='&copy; OpenStreetMap' />
            <FitBounds points={mapPoints} />

            {/* Customer */}
            <Marker position={saPos} icon={customerMarkerIcon(sa.number, sa.member_name, sa.vehicle, sa.vehicle_plate)}>
              <Tooltip direction="top" offset={[0, -32]} opacity={1} className="fsl-tooltip">
                <CustomerTooltip sa={sa} />
              </Tooltip>
            </Marker>

            {/* Towbook garages — building icons, colored by priority */}
            {garages.map(g => g.latitude && g.longitude && (
              <Marker key={g.territory_id} position={[g.latitude, g.longitude]}
                icon={garageMarkerIcon(g.priority, g.name)}>
                <Popup>
                  <b>{g.name}</b><br />
                  Priority: P{g.priority}<br />
                  {g.distance_miles != null && <>{g.distance_miles} mi · ~{Math.round(g.travel_min || 0)} min<br /></>}
                  {g.phone_display ? <>📞 {g.phone_display}</> : 'No phone on file'}
                </Popup>
              </Marker>
            ))}

            {/* FSL drivers — truck icons */}
            {drivers.map(d => d.latitude && d.longitude && (
              <Marker key={d.resource_id} position={[d.latitude, d.longitude]}
                icon={driverMarkerIcon(d.travel_tier, d.is_available, d.name)}>
                <Tooltip direction="top" offset={[0, -22]} opacity={1} className="fsl-tooltip">
                  <DriverTooltip d={d} />
                </Tooltip>
              </Marker>
            ))}
          </MapContainer>
        </div>
      )}

      <div className="flex-1 overflow-y-auto">
        {/* Towbook Garages Table */}
        <div className="px-4 pt-3 pb-1">
          <div className="flex items-center gap-2 mb-2">
            <Building2 className="w-3.5 h-3.5 text-blue-400" />
            <span className="text-xs font-bold text-white">Towbook Garages — Cascade Order</span>
            <span className="text-[10px] text-slate-500 ml-1">{garages.length} garages · call directly to override decline</span>
          </div>
          {garages.length === 0
            ? <p className="text-xs text-slate-500 py-2">No cascade garages found for this grid zone.</p>
            : (
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="text-slate-500 border-b border-slate-700/50">
                    <th className="text-left pb-1 pr-2 font-medium w-8">Rank</th>
                    <th className="text-left pb-1 pr-2 font-medium">Garage</th>
                    <th className="text-left pb-1 pr-2 font-medium w-28">Phone</th>
                    <th className="text-right pb-1 font-medium w-20">Distance</th>
                  </tr>
                </thead>
                <tbody>
                  {garages.map(g => <GarageRow key={g.territory_id} garage={g} />)}
                </tbody>
              </table>
            )
          }
        </div>

        {/* FSL Drivers */}
        <div className="px-4 pt-3 pb-1 border-t border-slate-700/30 mt-2">
          <div className="flex items-center gap-2 mb-2">
            <Truck className="w-3.5 h-3.5 text-emerald-400" />
            <span className="text-xs font-bold text-white">FSL Drivers — Within 60 Min</span>
            <span className="text-[10px] text-slate-500 ml-1">
              {availableDrivers.length} available · {drivers.length - availableDrivers.length} busy
            </span>
          </div>
          {drivers.length === 0
            ? <p className="text-xs text-slate-500 py-2">No FSL drivers within 60 min of this location.</p>
            : <div className="space-y-0.5">{drivers.map(d => <DriverCard key={d.resource_id} driver={d} />)}</div>
          }
        </div>
      </div>
    </div>
  )
}

// ── Garage Table Row ───────────────────────────────────────────────────────

function GarageRow({ garage: g }) {
  const priorityColor = g.priority <= 3 ? 'text-blue-400' : g.priority <= 6 ? 'text-purple-400' : 'text-slate-400'
  return (
    <tr className="border-b border-slate-800/60 hover:bg-slate-800/30 transition-colors">
      <td className="py-1.5 pr-2">
        <span className={clsx('font-bold text-[10px]', priorityColor)}>P{g.priority}</span>
      </td>
      <td className="py-1.5 pr-2">
        <span className="text-slate-200 font-medium leading-tight">{g.name}</span>
      </td>
      <td className="py-1.5 pr-2">
        {g.phone
          ? <a href={`tel:${g.phone}`} className="text-emerald-400 hover:text-emerald-300 font-mono flex items-center gap-0.5">
              <Phone className="w-2.5 h-2.5" />{g.phone_display || g.phone}
            </a>
          : <span className="text-slate-600">—</span>
        }
      </td>
      <td className="py-1.5 text-right">
        {g.distance_miles != null
          ? <span className="text-slate-300">{g.distance_miles} mi</span>
          : <span className="text-slate-600">—</span>
        }
      </td>
    </tr>
  )
}

// ── Driver Card ────────────────────────────────────────────────────────────

function DriverCard({ driver: d }) {
  return (
    <div className={clsx(
      'flex items-center gap-3 px-3 py-2 rounded-lg mb-1 border transition-colors',
      d.is_available
        ? 'bg-slate-800/60 border-slate-700/50 hover:border-emerald-500/40'
        : 'bg-slate-800/40 border-slate-700/30 hover:border-yellow-500/30'
    )}>
      <div className={clsx('w-2.5 h-2.5 rounded-full shrink-0',
        d.is_available ? 'bg-emerald-400' : 'bg-yellow-400')} />

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-white truncate">{d.name}</span>
          {d.tech_id && <span className="text-[9px] text-slate-500 font-mono">#{d.tech_id}</span>}
          <span className="text-[9px] text-slate-600 truncate">{d.driver_type?.replace(' Driver', '')}</span>
        </div>
        <div className="flex items-center gap-2 mt-0.5 text-[10px] text-slate-400">
          {!d.is_available && (
            <span className="text-yellow-400">
              {d.current_status === 'InProgress' ? 'On Job' : d.current_status}
              {d.current_work_type && ` (${d.current_work_type})`}
            </span>
          )}
          {d.skills?.length > 0 && (
            <span className="truncate max-w-[150px]" title={d.skills.join(', ')}>
              {d.skills.slice(0, 3).join(', ')}{d.skills.length > 3 ? '…' : ''}
            </span>
          )}
        </div>
      </div>

      <div className="text-right shrink-0">
        {d.distance_miles != null && (
          <div className={clsx('text-xs font-bold', TIER_STYLES[d.travel_tier] || 'text-slate-400')}>
            {d.distance_miles} mi
          </div>
        )}
        {d.travel_min != null && (
          <div className="text-[10px] text-slate-500 flex items-center justify-end gap-0.5">
            <Clock className="w-2.5 h-2.5" />{Math.round(d.travel_min)} min
          </div>
        )}
      </div>

      {d.phone && (
        <a href={`tel:${d.phone}`} className="shrink-0 p-1 rounded hover:bg-slate-700 text-slate-400 hover:text-emerald-400"
          title={d.phone}>
          <Phone className="w-3.5 h-3.5" />
        </a>
      )}

      {d.is_available
        ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
        : <AlertCircle className="w-3.5 h-3.5 text-yellow-500/60 shrink-0" />
      }
    </div>
  )
}
