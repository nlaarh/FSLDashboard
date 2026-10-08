import { useEffect, useRef } from 'react'
import L from 'leaflet'
import useLeafletMap, { esc } from './useLeafletMap'
import { dayFrame, trailUntil } from './replayMath'
import { dayTruckHtml, dayPinHtml, garageHtml, truckKindFor } from './gameIcons'
import { verdictColour } from '../reportcard/reportCardStyles'

const STACK = n => (n >= 3 ? '#f97316' : '#fbbf24')
const SLOW_MS = 66   // call pins, lines and the trail move 15 times a second; trucks move every frame
const diff = (a, b) => ((b - a + 540) % 360) - 180
const icon = (html, w, h) => L.divIcon({ className: '', html, iconSize: [w, h], iconAnchor: [w / 2, h / 2] })

function tipText(d) {
  const src = d.mode === 'gps' ? (d.pos.stale ? `GPS gap: last ping ${Math.round(d.pos.stale / 60)} min ago` : 'Real GPS') : 'Estimated position (no GPS)'
  return `<b>${esc(d.name)}</b><br>${esc(d.status.label)}${d.held.length ? ` · holds ${d.held.length} call${d.held.length > 1 ? 's' : ''}` : ''}<br><span style="color:#94a3b8">${src}</span>`
}

/**
 * The Day replay map: every driver as a heading-rotating tow truck, call pins from creation to clear, and a dashed line from each
 * driver to every call he holds (stacking shows as a fan). It subscribes to the replay engine and moves layers itself every frame,
 * so React does not render while it plays. Calls past the original promise get a pulsing red ring.
 */
