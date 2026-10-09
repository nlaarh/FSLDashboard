// Which truck drawing to use. Pure, so it is tested without a map.

const WHEEL_LIFT = /wheel.?lift|hook|\bwl\b|self.?loader/
const FLATBED = /flat.?bed|rollback|roll.?back|carrier|\bfb\b|\b\d{1,3}f\d?\b/   // "25- PATRIOT FB", "421 14F1", "076DO 27F"
const LIGHT = /\bls\b|\b\d{1,3}b\d?\b|service van|light/                       // "70- RAM LS", "100 09B1" (battery trucks)
const LIGHT_JOB = /battery|jump|lockout|lock.?out|tire|fuel|miscellaneous|gas|diesel/

/** flatbed | wheel_lift | light, from what Salesforce gave us.
 *  With a service (the call's work type): a tow gets a flatbed or a wheel-lift, a battery / lockout / fuel / tire call gets the light service van.
 *  Without one (the day map): from the truck name, then its capabilities (Flat Bed, Wheel Lift Truck, Tow); no tow capability at all = light. */
export function truckKindFor({ truck, skills, service } = {}) {
  const have = [truck, ...(Array.isArray(skills) ? skills : [skills])].filter(Boolean).join(' ').toLowerCase()
  const job = (service || '').toLowerCase()
  if (job) {
    if (LIGHT_JOB.test(job) && !/tow/.test(job)) return 'light'
    return WHEEL_LIFT.test(have) && !FLATBED.test(have) ? 'wheel_lift' : 'flatbed'
  }
  if (WHEEL_LIFT.test(have) && !FLATBED.test(have)) return 'wheel_lift'
  if (FLATBED.test(have)) return 'flatbed'
  if (LIGHT.test(have)) return 'light'
  if (have && !/\btow\b/.test(have)) return 'light'
  return 'flatbed'
}
