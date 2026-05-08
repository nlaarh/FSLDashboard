import { useState, useEffect } from 'react'
import { Loader2, AlertCircle } from 'lucide-react'
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

const COL_LABEL = (t) => t
  .replace('Tow Pick-Up', 'Tow P/U')
  .replace('Tow Drop-Off', 'Drop-Off')
  .replace('Fuel / Miscellaneous', 'Fuel/Misc')

export default function DriverDrillDown({ garageId, driverName, startDate, endDate }) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)

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

  const towCols  = typeColumns.filter(t => !batteryTypes.has(t))
  const battCols = typeColumns.filter(t => batteryTypes.has(t))

  const towLightSummary = type_summary?.filter(r => !batteryTypes.has(r.type)) || []
  const batterySummary  = type_summary?.filter(r => batteryTypes.has(r.type))  || []
  const totalBattRevDays = days.reduce((s, r) => s + (r.battery_revenue || 0), 0)

  return (
    <div className="mt-3 space-y-5 pb-2">

      {/* ── Tow/Light daily breakdown ────────────────────────────── */}
      <div>
        <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-2">
          Daily Breakdown — Tow / Light Revenue
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b border-slate-800/60">
                <th className="text-left py-1.5 px-2 text-slate-500 font-medium">Date</th>
                {towCols.map(t => (
                  <th key={t} className="text-center py-1.5 px-2 text-slate-500 font-medium whitespace-nowrap">
                    {COL_LABEL(t)}
                  </th>
                ))}
                <th className="text-right py-1.5 px-2 text-slate-500 font-medium">Total</th>
                <th className="text-right py-1.5 px-2 text-slate-500 font-medium">Hours</th>
                <th className="text-right py-1.5 px-2 text-slate-500 font-medium">Tow/Light Rev</th>
              </tr>
            </thead>
            <tbody>
              {days.map(row => {
                const towTotal = Object.entries(row.calls_by_type || {})
                  .filter(([t]) => !batteryTypes.has(t)).reduce((s, [, v]) => s + v, 0)
                return (
                  <tr key={row.date} className="border-b border-slate-800/30 hover:bg-slate-800/20">
                    <td className="py-1.5 px-2 text-slate-400">
                      {new Date(row.date + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', weekday: 'short' })}
                    </td>
                    {towCols.map(t => (
                      <td key={t} className="py-1.5 px-2 text-center text-slate-300">
                        {row.calls_by_type?.[t]
                          ? <span className={clsx('inline-block w-5 h-5 rounded text-[10px] font-bold leading-5 text-center text-white', typeColor(t))}>{row.calls_by_type[t]}</span>
                          : <span className="text-slate-700">—</span>}
                      </td>
                    ))}
                    <td className="py-1.5 px-2 text-right text-slate-300 font-medium">{towTotal}</td>
                    <td className="py-1.5 px-2 text-right text-slate-400">{row.hours > 0 ? `${row.hours}h` : '—'}</td>
                    <td className="py-1.5 px-2 text-right text-emerald-400 font-medium">
                      {row.revenue > 0 ? fmtRevFull(row.revenue) : <span className="text-slate-700">$0</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
            <tfoot>
              <tr className="border-t border-slate-700/50">
                <td className="py-2 px-2 text-slate-400 font-semibold text-[11px]">Total</td>
                {towCols.map(t => (
                  <td key={t} className="py-2 px-2 text-center text-slate-300 font-semibold">
                    {days.reduce((s, r) => s + (r.calls_by_type?.[t] || 0), 0) || '—'}
                  </td>
                ))}
                <td className="py-2 px-2 text-right text-slate-200 font-bold">
                  {days.reduce((s, r) => s + Object.entries(r.calls_by_type || {}).filter(([t]) => !batteryTypes.has(t)).reduce((a, [, v]) => a + v, 0), 0)}
                </td>
                <td className="py-2 px-2 text-right text-slate-300 font-semibold">
                  {days.reduce((s, r) => s + r.hours, 0).toFixed(1)}h
                </td>
                <td className="py-2 px-2 text-right text-emerald-300 font-bold">
                  {fmtRevFull(days.reduce((s, r) => s + r.revenue, 0))}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>

      {/* ── Battery daily breakdown ──────────────────────────────── */}
      {totalBattRevDays > 0 && battCols.length > 0 && (
        <div>
          <div className="text-[10px] font-semibold text-amber-600/80 uppercase tracking-widest mb-2">
            🔋 Daily Breakdown — Battery Revenue
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-amber-900/30">
                  <th className="text-left py-1.5 px-2 text-slate-500 font-medium">Date</th>
                  {battCols.map(t => (
                    <th key={t} className="text-center py-1.5 px-2 text-slate-500 font-medium">{t}</th>
                  ))}
                  <th className="text-right py-1.5 px-2 text-slate-500 font-medium">Battery Rev</th>
                </tr>
              </thead>
              <tbody>
                {days.filter(r => (r.battery_revenue || 0) > 0 || battCols.some(t => r.calls_by_type?.[t])).map(row => (
                  <tr key={row.date} className="border-b border-amber-900/20 hover:bg-amber-900/10">
                    <td className="py-1.5 px-2 text-slate-400">
                      {new Date(row.date + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', weekday: 'short' })}
                    </td>
                    {battCols.map(t => (
                      <td key={t} className="py-1.5 px-2 text-center text-slate-300">
                        {row.calls_by_type?.[t]
                          ? <span className="inline-block w-5 h-5 rounded text-[10px] font-bold leading-5 text-center text-white bg-amber-500">{row.calls_by_type[t]}</span>
                          : <span className="text-slate-700">—</span>}
                      </td>
                    ))}
                    <td className="py-1.5 px-2 text-right text-amber-400 font-medium">
                      {(row.battery_revenue || 0) > 0 ? fmtRevFull(row.battery_revenue) : <span className="text-slate-700">$0</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t border-amber-800/40">
                  <td className="py-2 px-2 text-slate-400 font-semibold">Total</td>
                  {battCols.map(t => (
                    <td key={t} className="py-2 px-2 text-center text-slate-300 font-semibold">
                      {days.reduce((s, r) => s + (r.calls_by_type?.[t] || 0), 0) || '—'}
                    </td>
                  ))}
                  <td className="py-2 px-2 text-right text-amber-300 font-bold">
                    {fmtRevFull(totalBattRevDays)}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
      )}

      {/* ── Call-type summary — Tow/Light ────────────────────────── */}
      {towLightSummary.length > 0 && (
        <div>
          <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-2">By Call Type — Tow / Light</div>
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
                  const total = towLightSummary.reduce((s, t) => s + t.count, 0)
                  return towLightSummary.map(row => (
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

      {/* ── Call-type summary — Battery ──────────────────────────── */}
      {batterySummary.length > 0 && (
        <div>
          <div className="text-[10px] font-semibold text-amber-600/80 uppercase tracking-widest mb-2">🔋 By Call Type — Battery</div>
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b border-amber-900/30">
                <th className="text-left py-1.5 px-2 text-slate-500 font-medium">Type</th>
                <th className="text-right py-1.5 px-2 text-slate-500 font-medium">Calls</th>
                <th className="text-right py-1.5 px-2 text-slate-500 font-medium">Revenue</th>
                <th className="text-right py-1.5 px-2 text-slate-500 font-medium">Avg/Call</th>
              </tr>
            </thead>
            <tbody>
              {batterySummary.map(row => (
                <tr key={row.type} className="border-b border-amber-900/20 hover:bg-amber-900/10">
                  <td className="py-1.5 px-2">
                    <div className="flex items-center gap-1.5">
                      <div className="w-2 h-2 rounded-full shrink-0 bg-amber-500" />
                      <span className="text-slate-300">{row.type}</span>
                    </div>
                  </td>
                  <td className="py-1.5 px-2 text-right text-slate-300 font-semibold">{row.count}</td>
                  <td className="py-1.5 px-2 text-right text-amber-400 font-medium">
                    {row.revenue > 0 ? fmtRevFull(row.revenue) : <span className="text-slate-700">$0</span>}
                  </td>
                  <td className="py-1.5 px-2 text-right text-slate-400">
                    {row.avg_per_call > 0 ? `$${row.avg_per_call.toFixed(0)}` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="text-[9px] text-slate-600 mt-2 px-2">
            Battery revenue tracked separately · excluded from Tow/Light and Rev/Hour calculations
          </div>
        </div>
      )}
    </div>
  )
}
