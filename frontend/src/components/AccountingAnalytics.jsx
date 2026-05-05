import { useState, useEffect, useMemo } from 'react'
import { clsx } from 'clsx'
import { RefreshCw, AlertTriangle, TrendingDown, Zap, Sparkles } from 'lucide-react'
import AccountingAnalyticsAiCard from './AccountingAnalyticsAiCard'
import AccountingAgingHeatmap from './AccountingAgingHeatmap'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, PieChart, Pie, Legend,
} from 'recharts'
import { fetchAccountingAnalytics, fetchAccountingAiInsights } from '../api'

// ── Constants ────────────────────────────────────────────────────────────────

const PROD_COLOR = {
  ER: '#3b82f6', TW: '#a855f7', TT: '#7c3aed', TU: '#8b5cf6', TM: '#6d28d9',
  EM: '#9333ea', E1: '#f97316', Z8: '#ea580c', MH: '#ef4444', TL: '#10b981',
  MI: '#64748b', BA: '#475569', BC: '#334155', HO: '#f59e0b', Z5: '#06b6d4',
}

const HEATMAP_COLS = ['ER','TW','BA','TU','TT','E1','TL','MH','BC']

const PROD_LABEL = {
  ER: 'Enroute Miles', TW: 'Tow Miles', BA: 'Base Rate', TU: 'Tow Plus 30-100mi',
  TT: 'Tow Plus 5-30mi', E1: 'Extrication', TL: 'Tolls/Parking', MH: 'Medium/Heavy', BC: 'Basic Cost',
}

function riskStyle(pct) {
  if (pct < 30) return { dot: 'bg-red-500', text: 'text-red-400', badge: 'bg-red-500/15 border-red-500/30' }
  if (pct < 60) return { dot: 'bg-amber-500', text: 'text-amber-400', badge: 'bg-amber-500/15 border-amber-500/30' }
  return { dot: 'bg-emerald-500', text: 'text-emerald-400', badge: 'bg-emerald-500/15 border-emerald-500/30' }
}

// ── Sub-components ────────────────────────────────────────────────────────────

function StackedBar({ allCodes, total, onDrillDown }) {
  if (!total) return null
  return (
    <div className="flex h-2.5 rounded overflow-hidden w-28 gap-px">
      {(allCodes || []).slice(0, 5).map(c => {
        const pct = Math.round(c.count / total * 100)
        if (!pct) return null
        return (
          <div key={c.code}
            title={`${c.code} — ${PROD_LABEL[c.code] || c.code}: ${c.count} WOAs (${pct}%)\nClick to filter list`}
            onClick={() => onDrillDown?.(c.code)}
            className={clsx('h-full transition-opacity hover:opacity-70', onDrillDown && 'cursor-pointer')}
            style={{ width: `${pct}%`, backgroundColor: PROD_COLOR[c.code] || '#475569', minWidth: 3 }} />
        )
      })}
    </div>
  )
}

function Alerts({ data, facilities }) {
  if (!facilities.length) return null
  const topReview   = facilities[0]
  const worstRate   = [...facilities].filter(f => f.count >= 20).sort((a, b) => a.approve_pct - b.approve_pct)[0]
  const topProduct  = data.by_product?.[0]
  const totalWoas   = data.total_woas || 1
  const topSubmitter = data.by_creator?.[0]

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
      <div className="rounded-xl border border-red-500/30 bg-red-950/15 p-3 flex gap-2.5">
        <AlertTriangle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
        <div>
          <div className="text-[9px] text-red-400 uppercase tracking-wider font-bold mb-0.5">Largest Review Backlog</div>
          <div className="text-xs font-semibold text-white truncate max-w-[200px]" title={topReview.facility}>{topReview.facility}</div>
          <div className="text-[10px] text-red-300 mt-0.5">
            {topReview.review} need manual review · {topReview.approve_pct}% auto-approve · #{1} priority
          </div>
        </div>
      </div>

      {worstRate && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-950/15 p-3 flex gap-2.5">
          <TrendingDown className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
          <div>
            <div className="text-[9px] text-amber-400 uppercase tracking-wider font-bold mb-0.5">Worst Approval Rate</div>
            <div className="text-xs font-semibold text-white truncate max-w-[200px]" title={worstRate.facility}>{worstRate.facility}</div>
            <div className="text-[10px] text-amber-300 mt-0.5">
              Only {worstRate.approve_pct}% pass · {worstRate.review} of {worstRate.count} WOAs flagged — call them
            </div>
          </div>
        </div>
      )}

      <div className="rounded-xl border border-blue-500/30 bg-blue-950/15 p-3 flex gap-2.5">
        <Zap className="w-4 h-4 text-blue-400 shrink-0 mt-0.5" />
        <div>
          <div className="text-[9px] text-blue-400 uppercase tracking-wider font-bold mb-0.5">What Drives Disputes</div>
          <div className="text-xs font-semibold text-white">
            {topProduct?.code} — {Math.round((topProduct?.count || 0) / totalWoas * 100)}% of all WOAs
          </div>
          <div className="text-[10px] text-blue-300 mt-0.5">
            {topSubmitter?.name} alone filed {topSubmitter?.count} WOAs ({Math.round((topSubmitter?.count||0)/totalWoas*100)}% of backlog)
          </div>
        </div>
      </div>
    </div>
  )
}

