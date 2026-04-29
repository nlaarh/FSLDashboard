import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'

function Delta({ before, after, positiveIsGood = true, suffix = '' }) {
  if (before == null || after == null) return null
  const diff = after - before
  if (diff === 0) return <span className="flex items-center gap-0.5 text-[11px] text-slate-500"><Minus size={10} />no change{suffix}</span>
  const improved = positiveIsGood ? diff > 0 : diff < 0
  const pct = before !== 0 ? Math.abs((diff / before) * 100).toFixed(0) : null
  const Icon = improved ? TrendingUp : TrendingDown
  const color = improved ? 'text-emerald-400' : 'text-red-400'
  return (
    <span className={`flex items-center gap-0.5 text-[11px] ${color}`}>
      <Icon size={10} />
      {diff > 0 ? '+' : ''}{diff}{pct ? ` (${pct}%)` : ''}{suffix}
    </span>
  )
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs shadow-xl">
      <div className="font-medium text-slate-200 mb-1">{label}</div>
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-sm shrink-0" style={{ background: p.fill }} />
          <span className="text-slate-400">{p.name}:</span>
          <span className="text-white font-mono">{p.value}</span>
        </div>
      ))}
    </div>
  )
}

export default function OptKpiBar({ data }) {
  if (!data) return null
  const { run_name, before = {}, after = {} } = data

  const scheduledData = [
    { name: 'Before', value: before.scheduled ?? 0, fill: '#475569' },
    { name: 'After',  value: after.scheduled ?? 0,  fill: '#34d399' },
  ]
  const unscheduledData = [
    { name: 'Before', value: before.unscheduled ?? 0, fill: '#475569' },
    { name: 'After',  value: after.unscheduled ?? 0,  fill: '#f87171' },
  ]
  const travelBefore = before.travel_s != null ? Math.round(before.travel_s / 60) : null
  const travelAfter  = after.travel_s  != null ? Math.round(after.travel_s  / 60) : null
  const travelData = [
    { name: 'Before', value: travelBefore ?? 0, fill: '#475569' },
    { name: 'After',  value: travelAfter  ?? 0, fill: '#60a5fa' },
  ]

  return (
    <div className="mt-2 rounded-xl border border-slate-700/50 bg-slate-900/60 overflow-hidden">
      <div className="px-4 py-2.5 bg-slate-800/60 border-b border-slate-700/40 flex items-center flex-wrap gap-3">
        <span className="text-sm font-semibold text-white">{run_name || 'Run KPIs'}</span>
        <div className="ml-auto flex items-center gap-4">
          <Delta before={before.scheduled} after={after.scheduled} positiveIsGood={true} suffix=" sched" />
          <Delta before={before.unscheduled} after={after.unscheduled} positiveIsGood={false} suffix=" unsched" />
        </div>
      </div>
      <div className="p-4 grid grid-cols-3 gap-4">
        {[
          { label: 'Scheduled', data: scheduledData, key: 'value' },
          { label: 'Unscheduled', data: unscheduledData, key: 'value' },
          { label: 'Avg Travel (min)', data: travelData, key: 'value' },
        ].map(({ label, data: d }) => (
          <div key={label}>
            <div className="text-[10px] text-slate-500 mb-2 font-semibold uppercase tracking-wider">{label}</div>
            <ResponsiveContainer width="100%" height={90}>
              <BarChart data={d} barSize={26} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#64748b' }} axisLine={false} tickLine={false} />
                <YAxis hide />
                <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
                <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                  {d.map((row, i) => <Cell key={i} fill={row.fill} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        ))}
      </div>
    </div>
  )
}
