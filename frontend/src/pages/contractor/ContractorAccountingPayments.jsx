import { useState, useCallback, useMemo } from 'react'
import { Loader2, AlertTriangle, ChevronDown, ChevronRight } from 'lucide-react'

const PRODUCT_ORDER = ['BA', 'ER', 'TW', 'TL', 'PG', 'MH']

function fmt(v) {
  if (v == null) return '—'
  return '$' + Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
function fmtNz(v) {
  return (!v || v === 0) ? '—' : fmt(v)
}

function defaultDates() {
  const end = new Date()
  const start = new Date()
  start.setDate(end.getDate() - 30)
  const iso = d => d.toISOString().slice(0, 10)
  return { start: iso(start), end: iso(end) }
}

function groupByWO(items) {
  const map = {}
  for (const item of items) {
    const key = item.wo_id || item.wo_number
    if (!map[key]) {
      map[key] = {
        wo_number: item.wo_number,
        wo_id: item.wo_id,
        facility: item.facility,
        call_type: item.call_type,
        created_date: item.created_date,
        status: item.status,
        wolis: [],
        total: 0,
        tax_total: 0,
      }
    }
    map[key].wolis.push(item)
    map[key].total = Math.round((map[key].total + (item.total_price || 0)) * 100) / 100
    map[key].tax_total = Math.round((map[key].tax_total + (item.tax_amount || 0)) * 100) / 100
  }
  return Object.values(map)
}

function buildPivot(items) {
  const pivot = {}
  const codes = new Set()
  for (const item of items) {
    const f = item.facility || '—'
    const c = item.product_code || '?'
    codes.add(c)
    if (!pivot[f]) pivot[f] = { _total: 0 }
    pivot[f][c] = (pivot[f][c] || 0) + (item.total_price || 0)
    pivot[f]._total += (item.total_price || 0)
  }
  const sortedCodes = [...codes].sort((a, b) => {
    const ia = PRODUCT_ORDER.indexOf(a), ib = PRODUCT_ORDER.indexOf(b)
    if (ia >= 0 && ib >= 0) return ia - ib
    if (ia >= 0) return -1
    if (ib >= 0) return 1
    return a.localeCompare(b)
  })
  return { pivot, codes: sortedCodes, facilities: Object.keys(pivot).sort() }
}

function BillingBreakdown({ items }) {
  const { pivot, codes, facilities } = useMemo(() => buildPivot(items), [items])
  if (!facilities.length) return null
  const grandTotal = facilities.reduce((s, f) => s + pivot[f]._total, 0)
  return (
    <div className="glass rounded-xl overflow-hidden mb-4">
      <div className="px-4 py-2.5 border-b border-slate-800/60">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
          Billing by Garage &amp; Product Type
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="border-b border-slate-800">
              <th className="px-3 py-2 text-left text-[10px] text-slate-500 font-semibold uppercase tracking-wider">Facility</th>
              {codes.map(c => (
                <th key={c} className="px-3 py-2 text-right text-[10px] text-slate-500 font-semibold uppercase tracking-wider">{c}</th>
              ))}
              <th className="px-3 py-2 text-right text-[10px] text-slate-500 font-semibold uppercase tracking-wider">Total</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/40">
            {facilities.map(f => (
              <tr key={f} className="hover:bg-slate-800/20">
                <td className="px-3 py-2 text-slate-200 font-medium">{f}</td>
                {codes.map(c => (
                  <td key={c} className="px-3 py-2 text-right font-mono text-slate-400">{fmtNz(pivot[f][c])}</td>
                ))}
                <td className="px-3 py-2 text-right font-mono font-semibold text-emerald-400">{fmt(pivot[f]._total)}</td>
              </tr>
            ))}
            {facilities.length > 1 && (
              <tr className="bg-slate-800/30 border-t border-slate-700/50">
                <td className="px-3 py-2 text-slate-200 font-semibold">All Garages</td>
                {codes.map(c => {
                  const t = facilities.reduce((s, f) => s + (pivot[f][c] || 0), 0)
                  return <td key={c} className="px-3 py-2 text-right font-mono text-slate-300">{fmtNz(t)}</td>
                })}
                <td className="px-3 py-2 text-right font-mono font-bold text-emerald-300">{fmt(grandTotal)}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function WORow({ wo }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <tr
        onClick={() => setOpen(o => !o)}
        className="hover:bg-slate-800/40 cursor-pointer transition-colors border-b border-slate-800/40"
      >
        <td className="px-2 py-2 text-slate-600 w-6">
          {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </td>
        <td className="px-2 py-2 font-mono">
          {wo.wo_id
            ? <a href={`https://aaawcny.lightning.force.com/${wo.wo_id}`}
                 target="_blank" rel="noopener noreferrer"
                 onClick={e => e.stopPropagation()}
                 className="text-indigo-400 hover:underline">{wo.wo_number || '—'}</a>
            : <span className="text-slate-300">{wo.wo_number || '—'}</span>}
        </td>
        <td className="px-2 py-2 text-slate-300">{wo.facility || '—'}</td>
        <td className="px-2 py-2 text-slate-400 whitespace-nowrap">{wo.created_date?.slice(0, 10) || '—'}</td>
        <td className="px-2 py-2 text-slate-500 text-[10px]">
          {wo.wolis.length} item{wo.wolis.length !== 1 ? 's' : ''}
        </td>
        <td className="px-2 py-2 text-right font-mono font-semibold text-emerald-400">{fmt(wo.total)}</td>
      </tr>
      {open && wo.wolis.map((woli, i) => (
        <tr key={woli.woli_id || i} className="bg-slate-900/60 border-b border-slate-800/20">
          <td className="px-2 py-1.5" />
          <td className="px-2 py-1.5 pl-8 font-mono text-[10px] text-slate-600">{woli.woli_id?.slice(-8) || '—'}</td>
          <td className="px-2 py-1.5" />
          <td className="px-2 py-1.5">
            <span className="font-mono text-slate-300 text-[10px] font-semibold">{woli.product_code}</span>
            {woli.product_name && (
              <span className="ml-1.5 text-slate-500 text-[10px]">{woli.product_name}</span>
            )}
          </td>
          <td className="px-2 py-1.5 text-right text-[10px] text-slate-500">
            {woli.quantity != null ? `×${woli.quantity}` : '—'}
          </td>
          <td className="px-2 py-1.5 text-right font-mono text-[10px] text-emerald-300 font-semibold">
            {fmt(woli.total_price)}
          </td>
        </tr>
      ))}
    </>
  )
}

export default function ContractorAccountingPayments() {
  const { start: defStart, end: defEnd } = defaultDates()
  const [startDate, setStartDate] = useState(defStart)
  const [endDate, setEndDate] = useState(defEnd)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [fetched, setFetched] = useState(false)

  const fetchData = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const params = new URLSearchParams({ start_date: startDate, end_date: endDate, page: 1, page_size: 2000 })
      const res = await fetch(`/api/contractor/wo-payments?${params}`)
      if (!res.ok) throw new Error(`Server error ${res.status}`)
      setData(await res.json())
      setFetched(true)
    } catch (e) {
      setError(e.message || 'Failed to load payment report')
    } finally {
      setLoading(false)
    }
  }, [startDate, endDate])

  const allItems = data?.items || []
  const woList = useMemo(() => groupByWO(allItems), [allItems])

  return (
    <div>
      {/* Date controls */}
      <div className="glass rounded-xl border border-slate-700/30 p-4 mb-4 flex flex-wrap items-end gap-4">
        <div className="flex flex-col gap-1">
          <label className="text-[10px] text-slate-500 uppercase tracking-wider">Start Date</label>
          <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/50" />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] text-slate-500 uppercase tracking-wider">End Date</label>
          <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/50" />
        </div>
        <button onClick={fetchData} disabled={loading}
          className="flex items-center gap-2 px-5 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-semibold transition-all">
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
          {loading ? 'Loading…' : 'Generate Report'}
        </button>
      </div>

      {/* Summary cards */}
      {fetched && !loading && data && (
        <div className="grid grid-cols-2 gap-3 mb-4">
          <div className="glass rounded-xl border border-slate-700/30 p-4">
            <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Total Payment</div>
            <div className="text-2xl font-bold text-emerald-400">{fmt(data.total_payment)}</div>
          </div>
          <div className="glass rounded-xl border border-slate-700/30 p-4">
            <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Work Orders</div>
            <div className="text-2xl font-bold text-white">{woList.length.toLocaleString()}</div>
          </div>
        </div>
      )}

      {error && (
        <div className="mb-4 px-4 py-2.5 rounded-xl border border-red-800/30 bg-red-950/10 flex items-center gap-2">
          <AlertTriangle className="w-3.5 h-3.5 text-red-400 shrink-0" />
          <span className="text-xs text-red-300">{error}</span>
        </div>
      )}

      {!fetched && !loading && !error && (
        <div className="glass rounded-xl border border-slate-700/30 py-16 text-center text-slate-500 text-sm">
          Select a date range and click Generate Report to view payments.
        </div>
      )}

      {fetched && allItems.length > 0 && (
        <>
          <BillingBreakdown items={allItems} />

          <div className="glass rounded-xl overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="border-b border-slate-800">
                    <th className="px-2 py-2 w-6" />
                    {['WO Number', 'Facility', 'Date', 'Line Items', 'Total'].map((h, i) => (
                      <th key={h}
                        className={`px-2 py-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500 whitespace-nowrap ${i >= 3 ? 'text-right' : 'text-left'}`}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {loading && [...Array(8)].map((_, i) => (
                    <tr key={i} className="border-b border-slate-800/40">
                      {[...Array(6)].map((__, j) => (
                        <td key={j} className="px-2 py-2"><div className="skeleton h-3.5 rounded w-16" /></td>
                      ))}
                    </tr>
                  ))}
                  {!loading && woList.map(wo => <WORow key={wo.wo_id || wo.wo_number} wo={wo} />)}
                </tbody>
              </table>
            </div>
            {!loading && woList.length === 0 && (
              <div className="py-12 text-center text-slate-600 text-sm">No payment records found for this date range.</div>
            )}
            {!loading && woList.length > 0 && (
              <div className="px-4 py-2.5 border-t border-slate-800/60 text-[10px] text-slate-600">
                {woList.length} work orders · {allItems.length} line items total
                {data?.total > allItems.length && (
                  <span className="text-amber-500 ml-2">
                    (showing first {allItems.length} of {data.total} — narrow the date range to see all)
                  </span>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
