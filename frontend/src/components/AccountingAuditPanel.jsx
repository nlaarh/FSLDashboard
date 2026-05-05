import { useState, useEffect } from 'react'
import { clsx } from 'clsx'
import {
  Loader2, AlertTriangle, ExternalLink,
  MapPin, RefreshCw, ArrowRight, Info, Sparkles, ShieldAlert, Lightbulb, CheckSquare,
} from 'lucide-react'
import { fetchWOAAudit, recalculateWOAAudit, fetchAccountingRates, fetchWOAAiAnalysis } from '../api'
import { productCode } from '../utils/formatting'
import { PRODUCT_NAMES, TOW_CODES, TIME_CODES, FLAT_CODES, UNITS, headerSummary, buildLocalSummary } from '../utils/accountingAudit'
import WODiagnosticStrip from './WODiagnosticStrip'
import AuditVerificationCard from './AuditVerificationCard'
import WOAAuditMap from './WOAAuditMap'

const REC_BADGE = {
  PAY:    'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30',
  REVIEW: 'bg-amber-500/15 text-amber-400 border border-amber-500/30',
  DENY:   'bg-red-500/15 text-red-400 border border-red-500/30',
}

const Skeleton = ({ className = '' }) => (
  <div className={`animate-pulse bg-slate-700/30 rounded ${className}`} />
)

const SkeletonCard = () => (
  <div className="glass rounded-xl border border-slate-700/30 p-4 space-y-3">
    <Skeleton className="h-3 w-1/3" />
    <Skeleton className="h-2 w-full" />
    <Skeleton className="h-2 w-4/5" />
    <Skeleton className="h-2 w-2/3" />
    <Skeleton className="h-2 w-3/4" />
  </div>
)

