import { useState, useCallback, useMemo, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Loader2, AlertTriangle, ChevronUp, ChevronDown,
  Download, ExternalLink, ArrowUpDown, Camera
} from 'lucide-react'
import { InfoTip } from '../../components/CommandCenterUtils'

const SF_BASE = 'https://aaawcny.lightning.force.com'

function fmt(v) {
  if (v == null || v === '') return '—'
  return '$' + Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function defaultDates() {
  const now = new Date()
  const start = new Date(now.getFullYear(), now.getMonth(), 1)
  const iso = d => d.toISOString().slice(0, 10)
  return { start: iso(start), end: iso(now) }
}

function exportCSV(rows) {
  const headers = ['WO Number', 'Call Type', 'Coverage', 'Resolution Code', 'Status', 'Date', 'Facility', 'Total Cost']
  const lines = [
    headers.join(','),
    ...rows.map(r => [
      `WO-${r.wo_number}`, r.call_type, r.coverage, r.resolution_code, r.status,
      r.created_date?.slice(0, 10), r.facility,
      r.total_cost
    ].map(v => `"${(v || '').toString().replace(/"/g, '""')}"`).join(','))
  ]
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `calls-${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
}

function StatusBadge({ status }) {
  const colors = {
    'Completed': 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
    'In Progress': 'bg-blue-500/15 text-blue-300 border-blue-500/30',
    'Canceled': 'bg-slate-700/40 text-slate-400 border-slate-600/30',
    'New': 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  }
  const cls = colors[status] || 'bg-slate-700/30 text-slate-400 border-slate-600/30'
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium border ${cls}`}>
      {status || '—'}
    </span>
  )
}

function SortIcon({ col, sortCol, sortDir }) {
  if (sortCol !== col) return <ArrowUpDown size={10} className="text-slate-600 ml-0.5" />
  return sortDir === 'asc'
    ? <ChevronUp size={10} className="text-indigo-400 ml-0.5" />
    : <ChevronDown size={10} className="text-indigo-400 ml-0.5" />
}


const COLUMNS = [
  { key: 'wo_number',      label: 'WO Number',      sortFn: (a, b) => a.wo_number.localeCompare(b.wo_number) },
  { key: 'call_type',      label: 'Call Type',      sortFn: (a, b) => (a.call_type || '').localeCompare(b.call_type || '') },
  { key: 'coverage',       label: 'Coverage',       sortFn: (a, b) => (a.coverage || '').localeCompare(b.coverage || '') },
  { key: 'resolution_code',label: 'Resolution',     sortFn: (a, b) => (a.resolution_code || '').localeCompare(b.resolution_code || '') },
  { key: 'status',         label: 'Status',         sortFn: (a, b) => (a.status || '').localeCompare(b.status || '') },
  { key: 'created_date',   label: 'Date',           sortFn: (a, b) => (a.created_date || '').localeCompare(b.created_date || '') },
  { key: 'facility',       label: 'Facility',       sortFn: (a, b) => (a.facility || '').localeCompare(b.facility || '') },
  { key: 'total_cost',     label: 'Total',          sortFn: (a, b) => (a.total_cost || 0) - (b.total_cost || 0) },
]

