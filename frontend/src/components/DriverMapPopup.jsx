/**
 * DriverMapPopup.jsx
 *
 * Small floating map popup showing driver GPS vs customer location.
 * Shows distance, estimated drive time, customer name/phone, driver phone.
 * Opens when dispatcher clicks a driver name in the live board.
 */

import { useState, useEffect, useRef } from 'react'
import { clsx } from 'clsx'
import { MapContainer, TileLayer, Marker, Polyline, useMap } from 'react-leaflet'
import L from 'leaflet'
import { X, Navigation, MapPin, Truck, Clock, Phone, User, Loader2 } from 'lucide-react'
import { lookupSA } from '../api'

// Haversine distance in miles
function haversine(lat1, lon1, lat2, lon2) {
  const R = 3958.8
  const dLat = (lat2 - lat1) * Math.PI / 180
  const dLon = (lon2 - lon1) * Math.PI / 180
  const a = Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
    Math.sin(dLon / 2) ** 2
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

const truckIcon = L.divIcon({
  className: '',
  html: `<div style="width:24px;height:24px;background:#6366f1;border-radius:50%;border:2px solid #fff;display:flex;align-items:center;justify-content:center;">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="1" y="3" width="15" height="13"></rect><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"></polygon><circle cx="5.5" cy="18.5" r="2.5"></circle><circle cx="18.5" cy="18.5" r="2.5"></circle></svg>
  </div>`,
  iconSize: [24, 24],
  iconAnchor: [12, 12],
})

const customerIcon = L.divIcon({
  className: '',
  html: `<div style="width:24px;height:24px;background:#ef4444;border-radius:50%;border:2px solid #fff;display:flex;align-items:center;justify-content:center;">
    <svg width="12" height="12" viewBox="0 0 24 24" fill="#fff" stroke="none"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3" fill="#ef4444"/></svg>
  </div>`,
  iconSize: [24, 24],
  iconAnchor: [12, 12],
})

function FitBounds({ bounds }) {
  const map = useMap()
  useEffect(() => {
    if (bounds) map.fitBounds(bounds, { padding: [30, 30], maxZoom: 14 })
  }, [bounds, map])
  return null
}

export default function DriverMapPopup({ driver, onClose }) {
  const popupRef = useRef(null)
  const [extra, setExtra] = useState(null)
  const [extraLoading, setExtraLoading] = useState(false)
  const [driverAddress, setDriverAddress] = useState(null)

  // Lazy-load customer name, phone, driver details from lookupSA
  useEffect(() => {
    if (!driver?.sa_number) return
    setExtraLoading(true)
    lookupSA(driver.sa_number)
      .then(d => setExtra(d))
      .catch(() => setExtra(null))
      .finally(() => setExtraLoading(false))
  }, [driver?.sa_number])

  // Reverse-geocode driver lat/lon to a readable address
  useEffect(() => {
    const lat = driver?.driver_lat
    const lon = driver?.driver_lon
    if (lat == null || lon == null) return
    setDriverAddress(null)
    fetch(`https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json&zoom=16&addressdetails=1`, {
      headers: { 'Accept-Language': 'en' }
    })
      .then(r => r.json())
      .then(d => {
        const a = d.address || {}
        const parts = [a.house_number, a.road, a.city || a.town || a.village].filter(Boolean)
        setDriverAddress(parts.join(' ') || d.display_name?.split(',').slice(0, 3).join(',') || null)
      })
      .catch(() => setDriverAddress(null))
  }, [driver?.driver_lat, driver?.driver_lon])

  useEffect(() => {
    const handler = (e) => {
      if (popupRef.current && !popupRef.current.contains(e.target)) onClose()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose])

  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  if (!driver) return null

  const dLat = driver.driver_lat
  const dLon = driver.driver_lon
  const cLat = driver.customer_lat
  const cLon = driver.customer_lon
  const hasDriver = dLat != null && dLon != null
  const hasCustomer = cLat != null && cLon != null
  const hasBoth = hasDriver && hasCustomer

  const distance = hasBoth ? haversine(dLat, dLon, cLat, cLon) : null
  const estMinutes = distance != null ? Math.round(distance / 0.5) : null

  const center = hasBoth
    ? [(dLat + cLat) / 2, (dLon + cLon) / 2]
    : hasDriver ? [dLat, dLon]
    : hasCustomer ? [cLat, cLon]
    : [42.9, -78.8]

  const bounds = hasBoth ? L.latLngBounds([dLat, dLon], [cLat, cLon]) : null

  // Extra data from lookupSA
  const sa = extra?.sa || {}
  const closestDriver = extra?.drivers?.[0]
  const customerName = sa.customer || ''
  const customerPhone = sa.phone || ''

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div
        ref={popupRef}
        className="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl overflow-hidden"
        style={{ width: 400, maxHeight: '85vh' }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-800">
          <div className="flex items-center gap-2">
            <Truck className="w-4 h-4 text-indigo-400" />
            <div>
              <span className="text-sm font-semibold text-white">{driver.driver_name}</span>
              <span className="text-[10px] text-slate-500 ml-2">{driver.territory_short || driver.territory}</span>
            </div>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-slate-800 text-slate-500 hover:text-white transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Map */}
        <div style={{ height: 200 }}>
          {(hasDriver || hasCustomer) ? (
            <MapContainer center={center} zoom={12} className="w-full h-full" zoomControl={false} attributionControl={false}>
              <TileLayer url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png" />
              {hasDriver && <Marker position={[dLat, dLon]} icon={truckIcon} />}
              {hasCustomer && <Marker position={[cLat, cLon]} icon={customerIcon} />}
              {hasBoth && (
                <Polyline
                  positions={[[dLat, dLon], [cLat, cLon]]}
                  pathOptions={{ color: '#6366f1', weight: 2, dashArray: '6,6', opacity: 0.7 }}
                />
              )}
              {bounds && <FitBounds bounds={bounds} />}
            </MapContainer>
          ) : (
            <div className="w-full h-full flex items-center justify-center bg-slate-950 text-slate-600 text-xs">
              No GPS data available
            </div>
          )}
        </div>

        {/* Info panel */}
        <div className="px-4 py-3 space-y-2.5">
          {/* Distance + ETA bar */}
          {hasBoth && (
            <div className="flex gap-4 pb-2 border-b border-slate-800">
              <div className="flex items-center gap-1.5">
                <Navigation className="w-4 h-4 text-amber-400" />
                <span className="text-base font-bold font-mono text-amber-400">
                  {distance < 1 ? `${(distance * 5280).toFixed(0)} ft` : `${distance.toFixed(1)} mi`}
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <Clock className="w-4 h-4 text-slate-400" />
                <span className="text-base font-mono text-slate-300">
                  ~{estMinutes < 1 ? '<1' : estMinutes} min
                </span>
              </div>
            </div>
          )}

          {/* Driver info */}
          <div className="flex items-start gap-2.5">
            <div className="w-6 h-6 rounded-full bg-indigo-500/20 flex items-center justify-center flex-shrink-0 mt-0.5">
              <Truck className="w-3 h-3 text-indigo-400" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-[10px] text-slate-500 uppercase tracking-wide">Driver — Last Known Location</div>
              <div className="text-xs font-medium text-white">{driver.driver_name}</div>
              <div className="text-[11px] text-slate-400">
                {driverAddress || driver.territory || '—'}
              </div>
              {extraLoading && <Loader2 className="w-3 h-3 animate-spin text-slate-600 mt-1" />}
              {closestDriver?.phone && (
                <div className="flex items-center gap-1 mt-0.5 text-[11px] text-blue-400">
                  <Phone className="w-2.5 h-2.5" /> {closestDriver.phone}
                </div>
              )}
            </div>
          </div>

          {/* Customer info */}
          <div className="flex items-start gap-2.5">
            <div className="w-6 h-6 rounded-full bg-red-500/20 flex items-center justify-center flex-shrink-0 mt-0.5">
              <User className="w-3 h-3 text-red-400" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-[10px] text-slate-500 uppercase tracking-wide">Customer</div>
              {extraLoading ? (
                <Loader2 className="w-3 h-3 animate-spin text-slate-600 mt-1" />
              ) : (
                <>
                  {customerName && <div className="text-xs font-medium text-white">{customerName}</div>}
                  <div className="text-[11px] text-slate-400">
                    {driver.address || sa.address || (hasCustomer ? `${cLat.toFixed(4)}, ${cLon.toFixed(4)}` : 'No location')}
                  </div>
                  {customerPhone && (
                    <div className="flex items-center gap-1 mt-0.5 text-[11px] text-blue-400">
                      <Phone className="w-2.5 h-2.5" /> {customerPhone}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}
