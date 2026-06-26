import { useState, useMemo, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Loader2, AlertTriangle, ExternalLink, Download, Search,
  Truck, MapPin, DollarSign, Droplets, Link2, Camera,
  ChevronUp, ChevronDown, ChevronsUpDown,
} from 'lucide-react'

const REC_TABS = [
  { key: 'mh',        label: 'MH (Medium Duty)', icon: Truck },
  { key: 'pg-fuel',   label: 'PG Fuel',           icon: Droplets },
  { key: 'er-miles',  label: 'ER Miles',           icon: MapPin },
  { key: 'tow-miles', label: 'Tow Miles',          icon: Link2 },
  { key: 'tl-tolls',  label: 'TL Tolls',           icon: DollarSign },
]

function defaultDates() {
  const now = new Date()
  const start = new Date(now.getFullYear(), now.getMonth(), 1)
  const iso = d => d.toISOString().slice(0, 10)
  return { start: iso(start), end: iso(now) }
}

const SF_BASE = 'https://aaawcny.lightning.force.com'

function StatusBadge({ status }) {
  if (!status) return <span className="text-slate-600">—</span>
  const cls = status === 'Completed'
    ? 'bg-emerald-500/15 text-emerald-400 border-emerald-700/30'
    : 'bg-sky-500/15 text-sky-400 border-sky-700/30'
  return (
    <span className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium border ${cls}`}>
      {status}
    </span>
  )
}

function WoCell({ r, navigate }) {
  return (
    <div className="flex items-center gap-1.5">
      <button
        onClick={() => r.wo_id && navigate(`/contractor/accounting/calls/${r.wo_id}`)}
        className="font-mono text-indigo-400 hover:text-indigo-300 hover:underline text-left"
      >
        WO-{r.wo_number || '—'}
      </button>
      {r.has_photos && (
        <Camera size={11} className="text-sky-400 shrink-0" title="Has photos" />
      )}
      {r.wo_id && (
        <a href={`${SF_BASE}/${r.wo_id}`} target="_blank" rel="noopener noreferrer"
          onClick={e => e.stopPropagation()}
          className="text-slate-600 hover:text-slate-400 transition-colors"
          title="Open in Salesforce">
          <ExternalLink size={9} className="shrink-0" />
        </a>
      )}
    </div>
  )
}

// Status column injected into every tab
const STATUS_COLUMN = {
  key: 'wo_status',
  label: 'Status',
  sortable: true,
  render: r => <StatusBadge status={r.wo_status} />,
}

// Columns per tab — wo_number column injected dynamically
const EXTRA_COLUMNS = {
  'mh': [
    { key: 'facility',     label: 'Facility',      sortable: true,  render: r => <span className="text-slate-300">{r.facility || '—'}</span> },
    { key: 'created_date', label: 'Date',           sortable: true,  render: r => <span className="text-slate-400 whitespace-nowrap">{r.created_date?.slice(0,10) || '—'}</span> },
    { key: 'vehicle_make', label: 'Vehicle Make',   sortable: true,  render: r => <span className="text-slate-300">{r.vehicle_make || '—'}</span> },
    { key: 'vehicle_model',label: 'Vehicle Model',  sortable: true,  render: r => <span className="text-slate-300">{r.vehicle_model || '—'}</span> },
    STATUS_COLUMN,
  ],
  'pg-fuel': [
    { key: 'facility',     label: 'Facility',      sortable: true,  render: r => <span className="text-slate-300">{r.facility || '—'}</span> },
    { key: 'created_date', label: 'Date',           sortable: true,  render: r => <span className="text-slate-400 whitespace-nowrap">{r.created_date?.slice(0,10) || '—'}</span> },
    { key: 'dispatch_code',label: 'Dispatch Code',  sortable: true,  render: r => <span className="font-mono text-slate-300">{r.dispatch_code || '—'}</span> },
    { key: 'fuel_type',    label: 'Fuel Type',      sortable: true,  render: r => <span className="text-slate-300">{r.fuel_type || '—'}</span> },
    { key: 'max_reimbursement', label: 'Max Reimb.', sortable: true, render: r => <span className="font-mono text-slate-300">{r.max_reimbursement != null ? `$${Number(r.max_reimbursement).toFixed(2)}` : '—'}</span> },
    STATUS_COLUMN,
  ],
  'er-miles': [
    { key: 'facility',     label: 'Facility',     sortable: true, render: r => <span className="text-slate-300">{r.facility || '—'}</span> },
    { key: 'created_date', label: 'Date',         sortable: true, render: r => <span className="text-slate-400 whitespace-nowrap">{r.created_date?.slice(0,10) || '—'}</span> },
    { key: 'estimated_er_miles', label: 'Est. ER Miles', sortable: true, render: r => <span className="font-mono text-slate-300">{r.estimated_er_miles != null ? `${r.estimated_er_miles} mi` : '—'}</span> },
    { key: 'ai_summary',   label: 'Reason',       sortable: false, render: r => <span className="text-slate-300 max-w-[220px] block text-[10px]">{r.ai_summary || '—'}</span> },
    STATUS_COLUMN,
  ],
  'tow-miles': [
    { key: 'facility',       label: 'Facility',      sortable: true, render: r => <span className="text-slate-300">{r.facility || '—'}</span> },
    { key: 'created_date',   label: 'Date',          sortable: true, render: r => <span className="text-slate-400 whitespace-nowrap">{r.created_date?.slice(0,10) || '—'}</span> },
    { key: 'resolution_code',label: 'Resolution Code', sortable: true, render: r => <span className="font-mono text-slate-300">{r.resolution_code || '—'}</span> },
    { key: 'estimated_tow_miles', label: 'Est. Tow Miles', sortable: true, render: r => <span className="font-mono text-slate-300">{r.estimated_tow_miles != null ? `${r.estimated_tow_miles} mi` : '—'}</span> },
    STATUS_COLUMN,
  ],
  'tl-tolls': [
    { key: 'facility',           label: 'Facility',      sortable: true, render: r => <span className="text-slate-300">{r.facility || '—'}</span> },
    { key: 'created_date',       label: 'Date',          sortable: true, render: r => <span className="text-slate-400 whitespace-nowrap">{r.created_date?.slice(0,10) || '—'}</span> },
    { key: 'estimated_tow_miles',label: 'Est. Tow Miles',sortable: true, render: r => <span className="font-mono text-slate-300">{r.estimated_tow_miles != null ? `${r.estimated_tow_miles} mi` : '—'}</span> },
    { key: 'actual_tow_miles',   label: 'Actual Miles',  sortable: true, render: r => <span className="font-mono text-slate-300">{r.actual_tow_miles != null ? `${r.actual_tow_miles} mi` : '—'}</span> },
    STATUS_COLUMN,
  ],
}

// Plain-text values for CSV export
const CSV_COLUMNS = {
  'mh':        ['wo_number','facility','created_date','vehicle_make','vehicle_model','wo_status'],
  'pg-fuel':   ['wo_number','facility','created_date','dispatch_code','fuel_type','max_reimbursement','wo_status'],
  'er-miles':  ['wo_number','facility','created_date','estimated_er_miles','ai_summary','wo_status'],
  'tow-miles': ['wo_number','facility','created_date','resolution_code','estimated_tow_miles','wo_status'],
  'tl-tolls':  ['wo_number','facility','created_date','estimated_tow_miles','actual_tow_miles','wo_status'],
}

function exportCSV(tabKey, items) {
  const cols = CSV_COLUMNS[tabKey] || []
  const allCols = [...(EXTRA_COLUMNS[tabKey] || []), { key: 'wo_number', label: 'WO Number' }]
  const hdrs = cols.map(k => allCols.find(c => c.key === k)?.label || k)
  const esc = v => `"${String(v ?? '').replace(/"/g, '""')}"`
  const lines = [
    hdrs.map(esc).join(','),
    ...items.map(r => cols.map(k => {
      if (k === 'wo_number') return esc(`WO-${r.wo_number || ''}`)
      const v = r[k]
      return esc(k === 'created_date' ? (v || '').slice(0, 10) : v)
    }).join(','))
  ]
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `recommendations-${tabKey}-${new Date().toISOString().slice(0,10)}.csv`
  a.click()
}

