import { Truck, Crosshair, Hourglass, Navigation, MapPin, Wrench, Info } from 'lucide-react'
import { etClock } from './contactMarks'

const CHANNEL = { fleet: 'Fleet', on_platform: 'On-Platform', towbook: 'Towbook' }
const STATE = {
  towing: { icon: Truck, cls: 'bg-rose-500/15 text-rose-300 border-rose-500/40' },
  'on location': { icon: MapPin, cls: 'bg-amber-500/15 text-amber-300 border-amber-500/40' },
  'en route': { icon: Navigation, cls: 'bg-amber-500/15 text-amber-300 border-amber-500/40' },
  dispatched: { icon: Hourglass, cls: 'bg-slate-500/15 text-slate-300 border-slate-500/40' },
  accepted: { icon: Hourglass, cls: 'bg-slate-500/15 text-slate-300 border-slate-500/40' },
}

function Job({ job, extra, right }) {
  const st = STATE[job.state] || STATE.dispatched, Icon = st.icon
  return (
    <li className="rounded-lg border border-slate-700/70 bg-slate-900/50 px-3 py-2 flex items-center gap-3">
      <Wrench className="w-4 h-4 text-slate-500 shrink-0" />
      <span className="flex-1 min-w-0">
        <span className="block text-xs font-semibold text-slate-100">Work order {job.wo || job.sa} <span className="font-normal text-slate-400">· {job.work_type.replace(/ Pick-Up$/i, '')}</span></span>
        {extra && <span className="block text-[11px] text-slate-400">{extra}</span>}
      </span>
      {job.label && <span className={`px-2 py-0.5 rounded-full border text-[11px] flex items-center gap-1 ${st.cls}`}><Icon className="w-3 h-3" />{job.label}</span>}
      {right}
    </li>
  )
}

/** Driver's other jobs tab. load = extras.driver_load[0] (or undefined), notes = extras.notes, onShow(ts) seeks the replay.
 *  Towbook drivers are never named: the answer already says "Towbook Driver". */
export default function DriverLoadCard({ load, notes = [], onShow }) {
  const who = load?.channel === 'towbook' ? 'the Towbook driver' : load?.driver
  const showBtn = ts => ts && onShow && <button onClick={() => onShow(ts)} className="text-[11px] text-brand-300 hover:text-brand-200 flex items-center gap-1 shrink-0"><Crosshair className="w-3 h-3" />Show</button>
  return (
    <div className="glass rounded-xl p-4 space-y-3">
      {!load && <div className="text-sm text-slate-400">No driver took this call, so there are no other jobs to compare.</div>}
      {load && <>
        <div className="flex items-center gap-2 flex-wrap">
          <Truck className="w-4 h-4 text-brand-400" />
          <span className="text-sm font-semibold text-white">{load.driver}</span>
          <span className="px-2 py-0.5 rounded-full border border-slate-600 text-[11px] text-slate-300">{CHANNEL[load.channel] || load.channel}</span>
          <span className="text-xs text-slate-400 ml-auto flex items-center gap-2">Call given to {who} at {etClock(load.given_at)} ET {showBtn(load.given_at)}</span>
        </div>
        <section>
          <h3 className="text-xs font-semibold text-amber-300 mb-1.5">Jobs they still had to finish first ({load.ahead.length})</h3>
          {load.ahead.length ? <ul className="space-y-1.5">{load.ahead.map(j => <Job key={j.wo} job={j} extra={j.is_current ? 'Already under way when this call was given to them' : 'Waiting to start'} />)}</ul>
            : <div className="text-xs text-slate-500">Nothing. The driver was free when this call was given to them.</div>}
        </section>
        <section>
          <h3 className="text-xs font-semibold text-rose-300 mb-1.5">Jobs that jumped the queue ({load.after.length})</h3>
          {load.after.length ? <ul className="space-y-1.5">{load.after.map(j => (
            <Job key={j.wo} job={j} right={showBtn(j.reached_at)} extra={`Given to the driver at ${etClock(j.given_at)}, reached at ${etClock(j.reached_at)}, before this member`} />
          ))}</ul> : <div className="text-xs text-slate-500">None. Every job given after this one was served after this member.</div>}
        </section>
        <div className="text-[11px] text-slate-500">{load.jobs_in_window} other job{load.jobs_in_window === 1 ? '' : 's'} looked at around this call. Drop-off legs are not counted as separate jobs.</div>
      </>}
      {notes.map((n, k) => <div key={k} className="text-[11px] text-slate-500 flex gap-1.5"><Info className="w-3 h-3 shrink-0 mt-0.5" />{n}</div>)}
    </div>
  )
}
