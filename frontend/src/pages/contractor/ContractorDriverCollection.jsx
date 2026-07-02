import { useState, useCallback, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2, AlertTriangle, ExternalLink, Download, ChevronUp, ChevronDown, ArrowUpDown, Camera } from 'lucide-react'
import { InfoTip } from '../../components/CommandCenterUtils'
import Paginator from '../../components/Paginator'
import { contractorWoLink } from '../../utils/sfLinks'
import MiniDatePicker from '../../components/MiniDatePicker'

const PAGE_SIZE = 100

function defaultDates() {
  const now = new Date()
  const start = new Date(now.getFullYear(), now.getMonth(), 1)
  const iso = d => d.toISOString().slice(0, 10)
  return { start: iso(start), end: iso(now) }
}

function SortIcon({ col, sortCol, sortDir }) {
  if (sortCol !== col) return <ArrowUpDown size={10} className="text-slate-600 ml-0.5" />
  return sortDir === 'asc'
    ? <ChevronUp size={10} className="text-indigo-400 ml-0.5" />
    : <ChevronDown size={10} className="text-indigo-400 ml-0.5" />
}

const COLUMNS = [
  { key: 'wo_number',             label: 'Work Order #',         sortFn: (a, b) => (a.wo_number || '').localeCompare(b.wo_number || '') },
  { key: 'service_resource_name', label: 'Service Resource',     sortFn: (a, b) => (a.service_resource_name || '').localeCompare(b.service_resource_name || '') },
  { key: 'reason',                label: 'Collection Reason',    sortFn: (a, b) => (a.reason || '').localeCompare(b.reason || '') },
  { key: 'amount',                label: 'Amount',               sortFn: (a, b) => (a.amount || '').localeCompare(b.amount || '') },
  { key: 'call_type',             label: 'Call Type',            sortFn: (a, b) => (a.call_type || '').localeCompare(b.call_type || '') },
  { key: 'dispatch_code',         label: 'Dispatch Code',        sortFn: (a, b) => (a.dispatch_code || '').localeCompare(b.dispatch_code || '') },
  { key: 'resolution_code',       label: 'Resolution Code',      sortFn: (a, b) => (a.resolution_code || '').localeCompare(b.resolution_code || '') },
  { key: 'coverage',              label: 'Entitlement Coverage', sortFn: (a, b) => (a.coverage || '').localeCompare(b.coverage || '') },
]

function rowKey(r) {
  return `${r.wo_id}::${r.reason}`
}

