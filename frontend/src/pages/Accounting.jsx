import { useState, useEffect, useMemo, Fragment, useCallback } from 'react'
import { clsx } from 'clsx'
import {
  Search, ChevronUp, ChevronDown, RefreshCw,
  AlertTriangle, HelpCircle, X, Download,
} from 'lucide-react'
import { fetchWOAdjustments } from '../api'
import AccountingAuditPanel from '../components/AccountingAuditPanel'
import { productCode, formatQty } from '../utils/formatting'

const PRODUCTS = [
  { val: 'All', label: 'All Products' },
  { val: 'ER', label: 'ER — Enroute Miles' },
  { val: 'TW', label: 'TW — Tow Miles' },
  { val: 'TB', label: 'TB — Tow Basic (Acctg)' },
  { val: 'TT', label: 'TT — Tow Plus 5-30mi (Acctg)' },
  { val: 'TU', label: 'TU — Tow Plus 30-100mi (Acctg)' },
  { val: 'TM', label: 'TM — Tow Premier (Acctg)' },
  { val: 'EM', label: 'EM — Extra Tow Mileage' },
  { val: 'E1', label: 'E1 — Extrication (1st Truck)' },
  { val: 'Z8', label: 'Z8 — RAP Extrication' },
  { val: 'MH', label: 'MH — Medium/Heavy Duty' },
  { val: 'TL', label: 'TL — Tolls/Parking' },
  { val: 'MI', label: 'MI — Wait Time / Misc' },
  { val: 'BA', label: 'BA — Base Rate' },
  { val: 'BC', label: 'BC — Basic Cost' },
  { val: 'HO', label: 'HO — Holiday Bonus' },
  { val: 'PG', label: 'PG — Plus/Premier Fuel' },
  { val: 'Z5', label: 'Z5 — RAP Fuel Delivery' },
  { val: 'Z7', label: 'Z7 — RAP Lockout' },
  { val: 'TJ', label: 'TJ — TireJect' },
]

const PRODUCT_COLORS = {
  ER: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  TW: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
  TB: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
  TT: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
  TU: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
  TM: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
  EM: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
  E1: 'bg-orange-500/15 text-orange-400 border-orange-500/30',
  Z8: 'bg-orange-500/15 text-orange-400 border-orange-500/30',
  MH: 'bg-red-500/15 text-red-400 border-red-500/30',
  TL: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  MI: 'bg-slate-500/15 text-slate-400 border-slate-500/30',
  HO: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
}

const SORT_DEF = {
  woa_number: 'asc', facility: 'asc', wo_number: 'asc', product: 'asc',
  requested_qty: 'desc', currently_paid: 'desc', delta: 'desc',
  recommendation: 'asc', created_date: 'desc', created_by: 'asc',
}

