import { useMemo } from 'react'
import { X, Satellite, Route } from 'lucide-react'
import useTimeScale from '../reportcard/useTimeScale'
import { verdictColour, HEALTH_STYLES, LENS_LABEL, fmtTime } from '../reportcard/reportCardStyles'
import { initials } from './useLeafletMap'

const ms = iso => (iso ? new Date(iso).getTime() : null)
const PAD = 20 * 60000

function Bar({ scale, from, to, style, className = '', title }) {
  if (from == null || to == null || to <= from) return null
  const l = scale.pct(from)
  return <div title={title} className={`absolute ${className}`} style={{ left: `${l}%`, width: `${Math.max(scale.pct(to) - l, 0.6)}%`, ...style }} />
}

function statusLine(fd, sasById, tMs) {
  const c = fd?.status.call
  if (!c) return fd?.status.label || 'Not on the map'
  const sa = sasById[c.id]
  const due = c.promise_due ? c.promise_due * 1000 : null
  const left = due ? Math.round((due - tMs) / 60000) : null
  const promise = left == null ? '' : left >= 0 ? ` · original promise in ${left} min` : ` · ${-left} min past original promise`
  return `${fd.status.label}: ${sa?.number || c.number}${promise}`
}

/**
 * One driver's day at the replay clock, adapted from the Studio driver Gantt: live status, health,
 * where the position comes from, and his day timeline with the clock needle. Click the timeline to seek.
 */
