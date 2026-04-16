/**
 * LiveDispatchUtils.jsx
 *
 * Shared utility components and helpers for LiveDispatchBoard and SAWatchlist.
 * Dark ops-center theme. Monospace numbers. Lucide icons.
 */

import { useState, useRef } from 'react'
import ReactDOM from 'react-dom'
import { clsx } from 'clsx'
import { Eye, AlertTriangle, Clock, User, MapPin, Wrench } from 'lucide-react'
import CheckpointTracker from './CheckpointTracker'
import SALink from './SALink'

// ── Helper functions ────────────────────────────────────────────────────────

export function fmtDuration(min) {
  if (!min || min <= 0) return '\u2014'
  if (min < 60) return `${min}m`
  return `${Math.floor(min / 60)}h ${min % 60}m`
}

export function getInitials(name) {
  if (!name) return '??'
  const parts = name.trim().split(/\s+/)
  return (parts[0]?.[0] || '') + (parts[parts.length - 1]?.[0] || '')
}

export const PHASE_SHORT = {
  'Dispatched':  'Disp',
  'Accepted':    'Acpt',
  'En Route':    'EnRte',
  'On Location': 'OnLoc',
  'In Progress': 'InProg',
  'Completed':   'Done',
}

// ── Phase color mapping ─────────────────────────────────────────────────────

const PHASE_COLORS = {
  dispatched:   { bg: 'bg-blue-500/15',    border: 'border-blue-500/30',    text: 'text-blue-400'    },
  accepted:     { bg: 'bg-indigo-500/15',   border: 'border-indigo-500/30',  text: 'text-indigo-400'  },
  en_route:     { bg: 'bg-cyan-500/15',     border: 'border-cyan-500/30',    text: 'text-cyan-400'    },
  on_location:  { bg: 'bg-amber-500/15',    border: 'border-amber-500/30',   text: 'text-amber-400'   },
  in_progress:  { bg: 'bg-purple-500/15',   border: 'border-purple-500/30',  text: 'text-purple-400'  },
  completed_1h: { bg: 'bg-emerald-500/15',  border: 'border-emerald-500/30', text: 'text-emerald-400' },
}

const PHASE_LABELS = {
  dispatched:   'Dispatched',
  accepted:     'Accepted',
  en_route:     'En Route',
  on_location:  'On Location',
  in_progress:  'In Progress',
  completed_1h: 'Done (1h)',
}

// ── KpiStrip ────────────────────────────────────────────────────────────────

export function KpiStrip({ kpis = {} }) {
  const cells = [
    { key: 'active',   label: 'Active SAs', value: kpis.active,   color: 'text-white'       },
    { key: 'on_track', label: 'On Track',   value: kpis.on_track, color: 'text-emerald-400' },
    { key: 'aging',    label: 'Aging',      value: kpis.aging,    color: 'text-amber-400'   },
    { key: 'stuck',    label: 'Stuck',      value: kpis.stuck,    color: 'text-red-400'     },
  ]

  return (
    <div className="grid grid-cols-4 gap-2">
      {cells.map(c => (
        <div
          key={c.key}
          className="rounded-lg bg-slate-800/60 border border-slate-700/30 px-3 py-2 text-center"
        >
          <div className={clsx('text-lg font-black font-mono leading-none', c.color)}>
            {c.value ?? '\u2014'}
          </div>
          <div className="text-[9px] font-semibold uppercase tracking-wider text-slate-500 mt-1">
            {c.label}
          </div>
        </div>
      ))}
    </div>
  )
}

// ── PhaseFunnel ─────────────────────────────────────────────────────────────

