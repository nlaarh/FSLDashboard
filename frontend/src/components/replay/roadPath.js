import { GPS_GAP_S } from './replayMath.js'

/**
 * A driver's path as ONE timed polyline of [t, lat, lon] vertices.
 * Where the backend sent road geometry (a "run": ping times t[], the vertex index i[] of each ping, road vertices c[]),
 * the vertices of the road between two pings get times by distance, so the truck follows the streets at the speed the GPS
 * implies. Everywhere else the raw pings are joined in a straight line (today's behaviour).
 */

const R = 6371000
const rad = d => (d * Math.PI) / 180
export function metres(a, b) {
  const h = Math.sin(rad(b[0] - a[0]) / 2) ** 2 + Math.cos(rad(a[0])) * Math.cos(rad(b[0])) * Math.sin(rad(b[1] - a[1]) / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(h))
}

export function bearing(a, b) {   // a, b = [lat, lon]
  const y = Math.sin(rad(b[1] - a[1])) * Math.cos(rad(b[0]))
  const x = Math.cos(rad(a[0])) * Math.sin(rad(b[0])) - Math.sin(rad(a[0])) * Math.cos(rad(b[0])) * Math.cos(rad(b[1] - a[1]))
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360
}

/** Vertices coords[from..to] with times spread by distance between t0 and t1 (equal times when the road has no length). */
function timed(coords, from, to, t0, t1) {
  const out = [], cum = [0]
  for (let k = from + 1; k <= to; k++) cum.push(cum[cum.length - 1] + metres(coords[k - 1], coords[k]))
  const total = cum[cum.length - 1]
  for (let k = from; k <= to; k++) out.push([total > 0 ? t0 + (t1 - t0) * (cum[k - from] / total) : t0, coords[k][0], coords[k][1]])
  return out
}

/** A timed leg along road coords from t0 to t1 (used for the estimated Towbook vehicle). */
export function buildLeg(coords, t0, t1) {
  return coords && coords.length > 1 ? timed(coords, 0, coords.length - 1, t0, t1) : []
}

/** Merge a raw ping track with road runs into one timed vertex list. Bad runs (non-increasing indexes) are ignored. */
export function mergeRuns(track, runs = []) {
  const good = runs.filter(r => r?.t?.length >= 2 && r.t.length === r.i?.length && r.i.every((x, k) => k === 0 || x >= r.i[k - 1]) && r.i[r.i.length - 1] < r.c.length)
    .sort((a, b) => a.t[0] - b.t[0])
  const out = []
  let ri = 0
  for (const p of track) {
    while (ri < good.length && p[0] > good[ri].t[good[ri].t.length - 1]) { pushRun(out, good[ri]); ri++ }
    const run = good[ri]
    if (run && p[0] >= run.t[0] && p[0] <= run.t[run.t.length - 1]) continue   // this ping is inside a run: the road represents it
    out.push(p)
  }
  while (ri < good.length) pushRun(out, good[ri++])
  return out.sort((a, b) => a[0] - b[0])
}

function pushRun(out, r) {
  for (let k = 0; k + 1 < r.t.length; k++) {
    const seg = timed(r.c, r.i[k], r.i[k + 1], r.t[k], r.t[k + 1])
    if (k > 0) seg.shift()
    out.push(...seg)
  }
}

/** Index of the last vertex at or before t, -1 before the start. */
function floorIndex(v, t) {
  let lo = 0, hi = v.length - 1, ans = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (v[mid][0] <= t) { ans = mid; lo = mid + 1 } else hi = mid - 1
  }
  return ans
}

/**
 * buildPath(track, roadRuns) -> { verts, at(t), behind(t, seconds), ahead(t, seconds) }.
 * at(t) = { lat, lon, heading, stale } or null outside the track (same shape as replayMath.positionAt).
 */
export function buildPath(track, roadRuns) {
  const verts = roadRuns?.length ? mergeRuns(track || [], roadRuns) : (track || [])
  const at = t => {
    if (!verts.length || t < verts[0][0] || t > verts[verts.length - 1][0]) return null
    const i = floorIndex(verts, t)
    const a = verts[i], b = verts[i + 1]
    if (!b || b[0] === a[0]) return { lat: a[1], lon: a[2], heading: null, stale: 0 }
    if (b[0] - a[0] > GPS_GAP_S) return { lat: a[1], lon: a[2], heading: null, stale: t - a[0] }
    const f = (t - a[0]) / (b[0] - a[0])
    const moved = a[1] !== b[1] || a[2] !== b[2]
    return { lat: a[1] + (b[1] - a[1]) * f, lon: a[2] + (b[2] - a[2]) * f, heading: moved ? bearing([a[1], a[2]], [b[1], b[2]]) : null, stale: 0 }
  }
  /** Vertices between t0 and t1 plus the interpolated ends, as [lat, lon]; gaps over GPS_GAP_S are not bridged. */
  const slice = (t0, t1) => {
    if (!verts.length) return []
    const out = []
    const p0 = at(Math.max(t0, verts[0][0])), p1 = at(Math.min(t1, verts[verts.length - 1][0]))
    if (!p0 || !p1) return []
    out.push([p0.lat, p0.lon])
    for (let k = floorIndex(verts, t0) + 1; k < verts.length && verts[k][0] < t1; k++) {
      if (k > 0 && verts[k][0] - verts[k - 1][0] > GPS_GAP_S) out.length = 0
      out.push([verts[k][1], verts[k][2]])
    }
    out.push([p1.lat, p1.lon])
    return out
  }
  return { verts, at, behind: (t, s) => slice(t - s, t), ahead: (t, s) => slice(t, t + s) }
}
