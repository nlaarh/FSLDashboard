import { useEffect, useMemo, useRef } from 'react'
import { Play, Pause, SkipBack, SkipForward, FastForward } from 'lucide-react'
import { SPEEDS, useEngineState } from './useReplayEngine'
import { fmtSkip } from './engineMath'
import { clockLabel } from './replayMath'

const ET = 'America/New_York'

/** "skipping 14 min" chip, shown while a quiet stretch is being fast-forwarded. Put it on top of a map. */
export function SkipChip({ engine, className = '' }) {
  const { boosted } = useEngineState(engine, 4)
  if (!boosted) return null
  return (
    <div className={`rp-glass rounded-full px-3 py-1 text-xs font-semibold text-amber-200 flex items-center gap-1.5 ${className}`} role="status">
      <FastForward className="w-3.5 h-3.5" />skipping {fmtSkip(boosted)} of quiet time
    </div>
  )
}

/**
 * Transport bar and scrubber over the replay engine: Prev / Play / Next, speeds 1x-300x, drag to scrub, hour ticks, a density strip,
 * and clickable event marks (colour or icon). The playhead and clock are written straight to the DOM every frame (no React render).
 * marks: [{ t, label, colour, Icon, level }] — clicking one jumps there.
 */
export default function ReplayPlayer({ engine, start, end, density, marks = [], onPrev, onNext, speeds = SPEEDS, children }) {
  const barRef = useRef(null), headRef = useRef(null), fillRef = useRef(null), clockRef = useRef(null)
  const { playing, speed } = useEngineState(engine, 4)
  const span = Math.max(end - start, 1)
  const pct = s => `${Math.min(100, Math.max(0, ((s - start) / span) * 100))}%`
  useEffect(() => {
    const paint = t => {
      const p = pct(t)
      if (headRef.current) headRef.current.style.left = p
      if (fillRef.current) fillRef.current.style.width = p
      if (clockRef.current) clockRef.current.textContent = clockLabel(t, true)
    }
    paint(engine.ref.current.t)
    return engine.subscribe(paint)
  }, [engine, start, end]) // eslint-disable-line react-hooks/exhaustive-deps
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
    engine.seek(start + ((e.clientX - r.left) / r.width) * span)
  }
  const onDown = e => {
    e.currentTarget.setPointerCapture(e.pointerId)
    engine.pause()
    seekFrom(e)
  }

  const btn = 'p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition-colors'
  return (
    <div className="glass rounded-xl px-4 py-3 space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" className={btn} onClick={onPrev || engine.prev} title="Previous event (←)"><SkipBack className="w-4 h-4" /></button>
        <button type="button" onClick={engine.toggle} title={playing ? 'Pause (Space)' : 'Play (Space)'}
          className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors ${
            playing ? 'bg-amber-500 hover:bg-amber-400 text-slate-950' : 'bg-brand-600 hover:bg-brand-500 text-white'}`}>
          {playing ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
          {playing ? 'Pause' : 'Play'}
        </button>
        <button type="button" className={btn} onClick={onNext || engine.next} title="Next event (→)"><SkipForward className="w-4 h-4" /></button>
        <span ref={clockRef} className="font-mono text-sm font-semibold text-white bg-slate-900/70 border border-slate-700 rounded px-2 py-0.5 tabular-nums min-w-[92px] text-center" />
        <div className="flex items-center bg-slate-900/70 rounded-lg p-0.5 border border-slate-700" role="group" aria-label="Playback speed">
          {speeds.map(s => (
            <button key={s} type="button" onClick={() => engine.setSpeed(s)} title={`${s}x: ${s} second${s > 1 ? 's' : ''} of real time per second (keys 1-4)`}
              className={`px-2 py-0.5 rounded text-[11px] font-mono font-semibold transition-colors ${
                speed === s ? 'bg-brand-600 text-white' : 'text-slate-400 hover:text-white'}`}>
              {s}×
            </button>
          ))}
        </div>
        <SkipChip engine={engine} />
        {children}
        <span className="ml-auto text-[10px] text-slate-500 hidden lg:inline">Space play/pause · ← → event · Shift 5 min · 1-4 speed</span>
      </div>

      <div ref={barRef} onPointerDown={onDown} onPointerMove={e => e.buttons === 1 && seekFrom(e)}
        className="relative h-11 cursor-pointer select-none touch-none" role="slider" aria-label="Replay time" aria-valuemin={start} aria-valuemax={end}>
        {density && (
          <div className="absolute inset-x-0 top-0 h-5 flex items-end gap-px opacity-70" aria-hidden>
            {density.map((n, i) => <div key={i} className="flex-1 bg-slate-600 rounded-t-sm" style={{ height: `${(n / peak) * 100}%` }} />)}
          </div>
        )}
        <div className="absolute inset-x-0 top-[22px] h-1.5 rounded-full bg-slate-800" />
        <div ref={fillRef} className="absolute left-0 top-[22px] h-1.5 rounded-full bg-brand-500" />
        {marks.map((m, i) => (
          <button key={i} type="button" title={m.label} aria-label={m.label} onPointerDown={e => e.stopPropagation()}
            onClick={() => { engine.pause(); engine.seek(m.t) }}
            className="absolute top-[13px] w-[18px] h-[18px] -translate-x-1/2 rounded-full flex items-center justify-center hover:scale-125 transition-transform"
            style={{ left: pct(m.t), background: m.colour || '#e2e8f0', boxShadow: m.level === 'bad' ? '0 0 0 2px #fff6' : undefined }}>
            {m.Icon && <m.Icon size={11} color="#fff" strokeWidth={2.6} />}
          </button>
        ))}
        <span ref={headRef} className="absolute top-[18px] w-3.5 h-3.5 -translate-x-1/2 rounded-full bg-white shadow ring-2 ring-brand-500 pointer-events-none" />
        {ticks.map(k => (
          <span key={k.t} className="absolute top-[34px] -translate-x-1/2 text-[9px] text-slate-500 pointer-events-none" style={{ left: pct(k.t) }}>{k.label}</span>
        ))}
      </div>
    </div>
  )
}
