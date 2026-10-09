// How a call came in, from WorkOrder.Source__c. Same grouping as the work-order replay (backend/wo_replay.py INTAKE / SRC_NODE):
// IVR = Replicant voice AI, DRR = member web/app form, Intake = call-center (MCC) agent, RAP and Call Mover = partner.
export const CHANNELS = [
  { key: 'drr', label: 'DRR', long: 'Member web or app form (DRR)', bar: '#38bdf8', code: 'DRR' },
  { key: 'replicant', label: 'Replicant', long: 'Voice AI (Replicant IVR)', bar: '#a78bfa', code: 'AI' },
  { key: 'mcc', label: 'Call center', long: 'Call-center agent (MCC)', bar: '#34d399', code: 'MCC' },
  { key: 'partner', label: 'Partner', long: 'Partner (RAP / Call Mover)', bar: '#fb923c', code: 'PTN' },
  { key: 'reciprocal', label: 'Reciprocal', long: 'Reciprocal', bar: '#f472b6', code: 'REC' },
  { key: 'ticket', label: 'Service Ticket', long: 'Service Ticket', bar: '#facc15', code: 'TKT' },
  { key: 'authorize', label: 'Authorize', long: 'Authorize', bar: '#2dd4bf', code: 'AUT' },
  { key: 'unknown', label: 'Unknown', long: 'Source not recorded', bar: '#64748b', code: '?' },
]
const BY_KEY = Object.fromEntries(CHANNELS.map(c => [c.key, c]))
const MAP = { ivr: 'replicant', drr: 'drr', intake: 'mcc', rap: 'partner', 'call mover': 'partner', reciprocal: 'reciprocal', 'service ticket': 'ticket', authorize: 'authorize' }

export const channelOf = source => BY_KEY[MAP[(source || '').trim().toLowerCase()] || 'unknown']

/** Distinct work orders per channel with %, biggest first. calls = the day's non-drop-off calls; flags = per call id, each with wo_id + source.
 *  A call with no flag yet is skipped (the split appears when the flags arrive). */
export function channelSplit(calls, flags) {
  const seen = new Set(), n = {}
  for (const c of calls) {
    const x = flags[c.id]
    if (!x || c.is_drop_off) continue
    const id = x.wo_id || c.id
    if (seen.has(id)) continue
    seen.add(id)
    const k = channelOf(x.source).key
    n[k] = (n[k] || 0) + 1
  }
  const total = seen.size
  return { total, rows: CHANNELS.filter(c => n[c.key]).map(c => ({ ...c, n: n[c.key], pct: Math.round(100 * n[c.key] / total) })).sort((a, b) => b.n - a.n) }
}