export default function ContractorCalls() {
  const navigate = useNavigate()
  const { start: defStart, end: defEnd } = defaultDates()
  const [startDate, setStartDate] = useState(defStart)
  const [endDate, setEndDate] = useState(defEnd)
  const [allCalls, setAllCalls] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [fetched, setFetched] = useState(false)

  // Filters
  const [filterCallType, setFilterCallType] = useState('')
  const [filterCoverage, setFilterCoverage] = useState('')
  const [filterStatus, setFilterStatus] = useState('')
  const [filterResolution, setFilterResolution] = useState('')

  // Sorting
  const [sortCol, setSortCol] = useState('created_date')
  const [sortDir, setSortDir] = useState('desc')

  const fetchData = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const params = new URLSearchParams({ start_date: startDate, end_date: endDate })
      const res = await fetch(`/api/contractor/calls?${params}`)
      if (!res.ok) throw new Error(`Server error ${res.status}`)
      const json = await res.json()
      setAllCalls(json.items || [])
      setFetched(true)
    } catch (e) {
      setError(e.message || 'Failed to load calls')
    } finally {
      setLoading(false)
    }
  }, [startDate, endDate])

  // Auto-load on mount
  useEffect(() => { fetchData() }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  const callTypeOptions = useMemo(() => {
    if (!allCalls) return []
    return [...new Set(allCalls.map(c => c.call_type).filter(Boolean))].sort()
  }, [allCalls])

  const coverageOptions = useMemo(() => {
    if (!allCalls) return []
    return [...new Set(allCalls.map(c => c.coverage).filter(Boolean))].sort()
  }, [allCalls])

  const statusOptions = useMemo(() => {
    if (!allCalls) return []
    return [...new Set(allCalls.map(c => c.status).filter(Boolean))].sort()
  }, [allCalls])

  const resolutionOptions = useMemo(() => {
    if (!allCalls) return []
    return [...new Set(allCalls.map(c => c.resolution_code).filter(Boolean))].sort()
  }, [allCalls])

  const handleSort = (col) => {
    if (sortCol === col) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortCol(col)
      setSortDir('asc')
    }
  }

  const filteredSortedCalls = useMemo(() => {
    if (!allCalls) return []
    let rows = allCalls.filter(c => {
      if (filterCallType && c.call_type !== filterCallType) return false
      if (filterCoverage && c.coverage !== filterCoverage) return false
      if (filterStatus && c.status !== filterStatus) return false
      if (filterResolution && c.resolution_code !== filterResolution) return false
      return true
    })
    const col = COLUMNS.find(c => c.key === sortCol)
    if (col) {
      rows = [...rows].sort((a, b) => sortDir === 'asc' ? col.sortFn(a, b) : col.sortFn(b, a))
    }
    return rows
  }, [allCalls, filterCallType, filterCoverage, filterStatus, sortCol, sortDir])

  return (
    <div>
      {/* Controls bar */}
      <div className="glass rounded-xl border border-slate-700/30 p-4 mb-4 flex flex-wrap items-end gap-4">
        <div className="flex flex-col gap-1">
          <label className="text-[10px] text-slate-500 uppercase tracking-wider">Start Date</label>
          <input type="date" value={startDate} onChange={e => { setStartDate(e.target.value); e.target.blur() }}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/50" />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] text-slate-500 uppercase tracking-wider">End Date</label>
          <input type="date" value={endDate} onChange={e => { setEndDate(e.target.value); e.target.blur() }}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/50" />
        </div>
        <button onClick={fetchData} disabled={loading}
          className="flex items-center gap-2 px-5 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-semibold transition-all">
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
          {loading ? 'Loading…' : 'Load Calls'}
        </button>

        <div className="self-center">
          <InfoTip text={"WORK ORDERS\n\nEvery work order for your assigned garages in the selected date range.\n\nFILTERS:\n  • Your facilities only (Facility_ID__c)\n  • CreatedDate within the date range\n\nShows the full call log across all statuses (completed, closed, cancelled, etc.)."} />
        </div>

        {fetched && allCalls && allCalls.length > 0 && (
          <>
            <div className="w-px h-6 bg-slate-700 self-center hidden sm:block" />

            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-slate-500 uppercase tracking-wider">Call Type</label>
              <select value={filterCallType} onChange={e => setFilterCallType(e.target.value)}
                className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/50">
                <option value="">All</option>
                {callTypeOptions.map(v => <option key={v} value={v}>{v}</option>)}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-slate-500 uppercase tracking-wider">Coverage</label>
              <select value={filterCoverage} onChange={e => setFilterCoverage(e.target.value)}
                className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/50">
                <option value="">All</option>
                {coverageOptions.map(v => <option key={v} value={v}>{v}</option>)}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-slate-500 uppercase tracking-wider">Status</label>
              <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)}
                className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/50">
                <option value="">All</option>
                {statusOptions.map(v => <option key={v} value={v}>{v}</option>)}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-slate-500 uppercase tracking-wider">Resolution</label>
              <select value={filterResolution} onChange={e => setFilterResolution(e.target.value)}
                className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/50">
                <option value="">All</option>
                {resolutionOptions.map(v => <option key={v} value={v}>{v}</option>)}
              </select>
            </div>

            <button onClick={() => exportCSV(filteredSortedCalls)}
              className="flex items-center gap-2 px-4 py-2 rounded-lg border border-slate-700 text-slate-300 hover:text-white hover:border-slate-600 text-sm font-medium transition-all ml-auto">
              <Download size={14} />
              Export CSV
            </button>
          </>
        )}
      </div>

      {/* Summary cards */}
      {fetched && !loading && allCalls && (
        <div className="grid grid-cols-3 gap-3 mb-4">
          <div className="glass rounded-xl border border-slate-700/30 p-4">
            <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Total Calls</div>
            <div className="text-2xl font-bold text-white">{filteredSortedCalls.length.toLocaleString()}</div>
            {allCalls.length !== filteredSortedCalls.length && (
              <div className="text-[10px] text-slate-500 mt-0.5">of {allCalls.length} total</div>
            )}
          </div>
          <div className="glass rounded-xl border border-slate-700/30 p-4">
            <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Total Billed</div>
            <div className="text-2xl font-bold text-emerald-400">
              {'$' + filteredSortedCalls.reduce((s, c) => s + (c.total_cost || 0), 0)
                .toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
          </div>
          <div className="glass rounded-xl border border-slate-700/30 p-4">
            <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Date Range</div>
            <div className="text-sm font-semibold text-slate-200">{startDate} – {endDate}</div>
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
          Select a date range and click Load Calls to view your call history.
        </div>
      )}

      {/* Main sortable table */}
      {fetched && (
        <div className="glass rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-slate-800">
                  {COLUMNS.map(col => (
                    <th key={col.key}
                      onClick={() => handleSort(col.key)}
                      className={`px-2 py-2.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500 whitespace-nowrap cursor-pointer hover:text-slate-300 select-none transition-colors ${
                        col.key === 'total_cost' ? 'text-right' : 'text-left'
                      }`}>
                      <span className="inline-flex items-center gap-0.5">
                        {col.label}
                        <SortIcon col={col.key} sortCol={sortCol} sortDir={sortDir} />
                      </span>
                    </th>
                  ))}
                  <th className="px-2 py-2.5 w-6" />
                </tr>
              </thead>
              <tbody>
                {loading && [...Array(8)].map((_, i) => (
                  <tr key={i} className="border-b border-slate-800/40">
                    {[...Array(9)].map((__, j) => (
                      <td key={j} className="px-2 py-2.5"><div className="skeleton h-3.5 rounded w-16" /></td>
                    ))}
                  </tr>
                ))}
                {!loading && filteredSortedCalls.map(c => (
                  <tr key={c.wo_id}
                    onClick={() => navigate(`/contractor/accounting/calls/${c.wo_id}`, { state: { from: 'calls' } })}
                    className="hover:bg-slate-800/40 cursor-pointer transition-colors border-b border-slate-800/40">
                    <td className="px-2 py-2.5 font-mono">
                      <div className="flex items-center gap-1.5">
                        <span className="text-indigo-400">WO-{c.wo_number || '—'}</span>
                        {c.has_photos && (
                          <Camera size={11} className="text-sky-400 shrink-0" title="Has photos" />
                        )}
                        <a
                          href={`${SF_BASE}/${c.wo_id}`}
                          target="_blank" rel="noopener noreferrer"
                          onClick={e => e.stopPropagation()}
                          className="text-slate-600 hover:text-slate-400 transition-colors"
                          title="Open in Salesforce"
                        >
                          <ExternalLink size={9} className="shrink-0" />
                        </a>
                      </div>
                    </td>
                    <td className="px-2 py-2.5 text-slate-300">{c.call_type || <span className="text-slate-600">—</span>}</td>
                    <td className="px-2 py-2.5 text-slate-400">{c.coverage || <span className="text-slate-600">—</span>}</td>
                    <td className="px-2 py-2.5 text-slate-400 font-mono text-[10px]">{c.resolution_code || <span className="text-slate-600">—</span>}</td>
                    <td className="px-2 py-2.5"><StatusBadge status={c.status} /></td>
                    <td className="px-2 py-2.5 text-slate-400 whitespace-nowrap">{c.created_date?.slice(0, 10) || '—'}</td>
                    <td className="px-2 py-2.5 text-slate-300">{c.facility || <span className="text-slate-600">—</span>}</td>
                    <td className="px-2 py-2.5 text-right font-mono font-semibold text-emerald-400">
                      {c.total_cost ? fmt(c.total_cost) : <span className="text-slate-600">—</span>}
                    </td>
                    <td className="px-2 py-2.5">
                      <ChevronDown size={12} className="text-slate-600 rotate-[-90deg]" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {!loading && fetched && filteredSortedCalls.length === 0 && (
            <div className="py-12 text-center text-slate-600 text-sm">
              {allCalls && allCalls.length > 0 ? 'No calls match the current filters.' : 'No calls found for this date range.'}
            </div>
          )}

          {!loading && filteredSortedCalls.length > 0 && (
            <div className="px-4 py-2.5 border-t border-slate-800/60 text-[10px] text-slate-600">
              {filteredSortedCalls.length} calls
              {allCalls && allCalls.length !== filteredSortedCalls.length && ` (filtered from ${allCalls.length})`}
              {' · '}sorted by {COLUMNS.find(c => c.key === sortCol)?.label} ({sortDir})
            </div>
          )}
        </div>
      )}

    </div>
  )
}
