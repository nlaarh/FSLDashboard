import { useState, useEffect } from 'react'
import { clsx } from 'clsx'
import { ChevronDown, ChevronRight, AlertTriangle, Clock, ArrowUp, ArrowDown } from 'lucide-react'
import { fetchAccountingAging } from '../api'

const BUCKET_COLORS = {
  '0–15d':  { bg: 'bg-emerald-900/20', text: 'text-emerald-400',  heat: (n) => n > 0 ? `rgba(52,211,153,${Math.min(0.15 + n * 0.05, 0.6)})` : '' },
  '16–30d': { bg: 'bg-yellow-900/20',  text: 'text-yellow-400',   heat: (n) => n > 0 ? `rgba(250,204,21,${Math.min(0.15 + n * 0.05, 0.6)})` : '' },
  '31–45d': { bg: 'bg-orange-900/20',  text: 'text-orange-400',   heat: (n) => n > 0 ? `rgba(251,146,60,${Math.min(0.15 + n * 0.05, 0.6)})` : '' },
  '46–60d': { bg: 'bg-red-900/20',     text: 'text-red-400',      heat: (n) => n > 0 ? `rgba(248,113,113,${Math.min(0.15 + n * 0.05, 0.65)})` : '' },
  '61–90d': { bg: 'bg-red-900/30',     text: 'text-red-300',      heat: (n) => n > 0 ? `rgba(239,68,68,${Math.min(0.2 + n * 0.06, 0.75)})` : '' },
  '90+d':   { bg: 'bg-rose-900/40',    text: 'text-rose-300',     heat: (n) => n > 0 ? `rgba(225,29,72,${Math.min(0.25 + n * 0.07, 0.85)})` : '' },
}

