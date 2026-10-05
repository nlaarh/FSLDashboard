import { useEffect, useRef } from 'react'
import L from 'leaflet'
import useLeafletMap, { esc, initials, garageMarker } from './useLeafletMap'
import { trailUntil } from './replayMath'
import { verdictColour } from '../reportcard/reportCardStyles'

const STACK = n => (n >= 3 ? '#f97316' : '#fbbf24')

/** Driver chip, after the Studio replay truck marker: initials, status colour, held-calls badge. */
function truckHtml(d, selected, smooth) {
  const n = d.held.length
  const est = d.mode === 'estimated'
  const stale = d.pos.stale > 0
  const arrow = d.pos.heading != null && !stale
    ? `<div style="position:absolute;left:50%;top:50%;width:0;height:0;transform:translate(-50%,-50%) rotate(${d.pos.heading}deg) translateY(-19px);
        border-left:5px solid transparent;border-right:5px solid transparent;border-bottom:7px solid ${d.status.colour}"></div>` : ''
  return `<div style="position:relative;width:30px;height:30px;opacity:${stale ? 0.45 : 1};${smooth ? 'transition:opacity .3s' : ''}">
    ${arrow}
    <div style="width:30px;height:30px;border-radius:9px;background:#0f172a;display:flex;align-items:center;justify-content:center;
      border:2.5px ${est ? 'dashed' : 'solid'} ${d.status.colour};font:700 11px/1 system-ui;color:#f1f5f9;
      box-shadow:${selected ? '0 0 0 3px #fff,0 0 0 6px #6366f1' : '0 2px 6px rgba(0,0,0,.5)'}">${esc(initials(d.name))}</div>
    ${n >= 2 ? `<div style="position:absolute;top:-8px;right:-9px;min-width:17px;height:17px;padding:0 4px;border-radius:9px;
      background:${STACK(n)};color:#0f172a;font:800 10px/17px system-ui;text-align:center;border:1.5px solid #0f172a">${n}</div>` : ''}
    ${selected ? `<div style="position:absolute;top:34px;left:50%;transform:translateX(-50%);white-space:nowrap;background:#0f172aee;
      border:1px solid #334155;border-radius:6px;padding:1px 6px;font:600 10px system-ui;color:#e2e8f0">${esc(d.name)}</div>` : ''}
  </div>`
}

function iconKey(d, selected) {
  return [d.status.key, d.held.length, d.mode, d.pos.stale > 0, d.pos.heading == null ? '-' : Math.round(d.pos.heading / 15), selected].join('|')
}

function tipText(d) {
  const src = d.mode === 'gps' ? (d.pos.stale ? `GPS gap: last ping ${Math.round(d.pos.stale / 60)} min ago` : 'Real GPS')
    : 'Estimated position (no GPS)'
  return `<b>${esc(d.name)}</b><br>${esc(d.status.label)}${d.held.length ? ` · holds ${d.held.length} call${d.held.length > 1 ? 's' : ''}` : ''}<br><span style="color:#94a3b8">${src}</span>`
}

/**
 * The Day replay map: every driver at the clock time, call pins from creation to clear coloured by
 * verdict, a dashed line from each driver to every call he holds (stacking is visible as a fan).
 */
export default function DayReplayMap({ replay, frame, t, verdictById, selectedDriver, selectedSa, onSelectDriver, onSelectSa, smooth }) {
  const [ref, map] = useLeafletMap([replay.territory.lat, replay.territory.lon])
  const layers = useRef(null)

  useEffect(() => {
    if (!map) return undefined
    const g = { drivers: new Map(), keys: new Map(), pins: new Map(), lines: new Map(), trail: L.polyline([], { color: '#a5b4fc', weight: 3, opacity: 0.8 }) }
    g.root = L.layerGroup([garageMarker(replay.territory), g.trail]).addTo(map)
    const pts = replay.calls.filter(c => c.lat != null).map(c => [c.lat, c.lon])
    if (pts.length) map.fitBounds(L.latLngBounds([...pts, [replay.territory.lat, replay.territory.lon]]), { padding: [30, 30], maxZoom: 12 })
    layers.current = g
    return () => { g.root.remove(); layers.current = null }
  }, [map, replay])

  useEffect(() => {
    const g = layers.current
    if (!g) return
    // Call pins: hollow while the member waits, solid once a driver is there, red ring past the original promise.
    const open = new Set()
    for (const c of frame.open) {
      if (c.lat == null) continue
      open.add(c.id)
      const arrived = c.arrival != null && t >= c.arrival
      const late = c.promise_due && t > c.promise_due && !arrived
      const colour = verdictColour(verdictById[c.id])
      const style = { radius: c.id === selectedSa ? 9 : 6, color: late ? '#f43f5e' : (c.id === selectedSa ? '#fff' : colour),
        weight: late || c.id === selectedSa ? 3 : 2, fillColor: colour, fillOpacity: arrived ? 0.95 : 0.25 }
      let pin = g.pins.get(c.id)
      if (!pin) {
        pin = L.circleMarker([c.lat, c.lon], style).on('click', () => onSelectSa(c.id)).addTo(g.root)
        pin.bindTooltip('', { direction: 'top', offset: [0, -6] })
        g.pins.set(c.id, pin)
      } else pin.setStyle(style)
      pin.setTooltipContent(`<b>${esc(c.number)}</b><br>${arrived ? 'Driver on scene' : 'Member waiting'}${late ? ' · past original promise' : ''}`)
    }
    for (const [id, pin] of g.pins) if (!open.has(id)) { pin.remove(); g.pins.delete(id) }

    // Drivers and their held-call lines.
    const seen = new Set(), lineSeen = new Set()
    for (const d of frame.drivers) {
      if (!d.pos) continue
      seen.add(d.id)
      const sel = d.id === selectedDriver
      let mk = g.drivers.get(d.id)
      const key = iconKey(d, sel)
      if (!mk) {
        mk = L.marker([d.pos.lat, d.pos.lon], { zIndexOffset: 1000 }).on('click', () => onSelectDriver(d.id)).addTo(g.root)
        mk.bindTooltip('', { direction: 'right', offset: [16, 0] })
        g.drivers.set(d.id, mk)
      } else mk.setLatLng([d.pos.lat, d.pos.lon])
      if (g.keys.get(d.id) !== key) {
        mk.setIcon(L.divIcon({ className: '', iconSize: [30, 30], iconAnchor: [15, 15], html: truckHtml(d, sel, smooth) }))
        mk.setZIndexOffset(sel ? 3000 : 1000 + d.held.length * 100)
        g.keys.set(d.id, key)
      }
      mk.setTooltipContent(tipText(d))
      for (const c of d.held) {
        if (c.lat == null) continue
        const lk = `${d.id}:${c.id}`
        lineSeen.add(lk)
        const style = { color: d.held.length >= 2 ? STACK(d.held.length) : verdictColour(verdictById[c.id]), weight: 2, opacity: 0.8, dashArray: '5 5' }
        const ll = [[d.pos.lat, d.pos.lon], [c.lat, c.lon]]
        const line = g.lines.get(lk)
        if (line) line.setLatLngs(ll).setStyle(style)
        else g.lines.set(lk, L.polyline(ll, { ...style, interactive: false }).addTo(g.root))
      }
    }
    for (const [id, mk] of g.drivers) if (!seen.has(id)) { mk.remove(); g.drivers.delete(id); g.keys.delete(id) }
    for (const [k, line] of g.lines) if (!lineSeen.has(k)) { line.remove(); g.lines.delete(k) }

    const track = replay.drivers.find(d => d.id === selectedDriver)?.track
    g.trail.setLatLngs(track ? trailUntil(track, t) : [])
  }, [frame, t, replay, verdictById, selectedDriver, selectedSa, onSelectDriver, onSelectSa, smooth])

  return <div ref={ref} className="w-full h-full rounded-xl overflow-hidden" style={{ background: '#0b1220' }} />
}
