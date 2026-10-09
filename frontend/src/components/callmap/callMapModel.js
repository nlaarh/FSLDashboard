/** Watchlist call map: the pure parts (colours, the waiting clock, the events of the call). No React, no DOM. */
import { contactMarks, MARK_TYPES } from '../woreplay/contactMarks.js'
import { KINDS, waitState, onSceneTs } from '../woreplay/woReplayModel.js'

/** Member pin colour by how late the call is: green on time, yellow up to 30 min late, orange up to (not including) 90, red from 90. */
export function latenessLevel(minLate) {
  if (minLate == null || minLate <= 0) return 'ok'
  return minLate <= 30 ? 'yellow' : minLate < 90 ? 'orange' : 'red'
}
export const LATE_COLOUR = { ok: '#22c55e', yellow: '#eab308', orange: '#f97316', red: '#ef4444' }

export const toS = v => (typeof v === 'number' ? v : Date.parse(v) / 1000)
const CASE_COLOUR = '#e11d48'
export const CASE_TYPES = new Set(['case_created', 'case_status', 'case_closed'])

/** The call's story in time order: the replay steps (the AAA texts come from the contact marks instead, so a text appears once),
 *  every member call and text, and every case (opened, status changes, closed). Each: { id, t, ts, cat, type, title, detail, colour, actor, level, mark }. */
export function buildEvents(data) {
  if (!data) return []
  const steps = data.steps || []
  const marks = contactMarks(steps, data.extras)
  const out = []
  for (const s of steps) {
    if (s.kind === 'sms') continue
    out.push({ id: `s:${s.id}`, t: toS(s.ts), ts: s.ts, cat: 'step', type: s.kind, title: s.title, detail: s.detail || '', actor: [s.actor, s.role].filter(Boolean).join(' · '),
      colour: (KINDS[s.kind] || KINDS.system).colour, level: s.flag ? 'bad' : null })
  }
  for (const m of marks) out.push({ id: m.id, t: m.t, ts: m.ts, cat: 'contact', type: m.type, title: m.title, detail: m.detail, colour: MARK_TYPES[m.type].colour, mark: m })
  for (const c of data.cases?.events || []) {
    out.push({ id: c.id, t: toS(c.ts), ts: c.ts, cat: 'case', type: c.type, title: c.title, detail: c.detail, colour: CASE_COLOUR, caseId: c.case_id, actor: c.by || '' })
  }
  return out.sort((a, b) => a.t - b.t)
}

/** What the member pin shows at time t (epoch s): the wait clock, the minutes past the promise and the colour level. */
export function pinState(data, t, onScene) {
  const sa = data.sa
  const created = toS(sa.created_at), promise = sa.promise_at ? toS(sa.promise_at) : null
  const w = waitState(t, created, promise, onScene)
  const late = promise != null && !(onScene != null && t >= onScene) ? (t - promise) / 60 : promise != null && onScene != null ? (onScene - promise) / 60 : null
  const level = w.state === 'done' ? 'ok' : latenessLevel(late)
  return { ...w, level, lateMin: late != null && late > 0 ? Math.round(late) : 0 }
}

/** The call map's answer in the shape Garage Live's map draws ({ garage, tickets, drivers }), so ONE map shows both screens: this call as the only
 *  ticket, the assigned driver first (it is also what `link` points at), then the qualified on-shift drivers. Status words are Garage Live's own. */
export function asGarageLive(data) {
  const { sa, garage, driver, peers } = data
  const now = Date.parse(data.now) / 1000
  const onScene = onSceneTs(data.steps || [])
  const one = (d, job) => ({
    id: d.id, name: d.name, truck: d.truck, caps: d.skills, phone: d.phone, status: d.status, label: d.label, held: d.held, status_since: null,
    lat: d.lat, lon: d.lon, stale_position: d.lat == null, gps_at: d.gps_at, gps_age_min: d.gps_at ? Math.max(0, Math.floor((now - toS(d.gps_at)) / 60)) : null,
    job, queue: (d.queue || []).map(j => ({ sa_id: j.sa, number: j.sa, work_type: j.work_type, label: j.label })),
  })
  return {
    garage: { id: sa.id, name: garage.name, lat: garage.lat, lon: garage.lon },
    tickets: [{ sa_id: sa.id, number: sa.number, wo_number: sa.wo_number, status: sa.status, work_type: sa.work_type || '', city: sa.city || '', lat: sa.lat, lon: sa.lon,
      created_at: sa.created_at, promise_at: sa.promise_at, waiting: onScene == null, on_scene_at: onScene == null ? null : new Date(onScene * 1000).toISOString(),
      status_since: null, towbook: sa.towbook, driver_name: driver?.name || null, flags: [] }],
    drivers: [...(driver ? [one(driver, { number: sa.number, work_type: sa.work_type })] : []), ...peers.map(p => one(p, null))],
  }
}

export const minutesSince = (iso, nowS) => Math.max(0, Math.floor((nowS - toS(iso)) / 60))
export const agoText = m => (m < 1 ? 'just now' : m < 60 ? `${m} min ago` : `${Math.floor(m / 60)} h ${m % 60} min ago`)
/** "Jane Dee" -> "Jane D." */
export const shortPerson = n => { const p = String(n || '').trim().split(/\s+/); return p.length > 1 ? `${p[0]} ${p[p.length - 1][0]}.` : p[0] || '' }
export const phoneText = p => { const d = String(p || '').replace(/\D/g, '').slice(-10); return d.length === 10 ? `(${d.slice(0, 3)}) ${d.slice(3, 6)}-${d.slice(6)}` : p || '' }
export const telHref = p => `tel:${String(p || '').replace(/[^\d+]/g, '')}`
