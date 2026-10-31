import { useEffect, useRef } from 'react'
import L from 'leaflet'
import useLeafletMap, { esc } from '../replay/useLeafletMap'
import { buildPath } from '../replay/roadPath'
import { clockLabel } from '../replay/replayMath'
import { garageHtml, truckKindFor } from '../replay/gameIcons'
import flatbedPng from '../../assets/trucks/flatbed.png'
import wreckerPng from '../../assets/trucks/wrecker.png'
import servicePng from '../../assets/trucks/service.png'
import { shortDriverName } from '../../utils/driverName'
import { kindOf, glyph, stopState, doingAt, fmtDur, splitAtGaps, hopsUntil, HOP_M } from './driverModel'

const SLOW_MS = 66                 // trails, flags and timers redraw 15 times a second; the truck and the camera move every frame
// The follow camera frames the truck like a film shot: one steady zoom (owner: streets readable, never so close the map disappears,
// never so far that everything piles up), it glides after the truck, and while driving it aims LEAD of the screen ahead of the truck
// so you see where it is going. The zoom does not change by itself: every zoom change reloads the map tiles and the screen flashes
// blank (watched 2026-10-30); the user can still zoom, or press Whole day.
export const FOLLOW_ZOOM = 13   // owner 2026-10-30: 14 too close, show which part of town he is in
const CHASE = 4                    // how fast the camera catches up with its aim point (per second; higher = tighter)
const LEAD = 0.16
const FLAG_W = 44, FLAG_H = 96     // the stop badge stands on a tall pole so the parked truck never covers it
const TRUCK_PX = 96                // the truck marker box (square, centred on the GPS point); the picture inside turns with the heading
// Realistic top-down AAA truck pictures (made with OpenAI's image model, 2026-10-30), front pointing up. A picture turned with CSS
// runs smoothly on any PC and browser (no 3D graphics needed). bar = where the roof light bar is, as a share of the height from the front.
const TRUCKS = {
  flatbed: { src: flatbedPng, bar: 0.31 },
  wheel_lift: { src: wreckerPng, bar: 0.25 },
  light: { src: servicePng, bar: 0.27 },
}
const TURN = 10                    // how fast the truck turns to a new heading (per second): a corner is a turn, not a snap
const turnBy = (from, to) => ((to - from + 540) % 360) - 180
const truckHtml = (name, kind) => {
  const t = TRUCKS[kind] || TRUCKS.flatbed
  return `<div class="dr-img dr-truck"><div class="dr-ring"></div>
    <div class="dr-rot"><img src="${t.src}" alt="" draggable="false"><i class="dr-bar" style="top:${(t.bar * 100).toFixed(0)}%"></i></div>
    <div class="rp-tag"><b>${esc(name)}</b></div></div>`
}
const icon = (html, w, h, ax = w / 2, ay = h / 2) => L.divIcon({ className: '', html, iconSize: [w, h], iconAnchor: [ax, ay] })

function flagHtml(stop, colour) {
  const k = kindOf(stop.kind)
  return `<div class="dr-flag" style="--k:${k.colour};--c:${colour}">
    <div class="dr-halo"></div><div class="dr-pole"></div>
    <div class="dr-badge">${glyph(stop.kind, 17)}</div>
    <div class="dr-ftag"><b>${esc(stop.label)}</b><span class="dr-time"></span></div></div>`
}

const flagTip = s => `<b>${esc(s.label)}</b>${s.place_kind ? `<br>${esc(s.place_kind)}` : ''}<br>${clockLabel(s.t0)} – ${clockLabel(s.t1)} · ${fmtDur(s.t1 - s.t0)}`

/**
 * The Driver Replay map. One truck per picked driver in that driver's colour, the road it has covered as a glowing line (gold for
 * the first driver), the rest of its day as a faint dashed line, and a flag at every stop: it pops up when the truck arrives,
 * counts the minutes while it is parked and keeps the total after it leaves. Layers move themselves on the replay engine's
 * frames, so React does not render while it plays.
 * view: 'follow' = a game-style chase camera keeps the first truck centred at street level; 'day' = the whole day's route;
 * 'free' = the user moved the map (dragging it calls onViewChange('free')). Only the stop the truck is at shows a full badge;
 * stops it has left shrink to a small dot (hover for details); stops ahead are hidden.
 */
