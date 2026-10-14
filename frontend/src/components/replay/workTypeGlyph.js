/** The small call-type glyph for the member disc (pure, so it can be unit tested without Leaflet). */
/** What kind of call it is, drawn small inside the member disc: [pattern, label, inline SVG body (24x24, stroke icon)]. First match wins. */
const WORK_GLYPHS = [
  [/tow|drop-?off|pick-?up/i, 'Tow', '<path d="M2 17V8h9l2 3h5l3 3v3z"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/><path d="M6 8V4h4"/>'],
  [/batter|jump/i, 'Battery', '<rect x="2" y="8" width="20" height="12" rx="2"/><path d="M6 8V5h3v3M15 8V5h3v3M7 14h4M15 12v4M13 14h4"/>'],
  [/tire|flat|wheel/i, 'Tire', '<circle cx="12" cy="12" r="9.5"/><circle cx="12" cy="12" r="3.5"/><path d="M12 2.5v6M12 15.5v6M2.5 12h6M15.5 12h6"/>'],
  [/lock|key/i, 'Lockout', '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4M12 15v3"/>'],
  [/winch|extric|recover|stuck/i, 'Winch', '<circle cx="12" cy="10" r="6"/><circle cx="12" cy="10" r="1.6"/><path d="M12 16v6M9 22h6"/>'],
  [/fuel|gas|diesel/i, 'Fuel', '<path d="M4 21V4a1 1 0 0 1 1-1h8a1 1 0 0 1 1 1v17M3 21h12M14 9h2.5a1.5 1.5 0 0 1 1.5 1.5v6a1.5 1.5 0 0 0 3 0V8l-3-3M6.5 8h5"/>'],
]
const WRENCH = '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.1L3 17.7 6.3 21l6.3-6.3a4 4 0 0 0 5.1-5.4l-2.6 2.6-2.3-.6-.6-2.3z"/>'

/** A compact glyph (inline SVG) and label for a call's work type, matched case-insensitively; a wrench for anything else, null for no type. */
export function workTypeGlyph(workType) {
  const w = String(workType || '').trim()
  if (!w) return null
  const hit = WORK_GLYPHS.find(([re]) => re.test(w))
  const body = hit ? hit[2] : WRENCH
  return { label: w, kind: hit ? hit[1] : 'Other', svg: `<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#f8fafc" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${body}</svg>` }
}

