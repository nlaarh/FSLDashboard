import { useEffect, useState } from 'react'
import { PhoneCall, PhoneIncoming, PhoneForwarded, MessageSquareText, MessageCircleReply, Loader2, Crosshair, Bot, UserRound } from 'lucide-react'
import { loadTextThread } from '../reportcard/prefetch'
import { MARK_TYPES, isFromMember, etClock, duration } from './contactMarks'

export const MARK_ICON = { call: PhoneCall, callback: PhoneIncoming, call_other: PhoneCall, text_in: MessageCircleReply, text_out: MessageSquareText }

const THREAD_MSG = { 409: 'Reload the replay, then open the text again.', 404: 'Not available.', 503: 'Salesforce is busy. Try again in a moment.' }

/** The text conversation. Message text is read only when the first text is opened, then kept for the other rows. */
function Thread({ q }) {
  const [s, setS] = useState({ phase: 'loading' })
  useEffect(() => {
    let live = true
    loadTextThread(q)
      .then(({ status, data }) => live && setS(status === 200 ? { phase: 'ok', entries: data.entries } : { phase: 'error', msg: THREAD_MSG[status] || `Unavailable (${status})` }))
      .catch(() => live && setS({ phase: 'error', msg: 'Could not load the messages.' }))
    return () => { live = false }
  }, [q])
  if (s.phase === 'loading') return <div className="flex items-center gap-2 text-xs text-slate-400 py-2"><Loader2 className="w-3.5 h-3.5 animate-spin" />Loading the conversation…</div>
  if (s.phase === 'error') return <div className="text-xs text-rose-300 py-2">{s.msg}</div>
  if (!s.entries.length) return <div className="text-xs text-slate-500 py-2">No messages were found for this conversation.</div>
  return (
    <ul className="space-y-1.5 max-h-72 overflow-y-auto pr-1" aria-label="Text conversation">
      {s.entries.map((e, k) => e.who === 'system' ? (
        <li key={k} className="flex gap-1.5 items-start justify-center">
          <Bot className="w-3 h-3 text-slate-500 mt-0.5 shrink-0" />
          <span className="text-[11px] text-slate-500 text-center whitespace-pre-line">{etClock(e.ts)} · Automatic text · {e.text}</span>
        </li>
      ) : (
        <li key={k} className={`flex ${e.who === 'member' ? 'justify-start' : 'justify-end'}`}>
          <div className={`max-w-[85%] rounded-2xl px-3 py-1.5 text-xs whitespace-pre-line ${e.who === 'member' ? 'bg-emerald-500/15 border border-emerald-500/30 text-emerald-100 rounded-bl-sm' : 'bg-sky-500/15 border border-sky-500/30 text-sky-100 rounded-br-sm'}`}>
            <div className="text-[10px] text-slate-400 mb-0.5 flex items-center gap-1"><UserRound className="w-3 h-3" />{e.who === 'member' ? 'Member' : 'AAA agent'} · {etClock(e.ts)}</div>
            {e.text}
          </div>
        </li>
      ))}
    </ul>
  )
}

function Detail({ mark, extras, q }) {
  if (mark.ref.kind === 'call') {
    const c = (extras?.calls || []).find(x => x.id === mark.ref.id)
    if (!c) return null
    return (
      <dl className="text-xs text-slate-300 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        <dt className="text-slate-500">Line</dt><dd>{c.line || 'unknown'}</dd>
        <dt className="text-slate-500">Rang at</dt><dd>{etClock(c.ts)}</dd>
        {c.answered_at && <><dt className="text-slate-500">Answered</dt><dd>{etClock(c.answered_at)}{c.agent && ` by ${c.agent}`}</dd></>}
        {!c.answered_at && c.agent && <><dt className="text-slate-500">Agent</dt><dd>{c.agent}</dd></>}
        {c.duration_s != null && <><dt className="text-slate-500">Length</dt><dd>{duration(c.duration_s)}</dd></>}
        {c.kind !== 'original' && <><dt className="text-slate-500">Came</dt><dd>{Math.round(c.min_after_create)} min after the call came in</dd></>}
        {c.kind === 'call_other' && <><dt className="text-slate-500">Note</dt><dd className="text-slate-400">Not about this tow. Not counted as a callback.</dd></>}
        {!!c.transfers?.length && <><dt className="text-slate-500 flex items-center gap-1"><PhoneForwarded className="w-3 h-3" />Transferred</dt>
          <dd>{c.transfers.map((t, k) => <div key={k}>{etClock(t.ts)} to {t.to}</div>)}</dd></>}
      </dl>
    )
  }
  if (mark.ref.kind === 'text') {
    const x = (extras?.inbound_texts || []).find(t => t.id === mark.ref.id)
    return (
      <div className="space-y-2">
        <div className="text-xs text-slate-400">{x?.end ? `Chat open ${etClock(x.ts)} to ${etClock(x.end)}` : `Chat started ${etClock(x?.ts)}`}{x?.agent && ` · handled by ${x.agent}`}</div>
        <Thread q={q} />
      </div>
    )
  }
  return <div className="text-xs text-slate-300 whitespace-pre-line">{mark.detail || mark.title}</div>
}

/** Member contact tab: every call and text in time order. One click on a row opens it; `openId` lets the stage's icons open a row too.
 *  props: q (the call), marks (contactMarks), extras (the extras answer), openId, onOpen(id | null), onShow(ts) seeks the replay. */
export default function ContactPanel({ q, marks, extras, openId, onOpen, onShow }) {
  if (!marks.length) return <div className="glass rounded-xl p-6 text-sm text-slate-400">No calls or texts from this member were found while they waited.</div>
  const fromMember = marks.filter(isFromMember).length
  return (
    <div className="glass rounded-xl p-4 space-y-3">
      <div className="text-xs text-slate-400">{fromMember} from the member · {marks.length - fromMember} sent by AAA. Times are Eastern. Click a row to open it.</div>
      <ul className="space-y-1.5">
        {marks.map(m => {
          const Icon = MARK_ICON[m.type], open = openId === m.id, meta = MARK_TYPES[m.type]
          return (
            <li key={m.id} className={`rounded-lg border bg-slate-900/50 ${open ? 'border-slate-500' : 'border-slate-700/70'}`}>
              <button onClick={() => onOpen(open ? null : m.id)} aria-expanded={open} className="w-full text-left px-3 py-2 flex items-center gap-3">
                <span className="w-7 h-7 rounded-full flex items-center justify-center shrink-0" style={{ background: `${meta.colour}26`, color: meta.colour }}><Icon className="w-4 h-4" /></span>
                <span className="flex-1 min-w-0">
                  <span className="block text-xs font-semibold text-slate-100">{m.title}</span>
                  {m.detail && <span className="block text-[11px] text-slate-400 truncate">{m.detail}</span>}
                </span>
                <span className="text-xs text-slate-300 tabular-nums shrink-0">{etClock(m.ts)}</span>
              </button>
              {open && (
                <div className="px-3 pb-3 pt-2 border-t border-slate-800 space-y-2">
                  <Detail mark={m} extras={extras} q={q} />
                  <button onClick={() => onShow?.(m.ts)} className="text-[11px] text-brand-300 hover:text-brand-200 flex items-center gap-1"><Crosshair className="w-3 h-3" />Show on the replay</button>
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
