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

/** Pull a numeric value from the rates dict with a fallback default */
function rateVal(rates, code, fallback) {
  return rates?.[code]?.value ?? fallback
}

/** Vehicle keywords that indicate recreational / non-covered vehicles for E1/E2 */
const RECREATIONAL_MAKES = new Set([
  'harley', 'harley-davidson', 'ducati', 'triumph', 'ktm', 'aprilia', 'moto guzzi',
  'royal enfield', 'indian motorcycle', 'kawasaki', 'husqvarna',
])
const RECREATIONAL_KEYWORDS = [
  'motorcycle', 'motorbike', 'dirt bike', 'atv', 'all-terrain', 'all terrain',
  'scooter', 'moped', 'snowmobile', 'golf cart', 'go-kart', 'gokart', 'quad bike',
  'skateboard', 'skate', 'bicycle', 'e-bike', 'electric bike',
]
function isRecreationalVehicle(make, model) {
  const str = `${make || ''} ${model || ''}`.toLowerCase()
  if (RECREATIONAL_MAKES.has((make || '').toLowerCase().trim())) return true
  return RECREATIONAL_KEYWORDS.some(k => str.includes(k))
}

/** One-line verdict for the header bar */
export function headerSummary(ev, code, rates = {}) {
  const req = ev.requested
  const isTowCode = TOW_CODES.has(code)
  const sfEst = isTowCode ? ev.sf_estimated_tow_miles : ev.sf_estimated_miles
  const sfRec = isTowCode ? ev.sf_tow_miles : ev.sf_enroute_miles
  const google = isTowCode ? null : ev.google_distance_miles
  const paid = ev.currently_paid
  const unit = UNITS[code] || 'units'
  const product = PRODUCT_NAMES[code] || ev.product || ''
  const baseline = isTowCode
    ? (sfEst > 0 ? sfEst : sfRec > 0 ? sfRec : null)
    : (google ?? (sfEst > 0 ? sfEst : sfRec > 0 ? sfRec : null))
  if (req != null && baseline != null && baseline > 0 && (code === 'ER' || isTowCode)) {
    const trueTotal = (paid || 0) + req
    const pct = (trueTotal / baseline * 100).toFixed(0)
    const src = isTowCode ? (sfEst > 0 ? 'Google/SF est' : 'SF rec') : google != null ? 'Google' : sfEst > 0 ? 'SF est' : 'SF rec'
    return paid > 0
      ? `+${req} ${unit} additional → true total ${trueTotal.toFixed(2)} ${unit} vs ${src} ${baseline} ${unit} (${pct}%)`
      : `${req} ${unit} claimed — ${src}: ${baseline} ${unit} (${pct}%)`
  }
  if (req != null && ev.on_location_minutes != null && TIME_CODES.has(code)) {
    const pct = (req / ev.on_location_minutes * 100).toFixed(0)
    return `${req} min claimed — on-scene: ${ev.on_location_minutes} min (${pct}%)`
  }
  if (code === 'TL') return `$${req} claimed — tolls always need receipts`
  if (req != null && paid != null && paid > 0) return `+${req} ${unit} additional for ${product} — billed: ${paid} ${unit}`
  if (req != null) return `${req} ${unit} claimed for ${product}`
  return product || 'No data'
}

/** Auditor narrative — plain English story of what happened.
 *  rates = {code: {value, unit, ...}} from /api/accounting/rates */
