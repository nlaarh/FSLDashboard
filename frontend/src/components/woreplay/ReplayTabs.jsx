import { useSearchParams } from 'react-router-dom'
import { Target, Loader2 } from 'lucide-react'
import TakeawaysCard from './TakeawaysCard'
import ContactPanel from './ContactPanel'
import DriverLoadCard from './DriverLoadCard'
import InsightStrip from './InsightStrip'
import { isFromMember } from './contactMarks'

function Decision({ decision }) {
  if (!decision) return <div className="glass rounded-xl p-6 text-sm text-slate-400">No driver choice to review for this call.</div>
  return (
    <div className="glass rounded-xl p-4">
      <div className="text-xs font-semibold text-slate-300 mb-2 flex items-center gap-1.5"><Target className="w-3.5 h-3.5 text-brand-400" />Was it the right driver?</div>
      <div className="text-xs text-slate-300 space-y-1">
        <div>Picked by: <b>{decision.who_decided}</b> · {decision.candidates} candidates</div>
        <div>Pick: <b>{decision.pick_miles} mi</b> away, {decision.pick_open_jobs} other open job{decision.pick_open_jobs === 1 ? '' : 's'}{decision.pick_qualified === false && <span className="text-rose-300"> · not qualified</span>}</div>
        <div>Closest qualified driver: <b>{decision.closest_qualified_miles ?? 'n/a'} mi</b> {decision.picked_closest === false ? <span className="text-amber-300">(not the one picked)</span> : decision.picked_closest ? <span className="text-emerald-300">(the one picked)</span> : null}</div>
        {decision.closest_free_miles != null && <div>Closest free qualified driver: <b>{decision.closest_free_miles} mi</b></div>}
      </div>
    </div>
  )
}

/** Everything below the replay stage as tabs, one visible at a time (URL: ?rtab=wrong|contact|jobs|driver), with the insight strip above.
 *  props: q, takeaways, decision (from the replay answer), extras (undefined = loading, null = switched off / unavailable),
 *  marks (contactMarks), openMark + onOpenMark (the open contact row: the stage's icons set it too), onShow(id | { ts }) seeks the replay.
 *  The contact and jobs tabs exist only when extras loaded, so with the flag off the page looks as it did before. */
export default function ReplayTabs({ q, takeaways, decision, extras, marks = [], openMark, onOpenMark, onShow }) {
  const [params, setParams] = useSearchParams()
  const load = extras?.driver_load?.[0]
  const tabs = [{ id: 'wrong', label: 'What went wrong' }]
  if (extras !== null) {
    tabs.push({ id: 'contact', label: 'Member contact', n: extras ? marks.filter(isFromMember).length : undefined })
    tabs.push({ id: 'jobs', label: "Driver's other jobs", n: extras ? (load ? load.ahead.length + load.after.length : 0) : undefined })
  }
  tabs.push({ id: 'driver', label: 'Right driver?' })
  const wanted = params.get('rtab')
  const tab = tabs.some(t => t.id === wanted) ? wanted : 'wrong'
  const pick = id => setParams(p => { const n = new URLSearchParams(p); n.set('rtab', id); return n }, { replace: true })
  const seek = ts => onShow?.({ ts })
  return (
    <div className="space-y-3">
      <InsightStrip insights={extras?.insights} onShow={seek} />
      <div role="tablist" className="flex gap-1 border-b border-slate-700/60 overflow-x-auto">
        {tabs.map(t => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => pick(t.id)}
            className={`px-3 py-2 text-xs font-medium whitespace-nowrap border-b-2 -mb-px flex items-center gap-1.5 ${tab === t.id ? 'border-brand-400 text-white' : 'border-transparent text-slate-400 hover:text-slate-200'}`}>
            {t.label}
            {t.n !== undefined && <span className="px-1.5 rounded-full bg-slate-700/70 text-[10px] text-slate-200">{t.n}</span>}
            {t.id !== 'wrong' && t.id !== 'driver' && extras === undefined && <Loader2 className="w-3 h-3 animate-spin text-slate-500" />}
          </button>
        ))}
      </div>
      {tab === 'wrong' && <TakeawaysCard takeaways={takeaways} onShow={onShow} />}
      {tab === 'contact' && (extras === undefined ? <div className="glass rounded-xl p-6 text-sm text-slate-400 flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" />Looking for the member's calls and texts…</div>
        : <ContactPanel q={q} marks={marks} extras={extras} openId={openMark} onOpen={onOpenMark} onShow={seek} />)}
      {tab === 'jobs' && (extras === undefined ? <div className="glass rounded-xl p-6 text-sm text-slate-400 flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" />Looking at the driver's other jobs…</div>
        : <DriverLoadCard load={load} notes={extras.notes} onShow={seek} />)}
      {tab === 'driver' && <Decision decision={decision} />}
    </div>
  )
}
