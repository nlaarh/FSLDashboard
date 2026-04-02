import { clsx } from 'clsx'

// ── Small Components ─────────────────────────────────────────────────────────

export function GradeRing({ grade, composite }) {
  const color = grade === 'A' ? 'text-emerald-400 border-emerald-500/40 bg-emerald-950/40'
    : grade === 'B' ? 'text-blue-400 border-blue-500/40 bg-blue-950/40'
    : grade === 'C' ? 'text-amber-400 border-amber-500/40 bg-amber-950/40'
    : 'text-red-400 border-red-500/40 bg-red-950/40'
  return (
    <div className={clsx('w-20 h-20 rounded-2xl flex flex-col items-center justify-center border-2', color)}>
      <div className="text-3xl font-black">{grade}</div>
      <div className="text-xs font-bold text-white/80">{composite}/100</div>
    </div>
  )
}

export function MetricCard({ label, value, sub, color = 'text-white', icon: Icon, target, met, border, definition, defId, activeDef, setActiveDef }) {
  const showDef = activeDef === defId
  return (
    <div className={clsx('rounded-xl p-4 bg-slate-800/50 border relative', border || 'border-slate-700/30')}>
      <div className="flex items-center justify-between mb-1.5">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</div>
        <div className="flex items-center gap-1">
          {definition && (
            <button onClick={() => setActiveDef?.(showDef ? null : defId)}
              className="w-4 h-4 rounded-full bg-slate-700/60 hover:bg-slate-600 text-slate-400 hover:text-white text-[9px] font-bold flex items-center justify-center transition-colors"
              title="How this is calculated">?</button>
          )}
          {Icon && <Icon className="w-3.5 h-3.5 text-slate-600" />}
        </div>
      </div>
      {showDef && definition && (
        <div className="absolute top-0 left-0 right-0 z-10 bg-slate-800 border border-slate-600/50 rounded-xl p-3 shadow-xl whitespace-normal break-words overflow-hidden">
          <div className="flex items-center justify-between mb-1 gap-2">
            <span className="text-[10px] font-bold text-brand-400 uppercase truncate">{label}</span>
            <button onClick={() => setActiveDef?.(null)} className="text-slate-400 hover:text-white text-xs shrink-0">&#x2715;</button>
          </div>
          <div className="text-[11px] text-slate-300 leading-relaxed break-words">{definition}</div>
        </div>
      )}
      <div className={clsx('text-2xl font-black', color)}>{value}</div>
      {sub && <div className="text-[10px] text-slate-500 mt-0.5">{sub}</div>}
      {target && (
        <div className={clsx('text-[10px] mt-1 font-medium', met ? 'text-emerald-500' : 'text-red-400')}>
          {met ? 'On target' : `Target: ${target}`}
        </div>
      )}
    </div>
  )
}

export function ProgressBar({ value, max = 100, color = 'bg-brand-500', height = 'h-2' }) {
  const w = Math.min(Math.max((value / max) * 100, 1), 100)
  return (
    <div className={clsx(height, 'bg-slate-900 rounded-full overflow-hidden')}>
      <div className={clsx('h-full rounded-full transition-all', color)} style={{ width: `${w}%` }} />
    </div>
  )
}

export function BucketGrid({ buckets }) {
  const colors = ['bg-emerald-950/30 border-emerald-800/20', 'bg-amber-950/30 border-amber-800/20',
                  'bg-orange-950/30 border-orange-800/20', 'bg-red-950/30 border-red-800/20']
  const textColors = ['text-emerald-400', 'text-amber-400', 'text-orange-400', 'text-red-400']
  return (
    <div className="grid grid-cols-4 gap-2">
      {buckets.map((b, i) => (
        <div key={b.label} className={clsx('text-center rounded-xl p-2.5 border', colors[i])}>
          <div className={clsx('text-lg font-bold', textColors[i])}>{b.count}</div>
          <div className="text-[9px] text-slate-400 mt-0.5 leading-tight">{b.label}</div>
          <div className={clsx('text-[10px] font-medium', textColors[i])}>{b.pct}%</div>
        </div>
      ))}
    </div>
  )
}

