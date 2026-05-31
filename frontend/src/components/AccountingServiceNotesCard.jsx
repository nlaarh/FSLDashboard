import { FileText } from 'lucide-react'

const NOTE_FIELDS = [
  { key: 'woa_description',    label: 'WOA Description' },
  { key: 'woa_internal_notes', label: 'Internal Notes' },
  { key: 'agent_comments',     label: 'Agent Comments' },
  { key: 'driver_instructions',label: 'Driver Instructions' },
  { key: 'system_notes',       label: 'System Notes' },
]

export default function AccountingServiceNotesCard({ serviceNotes }) {
  if (!serviceNotes) return null

  const hasAny = NOTE_FIELDS.some(f => serviceNotes[f.key]) ||
    (serviceNotes.sa_service_notes || []).some(s => s.note)
  if (!hasAny) return null

  return (
    <div className="glass rounded-xl border border-slate-700/20 px-4 py-3 mb-3">
      <div className="flex items-center gap-2 mb-2">
        <FileText className="w-3.5 h-3.5 text-slate-400" />
        <div className="text-[10px] text-slate-400 uppercase tracking-wider font-bold">Service Notes</div>
      </div>
      <div className="flex flex-col gap-2">
        {NOTE_FIELDS.map(({ key, label }) =>
          serviceNotes[key] ? (
            <div key={key}>
              <div className="text-[9px] text-slate-500 uppercase tracking-wider mb-0.5">{label}</div>
              <div className="text-[11px] text-slate-300 whitespace-pre-wrap leading-relaxed">{serviceNotes[key]}</div>
            </div>
          ) : null
        )}
        {(serviceNotes.sa_service_notes || []).map((s, i) => (
          <div key={i}>
            <div className="text-[9px] text-slate-500 uppercase tracking-wider mb-0.5">
              Service Note {s.sa_number ? `(${s.sa_number})` : ''}
            </div>
            <div className="text-[11px] text-slate-300 whitespace-pre-wrap leading-relaxed">{s.note}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
