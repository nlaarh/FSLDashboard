/**
 * The game-style markers, as HTML strings for Leaflet divIcons: tow trucks seen from above (they rotate with their heading),
 * the garage building and the member's car. Colours and animation live in index.css (.rp-*); a marker's status colour is
 * the CSS variable --c, so changing a truck's status is one style write, never a new icon.
 */
import { esc } from './useLeafletMap'

export const STATUS = {
  en_route: { label: 'En route', colour: '#38bdf8' },
  on_scene: { label: 'On scene', colour: '#10b981' },
  towing: { label: 'Towing', colour: '#a78bfa' },
  assigned: { label: 'Assigned, not rolling', colour: '#fbbf24' },
  idle: { label: 'Idle', colour: '#94a3b8' },
  estimated: { label: 'Estimated (no GPS)', colour: '#fb923c' },
}

/** flatbed | wheel_lift | light: from the truck and skill text when Salesforce gave it, else from the kind of job. */
export function truckKindFor({ truck, skills, service } = {}) {
  const s = [truck, ...(Array.isArray(skills) ? skills : [skills]), service].filter(Boolean).join(' ').toLowerCase()
  if (/wheel.?lift|hook|\bwl\b|self.?loader/.test(s)) return 'wheel_lift'
  if (/flat.?bed|rollback|roll.?back|carrier|\bfb\b/.test(s)) return 'flatbed'
  if (/battery|jump|light|service|lockout|tire|fuel|winch|van|\bls\b/.test(s)) return 'light'
  return 'flatbed'
}

const WHEELS = '<g fill="#0b1220"><rect x="0.5" y="6" width="3.5" height="8" rx="1.2"/><rect x="24" y="6" width="3.5" height="8" rx="1.2"/><rect x="0.5" y="44" width="3.5" height="9" rx="1.2"/><rect x="24" y="44" width="3.5" height="9" rx="1.2"/></g>'
const CAB = '<rect class="c" x="4" y="1.5" width="20" height="18" rx="5.5"/><rect x="6.5" y="4.5" width="15" height="6.5" rx="2" fill="#0f172a" opacity=".78"/><rect x="6.5" y="13" width="15" height="4" rx="1.5" fill="#fff" opacity=".18"/><circle class="beacon" cx="14" cy="15" r="1.7" fill="#fde047"/>'
const BODY = {
  flatbed: `${WHEELS}${CAB}<rect x="3" y="21.5" width="22" height="36.5" rx="2.6" fill="#1e293b" stroke="var(--c)" stroke-width="1.7"/><g stroke="var(--c)" stroke-width="1" opacity=".4"><path d="M3.5 27h21M3.5 33h21M3.5 39h21M3.5 45h21M3.5 51h21"/></g>`,
  wheel_lift: `${WHEELS}${CAB}<rect x="4" y="21.5" width="20" height="17" rx="2.4" fill="#1e293b" stroke="var(--c)" stroke-width="1.7"/><rect x="11" y="38" width="6" height="14" fill="#64748b"/><rect x="3.5" y="50" width="21" height="4.2" rx="1.6" fill="#e2e8f0"/><path d="M6 54v4M22 54v4" stroke="#e2e8f0" stroke-width="2.4" stroke-linecap="round"/>`,
  light: `${WHEELS}<rect class="c" x="4" y="1.5" width="20" height="57" rx="7.5"/><rect x="6.5" y="4.5" width="15" height="7" rx="2.2" fill="#0f172a" opacity=".78"/><rect x="7" y="16" width="14" height="28" rx="3" fill="#0f172a" opacity=".32"/><path d="M15.2 19.5l-5 9.2h3.8l-1.2 9.3 5.4-10.4h-3.9z" fill="#fde047"/><rect x="7" y="49" width="14" height="6" rx="2" fill="#0f172a" opacity=".6"/><circle class="beacon" cx="14" cy="14.5" r="1.6" fill="#fde047"/>`,
}

