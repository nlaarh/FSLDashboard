import { useEffect, useMemo, useRef, useState } from 'react'
import { Loader2, MapPinOff, MessageSquareOff } from 'lucide-react'
import { fetchReportCardReplay, fetchReportCardCallFlags } from '../../api'
import useReplayClock from '../replay/useReplayClock'
import { dayFrame, creationDensity, clockLabel } from '../replay/replayMath'
import ReplayPlayer from '../replay/ReplayPlayer'
import DayReplayMap from '../replay/DayReplayMap'
import DriverDayCard from '../replay/DriverDayCard'
import DayGantt from './DayGantt'
import ReplayPanel from '../woreplay/ReplayPanel'
import { verdictColour } from './reportCardStyles'

/** Garage Replay tab: the saved garage-day played back on a map, with the Gantt playhead on the same clock. */
export default function GarageReplay({ data, garage, date, selectedSa, onSelectSa, callStory }) {
  const [state, setState] = useState({ phase: 'loading' })
  useEffect(() => {
    let live = true
    setState({ phase: 'loading' })
    fetchReportCardReplay(garage, date)
      .then(({ status, data: d }) => live && setState(status === 200 ? { phase: 'ready', replay: d } : { phase: 'error', error: d?.detail || d?.error || `Replay unavailable (${status})` }))
      .catch(e => live && setState({ phase: 'error', error: e.message }))
    return () => { live = false }
  }, [garage, date])

  if (state.phase === 'loading') return <div className="glass rounded-xl p-8 flex justify-center"><Loader2 className="w-6 h-6 text-brand-400 animate-spin" /></div>
  if (state.phase === 'error') return <div className="glass rounded-xl p-8 text-center text-sm text-rose-400">{state.error}</div>
  return <ReplayBody key={`${garage}:${date}`} garage={garage} date={date} replay={state.replay} data={data} selectedSa={selectedSa} onSelectSa={onSelectSa} callStory={callStory} />
}

