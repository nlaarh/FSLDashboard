import { useEffect, useMemo, useRef } from 'react'
import L from 'leaflet'
import useLeafletMap from '../replay/useLeafletMap'
import useReplayEngine, { prefersReducedMotion } from '../replay/useReplayEngine'
import { truckHtml, truckKindFor, garageHtml, memberHtml } from '../replay/gameIcons'
import { shortDriverName } from '../../utils/driverName'
import { fetchGarageRoad } from '../../api'
import { pinState, toS } from '../callmap/callMapModel'
import { fmtWait } from '../woreplay/woReplayModel'
import { driverTip, ticketTip } from './liveTips'
import { DRIVER_STATUS, REFRESH_MS, minutesSince, turn } from './garageLiveModel'
import { TRAIL_S, createRoadFetcher, legPath, moveKind, stitch } from './glideRoute'

const icon = (html, w, h, dx = 0, dy = 0) => L.divIcon({ className: '', html, iconSize: [w, h], iconAnchor: [w / 2 - dx, h / 2 - dy] })
const nowS = () => Date.now() / 1000
const LEG_S = REFRESH_MS / 1000 - 3              // a drive lasts one refresh interval (less a margin), so motion is continuous at constant speed
const PULSE_MS = 3000
const tag = (d, now) => {
  const m = d.status_since ? minutesSince(d.status_since, now) : null
  return `${DRIVER_STATUS[d.status].short}${m != null && d.status !== 'free' ? ` ${m}m` : ''}`
}
const pulse = el => { if (!el) return; el.classList.remove('glive-pulse'); void el.offsetWidth; el.classList.add('glive-pulse'); setTimeout(() => el.classList.remove('glive-pulse'), PULSE_MS) }
const TIP = { className: 'cm-tip-wrap', direction: 'top', offset: [0, -26], opacity: 1 }

/**
 * The garage's map: the garage, one pin per open ticket (colour by lateness, wait clock ticking), one truck per driver on shift.
 * Motion uses Replay's own clock (useReplayEngine, 60 fps) and path maths (roadPath): when a refresh moves a truck, it drives the ROAD from
 * where it is drawn to its new position (street route from the same OSRM service Replay uses, fetched once per move and cached), at constant
 * speed over the refresh interval, turning with the road, with a fading trail. No road (OSRM down) or a long jump: a straight line.
 * Markers are created once and moved straight on the Leaflet layer, never re-rendered by React.
 */
