import { useState, useMemo, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Loader2, AlertTriangle, ExternalLink, Download, Search,
  Truck, MapPin, DollarSign, Droplets, Link2, Camera,
  ChevronUp, ChevronDown, ChevronsUpDown,
} from 'lucide-react'
import { InfoTip } from '../../components/CommandCenterUtils'

const REC_TABS = [
  { key: 'mh',        label: 'MH (Medium Duty)', icon: Truck },
  { key: 'pg-fuel',   label: 'PG Fuel',           icon: Droplets },
  { key: 'er-miles',  label: 'ER Miles',           icon: MapPin },
  { key: 'tow-miles', label: 'Tow Miles',          icon: Link2 },
  { key: 'tl-tolls',  label: 'TL Tolls',           icon: DollarSign },
]

const MAX_LOOKBACK_DAYS = 60

function defaultDates() {
  const now = new Date()
  const iso = d => d.toISOString().slice(0, 10)
  const minDate = new Date(now)
  minDate.setDate(minDate.getDate() - MAX_LOOKBACK_DAYS)
  // Start defaults to the later of: first of current month OR the 60-day cutoff
  const firstOfMonth = new Date(now.getFullYear(), now.getMonth(), 1)
  const start = firstOfMonth < minDate ? minDate : firstOfMonth
  return { start: iso(start), end: iso(now), min: iso(minDate) }
}

const SF_BASE = 'https://aaawcny.lightning.force.com'

