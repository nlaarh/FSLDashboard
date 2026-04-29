import { useMemo } from 'react'
import { MapContainer, TileLayer, Marker, Popup, Polyline } from 'react-leaflet'
import L from 'leaflet'
import { getMapConfig } from '../mapStyles'

function makePin(color, label) {
  return L.divIcon({
    className: '',
    html: `<div style="
      background:${color};border:2px solid rgba(255,255,255,0.8);
      border-radius:50% 50% 50% 0;transform:rotate(-45deg);
      width:16px;height:16px;box-shadow:0 2px 6px rgba(0,0,0,0.5)">
    </div><div style="color:#fff;font-size:9px;font-weight:700;
      white-space:nowrap;margin-top:2px;text-shadow:0 1px 2px rgba(0,0,0,0.9)">
      ${label}
    </div>`,
    iconSize: [16, 22],
    iconAnchor: [8, 22],
  })
}

const PINS = {
  truck:   makePin('#64748b', 'Truck'),
  call:    makePin('#ef4444', 'Call'),
  tow:     makePin('#22c55e', 'Tow Dest'),
}

export default function WOAAuditMap({ ev }) {
  const mapConfig = getMapConfig()

  const truck = ev?.truck_prev_location
  const callLat  = ev?.call_location_lat,  callLon  = ev?.call_location_lon
  const towLat   = ev?.tow_destination_lat, towLon   = ev?.tow_destination_lon

  const hasCall  = callLat != null && callLon != null
  const hasTruck = truck?.lat != null && truck?.lon != null
  const hasTow   = towLat != null && towLon != null

  const points = useMemo(() => {
    const pts = []
    if (hasTruck) pts.push([truck.lat, truck.lon])
    if (hasCall)  pts.push([callLat, callLon])
    if (hasTow)   pts.push([towLat, towLon])
    return pts
  }, [hasTruck, hasCall, hasTow, truck?.lat, truck?.lon, callLat, callLon, towLat, towLon])

  const center = useMemo(() => {
    if (!points.length) return [42.88, -76.5]
    const lat = points.reduce((s, p) => s + p[0], 0) / points.length
    const lon = points.reduce((s, p) => s + p[1], 0) / points.length
    return [lat, lon]
  }, [points])

  if (!hasCall) return (
    <div className="flex items-center justify-center h-36 rounded-xl bg-slate-800/30 border border-slate-700/20 text-[10px] text-slate-500">
      No call coordinates — map unavailable
    </div>
  )

  return (
    <div className="rounded-xl overflow-hidden border border-slate-700/30" style={{ height: 200 }}>
      <MapContainer center={center} zoom={11} style={{ height: '100%', width: '100%' }}
        zoomControl={false} attributionControl={false}>
        <TileLayer url={mapConfig.url} />

        {hasTruck && (
          <Marker position={[truck.lat, truck.lon]} icon={PINS.truck}>
            <Popup>
              <span className="text-xs font-semibold">Truck Origin</span><br />
              <span className="text-xs text-gray-600">{truck.city || ''} · {truck.source?.replace(/_/g, ' ')}</span>
            </Popup>
          </Marker>
        )}

        {hasCall && (
          <Marker position={[callLat, callLon]} icon={PINS.call}>
            <Popup>
              <span className="text-xs font-semibold">Breakdown Location</span><br />
              <span className="text-xs text-gray-600">{ev.call_location_city || ''}, {ev.call_location_state || ''}</span>
            </Popup>
          </Marker>
        )}

        {hasTow && (
          <Marker position={[towLat, towLon]} icon={PINS.tow}>
            <Popup><span className="text-xs font-semibold">Tow Destination</span></Popup>
          </Marker>
        )}

        {/* Truck → Call line (ER route) */}
        {hasTruck && hasCall && (
          <Polyline positions={[[truck.lat, truck.lon], [callLat, callLon]]}
            pathOptions={{ color: '#60a5fa', weight: 2, dashArray: '5,5', opacity: 0.7 }} />
        )}

        {/* Call → Tow line (TW route) */}
        {hasCall && hasTow && (
          <Polyline positions={[[callLat, callLon], [towLat, towLon]]}
            pathOptions={{ color: '#a78bfa', weight: 2, dashArray: '5,5', opacity: 0.7 }} />
        )}
      </MapContainer>
    </div>
  )
}
