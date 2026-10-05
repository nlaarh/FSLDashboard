import { useState } from 'react'
import { CheckCircle2, AlertTriangle, XCircle, ArrowRightCircle, ChevronDown, Play, Lightbulb } from 'lucide-react'
import { iconFor } from './explainIcons'

const VERDICT = {
  good: { cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40', label: 'Went well' },
  mixed: { cls: 'bg-amber-500/15 text-amber-300 border-amber-500/40', label: 'Mixed' },
  poor: { cls: 'bg-rose-500/15 text-rose-300 border-rose-500/40', label: 'Went wrong' },
}

/** One call in plain words: what went well, what went wrong (with why it may have happened) and what to change. Rules only, no AI. */
export default function TakeawaysCard({ takeaways, onShow }) {
  const [open, setOpen] = useState(() => new Set([0]))   // the worst problem opens by itself
  if (!takeaways) return null
  const v = VERDICT[takeaways.verdict] || VERDICT.mixed
  const toggle = k => setOpen(o => { const n = new Set(o); n.has(k) ? n.delete(k) : n.add(k); return n })
  return (
    <div className="glass rounded-xl p-4 space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        <span className={`px-2.5 py-1 rounded-full border text-xs font-semibold ${v.cls}`}>{v.label}</span>
        <span className="text-sm font-semibold text-white">{takeaways.headline}</span>
        <span className="text-[11px] text-slate-500 ml-auto">Worked out from the call's own numbers with fixed rules. No AI.</span>
      </div>
      <div className="grid lg:grid-cols-3 gap-4">
        <section>
          <h3 className="text-xs font-semibold text-emerald-300 mb-2 flex items-center gap-1.5"><CheckCircle2 className="w-4 h-4" />What went well</h3>
          <ul className="space-y-1.5">
            {takeaways.went_well.map((w, k) => <li key={k} className="text-xs text-slate-300 flex gap-2"><CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0 mt-0.5" /><span>{w.text}</span></li>)}
            {!takeaways.went_well.length && <li className="text-xs text-slate-500">Nothing stood out as done well on this call.</li>}
          </ul>
        </section>
        <section>
          <h3 className="text-xs font-semibold text-rose-300 mb-2 flex items-center gap-1.5"><XCircle className="w-4 h-4" />What went wrong, and why it may have happened</h3>
          <ul className="space-y-2">
            {takeaways.went_wrong.map((w, k) => {
              const Icon = w.explain ? iconFor(w.explain.icon) : AlertTriangle
              const isOpen = open.has(k)
              return (
                <li key={k} className="rounded-lg border border-slate-700/70 bg-slate-900/50">
                  <button onClick={() => toggle(k)} className="w-full text-left px-2.5 py-2 flex gap-2 items-start" aria-expanded={isOpen}>
                    <Icon className={`w-4 h-4 shrink-0 mt-0.5 ${w.severity === 'bad' ? 'text-rose-400' : w.severity === 'warn' ? 'text-amber-400' : 'text-slate-400'}`} />
                    <span className="text-xs text-slate-200 flex-1">{w.text}</span>
                    {w.explain && <ChevronDown className={`w-4 h-4 text-slate-500 shrink-0 transition-transform ${isOpen ? 'rotate-180' : ''}`} />}
                  </button>
                  {isOpen && w.explain && (
                    <div className="px-3 pb-2.5 pt-0.5 text-xs space-y-1.5 border-t border-slate-800">
                      <div className="font-semibold text-slate-300 pt-1.5">{w.explain.title}: why this may have happened</div>
                      <ul className="list-disc pl-4 space-y-1 text-slate-400">
                        {w.explain.why.map((t, i) => <li key={i} className={t.startsWith('This call:') ? 'text-amber-200' : ''}>{t}</li>)}
                      </ul>
                      {!!w.explain.check.length && (
                        <div className="flex gap-1.5 text-slate-400"><Lightbulb className="w-3.5 h-3.5 text-amber-300 shrink-0 mt-0.5" /><span><b className="text-slate-300">Check:</b> {w.explain.check.join(' ')}</span></div>
                      )}
                      {!!w.step_ids.length && onShow && (
                        <button onClick={() => onShow(w.step_ids[0])} className="inline-flex items-center gap-1 text-brand-300 hover:text-brand-200"><Play className="w-3 h-3" />Show it in the replay</button>
                      )}
                    </div>
                  )}
                </li>
              )
            })}
            {!takeaways.went_wrong.length && <li className="text-xs text-slate-500">No problems found on this call.</li>}
          </ul>
        </section>
        <section>
          <h3 className="text-xs font-semibold text-sky-300 mb-2 flex items-center gap-1.5"><ArrowRightCircle className="w-4 h-4" />What to change</h3>
          <ul className="space-y-1.5">
            {takeaways.improve.map((i, k) => (
              <li key={k} className="text-xs text-slate-300 flex gap-2"><ArrowRightCircle className="w-3.5 h-3.5 text-sky-400 shrink-0 mt-0.5" />
                <span><b className="text-slate-200">{i.owner}:</b> {i.action}.</span></li>
            ))}
            {!takeaways.improve.length && <li className="text-xs text-slate-500">Nothing to change from this call.</li>}
          </ul>
        </section>
      </div>
    </div>
  )
}
