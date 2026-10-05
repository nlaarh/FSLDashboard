import { useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import { iconFor } from './explainIcons'
import { Play, Pause, SkipBack, SkipForward, ChevronLeft, ChevronRight, ListOrdered, Maximize2, Minimize2 } from 'lucide-react'
import useLeafletMap, { esc } from '../replay/useLeafletMap'
import { positionAt, trailUntil } from '../replay/replayMath'
import useStepClock, { SPEEDS } from './useStepClock'
import { KINDS, HUD, DRAWER_W, STEP_S, LEAD_S, TRAVEL, NODE_ORDER, NODE_INFO, isSlot, slotX, buildTimeline, stepAt, realTimeAt, hudState, miles, towbookTrack } from './woReplayModel'

const TRUCK = c => `<svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2"/><path d="M15 18H9"/><path d="M19 18h2a1 1 0 0 0 1-1v-3.65a1 1 0 0 0-.22-.624l-3.48-4.35A1 1 0 0 0 17.52 8H14"/><circle cx="17" cy="18" r="2"/><circle cx="7" cy="18" r="2"/></svg>`
const PILL = 'position:absolute;left:50%;transform:translateX(-50%);white-space:nowrap;background:#0f172af2;color:#fff;border-radius:8px;padding:3px 10px;font:700 13px system-ui'
const truckHtml = (name, active, est, heading, sc = 1) => {
  const c = est ? '#ea580c' : active ? '#059669' : '#94a3b8'
  const arrow = heading == null || !(active || est) ? '' : `<div style="position:absolute;left:50%;top:50%;width:0;height:0;transform:translate(-50%,-50%) rotate(${heading}deg) translateY(-${Math.round(44 * sc)}px);border-left:9px solid transparent;border-right:9px solid transparent;border-bottom:15px solid ${c}"></div>`
  const W = Math.round(60 * sc)
  return `<div style="position:relative;width:${W}px;height:${W}px;opacity:${active || est ? 1 : 0.7}">
    ${arrow}
    <div style="width:${W}px;height:${W}px;border-radius:${Math.round(18 * sc)}px;background:#fff;display:flex;align-items:center;justify-content:center;border:${sc < 0.8 ? 3 : 4}px ${est ? 'dashed' : 'solid'} ${c};
      box-shadow:${active || est ? `0 0 0 6px ${c}33,0 6px 14px rgba(0,0,0,.4)` : '0 3px 8px rgba(0,0,0,.3)'}">${TRUCK(c)}</div>
    <div style="${PILL};top:66px;${active || est ? '' : 'background:#475569e6;font-weight:600;font-size:12px'}">${esc(name)}${est ? ' · estimated' : ''}</div>
  </div>`
}
const customerHtml = (sc = 1) => { const W = Math.round(60 * sc); return `<div style="position:relative;width:${W}px;height:${W}px"><div style="position:absolute;inset:0;border-radius:50%;background:#ec489944"></div>
  <div style="position:absolute;inset:${Math.round(12 * sc)}px;border-radius:50%;background:#ec4899;border:${sc < 0.8 ? 3 : 4}px solid #fff;box-shadow:0 3px 10px rgba(0,0,0,.45)"></div>
  <div style="${PILL};top:${W + 6}px">Customer</div></div>` }
const garageHtml = (name, sc = 1) => { const W = Math.round(44 * sc); return `<div style="position:relative;width:${W}px;height:${W}px"><div style="width:${W}px;height:${W}px;border-radius:10px;background:#6366f1;border:${sc < 0.8 ? 3 : 4}px solid #e0e7ff;box-shadow:0 0 0 6px rgba(99,102,241,.3),0 4px 10px rgba(0,0,0,.35)"></div>
  <div style="${PILL};top:${W + 6}px;background:#fff;color:#0f172a;box-shadow:0 2px 8px rgba(0,0,0,.25)">${esc(name)}</div></div>` }
const fmtDelta = s => (s < 60 ? `${s} s` : s < 3600 ? `${Math.floor(s / 60)} min ${s % 60 ? `${s % 60} s` : ''}`.trim() : `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min`)
const etClock = sec => new Date(sec * 1000).toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit', second: '2-digit' })
const ease = x => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2)

/** A hop between two channel spheres: an arc above the row, so it never slides across the spheres in between. */
function arcPts(a, b, n = 26) {
  const y0 = a.y - 19, h = Math.min(30, 12 + Math.abs(b.x - a.x) * 0.035), cx = (a.x + b.x) / 2, cy = y0 - 2 * h
  return Array.from({ length: n + 1 }, (_, k) => { const t = k / n; return { x: (1 - t) * (1 - t) * a.x + 2 * (1 - t) * t * cx + t * t * b.x, y: (1 - t) * (1 - t) * y0 + 2 * (1 - t) * t * cy + t * t * (b.y - 19) } })
}

function along(pts, t) {
  if (pts.length === 1) return pts[0]
  const lens = pts.slice(1).map((b, k) => Math.hypot(b.x - pts[k].x, b.y - pts[k].y))
  let d = t * lens.reduce((a, b) => a + b, 0)
  for (let k = 0; k < lens.length; k++) {
    if (d <= lens[k] || k === lens.length - 1) { const f = lens[k] ? Math.min(1, d / lens[k]) : 1; return { x: pts[k].x + (pts[k + 1].x - pts[k].x) * f, y: pts[k].y + (pts[k + 1].y - pts[k].y) * f } }
    d -= lens[k]
  }
  return pts[pts.length - 1]
}