export default function GarageLiveMap({ data, focus, canReplay, onReplay }) {
  const [ref, map] = useLeafletMap([data.garage.lat ?? 42.9, data.garage.lon ?? -78.8])
  const st = useRef({ root: null, tickets: new Map(), drivers: new Map(), garageId: null, fitted: null })
  const latest = useRef({})
  latest.current = { canReplay, onReplay }
  const t0 = useMemo(() => nowS(), [])
  const engine = useReplayEngine({ start: t0, end: t0 + 1e7, initial: t0, speed: 1, busy: () => true, keys: false })
  const roads = useMemo(() => createRoadFetcher((a, b) => fetchGarageRoad(a, b)), [])

  useEffect(() => {                                           // layers belong to the map: created with it, dropped with it
    if (!map) return undefined
    const s = st.current
    s.root = L.layerGroup().addTo(map)
    return () => { s.root.remove(); Object.assign(s, { root: null, tickets: new Map(), drivers: new Map(), garageId: null, fitted: null }) }
  }, [map])

  useEffect(() => { engine.play(); return () => engine.pause() }, [engine])

  useEffect(() => {                                           // the Replay clock moves every driving truck, every frame
    const clearTrail = it => { it.trail?.forEach(l => l.setLatLngs([])); it.trailOn = false }
    let lastTrail = 0
    return engine.subscribe(t => {
      const wall = performance.now(), trailDue = wall - lastTrail >= 100
      if (trailDue) lastTrail = wall
      for (const it of st.current.drivers.values()) {
        const leg = it.leg
        if (!leg) continue
        const end = t >= leg.t1
        const pos = leg.path.at(Math.min(t, leg.t1))
        if (pos) {
          it.cur = [pos.lat, pos.lon]
          it.mk.setLatLng(it.cur)
          if (pos.heading != null && (it.lastH == null || Math.abs(turn(it.lastH, pos.heading)) > 2)) {   // keep the last heading when parked; take the short way round
            it.rot = it.rot == null ? pos.heading : it.rot + turn(it.rot % 360, pos.heading)
            it.lastH = pos.heading
            it.el?.querySelector('.hdg')?.style.setProperty('transform', `rotate(${it.rot.toFixed(1)}deg)`)
          }
        }
        if (trailDue) {                                       // three fading pieces of the last TRAIL_S seconds of road
          if (!it.trail) it.trail = [0.85, 0.5, 0.2].map(o => L.polyline([], { interactive: false, weight: 5, opacity: o, lineCap: 'round', color: '#38bdf8' }).addTo(st.current.root))
          const ts = Math.min(t, leg.t1), q = TRAIL_S / 3
          it.trail[0].setLatLngs(leg.path.behind(ts, q)); it.trail[1].setLatLngs(leg.path.behind(ts - q, q)); it.trail[2].setLatLngs(leg.path.behind(ts - 2 * q, q))
          it.trailOn = true
        }
        if (end) { it.cur = leg.to; it.mk.setLatLng(leg.to); it.leg = null; setTimeout(() => clearTrail(it), 4000) }
      }
    })
  }, [engine])

  useEffect(() => {                                           // the Replay button inside a ticket card
    const el = ref.current
    const onClick = e => { const b = e.target.closest?.('[data-replay]'); if (b) latest.current.onReplay?.(b.dataset.replay) }
    el?.addEventListener('click', onClick)
    return () => el?.removeEventListener('click', onClick)
  }, [ref])

  useEffect(() => {                                           // every refresh: sync tickets, trucks and the garage with the new data
    const s = st.current
    if (!map || !s.root) return
    const { garage, tickets, drivers } = data
    if (s.garageId !== garage.id) {
      s.root.clearLayers(); s.tickets.clear(); s.drivers.clear(); s.fitted = null; s.garageId = garage.id
      if (garage.lat != null) L.marker([garage.lat, garage.lon], { interactive: false, keyboard: false, zIndexOffset: -500, icon: icon(garageHtml((garage.name || '').replace(/^\w+\s+-\s+/, '')), 46, 42) }).addTo(s.root)
    }

    const tNow = s.tickets
    const seenT = new Set()
    for (const t of tickets) {
      if (t.lat == null) continue
      seenT.add(t.sa_id)
      let it = tNow.get(t.sa_id)
      if (!it) {
        const mk = L.marker([t.lat, t.lon], { keyboard: false, zIndexOffset: 500, icon: icon(memberHtml({ number: t.number }), 56, 56) }).addTo(s.root)
        it = { mk, t, el: mk.getElement()?.firstElementChild, wait: null, key: '' }
        it.wait = it.el?.querySelector('.wait')
        mk.bindTooltip(() => ticketTip(it.t, nowS(), false), TIP).bindPopup(() => ticketTip(it.t, nowS(), latest.current.canReplay), { className: 'cm-tip-wrap', closeButton: false, offset: [0, -20] })
        mk.on('popupopen', () => mk.closeTooltip())
        tNow.set(t.sa_id, it)
      }
      it.t = t
    }
    for (const [id, it] of tNow) if (!seenT.has(id)) { s.root.removeLayer(it.mk); tNow.delete(id) }

    const now = nowS(), dNow = s.drivers
    const seenD = new Set()
    for (const d of drivers) {
      if (d.lat == null) continue
      seenD.add(d.id)
      const to = [d.lat, d.lon], base = truckKindFor({ truck: d.truck, skills: d.caps, service: d.job?.work_type })
      const aside = d.status === 'on_scene'                      // a truck on scene is drawn beside the call's pin, so both can be hovered and clicked
      const kind = `${base}${aside ? '|aside' : ''}`
      let it = dNow.get(d.id)
      let changed = false                                        // a new status (arrived on scene, started towing...) pulses once
      if (it && it.kind !== kind) { changed = it.d.status !== d.status; s.root.removeLayer(it.mk); it.trail?.forEach(l => l.remove()); dNow.delete(d.id); it = null }
      if (!it) {
        const mk = L.marker(to, { keyboard: false, zIndexOffset: 1000, icon: icon(truckHtml({ name: shortDriverName(d.name), garage: tag(d, now), kind: base }), 60, 60, aside ? 44 : 0, aside ? 8 : 0) }).addTo(s.root)
        it = { mk, d, kind, el: mk.getElement()?.firstElementChild, cur: to, leg: null, rot: null, lastH: null, token: 0, trail: null }
        mk.bindTooltip(() => driverTip(it.d, nowS()), TIP).bindPopup(() => driverTip(it.d, nowS()), { className: 'cm-tip-wrap', closeButton: false, offset: [0, -20] })
        mk.on('popupopen', () => mk.closeTooltip())
        dNow.set(d.id, it)
        if (changed) pulse(it.el)
      } else {
        if (it.d.status !== d.status) pulse(it.el)
        const kindOfMove = moveKind(it.cur, to)
        const tok = ++it.token
        const drive = (coords, waited) => {
          const t = engine.ref.current.t
          it.leg = { path: legPath(coords, t, t + Math.max(8, LEG_S - waited)), t1: t + Math.max(8, LEG_S - waited), to }
        }
        if (kindOfMove === 'still' || prefersReducedMotion()) { it.leg = null; it.cur = to; it.mk.setLatLng(to) }
        else if (kindOfMove === 'line') drive([it.cur, to], 0)
        else {
          const from = it.cur, asked = performance.now()
          roads.get(from, to).then(road => { if (tok === it.token && dNow.get(d.id) === it) drive(stitch(road, from, to), (performance.now() - asked) / 1000) })
        }
      }
      it.d = d
      const span = it.el?.querySelector('.rp-tag span')
      if (span) span.textContent = tag(d, now)
      if (it.el) {
        it.el.style.setProperty('--c', DRIVER_STATUS[d.status].colour)
        it.el.classList.toggle('live', d.status === 'driving' || d.status === 'towing')
        it.el.style.opacity = (d.gps_age_min ?? 0) >= 30 ? 0.55 : 1
        it.trail?.forEach(l => l.setStyle({ color: DRIVER_STATUS[d.status].colour }))
      }
    }
    for (const [id, it] of dNow) if (!seenD.has(id)) { s.root.removeLayer(it.mk); it.trail?.forEach(l => l.remove()); dNow.delete(id) }

    if (s.fitted !== garage.id) {                              // frame everything once per garage; later refreshes never move the view
      const pts = [...s.tickets.values()].map(i => i.mk.getLatLng()).concat([...s.drivers.values()].map(i => i.mk.getLatLng()))
      if (garage.lat != null) pts.push(L.latLng(garage.lat, garage.lon))
      if (pts.length > 1) map.fitBounds(L.latLngBounds(pts), { padding: [70, 70], maxZoom: 13, animate: false })
      else if (pts.length) map.setView(pts[0], 12, { animate: false })
      s.fitted = garage.id
    }
  }, [map, data, engine, roads])

  useEffect(() => {                                           // the member pins: colour and wait clock, written straight to the DOM once a second
    const paint = () => {
      const t = nowS()
      for (const it of st.current.tickets.values()) {
        const p = pinState({ sa: it.t }, t, it.t.on_scene_at ? toS(it.t.on_scene_at) : null)
        const key = `${p.level}${p.state}`
        if (key !== it.key && it.el) { it.key = key; it.el.className = `rp-member cm ${p.level}` }
        if (it.wait) it.wait.textContent = `${fmtWait(p.secs)}${p.lateMin ? ` · +${p.lateMin} min` : p.state === 'done' ? ' · arrived' : ''}`
      }
    }
    paint()
    const id = setInterval(paint, 1000)
    return () => clearInterval(id)
  }, [map, data])

  useEffect(() => {                                           // a click in the drawer: fly there, open the card, glow for a few seconds
    if (!focus || !map) return undefined
    const it = (focus.type === 'driver' ? st.current.drivers : st.current.tickets).get(focus.id)
    if (!it) return undefined
    map.flyTo(it.mk.getLatLng(), Math.max(map.getZoom(), 14), { duration: 0.8 })
    it.mk.openPopup()
    it.el?.classList.add('glive-focus')
    const id = setTimeout(() => it.el?.classList.remove('glive-focus'), 5000)
    return () => { clearTimeout(id); it.el?.classList.remove('glive-focus') }
  }, [focus, map])

  return <div ref={ref} className="absolute inset-0" aria-label="Garage map" />
}
