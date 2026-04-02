import React, { useState } from 'react'
import { clsx } from 'clsx'
import { MapPin, CheckCircle2 } from 'lucide-react'
import SALink from './SALink'
import { fmtMin } from './CommandCenterUtils'

export function SADetailRow({ item }) {
  const reason = item.reject_reason || item.cancel_reason || ''
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] bg-slate-900/40 rounded px-2.5 py-1.5">
      {item.number
        ? <SALink number={item.number} style={{ fontFamily: 'monospace', fontSize: 10, width: 64, display: 'inline-block' }} />
        : <span className="text-slate-500 font-mono w-16">—</span>
      }
      {item.created_time && <span className="text-slate-600 w-14">{item.created_time}</span>}
      {item.customer && <span className="text-slate-300 w-24 truncate" title={item.customer}>{item.customer}</span>}
      <span className="text-slate-400 w-20 truncate">{item.work_type || '—'}</span>
      <span className="text-slate-500 flex-1 truncate">{item.territory || '—'}</span>
      {item.wait_min != null && (
        <span className={clsx('font-semibold whitespace-nowrap', item.wait_min > 45 ? 'text-red-400' : 'text-amber-400')}>{item.wait_min}m wait</span>
      )}
      {item.minutes_lost != null && (
        <span className="text-red-400 font-semibold whitespace-nowrap">{item.minutes_lost}m lost</span>
      )}
      {item.ata_min != null && (
        <span className={clsx('font-semibold whitespace-nowrap', item.ata_min <= 45 ? 'text-emerald-400' : 'text-amber-400')}>{item.ata_min}m ATA</span>
      )}
      <span className={clsx('px-1.5 py-0.5 rounded text-[8px] font-bold uppercase',
        item.status === 'Completed' ? 'bg-emerald-950/50 text-emerald-400' :
        item.status === 'Dispatched' ? 'bg-blue-950/50 text-blue-400' :
        item.status?.includes('Cancel') ? 'bg-red-950/50 text-red-400' :
        item.status === 'En Route' ? 'bg-amber-950/50 text-amber-400' :
        item.status === 'On Location' ? 'bg-cyan-950/50 text-cyan-400' :
        'bg-slate-800 text-slate-400'
      )}>{item.status || '—'}</span>
      {(() => {
        const dm = item.dispatch_method
        const terr = item.territory || ''
        const isFleet = dm === 'Field Services' && (terr.startsWith('100') || terr.startsWith('800'))
        const isContractor = dm === 'Field Services' && !isFleet
        const label = isFleet ? 'Fleet' : isContractor ? 'On-Platform' : dm === 'Towbook' ? 'Towbook' : dm || ''
        const cls = isFleet ? 'bg-blue-950/40 text-blue-400' : isContractor ? 'bg-indigo-950/40 text-indigo-400' : 'bg-fuchsia-950/40 text-fuchsia-400'
        return label ? <span className={clsx('text-[8px] px-1 py-0.5 rounded', cls)}>{label}</span> : null
      })()}
      {item.from_territory && item.to_territory && (
        <span className="w-full text-[9px] text-red-400/70 pl-16 truncate" title={`${item.from_territory} → ${item.to_territory}`}>
          {item.from_territory} → {item.to_territory}
        </span>
      )}
      {reason && (
        <span className="w-full text-[9px] text-amber-500/70 pl-16 truncate" title={reason}>Reason: {reason}</span>
      )}
    </div>
  )
}


const _OUTCOME = {
  Rejected:     { color: 'text-red-400',     icon: '✗', label: 'Rejected' },
  Declined:     { color: 'text-orange-400',  icon: '⊘', label: 'Declined' },
  Released:     { color: 'text-slate-500',   icon: '↩', label: 'Released (no response)' },
  Accepted:     { color: 'text-emerald-400', icon: '✓', label: 'Accepted' },
  'In Progress':{ color: 'text-blue-400',   icon: '⟳', label: 'In Progress' },
}