function ReplayBody({ garage, date, replay, data, selectedSa, onSelectSa, callStory }) {
  const [flags, setFlags] = useState({})   // RAP / out of territory / coverage / texts per call; the list works without them
  useEffect(() => {
    let live = true
    fetchReportCardCallFlags(garage, date).then(({ status, data: d }) => live && status === 200 && setFlags(d.flags || {})).catch(() => {})
    return () => { live = false }
  }, [garage, date])
  // The day's ACTIVE hours only: from 15 min before the first call to 15 min after the last one clears (not midnight to midnight).
  const win = useMemo(() => {
    const made = replay.calls.map(c => c.created).filter(Boolean), done = replay.calls.map(c => c.end).filter(Boolean)
    return [Math.max(replay.day_start, made.length ? Math.min(...made) - 900 : replay.day_start), Math.min(replay.day_end, done.length ? Math.max(...done) + 900 : replay.day_end)]
  }, [replay])
  const startAt = useMemo(() => {   // the clock opens when the picked service appointment was received, else at the first call
    const c = replay.calls.find(x => x.id === selectedSa)
    return c ? Math.max(win[0], c.created - 60) : win[0]
  }, [replay, selectedSa, win])
  const clock = useReplayClock(win[0], win[1], { initial: startAt, speed: 5 })
  const [driverId, setDriverId] = useState(null)
  const dayDrivers = useMemo(() => Object.fromEntries(data.drivers.map(d => [d.id, d])), [data])
  const sasById = useMemo(() => Object.fromEntries(data.sas.map(s => [s.id, s])), [data])
  const verdictById = useMemo(() => Object.fromEntries(data.sas.map(s => [s.id, s.verdict?.code])), [data])
  const frame = useMemo(() => dayFrame(replay, dayDrivers, sasById, clock.t), [replay, dayDrivers, sasById, clock.t])
  const density = useMemo(() => creationDensity(replay.calls, win[0], win[1]), [replay, win])
  const callIds = useMemo(() => Object.fromEntries(replay.calls.map(c => [c.id, c])), [replay])
  const selected = sasById[selectedSa] ? selectedSa : null
  const panelRef = useRef(null)
  useEffect(() => { if (selected) panelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }, [selected])
  const driver = driverId ? replay.drivers.find(d => d.id === driverId) : null
  useEffect(() => {
    const c = callIds[selected]
    if (c) clock.setT(Math.max(win[0], c.created - 60))
  }, [selected]) // eslint-disable-line react-hooks/exhaustive-deps
  const ORDER = { en_route: 0, on_scene: 1, assigned: 2, idle: 3, off: 4 }
  // only drivers and vehicles that are on the map or working a call right now (not the 20 who are off shift or have no truck out)
  const roster = frame.drivers.filter(d => d.pos || ['en_route', 'on_scene', 'assigned', 'idle'].includes(d.status.key)).sort((a, b) => (ORDER[a.status.key] ?? 9) - (ORDER[b.status.key] ?? 9) || a.name.localeCompare(b.name))
  const counts = roster.reduce((o, d) => ({ ...o, [d.status.key]: (o[d.status.key] || 0) + 1 }), {})

  const calls = useMemo(() => data.sas.filter(x => !x.is_drop_off).sort((a, b) => a.created.localeCompare(b.created)), [data])
  const names = useMemo(() => Object.fromEntries(data.drivers.map(d => [d.id, d.name.replace(/\s+\d{2,3}[A-Z]{0,2}$/, '')])), [data])
  return (
    <div className="flex gap-3 items-start">
    <CallList calls={calls} names={names} flags={flags} selected={selected} onSelect={onSelectSa} />
    <div className="space-y-3 flex-1 min-w-0">
      {selected && callStory && <div ref={panelRef}><ReplayPanel q={sasById[selected].number} /></div>}
      <ReplayPlayer clock={clock} start={win[0]} end={win[1]} density={density}>
        <span className="text-[11px] text-slate-400">{frame.open.length} open · {frame.late.length} past promise</span>
      </ReplayPlayer>
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 items-start">
        <div className="xl:col-span-2 glass rounded-xl overflow-hidden relative" style={{ height: 460 }}>
          <div className="absolute left-14 top-3 z-[1000] pointer-events-none rounded-xl bg-slate-900/90 text-white px-4 py-2 shadow-lg">
            <div className="text-2xl font-extrabold tabular-nums leading-none">{clockLabel(clock.t, true)}</div>
            <div className="text-[11px] text-slate-300 mt-1">
              {counts.en_route || 0} en route · {counts.on_scene || 0} on scene · {counts.idle || 0} idle · {frame.open.length} calls open{frame.late.length ? ` · ${frame.late.length} past promise` : ''}
            </div>
          </div>
          <DayReplayMap replay={replay} frame={frame} t={clock.t} verdictById={verdictById} selectedDriver={driverId}
            selectedSa={selected} onSelectDriver={setDriverId} onSelectSa={id => callIds[id] && onSelectSa(id)} />
        </div>
        <div className="space-y-2">
          {driver ? (
            <DriverDayCard driver={dayDrivers[driver.id]} replayDriver={driver} frameDriver={frame.drivers.find(d => d.id === driver.id)}
              sas={data.sas.filter(s => s.final_driver_id === driver.id)} sasById={sasById} t={clock.t} onSeek={clock.setT}
              onSelectSa={onSelectSa} onClose={() => setDriverId(null)} />
          ) : (
            <div className="glass rounded-xl overflow-hidden">
              <div className="px-3 py-2 border-b border-slate-700/60">
                <div className="text-xs font-semibold text-slate-200">What each driver is doing at {clockLabel(clock.t, true)}</div>
                <div className="text-[11px] text-slate-500">Click a driver for their whole day.</div>
              </div>
              <div className="max-h-[390px] overflow-y-auto">
                {roster.map(d => (
                  <button key={d.id} onClick={() => setDriverId(d.id)} className="w-full text-left px-3 py-1.5 border-b border-slate-800/80 hover:bg-slate-800/60 flex items-center gap-2">
                    <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: d.status.colour }} />
                    <span className="min-w-0">
                      <span className="block text-xs text-white truncate">{d.id.startsWith('tb:') ? d.name : d.name.replace(/\s+\d{2,3}[A-Z]{0,2}$/, '')}{d.pos && d.mode === 'estimated' ? ' (estimated)' : ''}</span>
                      <span className="block text-[11px] text-slate-400 truncate">{d.status.label}{d.status.call ? ` · ${d.status.call.number}` : ''}{d.held.length > 1 ? ` (+${d.held.length - 1} more)` : ''}</span>
                    </span>
                  </button>
                ))}
                {!roster.length && <div className="px-3 py-3 text-xs text-slate-500">No drivers or vehicles on the map at this moment.</div>}
              </div>
            </div>
          )}
        </div>
      </div>
      <DayGantt data={data} selectedSa={selected} onSelect={onSelectSa} clockMs={clock.t * 1000}
        onSeek={ms => clock.setT(ms / 1000)} onSelectDriver={setDriverId} selectedDriver={driverId} />
    </div>
    </div>
  )
}

const hhmm = iso => new Date(iso).toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit' })

const NONE = { rap: false, ooT: false, text: false, job: '', cover: '' }

