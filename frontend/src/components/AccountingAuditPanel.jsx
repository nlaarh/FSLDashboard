import { useState, useEffect } from 'react'
import { clsx } from 'clsx'
import {
  Loader2, AlertTriangle, ExternalLink,
  MapPin, RefreshCw, ArrowRight, Info,
} from 'lucide-react'
import { fetchWOAAudit, recalculateWOAAudit } from '../api'
import { productCode } from '../utils/formatting'
import { PRODUCT_NAMES, TOW_CODES, TIME_CODES, FLAT_CODES, UNITS, headerSummary, buildLocalSummary } from '../utils/accountingAudit'

const REC_BADGE = {
  PAY:    'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30',
  REVIEW: 'bg-amber-500/15 text-amber-400 border border-amber-500/30',
  DENY:   'bg-red-500/15 text-red-400 border border-red-500/30',
}

export default function AccountingAuditPanel({ woaId, onComplete, recReason }) {
  const [audit, setAudit] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [recalcing, setRecalcing] = useState(false)

  const handleResult = (data) => {
    setAudit(data)
    if (data?.recommendation) onComplete?.(woaId, { recommendation: data.recommendation, confidence: data.confidence, summary: data.ai_summary || '' })
  }
  const load = (fetcher) => { setLoading(true); setError(null); fetcher(woaId).then(handleResult).catch(e => setError(e.message || 'Failed')).finally(() => setLoading(false)) }
  useEffect(() => { load(fetchWOAAudit) }, [woaId])
  const handleRecalculate = () => { setRecalcing(true); recalculateWOAAudit(woaId).then(handleResult).catch(e => setError(e.message || 'Failed')).finally(() => setRecalcing(false)) }

  if (loading) return <div className="flex items-center justify-center gap-2 py-8"><Loader2 className="w-4 h-4 animate-spin text-brand-400" /><span className="text-xs text-slate-500">Running audit…</span></div>
  if (error) return <div className="flex items-center justify-center gap-2 py-8"><AlertTriangle className="w-4 h-4 text-red-400" /><span className="text-xs text-red-400">{error}</span></div>
  if (!audit) return null

  const rec = (audit.recommendation || '').toUpperCase()
  const urls = audit.sf_urls || {}
  const timeline = audit.sa_timeline || []
  const ev = audit.evidence || {}
  const code = productCode(ev.product)

  const isStale = !('call_location_city' in ev)
  const origin = ev.truck_prev_location
  const originCity = [origin?.city, origin?.state].filter(Boolean).join(', ')
  const destCity = [ev.call_location_city, ev.call_location_state].filter(Boolean).join(', ')
  const originLat = origin?.lat, originLon = origin?.lon
  const destLat = ev.call_location_lat, destLon = ev.call_location_lon

  const isTow = TOW_CODES.has(code)
  const isMileage = code === 'ER' || isTow || (!code && ev.sf_enroute_miles != null)
  const isTime = TIME_CODES.has(code)
  const isFlat = FLAT_CODES.has(code)
  const googleMi = ev.google_distance_miles
  const sfMi = isTow ? ev.sf_tow_miles : ev.sf_enroute_miles
  const sfEst = isTow ? ev.sf_estimated_tow_miles : ev.sf_estimated_miles
  const vehicle = [ev.vehicle_make, ev.vehicle_model].filter(Boolean).join(' ')
  const status = ev.status_quality || ''

  // Tow destination for TW products
  const towDestLat = ev.tow_destination_lat, towDestLon = ev.tow_destination_lon

  // Ratios — baseline from our Google calc (previous job → call), then SF estimate, then SF recorded
  // Our Google calc uses a verifiable origin (previous job or garage). SF Recorded may be inflated.
  const baseline = isTow
    ? (sfEst > 0 ? sfEst : sfMi > 0 ? sfMi : null)
    : (googleMi ?? (sfEst > 0 ? sfEst : sfMi > 0 ? sfMi : null))
  const mileRatio = isMileage && ev.requested != null && baseline ? (ev.requested / baseline * 100) : null
  const baselineLabel = isTow ? (sfEst > 0 ? 'SF tow est' : 'SF tow recorded')
    : (googleMi ? 'Google (prev job)' : sfEst > 0 ? 'SF estimate' : 'SF recorded')
  const mileColor = mileRatio == null ? 'text-slate-400'
    : mileRatio <= 130 ? 'text-emerald-400' : mileRatio <= 150 ? 'text-amber-400' : 'text-red-400'
  const mileBg = mileRatio == null ? 'bg-slate-800/30 border-slate-700/30'
    : mileRatio <= 130 ? 'bg-emerald-500/10 border-emerald-700/30'
    : mileRatio <= 150 ? 'bg-amber-500/10 border-amber-700/30' : 'bg-red-500/10 border-red-700/30'
  const timeRatio = isTime && ev.requested != null && ev.on_location_minutes ? (ev.requested / ev.on_location_minutes * 100) : null
  const timeColor = timeRatio == null ? 'text-slate-400' : timeRatio <= 120 ? 'text-emerald-400' : 'text-amber-400'

  // Google Maps link: TW = call→tow destination, ER = truck→call
  const googleMapsLink = isTow
    ? (destLat && towDestLat ? `https://www.google.com/maps/dir/${destLat},${destLon}/${towDestLat},${towDestLon}` : null)
    : (originLat && destLat ? `https://www.google.com/maps/dir/${originLat},${originLon}/${destLat},${destLon}`
      : destLat ? `https://www.google.com/maps/dir/${originCity || 'garage'}/${destLat},${destLon}` : null)

  const localSummary = buildLocalSummary(ev, audit.woli_items)
  const aiText = audit.ai_summary || audit.summary
  const showAi = aiText && !aiText.startsWith('AI not configured')

  return (
    <div className="px-6 py-4 space-y-3 bg-slate-900/40">

      {/* Stale cache nudge */}
      {isStale && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-700/30">
          <Info className="w-3.5 h-3.5 text-amber-400 shrink-0" />
          <span className="text-[10px] text-amber-300">
            Cached from before latest update — click <strong>Recalculate</strong> to refresh.
          </span>
        </div>
      )}

      {/* ── ROW 1: Verdict bar ── */}
      <div className="flex items-center gap-3 flex-wrap">
        <span className={clsx('px-4 py-1.5 rounded-lg text-sm font-bold uppercase tracking-wide', REC_BADGE[rec] || REC_BADGE.REVIEW)}>
          {rec || 'UNKNOWN'}
        </span>
        <span className="text-xs text-slate-300 flex-1 min-w-0 truncate">{headerSummary(ev, code)}</span>
        {audit.confidence && (
          <span className="text-[10px] text-slate-600 shrink-0">
            Conf: <span className="text-slate-400 font-semibold">{audit.confidence}</span>
          </span>
        )}
        <button onClick={handleRecalculate} disabled={recalcing}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[10px] font-medium
                     bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white transition-colors disabled:opacity-50 shrink-0">
          <RefreshCw className={clsx('w-3 h-3', recalcing && 'animate-spin')} />
          {recalcing ? 'Working…' : 'Recalculate'}
        </button>
      </div>

      {/* ── Status warning (only if bad) ── */}
      {status.startsWith('BAD') && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-700/30">
          <AlertTriangle className="w-3.5 h-3.5 text-red-400 shrink-0" />
          <span className="text-[10px] text-red-300">{status} — SF distance data is unreliable for this call</span>
        </div>
      )}

      {/* ── ROW 2: Route card with Google Maps link ── */}
      {!isStale && (origin || destCity) && (
        <div className="px-4 py-3 rounded-xl bg-slate-800/30 border border-slate-700/20 text-[10px] space-y-1.5">
          {isTow ? (
            /* TW: show call location → tow destination */
            <div className="flex items-center gap-4">
              <div className="min-w-0 flex-1">
                <span className="text-slate-600">Pickup:</span>{' '}
                <span className="text-slate-200 font-medium">{destCity || 'Unknown'}</span>
                {destLat ? <span className="text-slate-600 font-mono ml-1">({destLat.toFixed(4)}, {destLon.toFixed(4)})</span>
                  : <span className="text-amber-500 ml-1">no GPS</span>}
              </div>
              <ArrowRight className="w-3.5 h-3.5 text-slate-600 shrink-0" />
              <div className="min-w-0 flex-1">
                <span className="text-slate-600">Tow To:</span>{' '}
                {towDestLat ? <span className="text-slate-200 font-medium font-mono">({towDestLat.toFixed(4)}, {towDestLon.toFixed(4)})</span>
                  : <span className="text-amber-500">no tow destination on WO</span>}
              </div>
            </div>
          ) : (
            /* ER / other: show truck origin → call location */
            <div className="flex items-center gap-4">
              <div className="min-w-0 flex-1">
                <span className="text-slate-600">From:</span>{' '}
                <span className="text-slate-200 font-medium">{originCity || 'Unknown'}</span>
                {origin?.source === 'driver_gps_enroute' && <span className="text-emerald-500"> (driver GPS at En Route)</span>}
                {origin?.source === 'previous_job' && <span className="text-slate-600"> (estimated — last known job)</span>}
                {origin?.source === 'garage_location' && <span className="text-slate-600"> (garage location)</span>}
                {origin?.source === 'home_address' && <span className="text-slate-600"> (home)</span>}
                {originLat ? <span className="text-slate-600 font-mono ml-1">({originLat.toFixed(4)}, {originLon.toFixed(4)})</span>
                  : <span className="text-amber-500 ml-1">no GPS</span>}
              </div>
              <ArrowRight className="w-3.5 h-3.5 text-slate-600 shrink-0" />
              <div className="min-w-0 flex-1">
                <span className="text-slate-600">To:</span>{' '}
                <span className="text-slate-200 font-medium">{destCity || 'Unknown'}</span>
                {destLat ? <span className="text-slate-600 font-mono ml-1">({destLat.toFixed(4)}, {destLon.toFixed(4)})</span>
                  : <span className="text-amber-500 ml-1">no GPS on WO</span>}
              </div>
            </div>
          )}
          {googleMapsLink && (
            <a href={googleMapsLink} target="_blank" rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-brand-400 hover:text-brand-300 underline">
              <MapPin className="w-3 h-3" />{isTow ? 'Verify tow route on Google Maps' : 'Verify route on Google Maps'}
            </a>
          )}
          {/* Note when SF Recorded is much higher than our Google calc — driver may have been elsewhere */}
          {!isTow && googleMi && sfMi > 0 && sfMi > googleMi * 1.5 && (
            <div className="text-[9px] text-amber-400 mt-1">
              SF recorded {sfMi} mi at En Route but our calc shows {googleMi} mi — driver may have been somewhere other than the previous job when dispatched
            </div>
          )}
        </div>
      )}

      {/* ── ROW 3: Two-column — Distance Check + WO Context ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">

        {/* Left: Verification — adapts to product type */}
        <div className="glass rounded-xl border border-slate-700/30 p-4 space-y-3">
          <div className="text-[10px] text-slate-500 uppercase tracking-wider font-bold">
            {isTime ? 'Time Verification' : code === 'MH' ? 'Heavy Vehicle Verification'
              : code === 'TL' ? 'Toll / Receipt Verification' : isFlat ? 'Service Verification'
              : isTow ? 'Tow Distance Verification' : 'Distance Verification'}
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
            {ev.currently_paid > 0 && ev.requested != null && (
              <div className="flex justify-between">
                <span className="text-slate-400">Delta</span>
                <span className={clsx('font-bold', (ev.requested - ev.currently_paid) > 0 ? 'text-amber-400' : 'text-emerald-400')}>
                  {(ev.requested - ev.currently_paid) > 0 ? '+' : ''}{(ev.requested - ev.currently_paid).toFixed(2)} {UNITS[code] || ''}
                </span>
              </div>
            )}

            {/* Distance-specific fields */}
            {isMileage && !isTow && (
              <>
                <div className="border-t border-slate-800/50 pt-1.5 mt-1.5" />
                {googleMi != null && (
                  <div className="flex justify-between">
                    <span className="text-slate-400">Google Maps (our calc)</span>
                    <span className="font-bold text-brand-300">{googleMi} mi</span>
                  </div>
                )}
                <div className="flex justify-between">
                  <span className="text-slate-400">SF Recorded (at En Route)</span>
                  <span className={clsx('font-bold', ev.sf_enroute_miles > 0 ? 'text-slate-300' : 'text-amber-400')}>
                    {ev.sf_enroute_miles != null ? `${ev.sf_enroute_miles} mi` : 'N/A'}{ev.sf_enroute_miles === 0 ? ' — bad status?' : ''}
                  </span>
                </div>
                {ev.sf_estimated_miles != null && ev.sf_estimated_miles > 0 && (
                  <div className="flex justify-between">
                    <span className="text-slate-400">SF Google Est (pre-dispatch)</span>
                    <span className="font-bold text-slate-300">{ev.sf_estimated_miles} mi</span>
                  </div>
                )}
              </>
            )}
            {/* Tow-specific fields */}
            {isTow && (
              <>
                <div className="border-t border-slate-800/50 pt-1.5 mt-1.5" />
                <div className="flex justify-between">
                  <span className="text-slate-400">SF Tow Miles (recorded)</span>
                  <span className={clsx('font-bold', ev.sf_tow_miles > 0 ? 'text-slate-300' : 'text-amber-400')}>
                    {ev.sf_tow_miles != null ? `${ev.sf_tow_miles} mi` : 'N/A'}
                  </span>
                </div>
                {ev.sf_estimated_tow_miles != null && ev.sf_estimated_tow_miles > 0 && (
                  <div className="flex justify-between">
                    <span className="text-slate-400">SF Tow Est (pre-dispatch)</span>
                    <span className="font-bold text-slate-300">{ev.sf_estimated_tow_miles} mi</span>
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
                <div className="flex justify-between">
                  <span className="text-slate-400">On-Scene Time (actual)</span>
                  <span className="font-bold text-slate-300">{ev.on_location_minutes != null ? `${ev.on_location_minutes} min` : 'N/A'}</span>
                </div>
              </>
            )}

            {/* MH-specific: vehicle weight & group */}
            {code === 'MH' && (
              <>
                <div className="border-t border-slate-800/50 pt-1.5 mt-1.5" />
                <div className="flex justify-between">
                  <span className="text-slate-400">Vehicle</span>
                  <span className="font-bold text-slate-300">{vehicle || 'N/A'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Vehicle Group</span>
                  <span className={clsx('font-bold', ['DW', 'HD'].includes(ev.vehicle_group) ? 'text-emerald-400' : 'text-amber-400')}>
                    {ev.vehicle_group || 'N/A'}
                    {['DW', 'HD'].includes(ev.vehicle_group) && ' — Heavy duty confirmed'}
                    {ev.vehicle_group === 'PS' && ' — Passenger (not heavy)'}
                  </span>
                </div>
                {ev.vehicle_weight > 0 && (
                  <div className="flex justify-between">
                    <span className="text-slate-400">Weight</span>
                    <span className="font-bold text-slate-300">{ev.vehicle_weight} lbs</span>
                  </div>
                )}
              </>
            )}

            {/* TL: receipt + tow context */}
            {code === 'TL' && (
              <div className="mt-2 space-y-1.5">
                <div className="px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-700/30 text-[10px] text-amber-300">
                  No receipts in SF — request receipt from garage to verify.
                </div>
                {audit.woli_items?.some(w => TOW_CODES.has(w.code)) ? (
                  <div className="px-3 py-2 rounded-lg bg-emerald-500/10 border border-emerald-700/30 text-[10px] text-emerald-300">
                    Tow exists on this WO — tolls plausible if route crosses toll road.
                  </div>
                ) : (
                  <div className="px-3 py-2 rounded-lg bg-slate-800/40 border border-slate-700/30 text-[10px] text-slate-400">
                    No tow on this WO — tolls less likely (unless parking/airport).
                  </div>
                )}
              </div>
            )}

            {/* Flat fee / service event */}
            {isFlat && !isMileage && !isTime && code !== 'TL' && code !== 'MH' && (
              <div className="mt-2 px-3 py-2 rounded-lg bg-slate-800/40 border border-slate-700/30 text-[10px] text-slate-300">
                {PRODUCT_NAMES[code] || code} — flat fee or service event. Verify the service was performed on this Work Order.
              </div>
            )}
          </div>

          {/* Comparison ratio bar */}
          {mileRatio != null && (
            <div className={clsx('flex items-center gap-3 px-3 py-2 rounded-lg border', mileBg)}>
              <span className="text-[10px] text-slate-500">vs {baselineLabel} ({baseline} mi):</span>
              <span className={clsx('font-bold text-lg leading-none', mileColor)}>{mileRatio.toFixed(0)}%</span>
              <span className={clsx('text-[10px] font-semibold', mileColor)}>
                {mileRatio <= 130 ? '≤130% → PAY' : mileRatio <= 150 ? '130–150% → REVIEW' : '>150% → FLAG'}
              </span>
            </div>
          )}
          {timeRatio != null && (
            <div className={clsx('flex items-center gap-3 px-3 py-2 rounded-lg border',
              timeRatio <= 120 ? 'bg-emerald-500/10 border-emerald-700/30' : 'bg-amber-500/10 border-amber-700/30')}>
              <span className="text-[10px] text-slate-500">Ratio:</span>
              <span className={clsx('font-bold text-lg leading-none', timeColor)}>{timeRatio.toFixed(0)}%</span>
              <span className={clsx('text-[10px] font-semibold', timeColor)}>
                {timeRatio <= 120 ? '≤120% → PAY' : '>120% → REVIEW'}
              </span>
            </div>
          )}
        </div>

        {/* Right: WO Context — everything the auditor needs to know about this WO */}
        <div className="glass rounded-xl border border-slate-700/30 p-4 space-y-3">
          <div className="text-[10px] text-slate-500 uppercase tracking-wider font-bold">WO Context</div>

          {/* Work Order Line Items + WO Pricing */}
          {audit.woli_items?.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-1">
                <span className="text-[9px] text-slate-600 uppercase tracking-wider">Work Order Line Items ({audit.woli_items.length})</span>
                {urls.wo && <a href={urls.wo} target="_blank" rel="noopener noreferrer" className="text-[9px] text-brand-400 hover:underline">View in SF ↗</a>}
              </div>
              <div className="text-[9px] text-slate-600 grid grid-cols-[60px_1fr_50px_55px_65px] gap-1 pb-1 border-b border-slate-800/50">
                <span>Name</span><span>Product</span><span className="text-right">Quantity</span><span className="text-right">Tax Amt</span><span className="text-right">Grand Total</span>
              </div>
              {audit.woli_items.map((wl, i) => (
                <div key={i} className="grid grid-cols-[60px_1fr_50px_55px_65px] gap-1 text-[10px] py-0.5 items-center">
                  {wl.id ? (
                    <a href={`https://aaawcny.lightning.force.com/${wl.id}`} target="_blank" rel="noopener noreferrer"
                      className="font-mono text-brand-400 hover:text-brand-300 hover:underline">{wl.name || '—'}</a>
                  ) : (
                    <span className="font-mono text-slate-500">{wl.name || '—'}</span>
                  )}
                  <span className="text-slate-300 truncate">{wl.product || <span className="text-slate-600 italic">dispatch</span>}</span>
                  <span className="text-right font-mono text-slate-300">{wl.quantity != null ? wl.quantity : ''}</span>
                  <span className="text-right font-mono text-slate-400">{wl.tax != null ? `$${wl.tax.toFixed(2)}` : wl.grand_total != null ? '$0' : ''}</span>
                  <span className="text-right font-mono font-semibold text-slate-200">{wl.grand_total != null ? `$${wl.grand_total.toFixed(2)}` : ''}</span>
                </div>
              ))}
            </div>
          )}
          {/* WO Pricing (from WorkOrder, not WOLI) */}
          {audit.wo_pricing && (audit.wo_pricing.basic_cost > 0 || audit.wo_pricing.total_invoiced > 0) && (
            <div>
              <div className="text-[9px] text-slate-600 uppercase tracking-wider mb-1">WO Pricing</div>
              <div className="space-y-0.5 text-[10px]">
                {audit.wo_pricing.basic_cost > 0 && <div className="flex justify-between"><span className="text-slate-400">Basic Cost</span><span className="font-mono text-slate-200">${audit.wo_pricing.basic_cost.toFixed(2)}</span></div>}
                {audit.wo_pricing.plus_cost > 0 && <div className="flex justify-between"><span className="text-slate-400">Plus Cost</span><span className="font-mono text-slate-200">${audit.wo_pricing.plus_cost.toFixed(2)}</span></div>}
                {audit.wo_pricing.other_cost > 0 && <div className="flex justify-between"><span className="text-slate-400">Other Cost</span><span className="font-mono text-slate-200">${audit.wo_pricing.other_cost.toFixed(2)}</span></div>}
                {audit.wo_pricing.tax > 0 && <div className="flex justify-between"><span className="text-slate-400">Tax</span><span className="font-mono text-slate-200">${audit.wo_pricing.tax.toFixed(2)}</span></div>}
                {audit.wo_pricing.grand_total > 0 && <div className="flex justify-between border-t border-slate-700/30 pt-0.5"><span className="text-slate-300 font-bold">Grand Total</span><span className="font-mono font-bold text-white">${audit.wo_pricing.grand_total.toFixed(2)}</span></div>}
                {audit.wo_pricing.total_invoiced > 0 && <div className="flex justify-between"><span className="text-slate-400">Total Invoiced</span><span className="font-mono text-emerald-400">${audit.wo_pricing.total_invoiced.toFixed(2)}</span></div>}
              </div>
            </div>
          )}
          {audit.woli_items?.length === 0 && (
            <div className="text-[10px] text-amber-400">No line items on WO — new charge being added</div>
          )}

          {/* Vehicle */}
          <div>
            <div className="text-[9px] text-slate-600 uppercase tracking-wider mb-1">Vehicle</div>
            <div className="text-[10px] text-slate-300">
              {vehicle || <span className="text-slate-600">No vehicle data on WO</span>}
              {ev.vehicle_weight > 0 && <span className="text-slate-500 ml-2">({ev.vehicle_weight} lbs)</span>}
            </div>
          </div>

          {/* On-scene + Status */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="text-[9px] text-slate-600 uppercase tracking-wider mb-1">On-Scene Time</div>
              <div className="text-[10px] font-bold text-slate-300">
                {ev.on_location_minutes != null ? `${ev.on_location_minutes} min` : 'N/A'}
              </div>
            </div>
            <div>
              <div className="text-[9px] text-slate-600 uppercase tracking-wider mb-1">Status Quality</div>
              <div className={clsx('text-[10px] font-bold', status.startsWith('BAD') ? 'text-red-400' : 'text-emerald-400')}>
                {status || 'N/A'}
              </div>
            </div>
          </div>

          {/* Garage Note */}
          {ev.garage_note && (
            <div>
              <div className="text-[9px] text-slate-600 uppercase tracking-wider mb-1">Garage Note</div>
              <div className="text-[10px] text-slate-300 bg-slate-800/40 rounded px-2 py-1.5">{ev.garage_note}</div>
            </div>
          )}

          {/* Driver */}
          {audit.evidence?.driver && (
            <div className="text-[10px] text-slate-500">
              Driver: <span className="text-slate-300">{audit.evidence.driver}</span>
            </div>
          )}
        </div>
      </div>

      {/* ── What to verify (REVIEW only) ── */}
      {/* ── Auditor Summary — narrative + action items combined ── */}
      {(localSummary || (rec === 'REVIEW' && audit.ask_garage?.length > 0)) && (
        <div className="glass rounded-xl border border-slate-700/20 px-4 py-3">
          <div className="text-[10px] text-slate-400 uppercase tracking-wider font-bold mb-2">Auditor Summary</div>
          {localSummary && (
            <div className="text-[11px] text-slate-300 leading-relaxed space-y-1.5">
              {localSummary.split('\n\n').map((para, i) => (
                <p key={i} className={/^(RED FLAG|SIGNIFICANT|DRIVER STATUS)/.test(para) ? 'text-red-300 bg-red-950/20 px-3 py-2 rounded-lg border border-red-800/30' : ''}>{para}</p>
              ))}
            </div>
          )}
          {rec === 'REVIEW' && audit.ask_garage?.length > 0 && (
            <div className="mt-2 pt-2 border-t border-slate-700/30">
              <div className="text-[10px] text-amber-400 font-bold mb-1">Next Steps:</div>
              {audit.ask_garage.map((item, i) => (
                <div key={i} className="text-[10px] text-slate-300 flex items-start gap-2">
                  <span className="text-amber-400">-</span>{item}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      {showAi && (
        <details className="glass rounded-xl border border-blue-800/20">
          <summary className="px-4 py-2.5 text-[10px] text-blue-400 uppercase tracking-wider font-bold cursor-pointer hover:bg-blue-900/10">AI Analysis</summary>
          <div className="px-4 pb-3 text-[11px] text-slate-300 leading-relaxed whitespace-pre-line">{aiText}</div>
        </details>
      )}
      {timeline.length > 0 && (
        <details className="glass rounded-xl border border-slate-700/20">
          <summary className="px-4 py-2.5 text-[10px] text-slate-400 uppercase tracking-wider font-bold cursor-pointer hover:bg-slate-800/30">SA Timeline ({timeline.length} events)</summary>
          <div className="px-4 pb-3 space-y-0.5">
            {timeline.map((step, i) => (
              <div key={i} className="flex items-center gap-3 text-[10px] py-1 px-2 rounded bg-slate-800/30">
                <span className="text-slate-600 font-mono w-40 shrink-0">{step.time || '--'}</span>
                <span className="text-slate-500 shrink-0">{step.from || ''} →</span>
                <span className="text-slate-300">{step.to || '--'}</span>
              </div>
            ))}
          </div>
        </details>
      )}

      {/* ── SF Links ── */}
      <div className="flex items-center gap-3 pt-1">
        {urls.woa && (
          <a href={urls.woa} target="_blank" rel="noopener noreferrer"
            className="flex items-center gap-1.5 px-4 py-2 bg-brand-600 hover:bg-brand-500 rounded-lg text-xs font-semibold text-white transition-colors">
            <ExternalLink className="w-3.5 h-3.5" />Open WOA in SF
          </a>
        )}
        {urls.wo && (
          <a href={urls.wo} target="_blank" rel="noopener noreferrer"
            className="flex items-center gap-1.5 px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg text-xs font-semibold text-slate-300 transition-colors">
            <ExternalLink className="w-3.5 h-3.5" />Open Work Order
          </a>
        )}
      </div>
    </div>
  )
}
