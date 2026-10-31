import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Loader2, Crosshair, Route, ArrowLeft, List as ListIcon, Car, Warehouse, House, Coffee, Utensils, Fuel, Store, ShoppingCart, ShoppingBasket, Pill, Landmark, Mail, Beer, Wrench, CircleHelp, Moon } from 'lucide-react'
import { fetchDriverReplay } from '../../api'
import useReplayEngine, { useEngineState, prefersReducedMotion } from '../replay/useReplayEngine'
import ReplayPlayer, { SkipChip } from '../replay/ReplayPlayer'
import useExpand, { expandShell } from '../replay/useExpand'
import { ExpandButton } from '../replay/ExpandControls'
import { clockLabel } from '../replay/replayMath'
import { shortDriverName } from '../../utils/driverName'
import DriverReplayMap from './DriverReplayMap'
import { DRIVER_COLOURS, MAX_DRIVERS, BUCKETS, kindOf, fmtDur, bucketTotals, replayWindow, doingAt, daySegments, stopEvents, anyDriving, drivePace, DAY_WALL_S } from './driverModel'

const ICONS = { call: Car, garage: Warehouse, home: House, coffee: Coffee, food: Utensils, gas: Fuel, store: Store, bigstore: ShoppingCart, grocery: ShoppingBasket,
  pharmacy: Pill, bank: Landmark, post: Mail, bar: Beer, auto: Wrench, off: Moon, unknown: CircleHelp }
const BUCKET_COLOUR = { driving: null, calls: '#10b981', places: '#f97316', base: '#6366f1', unknown: '#94a3b8', no_signal: '#475569', off: '#334155' }
const SPEEDS = [0.5, 1, 2, 4]   // multipliers of drivePace: at 1x a whole day plays in about 3 minutes
const speedTitle = s => `${s}×: the whole day in about ${Math.round(DAY_WALL_S / s / 60 * 2) / 2} min (keys 1-4)`

// one request per driver-day, kept while the page is open (the day is saved, it does not change)
const loaded = new Map()
async function loadDrivers(garage, date, ids) {
  const key = id => `${garage}:${date}:${id}`
  const missing = ids.filter(id => !loaded.has(key(id)))
  if (missing.length) {
    const { status, data } = await fetchDriverReplay(garage, date, missing)
    if (status !== 200) throw new Error(data?.detail || data?.error || (data?.status === 'not_built' ? 'This day is not built yet.' : `Driver replay unavailable (${status})`))
    for (const d of data.drivers) loaded.set(key(d.id), d)
  }
  return ids.map(id => loaded.get(key(id))).filter(Boolean)
}

/** The picked drivers, kept in the URL (?drv=a,b) so a link opens the same replay. Up to MAX_DRIVERS, in pick order (= colour order). */
export function useDriverPicks() {
  const [params, setParams] = useSearchParams()
  const picked = useMemo(() => (params.get('drv') || '').split(',').filter(Boolean).slice(0, MAX_DRIVERS), [params])
  const setPicked = ids => setParams(p => { const n = new URLSearchParams(p); if (ids.length) n.set('drv', ids.join(',')); else n.delete('drv'); return n }, { replace: true })
  const toggle = id => setPicked(picked.includes(id) ? picked.filter(x => x !== id) : picked.length < MAX_DRIVERS ? [...picked, id] : picked)
  return { picked, toggle, pick: id => setPicked([id]), clear: () => setPicked([]), colourOf: id => DRIVER_COLOURS[picked.indexOf(id)] }
}

/** The right side of the Garage replay when the list shows Drivers: the picked drivers' day on the map, or a prompt.
 *  replay = the garage-day replay answer (territory, day bounds). */
export default function DriverReplayPane({ garage, date, replay, picked }) {
  const [days, setDays] = useState({ phase: 'idle', drivers: [] })
  useEffect(() => {
    if (!picked.length) { setDays({ phase: 'idle', drivers: [] }); return undefined }
    let live = true
    setDays(s => ({ ...s, phase: 'loading' }))
    loadDrivers(garage, date, picked)
      .then(ds => live && setDays({ phase: 'ready', drivers: ds }))
      .catch(e => live && setDays({ phase: 'error', error: e.message, drivers: [] }))
    return () => { live = false }
  }, [garage, date, picked.join(',')]) // eslint-disable-line react-hooks/exhaustive-deps

  // the same array while nothing changes, so the map does not rebuild its layers on every render
  const ready = useMemo(() => (days.phase === 'ready'
    ? days.drivers.filter(d => d.mode === 'gps').map(d => {
      const v = replay.drivers.find(x => x.id === d.id) || {}   // the truck they drove and its capabilities pick the AAA vehicle drawing
      return { ...d, colour: DRIVER_COLOURS[picked.indexOf(d.id)], truck: v.truck, skills: v.skills }
    }) : []), [days, picked, replay])

  if (!picked.length) return <div className="glass rounded-xl p-8 text-center text-sm text-slate-300">Pick a driver from the list to watch their day: where they drove, where they stopped, and for how long.</div>
  if (days.phase === 'error') return <div className="glass rounded-xl p-8 text-center text-sm text-rose-400">{days.error}</div>
  if (!ready.length) return <div className="glass rounded-xl p-8 flex justify-center"><Loader2 className="w-6 h-6 text-brand-400 animate-spin" /></div>
  return <Player key={`${garage}:${date}:${ready.map(d => d.id).join(',')}`} territory={replay.territory}
    dayStart={replay.day_start} dayEnd={replay.day_end} drivers={ready} />
}

