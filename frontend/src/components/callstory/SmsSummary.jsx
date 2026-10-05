import { MessageSquare } from 'lucide-react'

/** What the member was texted. We can prove a text was handed to the SMS channel, never that it arrived. */
export default function SmsSummary({ sms }) {
  const sent = sms.rows.filter(r => r.outcome === 'sent').length
  const notSent = sms.rows.length - sent
  return (
    <div className="glass rounded-xl p-4 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <MessageSquare className="w-4 h-4 text-slate-400" />
        <span className="text-sm font-semibold text-white">Texts to the member</span>
        <span className="text-xs text-slate-300">{sent} sent{notSent ? ` · ${notSent} not sent` : ''}</span>
        <span className="text-[10px] px-1.5 py-0.5 rounded border border-amber-500/30 text-amber-300">{sms.delivery.label}</span>
      </div>
      {sms.source === 'messaging_session' && (
        <div className="text-[11px] text-amber-300">Detailed text log starts 1 Sep 2026: earlier texts show as "type unknown".</div>
      )}
      {sms.why_not.map((w, i) => <div key={i} className="text-[12px] text-slate-300">• {w.text}</div>)}
    </div>
  )
}
