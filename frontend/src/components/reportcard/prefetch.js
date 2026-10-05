import { fetchReportCardReplay, fetchReportCardCallFlags, fetchCallStoryReplay, fetchCallStoryReplayMap, fetchCaseTrail } from '../../api'

/** One request per key, shared by whoever asks first (a hover that started loading, then the click that needs it).
 *  The Replay page starts these the moment the garage and date are known, in parallel with the day request.
 *  A good answer is kept for `ttlMs`; a failure is forgotten at once so a retry really retries. */
const pending = new Map()
const once = (kind, fn, ttlMs = Infinity) => (a, b) => {
  const key = `${kind}:${a}:${b}`
  const hit = pending.get(key)
  if (hit && Date.now() - hit.at < ttlMs) return hit.p
  const p = fn(a, b)
  p.then(r => { if (r.status !== 200) pending.delete(key) }, () => pending.delete(key))
  pending.set(key, { p, at: Date.now() })
  return p
}

export const loadReplay = once('replay', fetchReportCardReplay)
export const loadCallFlags = once('flags', fetchReportCardCallFlags)

// One call's story (animation steps) and map. Short life: a call still in progress keeps changing.
export const loadStoryReplay = once('story', q => fetchCallStoryReplay(q), 90_000)
export const loadStoryMap = once('storymap', q => fetchCallStoryReplayMap(q), 90_000)

// A work order's cases and who touched each one: loaded when someone opens them, kept for 2 minutes (open cases change).
export const loadCaseTrail = once('cases', woId => fetchCaseTrail(woId), 120_000)
