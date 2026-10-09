import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { User, MessageSquare, Headset, Truck, Cpu, Flag, AlertTriangle } from 'lucide-react'
import { useEngineIndex } from '../replay/useReplayEngine'
import { toastFor, KINDS } from './woReplayModel'

export const KIND_ICON = { member: User, sms: MessageSquare, human: Headset, driver: Truck, system: Cpu, mark: Flag }
const SHOW_MS = 3500, MAX = 3

/**
 * Small notes that slide in (bottom left, above the caption) as each step plays: icon, ET time, one line. Red when flagged.
 * `steps` is the story; `times` its epoch seconds. Appears on any change of step (playing, Next, or a click on the scrubber),
 * never for the first step shown on load.
 */
export default function EventToasts({ engine, steps, times, bottom = 84 }) {
  const idx = useEngineIndex(engine, times)
  const prev = useRef(idx)
  const [items, setItems] = useState([])
  useEffect(() => {
    if (idx === prev.current) return
    const from = prev.current
    prev.current = idx
    const t = idx >= 0 ? toastFor(steps, idx) : null
    if (!t || (from === -1 && !engine.ref.current.playing)) return
    const id = `${idx}:${Date.now()}`
    setItems(a => [...a.slice(-(MAX - 1)), { ...t, id }])
    setTimeout(() => setItems(a => a.filter(x => x.id !== id)), SHOW_MS)   // each toast leaves on its own clock, so it is not cleared when the next step comes
  }, [idx, steps, engine])
  return (
    <div className="absolute left-3 flex flex-col gap-1.5 items-start pointer-events-none" style={{ bottom, zIndex: 1065 }} aria-live="polite">
      <AnimatePresence initial={false}>
        {items.map(it => {
          const Icon = it.level === 'bad' || it.level === 'warn' ? AlertTriangle : KIND_ICON[it.kind] || Flag
          const colour = it.level === 'bad' ? '#f43f5e' : it.level === 'warn' ? '#f59e0b' : (KINDS[it.kind] || KINDS.system).colour
          return (
            <motion.div key={it.id} layout initial={{ opacity: 0, x: -28 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -28 }} transition={{ duration: 0.22 }}
              className="rp-glass rounded-xl pl-2 pr-3 py-1.5 flex items-center gap-2 max-w-[340px]" style={{ borderColor: `${colour}99` }}>
              <span className="w-7 h-7 rounded-full flex items-center justify-center shrink-0" style={{ background: `${colour}33`, color: colour }}><Icon size={16} /></span>
              <span className="min-w-0">
                <span className="block text-[10px] font-mono text-slate-400 leading-3">{it.clock}</span>
                <span className="block text-[12.5px] font-semibold text-white leading-4">{it.text}</span>
              </span>
            </motion.div>
          )
        })}
      </AnimatePresence>
    </div>
  )
}