export function ReasonBars({ items, color = 'bg-red-500' }) {
  return (
    <div className="space-y-1.5">
      {items.map(r => (
        <div key={r.reason} className="flex items-center gap-2">
          <div className="flex-1 text-[11px] text-slate-300 truncate">{r.reason}</div>
          <div className="w-20 h-1.5 bg-slate-900 rounded-full overflow-hidden shrink-0">
            <div className={clsx('h-full rounded-full', color)} style={{ width: `${r.pct}%` }} />
          </div>
          <div className="text-[10px] text-slate-500 w-14 text-right shrink-0">{r.count} ({r.pct}%)</div>
        </div>
      ))}
    </div>
  )
}

// ── Supervisor Insights ──────────────────────────────────────────────────────

export function buildInsights(perf) {
  const insights = []
  const actions  = []
  const { acceptance, completion, response_time: rt, pts_ata } = perf

  if (completion.pct < 80) {
    insights.push({ type: 'critical', text: `Only ${completion.pct}% completion — ${+(100 - completion.pct).toFixed(1)}% of calls lost to cancellations/no-shows.` })
    actions.push({ priority: 'HIGH', text: 'Investigate cancellation reasons. Member canceling (too slow) or facility declining?' })
  } else if (completion.pct < 92) {
    insights.push({ type: 'warn', text: `Completion rate ${completion.pct}% — below 95% target.` })
    actions.push({ priority: 'MED', text: 'Review "Could Not Wait" cancellations and facility declines.' })
  } else {
    insights.push({ type: 'good', text: `Strong completion: ${completion.pct}% of calls completed.` })
  }

  if (rt.median != null) {
    if (rt.median > 90) {
      insights.push({ type: 'critical', text: `Median response ${rt.median} min — ${rt.median - 45} min over 45-min target.` })
      actions.push({ priority: 'HIGH', text: `Close the ${rt.median - 45}-min gap: closest-driver dispatch + reduce queue wait.` })
    } else if (rt.median > 45) {
      insights.push({ type: 'warn', text: `Median response ${rt.median} min — ${rt.median - 45} min over target. ${rt.under_45_pct}% under 45 min.` })
      actions.push({ priority: 'HIGH', text: `Need ${+(100 - rt.under_45_pct).toFixed(1)}% more calls under 45 min. Focus on dispatch queue time.` })
    } else {
      insights.push({ type: 'good', text: `Median response ${rt.median} min — meeting 45-min target.` })
    }
    if (rt.over_120 > 0) {
      insights.push({ type: 'warn', text: `${rt.over_120} calls (${rt.over_120_pct}%) took over 2 hours — highest cancellation risk.` })
    }
  }

  if (pts_ata && pts_ata.on_time_pct != null) {
    if (pts_ata.late_pct > 50) {
      insights.push({ type: 'critical', text: `${pts_ata.late_pct}% of calls arrived late vs. promised ETA (avg ${pts_ata.avg_delta > 0 ? '+' : ''}${pts_ata.avg_delta} min).` })
      actions.push({ priority: 'HIGH', text: 'Dispatch promising unrealistic ETAs. Review PTA values at dispatch time.' })
    } else if (pts_ata.late_pct > 25) {
      insights.push({ type: 'warn', text: `${pts_ata.late_pct}% late vs. promise (avg ${pts_ata.avg_delta > 0 ? '+' : ''}${pts_ata.avg_delta} min).` })
    } else {
      insights.push({ type: 'good', text: `${pts_ata.on_time_pct}% on time or early — strong ETA accuracy.` })
    }
  }

  if (acceptance.primary_total > 0 && acceptance.primary_pct < 70) {
    insights.push({ type: 'critical', text: `Only ${acceptance.primary_pct}% primary acceptance — declining ${+(100 - acceptance.primary_pct).toFixed(1)}% of auto-dispatched work.` })
    actions.push({ priority: 'HIGH', text: 'Identify top decline reasons. Driver availability? Truck mismatch?' })
  }

  if (rt.median != null && rt.median > 45) {
    actions.push({
      priority: 'GOAL',
      text: `PATH TO 45-MIN: Median is ${rt.median} min. Close the ${rt.median - 45}-min gap → dispatch closest driver first, reduce queue wait, ensure driver en route within 5 min of assignment.`,
    })
  }
  if (!insights.some(i => i.type !== 'good')) {
    actions.push({ priority: 'MAINTAIN', text: 'All metrics on target. Continue monitoring daily.' })
  }

  return { insights, actions }
}
