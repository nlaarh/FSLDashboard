import { useState } from 'react'
import { clsx } from 'clsx'
import { AlertTriangle, ChevronDown, ChevronRight, ExternalLink } from 'lucide-react'

/** Trouble Code labels — actual SF picklist values are numeric strings */
const TC_LABELS = {
  '0': 'Other / Unknown', '1': 'Battery', '3': 'Flat Tire', '3B': 'Flat Tire (variant)',
  '5': 'Fuel Delivery', '5E': 'Fuel (Electric)', '6': 'Tow', '6R': 'Tow (Return)',
  '7': 'Mechanical', '7A': 'Mechanical (A)', '7B': 'Mechanical (B)',
  '8': 'Overturned / Rollover', '8R': 'Overturned (Return)', '9': 'Winching / Extrication',
}
/** Resolution Code labels — X002 triggers alternate ER distance calc */
const RC_LABELS = {
  X002: 'Cancel En Route ⚠', X001: 'GOA — Gone on Arrival',
  N380: 'Service Completed', N101: 'Service Completed',
  N480: 'Service Completed', G931: 'Service Completed',
}
const CC_LABELS = {
  CA1: 'Cancelled by AAA', CA2: 'Cancelled by Member',
  CP1: 'Completed', CP2: 'Completed — Partial',
}

/**
 * WO Diagnostic Strip — always-visible context bar explaining the call classification.
 *
 * Every field shown here comes directly from the Work Order in Salesforce.
 * These values are set by the dispatcher and CANNOT be changed by the garage.
 * They determine which billing rules apply for this adjustment.
 *
 * The collapsible "Source Data" drill-down shows the raw values so auditors
 * can cross-check against the SF Work Order without opening a separate tab.
 */