function WoCell({ r, navigate }) {
  return (
    <div className="flex items-center gap-1.5">
      <button
        onClick={() => r.wo_id && navigate(`/contractor/accounting/calls/${r.wo_id}`, { state: { from: 'recs' } })}
        className="font-mono text-indigo-400 hover:text-indigo-300 hover:underline text-left"
      >
        WO-{r.wo_number || '—'}
      </button>
      {r.already_actioned === 'paid' && (
        <span className="px-1.5 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wide bg-amber-500/20 border border-amber-500/40 text-amber-300 whitespace-nowrap shrink-0" title="A paid/active line item already exists for this product">
          Paid
        </span>
      )}
      {r.already_actioned === 'woa_submitted' && (
        <span className="px-1.5 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wide bg-slate-600/40 border border-slate-500/50 text-slate-300 whitespace-nowrap shrink-0" title="A WOA has already been submitted for this product">
          WOA submitted
        </span>
      )}
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

// Columns per tab — wo_number column injected dynamically
const EXTRA_COLUMNS = {
  'mh': [
    { key: 'facility',     label: 'Facility',      sortable: true,  render: r => <span className="text-slate-300">{r.facility || '—'}</span> },
    { key: 'created_date', label: 'Date',           sortable: true,  render: r => <span className="text-slate-400 whitespace-nowrap">{r.created_date?.slice(0,10) || '—'}</span> },
    { key: 'vehicle_make', label: 'Vehicle Make',   sortable: true,  render: r => <span className="text-slate-300">{r.vehicle_make || '—'}</span> },
    { key: 'vehicle_model',label: 'Vehicle Model',  sortable: true,  render: r => <span className="text-slate-300">{r.vehicle_model || '—'}</span> },
  ],
  'pg-fuel': [
    { key: 'facility',     label: 'Facility',      sortable: true,  render: r => <span className="text-slate-300">{r.facility || '—'}</span> },
    { key: 'created_date', label: 'Date',           sortable: true,  render: r => <span className="text-slate-400 whitespace-nowrap">{r.created_date?.slice(0,10) || '—'}</span> },
    { key: 'dispatch_code',label: 'Dispatch Code',  sortable: true,  render: r => <span className="font-mono text-slate-300">{r.dispatch_code || '—'}</span> },
    { key: 'fuel_type',    label: 'Fuel Type',      sortable: true,  render: r => <span className="text-slate-300">{r.fuel_type || '—'}</span> },
    { key: 'entitlement_master', label: 'Entitlement', sortable: true, render: r => <span className="text-slate-300 text-[10px]">{r.entitlement_master || '—'}</span> },
    { key: 'max_reimbursement', label: 'Max Reimb.', sortable: true, render: r => <span className="font-mono text-slate-300">{r.max_reimbursement != null ? `$${Number(r.max_reimbursement).toFixed(2)}` : '—'}</span> },
  ],
  'er-miles': [
    { key: 'facility',     label: 'Facility',     sortable: true, render: r => <span className="text-slate-300">{r.facility || '—'}</span> },
    { key: 'created_date', label: 'Date',         sortable: true, render: r => <span className="text-slate-400 whitespace-nowrap">{r.created_date?.slice(0,10) || '—'}</span> },
    { key: 'estimated_er_miles', label: 'Est. ER Miles', sortable: true, render: r => <span className="font-mono text-slate-300">{r.estimated_er_miles != null ? `${r.estimated_er_miles} mi` : '—'}</span> },
    { key: 'ai_summary',   label: 'Reason',       sortable: false, render: r => <span className="text-slate-300 max-w-[220px] block text-[10px]">{r.ai_summary || '—'}</span> },
  ],
  'tow-miles': [
    { key: 'facility',       label: 'Facility',      sortable: true, render: r => <span className="text-slate-300">{r.facility || '—'}</span> },
    { key: 'created_date',   label: 'Date',          sortable: true, render: r => <span className="text-slate-400 whitespace-nowrap">{r.created_date?.slice(0,10) || '—'}</span> },
    { key: 'resolution_code',label: 'Resolution Code', sortable: true, render: r => <span className="font-mono text-slate-300">{r.resolution_code || '—'}</span> },
    { key: 'estimated_tow_miles', label: 'Est. Tow Miles', sortable: true, render: r => <span className="font-mono text-slate-300">{r.estimated_tow_miles != null ? `${r.estimated_tow_miles} mi` : '—'}</span> },
  ],
  'tl-tolls': [
    { key: 'facility',           label: 'Facility',      sortable: true, render: r => <span className="text-slate-300">{r.facility || '—'}</span> },
    { key: 'created_date',       label: 'Date',          sortable: true, render: r => <span className="text-slate-400 whitespace-nowrap">{r.created_date?.slice(0,10) || '—'}</span> },
    { key: 'estimated_tow_miles',label: 'Est. Tow Miles',sortable: true, render: r => <span className="font-mono text-slate-300">{r.estimated_tow_miles != null ? `${r.estimated_tow_miles} mi` : '—'}</span> },
    { key: 'actual_tow_miles',   label: 'Actual Miles',  sortable: true, render: r => <span className="font-mono text-slate-300">{r.actual_tow_miles != null ? `${r.actual_tow_miles} mi` : '—'}</span> },
  ],
}

// Plain-text values for CSV export
const CSV_COLUMNS = {
  'mh':        ['wo_number','facility','created_date','vehicle_make','vehicle_model'],
  'pg-fuel':   ['wo_number','facility','created_date','dispatch_code','fuel_type','entitlement_master','max_reimbursement'],
  'er-miles':  ['wo_number','facility','created_date','estimated_er_miles','ai_summary'],
  'tow-miles': ['wo_number','facility','created_date','resolution_code','estimated_tow_miles'],
  'tl-tolls':  ['wo_number','facility','created_date','estimated_tow_miles','actual_tow_miles'],
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

function RecTable({ items, columns, loading, error, filter, navigate }) {
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
  }, [items, filter, sortKey, sortDir])

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
        {filter ? 'No matches for your filter.' : 'No recommendations for this period.'}
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
              onClick={() => r.wo_id && navigate(`/contractor/accounting/calls/${r.wo_id}`, { state: { from: 'recs' } })}
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
        {filter && items.length !== filtered.length && ` (filtered from ${items.length})`}
      </div>
    </div>
  )
}

