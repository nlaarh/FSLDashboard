import { clsx } from 'clsx'
import { Download, RefreshCw, Search } from 'lucide-react'

export default function AccountingToolbar({
  total,
  listCachedAt = '',
  statusFilter,
  product,
  recFilter,
  startDate,
  endDate,
  search,
  searchDebounce,
  loading,
  activeTab,
  products,
  onStatusFilterChange,
  onProductChange,
  onRecFilterChange,
  onStartDateChange,
  onEndDateChange,
  onClearDates,
  onSearchChange,
  onRefresh,
  onTabChange,
}) {
  function _timeAgo(dateStr) {
    if (!dateStr) return ''
    try {
      const d = new Date(dateStr.replace(' ', 'T') + 'Z')
      const mins = Math.round((Date.now() - d.getTime()) / 60000)
      if (mins < 1) return 'just now'
      if (mins === 1) return '1m ago'
      if (mins < 60) return `${mins}m ago`
      const hrs = Math.floor(mins / 60)
      return `${hrs}h ${mins % 60}m ago`
    } catch { return '' }
  }

  return (
    <>
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-2xl font-bold text-white">Accounting</h1>
          <p className="text-slate-500 text-xs mt-0.5">
            Work Order Adjustments · {total} pending review
          </p>
          {listCachedAt && (
            <p className="text-slate-600 text-[10px] mt-0.5">
              Data from {_timeAgo(listCachedAt)} · <button onClick={onRefresh} className="text-slate-500 hover:text-slate-300 underline">Refresh now</button>
            </p>
          )}
          <p className="text-slate-600 text-[10px] mt-0.5">
            {statusFilter === 'New' ? 'Showing open adjustments (Status = New)'
              : statusFilter === 'Approved' ? 'Showing approved adjustments'
              : statusFilter === 'Rejected' ? 'Showing rejected adjustments'
              : 'Showing all adjustments'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <a href={`/api/accounting/wo-adjustments/export?status=${statusFilter}&product_filter=${product === 'All' ? '' : product}&rec_filter=${recFilter === 'All' ? '' : recFilter}&start_date=${startDate}&end_date=${endDate}&q=${encodeURIComponent(searchDebounce)}&_t=${Date.now()}`}
            className="flex items-center gap-2 px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700
                       text-slate-400 hover:text-white text-xs font-medium transition-all">
            <Download className="w-3.5 h-3.5" />Export
          </a>
          <button onClick={onRefresh} disabled={loading}
            className="flex items-center gap-2 px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700
                       text-slate-400 hover:text-white text-xs font-medium transition-all disabled:opacity-50">
            <RefreshCw className={clsx('w-3.5 h-3.5', loading && 'animate-spin')} />
            {loading ? 'Loading…' : 'Refresh'}
          </button>
        </div>
      </div>

      <div className="flex items-center gap-1 mb-5 border-b border-slate-800/60 -mx-0">
        {[{ id: 'woa', label: 'WO Adjustments' }, { id: 'analytics', label: 'Analytics' }, { id: 'help', label: 'Help & Guide' }].map(t => (
          <button key={t.id} onClick={() => onTabChange(t.id)}
            className={clsx('px-4 py-2 text-xs font-medium border-b-2 transition-colors -mb-px',
              activeTab === t.id
                ? 'border-brand-400 text-brand-300'
                : 'border-transparent text-slate-500 hover:text-slate-300')}>
            {t.label}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3 mb-3">
        {activeTab !== 'analytics' && (<>
          <div className="relative">
            <select value={product} onChange={e => onProductChange(e.target.value)}
              className="bg-slate-900 border border-slate-700 rounded-lg text-xs px-3 py-2 pr-8
                         focus:outline-none focus:ring-2 focus:ring-brand-500/40 appearance-none cursor-pointer text-white">
              {products.map(p => (
                <option key={p.val} value={p.val}>{p.label}</option>
              ))}
            </select>
            <svg className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" /></svg>
          </div>

          <div className="flex items-center bg-slate-800/60 rounded-lg p-0.5 border border-slate-700/50">
            {['New', 'Approved', 'Rejected', 'All'].map(s => (
              <button key={s} onClick={() => onStatusFilterChange(s)}
                className={clsx(
                  'px-3 py-1.5 rounded-md text-xs font-medium transition-all',
                  statusFilter === s
                    ? s === 'Approved' ? 'bg-emerald-600/20 text-emerald-300'
                      : s === 'Rejected' ? 'bg-red-600/20 text-red-300'
                      : 'bg-brand-600/20 text-brand-300'
                    : 'text-slate-500 hover:text-white',
                )}>
                {s}
              </button>
            ))}
          </div>

          <div className="flex items-center bg-slate-800/60 rounded-lg p-0.5 border border-slate-700/50">
            {['All', 'Approve', 'Review', 'Credit'].map(f => (
              <button key={f} onClick={() => onRecFilterChange(f)}
                className={clsx(
                  'px-3 py-1.5 rounded-md text-xs font-medium transition-all',
                  recFilter === f
                    ? f === 'Approve' ? 'bg-emerald-600/20 text-emerald-300'
                      : f === 'Review' ? 'bg-amber-600/20 text-amber-300'
                      : f === 'Credit' ? 'bg-red-600/20 text-red-300'
                      : 'bg-brand-600/20 text-brand-300'
                    : 'text-slate-500 hover:text-white',
                )}>
                {f}
              </button>
            ))}
          </div>
        </>)}

        <div className="flex items-center gap-1.5">
          <input type="date" value={startDate} onChange={e => onStartDateChange(e.target.value)}
            className="bg-slate-900 border border-slate-700 rounded-lg text-xs px-2 py-2 text-white focus:outline-none focus:ring-2 focus:ring-brand-500/40 [color-scheme:dark]" />
          <span className="text-slate-600 text-xs">to</span>
          <input type="date" value={endDate} onChange={e => onEndDateChange(e.target.value)}
            className="bg-slate-900 border border-slate-700 rounded-lg text-xs px-2 py-2 text-white focus:outline-none focus:ring-2 focus:ring-brand-500/40 [color-scheme:dark]" />
          {(startDate || endDate) && (
            <button onClick={onClearDates}
              className="text-[10px] text-slate-500 hover:text-white">✕</button>
          )}
        </div>

        {activeTab !== 'analytics' && (
          <div className="relative flex-1 max-w-xs">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
            <input value={search} onChange={e => onSearchChange(e.target.value)}
              placeholder="Search WOA#, WO#, facility…"
              className="w-full pl-9 pr-4 py-2 bg-slate-900 border border-slate-700 rounded-xl text-sm
                         placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-brand-500/40 transition-all" />
          </div>
        )}
      </div>
    </>
  )
}
