import { PhoneIncoming, MessageCircleReply, Truck, Users, Crosshair } from 'lucide-react'

const LEVEL = {
  bad: 'border-rose-500/50 bg-rose-500/10 text-rose-100',
  warn: 'border-amber-500/50 bg-amber-500/10 text-amber-100',
  info: 'border-slate-600/60 bg-slate-800/50 text-slate-200',
}
const ICON = { CALLED_BACK: PhoneIncoming, TEXTED_IN: MessageCircleReply, DRIVER_AHEAD: Truck, DRIVER_MORE_AFTER: Users }

/** Up to four plain-words callouts about the member's calls, texts and the driver's workload, worst first.
 *  props: insights (extras.insights), onShow(ts) seeks the replay to the moment. Renders nothing when there are none. */
export default function InsightStrip({ insights, onShow }) {
  if (!insights?.length) return null
  return (
    <div className="grid gap-2 md:grid-cols-2" role="list" aria-label="Member contact and driver workload">
      {insights.map(i => {
        const Icon = ICON[i.code] || Truck
        return (
          <div key={i.code} role="listitem" className={`rounded-xl border px-3 py-2.5 flex items-start gap-2.5 ${LEVEL[i.level] || LEVEL.info}`}>
            <Icon className="w-4 h-4 shrink-0 mt-0.5" />
            <span className="text-xs flex-1">{i.text}</span>
            {i.ts && onShow && <button onClick={() => onShow(i.ts)} className="text-[11px] text-slate-300 hover:text-white flex items-center gap-1 shrink-0"><Crosshair className="w-3 h-3" />Show</button>}
          </div>
        )
      })}
    </div>
  )
}
