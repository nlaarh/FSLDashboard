import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

/**
 * A plain Leaflet map on a div, the way the Studio map drives it: markers are created once and
 * moved imperatively every frame, which react-leaflet re-renders would make far too slow.
 * Basemap: Esri World Street Map (light by default; dark is a CSS filter on the tile pane (.rp-dark / .rp-light in index.css), so the
 * theme switches with one class and no tile reload. The shared Carto tiles in mapStyles.js answer with an "API KEY REQUIRED"
 * image (checked 2026-10-04), so they are not used here.
 */
export default function useLeafletMap(center, { light = true } = {}) {
  const ref = useRef(null)
  const [map, setMap] = useState(null)

  useEffect(() => {
    const m = L.map(ref.current, { zoomControl: false, attributionControl: true, preferCanvas: false, zoomSnap: 0.25, zoomDelta: 0.5 })
      .setView(center, 11)
    ref.current.classList.add('rp-map', light ? 'rp-light' : 'rp-dark')
    // A clean street map (Esri World Street Map, no key): plain colours and clear street names, like Apple Maps. Owner, 2026-10-08.
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}', { maxZoom: 19, attribution: 'Tiles &copy; Esri' }).addTo(m)
    L.control.zoom({ position: 'topleft' }).addTo(m)
    setMap(m)
    // the map re-measures itself whenever its box changes size (Expand, window resize), or the tiles stay in the old frame
    const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => m.invalidateSize({ animate: false }))
    ro?.observe(ref.current)
    return () => { ro?.disconnect(); m.remove(); setMap(null) }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return [ref, map]
}

/** Switch the basemap theme (dark or light) on a map container. */
export const setMapTheme = (el, light) => { el?.classList.toggle('rp-light', light); el?.classList.toggle('rp-dark', !light) }

export const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))

export const initials = name => {
  const n = name || '?'
  const tb = n.match(/^Towbook Driver (\d+)$/)       // Towbook drivers are numbered, never named: chip reads T12
  if (tb) return `T${tb[1]}`
  return n.replace(/\s+\d{3}[A-Z]{2}$/, '').split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('')
}