export default function WODiagnosticStrip({ ev, sfUrls }) {
  const [expanded, setExpanded] = useState(false)

  const tc = ev.trouble_code
  const rc = ev.resolution_code
  const cc = ev.clear_code
  const coverage = ev.coverage
  const contract = ev.contract_name
  const entitlement = ev.entitlement_name
  const facilityId = ev.facility_id
  const isTowCall = ev.tow_call
  const membership = ev.membership_level_coverage
  const axles = ev.axle_count
  const isX002 = ev.is_cancel_en_route
  const woType = ev.wo_type

  const hasAny = tc || rc || cc || coverage || contract || entitlement || facilityId || isTowCall || membership || axles > 0 || woType

  if (!hasAny) return null

  return (
    <div className="rounded-xl bg-slate-800/40 border border-slate-700/20 overflow-hidden">

      {/* ── Main strip ── */}
      <div className="px-4 py-2.5 space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-[9px] text-slate-600 uppercase tracking-wider font-bold">
            WO Classification — set by dispatcher, drives billing rules
          </span>
          <button
            onClick={() => setExpanded(v => !v)}
            className="flex items-center gap-1 text-[9px] text-slate-600 hover:text-slate-400 transition-colors"
            title="Show raw SF field values used to derive this data"
          >
            {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            Source data
          </button>
        </div>

        <div className="flex flex-wrap gap-x-6 gap-y-1.5">
          {/* Codes */}
          {tc && (
            <div className="flex items-baseline gap-1" title="Trouble Code — dispatcher-set reason for the call (WorkOrder.Trouble_Code__c)">
              <span className="text-[9px] text-slate-600 uppercase">Trouble Code:</span>
              <span className="text-[10px] font-semibold text-slate-200">{tc}</span>
              {TC_LABELS[tc] && <span className="text-[10px] text-slate-500">— {TC_LABELS[tc]}</span>}
            </div>
          )}
          {rc && (
            <div
              className={clsx('flex items-baseline gap-1')}
              title="Resolution Code — how the call was resolved (WorkOrder.Resolution_Code__c). X002 = Cancel En Route changes how ER miles are calculated."
            >
              <span className={clsx('text-[9px] uppercase', isX002 ? 'text-amber-600' : 'text-slate-600')}>Resolution:</span>
              <span className={clsx('text-[10px] font-semibold', isX002 ? 'text-amber-300' : 'text-slate-200')}>{rc}</span>
              {RC_LABELS[rc] && <span className={clsx('text-[10px]', isX002 ? 'text-amber-400' : 'text-slate-500')}>— {RC_LABELS[rc]}</span>}
            </div>
          )}
          {cc && (
            <div className="flex items-baseline gap-1" title="Clear Code — final disposition (WorkOrder.Clear_Code__c)">
              <span className="text-[9px] text-slate-600 uppercase">Clear:</span>
              <span className="text-[10px] font-semibold text-slate-200">{cc}</span>
              {CC_LABELS[cc] && <span className="text-[10px] text-slate-500">— {CC_LABELS[cc]}</span>}
            </div>
          )}

          {/* Coverage & entitlement */}
          {coverage && (
            <div className="flex items-baseline gap-1" title="Coverage tier from member's entitlement (WorkOrder.Coverage__c). Determines included miles / services.">
              <span className="text-[9px] text-slate-600 uppercase">Coverage:</span>
              <span className="text-[10px] font-semibold text-emerald-300">{coverage}</span>
            </div>
          )}
          {membership && (
            <div className="flex items-baseline gap-1" title="Membership level computed from entitlement on the Service Appointment (ERS_Membership_Level_Coverage__c — formula).">
              <span className="text-[9px] text-slate-600 uppercase">Level:</span>
              <span className="text-[10px] font-semibold text-slate-200">{membership}</span>
            </div>
          )}
          {contract && (
            <div className="flex items-baseline gap-1" title="Facility Contract tier (WorkOrder.Facility_Contract__r.Name). Sets the rate schedule for this garage.">
              <span className="text-[9px] text-slate-600 uppercase">Contract:</span>
              <span className="text-[10px] font-semibold text-slate-200">{contract}</span>
            </div>
          )}
          {entitlement && (
            <div className="flex items-baseline gap-1" title="Entitlement Master record linked to this WO (WorkOrder.Entitlement_Master__r.Name). Governs coverage limits and call counts.">
              <span className="text-[9px] text-slate-600 uppercase">Entitlement:</span>
              <span className="text-[10px] font-semibold text-slate-200">{entitlement}</span>
            </div>
          )}

          {/* Operational */}
          {facilityId && (
            <div className="flex items-baseline gap-1" title="Facility ID — the garage's AAA ID code (WorkOrder.Facility_ID__c). GAR806 = airport (parking common). Confirm against invoice.">
              <span className="text-[9px] text-slate-600 uppercase">Facility ID:</span>
              <span className="text-[10px] font-mono text-slate-200">{facilityId}</span>
            </div>
          )}
          {woType && (
            <div className="flex items-baseline gap-1" title="Work Type from the Service Appointment linked to this WO (SA.WorkType.Name). Describes the service category performed.">
              <span className="text-[9px] text-slate-600 uppercase">WO Type:</span>
              <span className="text-[10px] font-semibold text-slate-200">{woType}</span>
            </div>
          )}
          {axles > 0 && (
            <div className="flex items-baseline gap-1" title="Number of Axles from vehicle record (WorkOrder.Number_of_Axles__c — formula from vehicle asset). 3+ axles typically qualifies for MH rate.">
              <span className="text-[9px] text-slate-600 uppercase">Axles:</span>
              <span className="text-[10px] font-semibold text-slate-200">{axles}</span>
            </div>
          )}
          {isTowCall && (
            <span
              className="px-2 py-0.5 rounded text-[9px] font-bold bg-blue-500/20 text-blue-300 border border-blue-600/30 uppercase"
              title="Tow Call flag is checked on this Work Order (WorkOrder.Tow_Call__c). Tolls on tow calls may be round-trip."
            >
              TOW CALL
            </span>
          )}
        </div>

        {/* X002 alert */}
        {isX002 && (
          <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-600/30">
            <AlertTriangle className="w-3 h-3 text-amber-400 shrink-0 mt-0.5" />
            <span className="text-[10px] text-amber-300 leading-relaxed">
              <strong>X002 — Cancel En Route:</strong> Driver was dispatched but cancelled before reaching the member.
              ER miles should reflect how far the driver actually traveled (from EN_ROUTE GPS to cancellation point) —
              not the full baseline-to-call distance. If the route card above shows actual driver GPS as origin, that calculation is correct.
              If it falls back to estimated origin, use the Google Maps link to verify manually.
            </span>
          </div>
        )}
      </div>

      {/* ── Collapsible source data drill-down ── */}
      {expanded && (
        <div className="border-t border-slate-700/30 px-4 py-3 bg-slate-900/30 space-y-1.5">
          <div className="text-[9px] text-slate-600 uppercase tracking-wider font-bold mb-2">
            Raw SF Field Values — exactly what Salesforce returned for this Work Order
          </div>
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-[10px]">
            <Row label="Trouble_Code__c (WO)" value={tc} />
            <Row label="Resolution_Code__c (WO)" value={rc} />
            <Row label="Clear_Code__c (WO)" value={cc} />
            <Row label="Coverage__c (WO)" value={coverage} />
            <Row label="Tow_Call__c (WO)" value={isTowCall == null ? null : isTowCall ? 'true' : 'false'} />
            <Row label="Facility_ID__c (WO)" value={facilityId} />
            <Row label="Number_of_Axles__c (WO formula)" value={axles > 0 ? axles : null} />
            <Row label="Facility_Contract__r.Name (WO)" value={contract} />
            <Row label="Entitlement_Master__r.Name (WO)" value={entitlement} />
            <Row label="ERS_Membership_Level_Coverage__c (SA formula)" value={membership} />
            <Row label="WorkType.Name (SA)" value={woType} />
          </div>
          {sfUrls?.wo && (
            <a href={sfUrls.wo} target="_blank" rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-[9px] text-brand-400 hover:text-brand-300 hover:underline mt-1">
              <ExternalLink className="w-2.5 h-2.5" />Verify in Salesforce Work Order ↗
            </a>
          )}
        </div>
      )}
    </div>
  )
}

function Row({ label, value }) {
  if (value == null || value === '') return null
  return (
    <>
      <span className="text-slate-600 font-mono">{label}</span>
      <span className="text-slate-300 font-mono">{String(value)}</span>
    </>
  )
}