/**
 * The Work Order Replay stage, in the style of the TowFlow simulation: a simple map is the stage. The vehicle drives
 * garage -> customer on it, and a command-center column over the map shows where the call was captured, the integration,
 * Salesforce and whoever touched it. Messages fly from that column to the vehicle, the garage and the customer's phone.
 */
export default function WoReplayStage({ steps, header, locations, jump }) {
  const loc = locations || null
  const [open, setOpen] = useState(() => { try { return localStorage.getItem('woReplayFlowOpen') === '1' } catch { return false } })
  const tracks = useMemo(() => {
    if (!loc) return []
    const out = loc.drivers.filter(d => d.track.length).map(d => ({ name: d.name, track: d.track, est: false }))
    const tb = towbookTrack(steps, loc.garage, loc.wo)
    if (tb.length) out.push({ name: `${loc.towbook?.driver || 'Towbook Driver'} 1`, track: tb, est: true })
    return out
  }, [loc, steps])
  // steps where the ACTING vehicle drives get more animation time (not other drivers who held the call earlier)
  const tl = useMemo(() => {
    const who = []; let cur = null
    steps.forEach(st => { if (st.names?.driver) cur = st.names.driver; who.push(cur) })
    return buildTimeline(steps, k => {
      if (k + 1 >= steps.length) return 0
      const a = Date.parse(steps[k].ts) / 1000, b = Date.parse(steps[k + 1].ts) / 1000
      return Math.max(0, ...tracks.filter(t => t.est || t.name === who[k]).map(t => { const p0 = positionAt(t.track, a), p1 = positionAt(t.track, b); return p0 && p1 ? miles(p0, p1) : 0 }))
    })
  }, [steps, tracks])
  const total = tl.total
  const clock = useStepClock(total)
  const { i, p, started, into, dur } = stepAt(clock.tau, tl)
  const step = started ? steps[i] : null
  const hud = hudState(steps, i, started)
  const realT = realTimeAt(clock.tau, steps, tl)
  const [ref, map] = useLeafletMap([42.9, -78.8], { light: true })
  const [, bump] = useState(0)
  const layers = useRef({})
  const [autoCam, setAutoCam] = useState(true)
  const [zoomBias, setZoomBias] = useState(0)          // the user's zoom ratio on top of the automatic framing, in zoom levels (2^bias x)
  const [sc, setSc] = useState(1)                      // icon scale: smaller icons when zoomed out, so they do not pile up
  useEffect(() => {
    if (!map) return undefined
    const f = () => setSc(Math.max(0.55, Math.min(1, +(0.55 + (map.getZoom() - 10) * 0.09).toFixed(2))))
    f(); map.on('zoomend', f)
    return () => map.off('zoomend', f)
  }, [map])
  const listRef = useRef(null)
  const bounds = useRef(null)
  const fsRef = useRef(null)
  const [isFs, setIsFs] = useState(false)
  useEffect(() => {
    const on = () => setIsFs(document.fullscreenElement === fsRef.current)
    document.addEventListener('fullscreenchange', on)
    return () => document.removeEventListener('fullscreenchange', on)
  }, [])
  const toggleFs = () => (document.fullscreenElement ? document.exitFullscreen() : fsRef.current?.requestFullscreen?.())
  useEffect(() => {   // the map re-measures whenever its box changes size (window, full screen, flow column)
    if (!map || !ref.current || typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver(() => { map.invalidateSize({ animate: false }); bump(v => v + 1) })
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [map]) // eslint-disable-line react-hooks/exhaustive-deps

  const [hold, setHold] = useState(false)
  const heldFor = useRef(-1)
  const hovering = useRef(false)
  const wasPlaying = useRef(false)
  useEffect(() => {   // the user's own zoom or drag takes the camera away from the animation until "Auto camera" is switched back on
    const el = ref.current
    if (!el) return undefined
    const off = e => { if (e.target.closest?.('.leaflet-control-zoom, .leaflet-container')) setAutoCam(false) }
    const wheel = () => setAutoCam(false)
    el.addEventListener('pointerdown', off); el.addEventListener('wheel', wheel, { passive: true }); el.addEventListener('dblclick', wheel)
    return () => { el.removeEventListener('pointerdown', off); el.removeEventListener('wheel', wheel); el.removeEventListener('dblclick', wheel) }
  }, [map]) // eslint-disable-line react-hooks/exhaustive-deps
  const autoStarted = useRef(false)
  useEffect(() => {   // start by itself once the map data is in (or known to be unavailable): nobody should have to find Play
    if (autoStarted.current || locations === undefined) return undefined
    autoStarted.current = true
    const t = setTimeout(() => clock.setPlaying(true), 700)
    return () => clearTimeout(t)
  }, [locations]) // eslint-disable-line react-hooks/exhaustive-deps
  const toggleDrawer = () => setOpen(o => { try { localStorage.setItem('woReplayFlowOpen', o ? '0' : '1') } catch { /* private window */ } return !o })

  const activeName = hud.names.driver
  const isActive = t => (t.est ? true : t.name === activeName)
  const activeTrack = tracks.find(t => isActive(t) && positionAt(t.track, realT)) || null
  const activePos = activeTrack && positionAt(activeTrack.track, realT)

  useEffect(() => {
    if (!map) return undefined
    const L0 = { root: L.layerGroup().addTo(map), markers: new Map(), trail: L.polyline([], { color: '#059669', weight: 7, opacity: 0.85 }), link: L.polyline([], { color: '#ec4899', weight: 4, dashArray: '8 9' }), ahead: L.polyline([], { color: '#64748b', weight: 5, opacity: 0.7, dashArray: '2 11', lineCap: 'round' }) }
    L0.ahead.addTo(L0.root); L0.trail.addTo(L0.root); L0.link.addTo(L0.root)
    if (loc?.garage) L0.garage = L.marker([loc.garage.lat, loc.garage.lon], { interactive: false, keyboard: false, zIndexOffset: -500, icon: L.divIcon({ className: '', iconSize: [44, 44], iconAnchor: [22, 22], html: garageHtml(loc.garage.name.replace(/^\w+\s+-\s+/, '')) }) }).addTo(L0.root)
    if (loc?.wo) L0.cust = L.marker([loc.wo.lat, loc.wo.lon], { interactive: false, keyboard: false, icon: L.divIcon({ className: '', iconSize: [60, 60], iconAnchor: [30, 30], html: customerHtml(1) }) }).addTo(L0.root)
    const pts = [loc?.wo, loc?.garage && loc.wo && miles(loc.garage, loc.wo) < 30 ? loc.garage : null].filter(Boolean).map(q => [q.lat, q.lon])
    bounds.current = pts.length > 1 ? L.latLngBounds(pts) : null
    if (pts.length > 1) map.fitBounds(L.latLngBounds(pts), { paddingTopLeft: [110, 172], paddingBottomRight: [110, 112], maxZoom: 15 })
    else if (pts.length) map.setView(pts[0], 13.5)
    const on = () => bump(n => n + 1)
    map.on('move zoom', on)
    layers.current = L0
    return () => { map.off('move zoom', on); L0.root.remove(); layers.current = {} }
  }, [map, loc, tracks])

  useEffect(() => {
    const L0 = layers.current
    if (!map || !L0.markers) return
    for (const t of tracks) {
      const pos = positionAt(t.track, realT)
      let m = L0.markers.get(t.name)
      if (!pos) { if (m) { m.remove(); L0.markers.delete(t.name) } continue }
      if (!m) { m = L.marker([pos.lat, pos.lon], { interactive: false, keyboard: false }).addTo(L0.root); L0.markers.set(t.name, m) }
      m.setLatLng([pos.lat, pos.lon]).setIcon(L.divIcon({ className: '', iconSize: [Math.round(60 * sc), Math.round(60 * sc)], iconAnchor: [Math.round(30 * sc), Math.round(30 * sc)], html: truckHtml(t.name, isActive(t), t.est, pos.heading, sc) }))
      m.setZIndexOffset(isActive(t) ? 1000 : 0)
    }
    if (activeTrack) { L0.trail.setLatLngs(trailUntil(activeTrack.track, realT)); L0.trail.setStyle({ dashArray: activeTrack.est ? '8 8' : null, color: activeTrack.est ? '#ea580c' : '#059669' }) } else L0.trail.setLatLngs([])
    L0.ahead.setLatLngs(activeTrack && activePos ? [[activePos.lat, activePos.lon], ...activeTrack.track.filter(q => q[0] > realT).slice(0, 120).map(q => [q[1], q[2]])] : [])
    L0.link.setLatLngs(activeTrack && activePos && loc?.wo ? [[activePos.lat, activePos.lon], [loc.wo.lat, loc.wo.lon]] : [])
    // never let the acting vehicle drift under the top bar, the caption or off the map: pan just enough to keep it in view
    if (activePos && autoCam) {
      const q = map.latLngToContainerPoint([activePos.lat, activePos.lon]), sz = map.getSize()
      if (q.x < 70 || q.x > sz.x - 70 || q.y < 150 || q.y > sz.y - 96) {
        map.panInside([activePos.lat, activePos.lon], { paddingTopLeft: [80, 160], paddingBottomRight: [80, 104], animate: false })
      }
    }
  }, [map, tracks, realT, activeName, sc]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!map) return undefined
    const z = ref.current?.querySelector('.leaflet-top.leaflet-right')
    if (z) z.style.marginTop = '108px'
    // the flow column opens beside the map (it never covers it): re-measure while it slides, then re-frame the action
    let n = 0
    const tick = setInterval(() => { map.invalidateSize({ animate: false }); bump(v => v + 1); if (++n > 12) clearInterval(tick) }, 30)
    const done = setTimeout(() => { map.invalidateSize({ animate: false }); if (bounds.current) map.fitBounds(bounds.current, { paddingTopLeft: [110, 172], paddingBottomRight: [110, 112], maxZoom: 15, animate: true }) }, 420)
    return () => { clearInterval(tick); clearTimeout(done) }
  }, [open, map]) // eslint-disable-line react-hooks/exhaustive-deps

  // Camera. At each step it frames what matters for THAT step: the customer, the vehicle that is acting (where it is at the start and
  // the end of the step) and, on a re-assignment, the driver it replaced. It zooms in as far as it can while those stay in view, so
  // they are clearly apart instead of piled up. The garage joins the frame only when the vehicle is near it. The user's zoom ratio
  // (the Zoom - / + buttons) is added on top. Other vehicles stay on the map but never force the camera wider.
  const frameTo = (animate) => {
    if (!map || !started || !loc?.wo || !steps[i]) return
    const at = k => Date.parse(steps[Math.min(k, steps.length - 1)].ts) / 1000
    const pts = [[loc.wo.lat, loc.wo.lon]]
    const prevDriver = step?.why ? [...steps.slice(0, i)].reverse().map(x => x.names?.driver).find(n => n && n !== hud.names.driver) : null
    let vehicle = false
    for (const t of tracks) {
      const acting = t.est || t.name === hud.names.driver
      if (!(acting || t.name === prevDriver)) continue
      for (const tm of acting ? [at(i), at(i + 1)] : [at(i)]) { const q = positionAt(t.track, tm); if (q) { pts.push([q.lat, q.lon]); vehicle = vehicle || acting } }
    }
    const nearGarage = loc.garage && (!vehicle || pts.slice(1).some(q => miles({ lat: q[0], lon: q[1] }, loc.garage) < 4))
    if (nearGarage && miles(loc.garage, loc.wo) < 60) pts.push([loc.garage.lat, loc.garage.lon])
    const bnds = L.latLngBounds(pts), tl_ = L.point(110, 172), br_ = L.point(110, 112)
    const tight = pts.length < 2 || bnds.getNorthEast().distanceTo(bnds.getSouthWest()) < 40     // everything on one spot: street level
    const fit = tight ? 16 : Math.min(map.getBoundsZoom(bnds, false, tl_.add(br_)), 17)
    const z = Math.max(8, Math.min(18, fit + zoomBias))
    const off = L.point((tl_.x - br_.x) / 2, (tl_.y - br_.y) / 2)          // the visible area sits between the top bar and the caption
    const centre = map.unproject(map.project(bnds.getCenter(), z).subtract(off), z)
    const sz = map.getSize()
    const outside = pts.some(q => { const c = map.latLngToContainerPoint(q); return c.x < tl_.x || c.x > sz.x - br_.x || c.y < tl_.y || c.y > sz.y - br_.y })
    // calm camera: move only when something would leave the view or the zoom is clearly off (or the user just changed the ratio)
    if (animate === 'force' || outside || Math.abs(z - map.getZoom()) > 0.6) map.flyTo(centre, z, { duration: 1.2 })
  }
  useEffect(() => { if (autoCam) frameTo() }, [map, i, started, loc, tracks, autoCam]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (autoCam) frameTo('force') }, [zoomBias]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const row = listRef.current?.querySelector(`[data-step="${i}"]`)
    if (row && open && started) listRef.current.scrollTo({ top: row.offsetTop - 120, behavior: 'smooth' })
  }, [i, open, started])

  const stageW = ref.current?.clientWidth || 1100
  useEffect(() => {
    const L0 = layers.current
    if (!map || !L0.root) return
    const w = Math.round(60 * sc), g = Math.round(44 * sc)
    L0.cust?.setIcon(L.divIcon({ className: '', iconSize: [w, w], iconAnchor: [w / 2, w / 2], html: customerHtml(sc) }))
    L0.garage?.setIcon(L.divIcon({ className: '', iconSize: [g, g], iconAnchor: [g / 2, g / 2], html: garageHtml(loc.garage.name.replace(/^\w+\s+-\s+/, ''), sc) }))
  }, [map, sc, loc, tracks]) // eslint-disable-line react-hooks/exhaustive-deps

  const toPx = q => { const c = map.latLngToContainerPoint([q.lat, q.lon]); return { x: c.x, y: c.y } }
  const pt = id => {
    if (isSlot(id)) return { x: slotX(id, stageW), y: HUD.y }
    if (!map) return null
    if (id === 'member') return loc?.wo ? toPx(loc.wo) : null
    if (id === 'garage') return loc?.garage ? toPx(loc.garage) : null
    if (id === 'driver') return activePos ? toPx(activePos) : loc?.garage ? toPx(loc.garage) : null
    return null
  }
  const ids = step ? [step.from, step.via, step.to].filter(Boolean) : []
  // The route of this step. A hop between two channel spheres is an arc over the row; a hop between the bar and the map
  // drops straight down from (or rises straight up to) the sphere, so nothing ever crosses a label or another channel.
  const path = []
  ids.forEach((id, k) => {
    const q = pt(id)
    if (!q) { path.push(null); return }
    const slot = isSlot(id), prev = ids[k - 1], next = ids[k + 1]
    if (slot && prev && !isSlot(prev)) path.push({ x: q.x, y: HUD.edgeY })
    if (slot && prev && isSlot(prev) && pt(prev)) path.push(...arcPts(pt(prev), q).slice(1))
    path.push(q)
    if (slot && next && !isSlot(next)) path.push({ x: q.x, y: HUD.edgeY })
  })
  // the hops the call has already made along the bar stay drawn, so the route taken so far is always visible
  const taken = []
  if (started) {
    const seen = new Set()
    steps.slice(0, i).forEach(sp => {
      const seq = [sp.from, sp.via, sp.to].filter(Boolean)
      for (let k = 1; k < seq.length; k++) {
        const key = `${seq[k - 1]}>${seq[k]}`
        if (isSlot(seq[k - 1]) && isSlot(seq[k]) && seq[k - 1] !== seq[k] && !seen.has(key)) { seen.add(key); taken.push({ key, kind: KINDS[sp.kind] || KINDS.system, pts: arcPts(pt(seq[k - 1]), pt(seq[k])) }) }
      }
    })
  }
  const hasPath = step && path.length > 1 && path.every(Boolean) && step.from !== step.to
  const pulse = hasPath ? along(path, ease(p)) : null
  const kind = KINDS[step?.kind] || KINDS.system
  const arrivedAt = step && p >= 1 ? pt(step.to) : null
  const t0 = steps.length ? Date.parse(steps[0].ts) / 1000 : 0
  const dueTs = steps.find(x => x.id === 'P1')?.ts
  const pastPromise = dueTs ? realT >= Date.parse(dueTs) / 1000 : false
  const STAGE_H_NOW = ref.current?.clientHeight || 640
  const cardAt = step ? (pulse && p < 1 ? pulse : pt(step.to)) : null
  const CARD_W = step?.why || step?.explain ? 310 : 270, CARD_H = Math.min(420, 150 + (step?.why ? 120 : 0) + (step?.explain ? 190 : 0))
  const corners = [
    { id: 'tl', x: 14, y: HUD.edgeY + 6 }, { id: 'tr', x: stageW - CARD_W - 84, y: HUD.edgeY + 6 },
    { id: 'bl', x: 14, y: STAGE_H_NOW - 76 - CARD_H }, { id: 'br', x: stageW - CARD_W - 84, y: STAGE_H_NOW - 76 - CARD_H },
  ]
  const action = [pt('member'), pt('garage'), pt('driver'), cardAt].filter(Boolean)
  const gap = c => Math.min(...action.map(q => Math.hypot(Math.max(c.x - q.x, 0, q.x - (c.x + CARD_W)), Math.max(c.y - q.y, 0, q.y - (c.y + CARD_H)))), 9999)
  const cornerRef = useRef('tr')
  const best = corners.reduce((a, c) => (gap(c) > gap(a) ? c : a), corners[0])
  const cur = corners.find(c => c.id === cornerRef.current) || best
  if (step && (gap(cur) < 50 && gap(best) > gap(cur) + 40)) cornerRef.current = best.id    // hysteresis: only move when clearly better
  const dock = corners.find(c => c.id === cornerRef.current) || best
  const cardX = dock.x, cardY = dock.y
  const readout = (() => {
    if (!loc) return locations === undefined ? 'Loading where the customer and drivers were…' : 'Locations are not available for this call.'
    if (!activeName && !activeTrack) return loc.towbook ? 'Towbook garage: Salesforce does not track where its driver is.' : 'No driver assigned at this moment.'
    if (activeTrack?.est) return `Towbook shows ${activeTrack.name} only by status. The vehicle on the map is estimated from the Towbook En Route and On Location times, not GPS.`
    if (activePos && loc.wo) return `${activeName} is ${miles(activePos, loc.wo).toFixed(1)} mi from the customer`
    if (activeName && !tracks.some(t => t.name === activeName)) return `${activeName}: no GPS pings while this call was open.`
    return `${activeName}: no GPS ping at this moment.`
  })()

  const channel = id => {
    const info = NODE_INFO[id], on = hud.touched.has(id), act = hud.active.has(id), lab = on && hud.labels[id] ? hud.labels[id] : info
    const x = slotX(id, stageW)
    return (
      <div key={id} style={{ opacity: on ? 1 : 0.4, transition: 'opacity .3s' }}>
        <div style={{ position: 'absolute', left: x - 18, top: HUD.y - 18, width: 36, height: 36, borderRadius: '50%',
          background: `radial-gradient(circle at 32% 28%, #ffffffcc 0, ${info.colour} 38%, #0f172a 130%)`,
          boxShadow: act ? `0 0 0 4px ${info.colour}66, 0 0 22px ${info.colour}` : '0 3px 8px rgba(0,0,0,.45)', transition: 'box-shadow .3s' }} />
        <div style={{ position: 'absolute', left: x - 55, top: HUD.y + 22, width: 110, textAlign: 'center', background: 'rgba(15,23,42,.82)', borderRadius: 7, padding: '1px 3px' }}>
          <div style={{ fontSize: 12.5, fontWeight: 700, color: '#fff', lineHeight: '15px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{lab.label}</div>
          <div style={{ fontSize: 10.5, color: '#94a3b8', lineHeight: '13px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{lab.sub}</div>
        </div>
      </div>
    )
  }
  const stepTo = k => { heldFor.current = -1; clock.setTau(LEAD_S + tl.starts[Math.min(steps.length - 1, Math.max(0, k))] + 0.01) }
  useEffect(() => {   // "Show it in the replay" from the takeaways: go to that step and stop, so the message can be read
    if (!jump?.n) return
    const k = steps.findIndex(x => x.id === jump.id)
    if (k >= 0) { clock.setPlaying(false); stepTo(k) }
  }, [jump?.n]) // eslint-disable-line react-hooks/exhaustive-deps
  const ARRIVED = STEP_S * TRAVEL + 0.3
  useEffect(() => {   // "Hold at each message": stop once the message has arrived, so it can be read; Play carries on through this step's drive
    if (hold && clock.playing && started && into >= ARRIVED && heldFor.current !== i) { heldFor.current = i; clock.setPlaying(false) }
  }, [into, hold, clock.playing, started, i]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div ref={fsRef} className="space-y-2" style={isFs ? { background: '#020617', padding: 12, height: '100vh', display: 'flex', flexDirection: 'column' } : undefined}>
      <div className="flex rounded-2xl overflow-hidden border border-slate-700/60" style={isFs ? { flex: 1, minHeight: 0 } : { height: 'clamp(540px, calc(100vh - 170px), 820px)' }}>
      <div className="relative flex-1 min-w-0" style={{ background: '#dbe4ee' }}>
        <div ref={ref} style={{ position: 'absolute', inset: 0 }} />

        <svg style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none', zIndex: 1050 }}>
          {taken.map(tk => <polyline key={tk.key} points={tk.pts.map(q => `${q.x},${q.y}`).join(' ')} fill="none" stroke={tk.kind.colour} strokeWidth="3.5" strokeLinecap="round" opacity="0.5" strokeDasharray={tk.kind.dash || undefined} />)}
          {hasPath && (
            <polyline points={path.map(q => `${q.x},${q.y}`).join(' ')} fill="none" stroke={kind.colour} strokeWidth="7" strokeLinejoin="round" strokeLinecap="round"
              strokeDasharray={kind.dash || undefined} opacity="0.9" />
          )}
          {arrivedAt && <circle cx={arrivedAt.x} cy={arrivedAt.y} r={28 + 18 * Math.min(1, (into - STEP_S * TRAVEL) / 1.2)} fill="none" stroke={kind.colour} strokeWidth="5" opacity="0.7" />}
          {hasPath && (() => {
            const e = path[path.length - 1], q = path.slice(0, -1).reverse().find(z => Math.hypot(z.x - e.x, z.y - e.y) > 8)
            if (!q) return null
            const ang = (Math.atan2(e.y - q.y, e.x - q.x) * 180) / Math.PI
            return <polygon points="0,0 -20,-10 -20,10" fill={kind.colour} transform={`translate(${e.x},${e.y}) rotate(${ang})`} opacity={p >= 0.97 ? 1 : 0.35} />
          })()}
          {pulse && <><circle cx={pulse.x} cy={pulse.y} r="26" fill={kind.colour} opacity="0.28" /><circle cx={pulse.x} cy={pulse.y} r="13" fill="#fff" stroke={kind.colour} strokeWidth="5" /></>}
        </svg>

        <div style={{ position: 'absolute', left: 10, right: 10, top: 10, height: HUD.h, borderRadius: 16, background: pastPromise ? 'rgba(127,29,29,.92)' : 'rgba(15,23,42,.9)', zIndex: 1040, pointerEvents: 'none',
          boxShadow: '0 4px 14px rgba(0,0,0,.3)', transition: 'background .4s' }} />
        <div style={{ position: 'absolute', left: 22, top: 30, zIndex: 1060, pointerEvents: 'none', color: '#fff', width: 200 }}>
          <div style={{ fontSize: 26, fontWeight: 800, fontVariantNumeric: 'tabular-nums', lineHeight: 1.05 }}>{etClock(Math.max(realT, t0))}</div>
          <div style={{ fontSize: 11.5, color: '#cbd5e1', marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>SA received {etClock(t0)}{pastPromise ? ' · promise passed' : ''}</div>
        </div>
        <div style={{ position: 'absolute', inset: 0, zIndex: 1060, pointerEvents: 'none' }}>
          {NODE_ORDER.map(channel)}
          {step?.flag && step.explain && (() => {
            const q = pt(step.to) || pt(step.from)
            if (!q) return null
            const BI = iconFor(step.explain.icon), grow = 1 + 0.1 * Math.sin(clock.tau * 6)
            return (
              <div style={{ position: 'absolute', left: q.x + 12, top: q.y - 54, width: 38, height: 38, borderRadius: '50%', background: step.flag.level === 'bad' ? '#e11d48' : '#d97706', color: '#fff',
                display: 'flex', alignItems: 'center', justifyContent: 'center', border: '3px solid #fff', boxShadow: '0 4px 14px rgba(0,0,0,.45)', transform: `scale(${grow})` }} title={step.explain.title}>
                <BI size={20} strokeWidth={2.4} />
              </div>)
          })()}
          {pulse && p < 1 && step && (
            <div style={{ position: 'absolute', left: pulse.x + 20, top: pulse.y - 36, padding: '3px 10px', borderRadius: 8, background: kind.colour, color: '#fff', fontSize: 12.5, fontWeight: 700, whiteSpace: 'nowrap', maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', boxShadow: '0 3px 10px rgba(0,0,0,.35)' }}>
              {step.title}
            </div>
          )}
          {cardAt && (
            <div onMouseEnter={() => { hovering.current = true; if (clock.playing) { wasPlaying.current = true; clock.setPlaying(false) } }}
              onMouseLeave={() => { hovering.current = false; if (wasPlaying.current) { wasPlaying.current = false; clock.setPlaying(true) } }}
              style={{ position: 'absolute', left: cardX, top: cardY, pointerEvents: 'auto', cursor: 'default', width: CARD_W, maxHeight: Math.max(220, STAGE_H_NOW - HUD.edgeY - 96), overflowY: 'auto', padding: '8px 12px', borderRadius: 12, background: 'rgba(15,23,42,.94)', color: '#e2e8f0',
              border: `2px solid ${step.flag ? '#f43f5e' : kind.colour}`, boxShadow: '0 8px 24px rgba(0,0,0,.4)' }}>
              <div style={{ fontSize: 10.5, letterSpacing: 1.5, textTransform: 'uppercase', fontWeight: 700, color: step.flag ? '#fda4af' : kind.colour }}>{etClock(Date.parse(step.ts) / 1000)} · {kind.label}{step.actor ? ` · ${step.actor}` : ''}</div>
              <div style={{ fontSize: 14, fontWeight: 700, color: '#fff', marginTop: 1 }}>{step.title}</div>
              {(step.content?.length ? step.content : []).map((l, k) => <div key={k} style={{ fontSize: 12, color: '#cbd5e1', marginTop: 1 }}>{l}</div>)}
              {step.flag && <div style={{ fontSize: 12.5, fontWeight: 700, color: '#fda4af', marginTop: 4 }}>{step.flag.text}</div>}
              {step.explain && (() => { const XI = iconFor(step.explain.icon); return (
                <div style={{ marginTop: 7, paddingTop: 6, borderTop: '1px solid #475569' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10.5, letterSpacing: 1.3, textTransform: 'uppercase', fontWeight: 700, color: '#fca5a5' }}><XI size={14} />Why this may have happened</div>
                  {step.explain.why.slice(0, 3).map((l, k) => <div key={k} style={{ fontSize: 12, color: l.startsWith('This call:') ? '#fde68a' : '#cbd5e1', marginTop: 3 }}>{l}</div>)}
                  {step.explain.check[0] && <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}><b style={{ color: '#cbd5e1' }}>Check:</b> {step.explain.check[0]}</div>}
                </div>) })()}
              {step.why && (
                <div style={{ marginTop: 7, paddingTop: 6, borderTop: '1px solid #475569' }}>
                  <div style={{ fontSize: 10.5, letterSpacing: 1.5, textTransform: 'uppercase', fontWeight: 700, color: '#fbbf24' }}>Why this driver</div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: '#fde68a', marginTop: 1 }}>{step.why.headline}</div>
                  {step.why.lines.map((l, k) => <div key={k} style={{ fontSize: 12, color: l.startsWith('Computed') ? '#fcd34d' : '#cbd5e1', marginTop: 2 }}>{l}</div>)}
                </div>
              )}
            </div>
          )}
        </div>

        {step && (
          <div style={{ position: 'absolute', left: 10, right: 10, bottom: 10, zIndex: 1060, padding: '8px 18px', borderRadius: 14, background: 'rgba(15,23,42,.92)', color: '#e2e8f0',
            border: `1px solid ${step.flag ? '#f43f5ecc' : kind.colour + '88'}`, display: 'flex', alignItems: 'center', gap: 18, pointerEvents: 'none' }}>
            <div style={{ fontSize: 22, fontWeight: 800, fontVariantNumeric: 'tabular-nums', color: '#fff', minWidth: 128 }}>{etClock(Date.parse(step.ts) / 1000)}</div>
            <div style={{ fontSize: 12, color: '#94a3b8', minWidth: 118 }}>{step.dt === 0 ? 'Call starts' : `${fmtDelta(step.dt)} into the call`}</div>
            <div style={{ flex: 1, minWidth: 0, fontSize: 16, fontWeight: 700, color: '#fff', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              <span style={{ fontSize: 10.5, letterSpacing: 1.4, textTransform: 'uppercase', color: kind.colour, marginRight: 10 }}>{kind.label}</span>{step.title}
              {step.flag && <span style={{ marginLeft: 10, padding: '1px 9px', borderRadius: 999, fontSize: 12, background: step.flag.level === 'bad' ? '#f43f5e33' : '#f59e0b33', color: step.flag.level === 'bad' ? '#fda4af' : '#fcd34d' }}>{step.flag.text}</span>}
            </div>
            {step.actor && <div style={{ textAlign: 'right', whiteSpace: 'nowrap' }}><span style={{ fontSize: 13.5, fontWeight: 600, color: '#fff' }}>{step.actor}</span><span style={{ fontSize: 12, color: kind.colour, marginLeft: 8 }}>{step.role}</span></div>}
            <div style={{ fontSize: 12, color: '#64748b', whiteSpace: 'nowrap' }}>{i + 1} / {steps.length}</div>
          </div>
        )}
        <button onClick={toggleDrawer} title={open ? 'Close the flow' : 'Open the flow'} aria-label={open ? 'Close the flow' : 'Open the flow'}
          style={{ position: 'absolute', right: 0, top: HUD.h + 112, width: 38, height: 64, borderRadius: '12px 0 0 12px', background: 'rgba(15,23,42,.94)', color: '#fff', border: 'none', zIndex: 1070,
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 2, cursor: 'pointer', boxShadow: '-3px 3px 10px rgba(0,0,0,.25)' }}>
          {open ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}<ListOrdered size={16} />
        </button>
        {!started && <div style={{ position: 'absolute', left: 24, top: HUD.h + 22, zIndex: 1060, padding: '6px 14px', borderRadius: 999, background: 'rgba(15,23,42,.88)', color: '#e2e8f0', fontSize: 13 }}>{locations === undefined ? 'Loading where the customer and vehicles were… it plays by itself when ready' : 'Starting…'}</div>}
      </div>
      <div style={{ width: open ? DRAWER_W : 0, transition: 'width .35s cubic-bezier(.2,.8,.2,1)', overflow: 'hidden', flexShrink: 0, background: 'rgba(15,23,42,.97)' }}>
        <div style={{ width: DRAWER_W, height: '100%', color: '#e2e8f0', display: 'flex', flexDirection: 'column' }}>
          <div style={{ padding: '12px 16px', borderBottom: '1px solid #33415588' }}>
            <div style={{ fontSize: 11, letterSpacing: 1.8, textTransform: 'uppercase', color: '#94a3b8' }}>Flow</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#fff' }}>{steps.length} events in order</div>
          </div>
            <div ref={listRef} style={{ flex: 1, overflowY: 'auto', padding: '6px 0', position: 'relative' }}>
              {steps.map((st, k) => {
                const kd = KINDS[st.kind] || KINDS.system, now = started && k === i, done = started && k < i
                return (
                  <button key={st.id} data-step={k} onClick={() => stepTo(k)}
                    style={{ display: 'block', width: '100%', textAlign: 'left', padding: '8px 16px 8px 40px', position: 'relative', border: 'none', cursor: 'pointer', color: 'inherit',
                      background: now ? `${kd.colour}33` : 'transparent', opacity: done || now ? 1 : 0.55, borderLeft: `3px solid ${now ? kd.colour : 'transparent'}` }}>
                    <span style={{ position: 'absolute', left: 17, top: 0, bottom: 0, width: 2, background: '#33415588' }} />
                    <span style={{ position: 'absolute', left: 11, top: 12, width: 14, height: 14, borderRadius: '50%', background: st.flag ? '#f43f5e' : kd.colour, border: '2px solid #0f172a', boxShadow: now ? `0 0 0 4px ${kd.colour}55` : 'none' }} />
                    <span style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11.5, color: '#94a3b8', fontVariantNumeric: 'tabular-nums' }}>
                      <span>{st.clock}</span><span>{st.dt ? `+${fmtDelta(st.dt)}` : 'start'}</span>
                    </span>
                    <span style={{ display: 'block', fontSize: 13.5, fontWeight: now ? 700 : 600, color: '#fff', lineHeight: '17px' }}>{st.title}</span>
                    <span style={{ display: 'block', fontSize: 11.5, color: kd.colour }}>{[kd.label, st.actor].filter(Boolean).join(' · ')}</span>
                    {st.explain && (() => { const FI = iconFor(st.explain.icon); return <span style={{ position: 'absolute', right: 12, top: 26, color: st.flag?.level === 'bad' ? '#fb7185' : '#fbbf24' }} title={st.explain.title}><FI size={16} /></span> })()}
                    {st.flag && <span style={{ display: 'block', fontSize: 11.5, color: '#fda4af', fontWeight: 700 }}>{st.flag.text}</span>}
                    {st.why && <span style={{ display: 'block', fontSize: 11.5, color: '#fde68a', fontWeight: 600 }}>Why: {st.why.headline}</span>}
                    {now && (st.content || []).slice(0, 3).map((l, n) => <span key={n} style={{ display: 'block', fontSize: 11.5, color: '#cbd5e1' }}>{l}</span>)}
                  </button>
                )
              })}
            </div>
        </div>
      </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
        <button onClick={() => stepTo(i - 1)} className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300" title="Previous step"><SkipBack className="w-4 h-4" /></button>
        <button onClick={() => { if (!clock.playing) heldFor.current = hold && started && into >= ARRIVED ? i : heldFor.current; clock.toggle() }} className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 ${clock.playing ? 'bg-amber-500 text-slate-950' : 'bg-brand-600 hover:bg-brand-500 text-white'}`}>
          {clock.playing ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}{clock.playing ? 'Pause' : 'Play'}
        </button>
        <button onClick={() => stepTo(i + 1)} className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300" title="Next step"><SkipForward className="w-4 h-4" /></button>
        <div className="relative flex-1 min-w-[240px] h-6">
          <input type="range" aria-label="Replay position" min={0} max={total} step={0.01} value={clock.tau}
            onChange={e => { clock.setPlaying(false); clock.setTau(Number(e.target.value)) }} className="absolute inset-0 w-full accent-indigo-500" />
          {steps.map((s, k) => (
            <span key={s.id} title={`${s.clock} ${s.title}`} className="absolute top-0 w-0.5 h-2 pointer-events-none"
              style={{ left: `${((LEAD_S + tl.starts[k]) / total) * 100}%`, background: s.flag ? '#f43f5e' : KINDS[s.kind]?.colour }} />
          ))}
        </div>
        <button onClick={() => setHold(h => !h)} title="Pause automatically when each message arrives, so you can read it. Press Play for the next one." aria-pressed={hold}
          className={`px-2 py-1 rounded-lg text-[11px] font-medium ${hold ? 'bg-amber-500 text-slate-950' : 'bg-slate-800 hover:bg-slate-700 text-slate-300'}`}>Hold at each message</button>
        <span className="flex items-center gap-1 text-[11px] text-slate-400" title="Zoom ratio on top of the automatic framing: + brings the customer and drivers closer, - shows more distance">
          Zoom
          <button onClick={() => { setAutoCam(true); setZoomBias(b => Math.max(-3, +(b - 0.5).toFixed(1))) }} aria-label="Zoom out" className="w-6 h-6 rounded bg-slate-800 hover:bg-slate-700 text-white font-bold leading-none">−</button>
          <span className="font-mono w-11 text-center text-slate-200">{(2 ** zoomBias).toFixed(2).replace(/0$/, '')}×</span>
          <button onClick={() => { setAutoCam(true); setZoomBias(b => Math.min(3, +(b + 0.5).toFixed(1))) }} aria-label="Zoom in" className="w-6 h-6 rounded bg-slate-800 hover:bg-slate-700 text-white font-bold leading-none">+</button>
          {zoomBias !== 0 && <button onClick={() => { setAutoCam(true); setZoomBias(0) }} className="px-1.5 h-6 rounded bg-slate-800 hover:bg-slate-700 text-[10px] text-slate-300">reset</button>}
        </span>
        <button onClick={() => { setAutoCam(a => !a) }} title="When on, the map follows the action. Zooming or dragging the map switches it off." aria-pressed={autoCam}
          className={`px-2 py-1 rounded-lg text-[11px] font-medium ${autoCam ? 'bg-brand-600 text-white' : 'bg-slate-800 hover:bg-slate-700 text-slate-300'}`}>Auto camera {autoCam ? 'on' : 'off'}</button>
        <button onClick={toggleFs} title={isFs ? 'Exit full screen' : 'Full screen'} aria-label={isFs ? 'Exit full screen' : 'Full screen'} className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200">{isFs ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}</button>
        {SPEEDS.map(v => (
          <button key={v} onClick={() => clock.setSpeed(v)} className={`px-2 py-0.5 rounded font-mono ${clock.speed === v ? 'bg-brand-600 text-white' : 'bg-slate-800 hover:bg-slate-700'}`}>{v}×</button>
        ))}
      </div>
      <div className="text-xs text-slate-300">{readout}</div>
      {loc?.towbook?.truck && <div className="text-xs text-slate-400">Towbook Driver 1 drove truck <b>{loc.towbook.truck}</b>. Towbook does not tell us who the driver is.</div>}
      {(loc?.notes || []).map((n, k) => <div key={k} className="text-xs text-slate-500">{n}</div>)}
    </div>
  )
}
