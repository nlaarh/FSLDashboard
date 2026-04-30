import { useEffect, useState, useMemo } from 'react'
import {
  AlertTriangle, CheckCircle2, Trophy, XCircle, Clock, MapPin,
  Search, ChevronRight, Sparkles, RefreshCw, Users,
} from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, Cell, Tooltip, ResponsiveContainer,
} from 'recharts'
import { optimizerRunHealth, optimizerDriverDay } from '../api'
import OptDecisionTree from './OptDecisionTree'
import { optimizerGetSA } from '../api'

function fmtSec(s) {
  if (s == null) return '—'
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.round(s / 60)}m`
  return `${(s / 3600).toFixed(1)}h`
}

function parseUtc(iso) {
  if (!iso) return null
  return new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + 'Z')
}

function fmtClock(iso) {
  const d = parseUtc(iso)
  return d ? d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false }) : ''
}

// ── Headline strip ──────────────────────────────────────────────────────────

function Headline({ headline, run }) {
  const sev = headline?.severity || 'info'
  const cfg = {
    ok:    { bg: 'rgba(34,197,94,0.10)',  border: 'rgba(34,197,94,0.35)',  color: '#86efac', Icon: CheckCircle2 },
    warn:  { bg: 'rgba(245,158,11,0.12)', border: 'rgba(245,158,11,0.4)',  color: '#fbbf24', Icon: AlertTriangle },
    error: { bg: 'rgba(239,68,68,0.12)',  border: 'rgba(239,68,68,0.4)',   color: '#fca5a5', Icon: AlertTriangle },
    info:  { bg: 'rgba(99,102,241,0.10)', border: 'rgba(99,102,241,0.4)',  color: '#a5b4fc', Icon: CheckCircle2 },
  }[sev] || { bg: '#1e293b', border: '#334155', color: '#cbd5e1', Icon: CheckCircle2 }
  const Icon = cfg.Icon
  return (
    <div className="flex items-center gap-3 px-4 py-3 rounded-xl border-2"
         style={{ background: cfg.bg, borderColor: cfg.border }}>
      <Icon size={22} color={cfg.color} className="shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="text-[10px] uppercase tracking-wider font-bold" style={{ color: cfg.color, opacity: 0.85 }}>
          Run Health
        </div>
        <div className="text-sm font-semibold text-slate-100 mt-0.5">
          {headline?.message || 'Loading…'}
        </div>
      </div>
      {run && (
        <div className="text-right text-[11px] text-slate-400 shrink-0">
          <div className="font-mono">{run.name}</div>
          <div>{run.policy_name || ''}</div>
        </div>
      )}
    </div>
  )
}

// ── Alert chips ─────────────────────────────────────────────────────────────

function AlertChips({ alerts, onChipClick }) {
  if (!alerts || alerts.length <= 1) return null
  return (
    <div className="flex gap-2 flex-wrap">
      {alerts.slice(1).map((a, i) => (
        <button
          key={i}
          onClick={() => onChipClick?.(a)}
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] border transition-colors ${
            a.severity === 'warn' || a.severity === 'error'
              ? 'bg-amber-500/10 text-amber-300 border-amber-500/30 hover:bg-amber-500/20'
              : 'bg-slate-800/50 text-slate-300 border-slate-700/40 hover:bg-slate-800'
          }`}
        >
          {(a.severity === 'warn' || a.severity === 'error') && <AlertTriangle size={11} />}
          {a.message}
        </button>
      ))}
    </div>
  )
}

// ── Workload bar chart (Recharts) ───────────────────────────────────────────