function Player({ territory, dayStart, dayEnd, drivers }) {
  const win = useMemo(() => replayWindow(drivers, dayStart, dayEnd), [drivers, dayStart, dayEnd])
  const events = useMemo(() => stopEvents(drivers).filter(x => x >= win.start && x <= win.end), [drivers, win])
  const busy = useMemo(() => anyDriving(drivers), [drivers])
  const pace = useMemo(() => drivePace(drivers, win.start, win.end), [drivers, win])   // whole day ~3 min at 1x, each stop 2-5 s
  const engine = useReplayEngine({ start: win.start, end: win.end, events, initial: win.initial, speed: 1, speeds: SPEEDS, busy, pace })
  const { t } = useEngineState(engine, 4)
  useEffect(() => {   // starts by itself when a driver is picked, like the work-order replay (not if the user already moved the playhead)
    if (prefersReducedMotion()) return undefined
    const h = setTimeout(() => { if (engine.ref.current.t === win.initial) engine.play() }, 400)
    return () => clearTimeout(h)
  }, [engine]) // eslint-disable-line react-hooks/exhaustive-deps
  const [tab, setTab] = useState(drivers[0].id)
  const [view, setView] = useState('follow')   // follow (chase camera) | day (whole route) | free (the user moved the map)
  const [panel, setPanel] = useState(false)    // the day list beside the map (closed: the map gets the whole screen)
  const shown = drivers.find(d => d.id === tab) || drivers[0]
  const marks = useMemo(() => drivers.flatMap(d => d.stops.filter(s => !['garage', 'home', 'off'].includes(s.kind)).map(s => ({
    t: s.t0, colour: kindOf(s.kind).colour, Icon: ICONS[s.kind] || CircleHelp,
    label: `${shortDriverName(d.name)}: ${s.label}, ${clockLabel(s.t0)} – ${clockLabel(s.t1)} (${fmtDur(s.t1 - s.t0)})`,
  }))), [drivers])
  const seekStop = s => { engine.pause(); engine.seek(Math.max(win.start, s.t0 - 90)); engine.play() }

  const ex = useExpand(), big = ex.expanded
  useEffect(() => { ex.open() }, []) // eslint-disable-line react-hooks/exhaustive-deps -- a picked driver opens big (Back returns to the list)
  return (
    <div ref={ex.ref} className={big
      ? 'fixed inset-0 !m-0 z-[3000] bg-slate-950 flex'
      : expandShell(false, 'grid grid-cols-1 xl:grid-cols-3 gap-3 items-start')}>
      {!big && (
        <ReplayPlayer engine={engine} start={win.start} end={win.end} marks={marks} speeds={SPEEDS} speedTitle={speedTitle} className="xl:col-span-3">
          <span className="text-[11px] text-slate-400">Whole day ≈ 3 min at 1× · ◀ ▶ step stop by stop · drag the slider to go back</span>
        </ReplayPlayer>
      )}

      <div className={`overflow-hidden relative ${big ? 'flex-1 min-w-0 h-full' : 'glass rounded-xl xl:col-span-2'}`} style={big ? undefined : { height: 520 }}>
        <div className="absolute left-14 top-3 z-[1000] pointer-events-none rounded-xl bg-slate-900/90 text-white px-4 py-2 shadow-lg max-w-[60%]">
          <div className={`${big ? 'text-4xl' : 'text-2xl'} font-extrabold tabular-nums leading-none`}>{clockLabel(t, true)}</div>
          <div className="mt-1.5 space-y-0.5">
            {drivers.map(d => <NowLine key={d.id} d={d} t={t} big={big} />)}
          </div>
        </div>
        <DriverReplayMap territory={territory} drivers={drivers} engine={engine} view={view} onViewChange={setView}
          onPickStop={(id, s) => { setTab(id); seekStop(s) }} />
        <SkipChip engine={engine} className={`absolute left-1/2 -translate-x-1/2 z-[1000] ${big ? 'bottom-16' : 'bottom-3'}`} />
        {big && <ReplayPlayer engine={engine} start={win.start} end={win.end} marks={marks} speeds={SPEEDS} speedTitle={speedTitle} compact
          className="absolute left-2 right-2 bottom-2 z-[1000]" />}
        <div className="absolute right-3 top-3 z-[1000] flex gap-2">
          {big && (
            <button type="button" onClick={ex.close} title="Back to the list (Esc)"
              className="rp-glass rounded-lg px-2.5 py-1.5 text-xs font-semibold text-white flex items-center gap-1.5 hover:brightness-125"><ArrowLeft className="w-3.5 h-3.5" />Back</button>
          )}
          <div className="rp-glass rounded-lg p-0.5 flex" role="group" aria-label="Map view">
            <button type="button" onClick={() => setView('follow')} aria-pressed={view === 'follow'} title="Follow the truck, zoomed in to the streets"
              className={`px-2.5 py-1 rounded-md text-xs font-semibold flex items-center gap-1.5 ${view === 'follow' ? 'bg-amber-400 text-slate-950' : 'text-white hover:bg-slate-700/60'}`}>
              <Crosshair className="w-3.5 h-3.5" />Follow truck
            </button>
            <button type="button" onClick={() => setView('day')} aria-pressed={view === 'day'} title="Zoom out to the whole day's route"
              className={`px-2.5 py-1 rounded-md text-xs font-semibold flex items-center gap-1.5 ${view === 'day' ? 'bg-amber-400 text-slate-950' : 'text-white hover:bg-slate-700/60'}`}>
              <Route className="w-3.5 h-3.5" />Whole day
            </button>
          </div>
          {big && (
            <button type="button" onClick={() => setPanel(p => !p)} aria-pressed={panel} title="Show or hide the list of stops beside the map"
              className={`rp-glass rounded-lg px-2.5 py-1.5 text-xs font-semibold flex items-center gap-1.5 ${panel ? 'text-amber-300' : 'text-white'} hover:brightness-125`}>
              <ListIcon className="w-3.5 h-3.5" />{panel ? 'Hide stops' : `Stops · ${drivers[0].stops.length}`}
            </button>
          )}
          {!big && <ExpandButton expand={ex} />}
        </div>
      </div>

      <div className={big ? (panel ? 'w-[340px] shrink-0 h-full overflow-y-auto p-2 space-y-2' : 'hidden') : 'space-y-2'}>
        {drivers.length > 1 && (
          <div role="tablist" className="flex gap-1 border-b border-slate-700/60 overflow-x-auto">
            {drivers.map(d => (
              <button key={d.id} role="tab" aria-selected={shown.id === d.id} onClick={() => setTab(d.id)}
                className={`px-2.5 py-1.5 text-xs font-medium whitespace-nowrap border-b-2 -mb-px flex items-center gap-1.5 ${shown.id === d.id ? 'text-white' : 'border-transparent text-slate-400 hover:text-slate-200'}`}
                style={shown.id === d.id ? { borderColor: d.colour } : undefined}>
                <span className="w-2 h-2 rounded-full" style={{ background: d.colour }} />{shortDriverName(d.name)}
                <span className="px-1.5 rounded-full bg-slate-700/70 text-[10px] text-slate-200">{d.stops.length}</span>
              </button>
            ))}
          </div>
        )}
        <DayCard d={shown} t={t} big={big} win={win} onSeek={engine.seek} onStop={seekStop} />
      </div>
    </div>
  )
}

