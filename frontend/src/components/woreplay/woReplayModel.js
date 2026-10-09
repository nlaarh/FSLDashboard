/** Work Order Replay model: the command-center slots drawn over the map, what each step means, and the waiting-timer maths.
 *  The clock itself is the replay engine (components/replay/useReplayEngine.js); this file has no timing of its own. */
import { buildLeg } from '../replay/roadPath.js'

/** What kind of hop it is. System-to-system and texts to the member look different on purpose. */
export const KINDS = {
  member: { colour: '#f59e0b', dash: null, label: 'Member action' },
  system: { colour: '#8b5cf6', dash: '8 7', label: 'System to system' },
  sms:    { colour: '#ec4899', dash: null, label: 'Text to member' },
  human:  { colour: '#0891b2', dash: null, label: 'Dispatcher action' },
  driver: { colour: '#059669', dash: null, label: 'Driver action' },
  mark:   { colour: '#e11d48', dash: null, label: 'Milestone' },
}

/** The command-center bar across the top shows EVERY channel a call can pass through, lit when this call touches it:
 *  where it was captured, the integration, Salesforce, and everything that can act on it. */
export const HUD = { y: 36, edgeY: 76, h: 52 }
export const NODE_ORDER = ['src_ivr', 'src_drr', 'src_mcc', 'src_partner', 'intake', 'sf', 'fsl', 'dispatcher', 'towbook']
export const NODE_INFO = {
  src_ivr:     { label: 'Replicant', sub: 'Voice AI', colour: '#0284c7' },
  src_drr:     { label: 'DRR', sub: 'Web / app form', colour: '#0891b2' },
  src_mcc:     { label: 'MCC', sub: 'Call-center agent', colour: '#0d9488' },
  src_partner: { label: 'Partner', sub: 'RAP / Call Mover', colour: '#64748b' },
  intake:      { label: 'Mulesoft', sub: 'Integration', colour: '#2563eb' },
  sf:          { label: 'Salesforce', sub: 'Service appointment', colour: '#4f46e5' },
  fsl:         { label: 'FSL scheduler', sub: 'Optimizer / auto-schedule', colour: '#8b5cf6' },
  dispatcher:  { label: 'Dispatcher', sub: 'AAA / garage staff', colour: '#c026d3' },
  towbook:     { label: 'Towbook', sub: 'Off-platform garage', colour: '#ea580c' },
}
export const DRAWER_W = 320
export const isSlot = id => NODE_ORDER.includes(id)
/** x of a channel's sphere for a stage of width w (the clock sits on the left). */
export const slotX = (id, w, left = 232) => left + ((w - 16 - left) * (NODE_ORDER.indexOf(id) + 0.5)) / NODE_ORDER.length

/** Step times as epoch seconds, in step order (the steps arrive sorted). */
export const stepTimes = steps => steps.map(s => Date.parse(s.ts) / 1000)

/** The member's waiting timer. created = call received, promise = original promise time, onScene = driver arrived (epoch s or null).
 *  state: ok -> soon (10 min or less to the promise) -> late (past it); done once the driver is on scene, and the timer stops. */
export function waitState(t, created, promise, onScene) {
  const arrived = onScene != null && t >= onScene
  const end = arrived ? onScene : t
  const state = arrived ? 'done' : promise != null && t > promise ? 'late' : promise != null && promise - t <= 600 ? 'soon' : 'ok'
  return { secs: Math.max(0, Math.floor(end - created)), state, over: promise != null && end > promise ? Math.round((end - promise) / 60) : 0 }
}

export function fmtWait(secs) {
  const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60), s = secs % 60
  return `${h ? `${h}:` : ''}${String(m).padStart(h ? 2 : 1, '0')}:${String(s).padStart(2, '0')}`
}

const isDriverStatus = (s, re) => (s.from === 'driver' || s.from === 'towbook') && s.to === 'sf' && re.test(s.title || '')
/** When the driver reached the member (the first "On Location" step), or null. */
export const onSceneTs = steps => { const s = steps.find(x => isDriverStatus(x, /on location/i)); return s ? Date.parse(s.ts) / 1000 : null }
export const promiseTs = steps => { const s = steps.find(x => x.id === 'P1'); return s ? Date.parse(s.ts) / 1000 : null }

/** What the acting vehicle is doing after step i, from the status steps so far: assigned | en_route | on_scene | done. */
export function driverPhase(steps, i) {
  let phase = 'assigned'
  for (let k = 0; k <= i && k < steps.length; k++) {
    const s = steps[k]
    if (isDriverStatus(s, /en route/i)) phase = 'en_route'
    else if (isDriverStatus(s, /on location/i)) phase = 'on_scene'
    else if (isDriverStatus(s, /completed|cannot|cancel|unable|no.?show/i)) phase = 'done'
    else if (/^(Assigned to|Driver removed|Pulled back)/.test(s.title || '')) phase = 'assigned'
  }
  return phase
}

