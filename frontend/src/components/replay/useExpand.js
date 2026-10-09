import { useEffect, useRef, useState } from 'react'

/**
 * "Expand" for a replay (big-screen mode): the same component tree fills the window instead of being copied, so the playhead, the
 * selected driver and the open tab survive. Put `ref` on the element that gets `fixed inset-0`; Esc or `close` collapses it.
 * `toggleFs` also makes that element the browser's full screen, so the details beside the map stay visible.
 */
export default function useExpand() {
  const ref = useRef(null)
  const [expanded, setExpanded] = useState(false)
  const [isFs, setIsFs] = useState(false)
  useEffect(() => {
    const on = () => setIsFs(!!ref.current && document.fullscreenElement === ref.current)
    document.addEventListener('fullscreenchange', on)
    return () => document.removeEventListener('fullscreenchange', on)
  }, [])
  useEffect(() => {
    if (!expanded) return undefined
    const key = e => { if (e.key === 'Escape') setExpanded(false) }
    const el = ref.current, overflow = document.body.style.overflow
    window.addEventListener('keydown', key)
    document.body.style.overflow = 'hidden'   // the page behind must not scroll
    return () => {
      window.removeEventListener('keydown', key)
      document.body.style.overflow = overflow
      if (document.fullscreenElement && document.fullscreenElement === el) document.exitFullscreen?.()
    }
  }, [expanded])
  const toggleFs = () => (document.fullscreenElement ? document.exitFullscreen() : ref.current?.requestFullscreen?.())
  return { ref, expanded, isFs, open: () => setExpanded(true), close: () => setExpanded(false), toggleFs }
}

/** Classes for the element that holds the replay: a normal block, or the whole window on a dark page. Expanded it is one column that scrolls on a phone,
 *  and map + details side by side from `lg` up (rows = the Tailwind grid-rows class for that screen). */
export const expandShell = (expanded, normal, rows) => (expanded
  ? `fixed inset-0 z-[3000] bg-slate-950 p-3 gap-3 grid grid-cols-1 overflow-y-auto lg:overflow-hidden lg:grid-cols-[minmax(0,1fr)_clamp(360px,26vw,560px)] ${rows}`
  : normal)
