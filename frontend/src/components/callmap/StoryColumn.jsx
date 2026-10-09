import { useEffect, useRef, useState } from 'react'
import { Briefcase, Crosshair } from 'lucide-react'
import { KIND_ICON } from '../woreplay/EventToasts'
import { MARK_ICON, Detail } from '../woreplay/ContactPanel'
import { etClock } from '../woreplay/contactMarks'

export const iconFor = e => (e.cat === 'case' ? Briefcase : e.cat === 'contact' ? MARK_ICON[e.type] : KIND_ICON[e.type]) || KIND_ICON.mark

/**
 * "What happened on this call": every event in order (who touched it, assignments, declines, member calls and texts, cases).
 * Events after the slider's time are dimmed; the one at the slider is highlighted and kept in view. A click moves the slider there;
 * a member call or text opens its detail (message text only when the user may read texts: `canReadTexts`).
 */
export default function StoryColumn({ events, t, saId, extras, canReadTexts, onSeek }) {
  const [open, setOpen] = useState(null)
  const cur = events.reduce((a, e, i) => (e.t <= t ? i : a), -1)
  const curRef = useRef(null)
  useEffect(() => { curRef.current?.scrollIntoView?.({ block: 'nearest' }) }, [cur, events.length])
  if (!events.length) return <div className="rounded-xl border border-slate-700/70 bg-slate-900/70 p-4 text-sm text-slate-400">Nothing has been recorded for this call yet.</div>
  return (
    <ol className="space-y-1.5" aria-label="What happened on this call">
      {events.map((e, i) => {
        const Icon = iconFor(e)
        const expandable = e.cat === 'contact' && (e.type !== 'text_in' || canReadTexts) && e.type !== 'text_out'
        const isOpen = open === e.id
        return (
          <li key={e.id} ref={i === cur ? curRef : null} className={`rounded-lg border ${i === cur ? 'border-sky-400 bg-slate-800' : 'border-slate-700/70 bg-slate-900/60'} ${e.t > t ? 'opacity-45' : ''}`}>
            <button type="button" onClick={() => (expandable ? setOpen(isOpen ? null : e.id) : onSeek(e.t))} aria-expanded={expandable ? isOpen : undefined}
              className="w-full text-left px-2.5 py-2 flex items-start gap-2.5">
              <span className="w-7 h-7 rounded-full flex items-center justify-center shrink-0 mt-0.5" style={{ background: `${e.colour}33`, color: e.colour }}><Icon className="w-4 h-4" /></span>
              <span className="flex-1 min-w-0">
                <span className={`block text-xs font-semibold ${e.level === 'bad' ? 'text-rose-300' : 'text-slate-100'}`}>{e.title}</span>
                {e.detail && <span className="block text-[11px] text-slate-400 break-words">{e.detail}</span>}
                {e.actor && <span className="block text-[11px] text-slate-500">{e.actor}</span>}
              </span>
              <span className="text-[11px] text-slate-300 tabular-nums shrink-0 mt-0.5">{etClock(e.ts)}</span>
            </button>
            {isOpen && (
              <div className="px-3 pb-3 pt-2 border-t border-slate-800 space-y-2">
                <Detail mark={e.mark} extras={extras} q={saId} />
                <button type="button" onClick={() => onSeek(e.t)} className="text-[11px] text-sky-300 hover:text-sky-200 flex items-center gap-1"><Crosshair className="w-3 h-3" />Move the slider here</button>
              </div>
            )}
          </li>
        )
      })}
    </ol>
  )
}
