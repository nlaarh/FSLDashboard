import { useMemo } from 'react'

const ET = 'America/New_York'

/**
 * Minute ↔ % mapping over [startMs, endMs] with hour ticks labelled in Eastern time.
 * Ticks are found by walking real instants, so 23 h / 25 h DST days label correctly.
 */
export default function useTimeScale(startMs, endMs) {
  return useMemo(() => {
    const span = Math.max(endMs - startMs, 1)
    const pct = ms => Math.min(100, Math.max(0, ((ms - startMs) / span) * 100))
    const ticks = []
    const hour = 3600 * 1000
    for (let t = Math.ceil(startMs / hour) * hour; t <= endMs; t += hour) {
      const label = new Date(t).toLocaleTimeString('en-US', { timeZone: ET, hour: 'numeric' })
      ticks.push({ ms: t, left: pct(t), label })
    }
    return { pct, ticks, span }
  }, [startMs, endMs])
}