function DrillDown({ woas, bucket }) {
  if (!woas || woas.length === 0) return null
  const color = BUCKET_COLORS[bucket]
  return (
    <div className="mt-2 rounded-lg border border-slate-700/40 overflow-hidden">
      <table className="w-full text-[10px]">
        <thead>
          <tr className="bg-slate-800/60">
            <th className="text-left px-2 py-1 text-slate-400 font-medium">WOA #</th>
            <th className="text-left px-2 py-1 text-slate-400 font-medium">Product</th>
            <th className="text-right px-2 py-1 text-slate-400 font-medium">Age</th>
            <th className="text-right px-2 py-1 text-slate-400 font-medium">Est. $</th>
            <th className="text-left px-2 py-1 text-slate-400 font-medium">Rec</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/40">
          {woas.map((w) => (
            <tr key={w.id} className="hover:bg-slate-800/30">
              <td className="px-2 py-1 font-mono text-blue-400">{w.woa_number}</td>
              <td className="px-2 py-1 text-slate-300">{w.code}</td>
              <td className={clsx('px-2 py-1 text-right font-semibold', color?.text)}>{w.age_days}d</td>
              <td className="px-2 py-1 text-right text-slate-300">
                {w.estimated_usd != null ? `$${w.estimated_usd.toFixed(2)}` : '—'}
              </td>
              <td className="px-2 py-1">
                <span className={clsx('px-1.5 py-0.5 rounded text-[9px] font-bold uppercase',
                  w.recommendation === 'approve' ? 'bg-emerald-900/40 text-emerald-400'
                    : w.recommendation === 'deny' ? 'bg-red-900/40 text-red-400'
                    : 'bg-amber-900/40 text-amber-400')}>
                  {w.recommendation || '?'}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function HeatCell({ bucket, cell, facility }) {
  const [open, setOpen] = useState(false)
  const color = BUCKET_COLORS[bucket]
  const bg = color?.heat(cell.count) || ''

  if (cell.count === 0) {
    return <td className="px-2 py-2 text-center text-slate-700 text-[10px]">—</td>
  }

  return (
    <td className="px-1 py-1 align-top" style={{ minWidth: 64 }}>
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full rounded px-2 py-1.5 text-center transition-all hover:opacity-90 cursor-pointer"
        style={{ backgroundColor: bg }}
        title={`${cell.count} WOA${cell.count !== 1 ? 's' : ''} · $${cell.usd.toFixed(2)}`}
      >
        <div className={clsx('text-[11px] font-bold', color?.text)}>{cell.count}</div>
        <div className="text-[9px] text-slate-400">${cell.usd < 1000 ? cell.usd.toFixed(0) : `${(cell.usd / 1000).toFixed(1)}k`}</div>
      </button>
      {open && (
        <div className="absolute z-20 left-0 right-0 px-4 mt-1">
          <div className="glass rounded-xl border border-slate-700/40 p-3 shadow-2xl">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] font-semibold text-slate-300">{facility} · {bucket}</span>
              <button onClick={() => setOpen(false)} className="text-slate-500 hover:text-slate-300 text-[10px]">close</button>
            </div>
            <DrillDown woas={cell.woas} bucket={bucket} />
          </div>
        </div>
      )}
    </td>
  )
}

function SortIcon({ col, sortCol, sortDir }) {
  if (col !== sortCol) return <span className="text-slate-700 ml-0.5">↕</span>
  return sortDir === 'asc'
    ? <ArrowUp size={9} className="inline ml-0.5 text-slate-300" />
    : <ArrowDown size={9} className="inline ml-0.5 text-slate-300" />
}

export default function AccountingAgingHeatmap({ status = 'open' }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [collapsed, setCollapsed] = useState(false)
  const [search, setSearch] = useState('')
  const [sortCol, setSortCol] = useState('oldest_days')
  const [sortDir, setSortDir] = useState('desc')

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchAccountingAging(status)
      .then(setData)
      .catch(() => setError('Failed to load aging data'))
      .finally(() => setLoading(false))
  }, [status])

  const buckets = data?.buckets || []

  const allFacilities = data?.facilities || []
  const totalOpenWoas = allFacilities.reduce((s, f) => s + f.total, 0)

  const handleSort = (col) => {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortCol(col); setSortDir('desc') }
  }

  const facilities = allFacilities
    .filter(f => !search || f.facility.toLowerCase().includes(search.toLowerCase()))
    .slice()
    .sort((a, b) => {
      const v = sortCol === 'total' ? a.total - b.total : a.oldest_days - b.oldest_days
      return sortDir === 'asc' ? v : -v
    })

  // Summary stats
  const has90plus = facilities.filter(f => f.cells['90+d']?.count > 0).length
  const oldest = allFacilities[0] ? Math.max(...allFacilities.map(f => f.oldest_days)) : 0
  const totalWarning = allFacilities.reduce((s, f) =>
    s + (f.cells['61–90d']?.count || 0) + (f.cells['90+d']?.count || 0), 0)

  return (
    <div className="glass rounded-xl border border-slate-700/30 overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setCollapsed(v => !v)}
        className="w-full px-4 py-3 flex items-center justify-between border-b border-slate-800/60 hover:bg-slate-800/30 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Clock size={13} className="text-amber-400" />
          <span className="text-xs font-semibold text-slate-200">WOA Aging by Garage</span>
          {!loading && data && (
            <span className="text-[10px] text-slate-500">
              {allFacilities.length} garages · as of {data.as_of}
            </span>
          )}
          {totalWarning > 0 && (
            <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-red-900/30 border border-red-800/40 text-[9px] text-red-400 font-semibold">
              <AlertTriangle size={9} />
              {totalWarning} WOA{totalWarning !== 1 ? 's' : ''} 60+ days
            </span>
          )}
        </div>
        {collapsed ? <ChevronRight size={13} className="text-slate-500" /> : <ChevronDown size={13} className="text-slate-500" />}
      </button>

      {!collapsed && (
        <div className="p-4">
          {loading && (
            <div className="text-center py-8 text-slate-500 text-xs">Loading aging data…</div>
          )}

          {!loading && error && (
            <div className="text-center py-8 text-red-400 text-xs">{error}</div>
          )}

          {!loading && !error && data && (
            <>
              {/* Summary strip — 4 cards */}
              <div className="grid grid-cols-4 gap-3 mb-4">
                <div className="glass rounded-lg border border-slate-700/30 p-3 text-center">
                  <div className="text-[10px] text-slate-500 mb-0.5">Total Open WOAs</div>
                  <div className="text-lg font-bold text-slate-200">{totalOpenWoas}</div>
                </div>
                <div className="glass rounded-lg border border-slate-700/30 p-3 text-center">
                  <div className="text-[10px] text-slate-500 mb-0.5">Oldest WOA</div>
                  <div className={clsx('text-lg font-bold', oldest > 90 ? 'text-rose-400' : oldest > 60 ? 'text-red-400' : oldest > 30 ? 'text-orange-400' : 'text-slate-200')}>
                    {oldest}d
                  </div>
                </div>
                <div className="glass rounded-lg border border-slate-700/30 p-3 text-center">
                  <div className="text-[10px] text-slate-500 mb-0.5">Garages w/ 90+ Days</div>
                  <div className={clsx('text-lg font-bold', has90plus > 0 ? 'text-rose-400' : 'text-emerald-400')}>
                    {has90plus}
                  </div>
                </div>
                <div className="glass rounded-lg border border-slate-700/30 p-3 text-center">
                  <div className="text-[10px] text-slate-500 mb-0.5">WOAs 60+ Days</div>
                  <div className={clsx('text-lg font-bold', totalWarning > 0 ? 'text-red-400' : 'text-emerald-400')}>
                    {totalWarning}
                  </div>
                </div>
              </div>

              {/* Search */}
              <input
                type="text"
                placeholder="Filter garage…"
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="w-full mb-3 px-3 py-1.5 text-xs bg-slate-800/50 border border-slate-700/40 rounded-lg text-slate-200 placeholder-slate-600 focus:outline-none focus:border-slate-500"
              />

              {/* Legend */}
              <div className="flex items-center gap-3 mb-3 flex-wrap">
                {buckets.map(b => (
                  <div key={b} className="flex items-center gap-1">
                    <div className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: BUCKET_COLORS[b]?.heat(3) }} />
                    <span className={clsx('text-[10px]', BUCKET_COLORS[b]?.text)}>{b}</span>
                  </div>
                ))}
                <span className="text-[9px] text-slate-600 ml-1">Click any cell to see WOAs</span>
              </div>

              {/* Heatmap table */}
              <div className="overflow-x-auto">
                <table className="w-full text-[11px] border-collapse">
                  <thead>
                    <tr className="border-b border-slate-800/60">
                      <th className="text-left px-3 py-2 text-slate-400 font-medium min-w-[200px]">Garage</th>
                      <th
                        className="text-right px-2 py-2 text-slate-400 font-medium cursor-pointer hover:text-slate-200 select-none"
                        onClick={() => handleSort('total')}
                      >
                        Total <SortIcon col="total" sortCol={sortCol} sortDir={sortDir} />
                      </th>
                      <th
                        className="text-right px-2 py-2 text-slate-400 font-medium cursor-pointer hover:text-slate-200 select-none"
                        onClick={() => handleSort('oldest_days')}
                      >
                        Oldest <SortIcon col="oldest_days" sortCol={sortCol} sortDir={sortDir} />
                      </th>
                      {buckets.map(b => (
                        <th key={b} className={clsx('text-center px-2 py-2 font-semibold', BUCKET_COLORS[b]?.text)}>
                          {b}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/30">
                    {facilities.map((f) => (
                      <tr key={f.facility} className="hover:bg-slate-800/20 relative">
                        <td className="px-3 py-2 text-slate-200 font-medium max-w-[220px] truncate" title={f.facility}>
                          {f.facility}
                        </td>
                        <td className="px-2 py-2 text-right text-slate-300 font-semibold">{f.total}</td>
                        <td className={clsx('px-2 py-2 text-right font-bold',
                          f.oldest_days > 90 ? 'text-rose-400' : f.oldest_days > 60 ? 'text-red-400' : f.oldest_days > 30 ? 'text-orange-400' : 'text-slate-400')}>
                          {f.oldest_days}d
                        </td>
                        {buckets.map(b => (
                          <HeatCell key={b} bucket={b} cell={f.cells[b] || { count: 0, usd: 0, woas: [] }} facility={f.facility} />
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {facilities.length === 0 && (
                  <div className="text-center py-6 text-slate-500 text-xs">No garages match your filter.</div>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