function SortIcon({ colKey, sortKey, sortDir }) {
  if (sortKey !== colKey) return <ChevronsUpDown size={10} className="text-slate-600 ml-0.5 inline" />
  return sortDir === 'asc'
    ? <ChevronUp size={10} className="text-indigo-400 ml-0.5 inline" />
    : <ChevronDown size={10} className="text-indigo-400 ml-0.5 inline" />
}

function sortItems(items, sortKey, sortDir) {
  if (!sortKey) return items
  return [...items].sort((a, b) => {
    let va = a[sortKey] ?? ''
    let vb = b[sortKey] ?? ''
    // Numeric sort for mile/number fields
    const na = parseFloat(va)
    const nb = parseFloat(vb)
    if (!isNaN(na) && !isNaN(nb)) {
      return sortDir === 'asc' ? na - nb : nb - na
    }
    va = String(va).toLowerCase()
    vb = String(vb).toLowerCase()
    if (va < vb) return sortDir === 'asc' ? -1 : 1
    if (va > vb) return sortDir === 'asc' ? 1 : -1
    return 0
  })
}

function RecTable({ items, columns, loading, error, filter, statusFilter, navigate }) {
  const [sortKey, setSortKey] = useState('created_date')
  const [sortDir, setSortDir] = useState('desc')

  const handleSort = colKey => {
    if (sortKey === colKey) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(colKey)
      setSortDir('asc')
    }
  }

  const filtered = useMemo(() => {
    if (!items) return []
    let result = items
    if (statusFilter) result = result.filter(r => r.wo_status === statusFilter)
    if (filter) {
      const q = filter.toLowerCase()
      result = result.filter(r =>
        (r.wo_number || '').toLowerCase().includes(q) ||
        (r.facility || '').toLowerCase().includes(q) ||
        (r.vehicle_make || '').toLowerCase().includes(q) ||
        (r.vehicle_model || '').toLowerCase().includes(q) ||
        (r.ai_summary || '').toLowerCase().includes(q) ||
        (r.resolution_code || '').toLowerCase().includes(q)
      )
    }
    return sortItems(result, sortKey, sortDir)
  }, [items, filter, statusFilter, sortKey, sortDir])

  if (loading) return (
    <div className="flex items-center justify-center py-16 gap-2 text-slate-500">
      <Loader2 className="w-5 h-5 animate-spin" />
      <span className="text-sm">Loading…</span>
    </div>
  )
  if (error) return (
    <div className="px-4 py-4 rounded-xl border border-red-800/30 bg-red-950/10 flex items-center gap-2">
      <AlertTriangle className="w-3.5 h-3.5 text-red-400 shrink-0" />
      <span className="text-xs text-red-300">{error}</span>
    </div>
  )
  if (!items) return (
    <div className="py-16 text-center text-slate-600 text-sm">Loading…</div>
  )
  if (filtered.length === 0) return (
    <div className="py-16 text-center">
      <div className="text-2xl mb-2">✓</div>
      <div className="text-slate-400 text-sm font-medium">
        {filter || statusFilter ? 'No matches for your filter.' : 'No recommendations for this period.'}
      </div>
    </div>
  )

  const thCls = sortable =>
    `px-2 py-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500 text-left whitespace-nowrap select-none${sortable ? ' cursor-pointer hover:text-slate-300 transition-colors' : ''}`

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="border-b border-slate-800">
            <th
              className={thCls(true)}
              onClick={() => handleSort('wo_number')}
            >
              WO Number <SortIcon colKey="wo_number" sortKey={sortKey} sortDir={sortDir} />
            </th>
            {columns.map(c => (
              <th
                key={c.key}
                className={thCls(c.sortable)}
                onClick={c.sortable ? () => handleSort(c.key) : undefined}
              >
                {c.label}
                {c.sortable && <SortIcon colKey={c.key} sortKey={sortKey} sortDir={sortDir} />}
              </th>
            ))}
            <th className="px-2 py-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500 text-left">Action</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/40">
          {filtered.map((r, idx) => (
            <tr
              key={r.wo_id || r.wo_number || idx}
              onClick={() => r.wo_id && navigate(`/contractor/accounting/calls/${r.wo_id}`)}
              className={`hover:bg-slate-800/30 transition-colors ${r.wo_id ? 'cursor-pointer' : ''}`}
            >
              <td className="px-2 py-2.5">
                <WoCell r={r} navigate={navigate} />
              </td>
              {columns.map(c => (
                <td key={c.key} className="px-2 py-2.5">
                  {c.render ? c.render(r) : <span className="text-slate-300">{r[c.key] || <span className="text-slate-600">—</span>}</span>}
                </td>
              ))}
              <td className="px-2 py-2.5" onClick={e => e.stopPropagation()}>
                {r.sf_new_woa_url ? (
                  <a href={r.sf_new_woa_url} target="_blank" rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-[11px] font-semibold bg-indigo-600/20 border border-indigo-500/40 text-indigo-300 hover:bg-indigo-600/40 hover:text-indigo-200 transition-all whitespace-nowrap">
                    Submit WOA <ExternalLink className="w-3 h-3" />
                  </a>
                ) : (
                  <span className="text-slate-600 text-[10px]">No link</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="px-4 py-2 border-t border-slate-800/60 text-[10px] text-slate-600">
        {filtered.length} recommendation{filtered.length !== 1 ? 's' : ''}
        {(filter || statusFilter) && items.length !== filtered.length && ` (filtered from ${items.length})`}
      </div>
    </div>
  )
}

export default function ContractorAccountingRecs() {
  const navigate = useNavigate()
  const { start: defStart, end: defEnd } = defaultDates()
  const [startDate, setStartDate] = useState(defStart)
  const [endDate, setEndDate] = useState(defEnd)
  const [activeRec, setActiveRec] = useState('mh')
  const [recData, setRecData] = useState({})
  const [recLoading, setRecLoading] = useState({})
  const [recError, setRecError] = useState({})
  const [filter, setFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')

  const loadAll = useCallback((start, end) => {
    setFilter('')
    setStatusFilter('')
    const s = start ?? startDate
    const e = end ?? endDate
    REC_TABS.forEach(({ key }) => {
      setRecLoading(prev => ({ ...prev, [key]: true }))
      const params = new URLSearchParams({ start_date: s, end_date: e })
      fetch(`/api/contractor/recommendations/${key}?${params}`)
        .then(r => { if (!r.ok) throw new Error(`Server error ${r.status}`); return r.json() })
        .then(json => {
          setRecData(prev => ({ ...prev, [key]: json.items || [] }))
          setRecError(prev => ({ ...prev, [key]: json.warning || null }))
        })
        .catch(err => setRecError(prev => ({ ...prev, [key]: err.message || 'Failed to load' })))
        .finally(() => setRecLoading(prev => ({ ...prev, [key]: false })))
    })
  }, [startDate, endDate])

  // Auto-load on mount
  useEffect(() => { loadAll() }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  const activeItems = recData[activeRec]
  const anyLoading = Object.values(recLoading).some(Boolean)

  // Export uses the filtered set (respects both text filter and status filter)
  const activeFiltered = useMemo(() => {
    if (!activeItems) return []
    let result = activeItems
    if (statusFilter) result = result.filter(r => r.wo_status === statusFilter)
    if (!filter) return result
    const q = filter.toLowerCase()
    return result.filter(r =>
      (r.wo_number || '').toLowerCase().includes(q) ||
      (r.facility || '').toLowerCase().includes(q) ||
      (r.vehicle_make || '').toLowerCase().includes(q) ||
      (r.vehicle_model || '').toLowerCase().includes(q) ||
      (r.ai_summary || '').toLowerCase().includes(q) ||
      (r.resolution_code || '').toLowerCase().includes(q)
    )
  }, [activeItems, filter, statusFilter])
  const canExport = activeFiltered.length > 0 && !recLoading[activeRec]

  return (
    <div>
      {/* Controls */}
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
        <button onClick={() => loadAll()}
          className="flex items-center gap-2 px-5 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-semibold transition-all">
          {anyLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
          {anyLoading ? 'Loading…' : 'Load Recommendations'}
        </button>
        <div className="relative ml-auto flex items-center gap-2 flex-wrap">
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/50"
          >
            <option value="">All Statuses</option>
            <option value="Completed">Completed</option>
            <option value="Closed">Closed</option>
          </select>
          <div className="relative flex items-center">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 pointer-events-none" />
            <input
              type="text"
              placeholder="Filter WO#, facility, resolution…"
              value={filter}
              onChange={e => setFilter(e.target.value)}
              className="pl-8 pr-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/50 w-52"
            />
          </div>
          {canExport && (
            <button
              onClick={() => exportCSV(activeRec, activeFiltered)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-300 text-[11px] font-semibold transition-all whitespace-nowrap"
              title="Export filtered to CSV">
              <Download className="w-3.5 h-3.5" /> Export
            </button>
          )}
        </div>
      </div>

      {/* Sub-tab bar */}
      <div className="flex gap-1 mb-4 flex-wrap">
        {REC_TABS.map(({ key, label, icon: Icon }) => {
          const count = recData[key]?.length
          const isLoading = recLoading[key]
          return (
            <button key={key} onClick={() => setActiveRec(key)}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all flex items-center gap-1.5 ${
                activeRec === key
                  ? 'bg-indigo-600/20 border border-indigo-500/40 text-indigo-300'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800 border border-transparent'
              }`}>
              {isLoading
                ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                : <Icon className="w-3.5 h-3.5" />}
              {label}
              {count != null && count > 0 && (
                <span className="px-1.5 py-0.5 rounded-full text-[10px] font-bold bg-indigo-500/30 text-indigo-300">
                  {count}
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* Active tab content */}
      <div className="glass rounded-xl overflow-hidden">
        <RecTable
          items={recData[activeRec]}
          columns={EXTRA_COLUMNS[activeRec] || []}
          loading={!!recLoading[activeRec]}
          error={recError[activeRec]}
          filter={filter}
          statusFilter={statusFilter}
          navigate={navigate}
          tabKey={activeRec}
        />
      </div>
    </div>
  )
}
