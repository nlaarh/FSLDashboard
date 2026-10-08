import { useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import { ListOrdered, ChevronLeft, ChevronRight, Maximize2, Minimize2, Sun, Moon, Crosshair, Globe2, Hand, PauseOctagon, PhoneCall, PhoneIncoming, MessageSquareText, MessageCircleReply } from 'lucide-react'
import useLeafletMap, { setMapTheme } from '../replay/useLeafletMap'
import useReplayEngine, { useEngineIndex, useEngineState, prefersReducedMotion } from '../replay/useReplayEngine'
import ReplayPlayer, { SkipChip } from '../replay/ReplayPlayer'
import { buildPath } from '../replay/roadPath'
import { indexAt } from '../replay/engineMath'
import { truckKindFor } from '../replay/gameIcons'
import { createStageLayers } from './stageLayers'
import { FlowPulse, pulsePath, pickDock } from './flowPulse'
import StageHud from './StageHud'
import FlowDrawer from './FlowDrawer'
import EventToasts, { KIND_ICON } from './EventToasts'
import { StepCard, StepCaption } from './StepCard'
import { KINDS, HUD, isSlot, slotX, stepTimes, hudState, driverPhase, onSceneTs, promiseTs, miles, towbookTrack } from './woReplayModel'

const MARK_ICON = { phone: PhoneCall, callback: PhoneIncoming, text_out: MessageSquareText, text_in: MessageCircleReply }
const MARK_COLOUR = { phone: '#38bdf8', callback: '#f43f5e', text_out: '#ec4899', text_in: '#f59e0b' }
const PAD = { tl: L.point(110, 172), br: L.point(110, 112) }   // the visible map sits between the command bar and the caption
const toS = v => (typeof v === 'number' ? v : Date.parse(v) / 1000)
const Chip = ({ on, children }) => on && <span className="rp-shimmer rounded-full px-3 py-1 text-[11px] text-slate-200">{children}</span>
const store = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v) } catch { /* private window */ } return null }

/**
 * The Work Order Replay stage: a game-style live operations map. The replay engine (60 fps, no React per frame) drives the layers in
 * stageLayers.js; React only re-renders on a new step, a pause or a click. Everything is clickable at once: the story shows first,
 * trucks fade in when the GPS arrives (locations: undefined = still loading, null = unavailable), contact marks when B's extras arrive.
 * Optional props: marks [{ id, ts, type, title }], onMark(mark), driverJobs [{ id, lat, lon, ahead }], extrasLoading, drawerTop (node).
 */
