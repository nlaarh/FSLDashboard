import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ArrowLeft, Loader2, AlertTriangle, ExternalLink, Lightbulb, RotateCcw, Radio, Clock } from 'lucide-react'
import useReplayEngine, { useEngineState } from '../replay/useReplayEngine'
import ReplayPlayer from '../replay/ReplayPlayer'
import { onSceneTs } from '../woreplay/woReplayModel'
import useCallMap from './useCallMap'
import QuickInfo from './QuickInfo'
import CallMapCanvas from './CallMapCanvas'
import StoryColumn, { iconFor } from './StoryColumn'
import { buildEvents, pinState, toS } from './callMapModel'

const SF_BASE = 'https://aaawcny.lightning.force.com'
const LIVE_SLACK_S = 90                     // the slider counts as "at now" within this many seconds of it
const EMPTY = []
const clockET = s => new Date(s * 1000).toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit' })

/**
 * The Watchlist call map: a full-window view of one open call (not a split screen). Back button or Esc closes it.
 * alert = the Watchlist row; flagClass = the row's flag chip colours. The data refreshes every 60 s while this is open and the tab is visible.
 */
export default function CallMapView({ alert, flagClass, onClose }) {
  const hints = useMemo(() => ({ sa_number: alert.sa_number, geo: alert.facility_name?.startsWith('000'), lat: alert.latitude, lon: alert.longitude }), [alert])
  const { data, error, stale, loading } = useCallMap(alert.sa_id, hints)
  const [nowS, setNowS] = useState(() => Date.now() / 1000)
  const backRef = useRef(null)

  useEffect(() => {                                    // Esc closes; the page behind does not scroll; focus returns to the map button
    const prevFocus = document.activeElement
    const onKey = e => { if (e.key === 'Escape') { e.preventDefault(); onClose() } }
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
  const engine = useReplayEngine({ start, end, events: times, initial: end, speed: 60 })
  const { t } = useEngineState(engine, 2)
  const live = t >= end - LIVE_SLACK_S
  const wasLive = useRef(true)
  const prevEnd = useRef(end)
  useEffect(() => {                                    // the slider sits at "now" and follows it until someone drags back
    if (wasLive.current && end > prevEnd.current) engine.seek(end)
    prevEnd.current = end
  }, [end, engine])
  useEffect(() => engine.subscribe(tt => { wasLive.current = tt >= prevEnd.current - LIVE_SLACK_S }), [engine])

  const marks = useMemo(() => events.map(e => ({ t: e.t, label: `${clockET(e.t)} ET · ${e.title}`, colour: e.colour, Icon: iconFor(e), level: e.level })), [events])
  const onScene = useMemo(() => (data ? onSceneTs(data.steps || EMPTY) : null), [data])
  const pin = data ? pinState(data, live ? nowS : t, onScene) : null
  const sa = data?.sa
  const replayFromStart = () => { engine.seek(start); engine.setSpeed(60); engine.play() }
  const goLive = () => { engine.pause(); engine.seek(end) }

  const chip = 'rounded-full px-2.5 py-0.5 text-xs font-semibold border'
  return createPortal(
    <div role="dialog" aria-modal="true" aria-label="Call map" className="fixed inset-0 z-[1200] bg-slate-950 text-slate-100 flex flex-col">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 border-b border-slate-800 bg-slate-900">
        <button ref={backRef} type="button" onClick={onClose} className="inline-flex items-center gap-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-white font-semibold px-4 py-2.5 text-sm min-h-[44px]">
          <ArrowLeft className="w-5 h-5" />Back to Watchlist
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

      {data && (
        <>
          <QuickInfo data={data} pin={pin} nowS={live ? nowS : t} />
          <div className="flex-1 min-h-0 flex flex-col lg:flex-row gap-3 p-4">
            <div className="relative flex-1 min-h-[300px] rounded-xl overflow-hidden border border-slate-700/70">
              <CallMapCanvas data={data} t={t} isLive={live} onScene={onScene} />
              <div className="absolute top-3 left-14 right-3 z-[1000] flex flex-wrap items-start gap-2 pointer-events-none">
                {data.suggestion && live && (
                  <div className="pointer-events-auto rp-glass rounded-xl px-3 py-2 text-sm text-amber-100 flex items-center gap-2 max-w-[760px]" role="status">
                    <Lightbulb className="w-4 h-4 text-amber-300 shrink-0" />{data.suggestion.text}
                  </div>
                )}
                <a href={`${SF_BASE}/lightning/r/${alert.sa_id}/view`} target="_blank" rel="noopener noreferrer"
                  className="pointer-events-auto ml-auto rp-glass rounded-xl px-3 py-2 text-sm text-sky-200 hover:text-white flex items-center gap-1.5 min-h-[40px]"><ExternalLink className="w-4 h-4" />Open in Salesforce</a>
              </div>
              <div className="absolute bottom-3 left-3 z-[1000] flex flex-col gap-1.5 pointer-events-none">
                {sa.towbook && <div className="rp-glass rounded-lg px-3 py-1.5 text-xs text-amber-200">Towbook garage — no driver GPS</div>}
                {!live && <div className="rp-glass rounded-lg px-3 py-1.5 text-xs text-slate-200 flex items-center gap-1.5"><Clock className="w-3.5 h-3.5" />Showing {clockET(t)} ET. Driver positions are only known live, so trucks are hidden.</div>}
                {live && !sa.towbook && data.peer_counts && <div className="rp-glass rounded-lg px-3 py-1.5 text-xs text-slate-300">
                  {data.peers.length} other qualified driver{data.peers.length === 1 ? '' : 's'} on shift shown · {data.peer_counts.not_qualified} not qualified · {data.peer_counts.no_gps} without a recent position. Miles are straight-line. Badge = jobs ahead.</div>}
                {data.notes.map(n => <div key={n} className="rp-glass rounded-lg px-3 py-1.5 text-xs text-slate-300">{n}</div>)}
              </div>
            </div>
            <aside className="lg:w-[390px] shrink-0 min-h-0 flex flex-col rounded-xl border border-slate-700/70 bg-slate-900/50">
              <h2 className="px-3 py-2 text-sm font-semibold text-white border-b border-slate-800">What happened on this call</h2>
              <div className="flex-1 min-h-0 overflow-y-auto p-2">
                <StoryColumn events={events} t={t} saId={alert.sa_id} extras={data.extras} canReadTexts={data.can_read_texts} onSeek={s => { engine.pause(); engine.seek(s) }} />
              </div>
            </aside>
          </div>
          <div className="px-4 pb-3">
            <ReplayPlayer engine={engine} start={start} end={end} marks={marks}>
              <button type="button" onClick={replayFromStart} className="inline-flex items-center gap-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold px-3 py-1.5"><RotateCcw className="w-3.5 h-3.5" />Replay from start</button>
              {!live && <button type="button" onClick={goLive} className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-700 hover:bg-emerald-600 text-white text-xs font-semibold px-3 py-1.5"><Radio className="w-3.5 h-3.5" />Go to now</button>}
            </ReplayPlayer>
          </div>
        </>
      )}
    </div>,
    document.body,
  )
}
