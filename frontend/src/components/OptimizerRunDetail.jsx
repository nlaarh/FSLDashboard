import { useState, useEffect, Fragment } from 'react'
import { RefreshCw, ChevronDown, ChevronRight, Sparkles } from 'lucide-react'
import { optimizerGetRun, optimizerGetSA } from '../api'
import OptDecisionTree from './OptDecisionTree'

// SF/DuckDB timestamps come without a TZ suffix but represent UTC.
// JS new Date(iso) without 'Z' interprets as LOCAL time → wrong day/hour.
function parseUtc(iso) {
  if (!iso) return null
  return new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + 'Z')
}

function fmtTime(iso) {
  const d = parseUtc(iso)
  if (!d) return ''
  return d.toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

function fmtTravel(min) {
  if (min == null) return null
  return min < 60 ? `${Math.round(min)}m` : `${(min / 60).toFixed(1)}h`
}

function KpiChip({ label, before, after, positiveIsGood = true, fmt = v => v }) {
  if (before == null && after == null) return null
  const diff = (after ?? 0) - (before ?? 0)
  const improved = positiveIsGood ? diff > 0 : diff < 0
  const noChange = diff === 0
  const color = noChange ? 'text-slate-400' : improved ? 'text-emerald-400' : 'text-red-400'
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/50 border border-slate-700/40 text-[11px]">
      <span className="text-slate-500">{label}</span>
      {before != null && <span className="text-slate-500 font-mono">{fmt(before)}</span>}
      {before != null && <span className="text-slate-700">→</span>}
      <span className={`font-mono font-semibold ${color}`}>{fmt(after ?? 0)}</span>
      {!noChange && (
        <span className={`${color} opacity-70`}>({diff > 0 ? '+' : ''}{fmt(diff)})</span>
      )}
    </div>
  )
}

function buildVizData(decision, run) {
  if (!decision?.verdicts) return null
  const winner   = decision.verdicts.find(v => v.status === 'winner')
  const eligible = decision.verdicts.filter(v => v.status === 'eligible')
  // Group excluded drivers by reason — preserve full driver objects for rich rendering
  const excluded = {}
  for (const v of decision.verdicts.filter(v => v.status === 'excluded')) {
    const r = v.exclusion_reason || 'unknown'
    if (!excluded[r]) excluded[r] = []
    excluded[r].push(v)
  }
  return {
    visualization_type: 'decision_tree',
    sa_number:          decision.sa_number,
    sa_work_type:       decision.sa_work_type,
    territory_name:     run.territory_name,
    run_at:             decision.run_at,
    action:             decision.action,
    unscheduled_reason: decision.unscheduled_reason,
    winner,
    eligible,
    excluded,
    // Full verdict list — fed to the detail grid below the funnel
    all_verdicts: decision.verdicts,
  }
}

