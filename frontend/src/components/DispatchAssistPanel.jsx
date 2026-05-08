/**
 * DispatchAssistPanel.jsx
 *
 * Slide-out panel showing nearby available resources for a flagged SA.
 * On-Platform: map + driver list with GPS, skills, travel time, phone
 * Towbook: garage list with phone, address, distance
 */

import { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { clsx } from 'clsx'
import { MapContainer, TileLayer, Marker, Popup, useMap } from 'react-leaflet'
import L from 'leaflet'
import {
  X, Truck, MapPin, Phone, Clock, Navigation, Loader2,
  CheckCircle2, AlertCircle, User, Wrench, Building2, Car,
} from 'lucide-react'
import { fetchDispatchAssist } from '../api'

// ── Map Icons ──────────────────────────────────────────────────────────────

// Customer: red car icon with label
function customerMarkerIcon(label) {
  return L.divIcon({
    className: '',
    html: `<div style="display:flex;flex-direction:column;align-items:center;">
      <div style="width:32px;height:32px;background:#ef4444;border-radius:50%;border:3px solid #fff;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 8px rgba(0,0,0,0.5);">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"><path d="M7 17m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M17 17m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M5 17H3v-6l2-5h9l4 5h1a2 2 0 0 1 2 2v4h-2"/><path d="M9 17h6"/><path d="M14 7l4 4"/></svg>
      </div>
      <div style="margin-top:2px;background:rgba(0,0,0,0.75);color:#fff;font-size:9px;font-weight:bold;padding:1px 4px;border-radius:3px;white-space:nowrap;">${label}</div>
    </div>`,
    iconSize: [32, 40],
    iconAnchor: [16, 20],
  })
}

// Driver: truck icon with tier color and name label
function driverMarkerIcon(tier, isAvailable, hasSkills, name) {
  const colors = {
    tier1: '#22c55e', tier2: '#22c55e',
    tier3: '#eab308', tier4: '#eab308',
    tier5: '#f97316', tier6: '#f97316',
    unknown: '#6b7280',
  }
  const bg = !hasSkills ? '#6b7280' : !isAvailable ? '#64748b' : (colors[tier] || '#6b7280')
  const border = isAvailable && hasSkills ? '#fff' : '#94a3b8'
  const shortName = (name || '').split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase()
  return L.divIcon({
    className: '',
    html: `<div style="display:flex;flex-direction:column;align-items:center;opacity:${hasSkills ? 1 : 0.5}">
      <div style="width:26px;height:26px;background:${bg};border-radius:50%;border:2px solid ${border};display:flex;align-items:center;justify-content:center;">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"><path d="M7 17m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M17 17m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M5 17H3V6a1 1 0 0 1 1-1h9v12M9 17h6"/><path d="M13 6h5l3 5v6h-2"/></svg>
      </div>
      <div style="margin-top:1px;background:rgba(0,0,0,0.75);color:${bg};font-size:8px;font-weight:bold;padding:0px 3px;border-radius:2px;white-space:nowrap;max-width:80px;overflow:hidden;text-overflow:ellipsis;">${name || shortName}</div>
    </div>`,
    iconSize: [26, 36],
    iconAnchor: [13, 18],
  })
}

// ── Helper to fit map bounds (runs ONCE on mount, not on every render) ─────

function FitBounds({ points }) {
  const map = useMap()
  const [fitted, setFitted] = useState(false)
  useEffect(() => {
    if (fitted || points.length === 0) return
    if (points.length === 1) {
      map.setView(points[0], 13)
    } else {
      const bounds = L.latLngBounds(points)
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 })
    }
    setFitted(true)
  }, [points, map, fitted])
  return null
}

// ── Tier colors for UI ─────────────────────────────────────────────────────

const TIER_STYLES = {
  tier1: 'text-emerald-400',
  tier2: 'text-emerald-400',
  tier3: 'text-yellow-400',
  tier4: 'text-yellow-400',
  tier5: 'text-orange-400',
  tier6: 'text-orange-400',
  unknown: 'text-slate-500',
}

// ── Main Component ─────────────────────────────────────────────────────────

