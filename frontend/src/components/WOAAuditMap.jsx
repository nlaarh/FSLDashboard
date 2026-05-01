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

function makeDistanceLabel(text, color) {
  return L.divIcon({
    className: '',
    html: `<div style="
      background:rgba(15,23,42,0.85);border:1px solid ${color};
      border-radius:4px;padding:2px 6px;
      color:${color};font-size:9px;font-weight:700;
      white-space:nowrap;box-shadow:0 1px 4px rgba(0,0,0,0.6);
      line-height:1.3">
      ${text}
    </div>`,
    iconSize: [1, 1],
    iconAnchor: [0, 0],
  })
}

function makeTollIcon(priceText) {
  return L.divIcon({
    className: '',
    html: `<div style="
      background:rgba(217,119,6,0.92);border:1.5px solid #fbbf24;
      border-radius:50%;width:22px;height:22px;
      display:flex;align-items:center;justify-content:center;
      box-shadow:0 2px 6px rgba(0,0,0,0.5);
      font-size:11px;line-height:1">💰</div>
    ${priceText ? `<div style="color:#fbbf24;font-size:8px;font-weight:700;text-align:center;margin-top:1px;text-shadow:0 1px 2px rgba(0,0,0,0.9);white-space:nowrap">${priceText}</div>` : ''}`,
    iconSize: [22, priceText ? 34 : 22],
    iconAnchor: [11, 11],
  })
}

const PINS = {
  truck:   makePin('#64748b', 'Truck'),
  call:    makePin('#ef4444', 'Call'),
  tow:     makePin('#22c55e', 'Tow Dest'),
}

function midpoint(a, b) {
  return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
}

export default function WOAAuditMap({ ev }) {
  const mapConfig = getMapConfig()

  const truck = ev?.truck_prev_location
  // Fall back to SA on-location GPS when WO.Latitude is not geocoded
  const _saLat = ev?.sa_on_location_lat > 0 ? ev.sa_on_location_lat : null
  const _saLon = ev?.sa_on_location_lat > 0 ? ev.sa_on_location_lon : null
  const _rflibLat = ev?.rflib_on_location?.lat > 0 ? ev.rflib_on_location.lat : null
  const _rflibLon = ev?.rflib_on_location?.lat > 0 ? ev.rflib_on_location.lon : null
  const callLat  = ev?.call_location_lat || _saLat || _rflibLat || null
  const callLon  = ev?.call_location_lon || _saLon || _rflibLon || null
  const towLat   = ev?.tow_destination_lat, towLon   = ev?.tow_destination_lon

  const hasCall  = callLat != null && callLon != null
  const hasTruck = truck?.lat != null && truck?.lon != null
  const hasTow   = towLat != null && towLon != null

  // Distance values — prefer actual SF miles, fall back to estimated
  const erMiles  = ev?.sf_enroute_miles ?? ev?.sf_estimated_miles
  const towMiles = ev?.sf_tow_miles ?? ev?.sf_estimated_tow_miles

  // Toll context (only populated for TL product audits)
  const tollData    = ev?.tl_context?.toll
  const tollLikely  = tollData?.toll_likely === true
  const tollPrice   = tollData?.estimated_price?.[0]
  const tollText    = tollPrice ? `$${tollPrice.amount}` : null

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

  // Midpoints for distance labels
  const erMid  = hasTruck && hasCall ? midpoint([truck.lat, truck.lon], [callLat, callLon]) : null
  const towMid = hasCall && hasTow   ? midpoint([callLat, callLon], [towLat, towLon]) : null

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

        {/* Distance label — en route segment */}
        {erMid && erMiles != null && (
          <Marker position={erMid}
            icon={makeDistanceLabel(`${erMiles.toFixed(1)} mi`, '#60a5fa')}
            interactive={false} />
        )}

        {/* Distance label — tow segment */}
        {towMid && towMiles != null && (
          <Marker position={towMid}
            icon={makeDistanceLabel(`${towMiles.toFixed(1)} mi`, '#a78bfa')}
            interactive={false} />
        )}

        {/* Toll icon — shown near call location when toll detected */}
        {tollLikely && hasCall && (
          <Marker position={[callLat + 0.008, callLon + 0.01]}
            icon={makeTollIcon(tollText)}>
            <Popup>
              <span className="text-xs font-semibold">⚠ Toll Road Detected</span>
              {tollText && <><br /><span className="text-xs text-gray-600">Est. toll: {tollText} {tollPrice?.currency || ''}</span></>}
            </Popup>
          </Marker>
        )}
      </MapContainer>
    </div>
  )
}
