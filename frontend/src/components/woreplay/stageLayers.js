import L from 'leaflet'
import { shortDriverName } from '../../utils/driverName'
import { truckHtml, garageHtml, memberHtml, markHtml, jobHtml, STATUS } from '../replay/gameIcons'
import { waitState, fmtWait } from './woReplayModel'

const icon = (html, w, h, ax = w / 2, ay = h / 2) => L.divIcon({ className: '', html, iconSize: [w, h], iconAnchor: [ax, ay] })
const diff = (a, b) => ((b - a + 540) % 360) - 180   // shortest signed turn from a to b, so a truck never spins the long way round
const ROUTE_EVERY_MS = 100

/**
 * Every Leaflet layer of the Work Order stage, created once and moved straight from the replay engine's frame (no React).
 * Markers are never re-created while playing: position by setLatLng, heading by one CSS rotate, status by one CSS variable.
 *
 * opts: { loc, header, trucks: [{ key, name, garage, kind, est, path }], actor(t) -> { name, phase }, wait: { created, promise, onScene },
 *         marks: [{ id, ts, type, title }], onMark(mark), jobs: [{ id, lat, lon, ahead }] }
 */
export function createStageLayers(map, opts) {
  const { loc, header, trucks, actor, wait, marks = [], onMark, jobs = [] } = opts
  const root = L.layerGroup().addTo(map)
  const own = { interactive: false, keyboard: false }
  const line = (o, cls) => L.polyline([], { interactive: false, lineCap: 'round', lineJoin: 'round', className: cls, ...o }).addTo(root)
  const glow = line({ weight: 11, opacity: 0.16, color: '#38bdf8' })
  const route = line({ weight: 4, opacity: 0.95, color: '#38bdf8', dashArray: '10 16' }, 'rp-march')
  const trail = [0.9, 0.5, 0.22].map(o => line({ weight: 5, opacity: o, color: '#38bdf8' }))

  let garagePt = null   // the garage tag's spot in layer pixels, so a truck's name never lands on top of it
  const placeGarage = () => { garagePt = loc?.garage ? map.latLngToLayerPoint([loc.garage.lat, loc.garage.lon]) : null }
  placeGarage(); map.on('zoomend', placeGarage)
  if (loc?.garage) L.marker([loc.garage.lat, loc.garage.lon], { ...own, zIndexOffset: -500, icon: icon(garageHtml(loc.garage.name.replace(/^\w+\s+-\s+/, '')), 46, 42) }).addTo(root)

  let member = null, waitEl = null, memberEl = null, memberState = '', waitText = ''
  if (loc?.wo) {
    member = L.marker([loc.wo.lat, loc.wo.lon], { ...own, zIndexOffset: 500, icon: icon(memberHtml({ number: header?.sa, vehicle: header?.vehicle }), 56, 56) }).addTo(root)
    memberEl = member.getElement()?.firstElementChild
    waitEl = memberEl?.querySelector('.wait')
  }

  jobs.filter(j => j.lat != null).forEach((j, n) => L.marker([j.lat, j.lon], { ...own, icon: icon(jobHtml(n + 1, j.ahead), 20, 20) }).addTo(root))
  const markItems = marks.map((m, n) => {
    const a = (-60 + n * 38) * Math.PI / 180, dx = Math.cos(a) * 46, dy = Math.sin(a) * 46    // fanned around the member pin
    const mk = L.marker(loc?.wo ? [loc.wo.lat, loc.wo.lon] : [0, 0], { keyboard: false, zIndexOffset: 800, title: m.title, icon: icon(markHtml(m.type), 26, 26, 13 - dx, 13 - dy) })
    if (loc?.wo) mk.addTo(root)
    mk.on('click', () => onMark?.(m))
    return { m, mk, on: false }
  })

  const items = trucks.map(tr => {
    const mk = L.marker([0, 0], { ...own, icon: icon(truckHtml({ ...tr, name: shortDriverName(tr.name) }), 60, 60) })
    return { tr, mk, shown: false, rot: null, key: '', st: 'idle', lastH: null, el: null }
  })

  const sizeIcons = () => map.getContainer().style.setProperty('--rp-s', Math.max(0.55, Math.min(1, 0.55 + (map.getZoom() - 10) * 0.09)).toFixed(2))
  sizeIcons()
  map.on('zoomend', sizeIcons)

  let lastRoute = -1e9, routeKey = ''
  function frame(t, playing = true) {
    const act = actor(t)
    let actingPos = null, actingItem = null
    for (const it of items) {
      const pos = it.tr.path.at(t)
      if (!pos) { if (it.shown) { root.removeLayer(it.mk); it.shown = false } continue }
      if (!it.shown) { it.mk.addTo(root); it.shown = true; it.el = it.mk.getElement()?.firstElementChild; it.rot = null; it.lastH = null; it.key = ''; it.above = false }
      it.mk.setLatLng([pos.lat, pos.lon])
      const isAct = it.tr.est || it.tr.name === act.name
      const moving = pos.heading != null && !pos.stale
      if (moving) {   // keep the last heading while stopped, so a parked truck does not snap back to north
        it.rot = it.rot == null ? pos.heading : it.rot + diff(it.rot % 360, pos.heading)
        if (it.lastH == null || Math.abs(diff(it.lastH, pos.heading)) > 2) { it.lastH = pos.heading; it.el?.querySelector('.hdg')?.style.setProperty('transform', `rotate(${it.rot.toFixed(1)}deg)`) }
      }
      const st = !isAct ? 'idle' : it.tr.est ? 'estimated' : act.phase === 'en_route' ? 'en_route'
        : act.phase === 'on_scene' ? (moving && /tow/i.test(header?.service || '') ? 'towing' : 'on_scene') : act.phase === 'done' ? 'idle' : 'assigned'
      const key = `${st}${moving && isAct ? '*' : ''}${isAct ? 'A' : ''}`
      if (key !== it.key && it.el) {
        it.key = key; it.st = st
        it.el.style.setProperty('--c', STATUS[st].colour)
        it.el.classList.toggle('live', moving && isAct)
        it.el.style.opacity = isAct ? 1 : 0.7
        it.mk.setZIndexOffset(isAct ? 1000 : 0)
      }
      if (garagePt && it.el) {   // the garage tag is ~110 px wide, 25-40 px under the garage; the truck tag is ~120 x 40, 50-90 px under the truck
        const q = map.latLngToLayerPoint([pos.lat, pos.lon]), clash = Math.abs(q.x - garagePt.x) < 115 && q.y < garagePt.y - 10 && q.y > garagePt.y - 65
        if (clash !== it.above) { it.above = clash; it.el.querySelector('.rp-tag')?.classList.toggle('above', clash) }
      }
      if (isAct && !actingItem) { actingItem = it; actingPos = pos }
    }

    // Route drawing ahead of the acting truck and a fading trail behind it: 10 times a second is plenty and keeps the frame cheap.
    const now = performance.now()
    if (!playing || now - lastRoute >= ROUTE_EVERY_MS) {
      lastRoute = now
      if (actingItem && actingPos) {
        const colour = STATUS[actingItem.st].colour
        const ahead = actingItem.tr.path.ahead(t, 1500)
        if (loc?.wo && ahead.length && act.phase !== 'on_scene') ahead.push([loc.wo.lat, loc.wo.lon])
        glow.setLatLngs(ahead); route.setLatLngs(ahead)
        const p = actingItem.tr.path
        trail[0].setLatLngs(p.behind(t, 150)); trail[1].setLatLngs(p.behind(t - 150, 300)); trail[2].setLatLngs(p.behind(t - 450, 750))
        if (colour !== routeKey) { routeKey = colour; [glow, route, ...trail].forEach(l => l.setStyle({ color: colour })) }
      } else { glow.setLatLngs([]); route.setLatLngs([]); trail.forEach(l => l.setLatLngs([])) }
    }

    if (memberEl) {
      const w = waitState(t, wait.created, wait.promise, wait.onScene)
      if (w.state !== memberState) { memberState = w.state; memberEl.className = `rp-member ${w.state}` }
      const text = `${fmtWait(w.secs)}${w.state === 'late' && w.over ? ` · +${w.over} min` : w.state === 'done' ? ' · arrived' : ''}`
      if (text !== waitText && waitEl) { waitText = text; waitEl.textContent = text }
    }
    for (const mi of markItems) {
      const on = t >= mi.m.ts
      if (on !== mi.on) { mi.on = on; mi.mk.getElement()?.firstElementChild?.classList.toggle('on', on) }
    }
    return { pos: actingPos, name: act.name }
  }

  return { frame, destroy() { map.off('zoomend', sizeIcons); map.off('zoomend', placeGarage); root.remove() } }
}
