import { ChevronLeft, ChevronRight } from 'lucide-react'

/**
 * Shared table paginator. Keeps large accounting tables fast by rendering only
 * one page of rows at a time. Returns null when everything fits on one page.
 *
 * Usage:
 *   const [page, setPage] = useState(0)
 *   const pageRows = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
 *   ...render pageRows...
 *   <Paginator page={page} setPage={setPage} total={filtered.length} pageSize={PAGE_SIZE} />
 * Remember to reset page to 0 when filters/search change.
 */
export default function Paginator({ page, setPage, total, pageSize = 100 }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  if (pages <= 1) return null
  const from = total === 0 ? 0 : page * pageSize + 1
  const to = Math.min((page + 1) * pageSize, total)
  const btn = 'flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-medium bg-slate-800 text-slate-300 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors'
  return (
    <div className="flex items-center justify-between px-4 py-2 border-t border-slate-800/60 text-[11px] text-slate-400">
      <span>Showing {from}–{to} of {total}</span>
      <div className="flex items-center gap-2">
        <button className={btn} disabled={page === 0} onClick={() => setPage(p => Math.max(0, p - 1))}>
          <ChevronLeft size={12} /> Prev
        </button>
        <span className="text-slate-500">Page {page + 1} / {pages}</span>
        <button className={btn} disabled={page >= pages - 1} onClick={() => setPage(p => Math.min(pages - 1, p + 1))}>
          Next <ChevronRight size={12} />
        </button>
      </div>
    </div>
  )
}