export default function DispatchAssistPanel({ saId, hints, alertData, onClose }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Build SA info from alert data (already in watchlist — no extra query needed)
  const sa = alertData ? {
    number: alertData.sa_number || '',
    status: alertData.status || '',
    work_type: alertData.work_type || '',
    latitude: alertData.latitude,
    longitude: alertData.longitude,
    city: alertData.city || '',
    address: alertData.address || '',
    phone: alertData.phone || '',
    member_name: alertData.member_name || '',
    wo_number: alertData.wo_number || '',
    vehicle: alertData.vehicle || '',
    vehicle_plate: alertData.vehicle_plate || '',
    facility_name: alertData.facility_name || '',
    facility_phone: alertData.facility_phone || '',
    channel: 'on-platform',
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

  // Merge SA info with driver data from API
  const viewData = data ? { ...data, sa } : null

  return createPortal(
    <div className="fixed inset-0 z-[9998] flex">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

      {/* Panel */}
      <div className="relative ml-auto w-full max-w-3xl h-full max-h-screen bg-slate-900 border-l border-slate-700 shadow-2xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-700/50 bg-slate-800/50">
          <div className="flex items-center gap-2">
            <Navigation className="w-4 h-4 text-blue-400" />
            <span className="font-bold text-sm text-white">Dispatch Assist</span>
            {sa && (
              <span className="text-[10px] text-slate-400 font-mono ml-2">
                {sa.number} · 🚛 On-Platform
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
              <span className="ml-2 text-sm text-slate-400">Loading nearby resources...</span>
            </div>
          )}
          {error && (
            <div className="p-6 text-center">
              <AlertCircle className="w-6 h-6 text-red-400 mx-auto mb-2" />
              <p className="text-sm text-red-400">{error}</p>
            </div>
          )}
          {viewData && !loading && (
            <OnPlatformView data={viewData} />
          )}
        </div>
      </div>
    </div>,
    document.body
  )
}

// ── Shared SA Info Bar ────────────────────────────────────────────────────

function SAInfoBar({ sa, extra }) {
  return (
    <div className="px-4 py-3 bg-slate-800/80 border-b border-slate-700/30 text-[11px] text-slate-300 space-y-1.5">
      {/* Row 1: SA number, WO, work type, status */}
      <div className="flex items-center gap-3 flex-wrap">
        <span className="font-bold text-white text-sm">{sa.number}</span>
        {sa.wo_number && <span className="text-slate-400 font-mono text-[10px]">WO {sa.wo_number}</span>}
        <span className="text-slate-500">·</span>
        <span><Wrench className="w-3 h-3 inline text-blue-400 mr-1" />{sa.work_type || '—'}</span>
        <span className={clsx('font-bold', sa.status === 'Dispatched' ? 'text-blue-400' : sa.status === 'En Route' ? 'text-yellow-400' : 'text-slate-400')}>
          {sa.status}
        </span>
        {extra}
      </div>

      {/* Row 2: Customer location */}
      <div className="flex items-center gap-1">
        <MapPin className="w-3 h-3 text-red-400 shrink-0" />
        <span className="text-white font-medium">{sa.address || sa.city || '—'}</span>
      </div>

      {/* Row 3: Member + phone */}
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

      {/* Row 4: Vehicle */}
      {(sa.vehicle || sa.vehicle_plate) && (
        <div className="flex items-center gap-1">
          <Car className="w-3 h-3 text-sky-400 shrink-0" />
          <span className="text-sky-300 font-medium">{sa.vehicle}</span>
          {sa.vehicle_plate && <span className="ml-2 text-[10px] bg-sky-500/15 text-sky-300 px-1.5 py-0.5 rounded font-mono font-bold">{sa.vehicle_plate}</span>}
          {sa.vehicle_group && <span className="text-slate-500 ml-1">({sa.vehicle_group})</span>}
        </div>
      )}

      {/* Row 5: Assigned garage */}
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

// ── On-Platform View (Map + Driver List) ──────────────────────────────────

function OnPlatformView({ data }) {
  const { sa, drivers = [], required_skills = [], total_eligible } = data
  const saPos = sa?.latitude && sa?.longitude ? [sa.latitude, sa.longitude] : null

  // Build map points
  const mapPoints = []
  if (saPos) mapPoints.push(saPos)
  drivers.forEach(d => {
    if (d.latitude && d.longitude) mapPoints.push([d.latitude, d.longitude])
  })

  const availableCount = drivers.filter(d => d.is_available && d.has_required_skills).length
  const busyCount = drivers.filter(d => !d.is_available && d.has_required_skills).length

  return (
    <div className="flex flex-col h-full">
      <SAInfoBar sa={sa} extra={required_skills?.length > 0 && (
        <div className="text-slate-500">Skills needed: {required_skills.join(', ')}</div>
      )} />

      {/* Stats bar */}
      <div className="px-4 py-2 flex items-center gap-4 text-[11px] border-b border-slate-700/30">
        <span className="text-emerald-400 font-bold">{availableCount} available</span>
        <span className="text-yellow-400">{busyCount} busy</span>
        <span className="text-slate-500">{total_eligible} total in range</span>
      </div>

      {/* Map */}
      {saPos && mapPoints.length > 0 && (
        <div className="h-80 min-h-[320px] border-b border-slate-700/30">
          <MapContainer center={saPos} zoom={11} className="h-full w-full"
            scrollWheelZoom={true} zoomControl={true}
            style={{ background: '#1e293b' }}>
            <TileLayer
              url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
              attribution='&copy; OpenStreetMap'
            />
            <FitBounds points={mapPoints} />
            {/* Customer marker — car icon with SA number label */}
            <Marker position={saPos} icon={customerMarkerIcon(sa.number)}>
              <Popup><b>{sa.number}</b><br/>{sa.member_name}<br/>{sa.address || sa.city}<br/>{sa.vehicle}</Popup>
            </Marker>
            {/* Driver markers — truck icon with name label */}
            {drivers.map(d => d.latitude && d.longitude && (
              <Marker
                key={d.resource_id}
                position={[d.latitude, d.longitude]}
                icon={driverMarkerIcon(d.travel_tier, d.is_available, d.has_required_skills, d.name)}
              >
                <Popup>
                  <b>{d.name}</b><br/>
                  {d.is_available ? '🟢 Available' : `🟡 ${d.current_status}`}
                  {d.distance_miles != null && <><br/>{d.distance_miles} mi · ~{Math.round(d.travel_min || 0)} min</>}
                  {d.phone && <><br/>📞 {d.phone}</>}
                </Popup>
              </Marker>
            ))}
          </MapContainer>
        </div>
      )}

      {/* Driver list */}
      <div className="flex-1 overflow-y-auto px-2 py-2">
        {drivers.length === 0 ? (
          <p className="text-center text-slate-500 py-6 text-sm">No drivers within 60 min range</p>
        ) : (
          drivers.map(d => <DriverCard key={d.resource_id} driver={d} />)
        )}
      </div>
    </div>
  )
}

function DriverCard({ driver: d }) {
  return (
    <div className={clsx(
      'flex items-center gap-3 px-3 py-2 rounded-lg mb-1 border transition-colors',
      d.has_required_skills && d.is_available
        ? 'bg-slate-800/60 border-slate-700/50 hover:border-emerald-500/40'
        : d.has_required_skills
          ? 'bg-slate-800/40 border-slate-700/30 hover:border-yellow-500/30'
          : 'bg-slate-800/20 border-slate-800/30 opacity-60'
    )}>
      {/* Status dot */}
      <div className={clsx('w-2.5 h-2.5 rounded-full shrink-0',
        d.is_available && d.has_required_skills ? 'bg-emerald-400' :
        d.has_required_skills ? 'bg-yellow-400' : 'bg-slate-600'
      )} />

      {/* Name + type */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-white truncate">{d.name}</span>
          {d.tech_id && <span className="text-[9px] text-slate-500 font-mono">#{d.tech_id}</span>}
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

      {/* Distance + ETA */}
      <div className="text-right shrink-0">
        {d.distance_miles != null && (
          <div className={clsx('text-xs font-bold', TIER_STYLES[d.travel_tier] || 'text-slate-400')}>
            {d.distance_miles} mi
          </div>
        )}
        {d.travel_min != null && (
          <div className="text-[10px] text-slate-500 flex items-center justify-end gap-0.5">
            <Clock className="w-2.5 h-2.5" />
            {Math.round(d.travel_min)} min
          </div>
        )}
      </div>

      {/* Phone */}
      {d.phone && (
        <a href={`tel:${d.phone}`} className="shrink-0 p-1 rounded hover:bg-slate-700 text-slate-400 hover:text-emerald-400"
          title={d.phone}>
          <Phone className="w-3.5 h-3.5" />
        </a>
      )}

      {/* Skill match indicator */}
      {d.has_required_skills ? (
        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0" title="Skills match" />
      ) : (
        <AlertCircle className="w-3.5 h-3.5 text-slate-600 shrink-0" title="Missing required skills" />
      )}
    </div>
  )
}

// TowbookView and GarageCard removed — Dispatch Assist shows On-Platform view only