export default function OptimizerRunDetail({ run, onAskAI }) {
  const [detail, setDetail]           = useState(null)
  const [loading, setLoading]         = useState(false)
  const [expanded, setExpanded]       = useState(null)
  const [verdictCache, setVerdictCache] = useState({})
  const [loadingVerdicts, setLoadingVerdicts] = useState({})

  useEffect(() => {
    if (!run?.id) return
    setLoading(true)
    setExpanded(null)
    setVerdictCache({})
    optimizerGetRun(run.id)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setLoading(false))
  }, [run?.id])

  const handleRowClick = async (d) => {
    const sa = d.sa_number
    if (expanded === sa) { setExpanded(null); return }
    setExpanded(sa)
    if (verdictCache[sa]) return

    setLoadingVerdicts(prev => ({ ...prev, [sa]: true }))
    try {
      const runs = await optimizerGetSA(sa, 10)
      const match = runs.find(r => r.run_id === run.id)
      if (match) setVerdictCache(prev => ({ ...prev, [sa]: match }))
    } catch { /* ignore */ } finally {
      setLoadingVerdicts(prev => ({ ...prev, [sa]: false }))
    }
  }

  if (!run) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3 text-center px-6">
        <div className="w-10 h-10 rounded-xl bg-slate-800/60 border border-slate-700/40 flex items-center justify-center">
          <ChevronRight size={18} className="text-slate-600" />
        </div>
        <p className="text-slate-500 text-sm">Select a run from the left</p>
        <p className="text-slate-600 text-xs">Click any run to see its SA decisions</p>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center gap-2 text-slate-500 text-sm">
        <RefreshCw size={15} className="animate-spin" />Loading decisions…
      </div>
    )
  }

  const { run: r, decisions = [] } = detail || {}
  const scheduled   = decisions.filter(d => d.action === 'Scheduled').length
  const unscheduled = decisions.filter(d => d.action === 'Unscheduled').length
  const unchanged   = decisions.filter(d => d.action === 'Unchanged').length

  // Format helpers for the rich header
  const fmtSec = (s) => s == null ? '—' : s < 60 ? `${s}s` : s < 3600 ? `${Math.round(s/60)}m` : `${(s/3600).toFixed(1)}h`
  const fmtMeters = (m) => m == null ? '—' : m < 1000 ? `${m}m` : `${(m/1000).toFixed(1)}km`

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Run header — name + policy + chunk + KPI rows */}
      <div className="px-4 py-3 bg-slate-800/60 border-b border-slate-700/40 shrink-0">
        <div className="flex items-center gap-2 mb-2">
          <span className="font-semibold text-sm text-white truncate">{run.name || run.id}</span>
          {r?.fsl_type && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-600/20 text-indigo-300 border border-indigo-500/25">
              {r.fsl_type}
            </span>
          )}
          {r?.fsl_status && (
            <span className={`text-[10px] px-1.5 py-0.5 rounded border ${
              r.fsl_status === 'Completed' ? 'bg-emerald-600/15 text-emerald-300 border-emerald-500/25' :
              r.fsl_status === 'Aborted' ? 'bg-red-600/15 text-red-300 border-red-500/25' :
              'bg-slate-700/40 text-slate-300 border-slate-600/30'
            }`}>{r.fsl_status}</span>
          )}
          {r?.chunk_num != null && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-600/15 text-amber-300 border border-amber-500/25" title={`Chunk ${r.chunk_num} of batch ${r.batch_id}`}>
              chunk #{r.chunk_num}
            </span>
          )}
          <span className="text-[11px] text-slate-500 shrink-0 ml-auto">{fmtTime(run.run_at)}</span>
          <button
            onClick={() => onAskAI?.(run)}
            className="ml-2 flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-lg bg-brand-600/20 hover:bg-brand-600/30 text-brand-300 border border-brand-500/25 transition-colors shrink-0"
          >
            <Sparkles size={10} />Ask AI
          </button>
        </div>

        {/* Policy + objectives summary */}
        {r && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mb-2 text-[11px] text-slate-400">
            <span>Policy: <span className="text-slate-200 font-medium">{r.policy_name || '—'}</span></span>
            {r.commit_mode && <span>Commit: <span className="text-slate-300">{r.commit_mode}</span></span>}
            {r.daily_optimization && <span className="text-emerald-400">Daily Opt ✓</span>}
            <span>Objectives: <span className="text-slate-200">{r.objectives_count ?? '—'}</span></span>
            <span>Work Rules: <span className="text-slate-200">{r.work_rules_count ?? '—'}</span></span>
            <span>Skills: <span className="text-slate-200">{r.skills_count ?? '—'}</span></span>
            <span>Resources: <span className="text-slate-200">{r.resources_count}</span></span>
            <span>Services: <span className="text-slate-200">{r.services_count}</span></span>
          </div>
        )}

        {/* KPI chips: scheduling, travel, response time, commute, extraneous */}
        {r && (
          <div className="flex gap-2 flex-wrap">
            <KpiChip label="Scheduled"   before={r.pre_scheduled}  after={r.post_scheduled} positiveIsGood={true} />
            <KpiChip label="Unscheduled" before={null}             after={r.unscheduled_count} positiveIsGood={false} />
            {r.pre_travel_time_s != null && (
              <KpiChip label="Total travel" before={Math.round(r.pre_travel_time_s/60)} after={Math.round(r.post_travel_time_s/60)} positiveIsGood={false} fmt={v => `${v}m`} />
            )}
            {r.pre_response_avg_s != null && (
              <KpiChip label="Avg response (non-appt)" before={Math.round(r.pre_response_avg_s)} after={Math.round(r.post_response_avg_s)} positiveIsGood={false} fmt={v => `${v}s`} />
            )}
            {r.post_response_appt_s != null && r.post_response_appt_s > 0 && (
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/50 border border-slate-700/40 text-[11px]">
                <span className="text-slate-500">Avg response (appt)</span>
                <span className="font-mono font-semibold text-slate-200">{Math.round(r.post_response_appt_s)}s</span>
              </div>
            )}
            {r.post_extraneous_time_s != null && r.post_extraneous_time_s > 0 && (
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/50 border border-slate-700/40 text-[11px]">
                <span className="text-slate-500">Extraneous (gaps)</span>
                <span className="font-mono font-semibold text-amber-300">{fmtSec(r.post_extraneous_time_s)}</span>
              </div>
            )}
            {(r.post_start_commute_dist || r.post_end_commute_dist) ? (
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/50 border border-slate-700/40 text-[11px]">
                <span className="text-slate-500">Commute</span>
                <span className="font-mono text-slate-300">start {fmtMeters(r.post_start_commute_dist)}</span>
                <span className="text-slate-700">·</span>
                <span className="font-mono text-slate-300">end {fmtMeters(r.post_end_commute_dist)}</span>
              </div>
            ) : null}
          </div>
        )}
      </div>

      {/* SA decisions table */}
      <div className="flex-1 overflow-y-auto">
        {decisions.length === 0 ? (
          <div className="text-center py-10 text-slate-500 text-xs">No SA decisions recorded for this run</div>
        ) : (
          <table className="w-full text-xs">
            <thead className="sticky top-0 z-10">
              <tr className="border-b border-slate-800/60 bg-slate-900/90 backdrop-blur-sm">
                <th className="text-left px-4 py-2 text-slate-500 font-medium">SA #</th>
                <th className="text-right px-2 py-2 text-slate-500 font-medium">Pri</th>
                <th className="text-right px-2 py-2 text-slate-500 font-medium">Dur</th>
                <th className="text-left px-2 py-2 text-slate-500 font-medium">SA Status</th>
                <th className="text-left px-2 py-2 text-slate-500 font-medium">Skills Req</th>
                <th className="text-left px-2 py-2 text-slate-500 font-medium">Result</th>
                <th className="text-left px-2 py-2 text-slate-500 font-medium">Winner</th>
                <th className="text-right px-4 py-2 text-slate-500 font-medium">Travel</th>
              </tr>
            </thead>
            <tbody>
              {decisions.map(d => {
                const isOpen  = expanded === d.sa_number
                const cached  = verdictCache[d.sa_number]
                const busy    = loadingVerdicts[d.sa_number]
                const vizData = cached ? buildVizData(cached, run) : null

                return (
                  <Fragment key={d.sa_number}>
                    <tr
                      className={`border-b border-slate-800/40 cursor-pointer transition-colors
                        ${isOpen ? 'bg-slate-800/50' : 'hover:bg-slate-800/25'}`}
                      onClick={() => handleRowClick(d)}
                    >
                      <td className="px-4 py-2.5">
                        <span className="flex items-center gap-1.5 font-mono text-indigo-300">
                          {isOpen
                            ? <ChevronDown size={11} className="text-slate-400 shrink-0" />
                            : <ChevronRight size={11} className="text-slate-500 shrink-0" />
                          }
                          {d.sa_number}
                        </span>
                      </td>
                      <td className="px-2 py-2.5 text-right font-mono text-slate-300">
                        {d.priority != null ? d.priority : '—'}
                      </td>
                      <td className="px-2 py-2.5 text-right font-mono text-slate-400">
                        {d.duration_min != null ? `${Math.round(d.duration_min)}m` : '—'}
                      </td>
                      <td className="px-2 py-2.5 text-slate-400 text-[11px]">
                        {d.sa_status || '—'}
                      </td>
                      <td className="px-2 py-2.5 max-w-[160px]">
                        {d.required_skills ? (
                          <span className="text-[10px] text-slate-300 line-clamp-1" title={d.required_skills}>
                            {d.required_skills}
                          </span>
                        ) : <span className="text-slate-600">—</span>}
                      </td>
                      <td className="px-2 py-2.5">
                        {d.action === 'Scheduled' ? (
                          <span className="text-emerald-400 font-medium">Scheduled</span>
                        ) : d.action === 'Unscheduled' ? (
                          <span className="text-amber-400 font-medium">Unscheduled</span>
                        ) : d.action === 'Unchanged' ? (
                          <span className="text-slate-500" title="Optimizer kept the existing assignment — no deliberation this run">No Change</span>
                        ) : (
                          <span className="text-slate-400">{d.action}</span>
                        )}
                        {d.unscheduled_reason && (
                          <div className="text-[10px] text-slate-600 mt-0.5 max-w-[130px] truncate" title={d.unscheduled_reason}>
                            {d.unscheduled_reason}
                          </div>
                        )}
                      </td>
                      <td className="px-2 py-2.5 text-slate-300 max-w-[110px] truncate">
                        {d.winner_driver_name || <span className="text-slate-600">—</span>}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-slate-400">
                        {d.winner_travel_time_min != null
                          ? fmtTravel(d.winner_travel_time_min)
                          : <span className="text-slate-600">—</span>
                        }
                      </td>
                    </tr>
                    {isOpen && (
                      <tr>
                        <td colSpan={8} className="px-4 pb-4 pt-1 bg-slate-900/40">
                          {busy
                            ? <div className="flex items-center gap-2 py-3 text-slate-500 text-[11px]">
                                <RefreshCw size={11} className="animate-spin" />Loading driver verdicts…
                              </div>
                            : vizData
                              ? <OptDecisionTree data={vizData} />
                              : <div className="text-[11px] text-slate-600 py-3">No verdict data found for this run</div>
                          }
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Footer summary */}
      {decisions.length > 0 && (
        <div className="px-4 py-2 border-t border-slate-800/60 bg-slate-900/30 shrink-0 flex gap-4 text-[11px]">
          <span className="text-emerald-400 font-medium">{scheduled} scheduled</span>
          {unscheduled > 0 && <span className="text-amber-400 font-medium">{unscheduled} unscheduled</span>}
          {unchanged > 0 && <span className="text-slate-500">{unchanged} unchanged</span>}
          <span className="text-slate-600">{decisions.length} total</span>
        </div>
      )}
    </div>
  )
}
