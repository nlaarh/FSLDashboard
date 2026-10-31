/**
 * Driver Replay: pure helpers (no React, no Leaflet) — colours, what each stop kind looks like, the replay window, and what a
 * driver is doing at a clock time. Times are epoch seconds. Stops come from the backend (driver_replay.py).
 */

/** One colour per picked driver, in pick order. The first is gold: one driver = one gold line. */
export const DRIVER_COLOURS = ['#fbbf24', '#38bdf8', '#f472b6', '#34d399', '#a78bfa', '#fb923c']
export const MAX_DRIVERS = DRIVER_COLOURS.length

// Glyph paths: Lucide icons (ISC licence), 24x24, stroked.
const G = {
  call: '<path d="M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9C18.7 10.6 16 10 16 10s-1.3-1.4-2.2-2.3c-.5-.4-1.1-.7-1.8-.7H5c-.6 0-1.1.4-1.4.9l-1.4 2.9A3.7 3.7 0 0 0 2 12v4c0 .6.4 1 1 1h2"/><circle cx="7" cy="17" r="2"/><path d="M9 17h6"/><circle cx="17" cy="17" r="2"/>',
  garage: '<path d="M22 8.35V20a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8.35A2 2 0 0 1 3.26 6.5l8-3.2a2 2 0 0 1 1.48 0l8 3.2A2 2 0 0 1 22 8.35Z"/><path d="M6 18h12"/><path d="M6 14h12"/><rect width="12" height="12" x="6" y="10"/>',
  home: '<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
  coffee: '<path d="M10 2v2"/><path d="M14 2v2"/><path d="M16 8a1 1 0 0 1 1 1v8a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V9a1 1 0 0 1 1-1h14a4 4 0 1 1 0 8h-1"/><path d="M6 2v2"/>',
  food: '<path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2"/><path d="M7 2v20"/><path d="M21 15V2a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3Zm0 0v7"/>',
  gas: '<line x1="3" x2="15" y1="22" y2="22"/><line x1="4" x2="14" y1="9" y2="9"/><path d="M14 22V4a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v18"/><path d="M14 13h2a2 2 0 0 1 2 2v2a2 2 0 0 0 2 2a2 2 0 0 0 2-2V9.83a2 2 0 0 0-.59-1.42L18 5"/>',
  store: '<path d="m2 7 4.41-4.41A2 2 0 0 1 7.83 2h8.34a2 2 0 0 1 1.42.59L22 7"/><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><path d="M15 22v-4a2 2 0 0 0-2-2h-2a2 2 0 0 0-2 2v4"/><path d="M2 7h20"/>',
  bigstore: '<circle cx="8" cy="21" r="1"/><circle cx="19" cy="21" r="1"/><path d="M2.05 2.05h2l2.66 12.42a2 2 0 0 0 2 1.58h9.78a2 2 0 0 0 1.95-1.57l1.65-7.43H5.12"/>',
  grocery: '<path d="m15 11-1 9"/><path d="m19 11-4-7"/><path d="M2 11h20"/><path d="m3.5 11 1.6 7.4a2 2 0 0 0 2 1.6h9.8a2 2 0 0 0 2-1.6l1.7-7.4"/><path d="M4.5 15.5h15"/><path d="m5 11 4-7"/><path d="m9 11 1 9"/>',
  pharmacy: '<path d="m10.5 20.5 10-10a4.95 4.95 0 1 0-7-7l-10 10a4.95 4.95 0 1 0 7 7Z"/><path d="m8.5 8.5 7 7"/>',
  bank: '<line x1="3" x2="21" y1="22" y2="22"/><line x1="6" x2="6" y1="18" y2="11"/><line x1="10" x2="10" y1="18" y2="11"/><line x1="14" x2="14" y1="18" y2="11"/><line x1="18" x2="18" y1="18" y2="11"/><polygon points="12 2 20 7 4 7"/>',
  post: '<rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>',
  bar: '<path d="M17 11h1a3 3 0 0 1 0 6h-1"/><path d="M9 12v6"/><path d="M13 12v6"/><path d="M5 8v12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V8"/><path d="M4 8h14"/>',
  auto: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
  off: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
  unknown: '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
}

