import { useState, useEffect } from 'react'
import { clsx } from 'clsx'
import { RefreshCw } from 'lucide-react'
import { fetchPerformance, fetchScorecard, fetchScore, fetchDecomposition } from '../api'
import GaragePerformance from './GaragePerformance'
import GarageOperations from './GarageOperations'

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════════════════════

export default function GarageDashboard({ garageId, garageName }) {
  // ── Shared date range (used by all tabs)
  // Default to last month (always has full data). If today is past the 5th, use current month instead.
  const today = new Date()
  const defaultStart = today.getDate() > 5
    ? new Date(today.getFullYear(), today.getMonth(), 1)
    : new Date(today.getFullYear(), today.getMonth() - 1, 1)
  const defaultEnd = today.getDate() > 5
    ? today
    : new Date(today.getFullYear(), today.getMonth(), 0)  // last day of previous month
  const [startDate, setStartDate] = useState(defaultStart.toISOString().slice(0, 10))
  const [endDate, setEndDate] = useState(defaultEnd.toISOString().slice(0, 10))

  // Legacy period compat — Overview endpoints use start/end
  const start = startDate
  const end = endDate

  // ── Data state
  const [perf, setPerf]           = useState(null)
  const [scorecard, setScorecard] = useState(null)
  const [score, setScore]         = useState(null)
  const [decomp, setDecomp]       = useState(null)
  const [loading, setLoading]     = useState({ perf: false, scorecard: false, score: false, decomp: false })
  const [error, setError]         = useState(null)
  const [decompError, setDecompError] = useState(null)
  const [scorecardError, setScorecardError] = useState(null)
  const [scoreError, setScoreError] = useState(null)
  const [activeDef, setActiveDef] = useState(null)  // which metric tooltip is open
  const [activeTab, setActiveTab] = useState('performance')  // performance | operations
  const [refreshKey, setRefreshKey] = useState(0)  // bump to force all data refresh

  // ── Load performance + decomposition in parallel (period-dependent)
  useEffect(() => {
    let ignore = false
    setLoading(p => ({ ...p, perf: true, decomp: true }))
    setError(null)
    setDecompError(null)
    setPerf(null)
    setDecomp(null)
    const load = async () => {
      const [perfResult, decompResult] = await Promise.allSettled([
        fetchPerformance(garageId, start, end),
        fetchDecomposition(garageId, start, end),
      ])
      if (ignore) return
      if (perfResult.status === 'fulfilled') setPerf(perfResult.value)
      else setError(perfResult.reason?.response?.data?.detail || perfResult.reason?.message || 'Failed to load')
      if (decompResult.status === 'fulfilled') setDecomp(decompResult.value)
      else { console.error('Decomposition fetch failed:', decompResult.reason); setDecompError(decompResult.reason?.response?.data?.detail || decompResult.reason?.message || 'Failed to load') }
      setLoading(p => ({ ...p, perf: false, decomp: false }))
    }
    load()
    return () => { ignore = true }
  }, [garageId, start, end, refreshKey])

  // ── Load scorecard + score in parallel (not period-dependent)
  useEffect(() => {
    let ignore = false
    setLoading(p => ({ ...p, scorecard: true, score: true }))
    setScorecardError(null)
    setScoreError(null)
    setScorecard(null)
    setScore(null)
    const load = async () => {
      const [scorecardResult, scoreResult] = await Promise.allSettled([
        fetchScorecard(garageId),
        fetchScore(garageId),
      ])
      if (ignore) return
      if (scorecardResult.status === 'fulfilled') setScorecard(scorecardResult.value)
      else { console.error('Scorecard fetch failed:', scorecardResult.reason); setScorecardError(scorecardResult.reason?.response?.data?.detail || scorecardResult.reason?.message || 'Failed to load') }
      if (scoreResult.status === 'fulfilled') setScore(scoreResult.value)
      else { console.error('Score fetch failed:', scoreResult.reason); setScoreError(scoreResult.reason?.response?.data?.detail || scoreResult.reason?.message || 'Failed to load') }
      setLoading(p => ({ ...p, scorecard: false, score: false }))
    }
    load()
    return () => { ignore = true }
  }, [garageId, refreshKey])

  return (
    <div className="space-y-5">

      {/* TAB BAR + DATE PILLS + CUSTOM RANGE */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex gap-1 bg-slate-900/50 rounded-lg p-1">
          {[['performance', 'Performance'], ['operations', 'Operations']].map(([key, label]) => (
            <button key={key}
              onClick={() => setActiveTab(key)}
              className={clsx('px-4 py-1.5 rounded-md text-xs font-semibold transition',
                activeTab === key ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white hover:bg-slate-800/50')}>
              {label}
            </button>
          ))}
        </div>
        {/* Month pills + custom date range */}
        <div className="flex gap-1 bg-slate-900/50 rounded-lg p-1">
              {(() => {
                const t = new Date()
                const todayStr = t.toISOString().slice(0, 10)
                const pills = []
                for (let i = 0; i <= t.getMonth(); i++) {
                  const s = new Date(t.getFullYear(), i, 1).toISOString().slice(0, 10)
                  const e = i === t.getMonth() ? todayStr : new Date(t.getFullYear(), i + 1, 0).toISOString().slice(0, 10)
                  const label = new Date(t.getFullYear(), i, 1).toLocaleDateString('en-US', { month: 'short' })
                  pills.push({ label, s, e })
                }
                return pills.map(p => (
                  <button key={p.label}
                    onClick={() => { setStartDate(p.s); setEndDate(p.e) }}
                    className={clsx('px-2.5 py-1.5 rounded-md text-[10px] font-medium transition',
                      startDate === p.s && endDate === p.e
                        ? 'bg-brand-600/30 text-brand-400 border border-brand-500/30'
                        : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800/50')}>
                    {p.label}
                  </button>
                ))
              })()}
            </div>
            <div className="flex items-center gap-2">
              <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)}
                className="bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-blue-500/50 [color-scheme:dark]" />
              <span className="text-slate-600 text-xs">to</span>
              <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)}
                className="bg-slate-800/50 border border-slate-700/50 rounded-lg px-3 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-blue-500/50 [color-scheme:dark]" />
              <button onClick={() => setRefreshKey(k => k + 1)}
                title="Force refresh all data"
                className="p-1.5 rounded-lg hover:bg-slate-800/50 text-slate-500 hover:text-white transition">
                <RefreshCw className="w-3.5 h-3.5" />
              </button>
            </div>
      </div>

      {/* PERFORMANCE TAB */}
      {activeTab === 'performance' && (
        <GaragePerformance garageId={garageId} garageName={garageName} startDate={startDate} endDate={endDate} refreshKey={refreshKey} />
      )}

      {/* OPERATIONS TAB */}
      {activeTab === 'operations' && (
        <GarageOperations
          perf={perf} score={score} scorecard={scorecard} decomp={decomp}
          loading={loading} error={error} decompError={decompError}
          scorecardError={scorecardError} scoreError={scoreError}
          startDate={startDate} endDate={endDate}
          activeDef={activeDef} setActiveDef={setActiveDef}
        />
      )}
    </div>
  )
}
