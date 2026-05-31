import { useState, useEffect, useMemo, Fragment, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { clsx } from 'clsx'
import {
  ChevronUp, ChevronDown,
  AlertTriangle, HelpCircle, X, Camera,
} from 'lucide-react'
import { fetchWOAdjustments, fetchWOAAudit, refreshAccountingWOAs } from '../api'
import AccountingAnalytics from '../components/AccountingAnalytics'
import AccountingToolbar from '../components/AccountingToolbar'
import HelpAccounting from '../components/HelpAccounting'
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
  { val: 'R1', label: 'R1 — RV/Motorhome Service' },
  { val: 'RA', label: 'RA — RV Rate' },
]

const PRODUCT_COLORS = {
  ER: 'bg-blue-500/25 text-blue-300 border-blue-500/50',
  TW: 'bg-purple-500/25 text-purple-300 border-purple-500/50',
  TB: 'bg-purple-500/25 text-purple-300 border-purple-500/50',
  TT: 'bg-purple-500/25 text-purple-300 border-purple-500/50',
  TU: 'bg-purple-500/25 text-purple-300 border-purple-500/50',
  TM: 'bg-purple-500/25 text-purple-300 border-purple-500/50',
  EM: 'bg-purple-500/25 text-purple-300 border-purple-500/50',
  E1: 'bg-orange-500/25 text-orange-300 border-orange-500/50',
  Z8: 'bg-orange-500/25 text-orange-300 border-orange-500/50',
  MH: 'bg-red-500/25 text-red-300 border-red-500/50',
  TL: 'bg-emerald-500/25 text-emerald-300 border-emerald-500/50',
  MI: 'bg-slate-500/25 text-slate-300 border-slate-500/50',
  HO: 'bg-amber-500/25 text-amber-300 border-amber-500/50',
}

const SORT_DEF = {
  woa_number: 'asc', facility: 'asc', wo_number: 'asc', product: 'asc',
  requested_qty: 'desc', currently_paid: 'desc', delta: 'desc',
  recommendation: 'asc', created_date: 'desc', created_by: 'asc',
  owner: 'asc', woa_age_from_wo_days: 'desc', woa_age_days: 'desc',
}