export function PhaseFunnel({ phaseCounts = {} }) {
  const phases = [
    'dispatched', 'accepted', 'en_route',
    'on_location', 'in_progress', 'completed_1h',
  ]

  return (
    <div className="grid grid-cols-6 gap-1.5">
      {phases.map(key => {
        const pc = PHASE_COLORS[key] || PHASE_COLORS.dispatched
        const count = phaseCounts[key] ?? 0
        return (
          <div
            key={key}
            className={clsx(
              'rounded-lg border px-2 py-2 text-center',
              pc.bg, pc.border
            )}
          >
            <div className={clsx('text-base font-black font-mono leading-none', pc.text)}>
              {count}
            </div>
            <div className="text-[8px] font-semibold uppercase tracking-tight text-slate-500 mt-1 truncate">
              {PHASE_LABELS[key]}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── StatusChip ──────────────────────────────────────────────────────────────

export function StatusChip({ status, isStuck = false }) {
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold',
        isStuck
          ? 'bg-red-500/15 text-red-400 border border-red-500/30'
          : 'bg-amber-500/15 text-amber-400 border border-amber-500/30'
      )}
    >
      <span
        className={clsx(
          'w-1.5 h-1.5 rounded-full animate-pulse',
          isStuck ? 'bg-red-500' : 'bg-amber-500'
        )}
      />
      {status || 'Unknown'}
    </span>
  )
}

// ── AgingBadge ──────────────────────────────────────────────────────────────

export function AgingBadge({ minutes, flag }) {
  const f = (flag || '').toString().toLowerCase()
  const isStuck = f === 'stuck' || f === 'danger'
  const isAging = minutes != null && minutes > 20

  return (
    <span
      className={clsx(
        'inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono font-bold',
        isStuck
          ? 'bg-red-500/15 text-red-400 border border-red-500/30'
          : isAging
            ? 'bg-amber-500/15 text-amber-400 border border-amber-500/30'
            : 'bg-slate-800/60 text-slate-400 border border-slate-700/30'
      )}
    >
      {fmtDuration(minutes)}
    </span>
  )
}

// ── FlagBadge ───────────────────────────────────────────────────────────────

export function FlagBadge({ flag }) {
  if (!flag) return null

  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-red-500/15 border border-red-500/30 text-[9px] font-bold uppercase tracking-wide text-red-400">
      <AlertTriangle className="w-2.5 h-2.5" />
      {String(flag).toUpperCase()}
    </span>
  )
}

// ── SATimelineTooltip — hover over SA# to see phase timeline ───────────────

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

const PHASE_DOTS = { done: '●', current: '◉', future: '○' }

export function SAWithTimeline({ number, driver }) {
  const [show, setShow] = useState(false)
  const [pos, setPos] = useState({ top: 0, left: 0, flipDown: false })
  const anchorRef = useRef(null)
  const phases = driver?.phases || []
  const hasTimeline = phases.length > 0

  const handleEnter = () => {
    if (anchorRef.current) {
      const rect = anchorRef.current.getBoundingClientRect()
      const flipDown = rect.top < 300
      setPos({
        left: rect.left,
        top: flipDown ? rect.bottom + 8 : rect.top - 8,
        flipDown,
      })
    }
    setShow(true)
  }

  return (
    <div
      ref={anchorRef}
      className="relative"
      onMouseEnter={handleEnter}
      onMouseLeave={() => setShow(false)}
    >
      <SALink number={number} className="text-xs font-mono" />

      {show && hasTimeline && ReactDOM.createPortal(
        <div
          className="fixed z-[9999] pointer-events-none"
          style={{
            left: pos.left,
            top: pos.flipDown ? pos.top : undefined,
            bottom: pos.flipDown ? undefined : `${window.innerHeight - pos.top}px`,
          }}
        >
          <div className="bg-slate-800 border border-slate-600 rounded-lg shadow-2xl px-3 py-2.5 min-w-[240px] max-w-[300px]">
            {/* Header */}
            <div className="flex items-center gap-2 mb-2 pb-1.5 border-b border-slate-700">
              <span className="text-[11px] font-bold text-white font-mono">{number}</span>
              {driver?.work_type && (
                <span className="text-[10px] text-slate-400 flex items-center gap-1">
                  <Wrench className="w-2.5 h-2.5" /> {driver.work_type}
                </span>
              )}
            </div>

            {/* Phase timeline */}
            <div className="space-y-1">
              {phases.map((p, i) => (
                <div key={i} className="flex items-center gap-2 text-[10px]">
                  <span className={clsx(
                    'w-3 text-center flex-shrink-0',
                    p.state === 'done' && 'text-slate-400',
                    p.state === 'current' && 'text-amber-400',
                    p.state === 'future' && 'text-slate-600',
                  )}>
                    {PHASE_DOTS[p.state] || '○'}
                  </span>
                  <span className={clsx(
                    'w-16 flex-shrink-0 font-mono',
                    p.state === 'current' ? 'text-amber-400 font-semibold' : p.state === 'done' ? 'text-slate-300' : 'text-slate-600',
                  )}>
                    {p.name === 'On Location' ? 'On Loc' : p.name === 'In Progress' ? 'InProg' : p.name}
                  </span>
                  <span className="text-slate-500 font-mono w-10 flex-shrink-0 text-right">
                    {p.duration_min != null ? fmtDuration(p.duration_min) : '—'}
                  </span>
                  <span className="text-slate-600 font-mono flex-shrink-0">
                    {fmtTime(p.started_at) || ''}
                  </span>
                  {p.actor && p.state !== 'future' && (
                    <span className="text-slate-600 truncate ml-auto text-[9px]">{p.actor.split(' ')[0]}</span>
                  )}
                </div>
              ))}
            </div>

            {/* Address + description */}
            {(driver?.address || driver?.description) && (
              <div className="mt-2 pt-1.5 border-t border-slate-700 space-y-0.5">
                {driver.address && (
                  <div className="text-[9px] text-slate-400 flex items-center gap-1 truncate">
                    <MapPin className="w-2.5 h-2.5 flex-shrink-0" /> {driver.address}
                  </div>
                )}
                {driver.description && (
                  <div className="text-[9px] text-slate-500 truncate">{driver.description.slice(0, 80)}</div>
                )}
              </div>
            )}

            {/* Arrow — flips direction based on position */}
            <div className={clsx(
              'absolute left-4 w-0 h-0 border-l-[5px] border-r-[5px] border-l-transparent border-r-transparent',
              pos.flipDown
                ? 'bottom-full border-b-[5px] border-b-slate-600'
                : 'top-full border-t-[5px] border-t-slate-600',
            )} />
          </div>
        </div>,
        document.body
      )}
    </div>
  )
}

// ── DriverRow ───────────────────────────────────────────────────────────────

export function DriverRow({ driver = {}, onClick }) {
  const {
    driver_name,
    driver_initials,
    territory_short,
    channel,
    tech_id,
    sa_number,
    current_status,
    time_in_status_min,
    flag,
    pta_delta_min,
    phases,
    work_type,
    address,
    description,
  } = driver

  const initials = driver_initials || getInitials(driver_name)
  const isStuck = (flag || '').toString().toLowerCase() === 'stuck'

  return (
    <div
      className={clsx(
        'flex items-center gap-2 px-3 py-2 border-b border-slate-800/40',
        'hover:bg-slate-800/40 transition-colors group cursor-pointer',
        isStuck && 'bg-red-950/10'
      )}
      onClick={onClick}
    >
      {/* Avatar */}
      <div
        className={clsx(
          'w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0',
          isStuck
            ? 'bg-red-500/20 text-red-400 border border-red-500/40'
            : 'bg-slate-700/60 text-slate-300 border border-slate-600/40'
        )}
      >
        {initials}
      </div>

      {/* Name + meta */}
      <div className="min-w-0 flex-shrink-0 w-28">
        <div className="text-xs font-semibold text-white truncate">{driver_name || 'Unknown'}</div>
        <div className="flex items-center gap-1.5 text-[9px] text-slate-500">
          {territory_short && <span>{territory_short}</span>}
          {channel && (
            <span
              className={clsx(
                'px-1 py-px rounded text-[8px] font-bold uppercase',
                channel === 'Off-Platform'
                  ? 'bg-orange-500/15 text-orange-400'
                  : channel === 'On-Platform'
                    ? 'bg-cyan-500/15 text-cyan-400'
                    : 'bg-indigo-500/15 text-indigo-400'
              )}
            >
              {channel === 'Off-Platform' ? 'OFF' : channel === 'On-Platform' ? 'ON' : 'FLT'}
            </span>
          )}
          {tech_id && <span className="font-mono">{tech_id}</span>}
        </div>
      </div>

      {/* SA link with timeline tooltip */}
      <div className="flex-shrink-0 w-20">
        {sa_number ? (
          <SAWithTimeline number={sa_number} driver={driver} />
        ) : (
          <span className="text-[10px] text-slate-600">\u2014</span>
        )}
      </div>

      {/* Status chip */}
      <div className="flex-shrink-0">
        <StatusChip status={current_status} isStuck={isStuck} />
      </div>

      {/* Aging badge */}
      <div className="flex-shrink-0">
        <AgingBadge minutes={time_in_status_min} flag={flag} />
      </div>

      {/* Flag badge */}
      <div className="flex-shrink-0 w-16">
        <FlagBadge flag={flag} />
      </div>

      {/* Checkpoint tracker */}
      <div className="flex-1 min-w-0">
        {phases && phases.length > 0 && (
          <CheckpointTracker phases={phases} isStuck={isStuck} saInfo={{ work_type, address, description }} />
        )}
      </div>

      {/* PTA delta */}
      <div className="flex-shrink-0 w-14 text-right">
        {pta_delta_min != null ? (
          <span
            className={clsx(
              'text-[10px] font-mono font-bold',
              pta_delta_min > 0
                ? 'text-red-400'
                : pta_delta_min < -10
                  ? 'text-emerald-400'
                  : 'text-slate-400'
            )}
          >
            {pta_delta_min > 0 ? '+' : ''}{pta_delta_min}m
          </span>
        ) : (
          <span className="text-[10px] text-slate-600">\u2014</span>
        )}
      </div>

      {/* Drill-down eye */}
      <button
        onClick={e => { e.stopPropagation(); onClick?.() }}
        title="View details"
        className="flex-shrink-0 p-1 rounded-md text-slate-600 hover:text-blue-400 hover:bg-slate-800/60 transition-all opacity-0 group-hover:opacity-100"
      >
        <Eye className="w-3.5 h-3.5" />
      </button>
    </div>
  )
}
