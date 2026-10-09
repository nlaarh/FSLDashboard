import { Users, Crosshair, Loader2, Info } from 'lucide-react'
import { peerLabel, peerMoments } from './peerNotes'

/** "Right driver?" tab: the other qualified drivers on shift when the call was given to the driver, nearest first.
 *  peers = /api/call-story/peers answer (undefined = loading, null = unavailable). onShow({ ts, peer }) seeks the replay and highlights that driver.
 *  Only qualified drivers are listed (skills and truck fit the call); the others are counted. Miles are straight-line. */
export default function PeersCard({ peers, onShow }) {
  if (peers === undefined) return <div className="glass rounded-xl p-4 text-sm text-slate-400 flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" />Looking at the garage's other drivers…</div>
  const moments = peerMoments(peers)
  return (
    <div className="glass rounded-xl p-4 space-y-3">
      <div className="text-xs font-semibold text-slate-300 flex items-center gap-1.5"><Users className="w-3.5 h-3.5 text-brand-400" />Other qualified drivers on shift</div>
      {peers === null && <div className="text-xs text-slate-500">The other drivers could not be loaded.</div>}
      {moments.map(m => (
        <section key={m.kind}>
          <h3 className="text-xs font-semibold text-slate-200 mb-1.5">{peerLabel(m.kind)} <span className="font-normal text-slate-400">· {m.clock} ET · {m.drivers.length} qualified{m.not_qualified ? `, ${m.not_qualified} other on-shift not qualified` : ''}{m.no_gps ? `, ${m.no_gps} with no recent GPS` : ''}</span></h3>
          {m.drivers.length ? (
            <ul className="space-y-1">
              {m.drivers.map(d => (
                <li key={d.name}>
                  <button onClick={() => onShow?.({ ts: m.at, peer: d.name })} title="Show on the map" className="w-full text-left rounded-lg border border-slate-700/70 bg-slate-900/50 hover:bg-slate-800/70 px-3 py-1.5 flex items-center gap-3 text-xs">
                    <span className="flex-1 min-w-0 font-semibold text-slate-100 truncate">{d.name}</span>
                    <span className="text-slate-300 w-40 shrink-0">{d.label}</span>
                    <span className="text-slate-300 w-16 shrink-0 text-right">{d.miles} mi</span>
                    <span className="text-slate-400 w-20 shrink-0 text-right">{d.held} call{d.held === 1 ? '' : 's'} held</span>
                    <Crosshair className="w-3.5 h-3.5 text-brand-300 shrink-0" />
                  </button>
                </li>
              ))}
            </ul>
          ) : <div className="text-xs text-slate-500">No other qualified driver was visible on shift at that moment.</div>}
        </section>
      ))}
      {(peers?.notes || []).map((n, k) => <div key={k} className="text-[11px] text-slate-500 flex gap-1.5"><Info className="w-3 h-3 shrink-0 mt-0.5" />{n}</div>)}
    </div>
  )
}
