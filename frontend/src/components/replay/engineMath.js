/** Pure maths of the replay engine (no React, no DOM), so it can be unit tested. All times are epoch seconds. */

/** Replay speeds: real seconds that pass per wall second. */
export const SPEEDS = [1, 10, 60, 300]
/** When the next event is further away than this and nothing is moving, the quiet stretch is skipped faster. */
export const QUIET_GAP_S = 600
export const QUIET_BOOST = 5

/** Index of the last event at or before t (binary search); -1 when t is before the first event. */
export function indexAt(events, t) {
  let lo = 0, hi = events.length - 1, ans = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (events[mid] <= t) { ans = mid; lo = mid + 1 } else hi = mid - 1
  }
  return ans
}

/** First event strictly after t, or null. */
export function nextEvent(events, t) {
  const i = indexAt(events, t + 1e-6)
  return i + 1 < events.length ? events[i + 1] : null
}

/** Last event before t (with a little slack so "Prev" while sitting on an event goes to the one before it), or null. */
export function prevEvent(events, t, slack = 1) {
  const i = indexAt(events, t - slack)
  return i >= 0 ? events[i] : null
}

/** Seconds per wall second right now, and whether a quiet stretch is being fast-forwarded. */
export function effectiveRate(t, speed, events, busy, end) {
  const nxt = nextEvent(events, t) ?? end
  const quiet = nxt - t > QUIET_GAP_S && !(busy && busy(t))
  return { rate: quiet ? speed * QUIET_BOOST : speed, boosted: quiet, gap: quiet ? nxt - t : 0 }
}

/**
 * One animation step of dtWall seconds. Never jumps past a stop (a "pause at problems" time) or the end.
 * Returns { t, boosted, gap, stopped, ended }.
 */
export function advance(t, dtWall, { speed, events = [], busy, end, stops = [] }) {
  const { rate, boosted, gap } = effectiveRate(t, speed, events, busy, end)
  let next = t + dtWall * rate
  let stopped = false
  const s = nextEvent(stops, t)
  if (s != null && next >= s) { next = s; stopped = true }
  if (next >= end) return { t: end, boosted: false, gap: 0, stopped: false, ended: true }
  return { t: next, boosted, gap, stopped, ended: false }
}

/** Plain-English length of a skipped stretch: "14 min", "2 h 5 min". */
export function fmtSkip(seconds) {
  const m = Math.max(1, Math.round(seconds / 60))
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ''}`
}

/** Scrubber marks that would overlap (closer than `gapPx` on a bar `widthPx` wide) go on higher lanes, so every one stays clickable.
 *  times: seconds, any order. Returns a lane (0 = on the track, 1 = one row up, ...) for each, in the input order. */
export function assignLanes(times, start, span, widthPx, gapPx = 20) {
  const order = times.map((t, i) => i).sort((a, b) => times[a] - times[b])
  const lastX = [], lane = new Array(times.length).fill(0)
  for (const i of order) {
    const x = ((times[i] - start) / span) * widthPx
    let k = lastX.findIndex(px => x - px >= gapPx)
    if (k < 0) k = lastX.length
    lastX[k] = x; lane[i] = k
  }
  return lane
}