export default function WoReplayStage({ steps, header, locations, jump, marks: rawMarks, onMark, driverJobs, extrasLoading, drawerTop }) {
  const where = header?.where
  const loc = useMemo(() => locations || (where ? { wo: where.member, garage: where.garage, drivers: [], notes: [] } : null), [locations, where])
  const times = useMemo(() => stepTimes(steps), [steps])
  const t0 = times[0] ?? 0
  const marks = useMemo(() => (rawMarks || []).map(m => ({ ...m, ts: toS(m.ts) })).filter(m => Number.isFinite(m.ts)).sort((a, b) => a.ts - b.ts), [rawMarks])
  const wait = useMemo(() => ({ created: t0, promise: promiseTs(steps), onScene: onSceneTs(steps) }), [steps, t0])
  const actors = useMemo(() => { let cur = null; return steps.map((s, k) => { if (s.names?.driver) cur = s.names.driver; return { name: cur, phase: driverPhase(steps, k) } }) }, [steps])
  const actor = useMemo(() => t => actors[indexAt(times, t)] || { name: null, phase: 'assigned' }, [actors, times])

  const trucks = useMemo(() => {
    if (!loc) return []
    const out = (loc.drivers || []).filter(d => d.track?.length).map(d => ({
      key: d.name, name: d.name, garage: header?.garage, est: false, path: buildPath(d.track, d.road),
      kind: truckKindFor({ truck: d.truck, skills: d.skills, service: header?.service }),
    }))
    const tb = towbookTrack(steps, loc.garage, loc.wo, loc.roads?.garage_to_member)
    if (tb.length) out.push({ key: 'tb', name: `${loc.towbook?.driver || 'Towbook Driver'} 1`, garage: header?.garage, est: true, path: buildPath(tb), kind: truckKindFor({ truck: loc.towbook?.truck, service: header?.service }) })
    return out
  }, [loc, steps, header])

  const end = Math.max(times[times.length - 1] ?? t0, t0) + 180
  const busy = useMemo(() => t => trucks.some(k => { const p = k.path.at(t); return p && p.heading != null && !p.stale }), [trucks])
  const eventTimes = useMemo(() => [...times, ...marks.map(m => m.ts)].sort((a, b) => a - b), [times, marks])
  const [hold, setHold] = useState(false)
  const stops = useMemo(() => (hold ? steps.map((s, k) => (s.flag ? times[k] : null)).filter(x => x != null) : []), [hold, steps, times])
  const engine = useReplayEngine({ start: t0 - 60, end, events: eventTimes, initial: t0 - 60, speed: 60, busy, stops })
  const { t: tNow } = useEngineState(engine, 4)
  const idx = useEngineIndex(engine, times)
  const hud = useMemo(() => hudState(steps, idx, idx >= 0), [steps, idx])
  const step = idx >= 0 ? steps[idx] : null

  const [ref, map] = useLeafletMap([42.9, -78.8])
  const [light, setLight] = useState(() => store('woReplayLight') === '1')
  useEffect(() => setMapTheme(ref.current, light), [light, map]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const z = map && ref.current.querySelector('.leaflet-top.leaflet-left'); if (z) z.style.marginTop = `${HUD.h + 22}px` }, [map]) // eslint-disable-line react-hooks/exhaustive-deps
  const [size, setSize] = useState({ w: 1100, h: 640 })
  const [open, setOpen] = useState(() => store('woReplayFlowOpen') === '1')
  const [mode, setMode] = useState('follow')            // follow | all | free
  const modeRef = useRef(mode); modeRef.current = mode
  const flying = useRef(0)
  const fsRef = useRef(null)
  const [isFs, setIsFs] = useState(false)
  useEffect(() => {
    const on = () => setIsFs(document.fullscreenElement === fsRef.current)
    document.addEventListener('fullscreenchange', on)
    return () => document.removeEventListener('fullscreenchange', on)
  }, [])
  useEffect(() => {   // the map re-measures whenever its box changes size (window, full screen, flow column)
    if (!map || typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver(() => { map.invalidateSize({ animate: false }); setSize({ w: ref.current.clientWidth, h: ref.current.clientHeight }) })
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [map]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {   // the user's own drag, wheel or zoom button takes the camera away until it is switched back
    const el = ref.current
    if (!map || !el) return undefined
    const free = () => setMode('free')
    const down = e => { if (e.target.closest?.('.leaflet-control-zoom')) free() }
    map.on('dragstart', free); el.addEventListener('pointerdown', down); el.addEventListener('wheel', free, { passive: true }); el.addEventListener('dblclick', free)
    return () => { map.off('dragstart', free); el.removeEventListener('pointerdown', down); el.removeEventListener('wheel', free); el.removeEventListener('dblclick', free) }
  }, [map]) // eslint-disable-line react-hooks/exhaustive-deps

  // First framing: the member and the garage, once the map and the coordinates are known.
  const fit = (animate = false) => {
    const pts = [loc?.wo, loc?.garage && loc.wo && miles(loc.garage, loc.wo) < 30 ? loc.garage : null].filter(Boolean).map(q => [q.lat, q.lon])
    if (pts.length > 1) map.fitBounds(L.latLngBounds(pts), { paddingTopLeft: PAD.tl, paddingBottomRight: PAD.br, maxZoom: 15, animate })
    else if (pts.length) map.setView(pts[0], 13.5, { animate })
  }
  useEffect(() => { if (map && loc) fit() }, [map, loc?.wo?.lat, loc?.wo?.lon, loc?.garage?.lat]) // eslint-disable-line react-hooks/exhaustive-deps

  // Layers: built once per data change, then moved by the engine every frame.
  const jobs = driverJobs
  const onMarkRef = useRef(onMark); onMarkRef.current = onMark
  useEffect(() => {
    if (!map) return undefined
    const layers = createStageLayers(map, { loc, header, trucks, actor, wait, marks, onMark: m => onMarkRef.current?.(m), jobs })
    let gliding = false
    const follow = r => {   // the truck leaving the middle 60% of the view makes the camera glide after it until it is centred again
      if (modeRef.current !== 'follow' || !r.pos || flying.current > Date.now()) return
      const playing = engine.ref.current.playing
      const q = map.latLngToContainerPoint([r.pos.lat, r.pos.lon]), sz = map.getSize()
      const cx = (PAD.tl.x + sz.x - PAD.br.x) / 2, cy = (PAD.tl.y + sz.y - PAD.br.y) / 2, hw = (sz.x - PAD.tl.x - PAD.br.x) * 0.3, hh = (sz.y - PAD.tl.y - PAD.br.y) * 0.3
      const outside = Math.abs(q.x - cx) > hw || Math.abs(q.y - cy) > hh
      if (!playing) { if (outside) map.panTo([r.pos.lat, r.pos.lon], { animate: true }); return }
      if (outside) gliding = true
      if (!gliding) return
      gliding = Math.abs(q.x - cx) > hw * 0.3 || Math.abs(q.y - cy) > hh * 0.3
      map.panBy([(q.x - cx) * 0.12, (q.y - cy) * 0.12], { animate: false })
    }
    const run = t => follow(layers.frame(t, engine.ref.current.playing))
    run(engine.ref.current.t)
    const off = engine.subscribe(run)
    return () => { off(); layers.destroy() }
  }, [map, loc, header, trucks, actor, wait, marks, jobs, engine])

  // Once per new step (wall time): the message flies, the card moves to the quietest corner, and the camera re-frames.
  const [fx, setFx] = useState(null)
  const dockId = useRef('tr')
  useEffect(() => {
    if (!map || idx < 0) { setFx(null); return }
    const s = steps[idx], t = times[idx], act = actor(t)
    const trk = trucks.find(k => k.est || k.name === act.name)
    const tp = trk?.path.at(t)
    const toPx = q => { const c = map.latLngToContainerPoint([q.lat, q.lon]); return { x: c.x, y: c.y } }
    const pt = id => (isSlot(id) ? { x: slotX(id, size.w), y: HUD.y }
      : id === 'member' ? (loc?.wo ? toPx(loc.wo) : null) : id === 'garage' ? (loc?.garage ? toPx(loc.garage) : null)
      : id === 'driver' ? (tp ? toPx(tp) : loc?.garage ? toPx(loc.garage) : null) : null)
    const path = pulsePath(s, pt), kind = KINDS[s.kind] || KINDS.system
    const cardW = s.why || s.explain ? 310 : 270, cardH = Math.min(420, 150 + (s.why ? 120 : 0) + (s.explain ? 190 : 0))
    const dock = pickDock(size.w, size.h, cardW, cardH, [pt('member'), pt('garage'), pt('driver'), path?.[path.length - 1]].filter(Boolean), dockId.current)
    dockId.current = dock.id
    setFx({ key: idx, path, colour: kind.colour, dash: kind.dash, dock, cardW })
    if (!loc?.wo || modeRef.current === 'free') return
    const pts = [[loc.wo.lat, loc.wo.lon]]
    for (const k of modeRef.current === 'all' ? trucks : trk ? [trk] : []) { const q = k.path.at(t); if (q) pts.push([q.lat, q.lon]) }
    if (loc.garage && (pts.length === 1 || modeRef.current === 'all' || pts.some(q => miles({ lat: q[0], lon: q[1] }, loc.garage) < 4)) && miles(loc.garage, loc.wo) < 60) pts.push([loc.garage.lat, loc.garage.lon])
    const b = L.latLngBounds(pts), tight = pts.length < 2 || b.getNorthEast().distanceTo(b.getSouthWest()) < 40
    const z = tight ? 16 : Math.min(map.getBoundsZoom(b, false, PAD.tl.add(PAD.br)), 17)
    if (modeRef.current === 'all' || Math.abs(z - map.getZoom()) > 0.8) {
      flying.current = Date.now() + 1000
      const off = L.point((PAD.tl.x - PAD.br.x) / 2, (PAD.tl.y - PAD.br.y) / 2)
      map.flyTo(map.unproject(map.project(b.getCenter(), z).subtract(off), z), z, { duration: 0.9 })
    }
  }, [idx, map]) // eslint-disable-line react-hooks/exhaustive-deps

  const heldBy = useRef(false)
  const stepTo = k => { const n = Math.min(steps.length - 1, Math.max(0, k)); engine.seek(times[n] + 0.01) }
  useEffect(() => {   // "Show it in the replay": go to that moment and stop, so it can be read ({ ts } from a contact mark, or { id } from a takeaway)
    if (!jump?.n) return
    const ts = jump.ts != null ? toS(jump.ts) : times[steps.findIndex(x => x.id === jump.id)]
    if (ts != null && Number.isFinite(ts)) { engine.pause(); engine.seek(ts + 0.01) }
  }, [jump?.n]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {   // it starts by itself as soon as the story is in: nobody should have to find Play
    if (prefersReducedMotion()) return undefined
    const h = setTimeout(() => engine.play(), 400)
    return () => clearTimeout(h)
  }, [engine])

  const scrub = useMemo(() => [
    ...steps.map((s, k) => ({ t: times[k], label: `${s.clock} ${s.title}`, level: s.flag?.level, colour: s.flag ? '#f43f5e' : KINDS[s.kind]?.colour, Icon: KIND_ICON[s.kind] })),
    ...marks.map(m => ({ t: m.ts, label: m.title, colour: MARK_COLOUR[m.type], Icon: MARK_ICON[m.type] })),
  ], [steps, times, marks])
  const toggleDrawer = () => setOpen(o => { store('woReplayFlowOpen', o ? '0' : '1'); return !o })
  const toggleFs = () => (document.fullscreenElement ? document.exitFullscreen() : fsRef.current?.requestFullscreen?.())
  const toggleTheme = () => setLight(v => { store('woReplayLight', v ? '0' : '1'); return !v })
  const btn = on => `px-2 py-1.5 rounded-lg text-[11px] font-medium flex items-center gap-1 ${on ? 'bg-brand-600 text-white' : 'bg-slate-800 hover:bg-slate-700 text-slate-300'}`

  const act = actor(tNow), pastPromise = wait.promise != null && tNow >= wait.promise
  const pos = trucks.find(k => k.est || k.name === act.name)?.path.at(tNow)
  const readout = !loc ? (locations === undefined ? 'Loading where the member and trucks were…' : 'Locations are not available for this call.')
    : !act.name && !pos ? (loc.towbook ? 'Towbook garage: Salesforce does not track where its driver is.' : 'No driver assigned at this moment.')
    : pos && loc.towbook && !act.name ? 'Towbook shows its driver only by status. The vehicle on the map is estimated from the Towbook En Route and On Location times, not GPS.'
    : pos && loc.wo ? `${act.name || 'The vehicle'} is ${miles(pos, loc.wo).toFixed(1)} mi from the member`
    : act.name && !trucks.some(k => k.name === act.name) ? `${act.name}: no GPS pings while this call was open.` : `${act.name || 'The vehicle'}: no GPS ping at this moment.`
  const ModeIcon = { follow: Crosshair, all: Globe2, free: Hand }[mode]

  return (
    <div ref={fsRef} className="space-y-2" style={isFs ? { background: '#020617', padding: 12, height: '100vh', display: 'flex', flexDirection: 'column' } : undefined}>
      <div className="flex rounded-2xl overflow-hidden border border-slate-700/60" style={isFs ? { flex: 1, minHeight: 0 } : { height: 'clamp(540px, calc(100vh - 230px), 820px)' }}>
        <div className="relative flex-1 min-w-0" style={{ background: '#0b1220' }}>
          <div ref={ref} style={{ position: 'absolute', inset: 0 }} />
          <FlowPulse fx={fx} />
          <StageHud engine={engine} hud={hud} stageW={size.w} t0={t0} pastPromise={pastPromise} pulse={idx} />
          <div style={{ position: 'absolute', left: 64, top: HUD.h + 22, zIndex: 1060, display: 'flex', gap: 8 }}>
            <Chip on={locations === undefined}>Loading trucks…</Chip><Chip on={!!extrasLoading}>Loading calls and texts…</Chip>
          </div>
          <div style={{ position: 'absolute', left: '50%', top: HUD.h + 22, transform: 'translateX(-50%)', zIndex: 1060, pointerEvents: 'none' }}><SkipChip engine={engine} /></div>
          <EventToasts engine={engine} steps={steps} times={times} />
          {step && fx?.dock && <StepCard step={step} dock={fx.dock} w={fx.cardW} maxH={Math.max(220, size.h - HUD.edgeY - 96)}
            onEnter={() => { if (engine.ref.current.playing) { heldBy.current = true; engine.pause() } }} onLeave={() => { if (heldBy.current) { heldBy.current = false; engine.play() } }} />}
          {step && <StepCaption step={step} i={idx} n={steps.length} />}
          <button onClick={toggleDrawer} title={open ? 'Close the flow' : 'Open the flow'} aria-label={open ? 'Close the flow' : 'Open the flow'}
            className="rp-glass" style={{ position: 'absolute', right: 0, top: HUD.h + 112, width: 38, height: 64, borderRadius: '12px 0 0 12px', color: '#fff', zIndex: 1070,
              display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 2, cursor: 'pointer' }}>
            {open ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}<ListOrdered size={16} />
          </button>
        </div>
        <FlowDrawer steps={steps} i={idx} open={open} onStep={stepTo} top={drawerTop} />
      </div>

      <ReplayPlayer engine={engine} start={t0 - 60} end={end} marks={scrub} onPrev={() => engine.prev()} onNext={() => engine.next()}>
        <button onClick={() => setHold(h => !h)} aria-pressed={hold} className={btn(hold)} title="Pause by itself at each problem, so it can be read. Press Play to carry on."><PauseOctagon className="w-3.5 h-3.5" />Pause at problems</button>
        <button onClick={() => setMode(m => (m === 'follow' ? 'all' : 'follow'))} className={btn(mode !== 'free')} title="Follow the truck, or show everyone. Dragging or zooming the map switches to free; click to follow again.">
          <ModeIcon className="w-3.5 h-3.5" />{mode === 'follow' ? 'Follow truck' : mode === 'all' ? 'Show all' : 'Free camera'}
        </button>
        <button onClick={toggleTheme} className={btn(false)} aria-label={light ? 'Dark map' : 'Light map'} title={light ? 'Dark map' : 'Light map'}>{light ? <Moon className="w-3.5 h-3.5" /> : <Sun className="w-3.5 h-3.5" />}</button>
        <button onClick={toggleFs} className={btn(false)} aria-label={isFs ? 'Exit full screen' : 'Full screen'} title={isFs ? 'Exit full screen' : 'Full screen'}>{isFs ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}</button>
      </ReplayPlayer>
      <div className="text-xs text-slate-300">{readout}</div>
      {loc?.towbook?.truck && <div className="text-xs text-slate-400">Towbook Driver 1 drove truck <b>{loc.towbook.truck}</b>. Towbook does not tell us who the driver is.</div>}
      {(loc?.notes || []).map((n, k) => <div key={k} className="text-xs text-slate-500">{n}</div>)}
    </div>
  )
}
