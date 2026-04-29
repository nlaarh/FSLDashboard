import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

const REASON_COLORS = {
  territory: '#fb923c',
  skill:     '#fbbf24',
  absent:    '#c084fc',
  capacity:  '#f87171',
}

const REASON_LABELS = {
  territory: 'Territory',
  skill:     'Missing Skill',
  absent:    'Absent',
  capacity:  'At Capacity',
}

const CustomTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs shadow-xl">
      <div className="font-medium text-white mb-1">{REASON_LABELS[d.reason] || d.reason}</div>
      <div className="text-slate-300">{d.fires.toLocaleString()} exclusions</div>
      <div className="text-slate-400">{d.drivers_affected} unique drivers affected</div>
    </div>
  )
}

export default function OptExclusionChart({ data }) {
  if (!data?.patterns?.length) return null
  const { patterns, days, territory } = data

  const chartData = patterns.map(p => ({
    ...p,
    name: REASON_LABELS[p.reason] || p.reason,
    fill: REASON_COLORS[p.reason] || '#64748b',
  }))

  return (
    <div className="mt-2 rounded-xl border border-slate-700/50 bg-slate-900/60 overflow-hidden">
      <div className="px-4 py-2.5 bg-slate-800/60 border-b border-slate-700/40">
        <span className="text-sm font-semibold text-white">
          Exclusion Patterns
          {territory ? ` — ${territory}` : ''}
          {days ? ` · last ${days}d` : ''}
        </span>
      </div>
      <div className="p-4">
        <ResponsiveContainer width="100%" height={130}>
          <BarChart data={chartData} layout="vertical" barSize={16} margin={{ top: 0, right: 24, left: 0, bottom: 0 }}>
            <XAxis
              type="number"
              tick={{ fontSize: 10, fill: '#64748b' }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              type="category"
              dataKey="name"
              tick={{ fontSize: 11, fill: '#94a3b8' }}
              axisLine={false}
              tickLine={false}
              width={96}
            />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
            <Bar dataKey="fires" radius={[0, 4, 4, 0]}>
              {chartData.map((d, i) => <Cell key={i} fill={d.fill} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>

        <div className="mt-3 pt-3 border-t border-slate-800/60 flex flex-wrap gap-4">
          {chartData.map(d => (
            <div key={d.reason} className="flex items-center gap-2 text-[11px]">
              <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: d.fill }} />
              <span className="text-slate-400">{d.name}</span>
              <span className="text-white font-mono font-medium">{d.fires.toLocaleString()}</span>
              <span className="text-slate-600">({d.drivers_affected} drivers)</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
