/**
 * Shared date helpers — used by Performance, GarageDashboard, GarageDetail.
 */

export function getWeek(offset = 0) {
  const now = new Date()
  const diff = now.getDay() === 0 ? -6 : 1 - now.getDay()
  const mon = new Date(now)
  mon.setDate(now.getDate() + diff + offset * 7)
  const sun = new Date(mon)
  sun.setDate(mon.getDate() + 6)
  const fmt = d => d.toISOString().split('T')[0]
  const lbl = d => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  return {
    start: fmt(mon), end: fmt(sun),
    label: `${lbl(mon)} – ${lbl(sun)}`,
    offset,
  }
}

export function getMonth(offset = 0) {
  const now = new Date()
  const d = new Date(now.getFullYear(), now.getMonth() + offset, 1)
  const start = d.toISOString().split('T')[0]
  const last = new Date(d.getFullYear(), d.getMonth() + 1, 0)
  const end = last.toISOString().split('T')[0]
  const label = d.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
  return { start, end, label, offset }
}

export function today() {
  return new Date().toISOString().split('T')[0]
}
