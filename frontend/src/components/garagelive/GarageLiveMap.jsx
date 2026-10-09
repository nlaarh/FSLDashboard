import { useEffect, useRef } from 'react'
import L from 'leaflet'
import useLeafletMap from '../replay/useLeafletMap'
import { truckHtml, truckKindFor, garageHtml, memberHtml } from '../replay/gameIcons'
import { shortDriverName } from '../../utils/driverName'
import { pinState, toS } from '../callmap/callMapModel'
import { fmtWait } from '../woreplay/woReplayModel'
import { driverTip, ticketTip } from './liveTips'
import { DRIVER_STATUS, GLIDE_MS, STILL_MILES, bearing, glidePoint, milesBetween, minutesSince, turn } from './garageLiveModel'

const icon = (html, w, h, dx = 0, dy = 0) => L.divIcon({ className: '', html, iconSize: [w, h], iconAnchor: [w / 2 - dx, h / 2 - dy] })
const reduced = () => typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches
const nowS = () => Date.now() / 1000
const tag = (d, now) => {
  const m = d.status_since ? minutesSince(d.status_since, now) : null
  return `${DRIVER_STATUS[d.status].short}${m != null && d.status !== 'free' ? ` ${m}m` : ''}`
}
const TIP = { className: 'cm-tip-wrap', direction: 'top', offset: [0, -26], opacity: 1 }

/**
 * The garage's map: the garage, one pin per open ticket (colour by lateness, wait clock ticking), one truck per driver on shift.
 * Every 60 s the data is replaced; each truck then GLIDES from where it was drawn to its new position over a few seconds (no jump), turning
 * toward where it is going. Markers are created once and moved straight on the Leaflet layer, never re-rendered by React.
 */
export default function GarageLiveMap({ data, focus, canReplay, onReplay }) {
  const [ref, map] = useLeafletMap([data.garage.lat ?? 42.9, data.garage.lon ?? -78.8])
  const st = useRef({ root: null, tickets: new Map(), drivers: new Map(), raf: 0, garageId: null, fitted: null })
  const latest = useRef({})
  latest.current = { canReplay, onReplay }

  useEffect(() => {                                           // layers belong to the map: created with it, dropped with it
    if (!map) return undefined
    const s = st.current
    s.root = L.layerGroup().addTo(map)
    return () => { cancelAnimationFrame(s.raf); s.root.remove(); Object.assign(s, { root: null, tickets: new Map(), drivers: new Map(), raf: 0, garageId: null, fitted: null }) }
  }, [map])

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
      if (it && it.kind !== kind) { s.root.removeLayer(it.mk); dNow.delete(d.id); it = null }
      if (!it) {
        const mk = L.marker(to, { keyboard: false, zIndexOffset: 1000, icon: icon(truckHtml({ name: shortDriverName(d.name), garage: tag(d, now), kind: base }), 60, 60, aside ? 44 : 0, aside ? 8 : 0) }).addTo(s.root)
        it = { mk, d, kind, el: mk.getElement()?.firstElementChild, cur: to, glide: null, rot: null }
        mk.bindTooltip(() => driverTip(it.d, nowS()), TIP).bindPopup(() => driverTip(it.d, nowS()), { className: 'cm-tip-wrap', closeButton: false, offset: [0, -20] })
        mk.on('popupopen', () => mk.closeTooltip())
        dNow.set(d.id, it)
      } else if (milesBetween(it.cur, to) >= STILL_MILES) {
        const h = bearing(it.cur, to)
        it.rot = it.rot == null ? h : it.rot + turn(it.rot % 360, h)
        it.el?.querySelector('.hdg')?.style.setProperty('transform', `rotate(${it.rot.toFixed(1)}deg)`)
        if (reduced()) { it.cur = to; it.mk.setLatLng(to) } else it.glide = { from: [...it.cur], to, start: performance.now() }
      }
      it.d = d
      const span = it.el?.querySelector('.rp-tag span')
      if (span) span.textContent = tag(d, now)
      if (it.el) {
        it.el.style.setProperty('--c', DRIVER_STATUS[d.status].colour)
        it.el.classList.toggle('live', d.status === 'driving' || d.status === 'towing')
        it.el.style.opacity = (d.gps_age_min ?? 0) >= 30 ? 0.55 : 1
      }
    }
    for (const [id, it] of dNow) if (!seenD.has(id)) { s.root.removeLayer(it.mk); dNow.delete(id) }

    if (s.fitted !== garage.id) {                              // frame everything once per garage; later refreshes never move the view
      const pts = [...s.tickets.values()].map(i => i.mk.getLatLng()).concat([...s.drivers.values()].map(i => i.mk.getLatLng()))
      if (garage.lat != null) pts.push(L.latLng(garage.lat, garage.lon))
      if (pts.length > 1) map.fitBounds(L.latLngBounds(pts), { padding: [70, 70], maxZoom: 13, animate: false })
      else if (pts.length) map.setView(pts[0], 12, { animate: false })
      s.fitted = garage.id
    }

    cancelAnimationFrame(s.raf)
    const step = () => {                                       // one loop moves every gliding truck until all have arrived
      const t = performance.now()
      let moving = false
      for (const it of dNow.values()) {
        if (!it.glide) continue
        const el = t - it.glide.start
        it.cur = glidePoint(it.glide.from, it.glide.to, el)
        it.mk.setLatLng(it.cur)
        if (el >= GLIDE_MS) { it.cur = it.glide.to; it.glide = null } else moving = true
      }
      s.raf = moving ? requestAnimationFrame(step) : 0
    }
    step()
  }, [map, data])

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
