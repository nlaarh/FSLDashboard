/**
 * PerformanceCharts.jsx
 *
 * Chart components extracted from Performance.jsx:
 * - Trend chart (volume & completion)
 * - Response time buckets
 * - PTS-ATA accuracy / PTA distribution
 * - Dispatch acceptance
 * - Satisfaction mini section
 * - Supervisor analysis (insights + actions)
 * - Progress to 45-min ATA goal
 */

import {
  ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, Legend,
} from 'recharts'
import { clsx } from 'clsx'
import {
  CheckCircle2, XCircle, Clock, ThumbsUp,
  AlertTriangle, Target, Activity, Users, ArrowRight,
} from 'lucide-react'

// ── Shared sub-components ────────────────────────────────────────────────────

function BucketBar({ label, count, total, colorClass, pct }) {
  const p = pct ?? (total > 0 ? Math.round(100 * count / total) : 0)
  return (
    <div className="flex items-center gap-2">
      <div className="w-28 text-xs text-slate-400 text-right shrink-0">{label}</div>
      <div className="flex-1 h-5 bg-slate-900 rounded-full overflow-hidden">
        <div className={clsx('h-full rounded-full transition-all', colorClass)}
          style={{ width: `${Math.max(p, 1)}%` }} />
      </div>
      <div className="w-20 text-xs text-slate-400 shrink-0">{count.toLocaleString()} ({p}%)</div>
    </div>
  )
}

// ── Tooltip style (shared) ───────────────────────────────────────────────────

const tooltipStyle = {
  contentStyle: { background: '#1e293b', border: '1px solid #334155', borderRadius: 8 },
  itemStyle: { color: '#e2e8f0' },
  labelStyle: { color: '#94a3b8', fontSize: 11 },
}

// ── Main Charts Component ────────────────────────────────────────────────────

