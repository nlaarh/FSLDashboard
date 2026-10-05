import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { X, Loader2, User, Cog, MessageSquare, Mail, ListChecks, FolderOpen } from 'lucide-react'
import { loadCaseTrail } from './prefetch'

const TYPE = { ERS_KMI_Alerts: 'KMI alert', Feedback_Record_Type: 'Customer feedback' }
const when = iso => iso ? new Date(iso).toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit' }) : ''
const ICON = { comment: MessageSquare, email: Mail, task: ListChecks }

/** Every case on one work order, and for the chosen case each touch in order: when, who (person or system) and what. */
export default function CaseTrailPanel({ woId, number, onClose }) {
  const [state, setState] = useState({ phase: 'loading' })
  const [pick, setPick] = useState(null)
  const [peopleOnly, setPeopleOnly] = useState(false)
  useEffect(() => {
    let live = true
    setState({ phase: 'loading' })
    loadCaseTrail(woId)
      .then(({ status, data }) => live && setState(status === 200 ? { phase: 'ready', cases: data.cases || [] } : { phase: 'error', error: data?.detail || `Cases unavailable (${status})` }))
      .catch(e => live && setState({ phase: 'error', error: e.message }))
    return () => { live = false }
  }, [woId])
  useEffect(() => { if (state.phase === 'ready' && state.cases.length) setPick(p => p || (state.cases.find(c => !c.closed) || state.cases[0]).id) }, [state])
  useEffect(() => { const k = e => e.key === 'Escape' && onClose(); window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [onClose])

  const cases = state.phase === 'ready' ? state.cases : []
  const chosen = cases.find(c => c.id === pick)
  const events = useMemo(() => (chosen ? chosen.events.filter(e => !peopleOnly || e.kind === 'person') : []), [chosen, peopleOnly])
  const people = chosen ? new Set(chosen.events.filter(e => e.kind === 'person').map(e => e.name)).size : 0

  return createPortal(
    <div className="fixed inset-0 z-[2000] flex justify-end bg-black/50" onClick={onClose}>
      <div className="w-full max-w-xl h-full bg-slate-950 border-l border-slate-700 overflow-y-auto" onClick={e => e.stopPropagation()}>
        <div className="sticky top-0 z-10 bg-slate-950 border-b border-slate-800 px-4 py-3 flex items-center gap-2">
          <FolderOpen className="w-4 h-4 text-amber-400" />
          <div className="text-sm font-semibold text-white">Cases{number ? ` · ${number}` : ''}</div>
          <button onClick={onClose} className="ml-auto text-slate-400 hover:text-white" aria-label="Close"><X className="w-5 h-5" /></button>
        </div>
        {state.phase === 'loading' && <div className="p-10 flex justify-center"><Loader2 className="w-6 h-6 text-brand-400 animate-spin" /></div>}
        {state.phase === 'error' && <div className="p-6 text-sm text-rose-400">{state.error}</div>}
        {state.phase === 'ready' && !cases.length && <div className="p-6 text-sm text-slate-400">This work order has no cases.</div>}
        {cases.length > 0 && (
          <div className="p-4 space-y-4">
            <div className="space-y-2">
              {cases.map(c => (
                <button key={c.id} onClick={() => setPick(c.id)}
                  className={`w-full text-left rounded-lg border px-3 py-2 ${pick === c.id ? 'border-brand-500 bg-brand-600/10' : 'border-slate-800 hover:bg-slate-900'}`}>
                  <div className="flex items-center gap-2 text-xs">
                    <span className="font-semibold text-white">Case {c.number}</span>
                    <span className="text-slate-400">{TYPE[c.type] || c.type || ''}</span>
                    <span className={`ml-auto px-1.5 rounded text-[10px] font-bold ${c.closed ? 'bg-slate-700 text-slate-300' : 'bg-amber-500/20 text-amber-300'}`}>{c.status}</span>
                  </div>
                  {(c.alert || c.subject) && <div className="text-[11px] text-slate-300 mt-0.5 truncate">{c.alert || c.subject}</div>}
                  <div className="text-[11px] text-slate-500 mt-0.5">Owner: {c.owner || 'nobody'} · opened by {c.created_by} · {when(c.created)}</div>
                </button>
              ))}
            </div>
            {chosen && (
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <div className="text-xs font-semibold text-slate-200">Who touched case {chosen.number}</div>
                  <div className="text-[11px] text-slate-500">{chosen.events.length} events · {people} {people === 1 ? 'person' : 'people'}</div>
                  <label className="ml-auto text-[11px] text-slate-400 flex items-center gap-1 cursor-pointer"><input type="checkbox" checked={peopleOnly} onChange={e => setPeopleOnly(e.target.checked)} />People only</label>
                </div>
                <ol className="relative border-l border-slate-800 ml-2 space-y-2.5">
                  {events.map((e, i) => {
                    const Icon = ICON[e.type] || (e.kind === 'person' ? User : Cog)
                    return (
                      <li key={i} className="ml-4">
                        <span className={`absolute -left-[7px] mt-1 w-3.5 h-3.5 rounded-full flex items-center justify-center ${e.kind === 'person' ? 'bg-emerald-500/30 text-emerald-300' : 'bg-slate-700 text-slate-400'}`}><Icon className="w-2.5 h-2.5" /></span>
                        <div className="text-[11px] text-slate-500">{when(e.ts)}</div>
                        <div className="text-xs text-white"><b>{e.name}</b> <span className={`ml-1 px-1 rounded text-[9px] font-bold ${e.kind === 'person' ? 'bg-emerald-500/15 text-emerald-300' : 'bg-slate-700 text-slate-300'}`}>{e.kind === 'person' ? 'PERSON' : 'SYSTEM'}</span>{e.profile && <span className="ml-1 text-[10px] text-slate-600">{e.profile}</span>}</div>
                        <div className="text-xs text-slate-300">{e.text}</div>
                        {e.snippet && <div className="text-[11px] text-slate-500 mt-0.5 italic">{e.snippet}</div>}
                      </li>
                    )
                  })}
                  {!events.length && <li className="ml-4 text-xs text-slate-500">No events to show.</li>}
                </ol>
              </div>
            )}
          </div>
        )}
      </div>
    </div>,
    document.body)
}
