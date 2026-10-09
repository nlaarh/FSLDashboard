import { Phone, PlayCircle, ExternalLink, CheckCircle2, ChevronRight, X } from 'lucide-react'
import { SF_LIGHTNING_BASE, contractorSaLink } from '../../utils/sfLinks'
import { SEVERITY, attentionCount } from './garageLiveModel'

const btn = 'inline-flex items-center gap-1 rounded-md border border-slate-600 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold px-2 py-1 min-h-[28px]'

/**
 * "Needs attention": the server's ranked list, one sentence per item with its severity colour and its actions. Clicking an item
 * sends the map to the call or driver it is about. The list is replaced on every refresh; nothing here is computed in the browser.
 */
export default function AttentionDrawer({ data, activeId, onFocus, onReplay, onClose }) {
  const items = data.attention || []
  const phone = data.garage.phone
  const tickets = new Map(data.tickets.map(t => [t.sa_id, t]))
  const sfHref = id => (data.contractor ? contractorSaLink(id) : `${SF_LIGHTNING_BASE}/lightning/r/${id}/view`)
  const counts = items.reduce((c, i) => ({ ...c, [i.severity]: (c[i.severity] || 0) + 1 }), {})

  return (
    <aside className="flex flex-col min-h-0 h-full rounded-xl border border-slate-700/70 bg-slate-900/70" aria-label="Needs attention">
      <header className="flex items-center gap-2 px-3 py-2 border-b border-slate-800">
        <h2 className="text-sm font-bold text-white">Needs attention</h2>
        <span className="rounded-full bg-slate-700 px-2 text-[11px] font-bold text-white" title="Things needing attention">{attentionCount(items)}</span>
        <div className="flex gap-1">
          {['red', 'orange', 'yellow'].filter(k => counts[k]).map(k => (
            <span key={k} className={`rounded-full border px-1.5 text-[11px] font-bold ${SEVERITY[k].chip}`}>{counts[k]}</span>))}
        </div>
        {onClose && <button type="button" onClick={onClose} aria-label="Hide the list" className="ml-auto p-1 rounded hover:bg-slate-800 text-slate-400"><X className="w-4 h-4" /></button>}
      </header>
      <div className="flex-1 min-h-0 overflow-y-auto p-2 space-y-2">
        {items.length === 0 && (
          <div className="flex flex-col items-center gap-2 py-10 text-slate-400 text-sm text-center">
            <CheckCircle2 className="w-8 h-8 text-emerald-400" />
            Nothing needs attention at this garage right now.
          </div>)}
        {items.map(i => {
          const sev = SEVERITY[i.severity]
          const hasMap = i.target && (i.target.type === 'driver' ? data.drivers.some(d => d.id === i.target.id && d.lat != null) : tickets.get(i.target.id)?.lat != null)
          return (
            <div key={i.id} className={`flex rounded-lg border overflow-hidden ${activeId === i.id ? 'border-sky-400' : 'border-slate-700/70'} bg-slate-800/60`}>
              <span className={`w-1.5 shrink-0 ${sev.bar}`} aria-hidden />
              <div className="flex-1 min-w-0 p-2">
                <button type="button" disabled={!hasMap} onClick={() => onFocus({ ...i.target, key: i.id })}
                  className="w-full text-left text-sm text-slate-100 leading-snug disabled:cursor-default group">
                  <span className={`mr-1.5 align-middle rounded border px-1 text-[10px] font-bold uppercase ${sev.chip}`}>{sev.label}</span>
                  {i.text}
                  {hasMap && <ChevronRight className="inline w-3.5 h-3.5 ml-1 text-slate-500 group-hover:text-sky-300" />}
                </button>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {i.actions.includes('call_garage') && phone && <a href={`tel:${phone.replace(/[^\d+]/g, '')}`} className={btn}><Phone className="w-3 h-3" />Call garage</a>}
                  {i.actions.includes('replay') && i.sa_id && data.can_replay && <button type="button" onClick={() => onReplay(i.sa_id)} className={btn}><PlayCircle className="w-3 h-3" />Open Replay</button>}
                  {i.actions.includes('salesforce') && i.sa_id && <a href={sfHref(i.sa_id)} target="_blank" rel="noopener noreferrer" className={btn}><ExternalLink className="w-3 h-3" />Open in Salesforce</a>}
                </div>
              </div>
            </div>)
        })}
      </div>
    </aside>
  )
}
