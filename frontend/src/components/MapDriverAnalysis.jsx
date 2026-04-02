import { clsx } from 'clsx'
import { CheckCircle2, XCircle, ChevronDown, ChevronUp, Truck, AlertTriangle } from 'lucide-react'
import { getDriverStatus, NarrativeBlock } from './MapLayers'

export default function MapDriverAnalysis({
  selected, tl, isTowbook, hasSteps, assignSteps, currentStep,
  sortedDrivers, closestDist, showAnalysis, setShowAnalysis, selectedStep, setSelectedStep,
}) {
  return (
    <div className="glass rounded-xl overflow-hidden">
      <button
        onClick={() => setShowAnalysis(v => !v)}
        className="w-full px-4 py-3 bg-slate-800/50 border-b border-slate-700/50 flex items-center justify-between hover:bg-slate-800/70 transition-colors"
      >
        <h4 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-400" />
          {isTowbook
            ? `Call Summary — ${selected.actual_driver || 'Unassigned'}`
            : hasSteps && currentStep
              ? `Driver Positions at ${currentStep.time} — ${currentStep.step_drivers?.length || 0} drivers on Track`
              : `Driver Analysis — ${selected.eligible_count} eligible of ${selected.total_drivers} drivers`}
        </h4>
        <div className="flex items-center gap-3">
          {!isTowbook && (hasSteps && currentStep
            ? <span className="text-xs text-green-400 font-semibold">
                Closest: {currentStep.step_drivers?.find(d => d.is_closest)?.name || '?'}
                {' '}({(currentStep.step_drivers?.find(d => d.is_closest)?.distance ?? '?')} mi)
              </span>
            : <span className="text-xs text-green-400 font-semibold">Closest: {selected.closest_driver} ({selected.closest_distance?.toFixed(1)} mi)</span>
          )}
          {showAnalysis ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
        </div>
      </button>

      {showAnalysis && (
        <>
          {/* Narrative */}
          <div className="px-4 py-3 bg-slate-900/50 border-b border-slate-800/50">
            <NarrativeBlock selected={selected} tl={tl} assignSteps={assignSteps} hasSteps={hasSteps} />
          </div>

          {/* Driver info */}
          {isTowbook ? (
            <TowbookDriverInfo selected={selected} />
          ) : hasSteps ? (
            <StepDriverInfo assignSteps={assignSteps} selectedStep={selectedStep} setSelectedStep={setSelectedStep} />
          ) : (
            <DriverTable sortedDrivers={sortedDrivers} closestDist={closestDist} />
          )}
        </>
      )}
    </div>
  )
}

function TowbookDriverInfo({ selected }) {
  return (
    <div className="px-4 py-3">
      <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-2">Assigned Driver</div>
      {(selected.assign_events || []).length > 0 ? (
        <div className="space-y-1.5">
          {selected.assign_events.map((ev, i) => (
            <div key={i} className="flex items-center gap-2 text-xs">
              <Truck className="w-3.5 h-3.5 text-orange-400 shrink-0" />
              <span className="text-orange-300 font-medium">{ev.driver}</span>
              <span className="text-slate-600">{ev.time}</span>
              {ev.is_reassignment && <span className="text-[9px] text-amber-400">{ev.reason || 'reassigned'}</span>}
              {ev.is_human && ev.by_name && <span className="text-[9px] text-slate-500">by {ev.by_name}</span>}
            </div>
          ))}
        </div>
      ) : selected.actual_driver ? (
        <div className="flex items-center gap-2 text-xs">
          <Truck className="w-3.5 h-3.5 text-orange-400 shrink-0" />
          <span className="text-orange-300 font-medium">{selected.actual_driver}</span>
        </div>
      ) : (
        <div className="text-xs text-slate-600">No driver assigned</div>
      )}
    </div>
  )
}

function StepDriverInfo({ assignSteps, selectedStep, setSelectedStep }) {
  return (
    <div className="divide-y divide-slate-800/50">
      {assignSteps.map((step, stepIdx) => {
        const isOpen = selectedStep === stepIdx
        const assigned = step.step_drivers?.find(d => d.is_assigned)
        const closest  = step.step_drivers?.find(d => d.is_closest)
        const notClosest = assigned && closest && assigned.driver_id !== closest.driver_id
        const others = (step.step_drivers || []).filter(d => !d.is_assigned)
        return (
          <div key={stepIdx} className="border-b border-slate-800/50 last:border-0">
            <div
              className={clsx(
                'flex items-center gap-3 px-4 py-2.5 cursor-pointer transition-colors',
                isOpen ? 'bg-slate-800/60' : 'hover:bg-slate-800/30'
              )}
              onClick={() => setSelectedStep(isOpen ? -1 : stepIdx)}
            >
              <span className={clsx('w-2 h-2 rounded-full shrink-0', step.is_reassignment ? 'bg-amber-400' : 'bg-orange-400')} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[10px] text-slate-500">{step.is_reassignment ? 'Reassigned' : 'Assigned'} at {step.time}</span>
                  {notClosest && <span className="text-[10px] text-amber-400 font-semibold">Not closest</span>}
                </div>
                <div className="flex items-center gap-3 mt-0.5">
                  <span className="text-sm font-bold text-orange-300">{step.driver}</span>
                  {assigned && <span className="text-xs text-orange-400">{assigned.distance?.toFixed(1)} mi</span>}
                  {notClosest && (
                    <>
                      <span className="text-slate-600 text-xs">vs closest:</span>
                      <span className="text-sm font-semibold text-green-300">{closest.name}</span>
                      <span className="text-xs text-green-400">{closest.distance?.toFixed(1)} mi</span>
                    </>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className="text-[10px] text-slate-600">{others.length} other drivers</span>
                {isOpen ? <ChevronUp className="w-3.5 h-3.5 text-slate-500" /> : <ChevronDown className="w-3.5 h-3.5 text-slate-500" />}
              </div>
            </div>

            {isOpen && others.length > 0 && (
              <div className="overflow-x-auto bg-slate-900/40">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-slate-600 border-b border-slate-800">
                      <th className="text-left py-1.5 px-4 font-medium pl-9">Driver</th>
                      <th className="text-center py-1.5 px-3 font-medium">Distance</th>
                      <th className="text-left py-1.5 px-3 font-medium">Role</th>
                    </tr>
                  </thead>
                  <tbody>
                    {others.map((d) => (
                      <tr key={d.driver_id} className={clsx(
                        'border-b border-slate-800/30',
                        d.is_closest && 'bg-green-500/5',
                      )}>
                        <td className="py-1.5 px-4 pl-9">
                          <span className={clsx('font-medium', d.is_closest ? 'text-green-300' : 'text-slate-500')}>
                            {d.name}
                          </span>
                        </td>
                        <td className="py-1.5 px-3 text-center">
                          <span className={clsx('font-bold', d.is_closest ? 'text-green-400' : 'text-slate-600')}>
                            {typeof d.distance === 'number' ? d.distance.toFixed(1) : d.distance} mi
                          </span>
                        </td>
                        <td className="py-1.5 px-3">
                          <span className={clsx('inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold border',
                            d.is_closest ? 'bg-green-500/10 text-green-300 border-green-500/20' :
                            d.has_skills ? 'bg-slate-700/30 text-slate-500 border-slate-600/20' :
                            'bg-red-500/10 text-red-400 border-red-500/20'
                          )}>
                            {d.is_closest ? 'CLOSEST' : d.has_skills ? 'ELIGIBLE' : 'NO SKILL'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function DriverTable({ sortedDrivers, closestDist }) {
  return (
    <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-slate-900/95 backdrop-blur">
          <tr className="text-slate-500 border-b border-slate-700">
            <th className="text-left py-2 px-3 font-medium">#</th>
            <th className="text-left py-2 px-3 font-medium">Driver</th>
            <th className="text-center py-2 px-3 font-medium">Distance</th>
            <th className="text-center py-2 px-3 font-medium">GPS</th>
            <th className="text-left py-2 px-3 font-medium">Skills</th>
            <th className="text-center py-2 px-3 font-medium">Eligible</th>
            <th className="text-left py-2 px-3 font-medium">Why Not Picked</th>
          </tr>
        </thead>
        <tbody>
          {sortedDrivers.map((d, i) => {
            const status = getDriverStatus(d, closestDist)
            return (
              <tr key={d.driver_id} className={clsx(
                'border-b border-slate-800/50',
                d.is_closest && 'bg-green-500/5',
              )}>
                <td className="py-2 px-3 text-slate-600">{i + 1}</td>
                <td className="py-2 px-3">
                  <div className="flex items-center gap-2">
                    <span className={clsx('w-2 h-2 rounded-full shrink-0',
                      d.is_closest ? 'bg-green-400' : d.eligible ? 'bg-slate-500' : 'bg-slate-700')} />
                    <span className={clsx('font-medium', d.is_closest ? 'text-green-300' : 'text-slate-300')}>{d.name}</span>
                  </div>
                  <div className="text-[10px] text-slate-600 ml-4">{d.territory_type}</div>
                </td>
                <td className="py-2 px-3 text-center">
                  {d.distance != null
                    ? <span className={clsx('font-bold', d.is_closest ? 'text-green-400' : d.distance < 5 ? 'text-slate-300' : 'text-slate-500')}>{d.distance.toFixed(1)} mi</span>
                    : <span className="text-slate-600">{'\u2014'}</span>}
                </td>
                <td className="py-2 px-3 text-center">
                  {d.has_gps ? <span className="text-emerald-400">Yes</span> : <span className="text-red-400">No</span>}
                </td>
                <td className="py-2 px-3">
                  <div className="flex flex-wrap gap-1">
                    {d.skills?.length > 0 ? d.skills.map(s => (
                      <span key={s} className={clsx('px-1.5 py-0.5 rounded text-[9px] font-medium border',
                        s.toLowerCase().includes('tow') ? 'bg-red-500/10 text-red-400 border-red-500/20' :
                        s.toLowerCase().includes('batt') ? 'bg-blue-500/10 text-blue-400 border-blue-500/20' :
                        'bg-slate-700/50 text-slate-400 border-slate-600/30'
                      )}>{s}</span>
                    )) : <span className="text-slate-600">None</span>}
                  </div>
                </td>
                <td className="py-2 px-3 text-center">
                  {d.eligible ? <CheckCircle2 className="w-4 h-4 text-emerald-400 inline" /> : <XCircle className="w-4 h-4 text-slate-600 inline" />}
                </td>
                <td className="py-2 px-3">
                  <span className={clsx('inline-block px-2 py-0.5 rounded text-[10px] font-semibold border', status.bg, status.color)}>{status.tag}</span>
                  <div className="text-[10px] text-slate-600 mt-0.5">{status.reason}</div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
