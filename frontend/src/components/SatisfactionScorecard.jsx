import React, { useState, useEffect, useRef } from 'react'
import { clsx } from 'clsx'
import { Loader2, TrendingUp, TrendingDown, Minus } from 'lucide-react'
import { fetchSatisfactionScorecard } from '../api'

const TARGET = 82

function ScoreCell({ pct, surveys }) {
  if (pct == null) return <td className="px-2 py-2 text-center text-slate-600 text-xs">—</td>
  const color = pct >= TARGET ? 'text-emerald-400' : pct >= 75 ? 'text-amber-400' : 'text-red-400'
  const bg = pct >= TARGET ? 'bg-emerald-500/8' : pct >= 75 ? 'bg-amber-500/8' : 'bg-red-500/8'
  return (
    <td className={clsx('px-2 py-2 text-center', bg)}>
      <div className={clsx('text-sm font-bold tabular-nums', color)}>{pct.toFixed(1)}%</div>
      {surveys > 0 && <div className="text-[9px] text-slate-600">{surveys} surveys</div>}
    </td>
  )
}

function ScorecardRow({ label, items, type }) {
  return (
    <div className="glass rounded-xl border border-slate-700/30 overflow-hidden">
      <div className="px-3 py-2 border-b border-slate-800/50 flex items-center gap-2">
        <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">{label}</span>
        {type === 'rolling' && <span className="text-[9px] text-slate-600">(12-month rolling avg)</span>}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-slate-800/30">
              {items.map((item, i) => (
                <th key={i} className="px-2 py-1.5 text-[10px] text-slate-500 font-medium text-center whitespace-nowrap">
                  {item.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              {items.map((item, i) => (
                <ScoreCell key={i} pct={item.pct} surveys={item.surveys} />
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function SatisfactionScorecard() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const retryRef = useRef(null)

  useEffect(() => {
    let cancelled = false
    const load = () => {
      fetchSatisfactionScorecard()
        .then(res => {
          if (cancelled) return
          if (res?.loading) {
            retryRef.current = setTimeout(load, 10000)
          } else {
            setData(res)
            setLoading(false)
          }
        })
        .catch(() => {
          if (!cancelled) setLoading(false)
        })
    }
    load()
    return () => { cancelled = true; if (retryRef.current) clearTimeout(retryRef.current) }
  }, [])

  if (!data?.generated) return null

  // Only show if there's actual data (at least one month with a score)
  const hasData = (data.monthly || []).some(m => m.pct != null)
  if (!hasData) return null

  // Compute overall trend arrow for the latest monthly value
  const monthly = data.monthly || []
  const latestMonth = monthly[monthly.length - 1]
  const prevMonth = monthly[monthly.length - 2]
  let trendIcon = Minus
  let trendColor = 'text-slate-500'
  let trendLabel = ''
  if (latestMonth?.pct != null && prevMonth?.pct != null) {
    const diff = latestMonth.pct - prevMonth.pct
    if (diff > 0.5) { trendIcon = TrendingUp; trendColor = 'text-emerald-400'; trendLabel = `+${diff.toFixed(1)}pp` }
    else if (diff < -0.5) { trendIcon = TrendingDown; trendColor = 'text-red-400'; trendLabel = `${diff.toFixed(1)}pp` }
    else { trendLabel = 'flat' }
  }
  const TrendIcon = trendIcon

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-bold text-slate-200">Satisfaction Scorecard</h3>
          {latestMonth?.pct != null && (
            <div className={clsx('flex items-center gap-1 text-xs', trendColor)}>
              <TrendIcon className="w-3.5 h-3.5" />
              <span className="font-medium">{trendLabel}</span>
            </div>
          )}
        </div>
        {data.as_of && (
          <span className="text-[9px] text-slate-600">as of {data.as_of}</span>
        )}
      </div>

      {/* Target line */}
      <div className="text-[10px] text-slate-500 flex items-center gap-2">
        <span className="w-6 h-px bg-emerald-500/60" />
        <span>Target: {TARGET}% Totally Satisfied</span>
      </div>

      {/* 4 sections — only show rows that have at least one value */}
      {(data.rolling_12 || []).some(r => r.pct != null) &&
        <ScorecardRow label="Rolling 12" items={(data.rolling_12 || []).filter(r => r.pct != null)} type="rolling" />}
      {(data.monthly || []).some(m => m.pct != null) &&
        <ScorecardRow label="Monthly" items={(data.monthly || []).filter(m => m.pct != null)} type="monthly" />}
      {(data.weekly || []).some(w => w.pct != null) &&
        <ScorecardRow label="Weekly" items={(data.weekly || []).filter(w => w.pct != null)} type="weekly" />}
      {(data.last_7_days || []).some(d => d.pct != null) &&
        <ScorecardRow label="Last 7 Days" items={(data.last_7_days || []).filter(d => d.pct != null)} type="daily" />}
    </div>
  )
}
