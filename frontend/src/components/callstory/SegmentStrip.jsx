import { SEVERITY, SEGMENT_LABEL, fmtTime } from './storyStyles'

/** One row per stage: bar scaled to the longest of {minutes, p95}, ticks at this garage's p75 / p90. */
export default function SegmentStrip({ segments, highlight, onHighlight }) {
  if (!segments.length) return null
  const scale = Math.max(...segments.map(g => Math.max(g.minutes || 0, g.baseline?.p95 || 0, g.floor_min || 0)), 1)
  const pct = m => `${Math.min(100, (m / scale) * 100)}%`
  return (
    <div className="glass rounded-xl p-4">
      <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-2">
        How long each stage took vs this garage's normal (ticks: p75 · p90)
      </div>
      <div className="space-y-1.5">
        {segments.map(g => {
          const sev = SEVERITY[g.severity] || SEVERITY.OK
          const b = g.baseline
          const thin = !b || b.n < 30
          const lit = highlight?.length && g.event_ids?.some(id => highlight.includes(id))
          return (
            <div key={g.id} onMouseEnter={() => onHighlight(g.event_ids || [])} onMouseLeave={() => onHighlight([])}
              className={`grid grid-cols-[230px_1fr_150px] items-center gap-3 rounded px-1 ${lit ? 'bg-slate-800/60' : ''}`}>
              <div className="text-[11px] text-slate-300 truncate" title={`${fmtTime(g.from)} – ${fmtTime(g.to)} · ${g.garage || ''}`}>
                {SEGMENT_LABEL[g.kind]}
                {g.driver_state && <span className="text-slate-500"> · driver {g.driver_state.toLowerCase()}</span>}
                {g.stuck_type && <span className="ml-1 text-[9px] px-1 rounded bg-rose-500/15 text-rose-300">{g.stuck_type.replaceAll('_', ' ')}</span>}
              </div>
              <div className="relative h-3 rounded bg-slate-800/70">
                <div className="absolute inset-y-0 left-0 rounded" style={{ width: pct(g.minutes || 0), background: sev.bar }} />
                {b && !thin && [b.p75, b.p90].map((p, i) => (
                  <div key={i} className="absolute -top-0.5 -bottom-0.5 w-px bg-slate-300/70" style={{ left: pct(p) }} />
                ))}
              </div>
              <div className="flex items-center gap-1.5 text-[11px]">
                <span className="text-slate-200 tabular-nums w-14 text-right">{g.minutes == null ? 'open' : `${g.minutes} min`}</span>
                <span className={`text-[9px] px-1.5 py-0.5 rounded border ${sev.cls}`}
                  title={thin ? `No baseline yet (n = ${b?.n || 0}): judged by the ${g.floor_min}-min floor` :
                    `p75 ${b.p75} · p90 ${b.p90} · p95 ${b.p95} min (n ${b.n}, ${b.key_level.replaceAll('_', ' ')})`}>
                  {sev.label}{g.severity_reason === 'pta_passed' ? ' · PTA passed' : ''}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
