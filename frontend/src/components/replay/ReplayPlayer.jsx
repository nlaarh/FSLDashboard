import { useMemo, useRef } from 'react'
import { Play, Pause, SkipBack, SkipForward } from 'lucide-react'
import { SPEEDS } from './useReplayClock'
import { clockLabel } from './replayMath'

const ET = 'America/New_York'

/**
 * Transport bar and scrubber, adapted from the Towbook Studio replay player: play/pause, speed,
 * pointer-drag scrub, hour ticks, and an optional density strip and step marks under the track.
 */
export default function ReplayPlayer({ clock, start, end, density, marks = [], onStep, speeds = SPEEDS, children }) {
  const barRef = useRef(null)
  const span = Math.max(end - start, 1)
  const pct = s => `${Math.min(100, Math.max(0, ((s - start) / span) * 100))}%`
  const ticks = useMemo(() => {
    const out = []
    for (let h = Math.ceil(start / 3600) * 3600; h <= end; h += 3600) {
      out.push({ t: h, label: new Date(h * 1000).toLocaleTimeString('en-US', { timeZone: ET, hour: 'numeric' }) })
    }
    const every = Math.ceil(out.length / 12)
    return out.filter((_, i) => i % every === 0)
  }, [start, end])
  const peak = density ? Math.max(1, ...density) : 1

  const seekFrom = e => {
    const r = barRef.current.getBoundingClientRect()
    clock.setT(start + ((e.clientX - r.left) / r.width) * span)
  }
  const onDown = e => {
    e.currentTarget.setPointerCapture(e.pointerId)
    clock.setPlaying(false)
    seekFrom(e)
  }

  const btn = 'p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition-colors'
  return (
    <div className="glass rounded-xl px-4 py-3 space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        {onStep && <button type="button" className={btn} onClick={() => onStep(-1)} title="Previous step"><SkipBack className="w-4 h-4" /></button>}
        <button type="button" onClick={clock.toggle} title={clock.playing ? 'Pause (Space)' : 'Play (Space)'}
          className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors ${
            clock.playing ? 'bg-amber-500 hover:bg-amber-400 text-slate-950' : 'bg-brand-600 hover:bg-brand-500 text-white'}`}>
          {clock.playing ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
          {clock.playing ? 'Pause' : 'Play'}
        </button>
        {onStep && <button type="button" className={btn} onClick={() => onStep(1)} title="Next step"><SkipForward className="w-4 h-4" /></button>}
        <span className="font-mono text-sm font-semibold text-white bg-slate-900/70 border border-slate-700 rounded px-2 py-0.5 tabular-nums">
          {clockLabel(clock.t, true)}
        </span>
        <div className="flex items-center bg-slate-900/70 rounded-lg p-0.5 border border-slate-700" role="group" aria-label="Playback speed">
          {speeds.map(s => (
            <button key={s} type="button" onClick={() => clock.setSpeed(s)} title={`${s} minute${s > 1 ? 's' : ''} of the day per second`}
              className={`px-2 py-0.5 rounded text-[11px] font-mono font-semibold transition-colors ${
                clock.speed === s ? 'bg-brand-600 text-white' : 'text-slate-400 hover:text-white'}`}>
              {s}×
            </button>
          ))}
        </div>
        {children}
        <span className="ml-auto text-[10px] text-slate-500 hidden md:inline">Space play/pause · ← → 5 min · Shift 30 min</span>
      </div>

      <div ref={barRef} onPointerDown={onDown} onPointerMove={e => e.buttons === 1 && seekFrom(e)}
        className="relative h-9 cursor-pointer select-none touch-none" role="slider" aria-label="Replay time"
        aria-valuemin={start} aria-valuemax={end} aria-valuenow={clock.t} aria-valuetext={clockLabel(clock.t)}>
        {density && (
          <div className="absolute inset-x-0 top-0 h-5 flex items-end gap-px opacity-70" aria-hidden>
            {density.map((n, i) => (
              <div key={i} className="flex-1 bg-slate-600 rounded-t-sm" style={{ height: `${(n / peak) * 100}%` }} />
            ))}
          </div>
        )}
        <div className="absolute inset-x-0 top-5 h-1.5 rounded-full bg-slate-800" />
        <div className="absolute left-0 top-5 h-1.5 rounded-full bg-brand-500" style={{ width: pct(clock.t) }} />
        {marks.map((m, i) => (
          <span key={i} title={m.label} className="absolute top-4 w-1 h-3.5 -translate-x-1/2 rounded-sm"
            style={{ left: pct(m.t), background: m.colour || '#e2e8f0' }} />
        ))}
        <span className="absolute top-[14px] w-3.5 h-3.5 -translate-x-1/2 rounded-full bg-white shadow ring-2 ring-brand-500" style={{ left: pct(clock.t) }} />
        {ticks.map(k => (
          <span key={k.t} className="absolute top-7 -translate-x-1/2 text-[9px] text-slate-500 pointer-events-none" style={{ left: pct(k.t) }}>{k.label}</span>
        ))}
      </div>
    </div>
  )
}
