import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ArrowLeft, Loader2, AlertTriangle, ExternalLink, Lightbulb, RotateCcw, Radio, Maximize2, Minimize2 } from 'lucide-react'
import useReplayEngine, { useEngineState } from '../replay/useReplayEngine'
import ReplayPlayer from '../replay/ReplayPlayer'
import { onSceneTs } from '../woreplay/woReplayModel'
import { DEFAULT_SPEED } from '../replay/engineMath'
import ReplayPanel from '../woreplay/ReplayPanel'
import GarageLiveMap from '../garagelive/GarageLiveMap'
import { DRIVER_STATUS } from '../garagelive/garageLiveModel'
import useCallMap from './useCallMap'
import QuickInfo from './QuickInfo'
import StoryColumn, { iconFor } from './StoryColumn'
import { asGarageLive, buildEvents, pinState, toS } from './callMapModel'

const SF_BASE = 'https://aaawcny.lightning.force.com'
const LIVE_SLACK_S = 90                     // the slider counts as "at now" within this many seconds of it
const EMPTY = []
const clockET = s => new Date(s * 1000).toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit' })

/**
 * The Watchlist call map: a full-window view of one open call (not a split screen). Back button or Esc closes it.
 * alert = the Watchlist row; flagClass = the row's flag chip colours. The data refreshes every 60 s while this is open and the tab is visible.
 * Now (the default): Garage Live's map shows the qualified drivers on shift with their status and the assigned driver's line to the member.
 * Past (the slider dragged back, or "Replay from start"): the Work Order Replay itself, for this call, for people who may use Replay.
 */
