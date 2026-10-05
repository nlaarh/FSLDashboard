import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { X, Loader2, User, Cog, MessageSquare, Mail, ListChecks, FolderOpen, StickyNote } from 'lucide-react'
import { loadCaseTrail } from './prefetch'

const TYPE = { ERS_KMI_Alerts: 'KMI alert', Feedback_Record_Type: 'Customer feedback' }
const when = iso => iso ? new Date(iso).toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit' }) : ''
const ICON = { note: StickyNote, comment: MessageSquare, email: Mail, task: ListChecks }
const VIEWS = [['both', 'Both'], ['human', 'Human'], ['automatic', 'Automatic']]

/** Three-way switch. `count` shows how many each choice would leave. */
function Switch({ label, value, onChange, count }) {
  return (
    <div className="flex items-center gap-2 text-[11px]">
      <span className="text-slate-500 w-12">{label}</span>
      <div className="inline-flex rounded-lg border border-slate-700 overflow-hidden">
        {VIEWS.map(([k, name]) => (
          <button key={k} onClick={() => onChange(k)} className={`px-2.5 py-1 ${value === k ? 'bg-brand-600 text-white' : 'text-slate-400 hover:text-white hover:bg-slate-800'}`}>
            {name} <span className="opacity-70">{count(k)}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

const caseKind = c => (c.origin === 'human' ? 'human' : 'automatic')
const eventKind = e => (e.kind === 'person' ? 'human' : 'automatic')

/** Every case on one work order. Pick Human or Automatic to see who opened them; for the chosen case, every touch in order:
 *  when, who (person or system), what they did, and in their own words what they wrote or told the member and the driver. */
export default function CaseTrailPanel({ woId, number, onClose }) {
  const [state, setState] = useState({ phase: 'loading' })
  const [pick, setPick] = useState(null)
  const [caseView, setCaseView] = useState('both')
  const [eventView, setEventView] = useState('both')
  useEffect(() => {
    let live = true
    setState({ phase: 'loading' })
    loadCaseTrail(woId)
      .then(({ status, data }) => live && setState(status === 200 ? { phase: 'ready', cases: data.cases || [] } : { phase: 'error', error: data?.detail || `Cases unavailable (${status})` }))
      .catch(e => live && setState({ phase: 'error', error: e.message }))
    return () => { live = false }
  }, [woId])
  useEffect(() => { const k = e => e.key === 'Escape' && onClose(); window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [onClose])

  const all = state.phase === 'ready' ? state.cases : []
  const shown = all.filter(c => caseView === 'both' || caseKind(c) === caseView)
  // keep a valid choice: the open case first, else the first one shown
  const chosen = shown.find(c => c.id === pick) || shown.find(c => !c.closed) || shown[0]
  const events = useMemo(() => (chosen ? chosen.events.filter(e => eventView === 'both' || eventKind(e) === eventView) : []), [chosen, eventView])
  const caseCount = k => all.filter(c => k === 'both' || caseKind(c) === k).length
  const eventCount = k => (chosen ? chosen.events.filter(e => k === 'both' || eventKind(e) === k).length : 0)

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
        {state.phase === 'ready' && !all.length && <div className="p-6 text-sm text-slate-400">This work order has no cases.</div>}
        {all.length > 0 && (
          <div className="p-4 space-y-4">
            <div className="space-y-2">
              <Switch label="Cases" value={caseView} onChange={setCaseView} count={caseCount} />
              <div className="text-[10px] text-slate-600 pl-14">Human = opened by a person · Automatic = opened by an integration or the system</div>
            </div>
            <div className="space-y-2">
              {shown.map(c => (
                <button key={c.id} onClick={() => setPick(c.id)}
                  className={`w-full text-left rounded-lg border px-3 py-2 ${chosen?.id === c.id ? 'border-brand-500 bg-brand-600/10' : 'border-slate-800 hover:bg-slate-900'}`}>
                  <div className="flex items-center gap-2 text-xs">
                    <span className="font-semibold text-white">Case {c.number}</span>
                    <span className="text-slate-400">{TYPE[c.type] || c.type || ''}</span>
                    <span className={`px-1.5 rounded text-[10px] font-bold ${caseKind(c) === 'human' ? 'bg-emerald-500/15 text-emerald-300' : 'bg-slate-700 text-slate-300'}`}>{caseKind(c) === 'human' ? 'HUMAN' : 'AUTOMATIC'}</span>
                    <span className={`ml-auto px-1.5 rounded text-[10px] font-bold ${c.closed ? 'bg-slate-700 text-slate-300' : 'bg-amber-500/20 text-amber-300'}`}>{c.status}</span>
                  </div>
                  {(c.alert || c.subject) && <div className="text-[11px] text-slate-300 mt-0.5 truncate">{c.alert || c.subject}</div>}
                  <div className="text-[11px] text-slate-500 mt-0.5">Owner: {c.owner || 'nobody'} · opened by {c.created_by} · {when(c.created)}</div>
                  <div className="text-[11px] mt-0.5 flex gap-3">
                    <span className={c.human_touched ? 'text-emerald-400' : 'text-slate-600'}>{c.human_touched ? `${c.people.length} ${c.people.length === 1 ? 'person' : 'people'} touched it` : 'no person touched it'}</span>
                    {c.written_count > 0 && <span className="text-sky-300">{c.written_count} written</span>}
                  </div>
                </button>
              ))}
              {!shown.length && <div className="text-xs text-slate-500">No {caseView} cases on this work order.</div>}
            </div>
            {chosen && (
              <div>
                {(chosen.description || chosen.resolution || chosen.resolution_notes || chosen.feedback_resolution) && (
                  <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3 mb-3 space-y-1.5">
                    {chosen.description && <div><div className="text-[10px] uppercase tracking-wide text-slate-500">What it was about</div><div className="text-xs text-slate-200 whitespace-pre-wrap">{chosen.description}</div></div>}
                    {(chosen.resolution || chosen.feedback_resolution) && <div><div className="text-[10px] uppercase tracking-wide text-slate-500">Resolution</div><div className="text-xs text-slate-200">{[chosen.resolution, chosen.feedback_resolution].filter(Boolean).join(' · ')}</div></div>}
                    {chosen.resolution_notes && <div><div className="text-[10px] uppercase tracking-wide text-slate-500">Resolution notes</div><div className="text-xs text-slate-200 whitespace-pre-wrap">{chosen.resolution_notes}</div></div>}
                  </div>
                )}
                <div className="flex items-center gap-2 mb-2">
                  <div className="text-xs font-semibold text-slate-200">Who touched case {chosen.number}</div>
                  <div className="text-[11px] text-slate-500">{chosen.events.length} events</div>
                </div>
                <div className="mb-3"><Switch label="Events" value={eventView} onChange={setEventView} count={eventCount} /></div>
                <ol className="relative border-l border-slate-800 ml-2 space-y-3">
                  {events.map((e, i) => {
                    const Icon = ICON[e.type] || (e.kind === 'person' ? User : Cog)
                    return (
                      <li key={i} className="ml-4">
                        <span className={`absolute -left-[7px] mt-1 w-3.5 h-3.5 rounded-full flex items-center justify-center ${e.kind === 'person' ? 'bg-emerald-500/30 text-emerald-300' : 'bg-slate-700 text-slate-400'}`}><Icon className="w-2.5 h-2.5" /></span>
                        <div className="text-[11px] text-slate-500">{when(e.ts)}</div>
                        <div className="text-xs text-white"><b>{e.name}</b> <span className={`ml-1 px-1 rounded text-[9px] font-bold ${e.kind === 'person' ? 'bg-emerald-500/15 text-emerald-300' : 'bg-slate-700 text-slate-300'}`}>{e.kind === 'person' ? 'PERSON' : 'SYSTEM'}</span>{e.profile && <span className="ml-1 text-[10px] text-slate-600">{e.profile}</span>}</div>
                        <div className="text-xs text-slate-300">{e.text}</div>
                        {e.body && <div className="mt-1 rounded-md border-l-2 border-sky-500/60 bg-sky-500/5 px-2.5 py-1.5 text-xs text-slate-100 whitespace-pre-wrap">{e.body}</div>}
                      </li>
                    )
                  })}
                  {!events.length && <li className="ml-4 text-xs text-slate-500">No {eventView} events on this case.</li>}
                </ol>
              </div>
            )}
          </div>
        )}
      </div>
    </div>,
    document.body)
}