/** One plain line for the toast that slides in when a step plays, e.g. "Driver on scene: 47 min after the call, 12 min past the promise". */
export function toastFor(steps, i) {
  const s = steps[i]
  if (!s) return null
  const who = s.names?.driver || s.names?.towbook || (s.from === 'driver' || s.from === 'towbook' ? steps.slice(0, i).reverse().map(x => x.names?.driver || x.names?.towbook).find(Boolean) : null)
  let text = s.title
  if (isDriverStatus(s, /on location/i)) {
    const at = Date.parse(s.ts) / 1000, due = promiseTs(steps)
    const late = due != null && at > due ? `, ${Math.round((at - due) / 60)} min past the promise` : ''
    text = `${who || 'Driver'} on scene: ${Math.round((at - Date.parse(steps[0].ts) / 1000) / 60)} min after the call${late}`
  } else if (/accepted/i.test(s.title) && who) text = `${who} accepted`
  else if (s.actor && !s.title.includes(s.actor)) text = `${s.title} (${s.actor})`
  return { text, level: s.flag?.level || (s.kind === 'mark' ? 'warn' : 'info'), kind: s.kind, clock: s.clock }
}

/** At step i: which channels the call has touched so far, which are active now, and what to print under each. */
export function hudState(steps, i, started) {
  const touched = new Set(), labels = {}, names = {}
  if (started) {
    steps.slice(0, i + 1).forEach(s => {
      Object.assign(names, s.names || {})
      for (const n of [s.from, s.via, s.to, ...(s.touch || [])].filter(Boolean)) {
        if (!NODE_INFO[n]) continue
        touched.add(n)
        if (n === 'dispatcher') labels.dispatcher = { label: s.actor || names.dispatcher || 'Dispatcher', sub: s.role || NODE_INFO.dispatcher.sub }
        else if (n === 'fsl') labels.fsl = { label: s.role || 'FSL scheduler', sub: s.actor || NODE_INFO.fsl.sub }
        else if (n === 'sf') labels.sf = { label: names.sf || 'Salesforce', sub: NODE_INFO.sf.sub }
        else if (n === 'towbook') labels.towbook = { label: names.towbook || 'Towbook', sub: NODE_INFO.towbook.sub }
        else if (n === 'intake') labels.intake = { label: 'Mulesoft', sub: /IT System/.test(s.actor || '') ? 'IT System User' : 'Integration' }
      }
    })
  }
  const cur = started ? steps[i] : null
  const active = new Set([cur?.from, cur?.via, cur?.to].filter(Boolean))
  return { touched, active, labels, names }
}

export const miles = (a, b) => {
  const r = x => (x * Math.PI) / 180
  const h = Math.sin(r(b.lat - a.lat) / 2) ** 2 + Math.cos(r(a.lat)) * Math.cos(r(b.lat)) * Math.sin(r(b.lon - a.lon) / 2) ** 2
  return 3958.8 * 2 * Math.asin(Math.sqrt(h))
}

/** Towbook shows a vehicle only as status times, and a Fleet / On-Platform driver may have no GPS at all. Draw it driving garage -> customer
 *  between En Route and On Location (along the road when the backend sent it, else straight), and say it is estimated.
 *  `by` = who reported the status steps: ['towbook'] (default) or ['driver', 'towbook'] for a driver with no GPS.
 *  Returns a track in the real GPS shape [t, lat, lon]. */
export function towbookTrack(steps, garage, wo, road, by = ['towbook']) {
  if (!garage || !wo) return []
  const t = s => Date.parse(s.ts) / 1000
  const er = steps.find(s => by.includes(s.from) && /en route/i.test(s.title))
  const ol = steps.find(s => by.includes(s.from) && /on location/i.test(s.title))
  if (!er) return []
  const end = t(steps[steps.length - 1]) + 3600
  const arrive = ol ? t(ol) : t(er) + 900
  const leg = road?.c?.length > 1 ? buildLeg(road.c, t(er), arrive) : [[t(er), garage.lat, garage.lon], [arrive, wo.lat, wo.lon]]
  const given = by.length > 1 ? steps.find(s => s.names?.driver) : null   // a driver with no GPS waits at the garage from the moment the call is given to them
  const from = given ? Math.min(t(given), t(er) - 1) : t(er) - 1
  return [[from, garage.lat, garage.lon], ...(from < t(er) - 1 ? [[t(er) - 1, garage.lat, garage.lon]] : []), ...leg, [Math.max(end, arrive + 1), wo.lat, wo.lon]]
}
