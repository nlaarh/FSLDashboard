/** Scheduler Report Card — verdict palette, health badge styles and ET formatting. */

export const VERDICT_COLOURS = {
  GOOD: '#10b981',
  GOOD_NO_ARRIVAL: '#5eead4',
  LATE_EXECUTION: '#38bdf8',
  CAPACITY_SHORT: '#fbbf24',
  INBOUND_CASCADE: '#a78bfa',
  BOUNCED: '#f43f5e',
  STACKED: '#dc2626',
  FAR_PICK: '#f97316',
  LATE_DESPITE_CAPACITY: '#ef4444',
  NOT_GRADED_INSUFFICIENT_DATA: '#64748b',
  NOT_GRADED_CANCELED_PRE_ASSIGN: '#64748b',
  NOT_GRADED_TOWBOOK: '#64748b',
}

export const verdictColour = code => VERDICT_COLOURS[code] || '#64748b'

export const HEALTH_STYLES = {
  healthy:   { label: 'Healthy',   cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
  watch:     { label: 'Watch',     cls: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
  unhealthy: { label: 'Unhealthy', cls: 'bg-rose-500/15 text-rose-300 border-rose-500/30' },
}

/** Which lens decided the health badge (metrics-spec 5A). */
export const LENS_LABEL = {
  scheduler: { short: 'Workload', long: 'Workload (scheduler-owned)' },
  driver:    { short: 'Execution', long: 'Execution (driver-owned)' },
  both:      { short: 'Both', long: 'Workload and execution' },
}

const ET = 'America/New_York'

export function fmtTime(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString('en-US', { timeZone: ET, hour: 'numeric', minute: '2-digit' })
}

export function fmtPct(v) {
  return v == null ? '—' : `${Math.round(v * 100)}%`
}

export function fmtMin(v) {
  return v == null ? '—' : `${Math.round(v)} min`
}

export function fmtSpan(fromIso, toIso) {
  if (!fromIso || !toIso) return '—'
  const min = Math.round((new Date(toIso) - new Date(fromIso)) / 60000)
  return min >= 60 ? `${Math.floor(min / 60)} h ${min % 60} min` : `${min} min`
}

/** Yesterday in Eastern time — the latest day the report card can grade. */
export function yesterdayEastern() {
  const today = new Date().toLocaleDateString('en-CA', { timeZone: ET })
  const d = new Date(`${today}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() - 1)
  return d.toISOString().slice(0, 10)
}
