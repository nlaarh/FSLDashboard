/**
 * CheckpointTracker.jsx
 *
 * Reusable SA lifecycle progress tracker — connected dots on a horizontal rail.
 * Done phases show a filled dot with checkmark, current phase pulses (amber or red),
 * future phases show hollow outline dots.
 * Hover any dot to see rich detail (time entered, duration, who triggered it).
 */

import { useState } from 'react'
import { clsx } from 'clsx'

const SHORT_LABELS = {
  'Dispatched':  'Disp',
  'Accepted':    'Acpt',
  'En Route':    'EnRte',
  'On Location': 'OnLoc',
  'In Progress': 'InProg',
  'Completed':   'Done',
}

function fmtDur(min) {
  if (!min || min <= 0) return null
  if (min < 60) return `${min}m`
  const h = Math.floor(min / 60)
  const r = min % 60
  return r > 0 ? `${h}h${r}m` : `${h}h`
}

function fmtTime(utcStr) {
  if (!utcStr) return null
  try {
    const d = new Date(utcStr)
    return d.toLocaleTimeString('en-US', {
      timeZone: 'America/New_York',
      hour: 'numeric', minute: '2-digit', hour12: true,
    })
  } catch { return null }
}

/** Tiny inline SVG checkmark for done dots */
function Checkmark() {
  return (
    <svg
      className="w-2 h-2 text-white"
      viewBox="0 0 12 12"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M2 6.5L5 9.5L10 3" />
    </svg>
  )
}

/** Tooltip shown on hover over a phase dot */
function PhaseTooltip({ phase, saInfo }) {
  const time = fmtTime(phase.started_at)
  const dur = fmtDur(phase.duration_min)

  return (
    <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-50 pointer-events-none">
      <div className="bg-slate-800 border border-slate-600 rounded-lg shadow-xl px-3 py-2 min-w-[160px] max-w-[220px] text-left">
        {/* Phase name */}
        <div className="text-[11px] font-semibold text-slate-200 mb-1">{phase.name}</div>

        {/* Time entered */}
        {time && (
          <div className="flex justify-between text-[10px] mb-0.5">
            <span className="text-slate-500">Entered</span>
            <span className="text-slate-300 font-mono">{time} ET</span>
          </div>
        )}

        {/* Duration */}
        {dur && (
          <div className="flex justify-between text-[10px] mb-0.5">
            <span className="text-slate-500">Duration</span>
            <span className={clsx('font-mono', phase.state === 'current' ? 'text-amber-400' : 'text-slate-300')}>
              {dur}
            </span>
          </div>
        )}

        {/* Who triggered */}
        {phase.actor && (
          <div className="flex justify-between text-[10px] mb-0.5">
            <span className="text-slate-500">By</span>
            <span className="text-slate-300 truncate ml-2">{phase.actor}</span>
          </div>
        )}

        {/* SA-level context when available */}
        {saInfo?.address && phase.name === 'On Location' && (
          <div className="border-t border-slate-700 mt-1.5 pt-1.5 text-[10px] text-slate-400 truncate">
            📍 {saInfo.address}
          </div>
        )}
        {saInfo?.work_type && phase.name === 'Dispatched' && (
          <div className="border-t border-slate-700 mt-1.5 pt-1.5 text-[10px] text-slate-400 truncate">
            🔧 {saInfo.work_type}
          </div>
        )}
        {saInfo?.description && phase.name === 'Dispatched' && (
          <div className="text-[9px] text-slate-500 truncate mt-0.5">
            {saInfo.description.slice(0, 60)}
          </div>
        )}

        {/* Status for future phases */}
        {phase.state === 'future' && (
          <div className="text-[10px] text-slate-500 italic">Not yet reached</div>
        )}

        {/* Arrow pointer */}
        <div className="absolute top-full left-1/2 -translate-x-1/2 w-0 h-0 border-l-[5px] border-r-[5px] border-t-[5px] border-l-transparent border-r-transparent border-t-slate-600" />
      </div>
    </div>
  )
}

export default function CheckpointTracker({ phases = [], isStuck = false, saInfo = null }) {
  const [hoveredIdx, setHoveredIdx] = useState(null)

  if (!phases.length) return null

  const count = phases.length
  const currentIdx = phases.findIndex(p => p.state === 'current')
  const allDone = currentIdx === -1 && phases.every(p => p.state === 'done')

  const totalGaps = Math.max(count - 1, 1)
  const filledGaps = allDone ? totalGaps : Math.max(currentIdx, 0)
  const fillPct = (filledGaps / totalGaps) * 100

  return (
    <div className="relative w-full select-none" role="progressbar">
      {/* Rail line */}
      <div className="absolute left-0 right-0 top-[7px] mx-[7px]">
        <div className="h-0.5 w-full rounded-full bg-slate-700/60" />
        <div
          className="absolute top-0 left-0 h-0.5 rounded-full bg-slate-500 transition-all duration-500"
          style={{ width: `${fillPct}%` }}
        />
      </div>

      {/* Dots + labels */}
      <div
        className="relative grid"
        style={{ gridTemplateColumns: `repeat(${count}, minmax(0, 1fr))` }}
      >
        {phases.map((phase, i) => {
          const short = SHORT_LABELS[phase.name] || phase.name?.slice(0, 4)
          const dur = fmtDur(phase.duration_min)
          const isCurrent = phase.state === 'current'
          const isDone = phase.state === 'done'
          const isHovered = hoveredIdx === i

          return (
            <div
              key={i}
              className="flex flex-col items-center gap-0.5 relative"
              onMouseEnter={() => setHoveredIdx(i)}
              onMouseLeave={() => setHoveredIdx(null)}
            >
              {/* Tooltip */}
              {isHovered && <PhaseTooltip phase={phase} saInfo={saInfo} />}

              {/* Dot */}
              {isDone && (
                <div className="w-3.5 h-3.5 rounded-full bg-slate-500 flex items-center justify-center z-10 cursor-pointer hover:bg-slate-400 transition-colors">
                  <Checkmark />
                </div>
              )}
              {isCurrent && (
                <div
                  className={clsx(
                    'w-4 h-4 rounded-full z-10 ring-2 ring-offset-1 ring-offset-slate-900 cursor-pointer',
                    isStuck
                      ? 'bg-red-500 animate-pulse ring-red-500/40'
                      : 'bg-amber-500 animate-pulse ring-amber-500/40'
                  )}
                />
              )}
              {!isDone && !isCurrent && (
                <div className="w-3.5 h-3.5 rounded-full border-2 border-slate-600 bg-transparent z-10 cursor-pointer hover:border-slate-400 transition-colors" />
              )}

              {/* Short label only — duration available via hover tooltip */}
              <span className={clsx(
                'text-[8px] font-mono uppercase tracking-tight leading-none mt-0.5',
                isCurrent
                  ? isStuck ? 'text-red-400 font-semibold' : 'text-amber-400 font-semibold'
                  : isDone ? 'text-slate-400' : 'text-slate-600',
              )}>
                {short}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
