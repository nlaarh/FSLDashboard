/** Garage Live: how a truck drives from where it was drawn to where the latest refresh puts it. Pure: no React, no DOM, no network of its own. */
import { buildLeg, buildPath, metres } from '../replay/roadPath.js'

export const MI = 1609.344
export const STILL_M = 0.01 * MI          // a move this small is GPS jitter: no drive, no trail
export const ROAD_MIN_M = 0.05 * MI       // between STILL and this, a straight line is as good as a road
export const JUMP_M = 15 * MI             // further than this is a jump: straight line, no road lookup
export const TRAIL_S = 90                 // the fading trail behind a truck covers this much driving
export const MAX_ROAD_REQUESTS = 3        // road lookups running at once

/** What a move needs: 'still' | 'line' (straight, no lookup) | 'road' (ask for the street route). */
export function moveKind(from, to) {
  const m = metres(from, to)
  return m < STILL_M ? 'still' : m < ROAD_MIN_M || m > JUMP_M ? 'line' : 'road'
}

/** A timed path (replay's buildPath) along coords, driven at constant speed from t0 to t1 (engine seconds). */
export function legPath(coords, t0, t1) {
  return buildPath(buildLeg(coords && coords.length > 1 ? coords : [], t0, t1), null)
}

/** Road coords stitched to the exact old and new positions (the road snaps to the nearest street, the truck should end where GPS says). */
export function stitch(road, from, to) {
  return [from, ...(road || []), to]
}

/**
 * Road lookups for moves: each distinct move is asked once (cached, oldest dropped past `keep`), never more than `max` at a time,
 * and a failure resolves to null (the caller draws a straight line). fetchRoad(from, to) -> Promise<coords | null>.
 */
export function createRoadFetcher(fetchRoad, { max = MAX_ROAD_REQUESTS, keep = 200 } = {}) {
  const cache = new Map(), queue = [], pending = new Map()
  let running = 0
  const key = (a, b) => `${a[0].toFixed(5)},${a[1].toFixed(5)}>${b[0].toFixed(5)},${b[1].toFixed(5)}`
  const pump = () => {
    while (running < max && queue.length) {
      const job = queue.shift()
      running++
      Promise.resolve().then(() => fetchRoad(job.a, job.b)).catch(() => null).then(res => {
        running--
        if (cache.size >= keep) cache.delete(cache.keys().next().value)
        cache.set(job.k, res || null)
        pending.delete(job.k)
        job.done(res || null)
        pump()
      })
    }
  }
  return {
    get(a, b) {
      const k = key(a, b)
      if (cache.has(k)) return Promise.resolve(cache.get(k))
      if (pending.has(k)) return pending.get(k)
      let done
      const p = new Promise(r => { done = r })
      pending.set(k, p)
      queue.push({ k, a, b, done })
      pump()
      return p
    },
    stats: () => ({ running, waiting: queue.length, cached: cache.size }),
  }
}
