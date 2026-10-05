import { memo } from 'react'
import { verdictColour, HEALTH_STYLES, LENS_LABEL, fmtPct, fmtTime, fmtSpan } from './reportCardStyles'

export const ROW_H = 46          // lane area height (px)
const LANE_Y = 12                 // top of the work lane
const LANE_H = 18
const RAIL_Y = 36                 // waiting rail (assigned → en route)
const ms = iso => (iso ? new Date(iso).getTime() : null)

/** Absolutely positioned span with a hover tooltip. */
function Span({ scale, from, to, style, className = '', tip, onHover, minPct = 0.12 }) {
  if (from == null || to == null || to <= from) return null
  const l = scale.pct(from)
  const w = Math.max(scale.pct(to) - l, minPct)
  return (
    <div className={`absolute ${className}`} style={{ left: `${l}%`, width: `${w}%`, ...style }}
      onMouseMove={tip ? e => onHover({ x: e.clientX, y: e.clientY, lines: tip }) : undefined}
      onMouseLeave={tip ? () => onHover(null) : undefined} />
  )
}

function callTip(sa, phase, from, to) {
  const v = sa.verdict
  return [
    `${sa.number} · ${sa.work_type}`,
    `${phase}: ${fmtTime(from)} – ${fmtTime(to)} (${fmtSpan(from, to)})`,
    v ? `Verdict: ${v.code.replaceAll('_', ' ')}${v.evidence?.pta_met === false ? ' · PTA missed' : ''}` : 'Not scored',
  ]
}

function Call({ sa, scale, dimmed, selected, onSelect, onHover }) {
  const m = sa.milestones
  const colour = verdictColour(sa.verdict?.code)
  const canceled = (m.end_status || '').toLowerCase().startsWith('cancel')
  const missed = sa.verdict?.evidence?.pta_met === false
  const end = m.t_end ?? m.actual_end
  const waitEnd = m.t_er ?? m.t_ol ?? end
  return (
    <div style={{ opacity: dimmed ? 0.12 : 1 }}>
      <Span scale={scale} from={ms(m.t_asg)} to={ms(waitEnd)} onHover={onHover}
        tip={callTip(sa, 'Waiting (assigned → en route)', m.t_asg, waitEnd)}
        style={{ top: RAIL_Y - 3, height: 6,
                 background: `repeating-linear-gradient(90deg, ${colour}aa 0 4px, transparent 4px 7px) center / 100% 1.5px no-repeat` }} />
      <Span scale={scale} from={ms(m.t_er)} to={ms(m.t_ol ?? end)} onHover={onHover}
        tip={callTip(sa, 'En route', m.t_er, m.t_ol ?? end)}
        style={{ top: LANE_Y + LANE_H / 2 - 4, height: 8, background: `linear-gradient(${colour}, ${colour}) center / 100% 2px no-repeat` }} />
      <Span scale={scale} from={ms(m.t_ol)} to={ms(end)} onHover={onHover} minPct={0.25}
        tip={callTip(sa, canceled ? 'Canceled on scene' : 'On scene', m.t_ol, end)} className="rounded-sm"
        style={{ top: LANE_Y, height: LANE_H, ...(canceled ? { border: `1.5px solid ${colour}` }
          : { background: colour, boxShadow: missed ? 'inset 0 0 0 2px #f43f5e' : undefined }) }} />
      <button type="button" onClick={() => onSelect(sa.id)}
        onMouseMove={e => onHover({ x: e.clientX, y: e.clientY, lines: [
          `${sa.number} · ${sa.work_type}`, `Decision ${fmtTime(m.t_asg)} by ${sa.decision.final_actor || '—'}`,
          sa.verdict ? `Verdict: ${sa.verdict.code.replaceAll('_', ' ')}` : 'Not scored', 'Click for details'] })}
        onMouseLeave={() => onHover(null)}
        className="absolute -translate-x-1/2 -translate-y-1/2 rounded-full"
        style={{
          left: `${scale.pct(ms(m.t_asg) ?? ms(sa.created))}%`, top: RAIL_Y, width: 9, height: 9, zIndex: 3,
          background: canceled ? '#0f172a' : colour, border: `2px solid ${selected ? '#fff' : colour}`,
          boxShadow: selected ? '0 0 0 2px #6366f1' : undefined,
        }} />
    </div>
  )
}