export default function PerformanceCharts({ data, label, insights, actions }) {
  return (
    <>
      {/* ── Trend Chart ─────────────────────────────────────────── */}
      {data.trend && data.trend.length > 0 && (
        <div className="glass rounded-xl p-5">
          <h3 className="font-semibold text-slate-200 mb-4 flex items-center gap-2">
            <Activity className="w-4 h-4 text-brand-400" />
            Volume & Completion Trend
            <span className="ml-auto text-xs text-slate-500 font-normal">
              {data.period.single_day ? 'Hourly' : 'Daily'} breakdown
            </span>
          </h3>
          <div className="h-52">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={data.trend} margin={{ left: -10, right: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="label" stroke="#475569"
                  tick={{ fontSize: 10, fill: '#94a3b8' }}
                  interval={data.trend.length > 14 ? Math.floor(data.trend.length / 10) : 0} />
                <YAxis yAxisId="vol" stroke="#475569" tick={{ fontSize: 10, fill: '#94a3b8' }} />
                <YAxis yAxisId="pct" orientation="right" domain={[0, 100]}
                  stroke="#475569" tick={{ fontSize: 10, fill: '#94a3b8' }}
                  tickFormatter={v => `${v}%`} />
                <Tooltip {...tooltipStyle}
                  formatter={(val, name) => name === 'Completion %' ? `${val}%` : val} />
                <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
                <Bar yAxisId="vol" dataKey="total" name="Total SAs" fill="#6366f1" radius={[3,3,0,0]} opacity={0.7} />
                <Bar yAxisId="vol" dataKey="completed" name="Completed" fill="#10b981" radius={[3,3,0,0]} opacity={0.8} />
                <Line yAxisId="pct" type="monotone" dataKey="completion_pct"
                  name="Completion %" stroke="#f59e0b" strokeWidth={2}
                  dot={{ fill: '#f59e0b', r: 3 }} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* ── Detail Cards Row ─────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {/* Response Time Buckets */}
        <div className="glass rounded-xl p-5 space-y-3">
          <h3 className="font-semibold text-slate-200 flex items-center gap-2">
            <Clock className="w-4 h-4 text-brand-400" /> {data.response_time.metric === 'PTA (promised)' ? 'PTA Breakdown (Towbook)' : 'Response Time Breakdown'}
          </h3>
          <div className="grid grid-cols-2 gap-2 mb-3">
            <div className="text-center bg-emerald-950/30 border border-emerald-800/20 rounded-xl p-3">
              <div className="text-xl font-bold text-emerald-400">{data.response_time.under_45}</div>
              <div className="text-[10px] text-slate-400 mt-0.5">Within 45 min</div>
              <div className="text-xs text-emerald-400">{data.response_time.under_45_pct}%</div>
            </div>
            <div className="text-center bg-amber-950/30 border border-amber-800/20 rounded-xl p-3">
              <div className="text-xl font-bold text-amber-400">{data.response_time.b45_90}</div>
              <div className="text-[10px] text-slate-400 mt-0.5">45-90 min</div>
              <div className="text-xs text-amber-400">{data.response_time.b45_90_pct}%</div>
            </div>
            <div className="text-center bg-orange-950/30 border border-orange-800/20 rounded-xl p-3">
              <div className="text-xl font-bold text-orange-400">{data.response_time.b90_120}</div>
              <div className="text-[10px] text-slate-400 mt-0.5">90-120 min</div>
              <div className="text-xs text-orange-400">{data.response_time.b90_120_pct}%</div>
            </div>
            <div className="text-center bg-red-950/30 border border-red-800/20 rounded-xl p-3">
              <div className="text-xl font-bold text-red-400">{data.response_time.over_120}</div>
              <div className="text-[10px] text-slate-400 mt-0.5">Over 2 hours</div>
              <div className="text-xs text-red-400">{data.response_time.over_120_pct}%</div>
            </div>
          </div>
          <div className="pt-2 border-t border-slate-800/60">
            <div className="flex justify-between text-xs text-slate-400 mb-1">
              <span>45-min target</span>
              <span className={data.response_time.median && data.response_time.median <= 45 ? 'text-emerald-400 font-semibold' : 'text-red-400 font-semibold'}>
                Median: {data.response_time.median ?? 'N/A'} min
              </span>
            </div>
            {data.response_time.median != null && data.response_time.median > 45 && (
              <div className="text-[10px] text-red-400 mt-1">
                ↑ {data.response_time.median - 45} min over target
              </div>
            )}
          </div>
        </div>

        {/* PTS-ATA Accuracy / Towbook PTA Distribution */}
        <div className="glass rounded-xl p-5 space-y-3">
          <h3 className="font-semibold text-slate-200 flex items-center gap-2">
            <Target className="w-4 h-4 text-brand-400" /> {data.pts_ata?.metric === 'PTA (promised)' ? 'PTA Distribution (Towbook)' : 'PTS-ATA (Promise vs Actual)'}
          </h3>
          {data.pts_ata?.on_time_pct != null ? (
            <>
              <div className="flex gap-3">
                <div className="flex-1 text-center bg-emerald-950/20 border border-emerald-800/20 rounded-xl p-3">
                  <div className="text-xl font-bold text-emerald-400">{data.pts_ata.on_time_pct}%</div>
                  <div className="text-[10px] text-slate-400">On Time or Early</div>
                </div>
                <div className="flex-1 text-center bg-red-950/20 border border-red-800/20 rounded-xl p-3">
                  <div className="text-xl font-bold text-red-400">{data.pts_ata.late_pct}%</div>
                  <div className="text-[10px] text-slate-400">Late vs Promise</div>
                </div>
              </div>
              <div className="text-center text-sm">
                <span className="text-slate-400">Avg delta: </span>
                <span className={clsx('font-bold', data.pts_ata.avg_delta > 0 ? 'text-red-400' : 'text-emerald-400')}>
                  {data.pts_ata.avg_delta > 0 ? '+' : ''}{data.pts_ata.avg_delta} min
                </span>
                <span className="text-slate-500 text-xs ml-1">vs. promise</span>
              </div>
              <div className="space-y-1.5 mt-1">
                {data.pts_ata.buckets.map(b => (
                  <BucketBar key={b.label} label={b.label} count={b.count}
                    total={data.pts_ata.total} pct={b.pct}
                    colorClass={
                      b.label.includes('Early') ? 'bg-emerald-500' :
                      b.label.includes('1–10')  ? 'bg-amber-400' :
                      b.label.includes('10–20') ? 'bg-orange-500' :
                      'bg-red-600'
                    } />
                ))}
              </div>
              <div className="text-[10px] text-slate-500 pt-1">
                Based on {data.pts_ata.total.toLocaleString()} completed SAs with valid ETA data.
                Positive = arrived after promised time.
              </div>
            </>
          ) : data.pts_ata?.metric === 'PTA (promised)' ? (
            <>
              <div className="flex gap-3">
                <div className="flex-1 text-center bg-brand-950/20 border border-brand-800/20 rounded-xl p-3">
                  <div className="text-xl font-bold text-brand-400">{data.pts_ata.median_pta ?? '?'}</div>
                  <div className="text-[10px] text-slate-400">Median PTA (min)</div>
                </div>
                <div className="flex-1 text-center bg-brand-950/20 border border-brand-800/20 rounded-xl p-3">
                  <div className="text-xl font-bold text-brand-400">{data.pts_ata.avg_pta ?? '?'}</div>
                  <div className="text-[10px] text-slate-400">Avg PTA (min)</div>
                </div>
              </div>
              <div className="text-[10px] text-slate-500 pt-2">
                Towbook garage — actual arrival time is unavailable (bulk-updated at midnight).
                PTA = promised time to member at dispatch. Based on {data.pts_ata.total?.toLocaleString()} completed SAs.
              </div>
            </>
          ) : (
            <div className="text-sm text-slate-500 py-4 text-center">
              No PTA data available for this period.
            </div>
          )}
        </div>

        {/* Acceptance Rates */}
        <div className="glass rounded-xl p-5 space-y-3">
          <h3 className="font-semibold text-slate-200 flex items-center gap-2">
            <Users className="w-4 h-4 text-brand-400" /> Dispatch Acceptance
          </h3>

          {/* Primary */}
          <div>
            <div className="flex justify-between items-center mb-1">
              <span className="text-xs text-slate-400 font-medium">Primary (Auto-Dispatched)</span>
              <span className={clsx('text-sm font-bold',
                data.acceptance.primary_pct >= 90 ? 'text-emerald-400' :
                data.acceptance.primary_pct >= 75 ? 'text-amber-400' : 'text-red-400')}>
                {data.acceptance.primary_pct}%
              </span>
            </div>
            <div className="h-3 bg-slate-900 rounded-full overflow-hidden">
              <div className={clsx('h-full rounded-full transition-all',
                data.acceptance.primary_pct >= 90 ? 'bg-emerald-500' :
                data.acceptance.primary_pct >= 75 ? 'bg-amber-500' : 'bg-red-500')}
                style={{ width: `${data.acceptance.primary_pct}%` }} />
            </div>
            <div className="text-[10px] text-slate-500 mt-0.5">
              {data.acceptance.primary_accepted} accepted / {data.acceptance.primary_total} auto-assigned
            </div>
          </div>

          {/* Not primary */}
          <div>
            <div className="flex justify-between items-center mb-1">
              <span className="text-xs text-slate-400 font-medium">Secondary (Manually Routed)</span>
              <span className={clsx('text-sm font-bold',
                data.acceptance.not_primary_pct >= 90 ? 'text-emerald-400' :
                data.acceptance.not_primary_pct >= 75 ? 'text-amber-400' : 'text-red-400')}>
                {data.acceptance.not_primary_pct}%
              </span>
            </div>
            <div className="h-3 bg-slate-900 rounded-full overflow-hidden">
              <div className={clsx('h-full rounded-full transition-all',
                data.acceptance.not_primary_pct >= 90 ? 'bg-emerald-500' :
                data.acceptance.not_primary_pct >= 75 ? 'bg-amber-500' : 'bg-red-500')}
                style={{ width: `${data.acceptance.not_primary_pct}%` }} />
            </div>
            <div className="text-[10px] text-slate-500 mt-0.5">
              {data.acceptance.not_primary_accepted} accepted / {data.acceptance.not_primary_total} manual
            </div>
          </div>

          <div className="pt-2 border-t border-slate-800/60 text-[10px] text-slate-500">
            Total facility declines this period: <span className="text-red-400 font-medium">{data.acceptance.total_declined}</span>
          </div>

          {/* Satisfaction mini */}
          {data.satisfaction && (
            <div className="pt-2 border-t border-slate-800/60 space-y-2">
              <div className="flex justify-between items-center">
                <span className="text-xs text-slate-400 font-medium">Total Satisfied</span>
                <span className={clsx('text-sm font-bold',
                  data.satisfaction.meets_target ? 'text-emerald-400' : 'text-amber-400')}>
                  {data.satisfaction.total_satisfied_pct}%
                  {data.satisfaction.meets_target
                    ? ' \u2713' : ` (need ${(82 - data.satisfaction.total_satisfied_pct).toFixed(1)}%\u2191)`}
                </span>
              </div>
              <div className="flex gap-1 text-[10px]">
                {[
                  { label: 'Totally Satisfied', count: data.satisfaction.totally_satisfied, color: 'bg-emerald-500' },
                  { label: 'Satisfied',          count: data.satisfaction.satisfied,          color: 'bg-teal-500' },
                  { label: 'Neither',            count: data.satisfaction.neither,            color: 'bg-slate-500' },
                  { label: 'Dissatisfied',       count: data.satisfaction.dissatisfied + data.satisfaction.totally_dissatisfied, color: 'bg-red-500' },
                ].map(s => (
                  <div key={s.label} className="flex-1 text-center">
                    <div className={clsx('h-1.5 rounded-full mb-1', s.color)} />
                    <div className="text-slate-400">{s.count}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Supervisor Analysis ──────────────────────────────────── */}
      <div className="glass rounded-xl p-5">
        <h3 className="font-bold text-slate-200 mb-4 flex items-center gap-2">
          <AlertTriangle className="w-5 h-5 text-amber-400" />
          Supervisor Analysis
          <span className="ml-auto text-xs font-normal text-slate-500">
            {label} · {data.total_sas.toLocaleString()} SAs
          </span>
        </h3>

        {/* Observations */}
        <div className="space-y-2 mb-5">
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-2">What the data shows</div>
          {insights.map((ins, i) => (
            <div key={i} className={clsx(
              'flex items-start gap-3 rounded-lg p-3 text-sm',
              ins.type === 'critical' ? 'bg-red-950/30 border border-red-800/30' :
              ins.type === 'warn'     ? 'bg-amber-950/30 border border-amber-800/30' :
              ins.type === 'info'     ? 'bg-brand-950/20 border border-brand-800/20' :
                                       'bg-emerald-950/20 border border-emerald-800/20'
            )}>
              {ins.type === 'critical' ? <XCircle className="w-4 h-4 text-red-400 mt-0.5 shrink-0" /> :
               ins.type === 'warn'     ? <AlertTriangle className="w-4 h-4 text-amber-400 mt-0.5 shrink-0" /> :
               ins.type === 'info'     ? <AlertTriangle className="w-4 h-4 text-brand-400 mt-0.5 shrink-0" /> :
                                        <CheckCircle2 className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" />}
              <span className={ins.type === 'critical' ? 'text-red-200' : ins.type === 'warn' ? 'text-amber-200' : ins.type === 'info' ? 'text-brand-200' : 'text-emerald-200'}>
                {ins.text}
              </span>
            </div>
          ))}
        </div>

        {/* Actions */}
        <div className="space-y-2">
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-2">What the supervisor should do</div>
          {actions.map((act, i) => (
            <div key={i} className={clsx(
              'flex items-start gap-3 rounded-lg p-3 text-sm border',
              act.priority === 'HIGH'     ? 'bg-red-950/20 border-red-800/30' :
              act.priority === 'MED'      ? 'bg-amber-950/20 border-amber-800/30' :
              act.priority === 'GOAL'     ? 'bg-brand-950/30 border-brand-700/40' :
                                           'bg-slate-800/30 border-slate-700/30'
            )}>
              <ArrowRight className={clsx('w-4 h-4 mt-0.5 shrink-0',
                act.priority === 'HIGH'   ? 'text-red-400' :
                act.priority === 'MED'    ? 'text-amber-400' :
                act.priority === 'GOAL'   ? 'text-brand-400' : 'text-slate-400')} />
              <div>
                <span className={clsx('text-[10px] font-bold uppercase tracking-wider mr-2',
                  act.priority === 'HIGH'   ? 'text-red-500' :
                  act.priority === 'MED'    ? 'text-amber-500' :
                  act.priority === 'GOAL'   ? 'text-brand-400' : 'text-slate-500')}>
                  {act.priority}
                </span>
                <span className="text-slate-300">{act.text}</span>
              </div>
            </div>
          ))}
        </div>

        {/* Path to 45-min ATA progress bar */}
        {data.response_time.median != null && (
          <div className="mt-5 pt-4 border-t border-slate-800/60">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold text-slate-300">Progress to 45-Min ATA Goal</span>
              <span className="text-xs text-slate-500">
                {data.response_time.under_45_pct}% of calls within target
              </span>
            </div>
            <div className="h-3 bg-slate-900 rounded-full overflow-hidden">
              <div className={clsx('h-full rounded-full transition-all',
                data.response_time.under_45_pct >= 80 ? 'bg-emerald-500' :
                data.response_time.under_45_pct >= 50 ? 'bg-amber-500' : 'bg-red-500')}
                style={{ width: `${data.response_time.under_45_pct}%` }} />
            </div>
            <div className="flex justify-between text-[10px] text-slate-500 mt-1">
              <span>0%</span>
              <span className="text-brand-400 font-medium">&#9650; Target: 80%+ of calls &le; 45 min</span>
              <span>100%</span>
            </div>
          </div>
        )}
      </div>
    </>
  )
}
