import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { useCallback } from 'react'
import { ArrowLeft, ExternalLink } from 'lucide-react'
import AccountingAuditPanel from '../components/AccountingAuditPanel'
import { productCode } from '../utils/formatting'

export default function AccountingWoaDetail() {
  const { woaId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()

  const row = location.state?.row || null
  const allRows = location.state?.rows || []

  const decodedId = decodeURIComponent(woaId)

  const siblings = row
    ? allRows.filter(r =>
        (r.id || r.woa_number) !== (row.id || row.woa_number) &&
        r.wo_id && r.wo_id === row.wo_id &&
        productCode(r.product) === productCode(row.product)
      )
    : []

  const allWoSiblings = row
    ? allRows.filter(r =>
        (r.id || r.woa_number) !== (row.id || row.woa_number) &&
        r.wo_id && r.wo_id === row.wo_id
      )
    : []

  const handleOpenWoa = useCallback((targetKey) => {
    const target = allRows.find(r => (r.id || r.woa_number) === targetKey)
    if (target) {
      navigate(`/accounting/woa/${encodeURIComponent(target.id || target.woa_number)}`, { state: { row: target, rows: allRows } })
    }
  }, [allRows, navigate])

  return (
    <div className="min-h-screen bg-slate-950">
      {/* Top bar */}
      <div className="sticky top-0 z-10 bg-slate-900/95 border-b border-slate-800/60 backdrop-blur-sm">
        <div className="max-w-7xl mx-auto px-4 py-2.5 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate('/accounting')}
              className="flex items-center gap-1.5 text-[11px] text-slate-400 hover:text-slate-200 transition-colors"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              Back to list
            </button>
            <span className="text-slate-700">|</span>
            <span className="text-[11px] font-mono text-slate-400">WOA Audit</span>
            {row?.woa_number && (
              <>
                <span className="text-[12px] font-semibold text-slate-200 font-mono">{row.woa_number}</span>
                {row.id && (
                  <a
                    href={`https://aaawcny.lightning.force.com/${row.id}`}
                    target="_blank" rel="noopener noreferrer"
                    className="text-brand-400 hover:text-brand-300 transition-colors"
                    title="Open in Salesforce"
                  >
                    <ExternalLink className="w-3.5 h-3.5" />
                  </a>
                )}
              </>
            )}
            {row?.facility && (
              <span className="text-[11px] text-slate-500">· {row.facility}</span>
            )}
            {row?.product && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 font-mono">{row.product}</span>
            )}
          </div>
          {row?.woa_number && (
            <span className="text-[10px] text-slate-600">
              {row.created_date && `Submitted ${row.created_date}`}
            </span>
          )}
        </div>
      </div>

      {/* Audit panel — full width with comfortable padding */}
      <div className="max-w-7xl mx-auto px-4 py-4">
        <AccountingAuditPanel
          woaId={row?.id || decodedId}
          onComplete={() => {}}
          recReason={row?.rec_reason || null}
          siblingWoas={siblings}
          allWoSiblings={allWoSiblings}
          isLowMateriality={row?.is_low_materiality || false}
          estimatedUsd={row?.estimated_usd || null}
          rowRec={row?.recommendation || null}
          onOpenWoa={handleOpenWoa}
        />
      </div>
    </div>
  )
}