function Heatmap({ facilities }) {
  const [open, setOpen] = useState(false)
  const colMax = useMemo(() => {
    const m = {}
    for (const col of HEATMAP_COLS)
      m[col] = Math.max(1, ...facilities.map(f => f.all_codes?.find(c => c.code === col)?.count || 0))
    return m
  }, [facilities])

  return (
    <div className="glass rounded-xl border border-slate-700/30 overflow-hidden">
      <button className="w-full px-4 py-3 flex items-center justify-between border-b border-slate-800/60 hover:bg-slate-800/30 transition-colors"
        onClick={() => setOpen(o => !o)}>
        <span className="text-xs font-semibold text-slate-300">Product × Garage Heatmap</span>
        <span className="text-[10px] text-slate-500">
          {open ? '▲ collapse' : '▼ expand — what each garage is claiming'}
        </span>
      </button>
      {open && (
        <div className="overflow-x-auto">
          <table className="w-full text-[10px]">
            <thead>
              <tr className="border-b border-slate-800">
                <th className="px-3 py-2 text-left text-[9px] text-slate-500 w-44">Garage</th>
                {HEATMAP_COLS.map(col => (
                  <th key={col} className="px-2 py-2 text-center text-[9px] font-bold"
                    style={{ color: PROD_COLOR[col] || '#64748b' }} title={PROD_LABEL[col]}>
                    {col}
                  </th>
                ))}
                <th className="px-3 py-2 text-right text-[9px] text-slate-500">Total</th>
                <th className="px-3 py-2 text-right text-[9px] text-slate-500">Approve%</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/40">
              {facilities.slice(0, 20).map(fac => {
                const rs = riskStyle(fac.approve_pct)
                return (
                  <tr key={fac.facility} className="hover:bg-slate-800/30">
                    <td className="px-3 py-2 text-slate-300 font-medium truncate max-w-[160px]" title={fac.facility}>
                      {fac.facility}
                    </td>
                    {HEATMAP_COLS.map(col => {
                      const count = fac.all_codes?.find(c => c.code === col)?.count || 0
                      const intensity = count / colMax[col]
                      const opHex = count > 0 ? Math.round(40 + intensity * 180).toString(16).padStart(2, '0') : ''
                      return (
                        <td key={col} className="px-2 py-2 text-center" title={count > 0 ? `${count} ${col}` : ''}>
                          {count > 0 ? (
                            <span className="inline-block px-1 rounded text-[9px] font-bold text-white"
                              style={{ backgroundColor: (PROD_COLOR[col] || '#475569') + opHex }}>
                              {count}
                            </span>
                          ) : <span className="text-slate-800">·</span>}
                        </td>
                      )
                    })}
                    <td className="px-3 py-2 text-right font-mono font-bold text-slate-300">{fac.count}</td>
                    <td className={clsx('px-3 py-2 text-right font-bold text-[11px]', rs.text)}>{fac.approve_pct}%</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Charts ───────────────────────────────────────────────────────────────────

const CHART_TOOLTIP_STYLE = {
  contentStyle: { background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 11 },
  labelStyle: { color: '#e2e8f0', fontWeight: 600 },
  cursor: { fill: 'rgba(255,255,255,0.04)' },
}

function GarageChart({ facilities }) {
  const data = useMemo(() =>
    facilities.slice(0, 15).map(f => ({
      name: f.facility.includes(' - ') ? f.facility.split(' - ').slice(1).join(' - ') : f.facility,
      full: f.facility,
      approve: f.approve,
      review: f.review,
    }))
  , [facilities])

  const CustomTick = ({ x, y, payload }) => (
    <text x={x} y={y} dy={4} textAnchor="end" fill="#94a3b8" fontSize={9}>
      {payload.value.length > 22 ? payload.value.slice(0, 22) + '…' : payload.value}
    </text>
  )

  return (
    <div className="glass rounded-xl border border-slate-700/30 p-4">
      <div className="text-xs font-semibold text-slate-300 mb-1">Review Backlog by Garage</div>
      <div className="text-[10px] text-slate-500 mb-3">green = auto-approved · amber = needs manual review · sorted by backlog</div>
      <ResponsiveContainer width="100%" height={420}>
        <BarChart data={data} layout="vertical" margin={{ top: 0, right: 48, left: 8, bottom: 0 }} barSize={10}>
          <XAxis type="number" tick={{ fill: '#64748b', fontSize: 9 }} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="name" tick={<CustomTick />} width={160} interval={0} axisLine={false} tickLine={false} />
          <Tooltip {...CHART_TOOLTIP_STYLE}
            formatter={(val, name) => [val, name === 'approve' ? '✓ Auto-Approved' : '⚠ Needs Review']} />
          <Bar dataKey="approve" stackId="a" fill="#10b981" name="approve" />
          <Bar dataKey="review" stackId="a" fill="#f59e0b" name="review" radius={[0, 3, 3, 0]}
            label={{ position: 'right', fill: '#64748b', fontSize: 9,
              formatter: (val, entry) => entry ? (entry.approve + val) : val }} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function ProductDonut({ byProduct, totalWoas }) {
  const data = useMemo(() =>
    (byProduct || []).slice(0, 8).map(p => ({
      name: p.code,
      value: p.count,
      pct: Math.round(p.count / (totalWoas || 1) * 100),
      color: PROD_COLOR[p.code] || '#475569',
    }))
  , [byProduct, totalWoas])

  const renderLabel = ({ cx, cy, midAngle, innerRadius, outerRadius, pct, name }) => {
    if (pct < 4) return null
    const RADIAN = Math.PI / 180
    const r = innerRadius + (outerRadius - innerRadius) * 0.5
    const x = cx + r * Math.cos(-midAngle * RADIAN)
    const y = cy + r * Math.sin(-midAngle * RADIAN)
    return (
      <text x={x} y={y} fill="white" textAnchor="middle" dominantBaseline="central" fontSize={9} fontWeight={700}>
        {name}
      </text>
    )
  }

  return (
    <div className="glass rounded-xl border border-slate-700/30 p-4">
      <div className="text-xs font-semibold text-slate-300 mb-1">Dispute Type Distribution</div>
      <div className="text-[10px] text-slate-500 mb-2">share of all WOAs by product code</div>
      <ResponsiveContainer width="100%" height={200}>
        <PieChart>
          <Pie data={data} cx="50%" cy="50%" innerRadius={48} outerRadius={80}
            dataKey="value" labelLine={false} label={renderLabel}>
            {data.map(d => <Cell key={d.name} fill={d.color} />)}
          </Pie>
          <Tooltip {...CHART_TOOLTIP_STYLE}
            formatter={(val, name, props) => [`${val} WOAs (${props.payload.pct}%)`, name]} />
          <Legend iconSize={8} iconType="circle"
            formatter={(val) => <span style={{ color: '#94a3b8', fontSize: 9 }}>{val}</span>} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}

function SubmitterChart({ byCreator }) {
  const data = useMemo(() =>
    (byCreator || []).slice(0, 15).map(c => ({
      name: c.name,
      approve: c.approve || 0,
      review: c.review || 0,
      total: c.count,
    }))
  , [byCreator])

  const CustomTick = ({ x, y, payload }) => (
    <text x={x} y={y} dy={4} textAnchor="end" fill="#94a3b8" fontSize={9}>
      {payload.value.length > 20 ? payload.value.slice(0, 20) + '…' : payload.value}
    </text>
  )

  return (
    <div className="glass rounded-xl border border-slate-700/30 p-4">
      <div className="text-xs font-semibold text-slate-300 mb-1">Top WOA Submitters</div>
      <div className="text-[10px] text-slate-500 mb-3">green = auto-approved · amber = needs review</div>
      <ResponsiveContainer width="100%" height={380}>
        <BarChart data={data} layout="vertical" margin={{ top: 0, right: 48, left: 8, bottom: 0 }} barSize={10}>
          <XAxis type="number" tick={{ fill: '#64748b', fontSize: 9 }} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="name" tick={<CustomTick />} width={148} interval={0} axisLine={false} tickLine={false} />
          <Tooltip {...CHART_TOOLTIP_STYLE}
            formatter={(val, name) => [val, name === 'approve' ? '✓ Auto-Approved' : '⚠ Needs Review']} />
          <Bar dataKey="approve" stackId="a" fill="#10b981" name="approve" />
          <Bar dataKey="review" stackId="a" fill="#f59e0b" name="review" radius={[0, 3, 3, 0]}
            label={{ position: 'right', fill: '#64748b', fontSize: 9,
              formatter: (val, entry) => entry ? (entry.approve + val) : val }} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function ProductChart({ byProduct, onDrillDown }) {
  const data = useMemo(() =>
    (byProduct || []).slice(0, 12).map(p => ({
      code: p.code,
      approve: p.approve || 0,
      review: p.review || 0,
      total: p.count,
      approvePct: p.count ? Math.round((p.approve || 0) / p.count * 100) : 0,
    }))
  , [byProduct])

  const handleClick = (barData) => {
    if (barData?.activePayload?.[0]?.payload?.code) {
      onDrillDown?.(barData.activePayload[0].payload.code)
    }
  }

  return (
    <div className="glass rounded-xl border border-slate-700/30 p-4">
      <div className="text-xs font-semibold text-slate-300 mb-1">WOAs by Product Line</div>
      <div className="text-[10px] text-slate-500 mb-2">click any bar to filter the WOA list · green = auto-approved · amber = needs review</div>
      {/* Color legend */}
      <div className="flex flex-wrap gap-x-3 gap-y-1 mb-3">
        {data.map(d => (
          <button key={d.code} onClick={() => onDrillDown?.(d.code)}
            className="flex items-center gap-1 text-[9px] hover:opacity-70 transition-opacity cursor-pointer">
            <span className="w-2 h-2 rounded-sm shrink-0" style={{ backgroundColor: PROD_COLOR[d.code] || '#475569' }} />
            <span className="font-bold" style={{ color: PROD_COLOR[d.code] || '#64748b' }}>{d.code}</span>
            <span className="text-slate-600">{PROD_LABEL[d.code] || ''}</span>
          </button>
        ))}
      </div>
      <ResponsiveContainer width="100%" height={380}>
        <BarChart data={data} layout="vertical" margin={{ top: 0, right: 48, left: 8, bottom: 0 }} barSize={12}
          onClick={handleClick} style={{ cursor: onDrillDown ? 'pointer' : 'default' }}>
          <XAxis type="number" tick={{ fill: '#64748b', fontSize: 9 }} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="code" width={36} interval={0} axisLine={false} tickLine={false}
            tick={({ x, y, payload }) => (
              <text x={x} y={y} dy={4} textAnchor="end" fill={PROD_COLOR[payload.value] || '#64748b'} fontSize={10} fontWeight={700}>
                {payload.value}
              </text>
            )} />
          <Tooltip {...CHART_TOOLTIP_STYLE}
            labelFormatter={(label) => `${label} — ${PROD_LABEL[label] || label}`}
            formatter={(val, name, props) => {
              const row = props.payload
              const pct = row.total ? Math.round(val / row.total * 100) : 0
              return [`${val} (${pct}%)`, name === 'approve' ? '✓ Auto-Approved' : '⚠ Needs Review']
            }} />
          <Bar dataKey="approve" stackId="a" fill="#10b981" name="approve" label={false} />
          <Bar dataKey="review" stackId="a" fill="#f59e0b" name="review" radius={[0, 3, 3, 0]}
            label={{ position: 'right', fill: '#64748b', fontSize: 9,
              formatter: (val, entry) => entry ? (entry.approve + val) : val }} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function BreakdownChart({ title, subtitle, data }) {
  const chartData = useMemo(() =>
    (data || []).map(d => ({
      name: d.type,
      approve: d.approve || 0,
      review: d.review || 0,
      total: d.count,
    }))
  , [data])

  const CustomTick = ({ x, y, payload }) => (
    <text x={x} y={y} dy={4} textAnchor="end" fill="#94a3b8" fontSize={9}>
      {payload.value.length > 22 ? payload.value.slice(0, 22) + '…' : payload.value}
    </text>
  )

  if (!chartData.length) return null
  const height = Math.max(160, chartData.length * 28 + 40)

  return (
    <div className="glass rounded-xl border border-slate-700/30 p-4">
      <div className="text-xs font-semibold text-slate-300 mb-1">{title}</div>
      <div className="text-[10px] text-slate-500 mb-3">{subtitle}</div>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={chartData} layout="vertical" margin={{ top: 0, right: 48, left: 8, bottom: 0 }} barSize={10}>
          <XAxis type="number" tick={{ fill: '#64748b', fontSize: 9 }} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="name" tick={<CustomTick />} width={140} interval={0} axisLine={false} tickLine={false} />
          <Tooltip {...CHART_TOOLTIP_STYLE}
            formatter={(val, name) => [val, name === 'approve' ? '✓ Auto-Approved' : '⚠ Needs Review']} />
          <Bar dataKey="approve" stackId="a" fill="#10b981" name="approve" />
          <Bar dataKey="review" stackId="a" fill="#f59e0b" name="review" radius={[0, 3, 3, 0]}
            label={{ position: 'right', fill: '#64748b', fontSize: 9,
              formatter: (val, entry) => entry ? (entry.approve + val) : val }} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function AccountingAnalytics({ status, onDrillDown }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [aiInsight, setAiInsight] = useState(null)
  const [aiLoading, setAiLoading] = useState(false)
  const [aiError, setAiError] = useState(null)

  const [aiHidden, setAiHidden] = useState(false)

  const load = () => {
    setLoading(true); setError(null)
    fetchAccountingAnalytics(status)
      .then(setData)
      .catch(e => setError(e.message || 'Failed to load'))
      .finally(() => setLoading(false))
  }
  useEffect(() => { load(); setAiInsight(null); setAiError(null); setAiHidden(false) }, [status])

  // Auto-load AI insights once analytics data is ready
  useEffect(() => {
    if (!data || aiInsight) return
    setAiLoading(true); setAiError(null)
    fetchAccountingAiInsights(status)
      .then(setAiInsight)
      .catch(e => setAiError(e.message || 'AI analysis failed — check AI configuration in Admin.'))
      .finally(() => setAiLoading(false))
  }, [data])

  const facilities = useMemo(() => (data?.by_facility || []).slice(0, 25), [data])
  const maxReview  = facilities[0]?.risk_score || 1
  const maxCreator = data?.by_creator?.[0]?.count || 1
  const approveRate = data?.total_woas ? Math.round(data.approve_count / data.total_woas * 100) : 0

  if (loading) return (
    <div className="flex items-center justify-center h-48 text-slate-500 text-sm">
      <RefreshCw className="w-4 h-4 animate-spin mr-2" />Loading analytics…
    </div>
  )
  if (error) return <div className="h-48 flex items-center justify-center text-red-400 text-sm">{error}</div>
  if (!data) return null

  return (
    <div className="space-y-4">
      {/* Insight Alerts */}
      <Alerts data={data} facilities={facilities} />

      {/* KPI Strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: 'Open WOAs',      value: (data.total_woas || 0).toLocaleString(),  color: 'text-white' },
          { label: 'Garages',        value: data.total_facilities,                     color: 'text-white' },
          { label: 'Auto-Approve',   value: `${approveRate}%`, color: approveRate >= 50 ? 'text-emerald-400' : 'text-amber-400' },
          { label: 'Manual Review',  value: (data.review_count || 0).toLocaleString(), color: 'text-amber-400' },
        ].map(({ label, value, color }) => (
          <div key={label} className="glass rounded-xl border border-slate-700/30 p-3">
            <div className="text-[10px] text-slate-500 uppercase tracking-wider">{label}</div>
            <div className={clsx('text-xl font-bold', color)}>{value}</div>
          </div>
        ))}
      </div>

      {/* AI Insights — auto-loaded, always visible unless hidden */}
      {(aiLoading || aiInsight || aiError) && !aiHidden && (
        <div className="glass rounded-xl border border-blue-800/30 overflow-hidden">
          <div className="px-4 py-2.5 border-b border-blue-900/30 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Sparkles className={clsx('w-3.5 h-3.5 text-blue-400', aiLoading && 'animate-pulse')} />
              <span className="text-[10px] font-bold text-blue-400 uppercase tracking-wider">
                {aiLoading ? 'AI Analysis' : 'AI Analysis'}
              </span>
              {aiLoading && <span className="text-[9px] text-slate-500">analyzing backlog…</span>}
            </div>
            <button onClick={() => setAiHidden(true)} className="text-[9px] text-slate-600 hover:text-slate-400 transition-colors">hide</button>
          </div>
          {aiLoading && (
            <div className="px-4 py-4 space-y-2">
              <div className="h-3 bg-slate-700/30 rounded animate-pulse w-2/3" />
              <div className="h-2 bg-slate-700/20 rounded animate-pulse w-full" />
              <div className="h-2 bg-slate-700/20 rounded animate-pulse w-5/6" />
            </div>
          )}
          {aiError && (
            <div className="px-4 py-3 flex items-start gap-2 text-[11px] text-red-300">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5 text-red-400" />
              <span>{aiError} — Go to <strong>Admin → AI Assistant</strong> to configure.</span>
            </div>
          )}
          {aiInsight && !aiError && !aiLoading && (
            <AccountingAnalyticsAiCard insight={aiInsight} />
          )}
        </div>
      )}
      {aiHidden && (
        <button onClick={() => setAiHidden(false)}
          className="flex items-center gap-1.5 text-[10px] text-slate-600 hover:text-blue-400 transition-colors">
          <Sparkles className="w-3 h-3" />Show AI Analysis
        </button>
      )}

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <GarageChart facilities={facilities} />
        </div>
        <div>
          <ProductDonut byProduct={data.by_product} totalWoas={data.total_woas} />
        </div>
      </div>

      {/* Submitter + Product charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <SubmitterChart byCreator={data.by_creator} />
        <ProductChart byProduct={data.by_product} onDrillDown={onDrillDown} />
      </div>

      {/* Program + Service Type breakdown */}
      {(data.by_program?.length > 0 || data.by_service_type?.length > 0) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <BreakdownChart
            title="WOAs by Program"
            subtitle="Standard, RAP, Reciprocal, Thruway, etc. (WorkOrder.Type__c) — green = auto-approved · amber = needs review"
            data={data.by_program}
          />
          <BreakdownChart
            title="WOAs by Service Type"
            subtitle="Tow, Battery, Lockout, etc. — which call types drive the most disputes"
            data={data.by_service_type}
          />
        </div>
      )}

      {/* Leaderboard + Sidebar */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {/* ── Garage Leaderboard ── */}
        <div className="lg:col-span-2 glass rounded-xl border border-slate-700/30 overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-800/60">
            <span className="text-xs font-semibold text-slate-300">Garage Leaderboard</span>
            <span className="text-[10px] text-slate-500 ml-2">sorted by review backlog — who needs attention first</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-slate-800">
                  <th className="px-2 py-2 text-left text-[9px] text-slate-500 w-5">#</th>
                  <th className="px-3 py-2 text-left text-[9px] text-slate-500">Garage</th>
                  <th className="px-3 py-2 text-left text-[9px] text-slate-500 w-40">Review Backlog</th>
                  <th className="px-3 py-2 text-center text-[9px] text-slate-500 w-16">Approve%</th>
                  <th className="px-3 py-2 text-left text-[9px] text-slate-500 w-32">Product Mix</th>
                  <th className="px-3 py-2 text-left text-[9px] text-slate-500">Submitter</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/40">
                {facilities.map((fac, i) => {
                  const rs        = riskStyle(fac.approve_pct)
                  const topCode   = fac.all_codes?.[0]
                  const topPct    = topCode ? Math.round(topCode.count / fac.count * 100) : 0
                  const topCreator = fac.top_creators?.[0]
                  const barPct    = Math.round(fac.risk_score / maxReview * 100)
                  const barColor  = barPct > 50 ? 'bg-red-500' : barPct > 25 ? 'bg-amber-500' : 'bg-slate-400'

                  return (
                    <tr key={fac.facility} className="hover:bg-slate-800/30 transition-colors">
                      <td className="px-2 py-2.5 text-slate-600 text-[9px]">{i + 1}</td>
                      <td className="px-3 py-2.5">
                        <div className="flex items-center gap-1.5">
                          <div className={clsx('w-1.5 h-1.5 rounded-full shrink-0', rs.dot)} />
                          <span className="text-slate-200 font-medium truncate max-w-[150px]" title={fac.facility}>
                            {fac.facility}
                          </span>
                        </div>
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="flex items-center gap-2">
                          <div className="w-20 h-1.5 rounded bg-slate-700 overflow-hidden">
                            <div className={clsx('h-full rounded', barColor)} style={{ width: `${barPct}%` }} />
                          </div>
                          <span className="font-mono font-bold text-slate-300 text-[10px]">{fac.risk_score}</span>
                          <span className="text-[9px] text-slate-600">/ {fac.count}</span>
                        </div>
                      </td>
                      <td className="px-3 py-2.5 text-center">
                        <span className={clsx('px-1.5 py-0.5 rounded text-[9px] font-bold border', rs.badge, rs.text)}>
                          {fac.approve_pct}%
                        </span>
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="flex flex-col gap-1">
                          <StackedBar allCodes={fac.all_codes} total={fac.count} />
                          <div className="flex flex-wrap gap-x-2 gap-y-0.5">
                            {(fac.all_codes || []).slice(0, 3).map(c => {
                              const pct = Math.round(c.count / fac.count * 100)
                              if (!pct) return null
                              return (
                                <span key={c.code} className="flex items-center gap-0.5">
                                  <span className="shrink-0 rounded-sm" style={{ width: 6, height: 6, backgroundColor: PROD_COLOR[c.code] || '#475569', display: 'inline-block' }} />
                                  <span className="text-[9px] font-bold" style={{ color: PROD_COLOR[c.code] || '#64748b' }}>{c.code}</span>
                                  <span className="text-[9px] text-slate-600">{pct}%</span>
                                </span>
                              )
                            })}
                          </div>
                        </div>
                      </td>
                      <td className="px-3 py-2.5 text-slate-500 text-[10px] truncate max-w-[110px]"
                        title={topCreator?.name}>
                        {topCreator ? `${topCreator.name.split(' ')[0]} ×${topCreator.count}` : '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── Right Sidebar ── */}
        <div className="space-y-4">

          {/* Description Keywords */}
          {(data.keywords?.length || 0) > 0 && (
            <div className="glass rounded-xl border border-slate-700/30 p-4">
              <div className="text-xs font-semibold text-slate-300 mb-1">Description Signals</div>
              <div className="text-[9px] text-slate-600 mb-2">common words garages write in their WOA descriptions</div>
              <div className="flex flex-wrap gap-1.5">
                {(data.keywords || []).slice(0, 20).map(k => (
                  <span key={k.word}
                    className="px-1.5 py-0.5 rounded text-[9px] bg-slate-800 border border-slate-700 text-slate-400"
                    title={`${k.count}×`}>
                    {k.word}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Product × Garage Heatmap */}
      <Heatmap facilities={facilities} />

      {/* WOA Aging by Garage */}
      <AccountingAgingHeatmap status={status} />
    </div>
  )
}
