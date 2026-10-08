import { useEffect, useMemo, useRef, useState } from 'react'
import { SPEEDS, advance, indexAt, nextEvent, prevEvent } from './engineMath'

export { SPEEDS }

export function prefersReducedMotion() {
  return typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}

/**
 * The ONE replay clock. It runs on requestAnimationFrame and never calls React: layers subscribe and move themselves
 * every frame. React reads it through useEngineState (a few times a second) and useEngineIndex (only when the event changes).
 */
function createEngine(cfg, initial, speed) {
  const frame = new Set(), change = new Set()
  const ref = { current: { t: initial, playing: false, speed, boosted: 0 } }   // boosted = seconds being skipped, 0 = normal
  let raf = 0, last = 0
  const emitFrame = () => frame.forEach(f => f(ref.current.t))
  const emitChange = () => change.forEach(f => f())
  const clamp = v => Math.min(cfg.current.end, Math.max(cfg.current.start, v))
  const tick = now => {
    const s = ref.current
    const r = advance(s.t, Math.min((now - last) / 1000, 0.1), { ...cfg.current, speed: s.speed })
    last = now
    const wasBoosted = s.boosted > 0
    s.t = r.t
    s.boosted = r.boosted ? r.gap : 0
    emitFrame()
    if (r.ended || r.stopped) { api.pause(); return }
    if (wasBoosted !== r.boosted) emitChange()
    raf = requestAnimationFrame(tick)
  }
  const api = {
    ref, cfg,
    subscribe: f => { frame.add(f); return () => frame.delete(f) },
    onChange: f => { change.add(f); return () => change.delete(f) },
    play() {
      const s = ref.current
      if (s.playing) return
      if (s.t >= cfg.current.end) s.t = cfg.current.start
      s.playing = true; last = performance.now(); raf = requestAnimationFrame(tick); emitFrame(); emitChange()
    },
    pause() { const s = ref.current; cancelAnimationFrame(raf); s.playing = false; s.boosted = 0; emitChange() },
    toggle() { if (ref.current.playing) api.pause(); else api.play() },
    seek(t) { ref.current.t = clamp(t); ref.current.boosted = 0; emitFrame(); emitChange() },
    setSpeed(x) { ref.current.speed = x; emitChange() },
    next() { api.seek(nextEvent(cfg.current.events, ref.current.t) ?? cfg.current.end) },
    prev() { api.seek(prevEvent(cfg.current.events, ref.current.t) ?? cfg.current.start) },
    destroy() { cancelAnimationFrame(raf); frame.clear(); change.clear() },
  }
  return api
}

/**
 * useReplayEngine({ start, end, events, initial, speed, busy, stops, keys })
 *   events  sorted epoch seconds that Prev / Next jump between; busy(t) is true while something is moving (no quiet skipping then);
 *   stops   sorted times where playing pauses by itself ("Pause at problems"); keys = Space, arrows, 1-4 (default on).
 */
export default function useReplayEngine({ start, end, events = [], initial, speed = 60, busy, stops = [], keys = true }) {
  const cfg = useRef({ start, end, events, busy, stops })
  cfg.current = { start, end, events, busy, stops }
  const engine = useMemo(() => createEngine(cfg, Math.min(end, Math.max(start, initial ?? start)), speed), []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => engine.destroy(), [engine])
  useEffect(() => { if (engine.ref.current.t < start || engine.ref.current.t > end) engine.seek(initial ?? start) }, [start, end]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!keys) return undefined
    const onKey = e => {
      if (e.target.closest?.('input, select, textarea, [contenteditable]') || e.metaKey || e.ctrlKey || e.altKey) return
      const t = engine.ref.current.t
      if (e.code === 'Space') { e.preventDefault(); engine.toggle() }
      else if (e.key === 'ArrowRight') { e.preventDefault(); if (e.shiftKey) engine.seek(t + 300); else engine.next() }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); if (e.shiftKey) engine.seek(t - 300); else engine.prev() }
      else if (/^[1-4]$/.test(e.key)) engine.setSpeed(SPEEDS[Number(e.key) - 1])
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [engine, keys])
  return engine
}

/** React state of the engine: at most `hz` renders a second while playing, and at once on play / pause / seek / speed. */
export function useEngineState(engine, hz = 4) {
  const [s, setS] = useState(() => ({ ...engine.ref.current }))
  useEffect(() => {
    let lastRender = 0
    const snap = () => { lastRender = performance.now(); setS({ ...engine.ref.current }) }
    const onFrame = () => { if (performance.now() - lastRender >= 1000 / hz) snap() }
    snap()
    const a = engine.subscribe(onFrame), b = engine.onChange(snap)
    return () => { a(); b() }
  }, [engine, hz])
  return s
}

/** Index of the last event at or before t. Re-renders only when it changes. */
export function useEngineIndex(engine, events) {
  const [i, setI] = useState(() => indexAt(events, engine.ref.current.t))
  useEffect(() => {
    const upd = t => setI(indexAt(events, t))
    upd(engine.ref.current.t)
    return engine.subscribe(upd)
  }, [engine, events])
  return i
}
