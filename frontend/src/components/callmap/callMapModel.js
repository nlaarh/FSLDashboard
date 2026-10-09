/** Watchlist call map: the pure parts (colours, the waiting clock, the events of the call). No React, no DOM. */
import { contactMarks, MARK_TYPES } from '../woreplay/contactMarks.js'
import { KINDS, waitState } from '../woreplay/woReplayModel.js'

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

export const minutesSince = (iso, nowS) => Math.max(0, Math.floor((nowS - toS(iso)) / 60))
export const agoText = m => (m < 1 ? 'just now' : m < 60 ? `${m} min ago` : `${Math.floor(m / 60)} h ${m % 60} min ago`)
/** "Jane Dee" -> "Jane D." */
export const shortPerson = n => { const p = String(n || '').trim().split(/\s+/); return p.length > 1 ? `${p[0]} ${p[p.length - 1][0]}.` : p[0] || '' }
export const phoneText = p => { const d = String(p || '').replace(/\D/g, '').slice(-10); return d.length === 10 ? `(${d.slice(0, 3)}) ${d.slice(3, 6)}-${d.slice(6)}` : p || '' }
export const telHref = p => `tel:${String(p || '').replace(/[^\d+]/g, '')}`
