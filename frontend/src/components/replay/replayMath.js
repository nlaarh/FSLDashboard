/**
 * Replay maths, adapted from the Towbook Studio driverTimelineReplay (getDriverReplayState):
 * position at a clock time, heading, and what each driver is doing. Times are epoch seconds.
 * Real GPS is interpolated in a straight line between pings (no easing: easing would invent motion).
 */

/** A gap between pings longer than this is shown as "GPS gap", not as a smooth drive. */
export const GPS_GAP_S = 20 * 60

const ET = 'America/New_York'
export const clockLabel = (s, seconds = false) => new Date(s * 1000).toLocaleTimeString('en-US', {
  timeZone: ET, hour: 'numeric', minute: '2-digit', ...(seconds ? { second: '2-digit' } : {}),
})

const isoS = iso => (iso ? Math.floor(new Date(iso).getTime() / 1000) : null)

/** Index of the last keyframe at or before t (binary search), -1 when t is before the track. */
function floorIndex(track, t) {
  let lo = 0, hi = track.length - 1, ans = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (track[mid][0] <= t) { ans = mid; lo = mid + 1 } else hi = mid - 1
  }
  return ans
}

function bearing(a, b) {
  const toRad = d => (d * Math.PI) / 180
  const y = Math.sin(toRad(b[2] - a[2])) * Math.cos(toRad(b[1]))
  const x = Math.cos(toRad(a[1])) * Math.sin(toRad(b[1])) - Math.sin(toRad(a[1])) * Math.cos(toRad(b[1])) * Math.cos(toRad(b[2] - a[2]))
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360
}

/**
 * Where a driver is at t, or null outside the track. `stale` = seconds since the last ping when the
 * surrounding pings are more than GPS_GAP_S apart (position held at the last ping, not interpolated).
 */
export function positionAt(track, t) {
  if (!track?.length || t < track[0][0] || t > track[track.length - 1][0]) return null
  const i = floorIndex(track, t)
  const a = track[i], b = track[i + 1]
  if (!b || b[0] === a[0]) return { lat: a[1], lon: a[2], heading: null, stale: 0 }
  if (b[0] - a[0] > GPS_GAP_S) return { lat: a[1], lon: a[2], heading: null, stale: t - a[0] }
  const f = (t - a[0]) / (b[0] - a[0])
  const moved = a[1] !== b[1] || a[2] !== b[2]
  return { lat: a[1] + (b[1] - a[1]) * f, lon: a[2] + (b[2] - a[2]) * f, heading: moved ? bearing(a, b) : null, stale: 0 }
}

/** The path a driver has covered up to t (for the selected driver's trail). */
export function trailUntil(track, t) {
  const i = floorIndex(track || [], t)
  if (i < 0) return []
  const pts = track.slice(0, i + 1).map(p => [p[1], p[2]])
  const now = positionAt(track, t)
  if (now) pts.push([now.lat, now.lon])
  return pts
}

/** driverId -> calls that driver holds at t (from each call's assignment spans). */
export function heldAt(calls, t) {
  const out = {}
  for (const c of calls) {
    if (t < c.created || t >= c.end) continue
    for (const [d, from, to] of c.holds) {
      if (t >= from && t < to) (out[d] ||= []).push(c)
    }
  }
  return out
}

/**
 * What a driver is doing at t, from the day view's milestones of the calls he holds.
 * Returns { key, label, colour, call } — the Studio status badge vocabulary, in FSLAPP terms.
 */
export function driverStatus(dayDriver, held, sasById, t) {
  for (const c of held) {
    const m = sasById[c.id]?.milestones || {}
    const er = isoS(m.t_er), ol = isoS(m.t_ol) ?? c.arrival
    if (ol != null && t >= ol) return { key: 'on_scene', label: 'On scene', colour: '#10b981', call: c }
    if (er != null && t >= er) return { key: 'en_route', label: 'En route', colour: '#38bdf8', call: c }
  }
  if (held.length) return { key: 'assigned', label: 'Assigned, not rolling', colour: '#fbbf24', call: held[0] }
  const onShift = (dayDriver?.on_shift || []).some(([a, b]) => t >= isoS(a) && t < isoS(b))
  return onShift
    ? { key: 'idle', label: 'Idle on shift', colour: '#94a3b8', call: null }
    : { key: 'off', label: 'Off shift', colour: '#475569', call: null }
}

/** Calls created per bucket across [start, end] — the density strip under the scrubber. */
export function creationDensity(calls, start, end, buckets = 96) {
  const out = new Array(buckets).fill(0)
  const span = Math.max(end - start, 1)
  for (const c of calls) {
    const i = Math.floor(((c.created - start) / span) * buckets)
    if (i >= 0 && i < buckets) out[i] += 1
  }
  return out
}

/** Everything the Day replay draws at t: one entry per driver on the map, plus held calls. */
export function dayFrame(replay, dayDrivers, sasById, t) {
  const held = heldAt(replay.calls, t)
  const drivers = replay.drivers.map(d => {
    const pos = positionAt(d.track, t)
    const mine = held[d.id] || []
    return { id: d.id, name: d.name, mode: d.mode, pos, held: mine, status: driverStatus(dayDrivers[d.id], mine, sasById, t) }
  })
  const open = replay.calls.filter(c => t >= c.created && t < c.end)
  const late = open.filter(c => c.promise_due && t > c.promise_due && (c.arrival == null || t < c.arrival))
  return { drivers, held, open, late }
}
