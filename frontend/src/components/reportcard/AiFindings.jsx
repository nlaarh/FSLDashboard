import { useEffect, useState } from 'react'
import { Sparkles, FileText, Loader2, Wrench, Lightbulb } from 'lucide-react'
import { fetchReportCardFindings } from '../../api'

const SEVERITY = {
  high: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
  medium: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  low: 'bg-slate-700/40 text-slate-300 border-slate-600/50',
}
const OWNER = { scheduler: 'Scheduler', process: 'Process', capacity: 'Capacity', driver: 'Driver' }

/** The model only ever sees D1, D2…; real names are put back here, for permitted users only. */
const unalias = (text, map) => (text || '').replace(/\bD\d+\b/g, a => map?.[a] || a)

function Finding({ f, i, res, active, onHighlight, onOpenSa }) {
  const key = `finding-${i}`
  return (
    <div onClick={() => onHighlight(key, f.evidence_sas || [])}
      className={`rounded-lg border p-3 cursor-pointer transition-colors flex flex-col gap-1.5 ${
        active === key ? 'border-brand-400/70 bg-brand-600/10' : 'border-slate-700/60 hover:bg-slate-800/40'}`}>
      <div className="text-[13px] font-semibold text-white leading-snug">{unalias(f.title, res.driver_map)}</div>
      <div className={`text-xs font-medium ${f.impact_minutes ? 'text-rose-300' : 'text-slate-400'}`}>
        {f.impact_minutes
          ? `Cost members ${f.impact_minutes.toLocaleString()} waiting minutes on ${f.late_calls} late call${f.late_calls === 1 ? '' : 's'}`
          : 'No member waited past the promised time on these calls'}
        {f.mostly_one_call && <span className="text-slate-400 font-normal"> · mostly one call ({f.mostly_one_call})</span>}
      </div>
      <div className="text-[11px] text-slate-300">{unalias(f.text, res.driver_map)}</div>
      {f.action && (
        <div className="flex gap-1.5 text-[11px] text-slate-100 mt-0.5">
          <Wrench className="w-3.5 h-3.5 shrink-0 mt-px text-brand-300" />
          <span><span className="font-semibold">{f.action.split(': ')[0]}:</span> {f.action.split(': ').slice(1).join(': ')}</span>
        </div>
      )}
      {f.config_cause && (
        <div className="flex gap-1.5 text-[10px] text-slate-500">
          <Lightbulb className="w-3 h-3 shrink-0 mt-px" />
          <span>Likely why (hypothesis): {unalias(f.config_cause, res.driver_map)}</span>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-1 mt-0.5">
        <span className={`text-[9px] px-1.5 py-0.5 rounded border ${SEVERITY[f.severity]}`}>{f.severity}</span>
        <span className="text-[9px] px-1.5 py-0.5 rounded border border-slate-600/60 text-slate-400">{OWNER[f.owner] || f.owner}</span>
        {[...(f.tags || []), f.lever_id].filter(Boolean).map(t => (
          <span key={t} className="text-[9px] px-1 py-0.5 rounded bg-slate-800/80 text-slate-500 font-mono">{t}</span>
        ))}
        <span className="flex-1" />
        {(f.evidence_sas || []).map(n => (
          <button key={n} onClick={e => { e.stopPropagation(); if (active !== key) onHighlight(key, f.evidence_sas); onOpenSa(n) }}
            className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 hover:bg-slate-700 hover:text-white">{n}</button>
        ))}
      </div>
    </div>
  )
}

/** Architecture 11: findings written only from the deterministic fact sheet (AI, else template). */
export default function AiFindings({ garage, date, rules, activeKey, onHighlight, onOpenSa }) {
  const [state, setState] = useState({ loading: true })
  useEffect(() => {
    let live = true
    setState({ loading: true })
    fetchReportCardFindings(garage, date, rules)
      .then(({ status, data }) => live && setState(status === 200 ? { res: data } : { error: data?.detail || `Findings unavailable (${status})` }))
      .catch(e => live && setState({ error: e.message }))
    return () => { live = false }
  }, [garage, date, rules])

  const res = state.res
  return (
    <div className="glass rounded-xl p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {res?.source === 'ai' ? <Sparkles className="w-4 h-4 text-brand-300" /> : <FileText className="w-4 h-4 text-slate-400" />}
        <span className="text-sm font-semibold text-white">Findings</span>
        {res && (
          <span className="text-[10px] px-1.5 py-0.5 rounded border border-slate-600/60 text-slate-400">
            {res.source === 'ai' ? `AI · ${res.model}` : res.validation.ai_configured ? 'Template (AI answer rejected)' : 'Template (no AI configured)'}
          </span>
        )}
        <span className="text-[10px] text-slate-500 ml-auto">Click a finding to highlight its calls on the Gantt</span>
      </div>
      {state.loading && <div className="flex items-center gap-2 text-xs text-slate-400"><Loader2 className="w-3.5 h-3.5 animate-spin" />Writing findings from the day's facts…</div>}
      {state.error && <div className="text-xs text-rose-300">{state.error}</div>}
      {res && (<>
        <div className="text-[15px] leading-relaxed text-slate-100">{unalias(res.headline, res.driver_map)}</div>
        <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-2">
          {res.findings.map((f, i) => (
            <Finding key={i} f={f} i={i} res={res} active={activeKey} onHighlight={onHighlight} onOpenSa={onOpenSa} />
          ))}
        </div>
        <div className="text-[10px] text-slate-500">
          Ordered by member impact: minutes members waited past their original promised arrival time on each finding's
          calls, counting a member who gave up to the time they cancelled (a call can appear in more than one finding). Every number was checked against the day's fact sheet
          ({res.fact_hash.slice(0, 8)}). Drivers are anonymised for the model. Causes are hypotheses, not proof.
        </div>
      </>)}
    </div>
  )
}