export default function DriverReplayMap({ territory, drivers, engine, view = 'follow', onViewChange, onPickStop }) {
  const [ref, map] = useLeafletMap([territory.lat, territory.lon])
  const cb = useRef({}); cb.current = { onPickStop, view, onViewChange }
  const g = useRef(null)

  useEffect(() => {
    if (!map) return undefined
    const root = L.layerGroup().addTo(map)
    if (territory.lat != null) {
      L.marker([territory.lat, territory.lon], { interactive: false, keyboard: false, zIndexOffset: -500, icon: icon(garageHtml((territory.name || 'Garage').replace(/^\w+\s+-\s+/, '')), 46, 42) }).addTo(root)
    }

    const items = drivers.map(d => {
      const path = buildPath(d.track, null)
      // where two GPS points are far apart the road is unknown: a thin dotted line, never a solid trail across fields or water
      const hops = L.polyline([], { color: d.colour, weight: 2, opacity: 0.7, dashArray: '1 6', interactive: false, lineCap: 'round' }).addTo(root)
      const glow = L.polyline([], { color: d.colour, weight: 12, opacity: 0.22, interactive: false, lineCap: 'round', lineJoin: 'round' }).addTo(root)
      const core = L.polyline([], { color: d.colour, weight: 4.5, opacity: 0.95, interactive: false, lineCap: 'round', lineJoin: 'round', className: 'dr-core' }).addTo(root)
      const flags = d.stops.map(s => {
        const mk = L.marker([s.lat, s.lon], { icon: icon(flagHtml(s, d.colour), FLAG_W, FLAG_H, FLAG_W / 2, FLAG_H), zIndexOffset: 400 })
          .on('click', () => cb.current.onPickStop?.(d.id, s))
        mk.bindTooltip(flagTip(s), { direction: 'top', offset: [0, -14] })
        return { s, mk, el: null, time: null, state: 'hidden' }
      })
      // the truck: the AAA truck picture for what they drove, turned to the real heading, the driver's name under it
      const truck = L.marker([d.track[0][1], d.track[0][2]], {
        zIndexOffset: 1000, interactive: false,
        icon: icon(truckHtml(shortDriverName(d.name), truckKindFor({ truck: d.truck, skills: d.skills })), TRUCK_PX, TRUCK_PX),
      }).addTo(root)
      const el = truck.getElement()?.firstElementChild
      el?.style.setProperty('--c', d.colour)
      return { d, path, hops, glow, core, flags, truck, el, rot: el?.querySelector('.dr-rot'), yaw: null, state: '', hopN: -1 }
    })

    let slowAt = 0, camAt = 0, frameAt = 0, lead = 0
    // follow camera, run every frame: aim a little ahead of the truck and glide there; a seek far away cuts straight to it
    const chase = () => {
      if (cb.current.view !== 'follow' || !items.length || map._animatingZoom) { camAt = 0; return }
      const now = performance.now(), dt = camAt ? Math.min((now - camAt) / 1000, 0.1) : 0
      camAt = now
      const it = items[0], ll = it.truck.getLatLng(), z = map.getZoom()
      if (engine.ref.current.playing && dt > 0) lead += ((it.state === 'driving' ? LEAD : 0) - lead) * (1 - Math.exp(-1.5 * dt))
      const size = map.getSize(), r = ((it.yaw ?? 0) * Math.PI) / 180
      const tp = map.latLngToContainerPoint(ll).add([Math.sin(r) * lead * size.y, -Math.cos(r) * lead * size.y])
      const target = map.containerPointToLatLng(tp), c = map.getCenter()
      if (!dt || tp.distanceTo(map.latLngToContainerPoint(c)) > Math.min(size.x, size.y) * 0.6) { map.setView(target, z, { animate: false }); return }
      const k = 1 - Math.exp(-CHASE * dt)
      map.setView([c.lat + (target.lat - c.lat) * k, c.lng + (target.lng - c.lng) * k], z, { animate: false })
    }
    const run = t => {
      const now = performance.now(), dt = frameAt ? Math.min((now - frameAt) / 1000, 0.1) : 0
      frameAt = now
      const slow = !engine.ref.current.playing || now - slowAt >= SLOW_MS
      for (const it of items) {
        const pos = it.path.at(Math.min(Math.max(t, it.d.track[0][0]), it.d.track[it.d.track.length - 1][0]))
        if (!pos) continue
        it.truck.setLatLng([pos.lat, pos.lon])
        // turn to the real heading, smoothly; parked or no signal keeps the last heading
        const h = pos.stale === 0 ? pos.heading : null
        if (h != null) {
          it.yaw = it.yaw == null ? h : it.yaw + turnBy(it.yaw, h) * (1 - Math.exp(-TURN * (engine.ref.current.playing ? dt : 1)))
          it.rot?.style.setProperty('transform', `rotate(${it.yaw.toFixed(1)}deg)`)
        }
        if (!slow) continue
        const doing = doingAt(it.d, t).state
        if (doing !== it.state && it.el) {
          it.state = doing
          it.el.classList.toggle('live', doing === 'driving')
          it.el.classList.toggle('parked', doing === 'stopped')
          it.el.style.opacity = doing === 'no_signal' || doing === 'before' || doing === 'after' ? 0.45 : 1
        }
        const covered = splitAtGaps(it.d.track, t, pos, HOP_M)
        it.core.setLatLngs(covered)
        it.glow.setLatLngs(covered)
        const hop = hopsUntil(it.d.track, t)
        if (hop.length !== it.hopN) { it.hopN = hop.length; it.hops.setLatLngs(hop) }
        for (const f of it.flags) {
          const st = stopState(f.s, t)
          if (st !== f.state) {
            if (f.state === 'hidden') { f.mk.addTo(root); f.el = f.mk.getElement()?.firstElementChild; f.time = f.el?.querySelector('.dr-time') }
            if (st === 'hidden') f.mk.remove()
            else { f.el?.classList.toggle('live', st === 'live'); f.el?.classList.toggle('done', st === 'done') }
            f.mk.setZIndexOffset(st === 'live' ? 2000 : 300)   // the stop the truck is at sits above everything
            f.state = st
          }
          if (f.time && st !== 'hidden') f.time.textContent = st === 'live' ? `since ${clockLabel(f.s.t0)} · ${fmtDur(t - f.s.t0)}` : fmtDur(f.s.t1 - f.s.t0)
        }
      }
      chase()
      if (!slow) return
      slowAt = performance.now()
    }
    run(engine.ref.current.t)
    const all = drivers.flatMap(d => d.track.map(p => [p[1], p[2]]))
    const showDay = animate => all.length && map.fitBounds(L.latLngBounds(all), { padding: [50, 50], maxZoom: 13, animate })
    const showTruck = animate => items.length && (animate
      ? map.flyTo(items[0].truck.getLatLng(), Math.max(map.getZoom(), FOLLOW_ZOOM), { duration: 0.8 })
      : map.setView(items[0].truck.getLatLng(), FOLLOW_ZOOM, { animate: false }))
    if (cb.current.view === 'day') showDay(false); else showTruck(false)
    const onDrag = () => cb.current.view !== 'free' && cb.current.onViewChange?.('free')
    map.on('dragstart', onDrag)
    map.getContainer().addEventListener('wheel', onDrag, { passive: true })   // the user zooming takes the camera too
    g.current = { showDay, showTruck, resetCam: () => { camAt = 0 } }
    const off = engine.subscribe(run)
    return () => { off(); map.off('dragstart', onDrag); map.getContainer().removeEventListener('wheel', onDrag); root.remove(); g.current = null }
  }, [map, drivers, engine, territory])

  // the view buttons: 'day' zooms out to the whole route, 'follow' flies back to the truck and the chase camera takes over
  const first = useRef(true)
  useEffect(() => {
    if (first.current) { first.current = false; return }
    if (view === 'day') g.current?.showDay(true)
    if (view === 'follow') { g.current?.showTruck(true); g.current?.resetCam() }
  }, [view])

  return <div ref={ref} className="w-full h-full rounded-xl overflow-hidden" />
}
