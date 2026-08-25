/**
 * mapIcons.js — Shared Leaflet icon factories.
 *
 * Import these in MapView, SAReportModal, DriverSnapshotMap, and any future
 * component that needs to place markers on a Leaflet map.
 */
import L from 'leaflet'

// ── Truck SVG ────────────────────────────────────────────────────────────────
export const TRUCK_SVG = (fill, stroke = '#fff') => `
<svg xmlns="http://www.w3.org/2000/svg" width="28" height="20" viewBox="0 0 28 20">
  <rect x="1" y="4" width="18" height="12" rx="2" fill="${fill}" stroke="${stroke}" stroke-width="1.5"/>
  <path d="M19 8h5l3 4v4h-8V8z" fill="${fill}" stroke="${stroke}" stroke-width="1.5"/>
  <circle cx="7" cy="17" r="2.5" fill="#1e293b" stroke="${stroke}" stroke-width="1"/>
  <circle cx="23" cy="17" r="2.5" fill="#1e293b" stroke="${stroke}" stroke-width="1"/>
</svg>`

// Color palette for truck states
export const TRUCK_COLORS = {
  closest:          { fill: '#22c55e', bg: 'rgba(34,197,94,0.15)',   border: '#22c55e' },
  dispatched:       { fill: '#f97316', bg: 'rgba(249,115,22,0.15)',  border: '#f97316' },
  assigned_closest: { fill: '#facc15', bg: 'rgba(250,204,21,0.15)',  border: '#facc15' },
  eligible:         { fill: '#64748b', bg: 'rgba(100,116,139,0.08)', border: '#475569' },
  ineligible:       { fill: '#334155', bg: 'rgba(51,65,85,0.08)',    border: '#1e293b' },
}

/**
 * truckIcon(color, label, glow)
 *   color: keyof TRUCK_COLORS
 *   label: short text under the icon (e.g. "2.3 mi")
 *   glow:  boolean — adds a glow ring (use for the assigned driver)
 */
export function truckIcon(color, label, glow = false) {
  const c = TRUCK_COLORS[color] || TRUCK_COLORS.eligible
  const glowStyle = glow ? `box-shadow:0 0 14px 5px ${c.fill}50;` : ''
  return L.divIcon({
    className: '',
    iconSize: [56, 44],
    iconAnchor: [28, 22],
    html: `<div style="display:flex;flex-direction:column;align-items:center;${glowStyle}">
      ${TRUCK_SVG(c.fill)}
      <div style="margin-top:1px;padding:0 4px;border-radius:4px;font-size:9px;font-weight:700;
                  color:${c.fill};background:${c.bg};border:1px solid ${c.border};white-space:nowrap;
                  line-height:14px;letter-spacing:0.3px">${label}</div>
    </div>`,
  })
}

// Customer location marker (red teardrop with star)
export const CUSTOMER_ICON = L.divIcon({
  className: '',
  iconSize: [36, 44],
  iconAnchor: [18, 44],
  html: `<div style="display:flex;flex-direction:column;align-items:center">
    <div style="width:36px;height:36px;border-radius:50% 50% 50% 0;transform:rotate(-45deg);
                background:#ef4444;border:3px solid white;box-shadow:0 3px 12px rgba(239,68,68,0.5);
                display:flex;align-items:center;justify-content:center">
      <span style="color:white;font-size:18px;font-weight:bold;transform:rotate(45deg)">&#9733;</span>
    </div>
  </div>`,
})

/**
 * teardropIcon({ rgb, glyph, selected })
 *   Shared teardrop pin. The selected pin is enlarged, ringed and pulsing so
 *   it is obvious which marker a list row flew you to.
 */
function teardropIcon({ rgb, glyph, selected = false }) {
  const size = selected ? 46 : 36
  const box = selected ? 60 : 36
  const ring = selected
    ? `box-shadow:0 0 0 6px rgba(${rgb},0.28),0 3px 14px rgba(${rgb},0.65);`
    : `box-shadow:0 3px 12px rgba(${rgb},0.5);`
  const h = size + 8
  return L.divIcon({
    className: selected ? 'pin-selected' : '',
    iconSize: [box, h],
    iconAnchor: [box / 2, h],
    // Lift the popup clear of the pin graphic — the anchor is the tip, and the
    // pin body sits above it, so without this the popup covers the marker.
    popupAnchor: [0, -h],
    html: `<div class="${selected ? 'pin-pulse' : ''}" style="display:flex;flex-direction:column;align-items:center">
      <div style="width:${size}px;height:${size}px;border-radius:50% 50% 50% 0;transform:rotate(-45deg);
                  background:rgb(${rgb});border:3px solid white;${ring}
                  display:flex;align-items:center;justify-content:center">
        <span style="color:white;font-size:${selected ? 22 : 18}px;font-weight:bold;transform:rotate(45deg)">${glyph}</span>
      </div>
    </div>`,
  })
}

/** Customer / pick-up pin — where the member is stranded. Red star. */
export const customerIcon = selected =>
  teardropIcon({ rgb: '239,68,68', glyph: '&#9733;', selected })

/**
 * Tow drop-off pin — the DESTINATION (repair shop), not a stranded member.
 * Deliberately blue with a shop glyph so it can never be misread as a pick-up.
 */
export const dropoffIcon = selected =>
  teardropIcon({ rgb: '56,142,255', glyph: '&#8962;', selected })

// Garage/facility marker (purple square with home icon)
export const FACILITY_ICON = L.divIcon({
  className: '',
  iconSize: [32, 32],
  iconAnchor: [16, 16],
  html: `<div style="width:32px;height:32px;border-radius:6px;background:#a855f7;border:2px solid white;
                      box-shadow:0 2px 8px rgba(168,85,247,0.4);display:flex;align-items:center;justify-content:center">
    <span style="color:white;font-size:18px">&#8962;</span>
  </div>`,
})