export function BounceDetailRow({ item }) {
  const chain = item.bounce_chain || []
  const isTowbook = item.dispatch_method === 'Towbook'

  return (
    <div className="bg-slate-900/40 rounded px-2.5 py-2 space-y-1.5">
      {/* SA header */}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px]">
        {item.number
          ? <SALink number={item.number} style={{ fontFamily: 'monospace', fontSize: 10 }} />
          : <span className="text-slate-500 font-mono">—</span>
        }
        {item.created_time && <span className="text-slate-600">{item.created_time}</span>}
        <span className="text-slate-400">{item.work_type || '—'}</span>
        {item.minutes_lost != null && (
          <span className="text-red-400 font-semibold">{fmtMin(item.minutes_lost)} total dispatch time</span>
        )}
        <span className="text-red-400/70 text-[9px]">{item.bounce_count} reassignment{item.bounce_count !== 1 ? 's' : ''}</span>
        <span className={clsx('px-1.5 py-0.5 rounded text-[8px] font-bold uppercase',
          item.status === 'Completed'      ? 'bg-emerald-950/50 text-emerald-400' :
          item.status === 'Dispatched'     ? 'bg-blue-950/50 text-blue-400' :
          item.status?.includes('Cancel') ? 'bg-red-950/50 text-red-400' :
          'bg-slate-800 text-slate-400'
        )}>{item.status || '—'}</span>
        <span className={clsx('text-[8px] px-1 py-0.5 rounded',
          isTowbook ? 'bg-fuchsia-950/40 text-fuchsia-400' : 'bg-blue-950/40 text-blue-400'
        )}>{isTowbook ? 'Towbook' : 'Fleet'}</span>
      </div>

      {/* Full assignment timeline */}
      {chain.length > 0 && (
        <div className="ml-1 border-l-2 border-slate-700/40 pl-3 space-y-2 text-[9px]">
          {chain.map((c, i) => {
            const isLast = i === chain.length - 1
            const prevTerritory = i > 0 ? chain[i - 1].territory : null
            const isNewGarage = !prevTerritory || c.territory !== prevTerritory
            const isSameGarageReassign = !isNewGarage   // same garage, next attempt
            const o = _OUTCOME[c.outcome] || _OUTCOME.Released

            return (
              <div key={i} className="space-y-0.5">

                {/* ── Garage / territory header ── */}
                {(i === 0 || isNewGarage) && c.territory && (
                  <div className={clsx(
                    'flex items-center gap-1.5 font-semibold text-[8px] uppercase tracking-wide py-0.5',
                    i === 0 ? 'text-slate-400' : 'text-indigo-400'
                  )}>
                    <span>{i === 0 ? '⌂' : '↷'}</span>
                    <span>{i === 0 ? 'Garage:' : 'Cascaded to garage:'}</span>
                    <span className={clsx('font-bold normal-case tracking-normal text-[9px]',
                      i === 0 ? 'text-slate-200' : 'text-indigo-200'
                    )} title={c.territory}>{c.territory}</span>
                  </div>
                )}

                {/* ── Driver assignment line ── */}
                <div className="flex items-center gap-1.5 pl-3">
                  <span className={isSameGarageReassign ? 'text-amber-400' : 'text-slate-500'}>
                    {isSameGarageReassign ? '↔' : '→'}
                  </span>
                  <span className={clsx('font-semibold',
                    isSameGarageReassign ? 'text-amber-300/80' : 'text-slate-400'
                  )}>
                    {isSameGarageReassign ? 'Re-offered driver:' : 'Assigned driver:'}
                  </span>
                  <span className="text-white font-medium truncate max-w-[140px]" title={c.driver}>
                    {c.driver}
                  </span>
                  {c.assigned_at && (
                    <span className="text-slate-600 ml-auto shrink-0">{c.assigned_at}</span>
                  )}
                </div>

                {/* ── Outcome line ── */}
                <div className="flex items-center gap-1.5 pl-3">
                  <span className={o.color}>{o.icon}</span>
                  <span className={clsx('font-semibold', o.color)}>{o.label}</span>
                  {c.duration_min != null && (
                    <span className="text-slate-600">after {fmtMin(c.duration_min)}</span>
                  )}
                  {c.outcome_at && (
                    <span className="text-slate-600 ml-auto shrink-0">{c.outcome_at}</span>
                  )}
                </div>

                {/* ── Gap to next attempt ── */}
                {c.gap_to_next_min != null && !isLast && (
                  <div className="pl-3 text-[8px] text-slate-600 italic">
                    {c.gap_to_next_min > 0
                      ? `↓ ${fmtMin(c.gap_to_next_min)} before next assignment`
                      : '↓ immediately reassigned'}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export function ClosestDriverDetailRow({ item, onViewOnMap }) {
  const candidates = item.candidates || []
  const [expanded, setExpanded] = useState(false)
  const shown = expanded ? candidates : candidates.slice(0, 3)
  const hasMore = candidates.length > 3
  const busyCount = candidates.filter(d => d.busy).length

  return (
    <div className={clsx('rounded px-2.5 py-2 space-y-1 border-l-2',
      item.is_closest
        ? 'bg-blue-950/20 border-l-blue-500'
        : 'bg-orange-950/20 border-l-orange-500'
    )}>
      {/* SA header row */}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px]">
        {item.number
          ? <SALink number={item.number} style={{ fontFamily: 'monospace', fontSize: 10 }} />
          : <span className="text-slate-400 font-mono">—</span>
        }
        {item.created_time && <span className="text-slate-600">{item.created_time}</span>}
        <span className="text-slate-400 truncate">{item.work_type || '—'}</span>
        <span className={clsx('px-1.5 py-0.5 rounded text-[8px] font-bold uppercase',
          item.is_auto ? 'bg-indigo-950/40 text-indigo-400' : 'bg-amber-950/40 text-amber-500'
        )}>{item.is_auto ? 'System' : item.dispatcher}</span>
        {item.is_closest ? (
          <span className="text-blue-400 font-semibold"><CheckCircle2 className="w-3 h-3 inline mr-0.5" />closest available</span>
        ) : (
          <span className="text-orange-400 font-semibold">+{item.extra_miles} mi extra</span>
        )}
        {item.available != null && (
          <span className="text-[8px] text-slate-600">{item.available}/{item.on_shift} avail</span>
        )}
        {onViewOnMap && (
          <button onClick={(e) => { e.stopPropagation(); onViewOnMap(item.number) }}
            className="ml-auto flex items-center gap-1 text-cyan-500 hover:text-cyan-400 transition-colors bg-cyan-950/30 hover:bg-cyan-950/50 px-1.5 py-0.5 rounded"
            title="View SA + drivers on map">
            <MapPin className="w-3 h-3" /><span className="text-[9px]">map</span>
          </button>
        )}
      </div>

      {/* Driver list — ranked by distance, busy drivers dimmed */}
      <div className="ml-4 space-y-0.5">
        {shown.map((d, i) => (
          <div key={i} className={clsx('flex items-center gap-2 text-[10px] rounded px-2 py-0.5',
            d.picked ? 'bg-slate-800/60 border border-slate-700/40' : '',
            d.busy && !d.picked ? 'opacity-40' : ''
          )}>
            <span className={clsx('w-4 text-center font-bold text-[9px]',
              d.busy ? 'text-slate-700' : i === 0 ? 'text-blue-400' : 'text-slate-600'
            )}>#{i + 1}</span>
            <span className={clsx('flex-1 truncate',
              d.picked ? 'text-white font-semibold' : d.busy ? 'text-slate-600' : 'text-slate-400'
            )}>{d.name}{d.picked && ' ← dispatched'}{d.busy && ' (busy)'}</span>
            <span className={clsx('font-mono whitespace-nowrap',
              d.busy && !d.picked ? 'text-slate-700' :
              d.picked && !d.busy ? 'text-blue-400' :
              d.picked && d.busy ? 'text-orange-400' :
              i === 0 ? 'text-blue-400/60' : 'text-slate-500'
            )}>{d.distance_mi} mi</span>
          </div>
        ))}
        {hasMore && !expanded && (
          <button onClick={() => setExpanded(true)}
            className="text-[9px] text-slate-600 hover:text-slate-400 pl-6">
            +{candidates.length - 3} more{busyCount > 0 ? ` (${busyCount} busy)` : ''}...
          </button>
        )}
        {expanded && hasMore && (
          <button onClick={() => setExpanded(false)}
            className="text-[9px] text-slate-600 hover:text-slate-400 pl-6">
            show less
          </button>
        )}
      </div>
    </div>
  )
}
