import React, { useState, useEffect, useMemo } from 'react'
import { clsx } from 'clsx'
import { Loader2, AlertTriangle, Clock, ArrowLeft, ArrowRight, ChevronRight, TrendingDown, TrendingUp } from 'lucide-react'
import { fetchSatisfactionDay } from '../api'
import SALink from '../components/SALink'
import { SatisfactionGarageMap } from './SatisfactionView'

export default function SatisfactionDayDetail({ date, onBack, onGarage }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    setLoading(true)
    fetchSatisfactionDay(date)
      .then(setData)
      .catch(e => setError(e.response?.data?.detail || e.message || 'Failed'))
      .finally(() => setLoading(false))
  }, [date])

  const dayLabel = new Date(date + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })

  const satBadge = (val) => {
    if (!val) return null
    const v = val.toLowerCase()
    const color = v === 'totally satisfied' ? 'bg-emerald-950/50 text-emerald-400 border-emerald-800/30' :
                  v === 'satisfied' ? 'bg-green-950/50 text-green-400 border-green-800/30' :
                  v.includes('neither') ? 'bg-slate-800 text-slate-400 border-slate-700/30' :
                  v === 'dissatisfied' ? 'bg-amber-950/50 text-amber-400 border-amber-800/30' :
                  'bg-red-950/50 text-red-400 border-red-800/30'
    return <span className={clsx('text-[9px] px-1.5 py-0.5 rounded border font-medium', color)}>{val}</span>
  }

  if (loading) return (
    <div className="max-w-5xl mx-auto flex items-center justify-center py-20">
      <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
      <span className="ml-2 text-sm text-slate-500">Analyzing {dayLabel}...</span>
    </div>
  )
  if (error) return <div className="max-w-5xl mx-auto text-center text-red-400 py-10 text-sm">{error}</div>

  const s = data?.summary || {}
  const insights = data?.insights || []
  const allGarages = data?.garage_breakdown || []
  const garagesWithSurveys = allGarages.filter(g => g.surveys > 0)
  const problems = data?.problem_surveys || []
  const longAta = data?.long_ata_sas || []
  const cancels = data?.cancel_reasons || []

  // Tier grouping for visual scorecard
  const tiers = {
    excellent: { label: 'Excellent', range: '90-100%', textCls: 'text-emerald-400', bg: 'bg-emerald-500', border: 'border-emerald-500/30', garages: garagesWithSurveys.filter(g => g.tier === 'excellent') },
    ok:        { label: 'On Target', range: '82-89%',  textCls: 'text-blue-400',    bg: 'bg-blue-500',    border: 'border-blue-500/30',    garages: garagesWithSurveys.filter(g => g.tier === 'ok') },
    below:     { label: 'Below Target', range: '60-81%', textCls: 'text-amber-400', bg: 'bg-amber-500',   border: 'border-amber-500/30',   garages: garagesWithSurveys.filter(g => g.tier === 'below') },
    critical:  { label: 'Critical', range: '<60%',    textCls: 'text-red-400',     bg: 'bg-red-500',      border: 'border-red-500/30',     garages: garagesWithSurveys.filter(g => g.tier === 'critical') },
  }

  const metTarget = s.totally_satisfied_pct != null && s.totally_satisfied_pct >= 82

  return (
    <div className="max-w-5xl mx-auto space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="p-1.5 rounded-lg hover:bg-slate-800/60 transition text-slate-400 hover:text-white">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div className="flex-1">
          <div className="text-base font-bold text-white">{dayLabel}</div>
          <div className="text-[11px] text-slate-500">Satisfaction Day Report</div>
        </div>
        {/* Big score badge */}
        <div className={clsx('px-5 py-2 rounded-xl text-center border',
          metTarget ? 'bg-emerald-950/30 border-emerald-500/30' : 'bg-red-950/30 border-red-500/30'
        )}>
          <div className={clsx('text-2xl font-black', metTarget ? 'text-emerald-400' : 'text-red-400')}>
            {s.totally_satisfied_pct != null ? `${s.totally_satisfied_pct}%` : '--'}
          </div>
          <div className={clsx('text-[9px] uppercase font-semibold', metTarget ? 'text-emerald-500/70' : 'text-red-500/70')}>
            {metTarget ? 'Target Met' : 'Below 82% Target'}
          </div>
        </div>
      </div>

      {/* Executive Summary */}
      <div className={clsx('glass rounded-xl border p-5', metTarget ? 'border-emerald-800/20' : 'border-red-800/20')}>
        <div className="text-xs font-bold text-white uppercase tracking-wide mb-3">Executive Summary</div>
        <div className="text-sm text-slate-300 leading-relaxed space-y-2">
          {/* Survey results narrative */}
          <p>
            {s.totally_satisfied_pct != null && s.totally_satisfied_pct < 82
              ? <><span className="text-red-400 font-semibold">{s.totally_satisfied_pct}%</span> of {s.total_surveys} survey responses for calls made this day were Totally Satisfied — <span className="text-red-400 font-semibold">{82 - s.totally_satisfied_pct} points below</span> the 82% AAA target. {s.dissatisfied_count > 0 && <><span className="text-red-400 font-semibold">{s.dissatisfied_count}</span> members reported dissatisfaction.</>}</>
              : <><span className="text-emerald-400 font-semibold">{s.totally_satisfied_pct}%</span> of {s.total_surveys} survey responses for calls made this day were Totally Satisfied — meeting the 82% AAA accreditation target.</>
            }
          </p>
          {/* Same-day operations context */}
          <p className="text-slate-400">
            <span className="text-slate-500 text-[11px] uppercase font-semibold">Same-day operations:</span>{' '}
            <span className="text-white font-medium">{s.total_sas?.toLocaleString()}</span> new service calls created with{' '}
            <span className={clsx('font-medium', (s.completion_pct || 0) >= 85 ? 'text-emerald-400' : 'text-amber-400')}>{s.completion_pct}%</span> completion rate.
            {s.cancelled > 0 && <> <span className="text-red-400 font-medium">{s.cancelled}</span> cancelled.</>}
            {s.avg_ata != null && <> Avg response time <span className={clsx('font-medium', s.avg_ata <= 45 ? 'text-emerald-400' : 'text-amber-400')}>{s.avg_ata}m</span>.</>}
            {s.sla_pct != null && <> 45-min SLA: <span className={clsx('font-medium', s.sla_pct >= 50 ? 'text-emerald-400' : 'text-red-400')}>{s.sla_pct}%</span> ({s.sla_hits}/{s.sla_eligible}).</>}
          </p>
          {/* ATA distribution */}
          {s.ata_under_30 != null && s.sla_eligible > 0 && (
            <div className="flex items-center gap-3 mt-1">
              <span className="text-[10px] text-slate-500 w-24">Response Time:</span>
              <div className="flex-1 flex h-5 rounded-lg overflow-hidden text-[9px] font-bold">
                {s.ata_under_30 > 0 && <div className="bg-emerald-600 flex items-center justify-center text-white" style={{ width: `${100 * s.ata_under_30 / s.sla_eligible}%` }}>{s.ata_under_30 > 3 ? `<30m (${s.ata_under_30})` : ''}</div>}
                {s.ata_30_45 > 0 && <div className="bg-emerald-800 flex items-center justify-center text-emerald-200" style={{ width: `${100 * s.ata_30_45 / s.sla_eligible}%` }}>{s.ata_30_45 > 3 ? `30-45m (${s.ata_30_45})` : ''}</div>}
                {s.ata_45_60 > 0 && <div className="bg-amber-700 flex items-center justify-center text-amber-100" style={{ width: `${100 * s.ata_45_60 / s.sla_eligible}%` }}>{s.ata_45_60 > 3 ? `45-60m (${s.ata_45_60})` : ''}</div>}
                {s.ata_over_60 > 0 && <div className="bg-red-700 flex items-center justify-center text-red-100" style={{ width: `${100 * s.ata_over_60 / s.sla_eligible}%` }}>{s.ata_over_60 > 3 ? `>60m (${s.ata_over_60})` : ''}</div>}
              </div>
            </div>
          )}
          {/* Survey distribution */}
          {s.total_surveys > 0 && (
            <div className="flex items-center gap-3 mt-1">
              <span className="text-[10px] text-slate-500 w-24 shrink-0">Survey Scores:</span>
              <div className="flex-1 flex h-6 rounded-lg overflow-hidden text-[9px] font-bold">
                {[
                  { count: s.totally_satisfied_count, label: 'Totally Sat', bg: 'bg-emerald-600', text: 'text-white' },
                  { count: s.satisfied_count, label: 'Sat', bg: 'bg-green-700', text: 'text-green-100' },
                  { count: s.neither_count, label: 'Neutral', bg: 'bg-slate-600', text: 'text-slate-200' },
                  { count: s.dissatisfied_count, label: 'Dissat', bg: 'bg-red-700', text: 'text-red-100' },
                ].filter(seg => seg.count > 0).map(seg => {
                  const pct = 100 * seg.count / s.total_surveys
                  return (
                    <div key={seg.label} className={clsx(seg.bg, seg.text, 'flex items-center justify-center overflow-hidden whitespace-nowrap px-1')}
                      style={{ width: `${Math.max(pct, 4)}%` }}
                      title={`${seg.label}: ${seg.count} (${Math.round(pct)}%)`}>
                      {pct > 8 ? `${seg.label} (${seg.count})` : seg.count}
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>

        {/* Insight pills */}
        {insights.length > 0 && (
          <div className="mt-4 pt-3 border-t border-slate-800/50 space-y-1.5">
            {insights.map((ins, i) => (
              <div key={i} className={clsx('text-xs px-3 py-2 rounded-lg',
                ins.type === 'critical' ? 'bg-red-950/30 text-red-300' :
                ins.type === 'warning' ? 'bg-amber-950/30 text-amber-300' :
                ins.type === 'success' ? 'bg-emerald-950/30 text-emerald-300' :
                'bg-blue-950/30 text-blue-300'
              )}>
                {ins.text}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Garage Leaders vs Laggards — two-column executive view */}
      {garagesWithSurveys.length >= 2 && <GarageLeaderboard garages={garagesWithSurveys} onGarage={onGarage} />}

      {/* Customer Voice — dissatisfied comments first */}
      {problems.length > 0 && (
        <div className="glass rounded-xl border border-red-800/20 p-5">
          <div className="text-xs font-bold text-white uppercase tracking-wide mb-3">
            Voice of the Customer
            <span className="text-red-400 font-normal normal-case ml-2">{problems.length} dissatisfied responses</span>
          </div>
          <div className="space-y-2">
            {problems.filter(sv => sv.comment).map((sv, i) => (
              <div key={i} className="bg-slate-900/40 rounded-lg p-3 space-y-1.5 border-l-2 border-red-500/40">
                <div className="flex items-center gap-2 flex-wrap text-[10px]">
                  <span className="text-slate-500 truncate max-w-[200px]">{sv.garage}</span>
                  {sv.sa_number && <SALink number={sv.sa_number} style={{ fontFamily: 'monospace', fontSize: 10 }} />}
                  {sv.call_date && <span className="text-slate-600">Call: {sv.call_date}</span>}
                  {sv.driver && <span className="text-slate-500">{sv.driver}</span>}
                  {!sv.sa_number && sv.wo_number && <span className="text-slate-600 font-mono">WO {sv.wo_number}</span>}
                  <div className="flex items-center gap-1.5 ml-auto">
                    {satBadge(sv.overall)}
                  </div>
                </div>
                <div className="text-xs text-slate-300 italic leading-relaxed pl-1">"{sv.comment}"</div>
              </div>
            ))}
            {problems.filter(sv => !sv.comment).length > 0 && (
              <div className="text-[10px] text-slate-600 pt-1">+ {problems.filter(sv => !sv.comment).length} dissatisfied responses without comments</div>
            )}
          </div>
        </div>
      )}

      {/* Garage Performance Map */}
      {garagesWithSurveys.length > 0 && (
        <div className="glass rounded-xl border border-slate-700/30 p-4 space-y-3">
          <div className="text-xs font-bold text-white uppercase tracking-wide">Garage Performance Map</div>
          <SatisfactionGarageMap garages={allGarages} onGarage={onGarage} />
        </div>
      )}

      {/* Slow Responses */}
      {longAta.length > 0 && (
        <div className="glass rounded-xl border border-amber-800/20 p-5">
          <div className="text-xs font-bold text-white uppercase tracking-wide mb-3">
            Slow Responses
            <span className="text-amber-400 font-normal normal-case ml-2">{longAta.length} calls over 60 minutes</span>
          </div>
          <div className="space-y-0.5 max-h-[300px] overflow-y-auto">
            {longAta.map((sa, i) => (
              <div key={i} className="flex items-center gap-3 px-3 py-1.5 rounded-lg text-[11px] bg-slate-900/30">
                {sa.number && <SALink number={sa.number} style={{ fontFamily: 'monospace', fontSize: 10 }} />}
                <span className="text-slate-400 flex-1 truncate">{sa.garage}</span>
                <span className="text-slate-500">{sa.work_type}</span>
                <span className={clsx('font-bold', sa.ata_min > 90 ? 'text-red-400' : 'text-amber-400')}>{sa.ata_min}m</span>
                <span className={clsx('text-[9px] px-1 py-0.5 rounded',
                  sa.dispatch_method === 'Field Services' ? 'bg-blue-950/40 text-blue-400' : 'bg-fuchsia-950/40 text-fuchsia-400'
                )}>{sa.dispatch_method === 'Field Services' ? 'Fleet' : 'TB'}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Cancellation Reasons */}
      {cancels.length > 0 && (
        <div className="glass rounded-xl border border-slate-700/30 p-5">
          <div className="text-xs font-bold text-white uppercase tracking-wide mb-3">Cancellation Breakdown</div>
          <div className="flex gap-3 flex-wrap">
            {cancels.map((cr, i) => (
              <div key={i} className="bg-slate-900/40 rounded-lg px-3 py-2 text-center border border-slate-800/50">
                <div className="text-lg font-bold text-red-400">{cr.count}</div>
                <div className="text-[9px] text-slate-500 max-w-[120px] truncate">{cr.reason}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Two-column: Worst (left) vs Best (right) garages ────────────────────────
function GarageLeaderboard({ garages, onGarage }) {
  // Bottom: lowest sat %, must have ≥2 surveys to be meaningful
  const qualified = garages.filter(g => g.totally_satisfied_pct != null && g.surveys >= 2)
  const bottom = qualified
    .filter(g => g.totally_satisfied_pct < 82)
    .sort((a, b) => a.totally_satisfied_pct - b.totally_satisfied_pct)
    .slice(0, 5)
  const top = qualified
    .filter(g => g.totally_satisfied_pct >= 82)
    .sort((a, b) => b.totally_satisfied_pct - a.totally_satisfied_pct)
    .slice(0, 5)

  if (!bottom.length && !top.length) return null

  const shortName = (n) => n.includes(' - ') ? n.split(' - ').slice(1).join(' - ').trim() : n

  const StatRow = ({ g, isBottom }) => (
    <button onClick={() => onGarage?.(g.name)}
      className={clsx('w-full flex items-center gap-2 px-3 py-2 rounded-lg text-left transition group',
        isBottom ? 'hover:bg-red-950/20' : 'hover:bg-emerald-950/20'
      )}>
      <div className={clsx('text-lg font-black w-12 text-right',
        isBottom ? 'text-red-400' : 'text-emerald-400'
      )}>{g.totally_satisfied_pct}%</div>
      <div className="flex-1 min-w-0">
        <div className="text-[11px] font-semibold text-white truncate group-hover:underline">{shortName(g.name)}</div>
        <div className="flex items-center gap-3 text-[9px] text-slate-500 mt-0.5">
          <span>{g.sa_completed ?? g.sa_total ?? 0} SAs</span>
          <span className={clsx(g.avg_ata != null && g.avg_ata > 45 ? 'text-amber-400' : '')}>{g.avg_ata != null ? `${g.avg_ata}m ATA` : ''}</span>
          {(g.sa_declined ?? 0) > 0 && <span className="text-red-400">{g.sa_declined} declined</span>}
          {(g.sa_cancelled ?? 0) > 0 && <span className="text-red-400/60">{g.sa_cancelled} cancelled</span>}
          <span>{g.surveys} surveys</span>
        </div>
      </div>
      <ChevronRight className="w-3.5 h-3.5 text-slate-700 group-hover:text-slate-400 flex-shrink-0" />
    </button>
  )

  return (
    <div className="grid grid-cols-2 gap-4">
      {/* LEFT — Worst performing */}
      <div className="glass rounded-xl border border-red-800/20 p-4">
        <div className="flex items-center gap-2 mb-3">
          <TrendingDown className="w-4 h-4 text-red-400" />
          <span className="text-xs font-bold text-red-400 uppercase tracking-wide">Dragging Score Down</span>
        </div>
        {bottom.length === 0 ? (
          <div className="text-xs text-slate-600 text-center py-4">All garages met target</div>
        ) : (
          <div className="space-y-0.5">
            {bottom.map(g => <StatRow key={g.name} g={g} isBottom />)}
          </div>
        )}
      </div>
      {/* RIGHT — Top performing */}
      <div className="glass rounded-xl border border-emerald-800/20 p-4">
        <div className="flex items-center gap-2 mb-3">
          <TrendingUp className="w-4 h-4 text-emerald-400" />
          <span className="text-xs font-bold text-emerald-400 uppercase tracking-wide">Driving Score Up</span>
        </div>
        {top.length === 0 ? (
          <div className="text-xs text-slate-600 text-center py-4">No garages above target</div>
        ) : (
          <div className="space-y-0.5">
            {top.map(g => <StatRow key={g.name} g={g} isBottom={false} />)}
          </div>
        )}
      </div>
    </div>
  )
}
