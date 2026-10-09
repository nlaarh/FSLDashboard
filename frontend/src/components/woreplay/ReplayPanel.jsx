import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { Loader2, AlertTriangle } from 'lucide-react'
import { loadStoryReplay, loadStoryMap } from '../reportcard/prefetch'
import useExpand, { expandShell } from '../replay/useExpand'
import { ExpandBar } from '../replay/ExpandControls'
import ReplayTabs from './ReplayTabs'
import ContactPanel from './ContactPanel'
import useReplayExtras from './useReplayExtras'
import useReplayPeers from './useReplayPeers'

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
  const expand = useExpand()
  const [jump, setJump] = useState(null)             // asks the stage to show a step: { id, n }
  const [locations, setLocations] = useState(undefined)   // undefined = loading, null = unavailable
  const [peerFocus, setPeerFocus] = useState(null)   // the other driver highlighted on the map
  const [openMark, setOpenMark] = useState(null)     // the open row of the Member contact tab
  const [stageMark, setStageMark] = useState(null)   // the contact icon clicked on the stage: its card opens beside the map
  const { extras, marks } = useReplayExtras(q, state.phase === 'ready', state.data?.steps)
  const load = extras?.driver_load?.[0]
  const { peers, moments } = useReplayPeers(q, state.phase === 'ready' && locations !== undefined)   // after the trucks, so it never slows the first picture
  const driverJobs = useMemo(() => (load ? [...load.ahead.map(j => ({ ...j, id: `a:${j.wo || j.sa}`, ahead: true })), ...load.after.map(j => ({ ...j, id: `x:${j.wo || j.sa}`, ahead: false }))] : []), [load])
  const seek = arg => { setPeerFocus(arg?.peer || null); setJump(j => ({ ...(typeof arg === 'object' ? arg : { id: arg }), n: (j?.n || 0) + 1 })); window.scrollTo?.({ top: 0, behavior: 'smooth' }) }
  useEffect(() => {
    if (!q) { setState({ phase: 'idle' }); return undefined }
    let live = true
    setState({ phase: 'loading' })
    setLocations(undefined); setOpenMark(null); setStageMark(null)
    loadStoryReplay(q)
      .then(({ status, data }) => live && setState(status === 200 ? { phase: 'ready', data } : { phase: 'error', error: MSG[status] || data?.detail || `Replay unavailable (${status})` }))
      .catch(e => live && setState({ phase: 'error', error: e.message }))
    // The map loads after the animation: Salesforce's driver GPS history is its slowest read.
    loadStoryMap(q)
      .then(({ status, data }) => live && setLocations(status === 200 ? data : null))
      .catch(() => live && setLocations(null))
    return () => { live = false }
  }, [q])

  if (state.phase === 'idle') return null
  if (state.phase === 'loading') return <div className="glass rounded-xl p-8 flex flex-col items-center gap-2 text-sm text-slate-400"><Loader2 className="w-6 h-6 text-brand-400 animate-spin" />Reading the call from Salesforce…</div>
  if (state.phase === 'error') return <div className="glass rounded-xl p-6 flex items-center gap-3 text-sm text-rose-300"><AlertTriangle className="w-5 h-5 shrink-0" />{state.error}</div>
  const { header, steps, decision, takeaways } = state.data
  if (!steps.length) return <div className="glass rounded-xl p-6 text-sm text-slate-400">This call has no recorded steps to replay.</div>
  const shown = marks.find(m => m.id === stageMark)
  const card = shown && (
    <div className="p-3 overflow-y-auto" style={{ maxHeight: '55%', borderBottom: '1px solid #33415588' }}>
      <ContactPanel q={q} marks={[shown]} extras={extras} openId={shown.id} onOpen={() => setStageMark(null)} onShow={ts => seek({ ts })} />
    </div>
  )
  return (
    <div ref={expand.ref} className={expandShell(expand.expanded, 'space-y-3', 'lg:grid-rows-[auto_minmax(0,1fr)]')}>
      <ExpandBar expand={expand} title={`Work order replay · ${q}`} className="lg:col-span-2" />
      <div className={expand.expanded ? 'min-h-0 min-w-0 h-[85vh] lg:h-auto' : 'min-w-0'}><Suspense fallback={<div className="glass rounded-xl p-8 flex justify-center"><Loader2 className="w-6 h-6 text-brand-400 animate-spin" /></div>}>
        <WoReplayStage key={header.sa} steps={steps} header={header} locations={locations} jump={jump}
          marks={extras ? marks : undefined} onMark={m => { setStageMark(m.id); setOpenMark(m.id) }} driverJobs={extras ? driverJobs : undefined} extrasLoading={extras === undefined} drawerTop={card} peers={moments} peerFocus={peerFocus} driverLoad={load} expand={expand} />
      </Suspense></div>
      <div className={expand.expanded ? 'min-h-0 lg:overflow-y-auto' : ''}><ReplayTabs q={q} takeaways={takeaways} decision={decision} peers={peers} extras={extras} marks={marks} openMark={openMark} onOpenMark={setOpenMark} onShow={seek} /></div>
    </div>
  )
}
