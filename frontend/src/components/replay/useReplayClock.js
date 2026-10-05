import { useCallback, useEffect, useRef, useState } from 'react'

/** Playback speeds: minutes of the real day per second of replay. */
export const SPEEDS = [1, 5, 15, 30, 60]
const FRAME_MS = 33   // ~30 updates a second is smooth enough and keeps React work bounded

export function prefersReducedMotion() {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}

/**
 * The ONE shared replay clock (epoch seconds) for map, scrubber, Gantt playhead and driver card.
 * Adapted from the Studio replay player: Space plays/pauses, arrows step 5 min (Shift: 30 min).
 * Never auto-plays; with reduced motion the user still drives it, nothing animates on its own.
 */
export default function useReplayClock(start, end, { initial, speed: initialSpeed = 15 } = {}) {
  const [t, setTRaw] = useState(initial ?? start)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(initialSpeed)
  const tRef = useRef(t)

  const setT = useCallback(v => {
    const next = Math.min(end, Math.max(start, Math.round(v)))
    tRef.current = next
    setTRaw(next)
  }, [start, end])

  useEffect(() => { setT(initial ?? start) }, [start, end]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!playing) return undefined
    let raf, last = performance.now(), acc = 0
    const tick = now => {
      acc += now - last
      last = now
      if (acc >= FRAME_MS) {
        const next = tRef.current + (acc / 1000) * speed * 60
        acc = 0
        if (next >= end) { setT(end); setPlaying(false); return }
        setT(next)
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing, speed, end, setT])

  const toggle = useCallback(() => {
    if (!playing && tRef.current >= end) setT(start)
    setPlaying(p => !p)
  }, [playing, start, end, setT])

  useEffect(() => {
    const onKey = e => {
      if (e.target.closest?.('input, select, textarea, [contenteditable]')) return
      const step = (e.shiftKey ? 30 : 5) * 60
      if (e.code === 'Space') { e.preventDefault(); toggle() }
      else if (e.key === 'ArrowRight') { e.preventDefault(); setT(tRef.current + step) }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); setT(tRef.current - step) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [toggle, setT])

  return { t, setT, playing, setPlaying, toggle, speed, setSpeed }
}