function exportCSV(rows) {
  const headers = COLUMNS.map(c => c.label).concat(['SF Link', 'Audit Verified'])
  const lines = [
    headers.join(','),
    ...rows.map(r => [
      r.wo_number ? `WO-${r.wo_number}` : '',
      r.service_resource_name, r.reason, r.amount, r.call_type,
      r.dispatch_code, r.resolution_code, r.coverage,
      r.wo_id ? contractorWoLink(r.wo_id) : '',
      r.audit_verified ? 'Yes' : 'No',
    ].map(v => `"${(v || '').toString().replace(/"/g, '""')}"`).join(','))
  ]
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `driver-collection-${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
}

export default function ContractorDriverCollection({ startDate, endDate, setStartDate, setEndDate }) {
  const navigate = useNavigate()
  const [items, setItems] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [fetched, setFetched] = useState(false)
  const [savingKeys, setSavingKeys] = useState(() => new Set())

  // Filters
  const [filterReason, setFilterReason] = useState('')
  const [filterCallType, setFilterCallType] = useState('')
  const [verifiedFilter, setVerifiedFilter] = useState('all') // 'all' | 'unverified' | 'verified'

  // Sorting
  const [sortCol, setSortCol] = useState('reason')
  const [sortDir, setSortDir] = useState('asc')
  const [page, setPage] = useState(0)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const q = new URLSearchParams({ start_date: startDate, end_date: endDate })
      const res = await fetch(`/api/contractor/driver-collection?${q}`)
      if (!res.ok) throw new Error(`Server error ${res.status}`)
      const data = await res.json()
      setItems(data.items || [])
      setFetched(true)
    } catch (e) {
      setError(e.message || 'Failed to load driver collection')
    } finally {
      setLoading(false)
    }
  }, [startDate, endDate])

  useEffect(() => { fetchData() }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  const reasonOptions   = useMemo(() => items ? [...new Set(items.map(r => r.reason).filter(Boolean))].sort() : [], [items])
  const callTypeOptions = useMemo(() => items ? [...new Set(items.map(r => r.call_type).filter(Boolean))].sort() : [], [items])

  const handleSort = col => {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortCol(col); setSortDir('asc') }
  }

  const toggleVerified = useCallback(async (row) => {
    const key = rowKey(row)
    const next = !row.audit_verified
    // Optimistic update
    setItems(prev => prev.map(r => rowKey(r) === key ? { ...r, audit_verified: next } : r))
    setSavingKeys(prev => new Set(prev).add(key))
    try {
      const res = await fetch('/api/contractor/driver-collection/audit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ wo_id: row.wo_id, reason: row.reason, verified: next }),
      })
      if (!res.ok) throw new Error(`Server error ${res.status}`)
    } catch (e) {
      // Revert on error
      setItems(prev => prev.map(r => rowKey(r) === key ? { ...r, audit_verified: !next } : r))
      setError(e.message || 'Failed to save verification')
    } finally {
      setSavingKeys(prev => { const s = new Set(prev); s.delete(key); return s })
    }
  }, [])

  const filtered = useMemo(() => {
    if (!items) return []
    let rows = items.filter(r => {
      if (filterReason   && r.reason    !== filterReason)   return false
      if (filterCallType && r.call_type !== filterCallType) return false
      if (verifiedFilter === 'verified'   && !r.audit_verified) return false
      if (verifiedFilter === 'unverified' &&  r.audit_verified) return false
      return true
    })
    const col = COLUMNS.find(c => c.key === sortCol)
    if (col) rows = [...rows].sort((a, b) => sortDir === 'asc' ? col.sortFn(a, b) : col.sortFn(b, a))
    return rows
  }, [items, filterReason, filterCallType, verifiedFilter, sortCol, sortDir])

  // Display one page only (keeps the table fast on large sets). Export uses full `filtered`.
  const pageRows = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  useEffect(() => { setPage(0) }, [filterReason, filterCallType, verifiedFilter, startDate, endDate, items])

  const selectCls ="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/50"

  return (
    <div>
      {/* Controls bar */}
      <div className="glass rounded-xl border border-slate-700/30 p-4 mb-4 flex flex-wrap items-end gap-4">
        <div className="flex flex-col gap-1">
          <label className="text-[10px] text-slate-500 uppercase tracking-wider">Start Date</label>
          <MiniDatePicker value={startDate} onChange={setStartDate} placeholder="Start date" />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] text-slate-500 uppercase tracking-wider">End Date</label>
          <MiniDatePicker value={endDate} onChange={setEndDate} placeholder="End date" />
        </div>
        <button onClick={fetchData} disabled={loading}
          className="flex items-center gap-2 px-5 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-semibold transition-all">
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
          {loading ? 'Loading…' : 'Load'}
        </button>

        <div className="self-center">
          <InfoTip text={"DRIVER COLLECTION\n\nCompleted/closed calls where the technician should have collected payment from the member.\n\nFIVE REASONS:\n  • Tow Overmiles — tow with Est. Tow Over-Mileage Cost > $0 (actual amount shown)\n  • Battery Sold — resolution G306/G307/G308 (verify manually)\n  • TireJECT Install — resolution G103 (fixed $34.99)\n  • Fuel Delivery – Basic Member — resolution G401/G402 + Basic coverage (2-3 gallons)\n  • Private Service — Type = Private Service (Completed/Closed)\n\nTick Audit Verification after confirming the tech collected — it saves per facility."} />
        </div>

        <div className="self-center flex flex-col gap-1">
          <label className="text-[10px] text-slate-500 uppercase tracking-wider">Audit Status</label>
          <div className="flex rounded-lg overflow-hidden border border-slate-700 text-xs font-medium">
            {[['all','All'],['unverified','Unverified'],['verified','Verified']].map(([val, label]) => (
              <button key={val} onClick={() => setVerifiedFilter(val)}
                className={`px-3 py-1.5 transition-colors ${verifiedFilter === val ? 'bg-indigo-600 text-white' : 'bg-slate-800 text-slate-400 hover:text-slate-200'}`}>
                {label}
              </button>
            ))}
          </div>
        </div>

        {fetched && items && items.length > 0 && (
          <>
            <div className="w-px h-6 bg-slate-700 self-center hidden sm:block" />

            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-slate-500 uppercase tracking-wider">Reason</label>
              <select value={filterReason} onChange={e => setFilterReason(e.target.value)} className={selectCls}>
                <option value="">All</option>
                {reasonOptions.map(v => <option key={v} value={v}>{v}</option>)}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-slate-500 uppercase tracking-wider">Call Type</label>
              <select value={filterCallType} onChange={e => setFilterCallType(e.target.value)} className={selectCls}>
                <option value="">All</option>
                {callTypeOptions.map(v => <option key={v} value={v}>{v}</option>)}
              </select>
            </div>
            <button onClick={() => exportCSV(filtered)}
              className="flex items-center gap-2 px-4 py-2 rounded-lg border border-slate-700 text-slate-300 hover:text-white hover:border-slate-600 text-sm font-medium transition-all ml-auto">
              <Download size={14} />
              Export CSV
            </button>
          </>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="mb-4 px-4 py-2.5 rounded-xl border border-red-800/30 bg-red-950/10 flex items-center gap-2">
          <AlertTriangle className="w-3.5 h-3.5 text-red-400 shrink-0" />
          <span className="text-xs text-red-300">{error}</span>
        </div>
      )}

      {!fetched && !loading && !error && (
        <div className="glass rounded-xl border border-slate-700/30 py-16 text-center text-slate-500 text-sm">
          Select a date range and click Load to view calls requiring collection.
        </div>
      )}

      {/* Table */}
      {fetched && (
        <div className="glass rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-slate-800">
                  {COLUMNS.map(col => (
                    <th key={col.key} onClick={() => handleSort(col.key)}
                      className="px-2 py-2.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500 text-left whitespace-nowrap cursor-pointer hover:text-slate-300 select-none transition-colors">
                      <span className="inline-flex items-center gap-0.5">
                        {col.label}
                        <SortIcon col={col.key} sortCol={sortCol} sortDir={sortDir} />
                      </span>
                    </th>
                  ))}
                  <th className="px-2 py-2.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500 text-center whitespace-nowrap">Audit Verification</th>
                </tr>
              </thead>
              <tbody>
                {loading && [...Array(6)].map((_, i) => (
                  <tr key={i} className="border-b border-slate-800/40">
                    {[...Array(COLUMNS.length + 1)].map((__, j) => (
                      <td key={j} className="px-2 py-2.5"><div className="skeleton h-3.5 rounded w-20" /></td>
                    ))}
                  </tr>
                ))}
                {!loading && pageRows.map((row, idx) => {
                  const key = rowKey(row)
                  const saving = savingKeys.has(key)
                  return (
                    <tr key={key || idx}
                      onClick={() => row.wo_id && navigate(`/contractor/accounting/calls/${row.wo_id}`, { state: { from: 'driver-collection' } })}
                      className={`hover:bg-slate-800/30 transition-colors border-b border-slate-800/40 ${row.wo_id ? 'cursor-pointer' : ''}`}>
                      <td className="px-2 py-2.5 font-mono text-indigo-400">
                        <span className="inline-flex items-center gap-1.5">
                          {row.wo_number ? `WO-${row.wo_number}` : <span className="text-slate-600">—</span>}
                          {row.wo_id && (
                            <a href={contractorWoLink(row.wo_id)} target="_blank" rel="noopener noreferrer"
                              onClick={e => e.stopPropagation()}
                              title="Open in Salesforce">
                              <ExternalLink size={9} className="text-slate-500 hover:text-indigo-400 shrink-0" />
                            </a>
                          )}
                          {row.has_photos && <Camera size={11} className="text-sky-400 shrink-0" title="Has photos" />}
                        </span>
                      </td>
                      <td className="px-2 py-2.5 text-slate-300">{row.service_resource_name || <span className="text-slate-600">—</span>}</td>
                      <td className="px-2 py-2.5 text-slate-200 whitespace-nowrap">{row.reason || <span className="text-slate-600">—</span>}</td>
                      <td className="px-2 py-2.5 text-slate-300 whitespace-nowrap">{row.amount || <span className="text-slate-600">—</span>}</td>
                      <td className="px-2 py-2.5 text-slate-300">{row.call_type || <span className="text-slate-600">—</span>}</td>
                      <td className="px-2 py-2.5 text-slate-400 font-mono">{row.dispatch_code || <span className="text-slate-600">—</span>}</td>
                      <td className="px-2 py-2.5 text-slate-400 font-mono">{row.resolution_code || <span className="text-slate-600">—</span>}</td>
                      <td className="px-2 py-2.5 text-slate-400">{row.coverage || <span className="text-slate-600">—</span>}</td>
                      <td className="px-2 py-2.5 text-center" onClick={e => e.stopPropagation()}>
                        <input type="checkbox" checked={!!row.audit_verified} disabled={saving}
                          onChange={() => toggleVerified(row)}
                          className="w-4 h-4 rounded border-slate-600 bg-slate-800 text-indigo-500 focus:ring-indigo-500/50 cursor-pointer disabled:opacity-50"
                          title="Mark collection as verified" />
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {!loading && fetched && filtered.length === 0 && (
            <div className="py-12 text-center text-slate-600 text-sm">
              {items && items.length > 0 ? 'No rows match the current filters.' : 'No collections found in this date range.'}
            </div>
          )}

          {!loading && filtered.length > 0 && (
            <>
              <Paginator page={page} setPage={setPage} total={filtered.length} pageSize={PAGE_SIZE} />
              <div className="px-4 py-2.5 border-t border-slate-800/60 text-[10px] text-slate-600">
                {filtered.length} row{filtered.length !== 1 ? 's' : ''}
                {items && items.length !== filtered.length && ` (filtered from ${items.length})`}
                {' · '}{startDate} – {endDate} · Export includes all {filtered.length} filtered rows
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
