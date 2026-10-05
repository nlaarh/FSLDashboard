import { useCallback, useEffect, useRef, useState } from 'react'

export const SPEEDS = [0.25, 0.5, 1, 2]

/** Animation clock in seconds (not real time): play, pause, speed and scrub. Never auto-plays. */
export default function useStepClock(total) {
  const [tau, setTauRaw] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const ref = useRef(0)
  const setTau = useCallback(v => { const n = Math.min(total, Math.max(0, v)); ref.current = n; setTauRaw(n) }, [total])

  useEffect(() => {
    if (!playing) return undefined
    let raf, last = performance.now()
    const tick = now => {
      const next = ref.current + ((now - last) / 1000) * speed
      last = now
      if (next >= total) { setTau(total); setPlaying(false); return }
      setTau(next)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing, speed, total, setTau])

  const toggle = useCallback(() => {
    if (!playing && ref.current >= total) setTau(0)
    setPlaying(p => !p)
  }, [playing, total, setTau])
  return { tau, setTau, playing, setPlaying, toggle, speed, setSpeed }
}