export default function ContractorAccountingRecs() {
  const navigate = useNavigate()
  const { start: defStart, end: defEnd, min: minDate } = defaultDates()
  const [startDate, setStartDate] = useState(defStart)
  const [endDate, setEndDate] = useState(defEnd)
  const [activeRec, setActiveRec] = useState('mh')
  const [recData, setRecData] = useState({})
  const [recLoading, setRecLoading] = useState({})
  const [recError, setRecError] = useState({})
  const [filter, setFilter] = useState('')
  const [showActioned, setShowActioned] = useState(false)

  const loadAll = useCallback((start, end, actioned) => {
    setFilter('')
    const s = start ?? startDate
    const e = end ?? endDate
    const inclActioned = actioned ?? showActioned
    REC_TABS.forEach(({ key }) => {
      setRecLoading(prev => ({ ...prev, [key]: true }))
      const params = new URLSearchParams({ start_date: s, end_date: e, include_actioned: inclActioned })
      fetch(`/api/contractor/recommendations/${key}?${params}`)
        .then(r => { if (!r.ok) throw new Error(`Server error ${r.status}`); return r.json() })
        .then(json => {
          setRecData(prev => ({ ...prev, [key]: json.items || [] }))
          setRecError(prev => ({ ...prev, [key]: json.warning || null }))
        })
        .catch(err => setRecError(prev => ({ ...prev, [key]: err.message || 'Failed to load' })))
        .finally(() => setRecLoading(prev => ({ ...prev, [key]: false })))
    })
  }, [startDate, endDate, showActioned])

  // Auto-load on mount
  useEffect(() => { loadAll() }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  const activeItems = recData[activeRec]
  const anyLoading = Object.values(recLoading).some(Boolean)

  const applyFilter = (items) => {
    if (!items) return []
    if (!filter) return items
    const q = filter.toLowerCase()
    return items.filter(r =>
      (r.wo_number || '').toLowerCase().includes(q) ||
      (r.facility || '').toLowerCase().includes(q) ||
      (r.vehicle_make || '').toLowerCase().includes(q) ||
      (r.vehicle_model || '').toLowerCase().includes(q) ||
      (r.ai_summary || '').toLowerCase().includes(q) ||
      (r.resolution_code || '').toLowerCase().includes(q)
    )
  }

  // Badge counts update when filter changes
  const filteredCounts = useMemo(() => {
    const counts = {}
    REC_TABS.forEach(({ key }) => { counts[key] = applyFilter(recData[key]).length })
    return counts
  }, [recData, filter]) // eslint-disable-line react-hooks/exhaustive-deps

  // Export uses filtered set
  const activeFiltered = useMemo(() => applyFilter(activeItems), [activeItems, filter]) // eslint-disable-line react-hooks/exhaustive-deps
  const canExport = activeFiltered.length > 0 && !recLoading[activeRec]

  return (
    <div>
      {/* Controls */}
      <div className="glass rounded-xl border border-slate-700/30 p-4 mb-4 flex flex-wrap items-end gap-4">
        <div className="flex flex-col gap-1">
          <label className="text-[10px] text-slate-500 uppercase tracking-wider">Start Date</label>
          <input type="date" value={startDate} min={minDate} onChange={e => { setStartDate(e.target.value); e.target.blur() }}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/50" />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] text-slate-500 uppercase tracking-wider">End Date</label>
          <input type="date" value={endDate} onChange={e => { setEndDate(e.target.value); e.target.blur() }}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/50" />
        </div>
        <button onClick={() => loadAll()}
          className="flex items-center gap-2 px-5 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-semibold transition-all">
          {anyLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
          {anyLoading ? 'Loading…' : 'Load Recommendations'}
        </button>
        <div className="self-center">
          <InfoTip text={"RECOMMENDATIONS\n\nCompleted/closed calls where your facility may be owed a Work Order Adjustment (WOA) you haven't claimed yet.\n\nFIVE TYPES (sub-tabs):\n  • MH — Medium Duty on approved-vehicle tows\n  • PG Fuel — fuel delivery\n  • ER Miles — enroute mileage\n  • Tow Miles — tow mileage\n  • TL Tolls — tolls\n\nRULES:\n  • Only completed/closed calls — never cancelled\n  • Hidden if a WOLI was already PAID for that product\n  • Hidden if a WOA already exists with status New or Approved. Rejected WOAs reappear so you can resubmit.\n  • MH: only tows of vehicles on the Approved List\n  • PG Fuel: shows coverage level (excludes Basic members)\n\nTurn on 'Show already-actioned' to also see paid/submitted ones, marked Paid / WOA submitted."} />
        </div>
        <label className="flex items-center gap-2 cursor-pointer select-none text-sm text-slate-300">
          <input
            type="checkbox"
            checked={showActioned}
            onChange={e => { const v = e.target.checked; setShowActioned(v); loadAll(undefined, undefined, v) }}
            className="w-4 h-4 rounded border-slate-600 bg-slate-800 text-indigo-500 focus:ring-indigo-500/50 focus:ring-offset-0"
          />
          Show already-actioned
        </label>
        <div className="relative ml-auto flex items-center gap-2 flex-wrap">
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
          const totalCount = recData[key]?.length
          const filteredCount = filteredCounts[key]
          const isLoading = recLoading[key]
          const badgeCount = filter ? filteredCount : totalCount
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
              {badgeCount != null && badgeCount > 0 && (
                <span className="px-1.5 py-0.5 rounded-full text-[10px] font-bold bg-indigo-500/30 text-indigo-300">
                  {badgeCount}
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
          navigate={navigate}
          tabKey={activeRec}
        />
      </div>
    </div>
  )
}