function NowLine({ d, t, big }) {
  const { state, stop } = doingAt(d, t)
  const text = state === 'stopped' ? `${stop.label} · since ${clockLabel(stop.t0)} · ${fmtDur(t - stop.t0)}`
    : state === 'driving' ? 'Driving' : state === 'no_signal' ? 'No GPS signal' : state === 'before' ? 'Not on the road yet' : 'Done for the day'
  return (
    <div className={`${big ? 'text-sm' : 'text-[11px]'} flex items-center gap-1.5 truncate`}>
      <span className="w-2 h-2 rounded-full shrink-0" style={{ background: d.colour }} />
      <span className="text-slate-300 truncate"><b className="text-white font-semibold">{shortDriverName(d.name)}</b> · {text}</span>
    </div>
  )
}

/** One driver's day: where the time went (buckets), the day as a coloured strip with the clock needle, and every stop in order. */
function DayCard({ d, t, big, win, onSeek, onStop }) {
  const totals = bucketTotals(d.summary)
  const all = Object.values(totals).reduce((a, b) => a + b, 0) || 1
  const seg = useMemo(() => daySegments(d), [d])
  const span = Math.max(win.end - win.start, 1)
  const pct = x => `${Math.min(100, Math.max(0, ((x - win.start) / span) * 100))}%`
  const segColour = k => (k === 'driving' ? d.colour : k === 'no_signal' ? '#334155' : kindOf(k).colour)
  const current = doingAt(d, t).stop
  return (
    <div className="glass rounded-xl overflow-hidden">
      <div className="px-3 py-2.5 border-b border-slate-700/60">
        <div className="flex items-center gap-2">
          <span className="w-3 h-3 rounded-full" style={{ background: d.colour, boxShadow: `0 0 8px ${d.colour}` }} />
          <span className={`${big ? 'text-base' : 'text-sm'} font-semibold text-white truncate`}>{shortDriverName(d.name)}</span>
          <span className="ml-auto text-[11px] text-slate-400">{d.calls_done ?? 0} call{d.calls_done === 1 ? '' : 's'} for this garage · {d.summary.miles} mi</span>
        </div>
        <div className="grid grid-cols-1 2xl:grid-cols-2 gap-x-3 gap-y-1 mt-2">
          {BUCKETS.filter(b => totals[b.id] > 0).map(b => (
            <div key={b.id} className="text-[11px] flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-sm shrink-0" style={{ background: BUCKET_COLOUR[b.id] || d.colour }} />
              <span className="text-slate-400 truncate">{b.label}</span>
              <span className="ml-auto text-white font-semibold tabular-nums">{fmtDur(totals[b.id])}</span>
              <span className="text-slate-500 tabular-nums w-8 text-right">{Math.round((totals[b.id] / all) * 100)}%</span>
            </div>
          ))}
        </div>
        <div className="relative h-4 mt-2.5 rounded bg-slate-800 cursor-pointer overflow-hidden" title="Click to jump there"
          onClick={e => { const r = e.currentTarget.getBoundingClientRect(); onSeek(win.start + ((e.clientX - r.left) / r.width) * span) }}>
          {seg.map((s, i) => (
            <div key={i} className="absolute top-0 bottom-0" title={`${s.kind === 'driving' ? 'Driving' : s.kind === 'no_signal' ? 'No GPS signal' : kindOf(s.kind).name} · ${clockLabel(s.t0)} – ${clockLabel(s.t1)}`}
              style={{ left: pct(s.t0), width: `calc(${pct(s.t1)} - ${pct(s.t0)})`, background: segColour(s.kind), opacity: s.kind === 'driving' ? 0.55 : 0.95 }} />
          ))}
          <div className="absolute top-0 bottom-0 w-0.5 bg-white shadow" style={{ left: pct(t) }} />
        </div>
      </div>
      <div className={big ? '' : 'max-h-[300px] overflow-y-auto'}>
        {d.stops.map((s, i) => {
          const Icon = ICONS[s.kind] || CircleHelp, k = kindOf(s.kind), on = current === s, past = t >= s.t1
          return (
            <button key={i} type="button" onClick={() => onStop(s)}
              className={`w-full text-left px-3 py-1.5 border-b border-slate-800/80 flex items-center gap-2.5 transition-colors ${on ? 'bg-slate-700/60' : 'hover:bg-slate-800/60'} ${!on && !past ? 'opacity-60' : ''}`}>
              <span className="w-7 h-7 rounded-full flex items-center justify-center shrink-0 shadow" style={{ background: `radial-gradient(circle at 35% 30%, #ffffff55, ${k.colour} 55%)`, boxShadow: on ? `0 0 0 2px ${d.colour}` : undefined }}>
                <Icon className="w-3.5 h-3.5 text-white" strokeWidth={2.4} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-xs text-white truncate">{s.label}</span>
                <span className="block text-[11px] text-slate-400 truncate">{clockLabel(s.t0)} – {clockLabel(s.t1)}{s.place_kind && s.place_kind !== s.label ? ` · ${s.place_kind}` : ''}</span>
              </span>
              <span className={`text-xs font-semibold tabular-nums shrink-0 ${on ? 'text-amber-300' : 'text-slate-200'}`}>{on ? fmtDur(t - s.t0) : fmtDur(s.t1 - s.t0)}</span>
            </button>
          )
        })}
        {!d.stops.length && <div className="px-3 py-3 text-xs text-slate-500">No stops of 5 minutes or more.</div>}
      </div>
      <div className="px-3 py-2 text-[10px] text-slate-500 border-t border-slate-800/80">
        A stop is 5 minutes or more within about 150 m (2 minutes at the driver's own call). Only this garage's calls are known here:
        work for another garage shows as an unlisted stop. Places come from OpenStreetMap (New York); "Near" = the truck stood a little
        away from the place. The line between GPS pings is straight.
      </div>
    </div>
  )
}
