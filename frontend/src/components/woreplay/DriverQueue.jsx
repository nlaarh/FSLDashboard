import { X } from 'lucide-react'
import { etClock } from './contactMarks'
import { shortDriverName } from '../../utils/driverName'

/** What one driver held when the call was given: each call in order (number, status, when it was given, miles from the member),
 *  then the next call they were given. q = peerNotes.queueFromLoad / queueFromPeer. Opens on a click on the truck; the map click or X closes it. */
export default function DriverQueue({ q, onClose }) {
  return (
    <div className="rp-glass rounded-xl p-3 text-xs text-slate-200 space-y-2" style={{ position: 'absolute', left: 64, top: 150, width: 310, zIndex: 1075 }} onClick={e => e.stopPropagation()}>
      <div className="flex items-start gap-2">
        <div className="flex-1 min-w-0"><div className="font-semibold text-white truncate">{shortDriverName(q.title)}</div>{q.at && <div className="text-[11px] text-slate-400">Queue when the call was given, {etClock(q.at)} ET</div>}</div>
        <button onClick={onClose} aria-label="Close" className="text-slate-400 hover:text-white"><X className="w-4 h-4" /></button>
      </div>
      {q.note ? <div className="text-slate-400">{q.note}</div> : q.rows.length ? (
        <ol className="space-y-1">{q.rows.map((j, k) => (
          <li key={`${j.sa}${k}`} className="flex items-center gap-2"><span className="w-4 text-slate-500">{k + 1}</span>
            <span className="flex-1 min-w-0"><b>{j.sa}</b> <span className="text-slate-400">{j.label}</span>{j.given_at && <span className="block text-[11px] text-slate-500">given {etClock(j.given_at)}</span>}</span>
            {j.miles != null && <span className="text-slate-300">{j.miles} mi</span>}</li>
        ))}</ol>
      ) : <div className="text-slate-400">Free: no other calls held at that moment.</div>}
      {q.next && <div className="border-t border-slate-700/60 pt-1.5 text-[11px] text-slate-300">Next: <b>{q.next.sa}</b>{q.next.given_at && <>, given {etClock(q.next.given_at)}</>}{q.next.reached_at ? <>, reached {etClock(q.next.reached_at)}</> : ', not reached'}{q.next.miles != null && <>, {q.next.miles} mi</>}</div>}
      <div className="text-[10px] text-slate-500">Miles are straight-line, from this member's location.</div>
    </div>
  )
}
