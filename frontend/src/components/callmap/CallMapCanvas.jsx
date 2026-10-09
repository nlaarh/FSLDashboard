import { useEffect, useRef } from 'react'
import L from 'leaflet'
import useLeafletMap, { esc } from '../replay/useLeafletMap'
import { truckHtml, truckKindFor, garageHtml, memberHtml, STATUS } from '../replay/gameIcons'
import { shortDriverName } from '../../utils/driverName'
import { pinState, toS, phoneText } from './callMapModel'
import { fmtWait } from '../woreplay/woReplayModel'

const icon = (html, w, h, ax = w / 2, ay = h / 2) => L.divIcon({ className: '', html, iconSize: [w, h], iconAnchor: [ax, ay] })
const COLOUR = { free: '#22c55e', driving: STATUS.en_route.colour, on_scene: STATUS.on_scene.colour, towing: STATUS.towing.colour, waiting: STATUS.assigned.colour }

/** The hover / click card of a truck: name, phone, status, distance and the calls it holds in the order they were given. */
export function tipHtml(d, isAssigned) {
  const queue = d.queue_known === false ? '<div class="m">Calls ahead are not known: this driver belongs to another garage.</div>'
    : d.queue?.length ? `<div class="m" style="margin-top:4px">Calls ahead, in order</div><ol>${d.queue.map(j => `<li><b>${esc(j.sa)}</b> ${esc(j.work_type || '')} <span class="m">${esc(j.label)}</span></li>`).join('')}</ol>`
      : '<div class="m" style="margin-top:4px">No other calls: free.</div>'
  return `<div class="cm-tip" style="min-width:210px"><b>${esc(d.name)}</b>${isAssigned ? ' <span class="m">· assigned to this call</span>' : ''}
    <div>${esc(d.label)}${d.miles != null ? ` · ${d.miles} mi from the member` : ''}</div>
    <div class="m">${d.phone ? esc(phoneText(d.phone)) : 'Phone not on file'}${d.truck ? ` · truck ${esc(d.truck)}` : ''}</div>${queue}</div>`
}

const truckIcon = (d, kind) => {
  const html = truckHtml({ name: shortDriverName(d.name), garage: d.miles != null ? `${d.miles} mi` : '', kind })
    .replace('<div class="rp-tag">', `<div class="rp-badge" style="background:${d.held ? '#f59e0b' : '#22c55e'}" title="${d.held} job${d.held === 1 ? '' : 's'} ahead">${d.held}</div><div class="rp-tag">`)
  return icon(html, 60, 60)
}

/**
 * The call's map: member pin (colour by lateness, wait clock), garage, assigned truck with a dashed line to the member, and the other
 * qualified on-shift trucks with a badge = jobs ahead (green 0 = free). Trucks are drawn from the drivers' CURRENT position, so they show
 * only while the slider sits at "now" (isLive); scrubbed back, the pin keeps following the clock but trucks are hidden (no position history is read).
 */
export default function CallMapCanvas({ data, t, isLive, onScene }) {
  const [ref, map] = useLeafletMap([data.sa.lat || 42.9, data.sa.lon || -78.8])
  const st = useRef({}), fitted = useRef(null), latest = useRef({})
  latest.current = { data, t, isLive, onScene }

  useEffect(() => {                                   // layers: rebuilt on every refresh (every 60 s), the view (zoom/pan) is kept
    if (!map) return undefined
    const { sa, garage, driver, peers } = data
    const root = L.layerGroup().addTo(map), trucks = L.layerGroup()
    const own = { interactive: false, keyboard: false }
    const kind = truckKindFor({ service: sa.work_type })
    const pts = []
    if (garage.lat != null) { pts.push([garage.lat, garage.lon]); L.marker([garage.lat, garage.lon], { ...own, zIndexOffset: -500, icon: icon(garageHtml((garage.name || '').replace(/^\w+\s+-\s+/, '')), 46, 42) }).addTo(root) }
    let memberEl = null
    if (sa.lat != null) {
      pts.push([sa.lat, sa.lon])
      const mk = L.marker([sa.lat, sa.lon], { ...own, zIndexOffset: 500, icon: icon(memberHtml({ number: sa.number }), 56, 56) }).addTo(root)
      memberEl = mk.getElement()?.firstElementChild
      st.current = { memberEl, wait: memberEl?.querySelector('.wait'), key: '' }
    }
    const addTruck = (d, assigned) => {
      if (d.lat == null) return
      const mk = L.marker([d.lat, d.lon], { keyboard: false, zIndexOffset: assigned ? 1000 : 200, icon: truckIcon(d, kind) }).addTo(trucks)
      mk.bindTooltip(tipHtml(d, assigned), { className: 'cm-tip-wrap', direction: 'top', offset: [0, -26], opacity: 1 })
      mk.bindPopup(tipHtml(d, assigned), { className: 'cm-tip-wrap', closeButton: false, offset: [0, -20] })
      const el = mk.getElement()?.firstElementChild
      el?.style.setProperty('--c', COLOUR[d.status] || '#94a3b8')
      if (assigned) el?.classList.add('live')
      if (!assigned && el) el.style.opacity = 0.92
      pts.push([d.lat, d.lon])
    }
    if (driver) {
      addTruck(driver, true)
      if (driver.lat != null && sa.lat != null) L.polyline([[driver.lat, driver.lon], [sa.lat, sa.lon]], { ...own, weight: 4, color: '#2563eb', dashArray: '8 10', opacity: 0.9 }).addTo(trucks)
    }
    peers.forEach(p => addTruck(p, false))
    st.current.trucks = trucks
    if (latest.current.isLive) trucks.addTo(map)
    if (fitted.current !== data.sa.id && pts.length) { map.fitBounds(L.latLngBounds(pts), { padding: [70, 70], maxZoom: 14 }); fitted.current = data.sa.id }
    return () => { root.remove(); trucks.remove(); st.current = {} }
  }, [map, data])

  useEffect(() => {                                   // trucks only while live
    const g = st.current.trucks
    if (!g || !map) return
    if (isLive) g.addTo(map); else g.remove()
  }, [isLive, map, data])

  useEffect(() => {                                   // the pin: colour and clock, written straight to the DOM (once a second when live)
    const paint = () => {
      const { data: d, t: tt, isLive: live, onScene: os } = latest.current
      const s = st.current
      if (!s.memberEl) return
      const p = pinState(d, live ? Date.now() / 1000 : tt, os)
      const key = `${p.level}${p.state}`
      if (key !== s.key) { s.key = key; s.memberEl.className = `rp-member cm ${p.level}` }
      if (s.wait) s.wait.textContent = `${fmtWait(p.secs)}${p.lateMin ? ` · +${p.lateMin} min` : p.state === 'done' ? ' · arrived' : ''}`
    }
    paint()
    const id = setInterval(paint, 1000)
    return () => clearInterval(id)
  }, [data, t, isLive, onScene, map])

  useEffect(() => {
    if (!map || typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver(() => map.invalidateSize())
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [map, ref])

  return <div ref={ref} className="absolute inset-0" aria-label="Call map" />
}
