import { useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, ExternalLink } from 'lucide-react'
import AccountingAuditPanel from '../../components/AccountingAuditPanel'

const SF_BASE = 'https://aaawcny.lightning.force.com'

export default function ContractorCallDetail() {
  const { woId } = useParams()
  const navigate = useNavigate()

  const auditFn = useMemo(() => {
    return () => fetch(`/api/contractor/calls/${encodeURIComponent(woId)}/audit`)
      .then(r => { if (!r.ok) throw new Error(`Server error ${r.status}`); return r.json() })
  }, [woId])

  return (
    <div>
      {/* Back bar */}
      <div className="flex items-center gap-4 mb-5">
        <button
          onClick={() => navigate(-1)}
          className="flex items-center gap-1.5 text-sm text-slate-400 hover:text-white transition-colors"
        >
          <ArrowLeft size={16} />
          Back to Calls Log
        </button>
        <div className="w-px h-4 bg-slate-700" />
        <span className="text-sm font-bold text-white font-mono">WO-{woId}</span>
        <a
          href={`${SF_BASE}/${woId}`}
          target="_blank" rel="noopener noreferrer"
          className="flex items-center gap-1 text-xs text-indigo-400 hover:underline"
        >
          <ExternalLink size={12} />
          Open in Salesforce
        </a>
      </div>

      {/* Full-width audit panel */}
      <div className="glass rounded-xl border border-slate-700/30 overflow-hidden">
        <AccountingAuditPanel
          woaId={woId}
          auditFn={auditFn}
          contractorMode={true}
        />
      </div>
    </div>
  )
}
