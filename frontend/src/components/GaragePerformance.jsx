/**
 * GaragePerformance.jsx — "Performance" tab in Garage Dashboard
 *
 * Shows: 4 satisfaction scores, primary vs secondary, driver breakdown with bonus,
 * drill-down to individual surveys, AI executive summary.
 */

import { useState, useEffect, useContext } from 'react'
import { Loader2, ChevronDown, ChevronUp, DollarSign, Star, AlertTriangle, Sparkles, Download } from 'lucide-react'
import { clsx } from 'clsx'
import { fetchGarageScorecard, fetchGarageAiSummary, exportGarageScorecard } from '../api'
import { SAReportContext } from '../contexts/SAReportContext'

// Score card colors
const scoreColor = (pct) =>
  pct == null ? 'text-slate-600' :
  pct >= 92 ? 'text-emerald-400' :
  pct >= 82 ? 'text-blue-400' :
  pct >= 70 ? 'text-amber-400' : 'text-red-400'

const scoreBg = (pct) =>
  pct == null ? 'bg-slate-800' :
  pct >= 92 ? 'bg-emerald-500' :
  pct >= 82 ? 'bg-blue-500' :
  pct >= 70 ? 'bg-amber-500' : 'bg-red-500'

const bonusColor = (bonus) =>
  bonus >= 4 ? 'text-emerald-400' :
  bonus >= 3 ? 'text-green-400' :
  bonus >= 2 ? 'text-blue-400' :
  bonus >= 1 ? 'text-amber-400' : 'text-slate-500'

function ScoreCard({ label, pct, subtitle }) {
  return (
    <div className="glass rounded-xl p-4 border border-slate-700/30">
      <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">{label}</div>
      <div className={clsx('text-3xl font-black', scoreColor(pct))}>
        {pct != null ? `${pct}%` : '—'}
      </div>
      <div className="h-1.5 rounded-full bg-slate-800 mt-2 overflow-hidden">
        {pct != null && <div className={clsx('h-full rounded-full', scoreBg(pct))} style={{ width: `${Math.min(pct, 100)}%` }} />}
      </div>
      {subtitle && <div className="text-[9px] text-slate-600 mt-1">{subtitle}</div>}
    </div>
  )
}

