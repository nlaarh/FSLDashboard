import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { AlertTriangle, Loader2, PanelRightClose, PanelRightOpen, Radio, RefreshCw, Siren } from 'lucide-react'
import { fetchGarages } from '../../api'
import GaragePicker from './GaragePicker'
import GarageLiveMap from './GarageLiveMap'
import AttentionDrawer from './AttentionDrawer'
import useGarageLive from './useGarageLive'
import { DRIVER_STATUS, dataAgeS, initialGarage, readLast, replayAlert, writeLast } from './garageLiveModel'

const CallMapView = lazy(() => import('../callmap/CallMapView'))     // the full-window call map loads only when opened
const KIND = { fleet: 'Fleet', on_platform: 'On-Platform contractor', towbook: 'Towbook' }
const chip = 'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold'

/**
 * Garage Live: the dispatcher's watch tower for one garage. The garage is in the URL (?tab=garage-live&garage=ID) and remembered for next time,
 * so coming back opens it with no click. Map on the left, "Needs attention" drawer on the right (under the map on a phone).
 */
export default function GarageLive() {
  const [params, setParams] = useSearchParams()
  const [garages, setGarages] = useState(null)
  const [garagesError, setGaragesError] = useState(null)
  const [drawer, setDrawer] = useState(true)
  const [focus, setFocus] = useState(null)
  const [replay, setReplay] = useState(null)
  const [nowMs, setNowMs] = useState(() => Date.now())

  const urlId = params.get('garage')
  const garageId = urlId || initialGarage(null, readLast(), null)
  const { data, error, stale, loading, receivedAt, reload } = useGarageLive(garageId)

  useEffect(() => { fetchGarages().then(setGarages).catch(() => setGaragesError('The garage list could not be loaded.')) }, [])
  useEffect(() => {                                              // put a remembered garage into the URL so the page can be shared and reloaded
    if (!urlId && garageId) setParams(p => { const n = new URLSearchParams(p); n.set('garage', garageId); return n }, { replace: true })
  }, [urlId, garageId, setParams])
  useEffect(() => { if (garageId) writeLast(garageId) }, [garageId])
  useEffect(() => { const id = setInterval(() => setNowMs(Date.now()), 1000); return () => clearInterval(id) }, [])

  const pick = useCallback(id => {
    setFocus(null)
    setParams(p => { const n = new URLSearchParams(p); n.set('garage', id); return n }, { replace: true })
  }, [setParams])
  const openReplay = useCallback(saId => { const t = data?.tickets.find(x => x.sa_id === saId); if (t) setReplay(replayAlert(t, data.garage)); else setReplay({ sa_id: saId, sa_number: data?.attention.find(i => i.sa_id === saId)?.sa_number, facility_name: data?.garage.name }) }, [data])

  const age = dataAgeS(data, receivedAt, nowMs)
  const s = data?.summary

  return (
    <div className="h-full flex flex-col overflow-y-auto lg:overflow-hidden bg-slate-950 text-slate-100">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5 border-b border-slate-800 bg-slate-900/80">
        <GaragePicker garages={garages} loading={!garages && !garagesError} value={garageId} onPick={pick} autoOpen={!garageId} />
        {data && <span className={`${chip} border-slate-600 text-slate-300`}>{KIND[data.garage.kind]}</span>}
        {s && (
          <>
            <span className={`${chip} border-slate-600 text-slate-200`}>{s.open_calls} open call{s.open_calls === 1 ? '' : 's'}</span>
            <span className={`${chip} ${s.late_calls ? 'border-red-500/50 bg-red-500/15 text-red-300' : 'border-slate-600 text-slate-300'}`}>
              <Siren className="w-3.5 h-3.5" />{s.late_calls} late</span>
            {data.garage.has_gps
              ? <span className={`${chip} border-slate-600 text-slate-200`} title="Free / busy / off shift">
                  <i className="w-2 h-2 rounded-full" style={{ background: DRIVER_STATUS.free.colour }} />{s.drivers.free} free
                  <span className="text-slate-500">·</span>{s.drivers.busy} busy<span className="text-slate-500">·</span>{s.drivers.off} off</span>
              : <span className={`${chip} border-amber-500/40 bg-amber-500/10 text-amber-200`}>Towbook garage — no driver GPS</span>}
          </>)}
        <div className="ml-auto flex items-center gap-3 text-xs">
          {stale && <span className="text-amber-300 flex items-center gap-1"><AlertTriangle className="w-3.5 h-3.5" />Could not refresh; showing the last data</span>}
          {data && <span className="flex items-center gap-1.5 text-emerald-300 font-semibold" title="Tickets and flags as of this moment; each driver's GPS time is in their card">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />LIVE · updated {age}s ago</span>}
          {garageId && <button type="button" onClick={reload} aria-label="Refresh now" className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700"><RefreshCw className="w-4 h-4" /></button>}
          {data && <button type="button" onClick={() => setDrawer(o => !o)} className="inline-flex items-center gap-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 px-2.5 py-1.5 font-semibold">
            {drawer ? <PanelRightClose className="w-4 h-4" /> : <PanelRightOpen className="w-4 h-4" />}Needs attention{data.attention.length ? ` (${data.attention.length})` : ''}</button>}
        </div>
      </div>

      {!garageId && <div className="flex-1 flex items-center justify-center text-slate-400 text-sm p-6">Pick a garage to watch its calls and drivers live.</div>}
      {garageId && loading && !data && <div className="flex-1 flex items-center justify-center gap-2 text-slate-400"><Loader2 className="w-6 h-6 animate-spin text-sky-400" />Reading the garage…</div>}
      {garageId && error && !data && <div className="flex-1 flex items-center justify-center gap-2 text-rose-300"><AlertTriangle className="w-5 h-5" />{error}</div>}

      {data && (
        <div className="flex-1 min-h-0 flex flex-col lg:flex-row gap-3 p-3">
          <div className="relative h-[62vh] lg:h-auto lg:flex-1 min-h-[320px] rounded-xl overflow-hidden border border-slate-700/70 shrink-0 lg:shrink">
            <GarageLiveMap data={data} focus={focus} canReplay={data.can_replay} onReplay={openReplay} />
            <div className="absolute bottom-3 left-3 z-[1000] flex flex-col gap-1.5 pointer-events-none max-w-[calc(100%-1.5rem)]">
              {data.notes.map(n => <div key={n} className="rp-glass rounded-lg px-3 py-1.5 text-xs text-amber-200">{n}</div>)}
              <div className="rp-glass rounded-lg px-3 py-1.5 text-xs text-slate-300 flex flex-wrap gap-x-3 gap-y-1">
                <span className="flex items-center gap-1"><Radio className="w-3 h-3 text-emerald-400" />Pins: green on time · yellow up to 30 min late · orange 30–90 · red 90+</span>
                {data.garage.has_gps && Object.values(DRIVER_STATUS).map(x => <span key={x.label} className="flex items-center gap-1"><i className="w-2 h-2 rounded-full" style={{ background: x.colour }} />{x.short}</span>)}
              </div>
            </div>
          </div>
          {drawer && <div className="lg:w-[400px] shrink-0 h-[60vh] lg:h-auto min-h-0">
            <AttentionDrawer data={data} activeId={focus?.key} onFocus={setFocus} onReplay={openReplay} onClose={() => setDrawer(false)} />
          </div>}
        </div>)}

      {replay && <Suspense fallback={null}><CallMapView alert={replay} backLabel="Garage Live" onClose={() => setReplay(null)} /></Suspense>}
    </div>
  )
}
