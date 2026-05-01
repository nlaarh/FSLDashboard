import { clsx } from 'clsx'
import { PRODUCT_NAMES, TOW_CODES, UNITS } from '../utils/accountingAudit'

/** Pull numeric value from rates dict with fallback */
function rv(rates, code, fallback) { return rates?.[code]?.value ?? fallback }

/** Left column in the 4-column audit grid — adapts by product code */
export default function AuditVerificationCard({
  ev, code, vehicle, isTow, isMileage, isTime, isFlat,
  googleMi, googleTowMi, towDestLat, origin,
  trueTotal, baseline, baselineLabel,
  mileRatio, mileColor, mileBg, timeRatio, timeColor,
  woliItems, rates, allWoSiblings, onOpenWoa,
}) {
  // Thresholds from admin reference data (with sensible fallbacks)
  const payPct    = rv(rates, 'mileage_pay_pct',    130)
  const reviewPct = rv(rates, 'mileage_review_pct', 150)
  const timePct   = rv(rates, 'time_pay_pct',       120)
  const e1Cap     = rv(rates, 'e1_time_cap_min',      60)

  // Included miles for member's coverage tier
  const covRaw = ev.coverage || ''
  const covKey = covRaw.toUpperCase().replace(/\s/g, '')
  const miPrefix = isTow ? 'tow' : 'er'
  const inclRateKey = covKey === 'B' ? `${miPrefix}_included_b`
    : covKey === 'P' ? `${miPrefix}_included_p`
    : (covKey === 'P+' || covKey === 'PP') ? `${miPrefix}_included_pp`
    : null
  const includedMi = inclRateKey ? rv(rates, inclRateKey, null) : null

  return (
    <div className="glass rounded-xl border border-slate-700/30 p-4 space-y-3">
      <div className="text-[10px] text-slate-500 uppercase tracking-wider font-bold">
        {isTime ? 'Time Verification' : code === 'MH' ? 'Heavy Vehicle Verification'
          : code === 'TL' ? 'Toll / Receipt Verification' : isFlat ? 'Service Verification'
          : isTow ? 'Tow Distance Verification' : 'Distance Verification'}
      </div>
      <div className="text-[9px] text-slate-700 italic leading-tight">
        SF = Salesforce auto-recorded values. Google = our independent calculation using driver GPS.
      </div>

      {/* Claim vs Baseline */}
      <div className="space-y-1.5 text-[11px]">
        <div className="flex justify-between">
          <span className="text-slate-400">Garage Claimed</span>
          <span className="font-bold text-white">{ev.requested ?? '—'} {UNITS[code] || 'units'}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-400">SF Billed (WOLI)</span>
          <span className="font-bold text-slate-300">{ev.currently_paid ?? 'Not on WO'}</span>
        </div>
        {ev.qty_interpretation && (
          <div className="text-[9px] text-slate-500 italic leading-tight px-1">{ev.qty_interpretation}</div>
        )}
        {ev.requested != null && (
          <div className="flex justify-between">
            <span className="text-slate-400">
              {ev.currently_paid > 0 ? 'True Total if Approved' : 'Total if Approved'}
            </span>
            <span className="font-bold text-amber-300">
              {trueTotal?.toFixed(2)} {UNITS[code] || ''}
            </span>
          </div>
        )}

        {/* Distance-specific fields */}
        {isMileage && !isTow && (
          <>
            <div className="border-t border-slate-800/50 pt-1.5 mt-1.5" />
            {/* Included miles from reference data */}
            {includedMi != null && (
              <div className="flex justify-between"
                title={`Included ${isTow ? 'tow' : 'ER'} miles for ${ev.coverage} coverage — source: Admin → Accounting Reference Rates (configurable)`}>
                <span className="text-slate-400">
                  Included ({ev.coverage} coverage){' '}
                  <span className="text-slate-600 font-normal">(ref data)</span>
                </span>
                <span className="font-bold text-sky-300">{includedMi} mi</span>
              </div>
            )}
            {googleMi != null && (
              <div className="flex justify-between"
                title={`We called Google Maps using ${origin?.source === 'towbook_gps_enroute' ? "the driver's Towbook EN_ROUTE GPS" : origin?.source === 'driver_gps_enroute' ? "the driver's FSL app EN_ROUTE GPS" : origin?.source === 'previous_job' ? "the driver's last-known job location (estimate)" : "the garage location (last resort)"} as the origin and the member's address as the destination.`}>
                <span className="text-slate-400">
                  Google Maps{' '}
                  <span className="text-slate-600 font-normal">
                    ({origin?.source === 'towbook_gps_enroute' ? 'Towbook GPS' : origin?.source === 'driver_gps_enroute' ? 'driver GPS' : origin?.source === 'previous_job' ? 'prev job est' : 'garage est'} → member)
                  </span>
                </span>
                <span className="font-bold text-brand-300">{googleMi} mi</span>
              </div>
            )}
            <div className="flex justify-between"
              title="SF automatically records this when the driver taps 'En Route' in the mobile app. Stored in WorkOrder.ERS_En_Route_Miles__c. May be 0 if driver status was skipped.">
              <span className="text-slate-400">SF Recorded <span className="text-slate-600 font-normal">(WO.ERS_En_Route_Miles__c)</span></span>
              <span className={clsx('font-bold', ev.sf_enroute_miles > 0 ? 'text-slate-300' : 'text-amber-400')}>
                {ev.sf_enroute_miles != null ? `${ev.sf_enroute_miles} mi` : 'N/A'}{ev.sf_enroute_miles === 0 ? ' — bad status?' : ''}
              </span>
            </div>
            {ev.sf_estimated_miles != null && ev.sf_estimated_miles > 0 && (
              <div className="flex justify-between"
                title="SF calculated this via Google Maps at dispatch time using the estimated driver location. Stored in WorkOrder.ERS_Estimated_En_Route_Miles__c.">
                <span className="text-slate-400">SF Pre-Dispatch Est <span className="text-slate-600 font-normal">(Google via SF)</span></span>
                <span className="font-bold text-slate-300">{ev.sf_estimated_miles} mi</span>
              </div>
            )}
          </>
        )}

        {/* Tow-specific fields */}
        {isTow && (
          <>
            <div className="border-t border-slate-800/50 pt-1.5 mt-1.5" />
            {/* Included tow miles */}
            {includedMi != null && (
              <div className="flex justify-between"
                title={`Included tow miles for ${ev.coverage} coverage — source: Admin → Accounting Reference Rates (configurable)`}>
                <span className="text-slate-400">
                  Included ({ev.coverage} coverage){' '}
                  <span className="text-slate-600 font-normal">(ref data)</span>
                </span>
                <span className="font-bold text-sky-300">{includedMi} mi</span>
              </div>
            )}
            {googleTowMi != null && (
              <div className="flex justify-between"
                title="SF called Google Maps at dispatch time to estimate tow distance (pickup → tow destination). Stored in WorkOrder.ERS_Estimated_Tow_Miles__c. Used as the benchmark for the tow mileage claim.">
                <span className="text-slate-400">
                  SF Google Est <span className="text-slate-600 font-normal">(pickup → tow dest)</span>
                </span>
                <span className="font-bold text-brand-300">{googleTowMi} mi</span>
              </div>
            )}
            <div className="flex justify-between"
              title="SF records this from the truck odometer/GPS at service completion. Stored in WorkOrder.Tow_Miles__c. May differ from Google Maps if driver took a different route.">
              <span className="text-slate-400">SF Tow Miles <span className="text-slate-600 font-normal">(WO.Tow_Miles__c)</span></span>
              <span className={clsx('font-bold', ev.sf_tow_miles > 0 ? 'text-slate-300' : 'text-amber-400')}>
                {ev.sf_tow_miles != null ? `${ev.sf_tow_miles} mi` : 'N/A'}
              </span>
            </div>
            {ev.sf_estimated_tow_miles != null && ev.sf_estimated_tow_miles > 0 && (
              <div className="flex justify-between"
                title="SF calculated this via Google Maps at dispatch time from pickup to tow destination. Stored in WorkOrder.ERS_Estimated_Tow_Miles__c. This is the most reliable tow distance reference.">
                <span className="text-slate-400">SF Pre-Dispatch Tow Est <span className="text-slate-600 font-normal">(Google via SF)</span></span>
                <span className="font-bold text-slate-300">{ev.sf_estimated_tow_miles} mi</span>
              </div>
            )}
            {ev.long_tow_used && (
              <div className="flex justify-between text-[10px] text-sky-300 mt-1"
                title="Long Tow Used flag is set on this Work Order (WorkOrder.Long_Tow_Used__c). Approval threshold raised to 150%.">
                <span>Long Tow Used <span className="text-slate-600">(WO flag)</span></span>
                <span className="font-bold">{ev.long_tow_miles ? `${ev.long_tow_miles} mi` : '✓'}</span>
              </div>
            )}
            {!towDestLat && (
              <div className="text-[10px] text-amber-400 mt-1">No tow destination GPS on WO — cannot verify tow distance automatically</div>
            )}
          </>
        )}

        {/* Time-specific fields */}
        {isTime && (
          <>
            <div className="border-t border-slate-800/50 pt-1.5 mt-1.5" />
            <div className="flex justify-between"
              title="Calculated from SA status timeline: time between 'On Location' and 'Completed' timestamps. Source: ServiceAppointmentHistory in Salesforce.">
              <span className="text-slate-400">On-Scene Time <span className="text-slate-600 font-normal">(SA timeline)</span></span>
              <span className="font-bold text-slate-300">{ev.on_location_minutes != null ? `${ev.on_location_minutes} min` : 'N/A'}</span>
            </div>
            {/* E1 time cap */}
            {code === 'E1' && trueTotal != null && (
              <div className="flex justify-between"
                title={`E1 maximum payable minutes per admin reference data (configurable in Admin → Accounting Reference Rates)`}>
                <span className="text-slate-400">E1 Policy Cap <span className="text-slate-600 font-normal">(ref data)</span></span>
                <span className={clsx('font-bold', trueTotal > e1Cap ? 'text-red-400' : 'text-emerald-400')}>
                  {e1Cap} min {trueTotal > e1Cap ? `— EXCEEDED by ${(trueTotal - e1Cap).toFixed(1)} min` : '— within cap ✓'}
                </span>
              </div>
            )}
          </>
        )}

        {/* MH-specific: vehicle weight, group, axles */}
        {code === 'MH' && (
          <>
            <div className="border-t border-slate-800/50 pt-1.5 mt-1.5" />
            <div className="flex justify-between">
              <span className="text-slate-400">Vehicle</span>
              <span className="font-bold text-slate-300">{vehicle || 'N/A'}</span>
            </div>
            <div className="flex justify-between"
              title="Vehicle Group from dispatch (WorkOrder.Vehicle_Group__c formula). DW/HD/MD = heavy duty. PS = passenger.">
              <span className="text-slate-400">Vehicle Group</span>
              <span className={clsx('font-bold', ['DW', 'HD', 'MD'].includes(ev.vehicle_group) ? 'text-emerald-400' : 'text-amber-400')}>
                {ev.vehicle_group || 'N/A'}
                {['DW', 'HD', 'MD'].includes(ev.vehicle_group) && ' — Heavy duty ✓'}
                {ev.vehicle_group === 'PS' && ' — Passenger (not heavy)'}
              </span>
            </div>
            {ev.vehicle_weight > 0 && (
              <div className="flex justify-between"
                title="Vehicle weight from the Asset record (WorkOrder.Weight_lbs__c formula). >10,000 lbs qualifies for MH.">
                <span className="text-slate-400">Weight <span className="text-slate-600 font-normal">(WO formula)</span></span>
                <span className={clsx('font-bold', ev.vehicle_weight > 10000 ? 'text-emerald-400' : 'text-amber-400')}>
                  {ev.vehicle_weight.toLocaleString()} lbs
                  {ev.vehicle_weight > 10000 ? ' — over 10K ✓' : ' — under 10K'}
                </span>
              </div>
            )}
            {ev.axle_count > 0 && (
              <div className="flex justify-between"
                title="Number of axles from the Asset record (WorkOrder.Number_of_Axles__c formula). 3+ axles typically qualifies for MH.">
                <span className="text-slate-400">Axles <span className="text-slate-600 font-normal">(vehicle record)</span></span>
                <span className={clsx('font-bold', ev.axle_count >= 3 ? 'text-emerald-400' : 'text-amber-400')}>
                  {ev.axle_count}{ev.axle_count >= 3 ? ' — 3+ axles ✓' : ' — under 3 axles'}
                </span>
              </div>
            )}
          </>
        )}

        {/* TL: receipt + toll detection + nearby places */}
        {code === 'TL' && (() => {
          const tl  = ev.tl_context || {}
          const toll = tl.toll   || {}
          const nearby = tl.nearby || {}
          const hasTow = woliItems?.some(w => TOW_CODES.has((w.product || w.code || '').split(' - ')[0]?.trim()))
          const airports = nearby.airport || []
          const parkings = nearby.parking || []
          return (
            <div className="mt-2 space-y-1.5">
              {/* Always: receipt reminder */}
              <div className="px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-700/30 text-[10px] text-amber-300">
                No receipts in SF — request receipt from garage to verify.
              </div>
              {ev.tow_call && (
                <div className="px-3 py-2 rounded-lg bg-blue-500/10 border border-blue-700/30 text-[10px] text-blue-300">
                  Tow Call — verify toll crossed on pickup AND return leg.
                </div>
              )}

              {/* Toll detection */}
              {toll.status === 'api_disabled' && (
                <div className="px-3 py-2 rounded-lg bg-slate-800/40 border border-slate-600/30 text-[10px] text-slate-400">
                  Toll detection unavailable — enable <span className="font-mono text-slate-300">routes.googleapis.com</span> in Google Cloud Console.
                </div>
              )}
              {toll.status === 'ok' && toll.toll_likely && (
                <div className="px-3 py-2 rounded-lg bg-red-500/10 border border-red-700/30 text-[10px] text-red-300 font-semibold">
                  Toll road detected on route
                  {toll.estimated_price?.length > 0 && ` — est. $${toll.estimated_price[0].amount}`}
                </div>
              )}
              {toll.status === 'ok' && !toll.toll_likely && (
                <div className="px-3 py-2 rounded-lg bg-emerald-500/10 border border-emerald-700/30 text-[10px] text-emerald-300">
                  No toll roads detected on route.
                </div>
              )}
              {toll.status === 'no_route' && (
                <div className="px-3 py-2 rounded-lg bg-slate-800/40 border border-slate-700/30 text-[10px] text-slate-400">
                  Toll check: no route found between these coordinates.
                </div>
              )}
              {(toll.status == null || toll.status === 'no_coords' || toll.status === 'no_key') && (
                hasTow
                  ? <div className="px-3 py-2 rounded-lg bg-emerald-500/10 border border-emerald-700/30 text-[10px] text-emerald-300">
                      Tow on WO — tolls plausible if route crosses toll road.
                    </div>
                  : <div className="px-3 py-2 rounded-lg bg-slate-800/40 border border-slate-700/30 text-[10px] text-slate-400">
                      No tow on WO — tolls less likely (unless parking/airport).
                    </div>
              )}

              {/* Nearby places */}
              {nearby.status === 'api_disabled' && (
                <div className="px-3 py-2 rounded-lg bg-slate-800/40 border border-slate-600/30 text-[10px] text-slate-400">
                  Nearby place context unavailable — enable <span className="font-mono text-slate-300">places.googleapis.com</span> in Google Cloud Console.
                </div>
              )}
              {nearby.status === 'ok' && airports.length > 0 && (
                <div className="px-3 py-2 rounded-lg bg-sky-500/10 border border-sky-700/30 text-[10px] text-sky-300">
                  Airport nearby: {airports[0].name}
                  {airports[0].vicinity ? ` (${airports[0].vicinity})` : ''} — parking/toll plausible.
                </div>
              )}
              {nearby.status === 'ok' && parkings.length > 0 && (
                <div className="px-3 py-2 rounded-lg bg-sky-500/10 border border-sky-700/30 text-[10px] text-sky-300">
                  Parking lot nearby: {parkings[0].name}
                  {parkings[0].vicinity ? ` (${parkings[0].vicinity})` : ''}.
                </div>
              )}
            </div>
          )
        })()}

        {/* Flat fee / service event */}
        {isFlat && !isMileage && !isTime && code !== 'TL' && code !== 'MH' && (
          <div className="mt-2 px-3 py-2 rounded-lg bg-slate-800/40 border border-slate-700/30 text-[10px] text-slate-300">
            {PRODUCT_NAMES[code] || code} — flat fee or service event. Verify the service was performed on this Work Order.
          </div>
        )}
      </div>

      {/* Comparison ratio bar — mileage */}
      {mileRatio != null && (
        <div className={clsx('flex items-center gap-3 px-3 py-2 rounded-lg border', mileBg)}>
          <span className="text-[10px] text-slate-500">{trueTotal?.toFixed(2)} ÷ {baselineLabel} ({baseline} mi):</span>
          <span className={clsx('font-bold text-lg leading-none', mileColor)}>{mileRatio.toFixed(0)}%</span>
          <span className={clsx('text-[10px] font-semibold', mileColor)}>
            {mileRatio <= payPct ? `≤${payPct}% → PAY` : mileRatio <= reviewPct ? `${payPct}–${reviewPct}% → REVIEW` : `>${reviewPct}% → FLAG`}
          </span>
        </div>
      )}

      {/* Comparison ratio bar — time */}
      {timeRatio != null && (
        <div className={clsx('flex items-center gap-3 px-3 py-2 rounded-lg border',
          timeRatio <= timePct ? 'bg-emerald-500/10 border-emerald-700/30' : 'bg-amber-500/10 border-amber-700/30')}>
          <span className="text-[10px] text-slate-500">Ratio:</span>
          <span className={clsx('font-bold text-lg leading-none', timeColor)}>{timeRatio.toFixed(0)}%</span>
          <span className={clsx('text-[10px] font-semibold', timeColor)}>
            {timeRatio <= timePct ? `≤${timePct}% → PAY` : `>${timePct}% → REVIEW`}
          </span>
        </div>
      )}

      {/* MI: claimed time parsed from description */}
      {ev.claimed_minutes_from_description != null && (
        <div className="text-[10px] text-slate-400 px-1">
          Description claims: <span className="font-bold text-slate-200">{ev.claimed_minutes_from_description} min</span>
          {ev.on_location_minutes != null && (
            <span className="text-slate-600"> · SA on-scene: {ev.on_location_minutes} min</span>
          )}
        </div>
      )}

      {/* Description keywords */}
      {ev.description_keywords?.length > 0 && (
        <div className="flex flex-wrap gap-1 pt-1">
          {ev.description_keywords.map(kw => (
            <span key={kw} className="px-1.5 py-0.5 rounded text-[9px] bg-amber-500/15 text-amber-300 border border-amber-700/30">
              {kw}
            </span>
          ))}
        </div>
      )}

      {/* Other WOAs on the same Work Order */}
      {allWoSiblings?.length > 0 && (
        <div className="mt-3 pt-2 border-t border-slate-700/20">
          <div className="text-[9px] text-slate-500 uppercase tracking-wider mb-1">Other WOAs — Same Work Order</div>
          <div className="space-y-0.5">
            {allWoSiblings.map(s => (
              <div key={s.id || s.woa_number} className="flex items-center gap-2 text-[10px]">
                <button
                  onClick={() => onOpenWoa?.(s.id || s.woa_number)}
                  className="text-blue-400 hover:text-blue-300 font-mono underline text-left cursor-pointer"
                >
                  {s.woa_number}
                </button>
                <span className="text-slate-500">{s.product || s.code}</span>
                {s.estimated_usd != null && (
                  <span className="text-slate-400">${s.estimated_usd.toFixed(2)}</span>
                )}
                <span className={clsx('text-[9px] font-semibold',
                  s.recommendation === 'approve' ? 'text-emerald-400' : 'text-amber-400')}>
                  {s.recommendation === 'approve' ? '✓' : '⚠'}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