/** What each stop kind looks like, and which of the four day buckets it counts in. */
export const KINDS = {
  call: { name: 'Call', colour: '#10b981', bucket: 'calls' },
  garage: { name: 'Garage', colour: '#6366f1', bucket: 'base' },
  home: { name: 'Home base', colour: '#64748b', bucket: 'base' },
  coffee: { name: 'Coffee', colour: '#d97706', bucket: 'places' },
  food: { name: 'Food', colour: '#f97316', bucket: 'places' },
  gas: { name: 'Gas station', colour: '#ef4444', bucket: 'places' },
  store: { name: 'Store', colour: '#3b82f6', bucket: 'places' },
  bigstore: { name: 'Store', colour: '#2563eb', bucket: 'places' },
  grocery: { name: 'Grocery', colour: '#14b8a6', bucket: 'places' },
  pharmacy: { name: 'Pharmacy', colour: '#ec4899', bucket: 'places' },
  bank: { name: 'Bank', colour: '#22c55e', bucket: 'places' },
  post: { name: 'Post office', colour: '#0ea5e9', bucket: 'places' },
  bar: { name: 'Bar or pub', colour: '#a855f7', bucket: 'places' },
  auto: { name: 'Auto parts', colour: '#78716c', bucket: 'places' },
  unknown: { name: 'Unlisted stop', colour: '#94a3b8', bucket: 'unknown' },
  off: { name: 'Parked, off shift', colour: '#334155', bucket: 'off' },
}
export const kindOf = k => KINDS[k] || KINDS.unknown
export const glyph = (k, size = 16) =>
  `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="#fff" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round">${G[k] || G.unknown}</svg>`

export const BUCKETS = [
  { id: 'driving', label: 'Driving' },
  { id: 'calls', label: 'At calls' },
  { id: 'places', label: 'Stores, food, gas' },
  { id: 'base', label: 'Garage / home' },
  { id: 'unknown', label: 'Unlisted stops' },
  { id: 'no_signal', label: 'No signal' },
  { id: 'off', label: 'Parked, off shift' },
]