/** The garage's calls for the day, earliest first, with RAP / out-of-territory / no-text icons and filters. Click one to replay it. */
function CallList({ calls, names, flags, selected, onSelect }) {
  const [f, setF] = useState(NONE)
  const jobs = useMemo(() => [...new Set(calls.map(c => c.work_type))].sort(), [calls])
  const covers = useMemo(() => [...new Set(Object.values(flags).map(x => x.coverage).filter(Boolean))].sort(), [flags])
  const shown = calls.filter(c => {
    const x = flags[c.id] || {}
    return (!f.job || c.work_type === f.job) && (!f.cover || x.coverage === f.cover) && (!f.rap || x.rap)
      && (!f.ooT || x.out_of_territory) && (!f.text || x.text?.state === 'missing')
  })
  const on = f.rap || f.ooT || f.text || f.job || f.cover
  const chip = (key, label, n) => (
    <button key={key} onClick={() => setF({ ...f, [key]: !f[key] })}
      className={`px-2 py-0.5 rounded-full text-[11px] border ${f[key] ? 'bg-brand-600/30 border-brand-500 text-white' : 'border-slate-700 text-slate-400 hover:text-white'}`}>{label} · {n}</button>
  )
  const all = Object.values(flags)
  const sel = (key, value, opts, all_) => (
    <select value={value} onChange={e => setF({ ...f, [key]: e.target.value })}
      className="bg-slate-900 border border-slate-700 rounded-md text-[11px] text-slate-300 px-1.5 py-0.5 max-w-[48%]">
      <option value="">{all_}</option>{opts.map(o => <option key={o} value={o}>{o}</option>)}
    </select>
  )
  return (
    <div className="glass rounded-xl w-72 shrink-0 overflow-hidden sticky top-20">
      <div className="px-3 py-2 text-xs font-semibold text-slate-300 border-b border-slate-700/60 flex items-center justify-between">
        <span>Work orders · {on ? `${shown.length} of ${calls.length}` : calls.length}</span>
        {on && <button onClick={() => setF(NONE)} className="text-[11px] font-normal text-brand-400 hover:text-brand-300">Clear</button>}
      </div>
      <div className="px-3 py-2 border-b border-slate-700/60 space-y-1.5">
        <div className="flex gap-1.5">{sel('job', f.job, jobs, 'All job types')}{covers.length > 0 && sel('cover', f.cover, covers, 'All members')}</div>
        {all.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {chip('rap', 'RAP', all.filter(x => x.rap).length)}
            {chip('ooT', 'Out of territory', all.filter(x => x.out_of_territory).length)}
            {chip('text', 'No text', all.filter(x => x.text?.state === 'missing').length)}
          </div>
        )}
      </div>
      <div className="max-h-[70vh] overflow-y-auto">
        {shown.map(c => {
          const x = flags[c.id]
          return (
            <button key={c.id} onClick={() => onSelect(c.id)}
              className={`w-full text-left px-3 py-2 border-b border-slate-800/80 flex items-start gap-2 transition-colors ${selected === c.id ? 'bg-brand-600/20' : 'hover:bg-slate-800/60'}`}>
              <span className="mt-1 w-2 h-2 rounded-full shrink-0" style={{ background: verdictColour(c.verdict?.code) }} />
              <span className="min-w-0 flex-1">
                <span className="block text-xs text-white font-medium">{c.number} · {c.work_type}</span>
                <span className="block text-[11px] text-slate-400 truncate">{hhmm(c.created)} · {names[c.final_driver_id] || (c.channel === 'towbook' ? 'Towbook garage' : 'no driver')}{x?.coverage ? ` · ${x.coverage}` : ''}</span>
                {x && x.opted_in != null && <span className={`block text-[11px] ${x.opted_in ? 'text-emerald-400' : 'text-slate-500'}`}>{x.opted_in ? 'Opted in to texts' : 'Not opted in to texts'}</span>}
              </span>
              {x && (
                <span className="flex items-center gap-1 shrink-0 mt-0.5">
                  {x.rap && <span title="RAP call" className="px-1 rounded bg-sky-500/20 text-sky-300 text-[10px] font-bold leading-4">RAP</span>}
                  {x.out_of_territory && <span title="Out of territory"><MapPinOff className="w-3.5 h-3.5 text-amber-400" /></span>}
                  {x.text?.state === 'missing' && <span title={x.text.tip}><MessageSquareOff className="w-3.5 h-3.5 text-rose-500" /></span>}
                  {x.text?.state === 'opted_out' && <span title={x.text.tip}><MessageSquareOff className="w-3.5 h-3.5 text-slate-500" /></span>}
                </span>
              )}
            </button>
          )
        })}
        {!shown.length && <div className="px-3 py-4 text-xs text-slate-500">No work orders match these filters.</div>}
      </div>
    </div>
  )
}