export default function DayReplayMap({ replay, engine, dayDrivers, sasById, verdictById, selectedDriver, selectedSa, onSelectDriver, onSelectSa }) {
  const [ref, map] = useLeafletMap([replay.territory.lat, replay.territory.lon])
  const g = useRef(null)
  const cb = useRef({}); cb.current = { onSelectDriver, onSelectSa, verdictById }

  useEffect(() => {
    if (!map) return undefined
    const root = L.layerGroup().addTo(map)
    L.marker([replay.territory.lat, replay.territory.lon], { interactive: false, keyboard: false, zIndexOffset: -500, icon: icon(garageHtml((replay.territory.name || 'Garage').replace(/^\w+\s+-\s+/, '')), 46, 42) }).addTo(root)
    const trail = L.polyline([], { color: '#a5b4fc', weight: 3, opacity: 0.8, interactive: false }).addTo(root)
    const pts = replay.calls.filter(c => c.lat != null).map(c => [c.lat, c.lon])
    if (pts.length) map.fitBounds(L.latLngBounds([...pts, [replay.territory.lat, replay.territory.lon]]), { padding: [30, 30], maxZoom: 12 })
    const drivers = new Map(), pins = new Map(), lines = new Map()
    const kinds = Object.fromEntries(replay.drivers.map(d => [d.id, truckKindFor({ truck: dayDrivers[d.id]?.truck, skills: dayDrivers[d.id]?.skills })]))
    let slowAt = 0

    const run = t => {
      const f = dayFrame(replay, dayDrivers, sasById, t)
      const slow = !engine.ref.current.playing || performance.now() - slowAt >= SLOW_MS
      const seen = new Set()
      for (const d of f.drivers) {
        if (!d.pos || d.status.key === 'off') continue   // off-shift drivers are not drawn on the day map
        seen.add(d.id)
        let it = drivers.get(d.id)
        if (!it) {
          const mk = L.marker([d.pos.lat, d.pos.lon], { zIndexOffset: 1000, icon: icon(dayTruckHtml({ name: d.name.replace(/\s+\d{2,3}[A-Z]{0,2}$/, ''), kind: kinds[d.id], est: d.mode === 'estimated' }), 40, 40) })
            .on('click', () => cb.current.onSelectDriver(d.id)).addTo(root)
          mk.bindTooltip('', { direction: 'right', offset: [16, 0] })
          const el = mk.getElement()?.firstElementChild
          it = { mk, el, hdg: el?.querySelector('.hdg'), held: el?.querySelector('.rp-held'), rot: null, lastH: null, key: '' }
          drivers.set(d.id, it)
          el?.classList.toggle('selected', d.id === g.current?.sel)
        }
        it.mk.setLatLng([d.pos.lat, d.pos.lon])
        const moving = d.pos.heading != null && d.pos.stale === 0
        if (moving) {
          it.rot = it.rot == null ? d.pos.heading : it.rot + diff(it.rot % 360, d.pos.heading)
          if (it.lastH == null || Math.abs(diff(it.lastH, d.pos.heading)) > 3) { it.lastH = d.pos.heading; it.hdg?.style.setProperty('transform', `rotate(${it.rot.toFixed(1)}deg)`) }
        }
        const key = `${d.status.key}|${d.held.length}|${moving}|${d.pos.stale > 0}`
        if (key !== it.key && it.el) {
          it.key = key
          it.el.style.setProperty('--c', d.status.colour)
          it.el.classList.toggle('live', moving)
          it.el.style.opacity = d.pos.stale > 0 ? 0.5 : 1
          if (it.held) { it.held.style.display = d.held.length >= 2 ? '' : 'none'; it.held.textContent = d.held.length; it.held.style.background = STACK(d.held.length) }
          it.mk.setZIndexOffset(1000 + d.held.length * 100)
          it.mk.setTooltipContent(tipText(d))
        }
      }
      for (const [id, it] of drivers) if (!seen.has(id)) { it.mk.remove(); drivers.delete(id) }
      if (!slow) return
      slowAt = performance.now()

      const open = new Set()
      for (const c of f.open) {
        if (c.lat == null) continue
        open.add(c.id)
        const arrived = c.arrival != null && t >= c.arrival
        const late = !!c.promise_due && t > c.promise_due && !arrived
        const state = arrived ? 'done' : late ? 'late' : 'ok'
        let pin = pins.get(c.id)
        if (!pin) {
          const mk = L.marker([c.lat, c.lon], { icon: icon(dayPinHtml(verdictColour(cb.current.verdictById[c.id])), 24, 24), zIndexOffset: 200 })
            .on('click', () => cb.current.onSelectSa(c.id)).addTo(root)
          mk.bindTooltip('', { direction: 'top', offset: [0, -8] })
          pin = { mk, el: mk.getElement()?.firstElementChild, state: '' }
          pins.set(c.id, pin)
        }
        if (pin.state !== state || pin.sel !== (c.id === g.current?.selSa)) {
          pin.state = state; pin.sel = c.id === g.current?.selSa
          if (pin.el) pin.el.className = `rp-dpin ${state}${pin.sel ? ' sel' : ''}`
          pin.mk.setTooltipContent(`<b>${esc(c.number)}</b><br>${arrived ? 'Driver on scene' : 'Member waiting'}${late ? ' · past original promise' : ''}`)
        }
      }
      for (const [id, p] of pins) if (!open.has(id)) { p.mk.remove(); pins.delete(id) }

      const lineSeen = new Set()
      for (const d of f.drivers) {
        if (!d.pos || d.status.key === 'off') continue
        for (const c of d.held) {
          if (c.lat == null) continue
          const lk = `${d.id}:${c.id}`
          lineSeen.add(lk)
          const style = { color: d.held.length >= 2 ? STACK(d.held.length) : verdictColour(cb.current.verdictById[c.id]), weight: 2, opacity: 0.8, dashArray: '5 5' }
          const ll = [[d.pos.lat, d.pos.lon], [c.lat, c.lon]]
          const line = lines.get(lk)
          if (line) line.setLatLngs(ll).setStyle(style)
          else lines.set(lk, L.polyline(ll, { ...style, interactive: false, className: 'rp-march' }).addTo(root))
        }
      }
      for (const [k, line] of lines) if (!lineSeen.has(k)) { line.remove(); lines.delete(k) }
      const track = replay.drivers.find(d => d.id === g.current?.sel)?.track
      trail.setLatLngs(track ? trailUntil(track, t) : [])
    }
    g.current = { sel: g.current?.sel, selSa: g.current?.selSa, drivers, pins, run }
    run(engine.ref.current.t)
    const off = engine.subscribe(run)
    return () => { off(); root.remove(); g.current = null }
  }, [map, replay, engine, dayDrivers, sasById])

  useEffect(() => {   // selection changes restyle the existing markers; the next frame draws the rest
    const s = g.current
    if (!s) return
    s.sel = selectedDriver; s.selSa = selectedSa
    for (const [id, it] of s.drivers) it.el?.classList.toggle('selected', id === selectedDriver)
    s.pins.forEach(p => { p.state = '' })
    s.run(engine.ref.current.t)
  }, [selectedDriver, selectedSa, engine, map, replay])

  return <div ref={ref} className="w-full h-full rounded-xl overflow-hidden" />
}