const COL_HELP = {
  woa_number: 'Work Order Adjustment number. This is the garage\'s request for additional payment. Click to open in Salesforce.',
  facility: 'The garage/facility that submitted this adjustment request.',
  wo_number: 'The Work Order this adjustment is for. Click to open in Salesforce.',
  product: 'Product code from the Work Order Line Item (WOLI).\n\nBA = Base Rate — flat fee for showing up\nER = Enroute Miles — miles from truck location to breakdown (SF uses Google Maps to calculate)\nTW = Tow Miles — miles towing vehicle pickup to drop-off destination\nE1 = Extrication 1st Truck — winch-out/recovery time in MINUTES (vehicle stuck in ditch, snow, mud, accident)\nE2 = Extrication 2nd Truck — if a second truck was needed\nMH = Medium/Heavy Duty — vehicle over 10,000 lbs required special equipment\nTL = Tolls/Parking — out-of-pocket costs (tolls on thruway, airport parking, etc.)\nMI = Miscellaneous — usually wait time (member held up the driver)\nBC = Basic Cost\nPC = Plus Cost\n\nHow we verify each:\n• ER/TW: Compare requested miles vs SF Google-calculated distance\n• E1/MI: Compare requested minutes vs actual on-scene time from SA timestamps\n• MH: Check vehicle group (DW=heavy) or weight field\n• TL: Always Review — need receipts\n• BA/BC/PC: Always Review — policy-based\n\nProduct matched to WOA by finding the WOLI with closest quantity.',
  requested_qty: 'What the garage is requesting in this adjustment.\n\nFor ER/TW: miles\nFor E1: minutes\nFor TL: dollar amount\nFor BA/BC/PC: flat rate\n\nNegative = credit/reduction (garage overpaid, adjusting down).',
  currently_paid: 'What SF currently has on the Work Order Line Item for this product.\n\nThis is the quantity that was billed — what the garage was (or will be) paid based on SF\'s auto-calculation.\n\nThe garage submitted this adjustment because they believe this amount is wrong.\n\nSource: WorkOrderLineItem.Quantity in Salesforce.',
  delta: 'Difference between what the garage requests and what SF billed.\n\nIf SF Billed > 0: Delta = Requested - SF Billed (garage wants a correction).\nIf SF Billed = 0: Delta = full Requested amount (product not yet on the WO).\n\nPositive = garage wants more than what SF calculated.\nZero = garage asking for same amount already billed.\nNegative = garage acknowledges overpayment.',
  recommendation: 'Auto-calculated recommendation based on SF data. No AI — pure math.\n\n✓ Approve = Data supports the garage\'s request\n⚠ Review = Data doesn\'t match or is missing. Needs human verification.\n\nHow we verify by product:\n• ER/TW (miles): Requested vs SF Google distance (≤130% = Approve)\n• E1/MI (time): Requested minutes vs actual on-scene time from SA timestamps (≤120% = Approve)\n• MH (weight): Vehicle Group DW/HD = Approve, PS = Review\n• TL (tolls): Always Review — need receipts\n• BA/BC/PC (rates): Always Review — policy-based\n\nSF already uses Google Maps internally — we reuse those distances, no extra API calls.\n\nHover over ⚠ Review for the specific reason.',
  created_date: 'When the adjustment was submitted.',
  created_by: 'Who submitted the adjustment (usually dispatch/garage staff).',
}

function HelpTip({ text, children }) {
  const [open, setOpen] = useState(false)
  if (!text) return children || null
  return (
    <span className="relative inline-block ml-1">
      <button onClick={e => { e.stopPropagation(); setOpen(!open) }}
        className={children ? '' : 'text-slate-600 hover:text-slate-400 transition-colors'}>
        {children || <HelpCircle className="w-3 h-3" />}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-5 z-50 w-72 p-3 rounded-lg bg-slate-800 border border-slate-600 shadow-xl text-[10px] text-slate-300 leading-relaxed whitespace-pre-line">
            <button onClick={() => setOpen(false)} className="absolute top-1.5 right-1.5 text-slate-500 hover:text-white">
              <X className="w-3 h-3" />
            </button>
            {text}
          </div>
        </>
      )}
    </span>
  )
}

function Th({ label, col, sort, onSort, right = false }) {
  const active = sort.col === col
  const help = COL_HELP[col]
  return (
    <th
      className={clsx(
        'px-3 py-3 text-[10px] font-semibold uppercase tracking-wider cursor-pointer select-none whitespace-nowrap',
        'hover:text-slate-200 transition-colors',
        right ? 'text-right' : 'text-left',
        active ? 'text-brand-400' : 'text-slate-500',
      )}
      onClick={() => onSort(col)}
    >
      {label}
      <HelpTip text={help} />
      {active
        ? sort.dir === 'asc'
          ? <ChevronUp className="inline w-3 h-3 ml-0.5 -mt-0.5" />
          : <ChevronDown className="inline w-3 h-3 ml-0.5 -mt-0.5" />
        : <span className="inline-block w-3 ml-0.5" />}
    </th>
  )
}