export function buildLocalSummary(ev, woliItems, rates = {}) {
  const lines = []
  const req = ev.requested, onLoc = ev.on_location_minutes, paid = ev.currently_paid
  const product = ev.product || '', status = ev.status_quality || ''
  const vehicle = [ev.vehicle_make, ev.vehicle_model].filter(Boolean).join(' ')
  const code = product.split(' - ')[0]?.trim() || ''
  const isTowCode = TOW_CODES.has(code)
  const unit = UNITS[code] || 'units'
  const productName = PRODUCT_NAMES[code] || product || 'unknown product'
  const wolis = woliItems || []

  // Thresholds from admin reference data (fallback to hardcoded defaults)
  const payPct    = rateVal(rates, 'mileage_pay_pct',    130)
  const reviewPct = rateVal(rates, 'mileage_review_pct', 150)
  const timePct   = rateVal(rates, 'time_pay_pct',       120)
  const tlFlag    = rateVal(rates, 'tl_flag_usd',         30)
  const e1Cap     = rateVal(rates, 'e1_time_cap_min',     60)

  // ── Distance products (ER, TW, etc.) ──
  if (code === 'ER' || isTowCode) {
    const distGoogle = isTowCode ? null : ev.google_distance_miles
    const sf = isTowCode ? ev.sf_tow_miles : ev.sf_enroute_miles
    const sfEstDist = isTowCode ? ev.sf_estimated_tow_miles : ev.sf_estimated_miles
    const bestSf = sfEstDist > 0 ? sfEstDist : sf > 0 ? sf : null

    // EM — Extra Tow Mileage: overage ONLY, requires a base tow charge on WO
    if (code === 'EM') {
      const hasBaseTow = wolis.some(w => ['TW', 'TB', 'TT', 'TU', 'TM'].includes(w.code))
      if (!hasBaseTow)
        lines.push(`EM REQUIRES BASE TOW: EM (Extra Tow Mileage) represents miles beyond the included tow allowance. A base tow line item (TW/TB/TT/TU/TM) must also be on this WO. No base tow is present — deny EM or request clarification from the garage.`)
      else
        lines.push(`EM = extra tow miles beyond the coverage-included allowance. Base tow exists on this WO ✓. Verify the total tow miles (base + EM) versus the Google/SF distance.`)
    }

    if (code === 'ER' && ev.is_cancel_en_route) {
      lines.push(`Resolution Code X002 (Cancel En Route): This driver was dispatched but cancelled before reaching the member. The ER claim represents distance traveled toward the member, NOT the full enroute distance from baseline.`)
      lines.push(`Verify: the route origin in the route card should be the driver's EN_ROUTE GPS position — not the baseline location. If the origin shows "estimated" or "garage," the Google distance may be overstated.`)
    }

    if (isTowCode && sfEstDist > 0)
      lines.push(`SF calculated the tow route via Google Maps at dispatch: ${sfEstDist} miles (WO.ERS_Estimated_Tow_Miles__c). This is the most reliable reference — it was computed from the actual pickup and drop-off addresses before any dispute.`)
    else if (distGoogle) {
      const originSrc = ev.truck_prev_location?.source
      const originLabel = originSrc === 'towbook_gps_enroute' ? "from driver's actual Towbook EN_ROUTE GPS (most accurate)"
        : originSrc === 'driver_gps_enroute' ? "from driver's FSL app GPS at En Route (accurate)"
        : originSrc === 'previous_job' ? "from driver's last completed job location (estimate — actual position may differ)"
        : 'from garage address (last resort estimate — least accurate)'
      lines.push(`Our Google Maps calculation ${originLabel} gives ${distGoogle} miles to the member's location.`)
    }
    else if (bestSf) lines.push(`No independent Google calculation available. Salesforce has ${bestSf} miles on record.`)
    else lines.push(`No distance data available to verify this claim.`)

    if (sf > 0 && sfEstDist > 0 && Math.abs(sf - sfEstDist) > 2)
      lines.push(`Note: SF recorded ${sf} miles at service time vs. ${sfEstDist} miles estimated at dispatch — a ${Math.abs(sf - sfEstDist).toFixed(1)}-mile gap. This may indicate the driver took a different route, or a status timestamp issue.`)
    else if (sf > 0 && !isTowCode)
      lines.push(`Salesforce recorded ${sf} miles at En Route (WO.ERS_En_Route_Miles__c).`)

    if (ev.coverage || ev.entitlement_name) {
      const cov = ev.coverage || ''
      const covUpper = cov.toUpperCase().replace(/\s/g, '')
      const prefix = isTowCode ? 'tow' : 'er'
      const inclKey = covUpper === 'B' ? `${prefix}_included_b`
        : covUpper === 'P' ? `${prefix}_included_p`
        : (covUpper === 'P+' || covUpper === 'PP') ? `${prefix}_included_pp`
        : null
      const inclMi = inclKey ? rateVal(rates, inclKey, null) : null
      const coverageNote = [cov, ev.entitlement_name].filter(Boolean).join(' / ')
      if (inclMi != null)
        lines.push(`Member coverage: ${coverageNote}. Per reference data, ${cov} coverage includes ${inclMi} ${isTowCode ? 'tow' : 'ER'} miles. Verify the claimed miles are an overage BEYOND the included amount before approving.`)
      else
        lines.push(`Member coverage: ${coverageNote}. Verify the claimed miles exceed the included miles in the member's entitlement before approving an overage charge.`)
    }

    if (paid > 0) lines.push(`We already paid ${paid} ${unit} for this product.`)
    else lines.push(`Nothing has been paid for this product yet.`)
    const trueTotal = (paid || 0) + req
    if (paid > 0)
      lines.push(`The garage requests ${req} ${unit} additional on top of the ${paid} ${unit} already paid — true total if approved: ${trueTotal.toFixed(2)} ${unit}.`)
    else
      lines.push(`The garage is requesting ${req} ${unit}.`)
    const baseline = distGoogle || bestSf
    if (baseline > 0) {
      const ratio = trueTotal / baseline
      if (ratio <= 1.0) lines.push(`True total (${trueTotal.toFixed(2)} ${unit}) is at or below the calculated distance — reasonable. Approve.`)
      else if (ratio * 100 <= payPct) lines.push(`True total (${trueTotal.toFixed(2)} ${unit}) is ${((ratio - 1) * 100).toFixed(0)}% above calculated distance — within normal variance (≤${payPct}%). Approve.`)
      else if (ratio * 100 <= reviewPct) lines.push(`True total (${trueTotal.toFixed(2)} ${unit}) is ${ratio.toFixed(1)}x the calculated distance (${(ratio * 100).toFixed(0)}%). Exceeds ${payPct}% threshold — ask the garage to explain the route.`)
      else lines.push(`True total (${trueTotal.toFixed(2)} ${unit}) is ${ratio.toFixed(1)}x the calculated distance (${(ratio * 100).toFixed(0)}%) — exceeds ${reviewPct}% flag threshold. Ask the garage for route documentation (turn-by-turn or GPS log).`)
    }
    if (status.startsWith('BAD'))
      lines.push(`Warning: Driver status timestamps are unreliable — SF distance data may be inaccurate. Do not deny based on SF miles alone; use the Google Maps link to verify independently.`)

  // ── Time products (E1, E2, MI, Z8) ──
  } else if (TIME_CODES.has(code)) {
    if (onLoc != null) lines.push(`The driver was on scene for ${onLoc} minutes.`)
    else lines.push(`On-scene time is not available.`)
    const timeTrueTotal = (paid || 0) + req
    if (paid > 0)
      lines.push(`We paid ${paid} min. Garage requests ${req} min additional — true total if approved: ${timeTrueTotal.toFixed(1)} min.`)
    else
      lines.push(`Nothing billed yet. Garage requests ${req} minutes.`)

    // E1: check against time cap
    if (code === 'E1') {
      if (timeTrueTotal > e1Cap)
        lines.push(`E1 TIME CAP: The true total (${timeTrueTotal.toFixed(1)} min) exceeds the policy cap of ${e1Cap} min. Per reference data, E1 is limited to ${e1Cap} minutes. Approve up to ${e1Cap} min; deny the excess.`)
      else
        lines.push(`E1 time cap is ${e1Cap} min. True total ${timeTrueTotal.toFixed(1)} min is within cap.`)
    }

    // E2: E1 must also be on this WO
    if (code === 'E2') {
      const hasE1 = wolis.some(w => {
        const c = (w.product || w.code || '').split(' - ')[0]?.trim()
        return c === 'E1'
      })
      if (!hasE1)
        lines.push(`E2 REQUIRES E1: The E2 (2nd Truck Extrication) product requires E1 (1st Truck Extrication) to also be on this Work Order. E1 is NOT present in the current line items — deny E2 unless the garage provides documentation showing both trucks were dispatched.`)
      else
        lines.push(`E1 is present on this WO — E2 prerequisite satisfied.`)
    }

    // Recreational / skates vehicle denial
    if (code === 'E1' || code === 'E2') {
      if (isRecreationalVehicle(ev.vehicle_make, ev.vehicle_model)) {
        lines.push(`RECREATIONAL VEHICLE DENIAL: Vehicle on record is "${vehicle || [ev.vehicle_make, ev.vehicle_model].filter(Boolean).join(' ')}" — appears to be a motorcycle, ATV, scooter, or other recreational vehicle. E1/E2 Extrication is NOT a covered benefit for recreational vehicles. Deny this claim.`)
      }
    }

    // Z8 — RAP extrication (Road Assistance Program, different rate/context)
    if (code === 'Z8') {
      lines.push(`Z8 is a RAP (Road Assistance Program) extrication code — typically used for non-member or special-program calls. Confirm this WO is on a RAP account before approving. Rate and coverage rules may differ from standard E1.`)
    }

    if (onLoc && req) {
      const ratio = timeTrueTotal / onLoc
      if (ratio * 100 <= timePct) lines.push(`True total (${timeTrueTotal.toFixed(1)} min) is within ${timePct}% of on-scene time — reasonable. Approve.`)
      else lines.push(`True total (${timeTrueTotal.toFixed(1)} min) is ${ratio.toFixed(1)}x on-scene time (${(ratio * 100).toFixed(0)}% — exceeds ${timePct}% threshold). Ask garage to explain.`)
    }

  // ── MH (heavy vehicle) ──
  } else if (code === 'MH') {
    lines.push(`Garage requests Medium/Heavy Duty surcharge.${vehicle ? ` Vehicle on WO: ${vehicle}.` : ''}`)
    const grp = ev.vehicle_group
    if (ev.axle_count > 0) lines.push(`Vehicle has ${ev.axle_count} axle${ev.axle_count !== 1 ? 's' : ''} per the asset record (WO.Number_of_Axles__c formula). Vehicles with 3+ axles typically qualify for MH. ${ev.axle_count >= 3 ? 'This vehicle has 3+ — qualifies on axles.' : 'This vehicle has fewer than 3 — confirm by weight or group.'}`)
    if (ev.vehicle_weight > 0) lines.push(`Vehicle weight: ${ev.vehicle_weight.toLocaleString()} lbs (WO.Weight_lbs__c formula). Threshold for MH is typically >10,000 lbs. ${ev.vehicle_weight > 10000 ? 'Over threshold — qualifies.' : 'Under threshold — confirm with garage.'}`)
    if (['DW', 'HD', 'MD'].includes(grp)) lines.push(`Vehicle group ${grp} = heavy duty (set by dispatch). Qualifies. Approve.`)
    else if (grp === 'PS') lines.push(`Vehicle group PS = passenger vehicle. Typically does NOT qualify for MH. Verify weight > 10,000 lbs or axles ≥ 3.`)
    else lines.push(`Vehicle group not set on WO. Use axle count or weight above, or request vehicle inspection report from garage.`)

  // ── TL (tolls) ──
  } else if (code === 'TL') {
    const hasTow = wolis.some(w => {
      const c = (w.product || w.code || '').split(' - ')[0]?.trim()
      return TOW_CODES.has(c)
    })
    lines.push(`Garage requests $${req} in tolls/parking charges. Salesforce does not store receipt data — always request receipt.`)
    if (ev.tow_call) lines.push(`Tow Call is checked (WO.Tow_Call__c = true). Tolls on tow calls may apply both ways (pickup drive + return drive). Verify if the toll road was crossed on both legs.`)
    if (hasTow) lines.push(`Tow service line item exists on this WO — tolls are plausible if the route crossed a toll road. Request receipt to confirm exact amount and toll location.`)
    else lines.push(`No tow service on this WO — tolls are less common for light service calls. Request receipt and verify the toll was genuinely incurred.`)
    if (ev.facility_id === 'GAR806') lines.push(`Facility ID is GAR806 (airport). Airport tows frequently include parking fees — receipt is essential.`)
    if (req > tlFlag) lines.push(`$${req} exceeds the reference threshold of $${tlFlag}. Verify with receipt. Major bridges (GWB, Tappan Zee) can reach $17–21 each way.`)

  // ── PG (Plus/Premier Fuel) ──
  } else if (code === 'PG') {
    const membershipLvl = ev.membership_level_coverage || ev.coverage || ''
    const ml = membershipLvl.toUpperCase()
    const isPlusPremier = ml.includes('P') && (ml.includes('+') || ml.includes('PLUS') || ml.includes('PREMIER') || ml === 'P')
    lines.push(`PG = Plus/Premier Fuel delivery. This benefit is only available to Plus or Premier AAA members.`)
    if (isPlusPremier)
      lines.push(`Member coverage is ${membershipLvl} — includes Plus or Premier tier. PG is a valid benefit. Approve if fuel was delivered.`)
    else if (membershipLvl)
      lines.push(`Member coverage shows ${membershipLvl}. This does not appear to be a Plus or Premier membership. PG is NOT covered under Basic. Verify membership tier before approving — if Basic, deny and inform the garage.`)
    else
      lines.push(`No membership level on file. Verify member has Plus or Premier coverage before approving — check the member record in Salesforce.`)

  // ── Flat fees ──
  } else {
    if (paid > 0 && Math.abs(req - paid) < 0.5) lines.push(`Requesting ${req} for ${productName} — same as billed. No change.`)
    else if (paid > 0) lines.push(`Requesting ${req} for ${productName}. Billed: ${paid}. Policy decision.`)
    else lines.push(`Requesting ${req} for ${productName}. Not currently on WO.`)
  }

  // ── Same-member same-day calls ──
  const sameDayCalls = ev.same_member_same_day
  if (sameDayCalls?.length > 0) {
    const callList = sameDayCalls.map(c => `WO#${c.wo_number} (TC:${c.trouble_code || '?'}, ${c.territory || c.status || '?'})`).join('; ')
    lines.push(`SAME MEMBER SAME DAY: This member had ${sameDayCalls.length} other service call${sameDayCalls.length > 1 ? 's' : ''} on the same day: ${callList}. Verify each call is for a distinct breakdown event.`)
  }

  return lines.join('\n\n') || null
}
