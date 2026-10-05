import { verdictColour, fmtPct, HEALTH_STYLES } from './reportCardStyles'

const BAND_CLS = { good: 'text-emerald-300', watch: 'text-amber-300', bad: 'text-rose-300' }

function Tile({ label, value, sub, band, title }) {
  return (
    <div className="glass rounded-xl px-4 py-3 min-w-[150px]" title={title}>
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`text-xl font-semibold mt-0.5 ${BAND_CLS[band] || 'text-white'}`}>{value}</div>
      {sub && <div className="text-[10px] text-slate-500 mt-0.5">{sub}</div>}
    </div>
  )
}

const ratio = (a, b) => (b ? a / b : null)

export default function DaySummary({ data, filter, onFilter }) {
  const s = data.summary
  const policy = data.config.policies_used?.[0]
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3">
        <Tile label="Calls" value={s.sa_count} sub={`${data.drivers.length} drivers`} />
        <Tile label="PTA met" value={fmtPct(s.M13.value)} sub={`${s.M13.met}/${s.M13.n} arrived calls`} band={s.M13.band} />
        <Tile label="Median response" value={s.M12.median == null ? '—' : `${s.M12.median} min`} sub={`n=${s.M12.n}`} />
        <Tile label="Queue wait p90" value={s.M08.p90 == null ? '—' : `${s.M08.p90} min`} sub={`median ${s.M08.median} min · assigned → en route`} band={s.M08.band} />
        <Tile label="Closer qualified driver idle" value={`${s.M20.idle_closer}/${s.M20.n}`}
          sub={`closer and less loaded: ${s.M20.less_loaded_closer}`} band={s.M20.band}
          title="A qualified, on-shift driver with fresh GPS was more than 0.5 mi closer than the pick and idle (spec M20)" />
        <Tile label="Closest picked" value={fmtPct(ratio(s.M17.picked, s.M17.n))} sub={`${s.M17.picked}/${s.M17.n} · free ${s.M19.picked}/${s.M19.n}`} band={s.M17.band} />
        <Tile label="Scheduler failures" value={fmtPct(s.failure_rate.value)} sub={`${s.failure_rate.failures}/${s.failure_rate.graded} graded`} />
        <div className="glass rounded-xl px-4 py-3">
          <div className="text-[10px] uppercase tracking-wide text-slate-500">Driver health</div>
          <div className="flex gap-1.5 mt-1.5">
            {['healthy', 'watch', 'unhealthy'].map(h => (
              <span key={h} className={`text-[11px] px-2 py-0.5 rounded border ${HEALTH_STYLES[h].cls}`}>
                {s.health_counts[h] || 0} {HEALTH_STYLES[h].label.toLowerCase()}
              </span>
            ))}
          </div>
        </div>
      </div>

      <div className="glass rounded-xl px-4 py-3">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[10px] uppercase tracking-wide text-slate-500">Verdicts · click to highlight on the Gantt</span>
          {filter && <button onClick={() => onFilter(null)} className="text-[10px] text-brand-300 hover:underline">Clear highlight</button>}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {data.verdict_catalog.filter(c => s.verdict_counts[c.code]).map(c => (
            <button key={c.code} onClick={() => onFilter(filter === c.code ? null : c.code)} title={c.label}
              className={`flex items-center gap-1.5 text-[11px] px-2 py-1 rounded-lg border transition-colors ${
                filter === c.code ? 'border-white/60 bg-slate-700/60' : 'border-slate-700/60 hover:bg-slate-800'}`}>
              <span className="w-2.5 h-2.5 rounded-full" style={{ background: verdictColour(c.code) }} />
              <span className="text-slate-200">{c.code.replaceAll('_', ' ')}</span>
              <span className="text-slate-400">{s.verdict_counts[c.code]}</span>
            </button>
          ))}
        </div>
        <div className="text-[10px] text-slate-500 mt-2 space-y-0.5">
          <div>
            Final decision by: {Object.entries(s.M09).map(([k, n]) => `${k.replaceAll('_', ' ').toLowerCase()} ${n}`).join(' · ')}
            {policy && <> · optimizer policy: {policy.name} ({policy.seen_in_runs} runs)</>}
          </div>
          <div>{data.caveats.join(' ')}</div>
        </div>
      </div>
    </div>
  )
}
