import { useState, useCallback, useEffect, useMemo } from 'react'
import { Loader2, AlertTriangle, ExternalLink, Download, ChevronUp, ChevronDown, ArrowUpDown } from 'lucide-react'
import { InfoTip } from '../../components/CommandCenterUtils'

const SF_BASE = 'https://aaawcny.lightning.force.com'

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
  { key: 'wo_number',    label: 'WO #',         sortFn: (a, b) => (a.wo_number || '').localeCompare(b.wo_number || '') },
  { key: 'facility',     label: 'Facility',      sortFn: (a, b) => (a.facility || '').localeCompare(b.facility || '') },
  { key: 'territory',    label: 'Territory',     sortFn: (a, b) => (a.territory || '').localeCompare(b.territory || '') },
  { key: 'call_type',    label: 'Call Type',     sortFn: (a, b) => (a.call_type || '').localeCompare(b.call_type || '') },
  { key: 'created_date', label: 'Created Date',  sortFn: (a, b) => (a.created_date || '').localeCompare(b.created_date || '') },
]

function exportCSV(rows) {
  const headers = COLUMNS.map(c => c.label).concat(['SF Link'])
  const lines = [
    headers.join(','),
    ...rows.map(r => [
      r.wo_number ? `WO-${r.wo_number}` : '',
      r.facility, r.territory, r.call_type,
      r.created_date?.slice(0, 10),
      r.woa_id ? `${SF_BASE}/${r.woa_id}` : ''
    ].map(v => `"${(v || '').toString().replace(/"/g, '""')}"`).join(','))
  ]
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `pending-woas-${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
}

export default function ContractorPendingWoas() {
  const { start: defStart, end: defEnd } = defaultDates()
  const [startDate, setStartDate] = useState(defStart)
  const [endDate, setEndDate] = useState(defEnd)
  const [items, setItems] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [fetched, setFetched] = useState(false)

  // Filters
  const [filterTerritory, setFilterTerritory] = useState('')
  const [filterCallType, setFilterCallType] = useState('')

  // Sorting
  const [sortCol, setSortCol] = useState('created_date')
  const [sortDir, setSortDir] = useState('desc')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const q = new URLSearchParams({ start_date: startDate, end_date: endDate })
      const res = await fetch(`/api/contractor/pending-woas?${q}`)
      if (!res.ok) throw new Error(`Server error ${res.status}`)
      const data = await res.json()
      setItems(data.items || [])
      setFetched(true)
    } catch (e) {
      setError(e.message || 'Failed to load pending WOAs')
    } finally {
      setLoading(false)
    }
  }, [startDate, endDate])

  useEffect(() => { fetchData() }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  const territoryOptions = useMemo(() => items ? [...new Set(items.map(r => r.territory).filter(Boolean))].sort() : [], [items])
  const callTypeOptions  = useMemo(() => items ? [...new Set(items.map(r => r.call_type).filter(Boolean))].sort() : [], [items])

  const handleSort = col => {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortCol(col); setSortDir('asc') }
  }

  const filtered = useMemo(() => {
    if (!items) return []
    let rows = items.filter(r => {
      if (filterTerritory && r.territory !== filterTerritory) return false
      if (filterCallType  && r.call_type !== filterCallType)  return false
      return true
    })
    const col = COLUMNS.find(c => c.key === sortCol)
    if (col) rows = [...rows].sort((a, b) => sortDir === 'asc' ? col.sortFn(a, b) : col.sortFn(b, a))
    return rows
  }, [items, filterTerritory, filterCallType, sortCol, sortDir])

  const selectCls = "bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/50"

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
          {loading ? 'Loading…' : 'Load'}
        </button>

        <div className="self-center">
          <InfoTip text={"WORK ORDER ADJS\n\nYour PENDING Work Order Adjustments — WOAs you've submitted that are awaiting a decision.\n\nFILTER: Status = 'New'\n\nNot shown here: Approved WOAs (already done) and Rejected WOAs (those reappear in Recommendations so you can resubmit)."} />
        </div>

        {fetched && items && items.length > 0 && (
          <>
            <div className="w-px h-6 bg-slate-700 self-center hidden sm:block" />

            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-slate-500 uppercase tracking-wider">Territory</label>
              <select value={filterTerritory} onChange={e => setFilterTerritory(e.target.value)} className={selectCls}>
                <option value="">All</option>
                {territoryOptions.map(v => <option key={v} value={v}>{v}</option>)}
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
          Select a date range and click Load to view pending adjustments.
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
                  <th className="px-2 py-2.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500 text-left whitespace-nowrap">SF Link</th>
                </tr>
              </thead>
              <tbody>
                {loading && [...Array(6)].map((_, i) => (
                  <tr key={i} className="border-b border-slate-800/40">
                    {[...Array(7)].map((__, j) => (
                      <td key={j} className="px-2 py-2.5"><div className="skeleton h-3.5 rounded w-20" /></td>
                    ))}
                  </tr>
                ))}
                {!loading && filtered.map((row, idx) => (
                  <tr key={row.woa_id || row.wo_id || idx} className="hover:bg-slate-800/30 transition-colors border-b border-slate-800/40">
                    <td className="px-2 py-2.5 font-mono text-indigo-400">
                      {row.wo_number ? `WO-${row.wo_number}` : <span className="text-slate-600">—</span>}
                    </td>
                    <td className="px-2 py-2.5 text-slate-300">{row.facility || <span className="text-slate-600">—</span>}</td>
                    <td className="px-2 py-2.5 text-slate-400">{row.territory || <span className="text-slate-600">—</span>}</td>
                    <td className="px-2 py-2.5 text-slate-300">{row.call_type || <span className="text-slate-600">—</span>}</td>
                    <td className="px-2 py-2.5 text-slate-400 whitespace-nowrap">
                      {row.created_date ? row.created_date.slice(0, 10) : <span className="text-slate-600">—</span>}
                    </td>
                    <td className="px-2 py-2.5">
                      {row.woa_id ? (
                        <a href={`${SF_BASE}/${row.woa_id}`} target="_blank" rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-indigo-400 hover:text-indigo-300 transition-colors"
                          title="Open WOA in Salesforce">
                          <ExternalLink size={11} />
                          <span className="text-[10px]">SF</span>
                        </a>
                      ) : <span className="text-slate-600">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {!loading && fetched && filtered.length === 0 && (
            <div className="py-12 text-center text-slate-600 text-sm">
              {items && items.length > 0 ? 'No WOAs match the current filters.' : 'No WOAs found in this date range.'}
            </div>
          )}

          {!loading && filtered.length > 0 && (
            <div className="px-4 py-2.5 border-t border-slate-800/60 text-[10px] text-slate-600">
              {filtered.length} WOA{filtered.length !== 1 ? 's' : ''}
              {items && items.length !== filtered.length && ` (filtered from ${items.length})`}
              {' · '}{startDate} – {endDate}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
