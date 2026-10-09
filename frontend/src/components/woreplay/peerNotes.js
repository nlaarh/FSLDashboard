/** The other qualified drivers (answer of /api/call-story/peers) turned into what the stage and the "Right driver?" tab print.
 *  Pure, no React. Miles are straight-line. A Towbook garage or an unbuilt day has no moments, only notes. */
import { miles } from './woReplayModel.js'

const ET = { timeZone: 'America/New_York' }
const clockOf = s => new Date(s * 1000).toLocaleTimeString('en-US', { ...ET, hour: 'numeric', minute: '2-digit', second: '2-digit' })

export const peerLabel = kind => (kind === 'accepted' ? 'When the driver accepted' : 'When the call was given to the driver')

/** The toast line: "3 other qualified drivers were on shift: closest Ann Lee, 2.1 mi, free". */
export function peerSentence(m) {
  const n = m.drivers.length, lead = m.kind === 'accepted' ? 'At accept: ' : ''
  if (!n) return `${lead}No other qualified driver was visible on shift${m.not_qualified ? ` (${m.not_qualified} on shift, not qualified)` : ''}`
  const c = m.drivers[0]
  return `${lead}${n} other qualified driver${n === 1 ? ' was' : 's were'} on shift: closest ${c.name}, ${c.miles} mi, ${c.label}`
}

/** peers -> [{ ...moment, at / ts (epoch s), clock, text }] ready for the stage (empty when nothing is available). */
export function peerMoments(peers) {
  if (!peers?.available) return []
  return peers.moments.map(m => { const at = Date.parse(m.at) / 1000; return { ...m, at, ts: at, clock: clockOf(at), text: peerSentence(m) } })
}

const LOAD_LABEL = { 'not started': 'not started', 'driving to it': 'driving to it', 'at the job': 'on scene', towing: 'towing' }

/** The popover content for the driver the call went to, from extras.driver_load[0] (Henry's "driver's other jobs" rules):
 *  { title, rows: [{ sa, label, given_at, miles }], next }. member = { lat, lon }. Towbook drivers are never named. */
export function queueFromLoad(load, member) {
  if (!load) return null
  const d = (j) => (j.lat != null && member ? Math.round(miles({ lat: j.lat, lon: j.lon }, member) * 10) / 10 : null)
  const first = load.after?.[0]
  return {
    title: load.channel === 'towbook' ? 'The Towbook driver' : load.driver,
    at: load.given_at,
    rows: (load.ahead || []).map(j => ({ sa: j.sa || j.wo, label: LOAD_LABEL[j.label] || j.label, given_at: null, miles: d(j) })),
    next: first ? { sa: first.sa || first.wo, given_at: first.given_at, reached_at: first.reached_at, miles: d(first) } : null,
  }
}

/** The popover content for one of the other drivers, from the peers answer (queue and next were worked out on the server). */
export const queueFromPeer = (p, at) => ({ title: p.name, at, rows: p.queue || [], next: p.next || null })
