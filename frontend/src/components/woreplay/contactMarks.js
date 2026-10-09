/** Member contact marks for the Work Order Replay, pure: no React. One mark per call or text, in time order.
 *  type: call (original call) | callback | call_other (membership line) | text_in (member texted) | text_out (AAA texted).
 *  Each mark is { id, ts (ISO), t (epoch seconds, for the engine), type, title, detail, ref } so the stage can draw an icon on the
 *  timeline / around the member pin and open the panel with onMark(id). `ref` says where the detail lives:
 *  { kind: 'call' | 'text' | 'sms', id } -> extras.calls[], extras.inbound_texts[], or the replay's own sms step. */

const ET = { timeZone: 'America/New_York' }
export const etClock = ts => (ts ? new Date(ts).toLocaleTimeString('en-US', { ...ET, hour: 'numeric', minute: '2-digit', second: '2-digit' }) : '')

export const MARK_TYPES = {
  call: { label: 'Member called', colour: '#38bdf8' },
  callback: { label: 'Member called back', colour: '#f59e0b' },
  call_other: { label: 'Called the membership line', colour: '#94a3b8' },
  text_in: { label: 'Member texted', colour: '#34d399' },
  text_out: { label: 'AAA texted the member', colour: '#ec4899' },
}
export const isFromMember = m => m.type !== 'text_out'

export const duration = s => (s == null ? '' : s < 60 ? `${s} sec` : `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, '0')} sec`)

/** @param steps the replay's steps (outbound texts are the kind 'sms' steps)  @param extras /api/call-story/extras answer, or null/undefined */
export function contactMarks(steps = [], extras) {
  const marks = []
  const add = (id, ts, type, title, detail, ref) => ts && marks.push({ id, ts, t: Date.parse(ts) / 1000, type, title, detail, ref })
  for (const s of steps) {
    if (s.kind === 'sms') add(`sms:${s.id}`, s.ts, 'text_out', s.title, s.detail || '', { kind: 'sms', id: s.id })
  }
  for (const c of extras?.calls || []) {
    const type = c.kind === 'original' ? 'call' : c.kind === 'callback' ? 'callback' : 'call_other'
    const bits = [c.line, duration(c.duration_s), c.agent && `answered by ${c.agent}`].filter(Boolean)
    add(`call:${c.id}`, c.ts, type, MARK_TYPES[type].label, bits.join(' · '), { kind: 'call', id: c.id })
  }
  for (const x of extras?.inbound_texts || []) {
    add(`text:${x.id}`, x.ts, 'text_in', MARK_TYPES.text_in.label, [x.agent && `handled by ${x.agent}`].filter(Boolean).join(' · '), { kind: 'text', id: x.id })
  }
  return marks.sort((a, b) => a.t - b.t)
}
