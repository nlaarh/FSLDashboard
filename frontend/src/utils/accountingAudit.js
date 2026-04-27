/** Accounting audit utilities — product constants, header summary, auditor narrative */

export const PRODUCT_NAMES = {
  ER: 'Enroute Miles', TW: 'Tow Miles', TB: 'Tow Miles Basic',
  TT: 'Tow Miles Plus (5-30mi)', TU: 'Tow Miles Plus (30-100mi)',
  TM: 'Tow Miles Premier', EM: 'Extra Tow Mileage',
  E1: 'Extrication (1st Truck)', E2: 'Extrication (2nd Truck)', Z8: 'RAP Extrication',
  MH: 'Medium/Heavy Duty', TL: 'Tolls & Parking', MI: 'Misc / Wait Time',
  BA: 'Base Rate', BC: 'Basic Cost', PC: 'Plus Cost', HO: 'Holiday Bonus',
  PG: 'Plus/Premier Fuel', Z5: 'RAP Fuel Delivery', Z7: 'RAP Lockout',
  TJ: 'TireJect', Z0: 'RAP Gone on Arrival', Z1: 'RAP Flat Tire', Z3: 'RAP Battery Boost',
}
export const TOW_CODES = new Set(['TW', 'TB', 'TT', 'TU', 'TM', 'EM'])
export const TIME_CODES = new Set(['E1', 'E2', 'Z8', 'MI'])
export const FLAT_CODES = new Set(['BA', 'BC', 'PC', 'HO', 'PG', 'Z5', 'Z7', 'TJ', 'Z0', 'Z1', 'Z3'])
export const UNITS = { ER: 'mi', TW: 'mi', TB: 'mi', TT: 'mi', TU: 'mi', TM: 'mi', EM: 'mi',
  E1: 'min', E2: 'min', Z8: 'min', MI: 'min', TL: '$' }

/** One-line verdict for the header bar */
export function headerSummary(ev, code) {
  const req = ev.requested
  const google = ev.google_distance_miles
  const sfEst = ev.sf_estimated_miles
  const paid = ev.currently_paid
  const unit = UNITS[code] || 'units'
  const product = PRODUCT_NAMES[code] || ev.product || ''
  const sfRec = ev.sf_enroute_miles
  const baseline = google ?? (sfEst > 0 ? sfEst : sfRec > 0 ? sfRec : null)
  if (req != null && baseline != null && baseline > 0 && (code === 'ER' || TOW_CODES.has(code))) {
    const pct = (req / baseline * 100).toFixed(0)
    const src = google != null ? 'Google' : sfEst > 0 ? 'SF est' : 'SF rec'
    return `${req} ${unit} claimed — ${src}: ${baseline} ${unit} (${pct}%)`
  }
  if (req != null && ev.on_location_minutes != null && TIME_CODES.has(code)) {
    const pct = (req / ev.on_location_minutes * 100).toFixed(0)
    return `${req} min claimed — on-scene: ${ev.on_location_minutes} min (${pct}%)`
  }
  if (code === 'TL') return `$${req} claimed — tolls always need receipts`
  if (req != null && paid != null && paid > 0) return `${req} ${unit} claimed for ${product} — billed: ${paid} ${unit}`
  if (req != null) return `${req} ${unit} claimed for ${product}`
  return product || 'No data'
}

