import { useState, useEffect, useMemo } from 'react'
import { FileText, Download, ChevronUp, ChevronDown, Loader2, BarChart3, Search, CheckSquare, Square } from 'lucide-react'
import { fetchGarages, fetchReportSummary, exportReportSummary } from '../api'
import { getMonth } from '../utils/dateHelpers'

const ALL_METRICS = [
  // Volume
  { key: 'total_sas',              label: 'Total SAs',            group: 'Volume' },
  { key: 'completed',              label: 'Completed',             group: 'Volume' },
  { key: 'completion_pct',         label: 'Completion %',          group: 'Volume', pct: true },
  { key: 'declined',               label: 'Declined',              group: 'Volume' },
  { key: 'cancelled',              label: 'Cancelled',             group: 'Volume' },
  { key: 'decline_rate',           label: 'Decline %',             group: 'Volume' },
  // Acceptance
  { key: 'first_call_pct',         label: '1st Call Accept %',     group: 'Acceptance', pct: true },
  { key: 'second_call_pct',        label: '2nd+ Call Accept %',    group: 'Acceptance', pct: true },
  { key: 'accepted_completion_pct',label: 'Accept Completion %',   group: 'Acceptance', pct: true },
  // Response Time
  { key: 'avg_ata',                label: 'Avg ATA (min)',         group: 'Response Time' },
  { key: 'median_ata',             label: 'Median ATA (min)',      group: 'Response Time' },
  { key: 'under_45_pct',           label: '% Under 45 min',        group: 'Response Time', pct: true },
  { key: 'over_120_pct',           label: '% Over 2 hrs',          group: 'Response Time', pct: true },
  // PTA
  { key: 'avg_pta',                label: 'Avg PTA (min)',         group: 'PTA' },
  { key: 'pta_hit_pct',            label: 'PTA Hit %',             group: 'PTA', pct: true },
  { key: 'pta_on_time_pct',        label: 'PTA On-Time %',         group: 'PTA', pct: true },
  { key: 'pta_avg_delta',          label: 'PTA Avg Delta (min)',   group: 'PTA' },
  // Satisfaction
  { key: 'total_surveys',          label: 'Surveys',               group: 'Satisfaction' },
  { key: 'overall_pct',            label: 'Overall Sat %',         group: 'Satisfaction', pct: true },
  { key: 'response_time_pct',      label: 'RT Sat %',              group: 'Satisfaction', pct: true },
  { key: 'technician_pct',         label: 'Tech Sat %',            group: 'Satisfaction', pct: true },
  { key: 'kept_informed_pct',      label: 'KI Sat %',              group: 'Satisfaction', pct: true },
  // Bonus
  { key: 'bonus_tier',             label: 'Bonus Tier',            group: 'Bonus' },
  { key: 'bonus_per_sa',           label: 'Bonus/SA ($)',          group: 'Bonus', money: true },
  { key: 'total_bonus',            label: 'Total Bonus ($)',       group: 'Bonus', money: true },
]

// Exclude dispatch-zone territory codes (e.g. CR035, DO123) — only letters+digits, no spaces
const isRealGarage = (name) => /\s/.test(name)

function pctColor(val) {
  if (val == null) return 'text-slate-500'
  if (val >= 90) return 'text-emerald-400'
  if (val >= 75) return 'text-amber-400'
  return 'text-red-400'
}

function SortIcon({ dir }) {
  if (!dir) return <ChevronUp className="w-3 h-3 opacity-20" />
  if (dir === 'asc') return <ChevronUp className="w-3 h-3 text-brand-400" />
  return <ChevronDown className="w-3 h-3 text-brand-400" />
}

function MetricCell({ value, metric }) {
  if (value == null || value === '') return <td className="px-3 py-2 text-center text-slate-600 text-xs">—</td>
  let display = value
  if (metric.pct) display = `${value}%`
  else if (metric.money) display = `$${typeof value === 'number' ? value.toLocaleString() : value}`
  else if (typeof value === 'number') display = value.toLocaleString()
  const colorClass = metric.pct ? pctColor(value) : metric.money ? 'text-emerald-400' : 'text-slate-200'
  return (
    <td className={`px-3 py-2 text-center text-sm font-medium ${colorClass}`}>
      {display}
    </td>
  )
}

