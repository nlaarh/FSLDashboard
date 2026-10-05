import { LADDER_STATE } from './storyStyles'

/** The grid's priority matrix: which ranks were tried, declined, skipped as closed, or never reached. */
export default function MatrixLadder({ ladder, grid }) {
  if (!ladder?.length) return null
  return (
    <div className="glass rounded-xl p-4">
      <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-2">
        Priority matrix for grid {grid} · current matrix, may differ from that day
      </div>
      <div className="flex flex-wrap gap-2">
        {ladder.map(r => {
          const s = LADDER_STATE[r.state] || LADDER_STATE.not_reached
          return (
            <div key={`${r.rank}-${r.garage}`} className="rounded-lg border border-slate-700/60 px-2.5 py-1.5 min-w-[150px]">
              <div className="text-[10px] text-slate-500">Rank {r.rank}{r.worktype ? ` · ${r.worktype}` : ''}</div>
              <div className="text-xs text-slate-200 truncate" title={r.garage}>{r.garage}</div>
              <div className={`text-[10px] ${s.cls}`}>{s.label}{r.hours ? <span className="text-slate-500"> · {r.hours}</span> : ''}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