export default function DriverDayCard({ driver, replayDriver, frameDriver, sas, sasById, t, onSeek, onSelectSa, onClose }) {
  const tMs = t * 1000
  const [startMs, endMs] = useMemo(() => {
    const times = [...(driver?.on_shift || []).flat().map(ms), ...sas.flatMap(s => [ms(s.milestones.t_asg) ?? ms(s.created), ms(s.milestones.t_end)])]
      .filter(Boolean)
    return times.length ? [Math.min(...times) - PAD, Math.max(...times) + PAD] : [tMs - 3600000, tMs + 3600000]
  }, [driver, sas]) // eslint-disable-line react-hooks/exhaustive-deps
  const scale = useTimeScale(startMs, endMs)
  const health = driver && HEALTH_STYLES[driver.health]
  const lens = driver?.health_owner && LENS_LABEL[driver.health_owner]
  const name = replayDriver?.name || driver?.name
  const mode = replayDriver?.mode

  const seek = e => {
    const r = e.currentTarget.getBoundingClientRect()
    onSeek((startMs + ((e.clientX - r.left) / r.width) * (endMs - startMs)) / 1000)
  }

  return (
    <div className="glass rounded-xl p-4 space-y-3">
      <div className="flex items-start gap-3">
        <span className="w-9 h-9 rounded-lg bg-slate-900 border-2 flex items-center justify-center text-xs font-bold text-white shrink-0"
          style={{ borderColor: frameDriver?.status.colour || '#475569', borderStyle: mode === 'estimated' ? 'dashed' : 'solid' }}>
          {initials(name)}
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-white truncate">{name}</div>
          <div className="flex flex-wrap items-center gap-1.5 mt-1">
            {health && <span className={`text-[10px] px-1.5 py-0.5 rounded border ${health.cls}`}>{health.label}{lens ? ` · ${lens.short}` : ''}</span>}
            <span className="text-[10px] text-slate-400 inline-flex items-center gap-1">
              {mode === 'gps' ? <Satellite className="w-3 h-3" /> : <Route className="w-3 h-3" />}
              {mode === 'gps' ? `Real GPS · ${replayDriver.gps_points} pings` : mode === 'estimated' ? 'Estimated position (no GPS)' : 'No position data'}
            </span>
          </div>
        </div>
        <button type="button" onClick={onClose} className="p-1 rounded hover:bg-slate-700 text-slate-400 hover:text-white" aria-label="Close driver">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="text-xs text-slate-200 flex items-center gap-2">
        <span className="w-2 h-2 rounded-full shrink-0" style={{ background: frameDriver?.status.colour || '#475569' }} />
        {statusLine(frameDriver, sasById, tMs)}
        {frameDriver?.pos?.stale > 0 && <span className="text-amber-300">· GPS gap {Math.round(frameDriver.pos.stale / 60)} min</span>}
      </div>
      {frameDriver?.held.length >= 2 && (
        <div className="text-[11px] text-amber-300">Holding {frameDriver.held.length} calls at once: {frameDriver.held.map(c => c.number).join(', ')}</div>
      )}

      <div>
        <div className="relative h-4">
          {scale.ticks.filter((_, i, a) => i % Math.ceil(a.length / 6) === 0).map(k => (
            <span key={k.ms} className="absolute -translate-x-1/2 text-[9px] text-slate-500" style={{ left: `${k.left}%` }}>{k.label}</span>
          ))}
        </div>
        <div className="relative h-12 rounded-lg bg-slate-900/80 border border-slate-700/60 overflow-hidden cursor-pointer" onClick={seek} title="Click to move the replay clock">
          {(driver?.on_shift || []).map(([a, b], i) => <Bar key={`s${i}`} scale={scale} from={ms(a)} to={ms(b)} className="top-0 bottom-0 bg-slate-700/30" title="On shift" />)}
          {(driver?.stacked || []).map(([a, b, n], i) => (
            <Bar key={`k${i}`} scale={scale} from={ms(a)} to={ms(b)} className="top-0 h-1.5" style={{ background: n >= 3 ? '#f97316' : '#fbbf24' }} title={`${n} open jobs`} />
          ))}
          {sas.map(s => {
            const m = s.milestones, c = verdictColour(s.verdict?.code), end = ms(m.t_end ?? m.actual_end)
            const missed = s.verdict?.evidence?.pta_met === false
            return (
              <div key={s.id}>
                <Bar scale={scale} from={ms(m.t_asg)} to={ms(m.t_er ?? m.t_ol) ?? end} className="top-[34px] h-px" style={{ borderTop: `1.5px dashed ${c}` }} title={`${s.number} waiting`} />
                <Bar scale={scale} from={ms(m.t_er)} to={ms(m.t_ol) ?? end} className="top-[20px] h-0.5" style={{ background: c }} title={`${s.number} en route`} />
                <Bar scale={scale} from={ms(m.t_ol)} to={end} className="top-3 h-4 rounded-sm"
                  style={{ background: c, boxShadow: missed ? 'inset 0 0 0 2px #f43f5e' : undefined }} title={`${s.number} on scene${missed ? ' · PTA missed' : ''}`} />
              </div>
            )
          })}
          <div className="absolute top-0 bottom-0 w-0.5 bg-white shadow-[0_0_6px_rgba(255,255,255,0.8)] pointer-events-none" style={{ left: `${scale.pct(tMs)}%` }} />
        </div>
      </div>

      <div className="max-h-48 overflow-y-auto divide-y divide-slate-800/70">
        {sas.length === 0 && <div className="text-[11px] text-slate-500 py-2">No calls ran by this driver today.</div>}
        {sas.map(s => (
          <button key={s.id} type="button" onClick={() => onSelectSa(s.id)}
            className="w-full flex items-center gap-2 py-1.5 text-left hover:bg-slate-800/50 rounded px-1">
            <span className="w-2 h-2 rounded-full shrink-0" style={{ background: verdictColour(s.verdict?.code) }} />
            <span className="text-[11px] font-mono text-slate-200">{s.number}</span>
            <span className="text-[10px] text-slate-500">{fmtTime(s.created)}</span>
            <span className="text-[10px] text-slate-400 ml-auto truncate">{s.verdict ? s.verdict.code.replaceAll('_', ' ').toLowerCase() : 'not scored'}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