function Check({ checked, onChange, label }) {
  return (
    <label className="flex items-center gap-2 cursor-pointer group py-0.5">
      <span onClick={onChange} className="flex-shrink-0">
        {checked
          ? <CheckSquare className="w-3.5 h-3.5 text-brand-400" />
          : <Square className="w-3.5 h-3.5 text-slate-600 group-hover:text-slate-400" />}
      </span>
      <span className="text-xs text-slate-300 group-hover:text-white truncate" onClick={onChange}>
        {label}
      </span>
    </label>
  )
}

export default function Reporting() {
  // ── Date range ─────────────────────────────────────────────────────────────
  const thisMonth = getMonth(0)
  const [startDate, setStartDate] = useState(thisMonth.start)
  const [endDate, setEndDate] = useState(thisMonth.end)

  const months = useMemo(() =>
    Array.from({ length: 6 }, (_, i) => {
      const m = getMonth(-i)
      return { label: m.label, start: m.start, end: m.end }
    }), [])

  const isActiveMonth = (m) => m.start === startDate && m.end === endDate

  // ── Garages ────────────────────────────────────────────────────────────────
  const [allGarages, setAllGarages] = useState([])
  const [garageSearch, setGarageSearch] = useState('')
  const [selectedGarageIds, setSelectedGarageIds] = useState(new Set())
  const [garagesLoading, setGaragesLoading] = useState(true)

  useEffect(() => {
    fetchGarages()
      .then(gs => {
        const real = gs.filter(g => g.active !== false && isRealGarage(g.name))
        real.sort((a, b) => a.name.localeCompare(b.name))
        setAllGarages(real)
      })
      .finally(() => setGaragesLoading(false))
  }, [])

  const filteredGarages = useMemo(() =>
    allGarages.filter(g => g.name.toLowerCase().includes(garageSearch.toLowerCase())),
    [allGarages, garageSearch])

  const toggleGarage = (id) => setSelectedGarageIds(prev => {
    const next = new Set(prev)
    next.has(id) ? next.delete(id) : next.add(id)
    return next
  })

  const selectAll = () => setSelectedGarageIds(new Set(filteredGarages.map(g => g.id)))
  const clearAll = () => setSelectedGarageIds(new Set())

  // ── Metrics ────────────────────────────────────────────────────────────────
  const defaultMetrics = new Set(['total_sas', 'completion_pct', 'declined', 'first_call_pct', 'avg_ata', 'under_45_pct', 'pta_hit_pct', 'overall_pct', 'technician_pct', 'total_bonus'])
  const [selectedMetrics, setSelectedMetrics] = useState(defaultMetrics)

  const toggleMetric = (key) => setSelectedMetrics(prev => {
    const next = new Set(prev)
    next.has(key) ? next.delete(key) : next.add(key)
    return next
  })

  const selectAllMetrics = () => setSelectedMetrics(new Set(ALL_METRICS.map(m => m.key)))
  const clearAllMetrics = () => setSelectedMetrics(new Set())

  const visibleMetrics = ALL_METRICS.filter(m => selectedMetrics.has(m.key))

  // ── Report data ────────────────────────────────────────────────────────────
  const [rows, setRows] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [reportDates, setReportDates] = useState(null)

  const garageNameMap = useMemo(() =>
    Object.fromEntries(allGarages.map(g => [g.id, g.name])), [allGarages])

  const generate = async () => {
    if (selectedGarageIds.size === 0) return
    setLoading(true)
    setError(null)
    setRows(null)
    try {
      const ids = [...selectedGarageIds]
      const data = await fetchReportSummary(ids, startDate, endDate)
      const enriched = data.rows.map(r => ({
        ...r,
        garage_name: garageNameMap[r.garage_id] || r.garage_name || r.garage_id,
      }))
      setRows(enriched)
      setReportDates({ start: data.start_date, end: data.end_date })
    } catch (e) {
      setError(e.message || 'Failed to load report')
    } finally {
      setLoading(false)
    }
  }

  // ── Sort ───────────────────────────────────────────────────────────────────
  const [sortKey, setSortKey] = useState('garage_name')
  const [sortDir, setSortDir] = useState('asc')

  const handleSort = (key) => {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('asc') }
  }

  const sortedRows = useMemo(() => {
    if (!rows) return []
    return [...rows].sort((a, b) => {
      const av = a[sortKey] ?? (sortDir === 'asc' ? Infinity : -Infinity)
      const bv = b[sortKey] ?? (sortDir === 'asc' ? Infinity : -Infinity)
      if (typeof av === 'string') return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av)
      return sortDir === 'asc' ? av - bv : bv - av
    })
  }, [rows, sortKey, sortDir])

  return (
    <div className="space-y-4">

      {/* ── Three-column filter bar ──────────────────────────────────────── */}
      <div className="grid grid-cols-3 gap-4">

        {/* Column 1: Date Range */}
        <div className="glass rounded-xl p-4 border border-slate-700/50">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Date Range</p>
          <div className="flex flex-wrap gap-1 mb-3">
            {months.map(m => (
              <button key={m.start}
                onClick={() => { setStartDate(m.start); setEndDate(m.end) }}
                className={`px-2 py-0.5 rounded text-[11px] font-medium border transition-all ${
                  isActiveMonth(m)
                    ? 'bg-brand-600/30 text-brand-400 border-brand-500/30'
                    : 'text-slate-400 border-slate-700/50 hover:border-slate-600 hover:text-white'
                }`}>
                {m.label}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <p className="text-[10px] text-slate-500 mb-1">From</p>
              <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)}
                className="w-full bg-slate-800/50 border border-slate-700/50 rounded-lg px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-brand-500/50 [color-scheme:dark]" />
            </div>
            <div>
              <p className="text-[10px] text-slate-500 mb-1">To</p>
              <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)}
                className="w-full bg-slate-800/50 border border-slate-700/50 rounded-lg px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-brand-500/50 [color-scheme:dark]" />
            </div>
          </div>
        </div>

        {/* Column 2: Garages */}
        <div className="glass rounded-xl p-4 border border-slate-700/50 flex flex-col">
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Garages
              {selectedGarageIds.size > 0 && (
                <span className="ml-1.5 bg-brand-600/30 text-brand-400 rounded-full px-1.5 py-0.5 text-[10px]">
                  {selectedGarageIds.size}
                </span>
              )}
            </p>
            <div className="flex gap-1">
              <button onClick={selectAll} className="px-2 py-0.5 rounded text-[11px] font-medium border border-brand-500/40 text-brand-400 hover:bg-brand-600/20 transition-all">All</button>
              <button onClick={clearAll} className="px-2 py-0.5 rounded text-[11px] font-medium border border-slate-600/50 text-slate-400 hover:bg-slate-700/40 transition-all">None</button>
            </div>
          </div>
          <div className="relative mb-2">
            <Search className="w-3 h-3 text-slate-600 absolute left-2 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input type="text" value={garageSearch} onChange={e => setGarageSearch(e.target.value)}
              placeholder="Search garages..."
              className="w-full bg-slate-800/50 border border-slate-700/50 rounded-lg pl-6 pr-2 py-1 text-[11px] text-slate-300 placeholder-slate-600 focus:outline-none focus:border-brand-500/50" />
          </div>
          <div className="overflow-y-auto flex-1 space-y-0.5 max-h-40">
            {garagesLoading
              ? <p className="text-xs text-slate-500 text-center py-4">Loading…</p>
              : filteredGarages.map(g => (
                  <Check key={g.id} checked={selectedGarageIds.has(g.id)}
                    onChange={() => toggleGarage(g.id)} label={g.name} />
                ))}
          </div>
        </div>

        {/* Column 3: Metrics */}
        <div className="glass rounded-xl p-4 border border-slate-700/50 flex flex-col">
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Metrics</p>
            <div className="flex gap-1">
              <button onClick={selectAllMetrics} className="px-2 py-0.5 rounded text-[11px] font-medium border border-brand-500/40 text-brand-400 hover:bg-brand-600/20 transition-all">All</button>
              <button onClick={clearAllMetrics} className="px-2 py-0.5 rounded text-[11px] font-medium border border-slate-600/50 text-slate-400 hover:bg-slate-700/40 transition-all">None</button>
            </div>
          </div>
          <div className="overflow-y-auto flex-1 max-h-40">
            {['Volume', 'Acceptance', 'Response Time', 'PTA', 'Dispatch', 'Satisfaction', 'Bonus'].map(group => (
              <div key={group} className="mb-2">
                <p className="text-[10px] text-slate-600 uppercase tracking-wider mb-1">{group}</p>
                {ALL_METRICS.filter(m => m.group === group).map(m => (
                  <Check key={m.key} checked={selectedMetrics.has(m.key)}
                    onChange={() => toggleMetric(m.key)} label={m.label} />
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Generate button ──────────────────────────────────────────────── */}
      <button
        onClick={generate}
        disabled={selectedGarageIds.size === 0 || loading}
        className="w-full py-2.5 rounded-xl text-sm font-semibold bg-brand-600 hover:bg-brand-500 disabled:opacity-40 disabled:cursor-not-allowed transition-all text-white flex items-center justify-center gap-2">
        {loading
          ? <><Loader2 className="w-4 h-4 animate-spin" />Generating…</>
          : <><BarChart3 className="w-4 h-4" />Generate Report</>}
      </button>

      {/* ── Results ──────────────────────────────────────────────────────── */}
      {!rows && !loading && !error && (
        <div className="glass rounded-xl border border-slate-700/50 h-48 flex flex-col items-center justify-center text-slate-500 gap-3">
          <FileText className="w-10 h-10 opacity-30" />
          <p className="text-sm">Select garages and metrics, then click Generate Report</p>
        </div>
      )}

      {loading && (
        <div className="glass rounded-xl border border-slate-700/50 h-48 flex items-center justify-center gap-3 text-slate-400">
          <Loader2 className="w-6 h-6 animate-spin" />
          <span className="text-sm">Fetching {selectedGarageIds.size} garage{selectedGarageIds.size !== 1 ? 's' : ''}…</span>
        </div>
      )}

      {error && (
        <div className="glass rounded-xl border border-red-500/30 p-6 text-red-400 text-sm">{error}</div>
      )}

      {rows && !loading && (
        <div className="glass rounded-xl border border-slate-700/50 overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-700/50 flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold text-slate-200">Garage Performance Report</p>
              <p className="text-xs text-slate-500 mt-0.5">
                {reportDates?.start} → {reportDates?.end} · {rows.length} garage{rows.length !== 1 ? 's' : ''} · {visibleMetrics.length} metric{visibleMetrics.length !== 1 ? 's' : ''}
              </p>
            </div>
            <button
              onClick={() => exportReportSummary([...selectedGarageIds], startDate, endDate)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-emerald-600/20 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-600/30 transition-all">
              <Download className="w-3.5 h-3.5" />Export Excel
            </button>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="border-b border-slate-700/50 bg-slate-900/50">
                  <th onClick={() => handleSort('garage_name')}
                    className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider cursor-pointer hover:text-white whitespace-nowrap sticky left-0 bg-slate-900/90">
                    <span className="inline-flex items-center gap-1">
                      Garage <SortIcon dir={sortKey === 'garage_name' ? sortDir : null} />
                    </span>
                  </th>
                  {visibleMetrics.map(m => (
                    <th key={m.key} onClick={() => handleSort(m.key)}
                      className="px-3 py-2 text-center text-xs font-semibold text-slate-400 uppercase tracking-wider cursor-pointer hover:text-white whitespace-nowrap">
                      <span className="inline-flex items-center gap-1 justify-center">
                        {m.label} <SortIcon dir={sortKey === m.key ? sortDir : null} />
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sortedRows.map((row, i) => (
                  <tr key={row.garage_id}
                    className={`border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors ${i % 2 === 0 ? '' : 'bg-slate-900/20'}`}>
                    <td className="px-3 py-2 text-slate-200 font-medium whitespace-nowrap sticky left-0 bg-inherit">
                      {row.garage_name}
                      {row.garage_type && (
                        <span className="ml-1.5 text-[10px] text-slate-500">{row.garage_type}</span>
                      )}
                      {row.error && <span className="ml-1.5 text-[10px] text-red-400">Error</span>}
                    </td>
                    {visibleMetrics.map(m => (
                      <MetricCell key={m.key} value={row[m.key]} metric={m} />
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
