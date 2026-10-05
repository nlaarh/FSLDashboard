import { useMemo, useState } from 'react'
import { MessageSquare } from 'lucide-react'
import { EVENT_LABEL, ACTOR_LABEL, fmtTime } from './storyStyles'

function summary(e) {
  if (e.kind === 'E07_declined' && e.seconds_from_offer != null) return `in ${e.seconds_from_offer} s${e.reason ? ` · ${e.reason}` : ''}`
  if (e.kind === 'E07_rejected') return e.reason || 'reason not recorded for this hop'
  const parts = []
  const status = e.fields.find(f => f.field === 'Status')
  if (e.kind === 'E00_status' && status) parts.push(`→ ${status.new}`)
  if (e.moved) parts.push(`→ ${e.to}`)
  if (e.assigned) parts.push(e.driver ? `driver ${e.driver}` : 'driver removed')
  if (e.pta_to && e.pta_from) parts.push(`PTA ${e.pta_from} → ${e.pta_to}`)
  return parts.join(' · ')
}

/** Events in time order with the member's texts interleaved; "raw history" shows every field change. */
export default function StoryTimeline({ events, sms, highlight }) {
  const [raw, setRaw] = useState(false)
  const rows = useMemo(() => [
    ...events.filter(e => raw || !e.hidden).map(e => ({ type: 'event', ts: e.ts, e })),
    ...sms.rows.map(r => ({ type: 'sms', ts: r.ts, r })),
  ].sort((a, b) => (a.ts || '').localeCompare(b.ts || '')), [events, sms, raw])
  return (
    <div className="glass rounded-xl p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] uppercase tracking-wide text-slate-500">Timeline (Eastern time)</span>
        <label className="text-[11px] text-slate-400 flex items-center gap-1.5 cursor-pointer">
          <input type="checkbox" checked={raw} onChange={e => setRaw(e.target.checked)} />raw history
        </label>
      </div>
      <div className="divide-y divide-slate-800/70">
        {rows.map((row, i) => row.type === 'sms' ? (
          <div key={`s${i}`} className="grid grid-cols-[64px_1fr] gap-3 py-1.5 text-[12px]">
            <span className="text-slate-500 tabular-nums">{fmtTime(row.ts)}</span>
            <span className="flex items-center gap-1.5 text-sky-300">
              <MessageSquare className="w-3 h-3" />Text: {row.r.label}
              <span className={row.r.outcome === 'sent' ? 'text-slate-400' : 'text-rose-300'}>
                ({row.r.outcome === 'sent' ? 'sent to SMS channel' : `not sent: ${row.r.reason}`})
              </span>
            </span>
          </div>
        ) : (
          <div key={row.e.id} className={`grid grid-cols-[64px_1fr] gap-3 py-1.5 text-[12px] rounded ${
            highlight?.includes(row.e.id) ? 'bg-brand-600/15' : ''} ${row.e.hidden ? 'opacity-60' : ''}`}>
            <span className="text-slate-500 tabular-nums">{fmtTime(row.e.ts)}</span>
            <div>
              <span className="text-slate-100 font-medium">{EVENT_LABEL[row.e.kind] || row.e.kind}</span>
              {summary(row.e) && <span className="text-slate-300"> {summary(row.e)}</span>}
              <span className="text-slate-500"> · {row.e.actor} ({ACTOR_LABEL[row.e.actor_class] || row.e.actor_class})</span>
              <span className="ml-1.5 text-[9px] font-mono text-slate-600">{row.e.id}</span>
              {raw && (
                <div className="text-[10px] text-slate-500 mt-0.5">
                  {row.e.fields.map((f, j) => (
                    <span key={j} className="mr-3">{f.field}: {String(f.old ?? '∅')} → {String(f.new ?? '∅')}</span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
