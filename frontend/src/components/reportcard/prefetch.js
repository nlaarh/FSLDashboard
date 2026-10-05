import { fetchReportCardReplay, fetchReportCardCallFlags } from '../../api'

/** One request per garage-day, shared by whoever asks first. The Replay page starts these the moment the
 *  garage and date are known, in parallel with the day request, so nothing waits behind anything else. */
const pending = new Map()
const once = (kind, fn) => (garage, date) => {
  const key = `${kind}:${garage}:${date}`
  if (!pending.has(key)) {
    const p = fn(garage, date)
    // keep a good answer for the session; forget a failure so a retry really retries
    p.then(r => { if (r.status !== 200) pending.delete(key) }, () => pending.delete(key))
    pending.set(key, p)
  }
  return pending.get(key)
}

export const loadReplay = once('replay', fetchReportCardReplay)
export const loadCallFlags = once('flags', fetchReportCardCallFlags)
