import { lazy, Suspense, useEffect, useState } from 'react'
import { Loader2, AlertTriangle, Target } from 'lucide-react'
import { fetchCallStoryReplay, fetchCallStoryReplayMap } from '../../api'
import TakeawaysCard from './TakeawaysCard'

const WoReplayStage = lazy(() => import('./WoReplayStage'))   // the map stage loads only when a replay opens

const MSG = {
  404: 'No work order or service appointment with that number.',
  409: 'That number matches more than one call. Try the SA number.',
  400: 'That is not a work order or SA number.',
  422: 'That call type is not supported by the replay.',
  503: 'Salesforce is busy. Try again in a moment.',
}

/** Fetches one call's replay and plays it. Shared by the Work Order tab and the Garage tab. */
export default function ReplayPanel({ q }) {
  const [state, setState] = useState({ phase: 'idle' })
  const [jump, setJump] = useState(null)             // asks the stage to show a step: { id, n }
  const [locations, setLocations] = useState(undefined)   // undefined = loading, null = unavailable
  useEffect(() => {
    if (!q) { setState({ phase: 'idle' }); return undefined }
    let live = true
    setState({ phase: 'loading' })
    setLocations(undefined)
    fetchCallStoryReplay(q)
      .then(({ status, data }) => live && setState(status === 200 ? { phase: 'ready', data } : { phase: 'error', error: MSG[status] || data?.detail || `Replay unavailable (${status})` }))
      .catch(e => live && setState({ phase: 'error', error: e.message }))
    // The map loads after the animation: Salesforce's driver GPS history is its slowest read.
    fetchCallStoryReplayMap(q)
      .then(({ status, data }) => live && setLocations(status === 200 ? data : null))
      .catch(() => live && setLocations(null))
    return () => { live = false }
  }, [q])

  if (state.phase === 'idle') return null
  if (state.phase === 'loading') return <div className="glass rounded-xl p-8 flex flex-col items-center gap-2 text-sm text-slate-400"><Loader2 className="w-6 h-6 text-brand-400 animate-spin" />Reading the call from Salesforce…</div>
  if (state.phase === 'error') return <div className="glass rounded-xl p-6 flex items-center gap-3 text-sm text-rose-300"><AlertTriangle className="w-5 h-5 shrink-0" />{state.error}</div>
  const { header, steps, decision, takeaways } = state.data
  if (!steps.length) return <div className="glass rounded-xl p-6 text-sm text-slate-400">This call has no recorded steps to replay.</div>
  return (
    <div className="space-y-3">
      <Suspense fallback={<div className="glass rounded-xl p-8 flex justify-center"><Loader2 className="w-6 h-6 text-brand-400 animate-spin" /></div>}>
        <WoReplayStage key={header.sa} steps={steps} header={header} locations={locations} jump={jump} />
      </Suspense>
      <TakeawaysCard takeaways={takeaways} onShow={id => { setJump(j => ({ id, n: (j?.n || 0) + 1 })); window.scrollTo?.({ top: 0, behavior: 'smooth' }) }} />
      <div className="grid gap-3">
        {decision && (
          <div className="glass rounded-xl p-4">
            <div className="text-xs font-semibold text-slate-300 mb-2 flex items-center gap-1.5"><Target className="w-3.5 h-3.5 text-brand-400" />Was it the right driver?</div>
            <div className="text-xs text-slate-300 space-y-1">
              <div>Picked by: <b>{decision.who_decided}</b> · {decision.candidates} candidates</div>
              <div>Pick: <b>{decision.pick_miles} mi</b> away, {decision.pick_open_jobs} other open job{decision.pick_open_jobs === 1 ? '' : 's'}{decision.pick_qualified === false && <span className="text-rose-300"> · not qualified</span>}</div>
              <div>Closest qualified driver: <b>{decision.closest_qualified_miles ?? 'n/a'} mi</b> {decision.picked_closest === false ? <span className="text-amber-300">(not the one picked)</span> : decision.picked_closest ? <span className="text-emerald-300">(the one picked)</span> : null}</div>
              {decision.closest_free_miles != null && <div>Closest free qualified driver: <b>{decision.closest_free_miles} mi</b></div>}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
