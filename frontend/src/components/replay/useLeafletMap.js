import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

/**
 * A plain Leaflet map on a div, the way the Studio map drives it: markers are created once and
 * moved imperatively every frame, which react-leaflet re-renders would make far too slow.
 * Basemap: plain gray (Esri). The shared Carto tiles in mapStyles.js now answer every request with an "API KEY REQUIRED"
 * image (checked 2026-10-04), so this map does not use them.
 */
export default function useLeafletMap(center, { light = false } = {}) {
  const ref = useRef(null)
  const [map, setMap] = useState(null)

  useEffect(() => {
    const m = L.map(ref.current, { zoomControl: false, attributionControl: true, preferCanvas: false, zoomSnap: 0.25, zoomDelta: 0.5 })
      .setView(center, 11)
    // Plain gray base maps (Esri), so vehicles and messages stand out. The shared Carto tiles in mapStyles.js stopped working
    // (API KEY REQUIRED), and the full OpenStreetMap look is too busy to animate on.
    const base = light ? 'World_Light_Gray_Base' : 'World_Dark_Gray_Base'
    L.tileLayer(`https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/${base}/MapServer/tile/{z}/{y}/{x}`,
      { maxZoom: 18, maxNativeZoom: 16, attribution: 'Tiles &copy; Esri' }).addTo(m)
    L.control.zoom({ position: light ? 'topright' : 'topleft' }).addTo(m)
    setMap(m)
    return () => { m.remove(); setMap(null) }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return [ref, map]
}

export const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))

export const initials = name => {
  const n = name || '?'
  const tb = n.match(/^Towbook Driver (\d+)$/)       // Towbook drivers are numbered, never named: chip reads T12
  if (tb) return `T${tb[1]}`
  return n.replace(/\s+\d{3}[A-Z]{2}$/, '').split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('')
}


/** The garage, as a small square marker. */
export function garageMarker(territory) {
  return L.marker([territory.lat, territory.lon], {
    interactive: false, keyboard: false, zIndexOffset: -500,
    icon: L.divIcon({ className: '', iconSize: [18, 18], iconAnchor: [9, 9],
      html: '<div style="width:18px;height:18px;border-radius:4px;background:#6366f1;border:2px solid #e0e7ff;box-shadow:0 0 0 3px rgba(99,102,241,.25)"></div>' }),
  })
}
