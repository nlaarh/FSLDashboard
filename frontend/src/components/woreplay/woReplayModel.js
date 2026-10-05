/** Work Order Replay model: the command-center slots drawn over the map, the step clock maths, and the pulse paths. */
export const STEP_S = 8        // seconds of animation per step: the pulse travels for TRAVEL of it, then rests so the caption can be read
export const TRAVEL = 0.45
export const LEAD_S = 1.5
export const STAGE_H = 680

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
export const HUD = { y: 60, edgeY: 124, h: 118 }
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

/** Animation timeline: every step gets STEP_S seconds, plus up to EXTRA_MAX more when a vehicle drives during it, so a drive
 *  can be watched instead of flashing past. starts/durs are in seconds after the lead-in. */
export const EXTRA_PER_MILE = 4
export const EXTRA_MAX = 22
export function buildTimeline(steps, driveMiles = () => 0) {
  const starts = [], durs = []
  let t = 0
  steps.forEach((_, k) => {
    const d = STEP_S + Math.min(EXTRA_MAX, EXTRA_PER_MILE * (driveMiles(k) || 0))
    starts.push(t); durs.push(d); t += d
  })
  return { starts, durs, total: LEAD_S + Math.max(t, STEP_S) + 1.5 }
}

/** Which step is playing at animation time tau, how far the pulse has travelled (0..1), and whether the lead-in is over. */
export function stepAt(tau, tl) {
  const f = Math.max(0, tau - LEAD_S)
  let i = 0
  while (i + 1 < tl.starts.length && tl.starts[i + 1] <= f) i++
  return { i, p: Math.min(1, (f - tl.starts[i]) / (STEP_S * TRAVEL)), started: tau >= LEAD_S, into: f - tl.starts[i], dur: tl.durs[i] }
}

/** Real time (epoch seconds) at tau: runs from this step's timestamp to the next one's across the step, so vehicles
 *  drive smoothly while hours of the call play in seconds. */
export function realTimeAt(tau, steps, tl) {
  if (!steps.length) return 0
  const { i, into, dur } = stepAt(tau, tl)
  const t = st => Date.parse(st.ts) / 1000
  const a = t(steps[i]), b = i + 1 < steps.length ? t(steps[i + 1]) : a
  return a + (b - a) * Math.min(1, Math.max(0, into / dur))
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

/** Towbook shows a vehicle only as status times. Draw it driving garage -> customer between En Route and On Location,
 *  and say it is estimated. Returns a track in the same [t, lat, lon] shape as real GPS, or [] when it cannot be drawn. */
export function towbookTrack(steps, garage, wo) {
  if (!garage || !wo) return []
  const t = s => Date.parse(s.ts) / 1000
  const er = steps.find(s => s.from === 'towbook' && /en route/i.test(s.title))
  const ol = steps.find(s => s.from === 'towbook' && /on location/i.test(s.title))
  if (!er) return []
  const end = t(steps[steps.length - 1]) + 3600
  const arrive = ol ? t(ol) : t(er) + 900
  return [[t(er) - 1, garage.lat, garage.lon], [t(er), garage.lat, garage.lon], [arrive, wo.lat, wo.lon], [Math.max(end, arrive + 1), wo.lat, wo.lon]]
}