function DriverRow({ driver, onToggle, expanded }) {
  const saCtx = useContext(SAReportContext)
  return (
    <div className="border-b border-slate-800/50 last:border-0">
      <div
        className="flex items-center gap-3 px-3 py-2.5 cursor-pointer hover:bg-slate-800/30 transition"
        onClick={onToggle}
      >
        <div className="w-4">
          {expanded ? <ChevronUp className="w-3.5 h-3.5 text-slate-500" /> : <ChevronDown className="w-3.5 h-3.5 text-slate-500" />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-xs font-semibold text-white truncate">{driver.name}</div>
          <div className="text-[9px] text-slate-500">{driver.survey_count} surveys</div>
        </div>
        <div className="text-center w-14">
          <div className={clsx('text-xs font-bold', scoreColor(driver.overall_pct))}>{driver.overall_pct ?? '—'}%</div>
          <div className="text-[8px] text-slate-600">Overall</div>
        </div>
        <div className="text-center w-14">
          <div className={clsx('text-xs font-bold', scoreColor(driver.response_time_pct))}>{driver.response_time_pct ?? '—'}%</div>
          <div className="text-[8px] text-slate-600">Resp Time</div>
        </div>
        <div className="text-center w-14">
          <div className={clsx('text-xs font-bold', scoreColor(driver.technician_pct))}>{driver.technician_pct ?? '—'}%</div>
          <div className="text-[8px] text-slate-600">Tech</div>
        </div>
        <div className="text-center w-14">
          <div className={clsx('text-xs font-bold', scoreColor(driver.kept_informed_pct))}>{driver.kept_informed_pct ?? '—'}%</div>
          <div className="text-[8px] text-slate-600">Informed</div>
        </div>
        <div className="text-center w-16">
          <div className={clsx('text-xs font-bold', bonusColor(driver.bonus_per_sa))}>
            ${driver.total_bonus}
          </div>
          <div className="text-[8px] text-slate-600">${driver.bonus_per_sa}/SA</div>
        </div>
      </div>
      {/* Drill-down: individual surveys */}
      {expanded && driver.surveys && (
        <div className="bg-slate-900/40 px-4 py-2 space-y-1.5">
          <div className="grid grid-cols-[80px_60px_60px_60px_60px_1fr] gap-2 text-[8px] text-slate-600 uppercase tracking-wider pb-1 border-b border-slate-800/40">
            <span>Date</span><span>Overall</span><span>Resp</span><span>Tech</span><span>Informed</span><span>Comment</span>
          </div>
          {driver.surveys.map((sv, i) => {
            const satBadge = (val) => {
              if (!val) return <span className="text-slate-700">—</span>
              const v = val.toLowerCase()
              const cls = v === 'totally satisfied' ? 'text-emerald-400' :
                v === 'satisfied' ? 'text-green-400' :
                v.includes('neither') ? 'text-slate-400' :
                v === 'dissatisfied' ? 'text-amber-400' : 'text-red-400'
              const short = v === 'totally satisfied' ? 'TS' :
                v === 'satisfied' ? 'S' :
                v.includes('neither') ? 'N' :
                v === 'dissatisfied' ? 'D' : 'TD'
              return <span className={clsx('font-semibold', cls)}>{short}</span>
            }
            return (
              <div key={i} className="grid grid-cols-[80px_60px_60px_60px_60px_1fr] gap-2 text-[10px] items-start">
                <span className="text-slate-400">
                  {sv.wo_number ? (
                    <button className="text-blue-400 hover:underline" onClick={(e) => { e.stopPropagation(); saCtx?.open(`SA-${sv.wo_number}`) }}>
                      {sv.call_date}
                    </button>
                  ) : sv.call_date}
                </span>
                {satBadge(sv.overall)}
                {satBadge(sv.response_time)}
                {satBadge(sv.technician)}
                {satBadge(sv.kept_informed)}
                <span className="text-slate-400 italic text-[9px] truncate" title={sv.comment || ''}>
                  {sv.comment || '—'}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default function GaragePerformance({ garageId, garageName, startDate, endDate }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [aiSummary, setAiSummary] = useState(null)
  const [aiLoading, setAiLoading] = useState(false)
  const [expandedDriver, setExpandedDriver] = useState(null)
  const [sortBy, setSortBy] = useState('survey_count')
  const [sortDir, setSortDir] = useState('desc')

  useEffect(() => {
    if (!startDate || !endDate) return
    setLoading(true)
    setError(null)
    setAiSummary(null)
    fetchGarageScorecard(garageId, startDate, endDate)
      .then(d => {
        setData(d)
        setAiLoading(true)
        fetchGarageAiSummary(garageId, startDate, endDate)
          .then(r => setAiSummary(r.summary))
          .catch(() => setAiSummary('Failed to generate AI summary.'))
          .finally(() => setAiLoading(false))
      })
      .catch(e => setError(e.response?.data?.detail || e.message || 'Failed'))
      .finally(() => setLoading(false))
  }, [garageId, startDate, endDate])

  const gs = data?.garage_summary || {}
  const ps = data?.primary_vs_secondary || {}
  const drivers = data?.drivers || []

  // Sort drivers
  const sorted = [...drivers].sort((a, b) => {
    const va = a[sortBy] ?? -1, vb = b[sortBy] ?? -1
    return sortDir === 'desc' ? vb - va : va - vb
  })

  const toggleSort = (field) => {
    if (sortBy === field) setSortDir(d => d === 'desc' ? 'asc' : 'desc')
    else { setSortBy(field); setSortDir('desc') }
  }

  return (
    <div className="space-y-4">
      {/* Date range info + Export */}
      <div className="flex items-center justify-between">
        <div className="text-[10px] text-slate-500">
          {gs.total_surveys || 0} surveys · {gs.total_completed || 0} completed SAs · {startDate} to {endDate}
        </div>
        {data && !loading && (
          <button
            onClick={() => exportGarageScorecard(garageId, startDate, endDate)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-medium text-slate-300 bg-slate-800/60 hover:bg-slate-700/60 border border-slate-700/40 rounded-lg transition"
          >
            <Download className="w-3.5 h-3.5" />
            Export Excel
          </button>
        )}
      </div>

      {error && <div className="text-red-400 text-sm bg-red-950/30 rounded-lg p-3 border border-red-800/30">{error}</div>}

      {loading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
          <span className="ml-2 text-sm text-slate-500">Loading scorecard...</span>
        </div>
      )}

      {data && !loading && (<>
        {/* AI Executive Summary — first, async loaded */}
        <div className="glass rounded-xl p-4 border border-purple-800/20">
          <div className="flex items-center gap-2 mb-3">
            <Sparkles className="w-4 h-4 text-purple-400" />
            <span className="text-xs font-bold text-white uppercase tracking-wide">AI Executive Summary</span>
          </div>
          {aiLoading && (
            <div className="flex items-center gap-2 py-4">
              <Loader2 className="w-4 h-4 animate-spin text-purple-400" />
              <span className="text-xs text-slate-500">Generating analysis...</span>
            </div>
          )}
          {aiSummary && !aiLoading && (
            <div className="text-xs text-slate-300 leading-relaxed whitespace-pre-wrap">{aiSummary}</div>
          )}
          {!aiSummary && !aiLoading && (
            <div className="text-xs text-slate-600 py-2">No AI summary available. Configure AI in Admin → AI Assistant.</div>
          )}
        </div>

        {/* Total Driver Bonus Earned */}
        {drivers.length > 0 && (() => {
          const totalDriverBonus = drivers.reduce((sum, d) => sum + (d.total_bonus || 0), 0)
          const driversWithBonus = drivers.filter(d => d.bonus_per_sa > 0)
          return (
            <div className={clsx('glass rounded-xl p-4 border flex items-center gap-4',
              totalDriverBonus > 0 ? 'border-emerald-800/30' : 'border-slate-700/30')}>
              <DollarSign className={clsx('w-8 h-8', totalDriverBonus > 0 ? 'text-emerald-400' : 'text-slate-600')} />
              <div className="flex-1">
                <div className="text-sm font-bold text-white">
                  Total Bonus Earned: <span className={totalDriverBonus > 0 ? 'text-emerald-400' : 'text-slate-500'}>${totalDriverBonus.toLocaleString()}</span>
                </div>
                <div className="text-xs text-slate-400">
                  {driversWithBonus.length} of {drivers.length} drivers earning bonus · Garage Tech score: {gs.technician_pct ?? '—'}%
                </div>
              </div>
            </div>
          )
        })()}

        {/* Primary vs Secondary — scores + SA metrics + bonus */}
        <div className="glass rounded-xl p-4 border border-slate-700/30">
          <div className="text-xs font-bold text-white uppercase tracking-wide mb-3">Primary vs Secondary Assignments</div>
          <div className="grid grid-cols-2 gap-4">
            {['primary', 'secondary'].map(type => {
              const g = ps[type] || {}
              const label = type === 'primary' ? 'Primary (First Assigned)' : 'Secondary (Reassigned Here)'
              return (
                <div key={type} className="bg-slate-900/40 rounded-lg p-3 space-y-3">
                  <div className="text-[10px] text-slate-500 uppercase font-bold">{label}</div>

                  {/* SA Metrics */}
                  <div className="grid grid-cols-3 gap-2">
                    <div className="bg-slate-800/40 rounded-lg p-2 text-center">
                      <div className="text-lg font-bold text-white">{g.total_sas ?? 0}</div>
                      <div className="text-[10px] text-slate-400">Total SAs</div>
                    </div>
                    <div className="bg-slate-800/40 rounded-lg p-2 text-center">
                      <div className="text-lg font-bold text-emerald-400">{g.completed ?? 0}</div>
                      <div className="text-[10px] text-slate-400">Completed</div>
                    </div>
                    <div className="bg-slate-800/40 rounded-lg p-2 text-center">
                      <div className="text-lg font-bold text-red-400">{g.declined ?? 0}</div>
                      <div className="text-[10px] text-slate-400">Declined</div>
                    </div>
                  </div>

                  {/* ATA + PTA */}
                  <div className="grid grid-cols-2 gap-2">
                    <div className="bg-slate-800/40 rounded-lg p-2 text-center">
                      <div className={clsx('text-sm font-bold', (g.avg_ata ?? 999) <= 45 ? 'text-emerald-400' : (g.avg_ata ?? 999) <= 60 ? 'text-amber-400' : 'text-red-400')}>
                        {g.avg_ata != null ? `${g.avg_ata}m` : '—'}
                      </div>
                      <div className="text-[10px] text-slate-400">Avg ATA</div>
                    </div>
                    <div className="bg-slate-800/40 rounded-lg p-2 text-center">
                      <div className={clsx('text-sm font-bold', (g.pta_hit_pct ?? 0) >= 80 ? 'text-emerald-400' : (g.pta_hit_pct ?? 0) >= 60 ? 'text-amber-400' : 'text-red-400')}>
                        {g.pta_hit_pct != null ? `${g.pta_hit_pct}%` : '—'}
                      </div>
                      <div className="text-[10px] text-slate-400">PTA Hit Rate</div>
                    </div>
                  </div>

                  {/* Satisfaction Scores */}
                  <div className="grid grid-cols-4 gap-2 text-center pt-2 border-t border-slate-800/40">
                    {[['Overall', g.overall_pct], ['Response Time', g.response_time_pct], ['Technician', g.technician_pct], ['Kept Informed', g.kept_informed_pct]].map(([lbl, pct]) => (
                      <div key={lbl}>
                        <div className="text-[10px] text-slate-400 mb-0.5">{lbl}</div>
                        <div className={clsx('text-lg font-bold', scoreColor(pct))}>{pct ?? '—'}%</div>
                      </div>
                    ))}
                  </div>
                  {/* Bonus for this group */}
                  {g.technician_pct != null && (
                    <div className={clsx('flex items-center gap-2 pt-2 border-t border-slate-800/40 text-[10px]',
                      g.technician_pct >= 92 ? 'text-emerald-400' : 'text-slate-500')}>
                      <DollarSign className="w-3 h-3" />
                      <span>
                        Tech {g.technician_pct}% → ${g.technician_pct >= 98 ? 4 : g.technician_pct >= 96 ? 3 : g.technician_pct >= 94 ? 2 : g.technician_pct >= 92 ? 1 : 0}/SA
                        × {g.completed || 0} = <span className="font-bold">${(g.technician_pct >= 98 ? 4 : g.technician_pct >= 96 ? 3 : g.technician_pct >= 94 ? 2 : g.technician_pct >= 92 ? 1 : 0) * (g.completed || 0)}</span>
                      </span>
                    </div>
                  )}
                  <div className="text-[9px] text-slate-600 text-right">{g.survey_count || 0} surveys</div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Driver Breakdown */}
        <div className="glass rounded-xl border border-slate-700/30 overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-800/50 flex items-center gap-2">
            <Star className="w-4 h-4 text-amber-400" />
            <span className="text-xs font-bold text-white uppercase tracking-wide">Driver Breakdown</span>
            <span className="text-[10px] text-slate-500 ml-auto">{drivers.length} drivers</span>
          </div>
          {/* Sort header */}
          <div className="flex items-center gap-3 px-3 py-1.5 bg-slate-900/60 text-[10px] text-slate-400 uppercase tracking-wider border-b border-slate-800/40">
            <div className="w-4" />
            <div className="flex-1">Driver</div>
            {[['overall_pct', 'Overall', 'w-14'], ['response_time_pct', 'Resp', 'w-14'], ['technician_pct', 'Tech', 'w-14'], ['kept_informed_pct', 'Informed', 'w-14'], ['total_bonus', 'Bonus', 'w-16']].map(([field, label, w]) => (
              <button key={field} className={clsx('text-center cursor-pointer hover:text-white transition', w, sortBy === field && 'text-blue-400')}
                onClick={() => toggleSort(field)}>
                {label} {sortBy === field && (sortDir === 'desc' ? '↓' : '↑')}
              </button>
            ))}
          </div>
          <div className="max-h-[500px] overflow-y-auto">
            {sorted.map((d, i) => (
              <DriverRow key={i} driver={d}
                expanded={expandedDriver === d.name}
                onToggle={() => setExpandedDriver(expandedDriver === d.name ? null : d.name)} />
            ))}
          </div>
        </div>
      </>)}
    </div>
  )
}