function WorkloadBars({ workload, distribution, onSelectDriver, selectedDriverId, search }) {
  const filtered = useMemo(() => {
    const q = (search || '').toLowerCase().trim()
    return q
      ? workload.filter(w => (w.driver_name || '').toLowerCase().includes(q))
      : workload
  }, [workload, search])

  // Cap visible bars to keep chart readable, but allow scrolling
  const data = filtered.slice(0, 30).map(w => ({
    ...w,
    name: w.driver_name?.replace(/\s+\d+[A-Z]+$/, '') || '?',
    full: w.driver_name,
    overload: w.sa_count >= distribution?.outlier_threshold,
  }))

  return (
    <div className="bg-slate-900/40 border border-slate-700/40 rounded-xl">
      <div className="px-4 py-2.5 border-b border-slate-700/40 flex items-center gap-3">
        <Users size={14} className="text-indigo-400" />
        <h3 className="text-xs font-semibold text-slate-200">Driver Workload</h3>
        <span className="text-[10px] text-slate-500">
          median {distribution?.median} · max {distribution?.max} · outlier ≥ {distribution?.outlier_threshold?.toFixed(0)}
        </span>
        <span className="ml-auto text-[10px] text-slate-500">{filtered.length} drivers</span>
      </div>
      <div className="p-2" style={{ height: Math.min(data.length * 28 + 40, 600) }}>
        {data.length === 0 ? (
          <div className="h-full flex items-center justify-center text-slate-500 text-xs">
            No drivers match
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} layout="vertical" margin={{ top: 6, right: 36, bottom: 6, left: 0 }}
                       onClick={(e) => e?.activePayload?.[0]?.payload && onSelectDriver?.(e.activePayload[0].payload)}>
              <XAxis type="number" hide />
              <YAxis type="category" dataKey="name" width={140}
                      tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 6, fontSize: 11 }}
                formatter={(v, name, p) => [`${v} SAs`, p.payload.full]}
                labelFormatter={() => ''}
                cursor={{ fill: 'rgba(148,163,184,0.06)' }}
              />
              <Bar dataKey="sa_count" radius={[0, 4, 4, 0]} cursor="pointer">
                {data.map((d, i) => (
                  <Cell key={i}
                        fill={d.driver_id === selectedDriverId ? '#a78bfa' :
                              d.overload ? '#fb7185' :
                              d.sa_count >= (distribution?.median || 0) ? '#60a5fa' : '#475569'}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}

// ── Driver day timeline ─────────────────────────────────────────────────────

function DriverDay({ runId, driver, onPickSA }) {
  const [day, setDay] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!driver) { setDay(null); return }
    setLoading(true)
    optimizerDriverDay(runId, driver.driver_id)
      .then(setDay)
      .catch(() => setDay(null))
      .finally(() => setLoading(false))
  }, [runId, driver])

  if (!driver) {
    return (
      <div className="bg-slate-900/40 border border-dashed border-slate-700/40 rounded-xl p-6 text-center text-slate-500 text-sm">
        Click a driver bar above to see their day
      </div>
    )
  }

  // Build timeline. Use scheduled times to position blocks across a 24h horizontal axis.
  const won = day?.won || []
  // Fall back to earliest_start when sched_start is null (optimizer didn't schedule yet).
  const startsMs = won.map(s => parseUtc(s.sched_start || s.earliest_start)?.getTime()).filter(t => t)
  const endsMs   = won.map(s => parseUtc(s.sched_end || s.sched_start || s.due_date)?.getTime()).filter(t => t)
  const dayStartMs = startsMs.length ? Math.min(...startsMs) : 0
  const dayEndMs   = endsMs.length   ? Math.max(...endsMs)   : 0
  const hasTimeline = dayEndMs > dayStartMs
  const span = hasTimeline ? (dayEndMs - dayStartMs) : 1

  return (
    <div className="bg-slate-900/40 border border-slate-700/40 rounded-xl">
      <div className="px-4 py-2.5 border-b border-slate-700/40 flex items-center gap-3">
        <Trophy size={14} className="text-emerald-400" />
        <h3 className="text-xs font-semibold text-slate-200">{driver.driver_name}</h3>
        <span className="text-[10px] text-slate-500">
          {driver.driver_territory} · {driver.sa_count} SAs assigned
        </span>
        <span className="ml-auto text-[10px] text-slate-500">
          {day ? `${day.lost_count} lost out, ${day.excluded_count} excluded` : '…'}
        </span>
      </div>
      <div className="p-3">
        {loading && <div className="text-slate-500 text-xs flex items-center gap-2"><RefreshCw size={11} className="animate-spin" />Loading…</div>}
        {!loading && won.length === 0 && (
          <div className="text-slate-500 text-xs">This driver got 0 SAs in this run.</div>
        )}
        {!loading && won.length > 0 && (
          <>
            {/* Horizontal day timeline (only if we have valid scheduled times) */}
            {hasTimeline ? (
              <>
                <div className="relative h-16 bg-slate-950/60 rounded-lg border border-slate-800/60 overflow-hidden">
                  {won.map((sa, i) => {
                    const start = parseUtc(sa.sched_start || sa.earliest_start)?.getTime()
                    const end = parseUtc(sa.sched_end || sa.sched_start || sa.due_date)?.getTime()
                    if (!start || !end) return null
                    const left = ((start - dayStartMs) / span) * 100
                    const width = Math.max(((end - start) / span) * 100, 1.5)
                    return (
                      <button
                        key={i}
                        onClick={() => onPickSA?.(sa.sa_number)}
                        className="absolute top-2 bottom-2 rounded transition-all hover:ring-2 hover:ring-emerald-300 cursor-pointer"
                        style={{
                          left: `${left}%`, width: `${width}%`,
                          background: `hsl(${(sa.priority || 50) * 1.5}, 70%, 50%)`,
                          minWidth: 18,
                        }}
                        title={`${sa.sa_number} · pri ${sa.priority} · ${Math.round(sa.duration_min || 0)}m · ${fmtClock(sa.sched_start || sa.earliest_start)}`}
                      />
                    )
                  })}
                </div>
                <div className="flex justify-between text-[10px] text-slate-500 font-mono mt-1.5">
                  <span>{fmtClock(new Date(dayStartMs).toISOString())}</span>
                  <span>—</span>
                  <span>{fmtClock(new Date(dayEndMs).toISOString())}</span>
                </div>
              </>
            ) : (
              <div className="text-[11px] text-slate-500 italic px-2 py-1 bg-slate-950/40 rounded mb-2">
                No scheduled times available for these SAs (optimizer hadn't committed yet) — showing the SA list below.
              </div>
            )}

            {/* SA list table */}
            <div className="mt-3 max-h-72 overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="text-[10px] text-slate-500 uppercase tracking-wider">
                  <tr className="border-b border-slate-800/60">
                    <th className="text-left px-2 py-1.5">SA</th>
                    <th className="text-left px-2 py-1.5">Time</th>
                    <th className="text-right px-2 py-1.5">Pri</th>
                    <th className="text-right px-2 py-1.5">Dur</th>
                    <th className="text-right px-2 py-1.5">Travel</th>
                    <th className="text-left px-2 py-1.5">Skills</th>
                  </tr>
                </thead>
                <tbody>
                  {won.map((sa, i) => (
                    <tr key={i} className="border-b border-slate-800/30 hover:bg-slate-800/30 cursor-pointer"
                         onClick={() => onPickSA?.(sa.sa_number)}>
                      <td className="px-2 py-1.5 font-mono text-indigo-300">{sa.sa_number}</td>
                      <td className="px-2 py-1.5 text-slate-400 font-mono text-[10px]">{fmtClock(sa.sched_start)}</td>
                      <td className="px-2 py-1.5 text-right font-mono text-slate-300">{sa.priority ?? '—'}</td>
                      <td className="px-2 py-1.5 text-right font-mono text-slate-400">{Math.round(sa.duration_min || 0)}m</td>
                      <td className="px-2 py-1.5 text-right font-mono text-slate-400">
                        {sa.winner_travel_time_min != null ? `${Math.round(sa.winner_travel_time_min)}m` : '—'}
                      </td>
                      <td className="px-2 py-1.5 text-slate-500 max-w-[180px] truncate" title={sa.required_skills}>
                        {sa.required_skills || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ── SA detail popover (uses existing decision tree) ──────────────────────────

function SADrillModal({ saNumber, runId, onClose }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!saNumber) return
    setLoading(true)
    optimizerGetSA(saNumber, 5)
      .then(rs => {
        const match = rs.find(r => r.run_id === runId) || rs[0]
        if (!match) return setData(null)
        const winner = match.verdicts?.find(v => v.status === 'winner')
        const eligible = match.verdicts?.filter(v => v.status === 'eligible') || []
        const excluded = {}
        for (const v of (match.verdicts || []).filter(v => v.status === 'excluded')) {
          const r = v.exclusion_reason || 'unknown'
          if (!excluded[r]) excluded[r] = []
          excluded[r].push(v)
        }
        setData({
          visualization_type: 'decision_tree',
          sa_number: match.sa_number,
          sa_work_type: match.sa_work_type,
          territory_name: match.territory_name,
          run_at: match.run_at,
          action: match.action,
          unscheduled_reason: match.unscheduled_reason,
          winner, eligible, excluded,
          all_verdicts: match.verdicts,
        })
      })
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [saNumber, runId])

  if (!saNumber) return null
  return (
    <div className="fixed inset-0 z-[100] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4"
         onClick={onClose}>
      <div className="bg-slate-950 border border-slate-700 rounded-xl shadow-2xl max-w-5xl w-full max-h-[90vh] flex flex-col"
           onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-3 border-b border-slate-700/60 flex items-center gap-3">
          <span className="font-mono font-bold text-indigo-300">{saNumber}</span>
          <span className="text-[11px] text-slate-500">decision tree</span>
          <button onClick={onClose} className="ml-auto text-slate-500 hover:text-white text-xs">✕ Close</button>
        </div>
        <div className="flex-1 overflow-auto p-4">
          {loading && <div className="text-slate-500 text-sm flex items-center gap-2"><RefreshCw size={12} className="animate-spin" />Loading decision…</div>}
          {!loading && data && <OptDecisionTree data={data} />}
          {!loading && !data && <div className="text-slate-500 text-sm">No verdict data found.</div>}
        </div>
      </div>
    </div>
  )
}

// ── Main view ───────────────────────────────────────────────────────────────

export default function OptimizerHealthView({ run, onAskAI }) {
  const [health, setHealth] = useState(null)
  const [loading, setLoading] = useState(false)
  const [search, setSearch]  = useState('')
  const [selectedDriver, setSelectedDriver] = useState(null)
  const [drillSA, setDrillSA] = useState(null)

  useEffect(() => {
    if (!run?.id) return
    setLoading(true)
    setSelectedDriver(null)
    optimizerRunHealth(run.id)
      .then(h => {
        setHealth(h)
        // Auto-select the most-loaded driver to give immediate context
        if (h?.workload?.length) setSelectedDriver(h.workload[0])
      })
      .catch(() => setHealth(null))
      .finally(() => setLoading(false))
  }, [run?.id])

  if (!run) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-500 text-sm">
        Select a run from the left to see its health
      </div>
    )
  }
  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center gap-2 text-slate-500 text-sm">
        <RefreshCw size={15} className="animate-spin" />Analyzing run…
      </div>
    )
  }
  if (!health) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-500 text-sm">
        No data for this run yet (still being parsed).
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-hidden gap-3 p-3">
      {/* Top: headline + ask AI */}
      <div className="flex gap-2 items-stretch">
        <div className="flex-1"><Headline headline={health.headline} run={health.run} /></div>
        <button
          onClick={() => onAskAI?.(run)}
          className="px-3 py-2 rounded-xl text-xs font-medium bg-brand-600/20 hover:bg-brand-600/30 text-brand-300 border border-brand-500/25 flex items-center gap-1.5 self-stretch"
        >
          <Sparkles size={12} />Ask AI
        </button>
      </div>

      {/* Anomaly chips (skip headline since shown above) */}
      <AlertChips alerts={health.alerts} onChipClick={() => {}} />

      {/* Search bar */}
      <div className="relative">
        <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search driver name…"
          className="w-full bg-slate-900/60 border border-slate-700/50 rounded-lg pl-8 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
        />
      </div>

      {/* Workload + driver day in two columns on wide, stacked on narrow */}
      <div className="flex-1 grid grid-cols-1 xl:grid-cols-2 gap-3 overflow-hidden">
        <div className="overflow-y-auto">
          <WorkloadBars
            workload={health.workload}
            distribution={health.distribution}
            onSelectDriver={setSelectedDriver}
            selectedDriverId={selectedDriver?.driver_id}
            search={search}
          />
        </div>
        <div className="overflow-y-auto">
          <DriverDay runId={run.id} driver={selectedDriver} onPickSA={setDrillSA} />
        </div>
      </div>

      {/* SA drill-down modal */}
      <SADrillModal saNumber={drillSA} runId={run.id} onClose={() => setDrillSA(null)} />
    </div>
  )
}
