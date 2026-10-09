/** Garage Live: the pure parts (formatting, gliding maths, the garage picker's rules). No React, no DOM, no Leaflet. */

export const REFRESH_MS = 60_000
export const GLIDE_MS = 6000                    // a truck slides from its old to its new position over this long after each refresh
export const STORE_KEY = 'fslapp.garageLive.last'
export const STILL_MILES = 0.01                 // a move smaller than this (about 15 m) is GPS jitter: no slide, no turning

export const SEVERITY = {
  red: { label: 'Urgent', bar: 'bg-red-500', chip: 'bg-red-500/15 text-red-300 border-red-500/40', dot: '#ef4444' },
  orange: { label: 'Soon', bar: 'bg-orange-500', chip: 'bg-orange-500/15 text-orange-300 border-orange-500/40', dot: '#f97316' },
  yellow: { label: 'Watch', bar: 'bg-yellow-400', chip: 'bg-yellow-400/15 text-yellow-200 border-yellow-400/40', dot: '#eab308' },
  info: { label: 'Info', bar: 'bg-sky-500', chip: 'bg-sky-500/15 text-sky-300 border-sky-500/40', dot: '#0ea5e9' },
}

export const DRIVER_STATUS = {
  free: { label: 'Free', short: 'free', colour: '#22c55e' },
  waiting: { label: 'Has a job, not started', short: 'assigned', colour: '#fbbf24' },
  driving: { label: 'Driving to a job', short: 'driving', colour: '#38bdf8' },
  on_scene: { label: 'On scene', short: 'on scene', colour: '#10b981' },
  towing: { label: 'Towing', short: 'towing', colour: '#a78bfa' },
}

/** 52 -> "52 min", 125 -> "2 h 05 min" (the server words its sentences the same way). */
export function fmtMin(m) {
  if (m == null || Number.isNaN(m)) return ''
  const r = Math.max(0, Math.round(m))
  return r < 60 ? `${r} min` : `${Math.floor(r / 60)} h ${String(r % 60).padStart(2, '0')} min`
}

/** Minutes since an ISO time at `nowS` (epoch seconds). */
export const minutesSince = (iso, nowS) => (iso ? Math.max(0, Math.floor((nowS - Date.parse(iso) / 1000) / 60)) : null)

/** Seconds the data on screen is old: how old the server said it was when it arrived, plus the time since. */
export function dataAgeS(data, receivedAtMs, nowMs) {
  if (!data) return null
  const server = Date.parse(data.now), stamped = Date.parse(data.watchlist_at || data.built_at)
  const atArrival = Number.isFinite(server) && Number.isFinite(stamped) ? Math.max(0, (server - stamped) / 1000) : 0
  return Math.round(atArrival + Math.max(0, nowMs - receivedAtMs) / 1000)
}

// ── gliding ──
export const easeInOut = x => (x < 0.5 ? 2 * x * x : 1 - ((-2 * x + 2) ** 2) / 2)
export const lerp = (a, b, k) => a + (b - a) * k

/** Where a truck is `elapsed` ms into a slide from `from` to `to` ([lat, lon] each). */
export function glidePoint(from, to, elapsed, dur = GLIDE_MS) {
  const k = dur <= 0 ? 1 : easeInOut(Math.min(1, Math.max(0, elapsed / dur)))
  return [lerp(from[0], to[0], k), lerp(from[1], to[1], k)]
}

/** Compass heading in degrees (0 = north, clockwise) from one point to another. */
export function bearing(a, b) {
  const p1 = (a[0] * Math.PI) / 180, p2 = (b[0] * Math.PI) / 180, dl = ((b[1] - a[1]) * Math.PI) / 180
  const y = Math.sin(dl) * Math.cos(p2), x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl)
  return (((Math.atan2(y, x) * 180) / Math.PI) + 360) % 360
}

/** Shortest signed turn from heading a to heading b, so a truck never spins the long way round. */
export const turn = (a, b) => ((b - a + 540) % 360) - 180

export function milesBetween(a, b) {
  const R = 3958.8, p1 = (a[0] * Math.PI) / 180, p2 = (b[0] * Math.PI) / 180
  const x = Math.sin((p2 - p1) / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(((b[1] - a[1]) * Math.PI) / 360) ** 2
  return 2 * R * Math.asin(Math.sqrt(x))
}

// ── the garage picker ──
/** Garages matching what was typed (case-insensitive, every word must appear), busiest first, capped for a short list. */
export function filterGarages(garages, query, cap = 60) {
  const words = String(query || '').toLowerCase().split(/\s+/).filter(Boolean)
  const hit = (garages || []).filter(g => { const n = `${g.name || ''} ${g.city || ''}`.toLowerCase(); return words.every(w => n.includes(w)) })
  return hit.sort((a, b) => (b.sa_count_28d || 0) - (a.sa_count_28d || 0)).slice(0, cap)
}

/** Which garage to open: the one in the URL, else the one picked last time, else none (the picker opens). */
export function initialGarage(urlId, storedId, garages) {
  if (urlId) return urlId
  return storedId && (!garages || garages.some(g => g.id === storedId)) ? storedId : null
}

export const readLast = () => { try { return localStorage.getItem(STORE_KEY) || null } catch { return null } }
export const writeLast = id => { try { localStorage.setItem(STORE_KEY, id) } catch { /* private mode: the pick just is not remembered */ } }

/** A ticket as the Watchlist call map wants it (its `alert` prop). */
export const replayAlert = (t, garage) => ({
  sa_id: t.sa_id, sa_number: t.number, wo_number: t.wo_number, work_type: t.work_type, priority_code: t.priority, city: t.city,
  facility_name: garage?.name, latitude: t.lat, longitude: t.lon, flag: t.flags?.[0] || '',
})
