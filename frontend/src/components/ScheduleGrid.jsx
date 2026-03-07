import { clsx } from 'clsx'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const PERIODS = [
  { name: 'Morning (6am-12pm)', blocks: ['6-8am', '8-10am', '10-12pm'] },
  { name: 'Peak (12pm-6pm)', blocks: ['12-2pm', '2-4pm', '4-6pm'] },
  { name: 'Evening (6pm-12am)', blocks: ['6-8pm', '8-10pm', '10-12am'] },
  { name: 'Overnight (12am-6am)', blocks: ['12-2am', '2-4am', '4-6am'] },
]

export default function ScheduleGrid({ data, onGarageName }) {
  const { schedule, daily_totals, summary } = data

  const battLightPct = summary.type_split?.batt_light_pct ?? 0
  const towPct       = summary.type_split?.tow_pct ?? 0

  return (
    <div className="space-y-6">

      {/* ── Summary cards ──────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <MetricCard label="Weekly Avg SAs"  value={summary.weekly_average} />
        <MetricCard label="Daily Avg"       value={summary.daily_average} />
        <MetricCard label="Weeks Analyzed"  value={summary.weeks_analyzed} />
        <MetricCard
          label="Type Split"
          value={`${towPct}% / ${battLightPct}%`}
          sub="Tow / Battery+Light"
        />
        <MetricCard
          label="Data Range"
          value={summary.total_sas_queried?.toLocaleString()}
          sub={summary.data_start && summary.data_end
            ? `${summary.data_start} → ${summary.data_end}`
            : `Last ${summary.weeks_analyzed} weeks`}
        />
      </div>

      {/* ── Legend ────────────────────────────────────────────────── */}
      <div className="flex flex-wrap gap-5 text-xs text-slate-400">
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded bg-red-500/80" />
          Tow (115 min cycle)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded bg-blue-500/80" />
          Battery / Light Service (33–38 min)
        </span>
        <span className="text-slate-600">|</span>
        <span className="text-slate-500">
          Cell: calls → drivers needed &nbsp; <strong className="text-slate-400">Tow | Batt/Light = Total</strong>
        </span>
      </div>

      {/* ── Period tables ─────────────────────────────────────────── */}
      {PERIODS.map(period => (
        <div key={period.name} className="glass rounded-xl overflow-hidden">
          <div className="px-4 py-2.5 bg-slate-800/50 border-b border-slate-700/50">
            <h3 className={clsx(
              'font-semibold text-sm',
              period.name.includes('Peak') ? 'text-amber-400' : 'text-slate-300'
            )}>
              {period.name}
              {period.name.includes('Peak') && (
                <span className="ml-2 text-xs bg-amber-500/20 text-amber-300 px-2 py-0.5 rounded-full">
                  Highest Volume
                </span>
              )}
            </h3>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-800/30">
                  <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-16">Day</th>
                  {period.blocks.map(b => (
                    <th key={b} className="px-3 py-2 text-center text-xs font-medium text-slate-400">{b}</th>
                  ))}
                  <th className="px-3 py-2 text-center text-xs font-medium text-slate-400 w-20">Period SAs</th>
                </tr>
              </thead>
              <tbody>
                {DAYS.map((day, di) => {
                  let periodSAs = 0
                  return (
                    <tr key={day} className={clsx(
                      'border-t border-slate-800/50',
                      di % 2 === 0 ? 'bg-slate-900/20' : ''
                    )}>
                      <td className="px-3 py-2 font-semibold text-slate-300">{day}</td>
                      {period.blocks.map(block => {
                        const cell = schedule?.[day]?.[block]
                        if (!cell) return <td key={block} className="px-3 py-2 text-center text-slate-600">–</td>
                        const total = cell.total_drivers
                        periodSAs += (cell.tow_calls ?? 0) + (cell.batt_light_calls ?? 0)
                        return (
                          <td key={block} className={clsx(
                            'px-3 py-1.5 text-center',
                            cell.is_peak && 'bg-amber-500/5'
                          )}>
                            {/* Call counts */}
                            <div className="text-[11px] text-slate-500 leading-tight">
                              <span className="text-red-400/80">T:{cell.tow_calls}</span>
                              {' '}
                              <span className="text-blue-400/80">BL:{cell.batt_light_calls}</span>
                            </div>
                            {/* Drivers needed */}
                            <div className="font-bold text-slate-200 leading-tight mt-0.5">
                              <span className="text-red-400">{cell.tow_drivers}</span>
                              <span className="text-slate-600 mx-0.5">|</span>
                              <span className="text-blue-400">{cell.batt_light_drivers}</span>
                              <span className="text-slate-500 mx-1">=</span>
                              <span className={clsx(
                                'text-lg',
                                total >= 30 ? 'text-amber-400' :
                                total >= 20 ? 'text-slate-100' : 'text-slate-300'
                              )}>
                                {total}
                              </span>
                            </div>
                          </td>
                        )
                      })}
                      <td className="px-3 py-2 text-center font-bold text-slate-300">{periodSAs}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      ))}

      {/* ── Daily peak totals ──────────────────────────────────────── */}
      <div className="glass rounded-xl overflow-hidden">
        <div className="px-4 py-2.5 bg-slate-800/50 border-b border-slate-700/50">
          <h3 className="font-semibold text-sm text-slate-300">Daily Peak Drivers Needed</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-800/30">
                <th className="px-3 py-2 text-left   text-xs font-medium text-slate-400">Day</th>
                <th className="px-3 py-2 text-center text-xs font-medium text-slate-400">Daily SAs</th>
                <th className="px-3 py-2 text-center text-xs font-medium text-red-400">Peak Tow Drivers</th>
                <th className="px-3 py-2 text-center text-xs font-medium text-blue-400">Peak Batt/Light Drivers</th>
                <th className="px-3 py-2 text-center text-xs font-medium text-white">Peak Total</th>
                <th className="px-3 py-2 text-center text-xs font-medium text-slate-400">Busiest Block</th>
              </tr>
            </thead>
            <tbody>
              {DAYS.map((day, i) => {
                const dt = daily_totals?.[day]
                if (!dt) return null
                return (
                  <tr key={day} className={clsx(
                    'border-t border-slate-800/50',
                    i % 2 === 0 ? 'bg-slate-900/20' : ''
                  )}>
                    <td className="px-3 py-2.5 font-semibold text-slate-300">{day}</td>
                    <td className="px-3 py-2.5 text-center text-slate-400">{dt.total_sas}</td>
                    <td className="px-3 py-2.5 text-center font-bold text-red-400 text-lg">
                      {dt.peak_tow_drivers}
                    </td>
                    <td className="px-3 py-2.5 text-center font-bold text-blue-400 text-lg">
                      {dt.peak_batt_light_drivers}
                    </td>
                    <td className="px-3 py-2.5 text-center font-black text-white text-2xl">
                      {dt.peak_total_drivers}
                    </td>
                    <td className="px-3 py-2.5 text-center text-slate-500 text-xs">{dt.peak_block}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function MetricCard({ label, value, sub }) {
  return (
    <div className="glass rounded-xl p-4">
      <div className="text-xs text-slate-400 uppercase tracking-wide">{label}</div>
      <div className="text-2xl font-bold text-white mt-1">{value}</div>
      {sub && <div className="text-xs text-slate-500 mt-0.5">{sub}</div>}
    </div>
  )
}
