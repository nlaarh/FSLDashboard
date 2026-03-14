import { useState, useEffect } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { clsx } from 'clsx'
import { CheckCircle2, XCircle, AlertTriangle, Target, Users, Truck, Clock, Award, Loader2 } from 'lucide-react'
import { fetchScore } from '../api'

export default function Scorecard({ data, garageId }) {
  const { sla, fleet, volume, goals } = data
  const [score, setScore] = useState(null)
  const [scoreLoading, setScoreLoading] = useState(false)
  const [scoreError, setScoreError] = useState(null)

  const dowOrder = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
  const dowData = dowOrder.map(d => ({ day: d, count: volume.by_dow?.[d] || 0 }))

  // Load performance score
  useEffect(() => {
    if (garageId && !score && !scoreLoading) {
      setScoreLoading(true)
      fetchScore(garageId)
        .then(setScore)
        .catch(e => { console.error('Score fetch failed:', e); setScoreError(e.response?.data?.detail || e.message || 'Failed to load') })
        .finally(() => setScoreLoading(false))
    }
  }, [garageId, score, scoreLoading])

  return (
    <div className="space-y-6">

      {/* ── Composite Score ───────────────────────────────────────────── */}
      {score && (
        <div className="glass rounded-xl p-6">
          <div className="flex items-center gap-3 mb-4">
            <Award className="w-6 h-6 text-brand-400" />
            <h3 className="font-bold text-lg text-slate-200">Performance Score</h3>
          </div>
          <div className="flex items-center gap-6 mb-5">
            <div className={clsx(
              'w-24 h-24 rounded-2xl flex flex-col items-center justify-center border-2',
              score.grade === 'A' ? 'bg-emerald-950/40 border-emerald-500/40' :
              score.grade === 'B' ? 'bg-blue-950/40 border-blue-500/40' :
              score.grade === 'C' ? 'bg-amber-950/40 border-amber-500/40' :
              'bg-red-950/40 border-red-500/40'
            )}>
              <div className={clsx(
                'text-4xl font-black',
                score.grade === 'A' ? 'text-emerald-400' :
                score.grade === 'B' ? 'text-blue-400' :
                score.grade === 'C' ? 'text-amber-400' :
                'text-red-400'
              )}>{score.grade}</div>
              <div className="text-sm font-bold text-white">{score.composite}/100</div>
            </div>
            <div className="text-sm text-slate-400">
              <p>Based on <span className="text-white font-semibold">{score.sample_sizes?.total_sas?.toLocaleString()}</span> SAs</p>
              <p>{score.sample_sizes?.completed?.toLocaleString()} completed, {score.sample_sizes?.surveys} surveys</p>
            </div>
          </div>

          {/* Dimension scores */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
            {Object.entries(score.dimensions || {}).map(([key, dim]) => (
              <div key={key} className={clsx(
                'rounded-xl p-3 border',
                dim.met ? 'bg-emerald-950/20 border-emerald-800/30' : 'bg-slate-800/30 border-slate-700/30'
              )}>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{dim.label}</span>
                  <span className="text-[10px] text-slate-500">{dim.weight_pct}</span>
                </div>
                <div className="flex items-baseline gap-2">
                  <span className={clsx('text-xl font-bold',
                    dim.score >= 80 ? 'text-emerald-400' :
                    dim.score >= 60 ? 'text-amber-400' :
                    dim.score != null ? 'text-red-400' : 'text-slate-600'
                  )}>
                    {dim.score != null ? dim.score : '—'}
                  </span>
                  <span className="text-xs text-slate-500">/100</span>
                </div>
                <div className="flex items-center justify-between mt-1">
                  <span className="text-xs text-slate-400">{dim.actual_display}</span>
                  <span className="text-[10px] text-slate-600">target: {dim.target_display}</span>
                </div>
                {/* Score bar */}
                <div className="mt-2 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                  <div className={clsx('h-full rounded-full transition-all',
                    dim.score >= 80 ? 'bg-emerald-500' :
                    dim.score >= 60 ? 'bg-amber-500' : 'bg-red-500'
                  )} style={{ width: `${Math.max(dim.score || 0, 2)}%` }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      {scoreLoading && (
        <div className="glass rounded-xl p-6 flex items-center gap-3">
          <Loader2 className="w-5 h-5 animate-spin text-brand-400" />
          <span className="text-sm text-slate-400">Computing performance score (querying surveys, response times...)...</span>
        </div>
      )}
      {!score && scoreError && !scoreLoading && (
        <div className="glass rounded-xl p-6">
          <div className="flex items-center gap-3">
            <AlertTriangle className="w-5 h-5 text-red-400" />
            <span className="text-sm text-red-400">Performance score unavailable: {scoreError}</span>
          </div>
        </div>
      )}

      {/* Goal Status Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {goals.map(g => (
          <div key={g.name} className={clsx(
            'rounded-xl p-5 border',
            g.met ? 'bg-emerald-950/30 border-emerald-800/40' : 'bg-red-950/30 border-red-800/40'
          )}>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">{g.name}</span>
              {g.met ? <CheckCircle2 className="w-5 h-5 text-emerald-400" /> : <XCircle className="w-5 h-5 text-red-400" />}
            </div>
            <div className="flex items-baseline gap-3">
              <span className="text-3xl font-bold text-white">{g.actual}</span>
              <span className="text-sm text-slate-500">target: {g.target}</span>
            </div>
            <div className={clsx('mt-2 text-sm font-medium', g.met ? 'text-emerald-400' : 'text-red-400')}>
              {g.met ? 'Meeting goal' : g.gap}
            </div>
          </div>
        ))}
      </div>

      {/* SLA Deep Dive + Fleet */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* SLA Analysis */}
        <div className="glass rounded-xl p-5 space-y-4">
          <div className="flex items-center gap-2">
            <Target className="w-5 h-5 text-brand-400" />
            <h3 className="font-semibold text-slate-200">45-Minute SLA Analysis</h3>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Stat label="Median PTA Promise" value={sla.median_pta_promised ? `${sla.median_pta_promised} min` : 'N/A'}
              color={sla.median_pta_promised && sla.median_pta_promised <= 45 ? 'text-emerald-400' : 'text-red-400'}
              sub={sla.median_pta_promised > 45 ? `${sla.median_pta_promised - 45} min over target` : null} />
            <Stat label="Actual Median Response" value={sla.actual_median_response ? `${sla.actual_median_response} min` : 'N/A'}
              color={sla.actual_median_response && sla.actual_median_response <= 45 ? 'text-emerald-400' : 'text-red-400'}
              sub={sla.actual_median_response > 45 ? `${sla.actual_median_response - 45} min over target` : null} />
            <Stat label="Calls Promised ≤45 min" value={`${sla.pta_compliance_45min}%`}
              color={sla.pta_compliance_45min > 50 ? 'text-emerald-400' : 'text-red-400'} />
            <Stat label="Actually Responded ≤45 min" value={`${sla.actual_under_45min_pct}%`}
              color={sla.actual_under_45min_pct > 50 ? 'text-emerald-400' : 'text-red-400'}
              sub={`${sla.actual_under_45min} of ${sla.response_sample_size} calls`} />
          </div>
          <div>
            <h4 className="text-xs text-slate-500 uppercase mb-2">What is being promised to members?</h4>
            <div className="space-y-1.5">
              {(sla.pta_buckets || []).map(b => (
                <div key={b.label} className="flex items-center gap-2">
                  <div className="w-24 text-xs text-slate-400 text-right">{b.label}</div>
                  <div className="flex-1 h-5 bg-slate-800 rounded-full overflow-hidden">
                    <div className={clsx('h-full rounded-full transition-all',
                      b.label.includes('Under 45') ? 'bg-emerald-500' :
                      b.label.includes('45-90') ? 'bg-amber-500' : 'bg-red-500'
                    )} style={{ width: `${Math.max(b.pct, 1)}%` }} />
                  </div>
                  <div className="w-16 text-xs text-slate-400">{b.pct}% ({b.count})</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Fleet / Contractor Composition */}
        <div className="glass rounded-xl p-5 space-y-4">
          <div className="flex items-center gap-2">
            <Truck className="w-5 h-5 text-brand-400" />
            <h3 className="font-semibold text-slate-200">
              {fleet.garage_type === 'towbook' ? 'Contractor Trucks' : 'Fleet Composition'}
            </h3>
            {fleet.garage_type === 'towbook' && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-600/20 text-amber-400 font-medium">TOWBOOK</span>
            )}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-slate-800/50 rounded-xl p-4 text-center">
              <div className="text-3xl font-bold text-white">{fleet.total_trucks || 0}</div>
              <div className="text-xs text-slate-400 mt-1">Total Trucks</div>
            </div>
            <div className="bg-slate-800/50 rounded-xl p-4 text-center">
              <div className="text-3xl font-bold text-slate-300">
                {fleet.garage_type === 'towbook' ? (fleet.total_contractors || 0) : fleet.total_members}
              </div>
              <div className="text-xs text-slate-400 mt-1">
                {fleet.garage_type === 'towbook' ? 'Active Contractors' : 'Territory Members'}
              </div>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-red-950/30 rounded-xl p-4 text-center border border-red-800/20">
              <div className="text-3xl font-bold text-red-400">{fleet.tow_trucks || 0}</div>
              <div className="text-xs text-slate-400 mt-1">Tow Trucks</div>
            </div>
            <div className="bg-blue-950/30 rounded-xl p-4 text-center border border-blue-800/20">
              <div className="text-3xl font-bold text-blue-400">{fleet.other_trucks || 0}</div>
              <div className="text-xs text-slate-400 mt-1">Battery/Light Trucks</div>
            </div>
          </div>
          <div>
            <h4 className="text-xs text-slate-500 uppercase mb-2">SA Volume by Type (last {data.weeks || 4} weeks)</h4>
            <div className="space-y-2">
              <TypeBar label="Tow" count={volume.tow_sas} total={volume.total} color="bg-red-500" />
              <TypeBar label="Battery" count={volume.battery_sas} total={volume.total} color="bg-blue-500" />
              <TypeBar label="Light Service" count={volume.light_sas} total={volume.total} color="bg-teal-500" />
            </div>
          </div>
          <div>
            <h4 className="text-xs text-slate-500 uppercase mb-2">Avg Weekly Demand by Day</h4>
            <div className="h-36">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={dowData}>
                  <XAxis dataKey="day" stroke="#475569" tick={{ fontSize: 11, fill: '#94a3b8' }} />
                  <YAxis stroke="#475569" tick={{ fontSize: 10, fill: '#94a3b8' }} />
                  <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
                    itemStyle={{ color: '#e2e8f0' }} />
                  <Bar dataKey="count" fill="#6366f1" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      </div>

      {/* Key insights */}
      <div className="glass rounded-xl p-5">
        <h3 className="font-semibold text-slate-200 mb-3 flex items-center gap-2">
          <AlertTriangle className="w-5 h-5 text-amber-400" />
          How to Meet the 45-Minute Goal
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Lever num={1} title={fleet.garage_type === 'towbook' ? 'Maximize Contractor Coverage' : 'Deploy Full Fleet'}
            desc={fleet.garage_type === 'towbook'
              ? `${fleet.total_contractors || fleet.total_trucks || 0} contractor trucks active. Monitor decline rates and PTA compliance.`
              : `${fleet.total_members} drivers on the books. Ensure all are on the road at peak.`}
            impact={fleet.garage_type === 'towbook' ? 'Reduces decline-driven delays' : 'Eliminates queue wait time'} />
          <Lever num={2} title="Dispatch Closest Driver"
            desc="System currently picks closest only ~26% of the time. Fix dispatch logic."
            impact="Cuts 5-10 min per call" />
          <Lever num={3} title="Reduce Drop-Off Time"
            desc="Garage drop-off takes 43 min (median 38). 10 min reduction = ~10% more tow capacity."
            impact="Frees driver capacity" />
        </div>
      </div>
    </div>
  )
}

function Stat({ label, value, color = 'text-white', sub }) {
  return (
    <div>
      <div className="text-[10px] text-slate-500 uppercase tracking-wider">{label}</div>
      <div className={clsx('text-2xl font-bold mt-0.5', color)}>{value}</div>
      {sub && <div className="text-xs text-slate-500 mt-0.5">{sub}</div>}
    </div>
  )
}

function TypeBar({ label, count, total, color }) {
  const pct = total > 0 ? round(100 * count / total) : 0
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 text-xs text-slate-400 text-right">{label}</div>
      <div className="flex-1 h-4 bg-slate-800 rounded-full overflow-hidden">
        <div className={clsx('h-full rounded-full', color)} style={{ width: `${Math.max(pct, 1)}%` }} />
      </div>
      <div className="w-24 text-xs text-slate-400">{count.toLocaleString()} ({pct}%)</div>
    </div>
  )
}

function round(n) { return Math.round(n * 10) / 10 }

function Lever({ num, title, desc, impact }) {
  return (
    <div className="bg-slate-800/40 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-2">
        <span className="w-6 h-6 rounded-full bg-brand-600 text-white text-xs font-bold flex items-center justify-center">{num}</span>
        <span className="font-semibold text-sm text-slate-200">{title}</span>
      </div>
      <p className="text-xs text-slate-400 leading-relaxed">{desc}</p>
      <div className="mt-2 text-xs text-emerald-400 font-medium">{impact}</div>
    </div>
  )
}
