import { useState, useEffect } from 'react'
import { Loader2, AlertCircle, ExternalLink } from 'lucide-react'
import { clsx } from 'clsx'
import { fetchDriverRevenueDaily } from '../api'

export const TYPE_COLORS = {
  'Tow Pick-Up':          'bg-blue-500',
  'Tow Drop-Off':         'bg-slate-600',
  'Battery':              'bg-amber-500',
  'Jumpstart':            'bg-amber-500',
  'Tire':                 'bg-purple-500',
  'Lockout':              'bg-teal-500',
  'Fuel / Miscellaneous': 'bg-orange-500',
  'Winch Out':            'bg-rose-500',
  'Locksmith':            'bg-cyan-500',
  'Other':                'bg-slate-500',
}
export const typeColor = (t) => TYPE_COLORS[t] || 'bg-slate-500'
export const fmtRevFull = (v) => `$${v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
export const batteryTypes = new Set(['Battery', 'Jumpstart'])

const TYPE_ORDER = ['Tow Pick-Up', 'Tow Drop-Off', 'Battery', 'Jumpstart', 'Tire', 'Lockout', 'Fuel / Miscellaneous', 'Winch Out', 'Locksmith']

const COL_SHORT = (t) => ({
  'Tow Pick-Up':          'T↑',
  'Tow Drop-Off':         'T↓',
  'Battery':              'Bat',
  'Jumpstart':            'JS',
  'Tire':                 'Tire',
  'Lockout':              'Lck',
  'Fuel / Miscellaneous': 'Fuel',
  'Winch Out':            'Wnch',
  'Locksmith':            'Lksm',
}[t] ?? t.slice(0, 3))

const COL_LABEL = (t) => t
  .replace('Tow Pick-Up', 'Tow P/U')
  .replace('Tow Drop-Off', 'Drop-Off')
  .replace('Fuel / Miscellaneous', 'Fuel/Misc')

export default function DriverDrillDown({ garageId, driverName, startDate, endDate }) {
  const [data, setData]             = useState(null)
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState(null)
  const [expandedDate, setExpandedDate] = useState(null)

  useEffect(() => {
    setLoading(true); setData(null); setError(null)
    fetchDriverRevenueDaily(garageId, driverName, startDate, endDate)
      .then(setData)
      .catch(e => setError(e?.response?.data?.detail || 'Failed to load'))
      .finally(() => setLoading(false))
  }, [garageId, driverName, startDate, endDate])

  if (loading) return (
    <div className="flex items-center gap-2 py-4 justify-center">
      <Loader2 className="w-4 h-4 animate-spin text-slate-500" />
      <span className="text-xs text-slate-500">Loading driver detail from Salesforce…</span>
    </div>
  )
  if (error) return (
    <div className="flex items-center gap-2 py-3 text-red-400 text-xs">
      <AlertCircle className="w-4 h-4 shrink-0" />{error}
    </div>
  )
  if (!data) return null

  const { days, type_summary } = data

  const typeSet = new Set()
  days.forEach(d => Object.keys(d.calls_by_type || {}).forEach(t => typeSet.add(t)))
  const typeColumns = [
    ...TYPE_ORDER.filter(t => typeSet.has(t)),
    ...[...typeSet].filter(t => !TYPE_ORDER.includes(t)).sort(),
  ]

  const totalMemberCollected = days.reduce((s, r) => s + (r.member_collected || 0), 0)

  const totalAAARev = days.reduce((s, r) => s + (r.revenue || 0) + (r.battery_revenue || 0), 0)
  const totalGrand  = totalAAARev + totalMemberCollected

  return (
    <div className="mt-3 space-y-5 pb-2">

      {/* ── Daily breakdown ─────────────────────────────────────────────── */}
      <div>
        <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-2">
          Daily Breakdown
          <span className="ml-2 normal-case font-normal text-slate-600">
            ({typeColumns.map(t => `${COL_SHORT(t)}=${COL_LABEL(t)}`).join(' · ')})
          </span>
        </div>
        <div>
          <table className="w-full table-fixed text-[11px]">
            <colgroup>
              <col style={{width:'88px'}} />
              {typeColumns.map(t => <col key={t} style={{width:'28px'}} />)}
              <col style={{width:'34px'}} />
              <col style={{width:'38px'}} />
              <col style={{width:'72px'}} />
              {totalMemberCollected > 0 && <col style={{width:'68px'}} />}
              {totalMemberCollected > 0 && <col style={{width:'72px'}} />}
            </colgroup>
            <thead>
              <tr className="border-b border-slate-800/60">
                <th className="text-left py-1 px-1 text-slate-500 font-medium">Date</th>
                {typeColumns.map(t => (
                  <th key={t} title={COL_LABEL(t)} className="text-center py-1 px-0 text-[9px] font-medium">
                    <span className={clsx('inline-block w-4 h-4 rounded text-[8px] font-bold leading-4 text-center text-white', typeColor(t))}>
                      {COL_SHORT(t).slice(0,1)}
                    </span>
                  </th>
                ))}
                <th className="text-right py-1 px-1 text-slate-500 font-medium text-[10px]">#</th>
                <th className="text-right py-1 px-1 text-slate-500 font-medium text-[10px]">Hrs</th>
                <th className="text-right py-1 px-1 text-emerald-600/80 font-medium text-[10px]">Revenue</th>
                {totalMemberCollected > 0 && (
                  <th className="text-right py-1 px-1 text-sky-500/80 font-medium text-[10px]">Mbr</th>
                )}
                {totalMemberCollected > 0 && (
                  <th className="text-right py-1 px-1 text-white font-medium text-[10px]">Total</th>
                )}
              </tr>
            </thead>
            <tbody>
              {days.map(row => {
                const aaaRev   = (row.revenue || 0) + (row.battery_revenue || 0)
                const mc       = row.member_collected || 0
                const rowTotal = aaaRev + mc
                const isExpanded = expandedDate === row.date
                const hasWOs = (row.wo_details || []).length > 0
                const extraCols = 3 + (totalMemberCollected > 0 ? 2 : 0)
                return (
                  <>
                    <tr
                      key={row.date}
                      className={clsx(
                        'border-b border-slate-800/30',
                        hasWOs ? 'cursor-pointer hover:bg-slate-800/30' : 'hover:bg-slate-800/20',
                        isExpanded && 'bg-slate-800/30'
                      )}
                      onClick={() => hasWOs && setExpandedDate(isExpanded ? null : row.date)}
                    >
                      <td className="py-1 px-1 text-slate-400 truncate">
                        {hasWOs && <span className="text-[8px] text-brand-400 mr-0.5">{isExpanded ? '▲' : '▼'}</span>}
                        <span className={clsx('text-[10px]', hasWOs && 'text-slate-300 font-medium')}>
                          {new Date(row.date + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                        </span>
                      </td>
                      {typeColumns.map(t => (
                        <td key={t} className="py-1 px-0 text-center">
                          {row.calls_by_type?.[t]
                            ? <span className={clsx('inline-block w-4 h-4 rounded text-[9px] font-bold leading-4 text-center text-white', typeColor(t))}>{row.calls_by_type[t]}</span>
                            : <span className="text-slate-800 text-[9px]">·</span>}
                        </td>
                      ))}
                      <td className="py-1 px-1 text-right text-slate-300 font-medium text-[10px]">
                        {Object.values(row.calls_by_type || {}).reduce((s, v) => s + v, 0)}
                      </td>
                      <td className="py-1 px-1 text-right text-slate-400 text-[10px]">
                        {row.hours > 0 ? `${row.hours}h` : '—'}
                      </td>
                      <td className="py-1 px-1 text-right text-emerald-400 font-medium text-[10px]">
                        {aaaRev > 0 ? `$${aaaRev.toLocaleString('en-US',{minimumFractionDigits:0,maximumFractionDigits:0})}` : <span className="text-slate-700">—</span>}
                      </td>
                      {totalMemberCollected > 0 && (
                        <td className="py-1 px-1 text-right text-sky-400 font-medium text-[10px]">
                          {mc > 0 ? `$${mc.toLocaleString('en-US',{minimumFractionDigits:0,maximumFractionDigits:0})}` : <span className="text-slate-700">—</span>}
                        </td>
                      )}
                      {totalMemberCollected > 0 && (
                        <td className="py-1 px-1 text-right text-white font-bold text-[10px]">
                          {rowTotal > 0 ? `$${rowTotal.toLocaleString('en-US',{minimumFractionDigits:0,maximumFractionDigits:0})}` : <span className="text-slate-700">—</span>}
                        </td>
                      )}
                    </tr>
                    {isExpanded && (row.wo_details || []).length > 0 && (
                      <tr key={`${row.date}-wos`} className="border-b border-slate-800/30 bg-slate-900/60">
                        <td colSpan={typeColumns.length + extraCols} className="px-3 py-2">
                          <table className="w-full text-[10px]">
                            <thead>
                              <tr className="border-b border-slate-700/40">
                                <th className="text-left py-1 px-1 text-slate-500 font-medium">WO #</th>
                                <th className="text-left py-1 px-1 text-slate-500 font-medium">Type</th>
                                <th className="text-right py-1 px-1 text-emerald-600/70 font-medium">Amount</th>
                                <th className="w-8 py-1 px-1" />
                              </tr>
                            </thead>
                            <tbody>
                              {(row.wo_details || []).map(wo => (
                                <tr key={wo.wo_id} className="border-b border-slate-800/20 hover:bg-slate-800/20">
                                  <td className="py-1 px-1 font-mono text-slate-300 text-[10px]">{wo.wo_number}</td>
                                  <td className="py-1 px-1">
                                    <div className="flex items-center gap-1">
                                      <div className={clsx('w-1.5 h-1.5 rounded-full shrink-0', typeColor(wo.type))} />
                                      <span className="text-slate-400">{wo.type}</span>
                                    </div>
                                  </td>
                                  <td className="py-1 px-1 text-right text-emerald-400 font-medium">
                                    {wo.amount > 0 ? fmtRevFull(wo.amount) : <span className="text-slate-600">$0</span>}
                                  </td>
                                  <td className="py-1 px-1 text-right">
                                    {wo.sf_url && (
                                      <a href={wo.sf_url} target="_blank" rel="noopener noreferrer"
                                        className="inline-flex items-center gap-0.5 text-[9px] text-brand-400 hover:text-brand-300"
                                        onClick={e => e.stopPropagation()}>
                                        <ExternalLink className="w-2.5 h-2.5" />SF
                                      </a>
                                    )}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </td>
                      </tr>
                    )}
                  </>
                )
              })}
            </tbody>
            <tfoot>
              <tr className="border-t border-slate-700/50">
                <td className="py-1.5 px-1 text-slate-400 font-semibold text-[10px]">Total</td>
                {typeColumns.map(t => (
                  <td key={t} className="py-1.5 px-0 text-center text-slate-300 font-semibold text-[10px]">
                    {days.reduce((s, r) => s + (r.calls_by_type?.[t] || 0), 0) || ''}
                  </td>
                ))}
                <td className="py-1.5 px-1 text-right text-slate-200 font-bold text-[10px]">
                  {days.reduce((s, r) => s + Object.values(r.calls_by_type || {}).reduce((a, v) => a + v, 0), 0)}
                </td>
                <td className="py-1.5 px-1 text-right text-slate-300 font-semibold text-[10px]">
                  {days.reduce((s, r) => s + r.hours, 0).toFixed(1)}h
                </td>
                <td className="py-1.5 px-1 text-right text-emerald-300 font-bold text-[10px]">
                  {fmtRevFull(totalAAARev)}
                </td>
                {totalMemberCollected > 0 && (
                  <td className="py-1.5 px-1 text-right text-sky-300 font-bold text-[10px]">
                    {fmtRevFull(totalMemberCollected)}
                  </td>
                )}
                {totalMemberCollected > 0 && (
                  <td className="py-1.5 px-1 text-right text-white font-bold text-[10px]">
                    {fmtRevFull(totalGrand)}
                  </td>
                )}
              </tr>
            </tfoot>
          </table>
        </div>
      </div>

      {/* ── Call-type summary ────────────────────────────────────────────── */}
      {type_summary?.length > 0 && (
        <div>
          <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-2">By Call Type</div>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-slate-800/60">
                  <th className="text-left py-1.5 px-2 text-slate-500 font-medium">Type</th>
                  <th className="text-right py-1.5 px-2 text-slate-500 font-medium">Calls</th>
                  <th className="text-left py-1.5 px-2 text-slate-500 font-medium">Share</th>
                  <th className="text-right py-1.5 px-2 text-slate-500 font-medium">Revenue</th>
                  <th className="text-right py-1.5 px-2 text-slate-500 font-medium">Avg/Call</th>
                </tr>
              </thead>
              <tbody>
                {(() => {
                  const total = type_summary.reduce((s, t) => s + t.count, 0)
                  return type_summary.map(row => (
                    <tr key={row.type} className="border-b border-slate-800/30 hover:bg-slate-800/20">
                      <td className="py-1.5 px-2">
                        <div className="flex items-center gap-1.5">
                          <div className={clsx('w-2 h-2 rounded-full shrink-0', typeColor(row.type))} />
                          <span className="text-slate-300">{row.type}</span>
                        </div>
                      </td>
                      <td className="py-1.5 px-2 text-right text-slate-300 font-semibold">{row.count}</td>
                      <td className="py-1.5 px-2">
                        <div className="flex items-center gap-1.5">
                          <div className="flex-1 h-2 bg-slate-800 rounded overflow-hidden w-16">
                            <div className={clsx('h-full rounded', typeColor(row.type))}
                              style={{ width: `${total > 0 ? Math.round(row.count / total * 100) : 0}%` }} />
                          </div>
                          <span className="text-[10px] text-slate-500 w-8">
                            {total > 0 ? `${Math.round(row.count / total * 100)}%` : '—'}
                          </span>
                        </div>
                      </td>
                      <td className="py-1.5 px-2 text-right text-emerald-400 font-medium">
                        {row.revenue > 0 ? fmtRevFull(row.revenue) : <span className="text-slate-700">$0</span>}
                      </td>
                      <td className="py-1.5 px-2 text-right text-slate-400">
                        {row.avg_per_call > 0 ? `$${row.avg_per_call.toFixed(0)}` : '—'}
                      </td>
                    </tr>
                  ))
                })()}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