/** Auditor narrative — plain English story of what happened */
export function buildLocalSummary(ev, woliItems) {
  const lines = []
  const req = ev.requested, google = ev.google_distance_miles, sf = ev.sf_enroute_miles
  const sfEst = ev.sf_estimated_miles, onLoc = ev.on_location_minutes, paid = ev.currently_paid
  const product = ev.product || '', status = ev.status_quality || ''
  const vehicle = [ev.vehicle_make, ev.vehicle_model].filter(Boolean).join(' ')
  const code = product.split(' - ')[0]?.trim() || ''
  const unit = UNITS[code] || 'units'
  const productName = PRODUCT_NAMES[code] || product || 'unknown product'
  const wolis = woliItems || []

  // ── Distance products (ER, TW, etc.) ──
  if (code === 'ER' || TOW_CODES.has(code)) {
    const bestSf = sf > 0 ? sf : sfEst > 0 ? sfEst : null
    if (google) lines.push(`Google Maps calculates the route at ${google} miles.`)
    else if (bestSf) lines.push(`No independent Google calculation available. Salesforce has ${bestSf} miles.`)
    else lines.push(`No distance data available to verify this claim.`)
    if (sf > 0 && sfEst > 0 && Math.abs(sf - sfEst) > 2)
      lines.push(`Salesforce recorded ${sf} miles (at En Route) and estimated ${sfEst} miles (at dispatch).`)
    else if (sf > 0)
      lines.push(`Salesforce recorded ${sf} miles.`)
    if (paid > 0) lines.push(`We already paid ${paid} ${unit}.`)
    else lines.push(`Nothing has been paid for this product yet.`)
    if (paid > 0) {
      const delta = req - paid
      lines.push(`The garage is requesting ${req} ${unit} — that's ${delta > 0 ? delta.toFixed(2) + ' more than' : Math.abs(delta).toFixed(2) + ' less than'} what's billed.`)
    } else lines.push(`The garage is requesting ${req} ${unit}.`)
    const baseline = google || bestSf
    if (baseline > 0) {
      const ratio = req / baseline
      if (ratio <= 1.0) lines.push(`The claim is at or below the calculated distance — reasonable. Approve.`)
      else if (ratio <= 1.3) lines.push(`The claim is ${((ratio - 1) * 100).toFixed(0)}% above — within normal variance. Approve.`)
      else if (ratio <= 2.0) lines.push(`The claim is ${ratio.toFixed(1)}x the calculated distance. Ask the garage for an explanation.`)
      else lines.push(`The claim is ${ratio.toFixed(1)}x the calculated distance — significant discrepancy. Ask the garage for route documentation.`)
    }
    if (status.startsWith('BAD'))
      lines.push(`Note: Driver status timestamps are unreliable — SF distance may be inaccurate. Garage claim could be legitimate.`)

  // ── Time products (E1, E2, MI) ──
  } else if (TIME_CODES.has(code)) {
    if (onLoc != null) lines.push(`The driver was on scene for ${onLoc} minutes.`)
    else lines.push(`On-scene time is not available.`)
    if (paid > 0) lines.push(`We paid ${paid} min. Garage requests ${req} min — ${(req - paid).toFixed(1)} more.`)
    else lines.push(`Nothing billed yet. Garage requests ${req} minutes.`)
    if (onLoc && req) {
      const ratio = req / onLoc
      if (ratio <= 1.2) lines.push(`Within 120% of on-scene time — reasonable. Approve.`)
      else lines.push(`${ratio.toFixed(1)}x on-scene time. Ask garage to explain.`)
    }

  // ── MH (heavy vehicle) ──
  } else if (code === 'MH') {
    lines.push(`Garage requests Medium/Heavy Duty surcharge.${vehicle ? ` Vehicle: ${vehicle}.` : ''}`)
    const grp = ev.vehicle_group
    if (['DW', 'HD', 'MD'].includes(grp)) lines.push(`Vehicle group ${grp} = heavy duty. Qualifies. Approve.`)
    else if (grp === 'PS') lines.push(`Vehicle group PS = passenger. Typically does NOT qualify. Verify weight > 10,000 lbs.`)
    else lines.push(`Vehicle group not set. Check VIN or weight to confirm.`)

  // ── TL (tolls) ──
  } else if (code === 'TL') {
    const hasTow = wolis.some(w => TOW_CODES.has(w.code))
    lines.push(`Garage requests $${req} in tolls/parking. No receipt data in SF.`)
    if (hasTow) lines.push(`Tow on this WO — tolls plausible. Request receipt to confirm.`)
    else lines.push(`No tow on this WO — tolls less common. Request receipt.`)
    if (req > 30) lines.push(`$${req} exceeds typical NY toll range ($5-15). Verify.`)

  // ── Flat fees ──
  } else {
    if (paid > 0 && Math.abs(req - paid) < 0.5) lines.push(`Requesting ${req} for ${productName} — same as billed. No change.`)
    else if (paid > 0) lines.push(`Requesting ${req} for ${productName}. Billed: ${paid}. Policy decision.`)
    else lines.push(`Requesting ${req} for ${productName}. Not currently on WO.`)
  }
  return lines.join('\n\n') || null
}