/** "25 min", "1 h 5 min", "under 1 min". */
export function fmtDur(s) {
  const m = Math.round(s / 60)
  if (m < 1) return 'under 1 min'
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ''}`
}

/** Seconds per bucket from a driver's summary (driver_replay.summary). */
export function bucketTotals(summary) {
  const out = { driving: summary?.driving_s || 0, calls: 0, places: 0, base: 0, unknown: 0, no_signal: summary?.no_signal_s || 0, off: 0 }
  for (const [k, s] of Object.entries(summary?.stopped_s || {})) out[kindOf(k).bucket] += s
  return out
}

/** The slider's range and where the clock opens: the picked drivers' shifts (else their GPS), clipped to the day, 15 min each side.
 *  The clock opens at the earliest shift start. */
export function replayWindow(drivers, dayStart, dayEnd) {
  const starts = [], ends = []
  for (const d of drivers) {
    for (const [a, b] of d.shift || []) { starts.push(a); ends.push(b) }
    if (d.track?.length) { starts.push(d.track[0][0]); ends.push(d.track[d.track.length - 1][0]) }
  }
  if (!starts.length) return { start: dayStart, end: dayEnd, initial: dayStart }
  const shiftStarts = drivers.flatMap(d => (d.shift || []).map(s => s[0]))
  const open = Math.max(dayStart, Math.min(...(shiftStarts.length ? shiftStarts : starts)))
  const start = Math.max(dayStart, Math.min(...starts) - 900)
  const end = Math.min(dayEnd, Math.max(...ends) + 900)
  return { start, end: Math.max(end, start + 60), initial: Math.min(Math.max(open, start), end) }
}

/** 'hidden' before the stop, 'live' during it, 'done' after. */
export const stopState = (s, t) => (t < s.t0 ? 'hidden' : t < s.t1 ? 'live' : 'done')

/** What the driver is doing at t: { state: 'before' | 'driving' | 'stopped' | 'no_signal' | 'after', stop } */
export function doingAt(d, t) {
  const tr = d.track || []
  if (!tr.length || t < tr[0][0]) return { state: 'before', stop: null }
  if (t > tr[tr.length - 1][0]) return { state: 'after', stop: null }
  const stop = (d.stops || []).find(s => t >= s.t0 && t < s.t1)
  if (stop) return { state: 'stopped', stop }
  if ((d.gaps || []).some(([a, b]) => t >= a && t < b)) return { state: 'no_signal', stop: null }
  return { state: 'driving', stop: null }
}

/** The day as coloured pieces for the strip under each driver: [{ t0, t1, kind }] where kind is a stop kind, 'driving' or 'no_signal'. */
export function daySegments(d) {
  const tr = d.track || []
  if (tr.length < 2) return []
  const marks = [
    ...(d.stops || []).map(s => ({ t0: s.t0, t1: s.t1, kind: s.kind })),
    ...(d.gaps || []).map(([a, b]) => ({ t0: a, t1: b, kind: 'no_signal' })),
  ].sort((a, b) => a.t0 - b.t0)
  const out = []
  let at = tr[0][0]
  for (const m of marks) {
    if (m.t0 > at) out.push({ t0: at, t1: m.t0, kind: 'driving' })
    if (m.t1 > Math.max(at, m.t0)) out.push({ ...m, t0: Math.max(at, m.t0) })
    at = Math.max(at, m.t1)
  }
  if (tr[tr.length - 1][0] > at) out.push({ t0: at, t1: tr[tr.length - 1][0], kind: 'driving' })
  return out
}

/** The line a driver drove up to t, as pieces [[lat, lon]...]: a GPS silence over GAP_S is a break, never a made-up straight line.
 *  now = the truck's current position (appended to the last piece); t = Infinity gives the whole day. */
export const GAP_S = 20 * 60
/** Two GPS points further apart than this are a "hop": the road between them is unknown, so it is not drawn as a solid trail. */
export const HOP_M = 3000   // 2 minutes at highway speed is about 3 km: closer than that a straight line is a fair drawing
const metresBetween = (a, b) => {
  const r = Math.PI / 180, x = (b[2] - a[2]) * r * Math.cos(((a[1] + b[1]) / 2) * r), y = (b[1] - a[1]) * r
  return Math.hypot(x, y) * 6371000
}
export function splitAtGaps(track, t, now = null, hopM = Infinity) {
  const out = []
  let cur = []
  for (let i = 0; i < (track || []).length && track[i][0] <= t; i++) {
    if (i > 0 && (track[i][0] - track[i - 1][0] > GAP_S || metresBetween(track[i - 1], track[i]) > hopM)) { if (cur.length > 1) out.push(cur); cur = [] }
    cur.push([track[i][1], track[i][2]])
  }
  if (now && cur.length) cur.push([now.lat, now.lon])
  if (cur.length > 1) out.push(cur)
  return out
}

/** The hops (see HOP_M) the truck has made up to t, as [[lat, lon], [lat, lon]] pairs (GPS silences over GAP_S are not hops). */
export function hopsUntil(track, t, hopM = HOP_M) {
  const out = []
  for (let i = 1; i < (track || []).length && track[i][0] <= t; i++) {
    const a = track[i - 1], b = track[i]
    if (b[0] - a[0] <= GAP_S && metresBetween(a, b) > hopM) out.push([[a[1], a[2]], [b[1], b[2]]])
  }
  return out
}

/** Sorted times that Prev / Next jump between: every stop's arrival and departure. */
export const stopEvents = drivers => [...new Set(drivers.flatMap(d => (d.stops || []).flatMap(s => [s.t0, s.t1])))].sort((a, b) => a - b)

/** How long a whole day plays at 1x, in wall seconds: long enough to follow every drive, short enough to watch in one go. */
export const DAY_WALL_S = 180
/** Wall seconds a stop stays on screen at 1x: 2 s for a short one, growing with its length up to 5 s (a 45-minute break visibly
 *  lasts longer than a 5-minute call). Before / after the GPS and no-signal stretches take QUIET_WALL_S. */
export const stopWallS = s => Math.min(5, Math.max(2, 2 + (s.t1 - s.t0) / 900))
export const QUIET_WALL_S = 1.5
const clamp = (v, a, b) => Math.min(b, Math.max(a, v))

/** The Driver replay's pace, so a human can follow it: a whole day takes about DAY_WALL_S at 1x. Each stop gets its stopWallS;
 *  the driving gets the rest of the time (base rate = driving seconds / wall seconds left, kept between 20x and 400x).
 *  speed = the player's multiplier (0.5x .. 4x). gap = seconds left of a stop, for the "skipping" chip. Returns pace(t, speed). */
export function drivePace(drivers, start, end) {
  let driveS = 0, quietWall = 0
  for (const d of drivers) {
    let dS = 0, qW = 2 * QUIET_WALL_S + (d.gaps || []).length * QUIET_WALL_S
    for (const s of daySegments(d)) if (s.kind === 'driving') dS += Math.max(0, Math.min(s.t1, end) - Math.max(s.t0, start))
    for (const s of d.stops || []) if (s.t1 > start && s.t0 < end) qW += stopWallS(s)
    driveS = Math.max(driveS, dS); quietWall = Math.max(quietWall, qW)
  }
  const base = clamp(driveS / Math.max(60, DAY_WALL_S - quietWall), 20, 400)
  const pace = (t, speed) => {
    let from = start, to = end, wall = QUIET_WALL_S
    for (const d of drivers) {
      const { state, stop } = doingAt(d, t)
      if (state === 'driving') return { rate: base * speed, boosted: false, gap: 0 }
      const tr = d.track || []
      const span = state === 'stopped' ? [stop.t0, stop.t1]
        : state === 'no_signal' ? (d.gaps || []).find(([a, b]) => t >= a && t < b)
          : state === 'before' ? [start, tr.length ? tr[0][0] : end] : [tr.length ? tr[tr.length - 1][0] : start, end]
      if (state === 'stopped') wall = stopWallS(stop)
      from = Math.max(from, span[0]); to = Math.min(to, span[1])
    }
    const rate = Math.max(1, (to - from) / (wall / speed))
    return { rate, boosted: rate > base * speed, gap: rate > base * speed ? to - t : 0 }
  }
  pace.base = base
  return pace
}

/** True while any picked driver is driving (quiet stretches are only fast-forwarded when everyone is parked). */
export const anyDriving = drivers => t => drivers.some(d => doingAt(d, t).state === 'driving')

/** Ways to sort the driver list. */
export const SORTS = [
  { id: 'name', label: 'Name A–Z' },
  { id: 'name_desc', label: 'Name Z–A' },
  { id: 'calls', label: 'Most calls' },
  { id: 'start', label: 'Earliest on shift' },
]
const byName = (a, b) => a.name.localeCompare(b.name, 'en', { sensitivity: 'base' })
/** rows = [{ name, calls, start }] sorted by SORTS id (ties by name; no shift sorts last). Returns a new array. */
export function sortDrivers(rows, sort = 'name') {
  const cmp = {
    name: byName,
    name_desc: (a, b) => byName(b, a),
    calls: (a, b) => b.calls - a.calls || byName(a, b),
    start: (a, b) => (a.start ?? Infinity) - (b.start ?? Infinity) || byName(a, b),
  }[sort] || byName
  return [...rows].sort(cmp)
}

/** The on-platform drivers of a garage-day that can be replayed (GPS that day), one row each for the driver list:
 *  calls finished for this garage and the first shift start that day (overnight = already on shift at midnight).
 *  replay = the garage-day replay answer; day = the day (report card) answer with sas and drivers. */
export function driverRows(replay, day) {
  const calls = {}
  for (const sa of day?.sas || []) if (!sa.is_drop_off && sa.final_driver_id) calls[sa.final_driver_id] = (calls[sa.final_driver_id] || 0) + 1
  const shifts = Object.fromEntries((day?.drivers || []).map(d => [d.id, d.on_shift || []]))
  return (replay?.drivers || []).filter(d => d.mode === 'gps').map(d => {
    const starts = (shifts[d.id] || []).map(([a]) => Date.parse(a) / 1000).filter(x => x >= replay.day_start)
    const start = starts.length ? Math.min(...starts) : null
    return { id: d.id, name: d.name, calls: calls[d.id] || 0, start, overnight: start === replay.day_start }
  })
}

/** Which way a side-view truck faces, from its compass heading (0 = north, 90 = east): 'right' heading east-ish, 'left' west-ish.
 *  Heading close to due north or south keeps the way it already faced, so the truck does not flicker on a north-south road. */
export function facing(prev, heading) {
  if (heading == null) return prev
  if (heading > 20 && heading < 160) return 'right'
  if (heading > 200 && heading < 340) return 'left'
  return prev
}