/** A truck: heading-rotating body, status ring, name and garage tag. d = { name, garage, kind, est }. */
export function truckHtml({ name, garage, kind = 'flatbed', est = false }) {
  return `<div class="rp-truck${est ? ' est' : ''}"><div class="rp-ring"></div>
    <div class="rp-body"><div class="hdg"><svg viewBox="0 0 28 60" width="28" height="60">${BODY[kind] || BODY.flatbed}</svg></div></div>
    <div class="rp-tag"><b>${esc(name)}</b>${garage ? `<span>${esc(garage)}</span>` : ''}${est ? '<span class="e">estimated</span>' : ''}</div></div>`
}

/** The garage: a building with bay doors, named. */
export function garageHtml(name) {
  return `<div class="rp-garage"><svg viewBox="0 0 48 44" width="46" height="42"><path d="M3 18 24 4l21 14v24H3z" fill="#4338ca" stroke="#c7d2fe" stroke-width="2" stroke-linejoin="round"/><rect x="10" y="22" width="28" height="20" rx="1.5" fill="#1e1b4b"/><path d="M12 26h24M12 30h24M12 34h24M12 38h24" stroke="#a5b4fc" stroke-width="1.4" opacity=".75"/><rect x="19" y="9" width="10" height="5" rx="1" fill="#fde047" opacity=".9"/></svg>
    <div class="rp-gtag">${esc(name)}</div></div>`
}

/** The member: a car in a ring that pulses, plus the call number, the waiting timer and the car when known. */
export function memberHtml({ number, vehicle }) {
  return `<div class="rp-member ok"><div class="rp-mring"></div><div class="rp-mring r2"></div>
    <div class="rp-mdisc"><svg viewBox="0 0 40 24" width="30" height="18"><path d="M3 17l2-6q1-2 4-2.5L14 4.5q1-1.5 3-1.5h8q2 0 3 1.5l5 4.5q3 .5 4 2.5l1 5.5v1.5q0 1-1 1H4q-1 0-1-1z" fill="#f8fafc"/><path d="M15 5.5h10l4 4H11z" fill="#0f172a" opacity=".55"/><circle cx="11" cy="19" r="3.4" fill="#0f172a" stroke="#f8fafc" stroke-width="1.6"/><circle cx="29" cy="19" r="3.4" fill="#0f172a" stroke="#f8fafc" stroke-width="1.6"/></svg></div>
    <div class="rp-mtag"><b>${esc(number || 'Member')}</b><span class="wait">0:00</span>${vehicle ? `<i>${esc(vehicle)}</i>` : ''}</div></div>`
}

/** Contact marks around the member pin. type: phone | callback | text_out | text_in. */
const GLYPH = {
  phone: '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.4 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z"/>',
  callback: '<path d="M16 2v6h6M22 2l-6 6M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.4 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z"/>',
  text_out: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2zM8 8h8M8 12h5"/>',
  text_in: '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22zM9 12h6"/>',
}
export const MARK_COLOUR = { phone: '#38bdf8', callback: '#f43f5e', text_out: '#ec4899', text_in: '#f59e0b' }
export const markHtml = type => `<div class="rp-mark" style="--c:${MARK_COLOUR[type] || '#94a3b8'}"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">${GLYPH[type] || GLYPH.phone}</svg></div>`

/** Another job the driver was carrying, as a small numbered pin. */
export const jobHtml = (n, ahead) => `<div class="rp-job${ahead ? ' ahead' : ''}">${n}</div>`

/** Small driver chip for the day map: truck glyph, status colour, held-calls badge. */
export function dayTruckHtml({ name, kind, est }) {
  return `<div class="rp-truck day${est ? ' est' : ''}"><div class="rp-ring"></div>
    <div class="rp-body"><div class="hdg"><svg viewBox="0 0 28 60" width="28" height="60">${BODY[kind] || BODY.flatbed}</svg></div></div>
    <div class="rp-held" style="display:none"></div><div class="rp-tag"><b>${esc(name)}</b></div></div>`
}

/** A call on the day map: pulsing ring while the member waits (red past the promise), solid once a driver is there. */
export const dayPinHtml = colour => `<div class="rp-dpin ok" style="--v:${colour}"><i class="rp-mring"></i><b></b></div>`
