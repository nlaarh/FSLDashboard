import { useCallback, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import GanttRow from './GanttRow'
import useTimeScale from './useTimeScale'
import { verdictColour } from './reportCardStyles'

const PAD_MS = 30 * 60000
const ms = iso => (iso ? new Date(iso).getTime() : null)
const GOOD = verdictColour('GOOD')

function Legend() {
  const item = (el, label) => <span className="flex items-center gap-1.5">{el}{label}</span>
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-slate-400 px-3 py-2 border-b border-slate-800/60">
      {item(<span className="w-5 h-3 bg-slate-700/60 rounded-sm" />, 'On shift (truck login)')}
      {item(<span className="w-5 h-3 rounded-sm" style={{ background: 'repeating-linear-gradient(135deg, rgba(148,163,184,0.35) 0 3px, transparent 3px 6px)' }} />, 'Idle on shift')}
      {item(<span className="w-5 h-3 rounded-sm" style={{ background: 'repeating-linear-gradient(45deg, rgba(100,116,139,0.7) 0 2px, transparent 2px 4px)' }} />, 'Absence')}
      {item(<span className="relative w-6 h-3"><span className="absolute inset-x-0 top-0 h-1.5 bg-amber-400 rounded-sm" /><span className="absolute left-0 -top-0.5 text-[8px] font-bold px-0.5 bg-amber-400 text-slate-900 rounded-sm leading-none">2</span></span>, 'Stacked: number = open jobs')}
      {item(<span className="w-5 h-1.5" style={{ background: `repeating-linear-gradient(90deg, ${GOOD} 0 4px, transparent 4px 7px)` }} />, 'Waiting (assigned → en route)')}
      {item(<span className="w-2.5 h-2.5 rounded-full" style={{ background: GOOD }} />, 'Decision (click for details)')}
      {item(<span className="w-5 h-0.5" style={{ background: GOOD }} />, 'En route')}
      {item(<span className="w-5 h-3 rounded-sm" style={{ background: GOOD }} />, 'On scene (colour = verdict)')}
      {item(<span className="w-5 h-3 rounded-sm" style={{ background: GOOD, boxShadow: 'inset 0 0 0 2px #f43f5e' }} />, 'PTA missed')}
      {item(<span className="w-5 h-3 rounded-sm" style={{ border: `1.5px solid ${GOOD}` }} />, 'Canceled')}
    </div>
  )
}

/** Portalled to <body>: the .glass card's backdrop-filter would otherwise re-anchor position: fixed. */
function Tooltip({ tip }) {
  if (!tip) return null
  const left = Math.min(tip.x + 14, window.innerWidth - 300)
  return createPortal(
    <div className="fixed z-[60] pointer-events-none max-w-[290px] rounded-lg border border-slate-700 bg-slate-900/95 px-3 py-2 shadow-xl"
      style={{ left, top: tip.y + 14 }}>
      {tip.lines.map((l, i) => (
        <div key={i} className={i === 0 ? 'text-xs font-semibold text-white' : 'text-[11px] text-slate-300 mt-0.5'}>{l}</div>
      ))}
    </div>,
    document.body,
  )
}

/** Optional replay props: clockMs draws the shared playhead, onSeek makes the hour strip a scrubber,
 *  onSelectDriver makes driver names clickable. */
export default function DayGantt({ data, highlight, selectedSa, onSelect, clockMs, onSeek, onSelectDriver, selectedDriver, bodyClass = '' }) {
  const { drivers, sas, window: win } = data
  const [tip, setTip] = useState(null)
  const onHover = useCallback(t => setTip(t), [])
  const [startMs, endMs] = useMemo(() => {
    const d0 = ms(win.day_start_utc), d1 = ms(win.day_end_utc)
    const times = [
      ...drivers.flatMap(d => d.on_shift.flat().map(ms)),
      ...sas.flatMap(s => [ms(s.created), ms(s.milestones.t_end) ?? ms(s.milestones.actual_end)]),
    ].filter(Boolean)
    if (!times.length) return [d0, d1]
    return [Math.max(d0, Math.min(...times) - PAD_MS), Math.min(d1, Math.max(...times) + PAD_MS)]
  }, [drivers, sas, win])
  const scale = useTimeScale(startMs, endMs)

  const byDriver = useMemo(() => {
    const out = {}
    for (const s of sas) {
      if (s.final_driver_id) (out[s.final_driver_id] ||= []).push(s)
    }
    return out
  }, [sas])
  const orphans = sas.filter(s => !s.final_driver_id || !drivers.some(d => d.id === s.final_driver_id))

  return (
    <div className="glass rounded-xl overflow-hidden">
      <Legend />
      <div className="overflow-x-auto">
        <div className="min-w-[900px]">
          <div className="flex border-b border-slate-700/60 bg-slate-900/40">
            <div className="w-64 shrink-0 px-3 py-1.5 text-[10px] uppercase tracking-wide text-slate-500 border-r border-slate-800/60">
              Driver · health (lens)
            </div>
            <div className={`relative flex-1 h-7 ${onSeek ? 'cursor-pointer' : ''}`} title={onSeek ? 'Click to move the replay clock' : undefined}
              onClick={onSeek ? e => { const r = e.currentTarget.getBoundingClientRect(); onSeek(startMs + ((e.clientX - r.left) / r.width) * scale.span) } : undefined}>
              {scale.ticks.map(t => (
                <span key={t.ms} className="absolute top-1.5 -translate-x-1/2 text-[10px] text-slate-500" style={{ left: `${t.left}%` }}>
                  {t.label}
                </span>
              ))}
            </div>
          </div>
          <div className={`relative ${bodyClass}`}>
            <div className="absolute inset-0 left-64 pointer-events-none">
              {scale.ticks.map(t => <div key={t.ms} className="absolute top-0 bottom-0 w-px bg-slate-800/70" style={{ left: `${t.left}%` }} />)}
              {clockMs != null && <div className="absolute top-0 bottom-0 w-0.5 bg-white/90 z-10 shadow-[0_0_6px_rgba(255,255,255,0.7)]" style={{ left: `${scale.pct(clockMs)}%` }} />}
            </div>
            {drivers.map(d => (
              <GanttRow key={d.id} driver={d} sas={byDriver[d.id] || []} scale={scale}
                highlight={highlight} selectedSa={selectedSa} onSelect={onSelect} onHover={onHover}
                onSelectDriver={onSelectDriver} selected={selectedDriver === d.id} />
            ))}
            {orphans.length > 0 && (
              <GanttRow
                driver={{ id: 'none', name: 'No driver assigned', health: null, assigned: orphans.length,
                          metrics: { M04: {}, M06: { value: '—' }, M13: {} }, on_shift: [], idle: [], absences: [], stacked: [] }}
                sas={orphans} scale={scale} highlight={highlight} selectedSa={selectedSa} onSelect={onSelect} onHover={onHover} />
            )}
          </div>
        </div>
      </div>
      <Tooltip tip={tip} />
    </div>
  )
}