export default function CallMapView({ alert, flagClass, onClose, backLabel = 'Watchlist' }) {
  const hints = useMemo(() => ({ sa_number: alert.sa_number, geo: alert.facility_name?.startsWith('000'), lat: alert.latitude, lon: alert.longitude }), [alert])
  const { data, error, stale, loading } = useCallMap(alert.sa_id, hints)
  const [nowS, setNowS] = useState(() => Date.now() / 1000)
  const [replay, setReplay] = useState(null)               // null = the live view; { at } = the Replay, opened at that epoch second (null = at its first step)
  const backRef = useRef(null)
  const [mapFull, setMapFull] = useState(false)          // the live map alone fills the screen
  const fullRef = useRef(false)
  fullRef.current = mapFull

  useEffect(() => {                                    // Esc leaves the full-screen map first, then closes; the page behind does not scroll; focus returns to the map button
    const prevFocus = document.activeElement
    const onKey = e => { if (e.key === 'Escape') { e.preventDefault(); if (fullRef.current) setMapFull(false); else onClose() } }
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', onKey)
    backRef.current?.focus()
    return () => { window.removeEventListener('keydown', onKey); document.body.style.overflow = overflow; prevFocus?.focus?.() }
  }, [onClose])
  useEffect(() => { const id = setInterval(() => setNowS(Date.now() / 1000), 15000); return () => clearInterval(id) }, [])
  useEffect(() => { if (data) setNowS(Date.now() / 1000) }, [data])

  const events = useMemo(() => buildEvents(data), [data])
  const created = data ? toS(data.sa.created_at) : nowS - 3600
  const start = Math.min(created, events[0]?.t ?? created)
  const end = Math.max(nowS, start + 60)
  const times = useMemo(() => events.map(e => e.t), [events])
  const engine = useReplayEngine({ start, end, events: times, initial: end, speed: DEFAULT_SPEED })
  const { t } = useEngineState(engine, 2)
  const wasLive = useRef(true)
  const prevEnd = useRef(end)
  useEffect(() => {                                    // the slider sits at "now" and follows it
    if (wasLive.current && end > prevEnd.current) engine.seek(end)
    prevEnd.current = end
  }, [end, engine])
  useEffect(() => engine.subscribe(tt => { wasLive.current = tt >= prevEnd.current - LIVE_SLACK_S }), [engine])

  const marks = useMemo(() => events.map(e => ({ t: e.t, label: `${clockET(e.t)} ET · ${e.title}`, colour: e.colour, Icon: iconFor(e), level: e.level })), [events])
  const onScene = useMemo(() => (data ? onSceneTs(data.steps || EMPTY) : null), [data])
  const pin = data ? pinState(data, nowS, onScene) : null
  const sa = data?.sa
  const canReplay = !!data?.can_read_texts                 // the same people as Replay itself (permission scheduler.replay)
  const live = !replay
  const board = useMemo(() => (data ? asGarageLive(data) : null), [data])
  useEffect(() => { if (canReplay && !wasLive.current && !replay) { engine.pause(); setReplay({ at: t }) } }, [canReplay, t, replay, engine])   // dragging the slider back opens the Replay there
  useEffect(() => { if (replay) setMapFull(false) }, [replay])   // the Replay has its own Expand
  const replayFromStart = () => { engine.pause(); setReplay({ at: null }) }
  const goLive = () => { engine.pause(); engine.seek(end); setReplay(null) }

  const chip = 'rounded-full px-2.5 py-0.5 text-xs font-semibold border'
  return createPortal(
    <div role="dialog" aria-modal="true" aria-label="Call map" className="fixed inset-0 z-[1200] bg-slate-950 text-slate-100 flex flex-col">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 border-b border-slate-800 bg-slate-900">
        <button ref={backRef} type="button" onClick={onClose} className="inline-flex items-center gap-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-white font-semibold px-4 py-2.5 text-sm min-h-[44px]">
          <ArrowLeft className="w-5 h-5" />Back to {backLabel}
        </button>
        <div className="min-w-0">
          <div className="text-lg font-bold text-white tabular-nums">WO {alert.wo_number || sa?.wo_number || '—'} <span className="text-slate-500">·</span> {alert.sa_number}</div>
          <div className="text-xs text-slate-400">{[alert.work_type, alert.priority_code && `Priority ${alert.priority_code}`, alert.city].filter(Boolean).join(' · ')}</div>
        </div>
        {alert.flag && <span className={`${chip} ${flagClass || 'bg-slate-700/50 text-slate-300 border-slate-600/50'}`}>{alert.flag}</span>}
        <div className="ml-auto flex items-center gap-3 text-xs">
          {stale && <span className="text-amber-300 flex items-center gap-1"><AlertTriangle className="w-3.5 h-3.5" />Could not refresh; showing the last data</span>}
          {live ? <span className="flex items-center gap-2 text-emerald-300 font-semibold"><span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse" />LIVE · updates every minute</span>
            : <button type="button" onClick={goLive} className="flex items-center gap-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold px-3 py-1.5"><Radio className="w-3.5 h-3.5" />Back to live</button>}
        </div>
      </header>

      {loading && !data && <div className="flex-1 flex items-center justify-center gap-2 text-slate-400"><Loader2 className="w-6 h-6 animate-spin text-sky-400" />Reading the call from Salesforce…</div>}
      {error && !data && <div className="flex-1 flex items-center justify-center gap-2 text-rose-300"><AlertTriangle className="w-5 h-5" />{error}</div>}

      {data && replay && (
        <div className="flex-1 min-h-0 overflow-y-auto p-4"><ReplayPanel q={alert.sa_id} startAt={replay.at} /></div>
      )}

      {data && !replay && (
        <>
          <QuickInfo data={data} pin={pin} nowS={nowS} />
          <div className="flex-1 min-h-0 flex flex-col lg:flex-row gap-3 p-4">
            <div className={mapFull ? 'fixed inset-0 z-[1300] bg-slate-950' : 'relative flex-1 min-h-[300px] rounded-xl overflow-hidden border border-slate-700/70'}>
              <GarageLiveMap data={board} canReplay={false} link={data.driver ? { driverId: data.driver.id, saId: sa.id } : null} />
              <div className="absolute top-3 left-14 right-3 z-[1000] flex flex-wrap items-start gap-2 pointer-events-none">
                {data.suggestion && (
                  <div className="pointer-events-auto rp-glass rounded-xl px-3 py-2 text-sm text-amber-100 flex items-center gap-2 max-w-[760px]" role="status">
                    <Lightbulb className="w-4 h-4 text-amber-300 shrink-0" />{data.suggestion.text}
                  </div>
                )}
                <a href={`${SF_BASE}/lightning/r/${alert.sa_id}/view`} target="_blank" rel="noopener noreferrer"
                  className="pointer-events-auto ml-auto rp-glass rounded-xl px-3 py-2 text-sm text-sky-200 hover:text-white flex items-center gap-1.5 min-h-[40px]"><ExternalLink className="w-4 h-4" />Open in Salesforce</a>
              </div>
              <div className="absolute bottom-3 left-3 z-[1000] flex flex-col gap-1.5 pointer-events-none max-w-[calc(100%-1.5rem)]">
                {sa.towbook && <div className="rp-glass rounded-lg px-3 py-1.5 text-xs text-amber-200">Towbook garage — no driver GPS</div>}
                {!sa.towbook && data.peer_counts && <div className="rp-glass rounded-lg px-3 py-1.5 text-xs text-slate-300 flex flex-wrap gap-x-3 gap-y-1">
                  <span>{data.peers.length} other qualified driver{data.peers.length === 1 ? '' : 's'} on shift · {data.peer_counts.not_qualified} not qualified · {data.peer_counts.no_gps} no recent position · dashed line = assigned driver</span>
                  {Object.values(DRIVER_STATUS).map(x => <span key={x.label} className="flex items-center gap-1"><i className="w-2 h-2 rounded-full" style={{ background: x.colour }} />{x.short}</span>)}</div>}
                {data.notes.map(n => <div key={n} className="rp-glass rounded-lg px-3 py-1.5 text-xs text-slate-300">{n}</div>)}
              </div>
              <button type="button" onClick={() => setMapFull(f => !f)} title={mapFull ? 'Exit full screen (Esc)' : 'Full screen map'} aria-label={mapFull ? 'Exit full screen' : 'Full screen map'}
                className="absolute bottom-3 right-3 z-[1000] rp-glass rounded-xl px-3 py-2 text-sm font-semibold text-white hover:brightness-125 flex items-center gap-1.5 min-h-[40px]">
                {mapFull ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}{mapFull ? 'Exit full screen' : 'Full screen'}
              </button>
            </div>
            <aside className="lg:w-[390px] shrink-0 min-h-0 flex flex-col rounded-xl border border-slate-700/70 bg-slate-900/50">
              <h2 className="px-3 py-2 text-sm font-semibold text-white border-b border-slate-800">What happened on this call</h2>
              <div className="flex-1 min-h-0 overflow-y-auto p-2">
                <StoryColumn events={events} t={nowS} saId={alert.sa_id} extras={data.extras} canReadTexts={canReplay} onSeek={s => { if (canReplay) { engine.pause(); engine.seek(s) } }} />
              </div>
            </aside>
          </div>
          {canReplay && (
            <div className="px-4 pb-3">
              <ReplayPlayer engine={engine} start={start} end={end} marks={marks}>
                <button type="button" onClick={replayFromStart} className="inline-flex items-center gap-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold px-3 py-1.5"><RotateCcw className="w-3.5 h-3.5" />Replay from start</button>
              </ReplayPlayer>
            </div>
          )}
        </>
      )}
    </div>,
    document.body,
  )
}