export default function AccountingAuditPanel({ woaId, onComplete, recReason, siblingWoas, allWoSiblings, isLowMateriality, estimatedUsd, rowRec, rowConf, onOpenWoa }) {
  const [audit, setAudit] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [recalcing, setRecalcing] = useState(false)
  const [aiLoading, setAiLoading] = useState(false)
  const [rates, setRates] = useState({})

  useEffect(() => { fetchAccountingRates().then(setRates).catch(() => {}) }, [])

  const handleResult = (data) => {
    setAudit(data)
    if (data?.recommendation) {
      // Normalize to lowercase — audit cache may return uppercase from AI ('APPROVE'/'REVIEW').
      // Apply the same low-materiality override the panel will show, so badge stays in sync.
      const rawRec = (data.recommendation || '').toLowerCase()
      const effRec = (isLowMateriality && rawRec === 'review') ? 'approve' : rawRec
      onComplete?.(woaId, { recommendation: effRec, confidence: data.confidence, summary: data.ai_summary || '' })
    }
    // If AI not yet loaded (data-only response), fetch it separately
    if (!data?.ai_headline && !data?.ai_story) {
      setAiLoading(true)
      fetchWOAAiAnalysis(woaId)
        .then(ai => setAudit(prev => prev ? { ...prev, ...ai, recommendation: prev.recommendation, rec_reason: prev.rec_reason } : prev))
        .catch(() => {})
        .finally(() => setAiLoading(false))
    }
  }
  const load = (fetcher) => { setLoading(true); setError(null); fetcher(woaId).then(handleResult).catch(e => setError(e.message || 'Failed')).finally(() => setLoading(false)) }
  useEffect(() => { load(fetchWOAAudit) }, [woaId])
  const handleRecalculate = () => { setRecalcing(true); recalculateWOAAudit(woaId).then(handleResult).catch(e => setError(e.message || 'Failed')).finally(() => setRecalcing(false)) }

  // Map list rec (approve/review/deny) → audit badge key (PAY/REVIEW/DENY)
  const initRec = rowRec === 'approve' ? 'PAY' : (rowRec || 'REVIEW').toUpperCase()

  if (loading) return (
    <div className="px-6 py-4 space-y-3 bg-slate-900/40">
      <SkeletonCard />
    </div>
  )
  if (error) return <div className="flex items-center justify-center gap-2 py-8"><AlertTriangle className="w-4 h-4 text-red-400" /><span className="text-xs text-red-400">{error}</span></div>
  if (!audit) return null

  const recRaw = (audit.recommendation || initRec || 'REVIEW').toUpperCase()
  // If low-materiality override was applied in the list, honour it here too
  const displayRec = (isLowMateriality && recRaw === 'REVIEW') ? 'APPROVE' : recRaw
  const rec = displayRec === 'APPROVE' ? 'PAY' : displayRec
  // AI recommendation is stored separately (ai_recommendation) — rule engine owns 'recommendation'
  const aiRecRaw = audit.ai_recommendation ? audit.ai_recommendation.toUpperCase() : null
  const aiRec = aiRecRaw === 'APPROVE' ? 'PAY' : aiRecRaw
  const aiRecDiffers = aiRec && aiRec !== rec
  const urls = audit?.sf_urls || {}
  const timeline = audit?.sa_timeline || []
  const ev = audit?.evidence || {}
  const code = productCode(ev.product)

  const isStale = !('call_location_city' in ev)
  const origin = ev.truck_prev_location
  const originCity = [origin?.city, origin?.state].filter(Boolean).join(', ')
  const destCity = [ev.call_location_city, ev.call_location_state].filter(Boolean).join(', ')
  const originLat = origin?.lat, originLon = origin?.lon
  // WO.Latitude is null for some calls (not geocoded in SF).
  // Fall back to SA on-location GPS (driver's tap = same spot as breakdown).
  const _saLat = ev.sa_on_location_lat > 0 ? ev.sa_on_location_lat : null
  const _saLon = ev.sa_on_location_lat > 0 ? ev.sa_on_location_lon : null
  const _rflibLat = ev.rflib_on_location?.lat > 0 ? ev.rflib_on_location.lat : null
  const _rflibLon = ev.rflib_on_location?.lat > 0 ? ev.rflib_on_location.lon : null
  const destLat = ev.call_location_lat || _saLat || _rflibLat || null
  const destLon = ev.call_location_lon || _saLon || _rflibLon || null

  const isTow = TOW_CODES.has(code)
  const isMileage = code === 'ER' || isTow || (!code && ev.sf_enroute_miles != null)
  const isTime = TIME_CODES.has(code)
  const isFlat = FLAT_CODES.has(code)
  const googleMi = ev.google_distance_miles
  const googleTowMi = ev.google_tow_distance_miles
  const sfMi = isTow ? ev.sf_tow_miles : ev.sf_enroute_miles
  const sfEst = isTow ? ev.sf_estimated_tow_miles : ev.sf_estimated_miles
  const vehicle = [ev.vehicle_make, ev.vehicle_model].filter(Boolean).join(' ')
  const status = ev.status_quality || ''

  // Tow destination for TW products
  const towDestLat = ev.tow_destination_lat, towDestLon = ev.tow_destination_lon

  // Ratios — baseline priority:
  //   ER: Google (truck GPS → call) → SF estimate → SF recorded
  //   TW: Google (pickup → tow destination) → SF estimate → SF recorded
  const baseline = isTow
    ? (googleTowMi ?? (sfEst > 0 ? sfEst : sfMi > 0 ? sfMi : null))
    : (googleMi ?? (sfEst > 0 ? sfEst : sfMi > 0 ? sfMi : null))
  // WOA.Quantity__c IS the total the garage claims — not additional on top of paid
  const trueTotal = ev.requested != null ? ev.requested : null
  const mileRatio = isMileage && trueTotal != null && baseline ? (trueTotal / baseline * 100) : null
  const baselineLabel = isTow
    ? (googleTowMi ? 'SF Google est (pickup → dest)' : sfEst > 0 ? 'SF tow estimate' : 'SF tow recorded')
    : (googleMi
        ? (origin?.source === 'towbook_gps_enroute' ? 'Google (Towbook GPS)'
           : origin?.source === 'driver_gps_enroute' ? 'Google (driver GPS)'
           : 'Google (prev job)')
        : sfEst > 0 ? 'SF estimate' : 'SF recorded')
  const payPct    = rates?.mileage_pay_pct?.value    ?? 130
  const reviewPct = rates?.mileage_review_pct?.value ?? 150
  const timePct   = rates?.time_pay_pct?.value       ?? 120
  const mileColor = mileRatio == null ? 'text-slate-400'
    : mileRatio <= payPct ? 'text-emerald-400' : mileRatio <= reviewPct ? 'text-amber-400' : 'text-red-400'
  const mileBg = mileRatio == null ? 'bg-slate-800/30 border-slate-700/30'
    : mileRatio <= payPct ? 'bg-emerald-500/10 border-emerald-700/30'
    : mileRatio <= reviewPct ? 'bg-amber-500/10 border-amber-700/30' : 'bg-red-500/10 border-red-700/30'
  const timeRatio = isTime && ev.requested != null && ev.on_location_minutes ? (ev.requested / ev.on_location_minutes * 100) : null
  const timeColor = timeRatio == null ? 'text-slate-400' : timeRatio <= timePct ? 'text-emerald-400' : 'text-amber-400'

  // Cross-WOA combined exposure when multiple adjustments for same product exist on this WO
  const hasSiblings = siblingWoas?.length > 0
  const isDupeRisk = hasSiblings && siblingWoas.some(s => s.is_possible_duplicate)
  const combinedAdditional = hasSiblings
    ? (ev.requested || 0) + siblingWoas.reduce((sum, s) => sum + (s.requested_qty || 0), 0)
    : null
  const combinedTrueTotal = combinedAdditional != null ? (ev.currently_paid || 0) + combinedAdditional : null
  const combinedPct = combinedTrueTotal != null && baseline ? (combinedTrueTotal / baseline * 100) : null
  const combinedColor = combinedPct == null ? 'text-amber-300'
    : combinedPct <= payPct ? 'text-emerald-400' : combinedPct <= reviewPct ? 'text-amber-400' : 'text-red-400'

  // Google Maps link: TW = call→tow destination, ER = truck→call (requires both GPS)
  const googleMapsLink = isTow
    ? (destLat && towDestLat ? `https://www.google.com/maps/dir/${destLat},${destLon}/${towDestLat},${towDestLon}` : null)
    : (originLat && destLat ? `https://www.google.com/maps/dir/${originLat},${originLon}/${destLat},${destLon}` : null)
  // Fallback pin link — when we have destination but no origin GPS
  const destPinLink = !googleMapsLink && destLat ? `https://www.google.com/maps?q=${destLat},${destLon}` : null

  const localSummary = buildLocalSummary(ev, audit?.woli_items, rates)
  const aiText = audit.ai_summary
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

      {/* Low materiality banner */}
      {isLowMateriality && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-emerald-500/10 border border-emerald-700/30">
          <Info className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
          <span className="text-[10px] text-emerald-300">
            <strong>Low materiality</strong> — estimated impact{' '}
            {estimatedUsd != null ? `$${estimatedUsd.toFixed(2)}` : ''} is below the configured threshold.
            {' '}No detailed review needed — approve in Salesforce.
          </span>
        </div>
      )}
      <div className="flex items-center gap-3 flex-wrap">
        <span className={clsx('px-4 py-1.5 rounded-lg text-sm font-bold uppercase tracking-wide', REC_BADGE[rec] || REC_BADGE.REVIEW)}>
          {rec || 'UNKNOWN'}
        </span>
        {ev.woa_type && (
          <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-700/60 text-slate-300 border border-slate-600/40 shrink-0">
            {ev.woa_type}
          </span>
        )}
        <span className="text-xs text-slate-300 flex-1 min-w-0 truncate">
          {audit ? headerSummary(ev, code) : (recReason || <span className="text-slate-600 italic">Loading details…</span>)}
        </span>
        {(audit?.confidence || rowConf) && (
          <span className="text-[10px] text-slate-600 shrink-0">
            Conf: <span className="text-slate-400 font-semibold">{audit?.confidence || rowConf}</span>
          </span>
        )}
        <button onClick={handleRecalculate} disabled={recalcing}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[10px] font-medium bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white transition-colors disabled:opacity-50 shrink-0">
          <RefreshCw className={clsx('w-3 h-3', recalcing && 'animate-spin')} />
          {recalcing ? 'Working…' : 'Recalculate'}
        </button>
        <a href={`/api/accounting/wo-adjustments/${woaId}/pdf`} target="_blank" rel="noreferrer"
          className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] font-medium bg-slate-800 hover:bg-blue-700 text-slate-400 hover:text-white transition-colors shrink-0">
          PDF
        </a>
      </div>
      {audit?.rec_reason && <div className="text-[10px] text-slate-500 px-1">{(audit.rec_reason.split('\n').filter(l=>l.startsWith('→')).pop()||'').slice(2).trim()}</div>}
      {isLowMateriality && recRaw === 'REVIEW' && (
        <div className="text-[9px] text-slate-500 px-1">Auto-approved: below materiality threshold</div>
      )}
      {aiRecDiffers && (
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/50 border border-slate-700/30">
          <span className="text-[9px] text-slate-500">AI assessed:</span>
          <span className={clsx('text-[9px] font-bold uppercase', REC_BADGE[aiRec] || REC_BADGE.REVIEW, 'px-1.5 py-0.5 rounded')}>
            {aiRec}
          </span>
          <span className="text-[9px] text-slate-600">— rule engine takes precedence</span>
        </div>
      )}
      {status.startsWith('BAD') && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-700/30">
          <AlertTriangle className="w-3.5 h-3.5 text-red-400 shrink-0" />
          <span className="text-[10px] text-red-300">{status} — SF distance data is unreliable for this call</span>
        </div>
      )}
      {ev.same_member_same_day?.length > 0 && (
        <div className="flex items-start gap-2 px-3 py-2.5 rounded-lg bg-purple-500/10 border border-purple-600/30">
          <AlertTriangle className="w-3.5 h-3.5 text-purple-400 shrink-0 mt-0.5" />
          <div className="text-[10px] text-purple-300 leading-relaxed">
            <strong>Same member, same day:</strong> This member had {ev.same_member_same_day.length} other service call{ev.same_member_same_day.length > 1 ? 's' : ''} on the same date.{' '}
            {ev.same_member_same_day.map((c, i) => (
              <span key={i}>
                {i > 0 && ' · '}
                <span className="font-mono">WO#{c.wo_number}</span>
                {c.trouble_code && ` (TC:${c.trouble_code})`}
                {c.territory && `, ${c.territory}`}
              </span>
            ))}
            . Verify each call is for a distinct breakdown event — same-day multi-call is uncommon and may indicate duplicate billing.
          </div>
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-2 text-[10px] text-slate-500">
          <Loader2 className="w-3 h-3 animate-spin text-brand-400" />Loading audit details…
        </div>
      )}

      {audit && <WODiagnosticStrip ev={ev} sfUrls={urls} />}

      {!audit && (
        <div className="grid grid-cols-4 gap-3">
          <SkeletonCard /><SkeletonCard /><SkeletonCard /><SkeletonCard />
        </div>
      )}

      {/* ── ROW 2: Route card — only for mileage products (ER/TW). E1/MI/BA etc. don't use distance. ── */}
      {audit && !isStale && isMileage && (origin || destCity) && (
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
          ) : originLat ? (
            /* ER with GPS origin — show full truck → call route */
            <div className="flex items-center gap-4">
              <div className="min-w-0 flex-1">
                <span className="text-slate-600">From:</span>{' '}
                <span className="text-slate-200 font-medium">{originCity || 'Unknown'}</span>
                {origin?.source === 'driver_gps_enroute' && <span className="text-emerald-500"> (driver GPS at En Route)</span>}
                {origin?.source === 'towbook_gps_enroute' && <span className="text-emerald-500"> (Towbook GPS at En Route)</span>}
                {origin?.source === 'towbook_gps_dispatched' && <span className="text-emerald-500"> (Towbook GPS at Dispatch)</span>}
                {origin?.source === 'previous_job' && <span className="text-slate-600"> (estimated — last known job)</span>}
                {origin?.source === 'garage_location' && <span className="text-slate-600"> (garage location)</span>}
                {origin?.source === 'home_address' && <span className="text-slate-600"> (home)</span>}
                <span className="text-slate-600 font-mono ml-1">({originLat.toFixed(4)}, {originLon.toFixed(4)})</span>
              </div>
              <ArrowRight className="w-3.5 h-3.5 text-slate-600 shrink-0" />
              <div className="min-w-0 flex-1">
                <span className="text-slate-600">To:</span>{' '}
                <span className="text-slate-200 font-medium">{destCity || 'Unknown'}</span>
                {destLat ? <span className="text-slate-600 font-mono ml-1">({destLat.toFixed(4)}, {destLon.toFixed(4)})</span>
                  : <span className="text-amber-500 ml-1">no GPS on WO</span>}
              </div>
            </div>
          ) : (
            /* ER no origin GPS — show call location only, no From→To */
            <div>
              <span className="text-slate-600">Call location:</span>{' '}
              <span className="text-slate-200 font-medium">{destCity || 'Unknown'}</span>
              {destLat ? <span className="text-slate-600 font-mono ml-1">({destLat.toFixed(4)}, {destLon.toFixed(4)})</span>
                : <span className="text-amber-500 ml-1">no GPS on WO</span>}
              <span className="text-amber-500 ml-2">· truck origin GPS unavailable</span>
            </div>
          )}
          {/* On-location GPS from SA (Fleet FSL app tap) */}
          {ev.sa_on_location_lat && (
            <div className="flex items-center gap-2">
              <span className="text-slate-600">Driver On-Location GPS:</span>
              <span className="text-emerald-400 font-mono text-[9px]">({ev.sa_on_location_lat.toFixed(4)}, {ev.sa_on_location_lon.toFixed(4)})</span>
              <a href={`https://www.google.com/maps?q=${ev.sa_on_location_lat},${ev.sa_on_location_lon}`}
                target="_blank" rel="noopener noreferrer"
                className="text-[9px] text-brand-400 hover:text-brand-300 underline flex items-center gap-0.5">
                <MapPin className="w-2.5 h-2.5" />Pin ↗
              </a>
              <span className="text-[9px] text-slate-600">(SA.On_Location_Geolocation — FSL app tap)</span>
            </div>
          )}
          {googleMapsLink && (
            <a href={googleMapsLink} target="_blank" rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-brand-400 hover:text-brand-300 underline">
              <MapPin className="w-3 h-3" />{isTow ? 'Verify tow route on Google Maps' : 'Verify route on Google Maps'}
            </a>
          )}
          {destPinLink && (
            <a href={destPinLink} target="_blank" rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-slate-400 hover:text-slate-300 underline">
              <MapPin className="w-3 h-3" />View call location on Google Maps
            </a>
          )}
          {/* Note when SF Recorded is much higher than our Google calc */}
          {!isTow && googleMi && sfMi > 0 && sfMi > googleMi * 1.5 && (
            <div className="text-[9px] text-amber-400 mt-1">
              SF recorded {sfMi} mi but Google route shows {googleMi} mi —{' '}
              {(origin?.source === 'towbook_gps_enroute' || origin?.source === 'driver_gps_enroute')
                ? 'origin is actual driver GPS — driver may have taken a longer route or SF recording is off'
                : 'driver may have been somewhere other than the estimated origin when dispatched'}
            </div>
          )}
        </div>
      )}

      {/* ── Call location pin for time products (MI/E1/E2/Z8) — no route to verify, but show where the job was ── */}
      {audit && !isStale && isTime && (ev.call_location_city || destLat) && (
        <div className="px-4 py-2 rounded-xl bg-slate-800/30 border border-slate-700/20 text-[10px] flex items-center gap-3">
          <span className="text-slate-600">Call Location:</span>
          <span className="text-slate-200 font-medium">
            {[ev.call_location_city, ev.call_location_state].filter(Boolean).join(', ') || 'Unknown'}
          </span>
          {destLat && (
            <>
              <span className="text-slate-600 font-mono">({destLat.toFixed(4)}, {destLon.toFixed(4)})</span>
              <a href={`https://www.google.com/maps?q=${destLat},${destLon}`} target="_blank" rel="noopener noreferrer"
                className="text-brand-400 hover:text-brand-300 underline flex items-center gap-0.5 text-[9px]">
                <MapPin className="w-2.5 h-2.5" />Map ↗
              </a>
            </>
          )}
        </div>
      )}

      {/* ── Multi-WOA combined exposure warning ── */}
      {audit && hasSiblings && (
        <div className={clsx(
          'px-4 py-3 rounded-xl border space-y-2',
          isDupeRisk
            ? 'bg-red-500/10 border-red-600/30'
            : 'bg-amber-500/10 border-amber-600/30',
        )}>
          <div className="flex items-center gap-2">
            <AlertTriangle className={clsx('w-3.5 h-3.5 shrink-0', isDupeRisk ? 'text-red-400' : 'text-amber-400')} />
            <span className={clsx('text-[11px] font-bold', isDupeRisk ? 'text-red-300' : 'text-amber-300')}>
              {isDupeRisk ? 'POSSIBLE DUPLICATE SUBMISSION' : 'MULTIPLE ADJUSTMENTS — SAME PRODUCT'}
              {' · '}{siblingWoas.length + 1} {code} WOAs on this Work Order
            </span>
          </div>

          {/* Per-WOA breakdown */}
          <div className="text-[10px] space-y-0.5">
            <div className="flex justify-between text-slate-300">
              <span>This WOA <span className="text-slate-500">(being audited)</span></span>
              <span className="font-mono font-bold">+{(ev.requested || 0).toFixed(2)} {UNITS[code] || ''}</span>
            </div>
            {siblingWoas.map((s, i) => (
              <div key={i} className="flex justify-between text-slate-400">
                <span className="font-mono">{s.woa_number || '—'}</span>
                <span className="font-mono">+{(s.requested_qty || 0).toFixed(2)} {UNITS[code] || ''}</span>
              </div>
            ))}
          </div>

          {/* Combined impact footer */}
          <div className={clsx('border-t pt-2 flex items-center justify-between gap-4 flex-wrap', isDupeRisk ? 'border-red-700/30' : 'border-amber-700/30')}>
            <span className="text-[10px] text-slate-400">
              If all approved — combined true total:
            </span>
            <span className={clsx('text-sm font-bold', combinedColor)}>
              {combinedTrueTotal?.toFixed(2)} {UNITS[code] || ''}
              {combinedPct != null && (
                <span className="text-[10px] font-normal text-slate-400 ml-2">
                  ({combinedPct.toFixed(0)}% of {baselineLabel})
                </span>
              )}
            </span>
          </div>
        </div>
      )}

      {/* ── 4-column: Verification | WO Context | SA Timeline | Auditor Summary ── */}
      {audit && <div className="grid grid-cols-4 gap-3">

        {/* Left: Verification — product-specific, extracted to AuditVerificationCard */}
        <AuditVerificationCard
          ev={ev} code={code} vehicle={vehicle}
          isTow={isTow} isMileage={isMileage} isTime={isTime} isFlat={isFlat}
          googleMi={googleMi} googleTowMi={googleTowMi} towDestLat={towDestLat} origin={origin}
          trueTotal={trueTotal} baseline={baseline} baselineLabel={baselineLabel}
          mileRatio={mileRatio} mileColor={mileColor} mileBg={mileBg}
          timeRatio={timeRatio} timeColor={timeColor}
          woliItems={audit.woli_items}
          rates={rates}
          allWoSiblings={allWoSiblings}
          onOpenWoa={onOpenWoa}
        />

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
              {audit.wo_pricing?.total_invoiced != null && (
                <div className="flex justify-between items-center border-t border-slate-700/40 pt-1 mt-1">
                  <span className="text-[9px] text-slate-500 uppercase tracking-wider">Total Invoiced (WO)</span>
                  <span className="font-mono font-bold text-emerald-400 text-[11px]">${audit.wo_pricing.total_invoiced.toFixed(2)}</span>
                </div>
              )}
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

          {ev.wo_type && (
            <div>
              <div className="text-[9px] text-slate-600 uppercase tracking-wider mb-1">Service Type</div>
              <div className="text-[10px] font-semibold text-slate-300">{ev.wo_type}</div>
            </div>
          )}

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

        {/* Col 3: SA Timeline */}
        {timeline.length > 0 && (
          <div className="glass rounded-xl border border-slate-700/20 p-4">
            <div className="text-[10px] text-slate-500 uppercase tracking-wider font-bold mb-3">
              SA Timeline <span className="text-slate-600 normal-case font-normal ml-1">({timeline.length} events)</span>
            </div>
            <div className="grid grid-cols-[1fr_auto] text-[9px] text-slate-600 uppercase tracking-wider pb-1.5 border-b border-slate-800/50 gap-x-2 px-1">
              <span>Transition</span><span className="text-right">Elapsed</span>
            </div>
            {timeline.map((step, i) => {
              const sec = step.elapsed_seconds
              let lbl = ''
              if (sec != null) {
                lbl = sec < 60 ? '<1m' : `${Math.floor(sec / 60)}m`
              }
              return (
                <div key={i} className="px-1 py-1.5 border-b border-slate-800/20 last:border-0 hover:bg-slate-800/20 rounded transition-colors">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[10px] text-slate-300 font-medium truncate">
                      {step.from && <span className="text-slate-500 font-normal">{step.from} → </span>}{step.to || '--'}
                    </span>
                    <span className={clsx('font-mono text-[9px] font-bold shrink-0', lbl ? 'text-sky-400' : 'text-slate-600')}>
                      {lbl ? `+${lbl}` : i === 0 ? '—' : ''}
                    </span>
                  </div>
                  <div className="text-[9px] text-slate-600 font-mono mt-0.5">{step.time || ''}</div>
                </div>
              )
            })}
          </div>
        )}

        {/* Col 4: Auditor Summary — full AI when available, local fallback otherwise */}
        {(localSummary || showAi || aiLoading || (rec === 'REVIEW' && audit.ask_garage?.length > 0)) && (
          <div className="glass rounded-xl border border-slate-700/20 px-4 py-3">
            <div className="flex items-center gap-2 mb-2">
              <div className="text-[10px] text-slate-400 uppercase tracking-wider font-bold">Auditor Summary</div>
              {(showAi || aiLoading) && (
                <span className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-blue-500/15 border border-blue-500/30 text-[9px] font-bold text-blue-400 uppercase tracking-wider">
                  <Sparkles className={clsx('w-2.5 h-2.5', aiLoading && 'animate-pulse')} />
                  {aiLoading ? 'AI…' : 'AI'}
                </span>
              )}
            </div>
            {showAi ? (
              <div className="space-y-3">
                {audit.ai_headline && <div className="text-[12px] font-semibold text-slate-200 leading-snug">{audit.ai_headline}</div>}
                {audit.ai_story && <div className="text-[11px] text-slate-300 leading-relaxed">{audit.ai_story}</div>}
                {audit.ai_fraud_signals?.length > 0 && (
                  <div>
                    <div className="flex items-center gap-1.5 mb-1"><ShieldAlert className="w-3 h-3 text-red-400" /><span className="text-[9px] font-bold text-red-400 uppercase tracking-wider">Fraud Signals</span></div>
                    {audit.ai_fraud_signals.map((s, i) => <div key={i} className="flex items-start gap-2 text-[10px] text-red-300"><span className="text-red-500 mt-0.5">●</span>{s}</div>)}
                  </div>
                )}
                {audit.ai_anomalies?.length > 0 && (
                  <div>
                    <div className="flex items-center gap-1.5 mb-1"><Lightbulb className="w-3 h-3 text-amber-400" /><span className="text-[9px] font-bold text-amber-400 uppercase tracking-wider">Anomalies</span></div>
                    {audit.ai_anomalies.map((s, i) => <div key={i} className="flex items-start gap-2 text-[10px] text-amber-300"><span className="text-amber-500 mt-0.5">●</span>{s}</div>)}
                  </div>
                )}
                {audit.ai_what_to_do?.length > 0 && (
                  <div>
                    <div className="flex items-center gap-1.5 mb-1"><CheckSquare className="w-3 h-3 text-emerald-400" /><span className="text-[9px] font-bold text-emerald-400 uppercase tracking-wider">What To Do</span></div>
                    {audit.ai_what_to_do.map((s, i) => <div key={i} className="flex items-start gap-2 text-[10px] text-emerald-300"><span className="text-emerald-600 font-bold mt-0.5">{i + 1}.</span>{s}</div>)}
                  </div>
                )}
              </div>
            ) : localSummary ? (
              <div className="text-[11px] text-slate-300 leading-relaxed space-y-1.5">
                {localSummary.split('\n\n').map((para, i) => (
                  <p key={i} className={/^(RED FLAG|SIGNIFICANT|DRIVER STATUS)/.test(para) ? 'text-red-300 bg-red-950/20 px-3 py-2 rounded-lg border border-red-800/30' : ''}>{para}</p>
                ))}
              </div>
            ) : null}
            {rec === 'REVIEW' && audit.ask_garage?.length > 0 && (
              <div className="mt-2 pt-2 border-t border-slate-700/30">
                <div className="text-[10px] text-amber-400 font-bold mb-1">Next Steps:</div>
                {audit.ask_garage.map((item, i) => (
                  <div key={i} className="text-[10px] text-slate-300 flex items-start gap-2"><span className="text-amber-400">-</span>{item}</div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>}
      {/* ── Route map ── */}
      {audit && (ev.call_location_lat || ev.truck_prev_location) && (
        <div className="space-y-1">
          <div className="text-[10px] text-slate-500 uppercase tracking-wider font-bold px-1">Route Map</div>
          <WOAAuditMap ev={ev} />
          <div className="flex gap-4 text-[9px] text-slate-600 px-1">
            <span><span className="inline-block w-2 h-0.5 bg-slate-400 mr-1" style={{borderTop:'2px dashed'}} />— Truck→Call</span>
            <span><span className="inline-block w-2 h-0.5 bg-purple-400 mr-1" />— Tow Route</span>
            <span>🔴 Breakdown &nbsp; ⬛ Truck origin &nbsp; 🟢 Tow destination</span>
          </div>
        </div>
      )}

      {/* ── SF Links ── */}
      {audit && <div className="flex items-center gap-3 pt-1">
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
      </div>}
    </div>
  )
}