function AuditToggle({ woaId, onComplete, recReason }) {
  return (
    <div>
      <AccountingAuditPanel woaId={woaId} onComplete={onComplete} recReason={recReason} />
    </div>
  )
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function Accounting() {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [totals, setTotals] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState('')
  const [searchDebounce, setSearchDebounce] = useState('')
  const [product, setProduct] = useState('All')
  const [recFilter, setRecFilter] = useState('All')
  const [statusFilter, setStatusFilter] = useState('open')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [sort, setSort] = useState({ col: 'created_date', dir: 'desc' })
  const [expanded, setExpanded] = useState(null)
  const [page, setPage] = useState(0)
  const PAGE_SIZE = 50
  const handleAuditComplete = useCallback(() => {}, [])

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    fetchWOAdjustments(statusFilter, page, PAGE_SIZE, product === 'All' ? '' : product, recFilter === 'All' ? '' : recFilter, searchDebounce, sort.col, sort.dir, startDate, endDate)
      .then(data => { setItems(data.items || []); setTotal(data.total || 0); setTotals(data.totals || {}) })
      .catch(e => setError(e.message || 'Failed to load adjustments'))
      .finally(() => setLoading(false))
  }, [statusFilter, page, product, recFilter, searchDebounce, sort, startDate, endDate])

  useEffect(() => { load() }, [load])

  // Debounce search
  useEffect(() => {
    const t = setTimeout(() => { setSearchDebounce(search); setPage(0) }, 400)
    return () => clearTimeout(t)
  }, [search])

  // Sort + filter
  const rows = useMemo(() => {
    return items.map(r => ({
      ...r,
      delta: r.currently_paid > 0
        ? (r.requested_qty || 0) - (r.currently_paid || 0)
        : (r.requested_qty || 0),
    }))
  }, [items])

  function onSort(col) {
    setSort(prev => prev.col === col
      ? { col, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
      : { col, dir: SORT_DEF[col] ?? 'asc' }
    )
    setPage(0)
    setExpanded(null)
  }

  const totalRequested = totals.requested || 0
  const totalPaid = totals.billed || 0
  const totalDelta = totals.delta || 0

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-2xl font-bold text-white">Accounting</h1>
          <p className="text-slate-500 text-xs mt-0.5">
            Work Order Adjustments · {total} pending review
          </p>
          <p className="text-slate-600 text-[10px] mt-0.5">
            {statusFilter === 'open'
              ? 'Showing adjustments not yet reviewed by accounting (CreatedBy = LastModifiedBy, excluding accounting staff)'
              : 'Showing all adjustments including already reviewed'}
          </p>
        </div>
        <div className="flex items-center gap-2">
        <a href={`/api/accounting/wo-adjustments/export?status=${statusFilter}&product_filter=${product === 'All' ? '' : product}&rec_filter=${recFilter === 'All' ? '' : recFilter}&start_date=${startDate}&end_date=${endDate}&q=${encodeURIComponent(searchDebounce)}&_t=${Date.now()}`}
          className="flex items-center gap-2 px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700
                     text-slate-400 hover:text-white text-xs font-medium transition-all">
          <Download className="w-3.5 h-3.5" />Export
        </a>
        <button onClick={load} disabled={loading}
          className="flex items-center gap-2 px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700
                     text-slate-400 hover:text-white text-xs font-medium transition-all disabled:opacity-50">
          <RefreshCw className={clsx('w-3.5 h-3.5', loading && 'animate-spin')} />
          {loading ? 'Loading…' : 'Refresh'}
        </button>
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <div className="glass rounded-xl border border-slate-700/30 p-4">
          <div className="text-[10px] text-slate-500 uppercase tracking-wider">Total WOAs</div>
          <div className="text-2xl font-bold text-white">{total}</div>
        </div>
        <div className="glass rounded-xl border border-slate-700/30 p-4">
          <div className="text-[10px] text-slate-500 uppercase tracking-wider">Total Requested</div>
          <div className="text-2xl font-bold text-white">${totalRequested.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
        </div>
        <div className="glass rounded-xl border border-slate-700/30 p-4">
          <div className="text-[10px] text-slate-500 uppercase tracking-wider">SF Billed</div>
          <div className="text-2xl font-bold text-emerald-400">${totalPaid.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
        </div>
        <div className="glass rounded-xl border border-slate-700/30 p-4">
          <div className="text-[10px] text-slate-500 uppercase tracking-wider">Outstanding Delta</div>
          <div className={clsx('text-2xl font-bold', totalDelta > 0 ? 'text-amber-400' : 'text-slate-500')}>
            ${totalDelta.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3 mb-3">
        <div className="relative">
          <select value={product} onChange={e => { setProduct(e.target.value); setExpanded(null); setPage(0); }}
            className="bg-slate-900 border border-slate-700 rounded-lg text-xs px-3 py-2 pr-8
                       focus:outline-none focus:ring-2 focus:ring-brand-500/40 appearance-none cursor-pointer text-white">
            {PRODUCTS.map(p => (
              <option key={p.val} value={p.val}>{p.label}</option>
            ))}
          </select>
          <svg className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" /></svg>
        </div>

        <div className="flex items-center bg-slate-800/60 rounded-lg p-0.5 border border-slate-700/50">
          {['open', 'all'].map(s => (
            <button key={s} onClick={() => setStatusFilter(s)}
              className={clsx(
                'px-3 py-1.5 rounded-md text-xs font-medium transition-all',
                statusFilter === s ? 'bg-brand-600/20 text-brand-300' : 'text-slate-500 hover:text-white',
              )}>
              {s === 'open' ? 'Open' : 'All'}
            </button>
          ))}
        </div>

        <div className="flex items-center bg-slate-800/60 rounded-lg p-0.5 border border-slate-700/50">
          {['All', 'Approve', 'Review', 'Credit'].map(f => (
            <button key={f} onClick={() => { setRecFilter(f); setPage(0); setExpanded(null) }}
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

        <div className="flex items-center gap-1.5">
          <input type="date" value={startDate} onChange={e => { setStartDate(e.target.value); setPage(0) }}
            className="bg-slate-900 border border-slate-700 rounded-lg text-xs px-2 py-2 text-white focus:outline-none focus:ring-2 focus:ring-brand-500/40 [color-scheme:dark]" />
          <span className="text-slate-600 text-xs">to</span>
          <input type="date" value={endDate} onChange={e => { setEndDate(e.target.value); setPage(0) }}
            className="bg-slate-900 border border-slate-700 rounded-lg text-xs px-2 py-2 text-white focus:outline-none focus:ring-2 focus:ring-brand-500/40 [color-scheme:dark]" />
          {(startDate || endDate) && (
            <button onClick={() => { setStartDate(''); setEndDate(''); setPage(0) }}
              className="text-[10px] text-slate-500 hover:text-white">✕</button>
          )}
        </div>

        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
          <input value={search} onChange={e => { setSearch(e.target.value); setExpanded(null); setPage(0) }}
            placeholder="Search WOA#, WO#, facility…"
            className="w-full pl-9 pr-4 py-2 bg-slate-900 border border-slate-700 rounded-xl text-sm
                       placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-brand-500/40 transition-all" />
        </div>
      </div>

      {error && !loading && (
        <div className="mb-4 px-4 py-2.5 rounded-xl border border-red-800/30 bg-red-950/10 flex items-center gap-2">
          <AlertTriangle className="w-3.5 h-3.5 text-red-400 shrink-0" />
          <span className="text-xs text-red-300">{error}</span>
        </div>
      )}

      {/* Table */}
      <div className="glass rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b border-slate-800">
                <th className="px-1 py-3 text-[10px] font-semibold uppercase tracking-wider text-slate-500 text-right w-5">#</th>
                <Th label="WOA #"      col="woa_number"    sort={sort} onSort={onSort} />
                <Th label="Facility"   col="facility"      sort={sort} onSort={onSort} />
                <Th label="WO #"       col="wo_number"     sort={sort} onSort={onSort} />
                <Th label="Product"    col="product"       sort={sort} onSort={onSort} />
                <Th label="Requested"  col="requested_qty" sort={sort} onSort={onSort} right />
                <Th label="SF Billed"  col="currently_paid" sort={sort} onSort={onSort} right />
                <Th label="Delta"      col="delta"         sort={sort} onSort={onSort} right />
                <th className="px-3 py-3 text-[10px] font-semibold uppercase tracking-wider text-slate-500 text-left whitespace-nowrap cursor-pointer"
                  onClick={() => onSort('recommendation')}>
                  Recommendation
                  {sort.col === 'recommendation'
                    ? sort.dir === 'asc' ? <ChevronUp className="inline w-3 h-3 ml-0.5 -mt-0.5" /> : <ChevronDown className="inline w-3 h-3 ml-0.5 -mt-0.5" />
                    : <span className="inline-block w-3 ml-0.5" />}
                </th>
                <Th label="Created"    col="created_date"  sort={sort} onSort={onSort} />
                <Th label="Created By" col="created_by"    sort={sort} onSort={onSort} />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/40">
              {loading && [...Array(10)].map((_, i) => (
                <tr key={i}>
                  <td className="px-2 py-3"><div className="skeleton h-3 rounded w-4" /></td>
                  {[...Array(10)].map((__, j) => (
                    <td key={j} className="px-3 py-3.5">
                      <div className={clsx('skeleton h-3.5 rounded', j === 1 ? 'w-32' : 'w-16')} />
                    </td>
                  ))}
                </tr>
              ))}

              {!loading && rows.map((r, idx) => {
                const rowKey = r.id || r.woa_number || idx
                const isExpanded = expanded === rowKey
                const code = productCode(r.product)
                const productClass = PRODUCT_COLORS[code] || PRODUCT_COLORS.MI
                const delta = r.delta || 0
                return (
                  <Fragment key={rowKey}>
                    <tr
                      onClick={() => setExpanded(isExpanded ? null : rowKey)}
                      className={clsx(
                        'cursor-pointer transition-colors group',
                        isExpanded ? 'bg-slate-800/70' : 'hover:bg-slate-800/40',
                      )}
                    >
                      <td className="px-1 py-2 text-[10px] text-slate-500 text-right">{page * PAGE_SIZE + idx + 1}</td>

                      {/* WOA # */}
                      <td className="px-3 py-2.5">
                        {r.id ? (
                          <a href={`https://aaawcny.lightning.force.com/${r.id}`} target="_blank" rel="noopener noreferrer"
                            onClick={e => e.stopPropagation()}
                            className="text-brand-400 hover:text-brand-300 font-mono font-medium hover:underline">
                            {r.woa_number || '--'}
                          </a>
                        ) : (
                          <span className="font-mono text-slate-300">{r.woa_number || '--'}</span>
                        )}
                      </td>

                      {/* Facility */}
                      <td className="px-3 py-2.5 text-slate-300 font-medium truncate max-w-[180px]">{r.facility || '--'}</td>

                      {/* WO # */}
                      <td className="px-3 py-2.5">
                        {r.wo_id ? (
                          <a href={`https://aaawcny.lightning.force.com/${r.wo_id}`} target="_blank" rel="noopener noreferrer"
                            onClick={e => e.stopPropagation()}
                            className="text-brand-400 hover:text-brand-300 font-mono hover:underline">
                            {r.wo_number || '--'}
                          </a>
                        ) : (
                          <span className="font-mono text-slate-400">{r.wo_number || '--'}</span>
                        )}
                      </td>

                      {/* Product */}
                      <td className="px-3 py-2.5">
                        {code || r.product ? (
                          <div className="flex items-center gap-1.5">
                            <span className={clsx('px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wide border', productClass)}>
                              {code || r.product}
                            </span>
                            {r.woli_id && (
                              <a href={`https://aaawcny.lightning.force.com/${r.woli_id}`} target="_blank" rel="noopener noreferrer"
                                onClick={e => e.stopPropagation()}
                                className="text-[9px] text-slate-500 hover:text-brand-400 hover:underline font-mono"
                                title="Open WOLI in Salesforce">
                                WOLI ↗
                              </a>
                            )}
                          </div>
                        ) : (
                          <span className="text-[10px] text-slate-600 italic cursor-help" title="No Work Order Line Items found on this WO. The product type could not be determined.">No WOLI</span>
                        )}
                      </td>

                      {/* Requested — unit-aware */}
                      <td className="px-3 py-2.5 text-right text-slate-300 font-mono">
                        {formatQty(r.requested_qty, r.product)}
                      </td>

                      {/* Paid — unit-aware */}
                      <td className="px-3 py-2.5 text-right font-mono">
                        <span className={r.currently_paid > 0 ? 'text-emerald-400' : 'text-slate-600'}>
                          {r.currently_paid != null ? formatQty(r.currently_paid, r.product) : '--'}
                        </span>
                      </td>

                      {/* Delta — unit-aware */}
                      <td className="px-3 py-2.5 text-right font-mono">
                        <span className={clsx(
                          'font-bold',
                          delta > 0 ? 'text-amber-400' : delta < 0 ? 'text-red-400' : 'text-slate-600',
                        )}>
                          {delta !== 0 ? formatQty(Math.abs(delta), r.product) : formatQty(0, r.product)}
                        </span>
                      </td>

                      {/* Recommendation — hyperlink style, clicks expand the row */}
                      <td className="px-3 py-2.5">
                        {r.recommendation === 'approve'
                          ? <a href="#" onClick={e => { e.preventDefault(); e.stopPropagation(); setExpanded(isExpanded ? null : rowKey) }}
                              className="text-[10px] font-bold text-emerald-400 underline hover:text-emerald-300">✓ Approve</a>
                          : <a href="#" onClick={e => { e.preventDefault(); e.stopPropagation(); setExpanded(isExpanded ? null : rowKey) }}
                              className="text-[10px] font-bold text-amber-400 underline hover:text-amber-300">⚠ Review</a>
                        }
                      </td>

                      {/* Created */}
                      <td className="px-3 py-2.5 text-slate-500 whitespace-nowrap">{r.created_date || '--'}</td>

                      {/* Created By */}
                      <td className="px-3 py-2.5 text-slate-500 truncate max-w-[140px]">{r.created_by || '--'}</td>
                    </tr>

                    {isExpanded && (
                      <tr>
                        <td colSpan={11} className="p-0 border-b border-slate-700/30">
                          <AuditToggle woaId={r.id || r.woa_number} onComplete={handleAuditComplete} recReason={r.rec_reason} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>

        {!loading && rows.length === 0 && (
          <div className="text-center py-16 text-slate-600 text-sm">
            {search || product !== 'All'
              ? 'No adjustments match your filters.'
              : error ? 'Failed to load adjustments.' : 'No work order adjustments found.'}
          </div>
        )}

        {!loading && rows.length > 0 && (
          <div className="px-4 py-2.5 border-t border-slate-800/60 flex items-center justify-between">
            <span className="text-[10px] text-slate-600">
              Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total}
              {product !== 'All' && ` (${product})`}
            </span>
            <div className="flex items-center gap-2">
              <button onClick={() => { setPage(p => Math.max(0, p - 1)); setExpanded(null) }}
                disabled={page === 0}
                className="px-2.5 py-1 rounded text-[10px] font-medium bg-slate-800 hover:bg-slate-700 text-slate-400 disabled:opacity-30 transition-all">
                ← Prev
              </button>
              <span className="text-[10px] text-slate-500">
                Page {page + 1} of {Math.ceil(total / PAGE_SIZE)}
              </span>
              <button onClick={() => { setPage(p => p + 1); setExpanded(null) }}
                disabled={(page + 1) * PAGE_SIZE >= total}
                className="px-2.5 py-1 rounded text-[10px] font-medium bg-slate-800 hover:bg-slate-700 text-slate-400 disabled:opacity-30 transition-all">
                Next →
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