const COL_HELP = {
  woa_number: 'Work Order Adjustment number. This is the garage\'s request for additional payment. Click to open in Salesforce.',
  facility: 'The garage/facility that submitted this adjustment request.',
  wo_number: 'The Work Order this adjustment is for. Click to open in Salesforce.',
  product: 'Product code from the Work Order Line Item (WOLI).\n\nBA = Base Rate — flat fee for showing up\nER = Enroute Miles — miles from truck location to breakdown (SF uses Google Maps to calculate)\nTW = Tow Miles — miles towing vehicle pickup to drop-off destination\nE1 = Extrication 1st Truck — winch-out/recovery time in MINUTES (vehicle stuck in ditch, snow, mud, accident)\nE2 = Extrication 2nd Truck — if a second truck was needed\nMH = Medium/Heavy Duty — vehicle over 10,000 lbs required special equipment\nTL = Tolls/Parking — out-of-pocket costs (tolls on thruway, airport parking, etc.)\nMI = Miscellaneous — usually wait time (member held up the driver)\nBC = Basic Cost\nPC = Plus Cost\n\nHow we verify each:\n• ER/TW: Compare requested miles vs SF Google-calculated distance\n• E1/MI: Compare requested minutes vs actual on-scene time from SA timestamps\n• MH: Check vehicle group (DW=heavy) or weight field\n• TL: Always Review — need receipts\n• BA/BC/PC: Always Review — policy-based\n\nProduct matched to WOA by finding the WOLI with closest quantity.',
  requested_qty: 'What the garage is requesting in this adjustment.\n\nFor ER/TW: miles\nFor E1: minutes\nFor TL: dollar amount\nFor BA/BC/PC: flat rate\n\nNegative = credit/reduction (garage overpaid, adjusting down).',
  currently_paid: 'What SF currently has on the Work Order Line Item for this product.\n\nThis is the quantity that was billed — what the garage was (or will be) paid based on SF\'s auto-calculation.\n\nThe garage submitted this adjustment because they believe this amount is wrong.\n\nSource: WorkOrderLineItem.Quantity in Salesforce.',
  delta: 'Net change: Requested (total claimed) minus SF Billed (currently on WOLI).\n\nDelta = 0  → garage is confirming the SF amount, no additional payment needed.\nDelta > 0  → garage is claiming more than SF calculated, additional payment needed.\nDelta < 0  → credit (garage was overpaid, adjusting down).\n\nThe Recommendation compares the total claimed directly against the SF baseline distance.',
  recommendation: 'Auto-calculated recommendation based on SF data. No AI — pure math.\n\n✓ Approve = Data supports the garage\'s request\n⚠ Review = Data doesn\'t match or is missing. Needs human verification.\n\nHow we verify by product:\n• ER/TW (miles): Requested vs SF Google distance (≤130% = Approve)\n• E1/MI (time): Requested minutes vs actual on-scene time from SA timestamps (≤120% = Approve)\n• MH (weight): Vehicle Group DW/HD = Approve, PS = Review\n• TL (tolls): Always Review — need receipts\n• BA/BC/PC (rates): Always Review — policy-based\n\nSF already uses Google Maps internally — we reuse those distances, no extra API calls.\n\nHover over ⚠ Review for the specific reason.',
  created_date: 'When the adjustment was submitted.',
  created_by: 'Who submitted the adjustment (usually dispatch/garage staff).',
  owner: 'Current owner of the WOA record in Salesforce — who is responsible for reviewing/actioning it.',
  woa_age_from_wo_days: 'Days between WO creation and WOA creation.\n\nHow long after the original call before the garage filed this adjustment.',
  woa_age_days: 'Days since this WOA was created.\n\nHow long this adjustment has been sitting unresolved.',
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
        'px-1.5 py-2 text-[9px] font-semibold uppercase tracking-wider cursor-pointer select-none whitespace-nowrap',
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

// ── Main Page ────────────────────────────────────────────────────────────────

const _SS_KEY = 'acct_filters_v1'
function _loadFilters() {
  try { return JSON.parse(sessionStorage.getItem(_SS_KEY) || 'null') || {} } catch { return {} }
}

export default function Accounting() {
  const navigate = useNavigate()
  const [items, setItems] = useState([])
  const [listCachedAt, setListCachedAt] = useState('')
  const [total, setTotal] = useState(0)
  const [totals, setTotals] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const _f = _loadFilters()
  const [search, setSearch] = useState(_f.search || '')
  const [searchDebounce, setSearchDebounce] = useState(_f.search || '')
  const [product, setProduct] = useState(_f.product || 'All')
  const [recFilter, setRecFilter] = useState(_f.recFilter || 'All')
  const [statusFilter, setStatusFilter] = useState(_f.statusFilter || 'New')
  const [startDate, setStartDate] = useState(_f.startDate || '')
  const [endDate, setEndDate] = useState(_f.endDate || '')
  const [sort, setSort] = useState(_f.sort || { col: 'created_date', dir: 'desc' })
  const [page, setPage] = useState(_f.page || 0)
  const [activeTab, setActiveTab] = useState(_f.activeTab || 'woa')
  const [auditOverrides, setAuditOverrides] = useState({})
  const _prefetchTimer = useRef(null)
  const _prefetching = useRef(new Set())
  const PAGE_SIZE = 50

  // Persist filters so they survive navigation to/from detail page
  useEffect(() => {
    try {
      sessionStorage.setItem(_SS_KEY, JSON.stringify({
        search, product, recFilter, statusFilter, startDate, endDate, sort, page, activeTab,
      }))
    } catch { /* ignore quota errors */ }
  }, [search, product, recFilter, statusFilter, startDate, endDate, sort, page, activeTab])

  const prefetchAudit = useCallback((woaId) => {
    if (!woaId || _prefetching.current.has(woaId)) return
    _prefetchTimer.current = setTimeout(() => {
      _prefetching.current.add(woaId)
      fetchWOAAudit(woaId).catch(() => {}).finally(() => _prefetching.current.delete(woaId))
    }, 400)
  }, [])
  const cancelPrefetch = useCallback(() => {
    clearTimeout(_prefetchTimer.current)
  }, [])
  const handleAuditComplete = useCallback((woaId, { recommendation, confidence }) => {
    if (woaId && recommendation) {
      setAuditOverrides(prev => ({ ...prev, [woaId]: { recommendation, confidence } }))
    }
  }, [])

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    fetchWOAdjustments(statusFilter, page, PAGE_SIZE, product === 'All' ? '' : product, recFilter === 'All' ? '' : recFilter, searchDebounce, sort.col, sort.dir, startDate, endDate)
      .then(data => {
        setItems(data.items || [])
        setListCachedAt(data.cached_at || '')
        // Stagger-prefetch first 15 New WOAs so drill-down is instant
        const toWarm = (data.items || []).filter(r => r.status === 'New').slice(0, 15)
        if (toWarm.length > 0) {
          setTimeout(() => {
            toWarm.forEach((item, i) => {
              setTimeout(() => {
                if (item.id && !_prefetching.current.has(item.id)) {
                  _prefetching.current.add(item.id)
                  fetchWOAAudit(item.id).catch(() => {}).finally(() => _prefetching.current.delete(item.id))
                }
              }, i * 400)
            })
          }, 2000)
        }
        setTotal(data.total || 0)
        setTotals(data.totals || {})
      })
      .catch(e => setError(e.message || 'Failed to load adjustments'))
      .finally(() => setLoading(false))
  }, [statusFilter, page, product, recFilter, searchDebounce, sort, startDate, endDate])

  const handleRefresh = useCallback(() => {
    setLoading(true)
    setError(null)
    refreshAccountingWOAs()
      .then(() => fetchWOAdjustments(
        statusFilter, page, PAGE_SIZE,
        product === 'All' ? '' : product,
        recFilter === 'All' ? '' : recFilter,
        searchDebounce, sort.col, sort.dir, startDate, endDate,
      ))
      .then(data => { setItems(data.items || []); setTotal(data.total || 0); setTotals(data.totals || {}); setListCachedAt(data.cached_at || '') })
      .catch(e => setError(e.message || 'Failed to refresh adjustments'))
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
      // WOA quantity = total claimed; delta = net additional vs what's already billed
      delta: (r.requested_qty || 0) - (r.currently_paid || 0),
    }))
  }, [items])

  function onSort(col) {
    setSort(prev => prev.col === col
      ? { col, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
      : { col, dir: SORT_DEF[col] ?? 'asc' }
    )
    setPage(0)
  }

  const totalRequested = totals.requested || 0
  const totalPaid = totals.billed || 0
  const totalDelta = totals.delta || 0

  return (
    <div>
      <AccountingToolbar
        total={total}
        listCachedAt={listCachedAt}
        statusFilter={statusFilter}
        product={product}
        recFilter={recFilter}
        startDate={startDate}
        endDate={endDate}
        search={search}
        searchDebounce={searchDebounce}
        loading={loading}
        activeTab={activeTab}
        products={PRODUCTS}
        onStatusFilterChange={(value) => { setStatusFilter(value); setPage(0) }}
        onProductChange={(value) => { setProduct(value); setPage(0) }}
        onRecFilterChange={(value) => { setRecFilter(value); setPage(0) }}
        onStartDateChange={(value) => { setStartDate(value); setPage(0) }}
        onEndDateChange={(value) => { setEndDate(value); setPage(0) }}
        onClearDates={() => { setStartDate(''); setEndDate(''); setPage(0) }}
        onSearchChange={(value) => { setSearch(value); setPage(0) }}
        onRefresh={handleRefresh}
        onTabChange={setActiveTab}
      />

      {activeTab === 'analytics' && <AccountingAnalytics status={statusFilter}
        onDrillDown={(prod) => { setProduct(prod); setActiveTab('woa'); setPage(0); }} />}

      {activeTab === 'help' && <HelpAccounting />}

      {activeTab === 'woa' && <>
      {/* KPIs */}
      <div className="grid grid-cols-4 gap-3 mb-4">
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

      {error && !loading && (
        <div className="mb-4 px-4 py-2.5 rounded-xl border border-red-800/30 bg-red-950/10 flex items-center gap-2">
          <AlertTriangle className="w-3.5 h-3.5 text-red-400 shrink-0" />
          <span className="text-xs text-red-300">{error}</span>
        </div>
      )}

      {/* Table */}
      {(() => {
      const isPgView = product === 'PG'
      return (
      <div className="glass rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-[10px]">
            <thead>
              <tr className="border-b border-slate-800">
                <th className="px-1 py-2 text-[9px] font-semibold uppercase tracking-wider text-slate-500 text-right w-4">#</th>
                <Th label="WOA #"      col="woa_number"    sort={sort} onSort={onSort} />
                <Th label="Facility"   col="facility"      sort={sort} onSort={onSort} />
                <Th label="Prog" col="program" sort={sort} onSort={onSort} />
                <Th label="WO #"       col="wo_number"     sort={sort} onSort={onSort} />
                <Th label="Product"    col="product"       sort={sort} onSort={onSort} />
                {isPgView ? (
                  <>
                    <Th label="Disp"   col="dispatch_code"   sort={sort} onSort={onSort} />
                    <Th label="Res" col="resolution_code" sort={sort} onSort={onSort} />
                    <Th label="Cov"   col="coverage_level"  sort={sort} onSort={onSort} />
                    <th className="px-1.5 py-2 text-[9px] font-semibold uppercase tracking-wider text-slate-500 text-left whitespace-nowrap">CC</th>
                  </>
                ) : (
                  <th className="px-1.5 py-2 text-[9px] font-semibold uppercase tracking-wider text-slate-500 text-right whitespace-nowrap cursor-pointer"
                    onClick={() => onSort('requested_usd')}
                    title="Estimated dollar value of the claim — requested qty × reference rate. Rates are configurable in Admin → Accounting Rates. May not match your contract.">
                    Est. $<span className="text-slate-600 ml-0.5">?</span>
                    {sort.col === 'requested_usd'
                      ? sort.dir === 'asc' ? <ChevronUp className="inline w-3 h-3 ml-0.5 -mt-0.5" /> : <ChevronDown className="inline w-3 h-3 ml-0.5 -mt-0.5" />
                      : <span className="inline-block w-3 ml-0.5" />}
                  </th>
                )}
                <Th label="Req"  col="requested_qty" sort={sort} onSort={onSort} right />
                <Th label="Billed"  col="currently_paid" sort={sort} onSort={onSort} right />
                <Th label="Δ"      col="delta"         sort={sort} onSort={onSort} right />
                <th className="px-1.5 py-2 text-[9px] font-semibold uppercase tracking-wider text-slate-500 text-left whitespace-nowrap cursor-pointer"
                  onClick={() => onSort('recommendation')}>
                  Rec
                  {sort.col === 'recommendation'
                    ? sort.dir === 'asc' ? <ChevronUp className="inline w-3 h-3 ml-0.5 -mt-0.5" /> : <ChevronDown className="inline w-3 h-3 ml-0.5 -mt-0.5" />
                    : <span className="inline-block w-3 ml-0.5" />}
                </th>
                {!isPgView && <Th label="Owner"   col="owner"        sort={sort} onSort={onSort} />}
                {!isPgView && <Th label="WOA Age" col="woa_age_days" sort={sort} onSort={onSort} right />}
                <Th label="W→W"    col="woa_age_from_wo_days" sort={sort} onSort={onSort} right />
                <Th label="Date"    col="created_date"  sort={sort} onSort={onSort} />
                <th className="px-1.5 py-2 text-[9px] font-semibold uppercase tracking-wider text-slate-500 text-left whitespace-nowrap">
                  {isPgView ? 'WOA Desc' : 'Desc'}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/40">
              {loading && [...Array(10)].map((_, i) => (
                <tr key={i}>
                  <td className="px-1 py-2"><div className="skeleton h-3 rounded w-4" /></td>
                  {[...Array(15)].map((__, j) => (
                    <td key={j} className="px-2 py-2">
                      <div className={clsx('skeleton h-3.5 rounded', j === 1 ? 'w-28' : 'w-14')} />
                    </td>
                  ))}
                </tr>
              ))}

              {!loading && rows.map((r, idx) => {
                const rowKey = r.id || r.woa_number || idx
                const code = productCode(r.product)
                const productClass = PRODUCT_COLORS[code] || PRODUCT_COLORS.MI
                const delta = r.delta || 0
                const isLowMat = r.is_low_materiality
                return (
                  <Fragment key={rowKey}>
                    <tr
                      onClick={() => navigate(`/accounting/woa/${encodeURIComponent(r.id || r.woa_number)}`, { state: { row: r, rows } })}
                      onMouseEnter={() => prefetchAudit(r.id)}
                      onMouseLeave={cancelPrefetch}
                      className={clsx(
                        'cursor-pointer transition-colors group hover:bg-slate-800/40',
                        isLowMat && 'opacity-60',
                      )}
                    >
                      <td className="px-1 py-1.5 text-[9px] text-slate-500 text-right">{page * PAGE_SIZE + idx + 1}</td>

                      {/* WOA # */}
                      <td className="px-1.5 py-1.5">
                        <div className="flex flex-col gap-0.5">
                          <div className="flex items-center gap-1">
                            {r.id ? (
                              <a href={`https://aaawcny.lightning.force.com/${r.id}`} target="_blank" rel="noopener noreferrer"
                                onClick={e => e.stopPropagation()}
                                className="text-brand-400 hover:text-brand-300 font-mono font-medium hover:underline">
                                {r.woa_number || '--'}
                              </a>
                            ) : (
                              <span className="font-mono text-slate-300">{r.woa_number || '--'}</span>
                            )}
                            {r.has_photos && (
                              <Camera className="w-3.5 h-3.5 text-emerald-400 shrink-0" title="Service photos on file" />
                            )}
                          </div>
                          {r.wo_woa_count > 1 && (
                            <span className="text-[9px] text-slate-500"
                              title={`This Work Order has ${r.wo_woa_count} adjustments submitted`}>
                              {r.wo_woa_count} WOAs on WO
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Facility / Territory */}
                      <td className="px-1.5 py-1.5">
                        <div className="flex flex-col gap-0">
                          {r.parent_territory && (
                            <span className="text-[9px] text-brand-400 font-mono font-semibold tracking-wide">{r.parent_territory}</span>
                          )}
                          <span className="text-slate-300 font-medium truncate max-w-[90px] block" title={r.facility}>{r.facility || '--'}</span>
                        </div>
                      </td>

                      {/* Program */}
                      <td className="px-1.5 py-1.5 whitespace-nowrap">
                        {r.program ? (
                          <span className={clsx(
                            'px-1.5 py-0.5 rounded text-[9px] font-semibold border',
                            r.program === 'Standard'       && 'bg-slate-700/40 text-slate-300 border-slate-600/40',
                            r.program === 'RAP'            && 'bg-amber-500/15 text-amber-400 border-amber-500/30',
                            r.program === 'Reciprocal'     && 'bg-amber-500/15 text-amber-400 border-amber-500/30',
                            r.program === 'Thruway'        && 'bg-purple-500/15 text-purple-400 border-purple-500/30',
                            r.program === 'Private Service' && 'bg-slate-600/30 text-slate-400 border-slate-600/30',
                            r.program === 'Authorization'  && 'bg-sky-500/15 text-sky-400 border-sky-500/30',
                            !['Standard','RAP','Reciprocal','Thruway','Private Service','Authorization'].includes(r.program) && 'bg-slate-700/40 text-slate-400 border-slate-600/40',
                          )}>
                            {r.program}
                          </span>
                        ) : (
                          <span className="text-slate-600">--</span>
                        )}
                      </td>

                      {/* WO # */}
                      <td className="px-1.5 py-1.5">
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
                      <td className="px-1.5 py-1.5">
                        {code || r.product ? (
                          <div className="flex flex-col gap-0.5">
                            <div className="flex items-center gap-1.5">
                              <span className={clsx('px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wide border', productClass)}>
                                {code || r.product}
                              </span>
                              {r.product_synthetic && (
                                <span className="text-[9px] text-amber-400 font-bold cursor-help" title="Product inferred from tow estimate — no TW line item on WO. Verify in Salesforce.">?</span>
                              )}
                              {r.is_possible_duplicate && (
                                <span className="px-1 py-0.5 rounded text-[8px] font-bold bg-red-500/20 text-red-400 border border-red-500/40 cursor-help"
                                  title={`Another WOA on Work Order ${r.wo_number} has nearly identical ${r.code} quantity. Likely a double-submit — cancel the extra one in Salesforce before approving.`}>
                                  DUPE?
                                </span>
                              )}
                              {r.is_multi_same_product && (
                                <span className="px-1 py-0.5 rounded text-[8px] font-bold bg-amber-500/20 text-amber-400 border border-amber-500/40 cursor-help"
                                  title={`Multiple ${r.code} adjustments on Work Order ${r.wo_number} with different quantities. Could be split billing or a correction — evaluate both together before approving.`}>
                                  MULTI
                                </span>
                              )}
                              {r.is_oot_private_service && (
                                <span className="px-1 py-0.5 rounded text-[8px] font-bold bg-orange-500/20 text-orange-400 border border-orange-500/40 cursor-help"
                                  title="OOT – Verify Private Service: Work Order is marked Unable To Complete (Dupe), Out of Territory, and Type = Private Service. Verify service legitimacy before approving.">
                                  OOT PS
                                </span>
                              )}
                              {r.woli_id && (
                                <a href={`https://aaawcny.lightning.force.com/${r.woli_id}`} target="_blank" rel="noopener noreferrer"
                                  onClick={e => e.stopPropagation()}
                                  className="text-[9px] text-brand-400 hover:text-brand-300 hover:underline font-mono"
                                  title="Open WOLI in Salesforce">
                                  WOLI ↗
                                </a>
                              )}
                            </div>
                            {r.all_products && (
                              <span className="text-[9px] text-slate-500 font-mono truncate max-w-[100px] block" title={`All non-BA products on this WO: ${r.all_products}`}>
                                {r.all_products}
                              </span>
                            )}
                            {r.service_type && (
                              <span className="text-[9px] text-slate-500">{r.service_type}</span>
                            )}
                          </div>
                        ) : (
                          <span className="text-[10px] text-slate-600 italic cursor-help" title="No Work Order Line Items found on this WO. The product type could not be determined.">No WOLI</span>
                        )}
                      </td>

                      {/* Est. $ (default) or PG dispatch/resolution/coverage/CC columns */}
                      {isPgView ? (
                        <>
                          <td className="px-1.5 py-1.5 font-mono text-slate-300">{r.dispatch_code || <span className="text-slate-700">—</span>}</td>
                          <td className="px-1.5 py-1.5 font-mono text-slate-300">{r.resolution_code || <span className="text-slate-700">—</span>}</td>
                          <td className="px-1.5 py-1.5 text-slate-300">{r.coverage_level || <span className="text-slate-500 italic text-[9px]">blank</span>}</td>
                          <td className="px-1.5 py-1.5 text-center">
                            {r.credit_card_on_file
                              ? <span className="text-emerald-400 font-bold text-[10px]">✓</span>
                              : <span className="text-slate-700 text-[10px]">—</span>}
                          </td>
                        </>
                      ) : (
                        <td className="px-1.5 py-1.5 text-right font-mono"
                          title="Estimated dollar value — requested qty × reference rate. See Admin → Accounting Rates to update rates.">
                          {r.requested_usd != null
                            ? <span className="text-slate-300">~${r.requested_usd.toFixed(2)}</span>
                            : <span className="text-slate-700">—</span>}
                        </td>
                      )}

                      {/* Requested — unit-aware */}
                      <td className="px-1.5 py-1.5 text-right text-slate-300 font-mono">
                        {formatQty(r.requested_qty, r.product)}
                      </td>

                      {/* Paid — unit-aware */}
                      <td className="px-1.5 py-1.5 text-right font-mono">
                        <span className={r.currently_paid > 0 ? 'text-emerald-400' : 'text-slate-600'}>
                          {r.currently_paid != null ? formatQty(r.currently_paid, r.product) : '--'}
                        </span>
                      </td>

                      {/* Delta — unit-aware */}
                      <td className="px-1.5 py-1.5 text-right font-mono">
                        <span className={clsx(
                          'font-bold',
                          delta > 0 ? 'text-amber-400' : delta < 0 ? 'text-red-400' : 'text-slate-600',
                        )}>
                          {delta !== 0 ? formatQty(Math.abs(delta), r.product) : formatQty(0, r.product)}
                        </span>
                      </td>

                      {/* Recommendation — use audit result once opened, fall back to pre-computed */}
                      <td className="px-1.5 py-1.5">
                        <div className="flex flex-col gap-0.5">
                          <div className="flex items-center gap-0.5">
                            {(() => {
                              const audited = !!auditOverrides[rowKey]
                              const effectiveRec = (auditOverrides[rowKey]?.recommendation || r.recommendation || '').toLowerCase()
                              const isTimeProduct = ['MI','E1','E2','Z8'].includes(code)
                              const provisional = !audited && isTimeProduct
                              return effectiveRec === 'approve'
                                ? <a href="#" onClick={e => { e.preventDefault(); e.stopPropagation(); navigate(`/accounting/woa/${encodeURIComponent(r.id || r.woa_number)}`, { state: { row: r, rows } }) }}
                                    className="text-[10px] font-bold text-emerald-400 underline hover:text-emerald-300"
                                    title={provisional ? 'Provisional — open to verify (list uses travel time; audit uses actual on-scene time)' : isLowMat ? `Auto-approved — estimated impact $${r.estimated_usd?.toFixed(2)} is below the materiality threshold` : undefined}>
                                    ✓ Approve{provisional ? '*' : ''}
                                  </a>
                                : effectiveRec === 'reject'
                                ? <a href="#" onClick={e => { e.preventDefault(); e.stopPropagation(); navigate(`/accounting/woa/${encodeURIComponent(r.id || r.woa_number)}`, { state: { row: r, rows } }) }}
                                    className="text-[10px] font-bold text-red-400 underline hover:text-red-300">
                                    ✗ Reject
                                  </a>
                                : <a href="#" onClick={e => { e.preventDefault(); e.stopPropagation(); navigate(`/accounting/woa/${encodeURIComponent(r.id || r.woa_number)}`, { state: { row: r, rows } }) }}
                                    className="text-[10px] font-bold text-amber-400 underline hover:text-amber-300"
                                    title={provisional ? 'Provisional — open to verify (list uses travel time; audit uses actual on-scene time)' : undefined}>
                                    ⚠ Review{provisional ? '*' : ''}
                                  </a>
                            })()}
                            {r.rec_reason && <HelpTip text={r.rec_reason} />}
                          </div>
                          {code === 'MH' && r.vehicle_display && (
                            <span className="text-[9px] text-slate-400 leading-tight">{r.vehicle_display}</span>
                          )}
                          {code === 'MH' && r.review_note && (
                            <span className="text-[9px] text-amber-500/80 italic leading-tight">{r.review_note}</span>
                          )}
                        </div>
                      </td>

                      {/* Owner — hidden in PG view */}
                      {!isPgView && <td className="px-1.5 py-1.5 text-slate-500 truncate max-w-[60px]">{r.owner || '--'}</td>}

                      {/* WOA Age — hidden in PG view */}
                      {!isPgView && (
                        <td className="px-1.5 py-1.5 text-right font-mono text-[9px]">
                          {r.woa_age_days != null
                            ? <span className={clsx(r.woa_age_days > 90 ? 'text-red-400' : r.woa_age_days > 30 ? 'text-amber-400' : 'text-slate-400')}>{r.woa_age_days}d</span>
                            : <span className="text-slate-700">--</span>}
                        </td>
                      )}

                      {/* WO→WOA */}
                      <td className="px-1 py-1.5 text-right font-mono text-[9px] w-8">
                        {r.woa_age_from_wo_days != null
                          ? <span className={clsx(r.woa_age_from_wo_days > 90 ? 'text-red-400' : r.woa_age_from_wo_days > 30 ? 'text-amber-400' : 'text-slate-400')}>{r.woa_age_from_wo_days}d</span>
                          : <span className="text-slate-700">--</span>}
                      </td>

                      {/* Created */}
                      <td className="px-1.5 py-1.5 text-slate-500 whitespace-nowrap" title={r.created_date}>{r.created_date ? r.created_date.slice(0, 5) : '--'}</td>

                      {/* Description / WOA Description */}
                      <td className="px-1.5 py-1.5 text-slate-500 max-w-[120px]">
                        {isPgView ? (
                          r.woa_description
                            ? <span title={r.woa_description} className="truncate block cursor-help">{r.woa_description.slice(0, 35)}{r.woa_description.length > 35 ? '…' : ''}</span>
                            : <span className="text-slate-700">—</span>
                        ) : (
                          r.description
                            ? <span title={r.description} className="truncate block cursor-help">{r.description.slice(0, 35)}{r.description.length > 35 ? '…' : ''}</span>
                            : <span className="text-slate-700">—</span>
                        )}
                      </td>
                    </tr>

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
              <button onClick={() => { setPage(p => Math.max(0, p - 1)) }}
                disabled={page === 0}
                className="px-2.5 py-1 rounded text-[10px] font-medium bg-slate-800 hover:bg-slate-700 text-slate-400 disabled:opacity-30 transition-all">
                ← Prev
              </button>
              <span className="text-[10px] text-slate-500">
                Page {page + 1} of {Math.ceil(total / PAGE_SIZE)}
              </span>
              <button onClick={() => { setPage(p => p + 1) }}
                disabled={(page + 1) * PAGE_SIZE >= total}
                className="px-2.5 py-1 rounded text-[10px] font-medium bg-slate-800 hover:bg-slate-700 text-slate-400 disabled:opacity-30 transition-all">
                Next →
              </button>
            </div>
          </div>
        )}
      </div>
      )})()}
      </>}
    </div>
  )
}