function HealthBadge({ driver, onHover }) {
  const s = HEALTH_STYLES[driver.health]
  if (!s) return null
  const h = driver.health_detail
  const lens = driver.health_owner ? LENS_LABEL[driver.health_owner] : null
  const lines = h.reasons.length
    ? [`${s.label}${lens ? ` · ${lens.long}` : ''}`, ...h.reasons.map(r => r.text)]
    : ['Healthy: workload and execution both in the good band']
  return (
    <span onMouseMove={e => onHover({ x: e.clientX, y: e.clientY, lines })} onMouseLeave={() => onHover(null)}
      className={`text-[10px] px-1.5 py-0.5 rounded border font-medium whitespace-nowrap cursor-help ${s.cls}`}>
      {s.label}{lens ? ` · ${lens.short}` : ''}
    </span>
  )
}

function GanttRow({ driver, sas, scale, highlight, selectedSa, onSelect, onHover, onSelectDriver, selected }) {
  const m = driver.metrics
  return (
    <div className={`flex border-b border-slate-800/60 ${selected ? 'bg-brand-500/10' : ''}`}>
      <div className="w-64 shrink-0 px-3 py-1.5 border-r border-slate-800/60 flex flex-col justify-center gap-0.5">
        {onSelectDriver && driver.id !== 'none'
          ? <button type="button" onClick={() => onSelectDriver(driver.id)} title={`Show ${driver.name} on the map`}
              className="text-xs text-left text-brand-300 hover:text-white truncate">{driver.name}</button>
          : <span className="text-xs text-slate-200 truncate" title={driver.name}>{driver.name}</span>}
        <div><HealthBadge driver={driver} onHover={onHover} /></div>
        <div className="text-[10px] text-slate-500">
          {driver.assigned} calls · util {fmtPct(m.M04.value)} · max open {m.M06.value}
          {m.M13.n ? ` · PTA ${m.M13.met}/${m.M13.n}` : ''}
        </div>
      </div>
      <div className="relative flex-1" style={{ height: ROW_H + 12 }}>
        {driver.on_shift.map((iv, i) => (
          <Span key={`s${i}`} scale={scale} from={ms(iv[0])} to={ms(iv[1])} className="top-0 bottom-0 bg-slate-700/25" />
        ))}
        {driver.idle.map((iv, i) => (
          <Span key={`i${i}`} scale={scale} from={ms(iv[0])} to={ms(iv[1])} className="top-0 bottom-0" onHover={onHover}
            tip={['Idle on shift (0 open jobs)', `${fmtTime(iv[0])} – ${fmtTime(iv[1])} (${fmtSpan(iv[0], iv[1])})`]}
            style={{ background: 'repeating-linear-gradient(135deg, rgba(148,163,184,0.10) 0 4px, transparent 4px 8px)' }} />
        ))}
        {driver.absences.map((a, i) => (
          <Span key={`a${i}`} scale={scale} from={ms(a.start)} to={ms(a.end)} className="top-0 bottom-0" onHover={onHover}
            tip={[a.type || 'Absence', `${fmtTime(a.start)} – ${fmtTime(a.end)}`]}
            style={{ background: 'repeating-linear-gradient(45deg, rgba(100,116,139,0.45) 0 3px, transparent 3px 6px)' }} />
        ))}
        {driver.stacked.map(([a, b, n], i) => (
          <Span key={`k${i}`} scale={scale} from={ms(a)} to={ms(b)} className="top-0 h-[6px] rounded-sm" onHover={onHover}
            tip={[`Stacked: ${n} open jobs`, `${fmtTime(a)} – ${fmtTime(b)} (${fmtSpan(a, b)})`]}
            style={{ background: n >= 3 ? '#f97316' : '#fbbf24' }} />
        ))}
        {driver.stacked.filter(([a, b]) => scale.pct(ms(b)) - scale.pct(ms(a)) > 0.8).map(([a, , n], i) => (
          <span key={`kb${i}`} className="absolute top-0 -translate-y-0.5 text-[9px] font-bold leading-none px-1 rounded-sm bg-amber-400 text-slate-900 pointer-events-none"
            style={{ left: `${scale.pct(ms(a))}%`, zIndex: 4 }}>{n}</span>
        ))}
        {sas.map(sa => (
          <Call key={sa.id} sa={sa} scale={scale} onSelect={onSelect} onHover={onHover}
            selected={selectedSa === sa.id} dimmed={!!highlight && !highlight.has(sa.id)} />
        ))}
      </div>
    </div>
  )
}

export default memo(GanttRow)
