import { useEffect, useState } from 'react'
import { Loader2, RefreshCw, HelpCircle, ChevronDown, ChevronUp, ChevronsUpDown, Sparkles, Check } from 'lucide-react'
import { fetchDispatchScore, refreshDispatchScore, fetchDispatcherInsight } from '../api'
import DispatchScoreDetail from './DispatchScoreDetail'

const TIER_STYLES = {
  Elite:           'bg-amber-500/15 text-amber-300 border-amber-500/30',
  Proficient:      'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  Developing:      'bg-blue-500/15 text-blue-400 border-blue-500/30',
  'Needs Support': 'bg-red-500/15 text-red-400 border-red-500/30',
}

const TIER_STROKE = {
  Elite: '#fbbf24', Proficient: '#34d399', Developing: '#60a5fa', 'Needs Support': '#f87171',
}

const fmtTs = (epoch) => epoch
  ? new Date(epoch * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
  : '—'

// ── Sortable column definitions ───────────────────────────────────────────────
const COLS = [
  { key: 'name',         label: 'Name',            align: 'left',  sortFn: d => d.name },
  { key: 'score',        label: 'Score',           align: 'right', sortFn: d => d.score ?? -1 },
  { key: 'channel_rank', label: 'Peer Rank',       align: 'right', sortFn: d => d.channel_rank ?? 99 },
  { key: 'adj_comp_pct', label: 'Fair Completion', align: 'right', sortFn: d => d.adj_comp_pct ?? -1 },
  { key: 'pta_rate',     label: 'PTA Rate',        align: 'right', sortFn: d => d.pta_rate ?? -1 },
  { key: 'median_rt_min','label': 'Avg Response',  align: 'right', sortFn: d => d.median_rt_min ?? 9999 },
]

function SortIcon({ col, sortCol, sortDir }) {
  if (sortCol !== col) return <ChevronsUpDown className="w-3 h-3 opacity-25 ml-1 inline" />
  return sortDir === 'asc'
    ? <ChevronUp   className="w-3 h-3 text-blue-400 ml-1 inline" />
    : <ChevronDown className="w-3 h-3 text-blue-400 ml-1 inline" />
}

function MiniRing({ score, tier }) {
  const pct = Math.max(0, Math.min(100, score || 0))
  const stroke = TIER_STROKE[tier] || '#64748b'
  return (
    <div className="relative w-9 h-9 flex items-center justify-center shrink-0">
      <svg className="w-9 h-9 -rotate-90 absolute" viewBox="0 0 36 36">
        <circle cx="18" cy="18" r="14" fill="none" stroke="rgb(51,65,85)" strokeWidth="3.5" />
        <circle cx="18" cy="18" r="14" fill="none" stroke={stroke} strokeWidth="3.5"
          strokeDasharray={`${(pct / 100) * 87.96} 87.96`} strokeLinecap="round" />
      </svg>
      <span className="text-[11px] font-bold text-slate-100 relative">{score}</span>
    </div>
  )
}

const SCORE_GUIDE = [
  {
    label: 'Completion Quality', max: 40, color: 'text-emerald-400',
    what: 'Did the drivers this dispatcher assigned actually complete the call?',
    how: 'Harder call types count more than easy ones — Winch Out is worth 2×, Tow Pick-Up 1.2×, Locksmith 1.3×, Tire 1.1×, Battery and Lockout 1.0×, Tow Drop-Off 0.8×.',
    thresholds: '≥93% → 40 pts · ≥90% → 35 · ≥85% → 30 · ≥80% → 23 · ≥75% → 15 · <75% → 7',
    why: 'Completing the member\'s call is the job. Low score usually means driver selection — wrong skill level, wrong territory, or the wrong driver for a hard call.',
  },
  {
    label: 'Speed', max: 25, color: 'text-blue-400',
    what: 'Typical minutes from when a service call lands in the queue to when the dispatcher assigns a driver.',
    how: 'Calls that waited over 2 hours are excluded — those are usually inherited from the previous shift.',
    thresholds: '≤5 min → 25 pts · ≤10 min → 22 · ≤15 min → 18 · ≤20 min → 14 · ≤30 min → 10 · ≤45 min → 5 · >45 min → 2',
    why: 'Dispatchers who monitor Live Dispatch and the Watchlist respond faster.',
  },
  {
    label: 'Reliability', max: 20, color: 'text-amber-400',
    what: 'What percentage of calls took over 30 minutes to get a driver assigned?',
    how: 'Even if the average looks fine, a high percentage here means many individual members waited a long time.',
    thresholds: '<15% slow → 20 pts · <20% → 17 · <30% → 13 · <40% → 8 · <55% → 4 · ≥55% → 1',
    why: 'Catches shift-change spikes and specific time windows with poor coverage.',
  },
  {
    label: 'Volume', max: 15, color: 'text-purple-400',
    what: 'Total calls dispatched in the 90-day window.',
    how: 'With fewer calls, the other scores are less reliable.',
    thresholds: '≥400 → 15 pts · ≥250 → 13 · ≥150 → 10 · ≥75 → 7 · ≥25 → 4 · <25 → 0',
    why: 'Ensures the other three scores are based on enough data to be meaningful.',
  },
]

function ScoringGuide() {
  const [open, setOpen] = useState(false)
  return (
    <div className="glass rounded-xl border border-slate-700/40 overflow-hidden">
      <button onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 px-4 py-3 text-left hover:bg-slate-800/30 transition-colors">
        <HelpCircle className="w-3.5 h-3.5 text-slate-500 shrink-0" />
        <span className="text-xs font-medium text-slate-400">How is the score calculated?</span>
        {open ? <ChevronUp className="w-3.5 h-3.5 text-slate-500 ml-auto" />
               : <ChevronDown className="w-3.5 h-3.5 text-slate-500 ml-auto" />}
      </button>
      {open && (
        <div className="px-4 pb-4 space-y-4 border-t border-slate-700/40 pt-4">
          <p className="text-xs text-slate-400">
            Each dispatcher receives a score of <span className="text-slate-200 font-semibold">0–100</span> built
            from four dimensions over a rolling 90-day window. Response times over 120 minutes are capped to
            protect against overnight shift-change backlog.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {SCORE_GUIDE.map(g => (
              <div key={g.label} className="bg-slate-800/40 rounded-lg border border-slate-700/30 p-3 space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className={`text-xs font-bold ${g.color}`}>{g.label}</span>
                  <span className="text-[10px] text-slate-500">{g.max} pts max</span>
                </div>
                <p className="text-[11px] text-slate-300 font-medium">{g.what}</p>
                <p className="text-[10px] text-slate-500 leading-relaxed">{g.how}</p>
                <p className="text-[10px] text-slate-600 font-mono leading-relaxed">{g.thresholds}</p>
                <p className="text-[10px] text-slate-500 italic leading-relaxed">{g.why}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default function DispatchScoreTab() {
  const [data,              setData]              = useState(null)
  const [loading,           setLoading]           = useState(true)
  const [computing,         setComputing]         = useState(false)
  const [refreshing,        setRefreshing]        = useState(false)
  const [error,             setError]             = useState('')
  const [selected,          setSelected]          = useState(null)
  const [sortCol,           setSortCol]           = useState('score')
  const [sortDir,           setSortDir]           = useState('desc')
  const [rowInsightLoading, setRowInsightLoading] = useState({})  // username → 'loading'|'done'|undefined

  const load = async () => {
    setLoading(true); setError('')
    try {
      const result = await fetchDispatchScore()
      setData(result)
      setComputing(result.status === 'computing')
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load scorecard')
    } finally { setLoading(false) }
  }

  const forceRefresh = async () => {
    setRefreshing(true); setError('')
    try {
      const result = await refreshDispatchScore()
      setData(result)
      setComputing(result.status === 'computing')
    } catch (e) {
      setError(e.response?.data?.detail || 'Refresh failed')
    } finally { setRefreshing(false) }
  }

  const regenerateInsight = async (e, username) => {
    e.stopPropagation()
    setRowInsightLoading(s => ({ ...s, [username]: 'loading' }))
    try {
      await fetchDispatcherInsight(username, true)
      setRowInsightLoading(s => ({ ...s, [username]: 'done' }))
      setTimeout(() => setRowInsightLoading(s => { const n = { ...s }; delete n[username]; return n }), 2000)
    } catch {
      setRowInsightLoading(s => { const n = { ...s }; delete n[username]; return n })
    }
  }

  useEffect(() => {
    if (!computing) return
    const iv = setInterval(async () => {
      try {
        const result = await fetchDispatchScore()
        setData(result)
        if (!result.status || result.status === 'ready') setComputing(false)
      } catch {}
    }, 3000)
    return () => clearInterval(iv)
  }, [computing])

  useEffect(() => { load() }, [])

  // Keep selected in sync when data refreshes — prevents stale detail panel
  useEffect(() => {
    if (!selected || !data?.dispatchers) return
    const fresh = data.dispatchers.find(d => d.username === selected.username)
    if (fresh && fresh !== selected) setSelected(fresh)
  }, [data])

  const handleSort = (key) => {
    if (sortCol === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortCol(key); setSortDir(key === 'name' ? 'asc' : 'desc') }
  }

  if (loading) return (
    <div className="glass rounded-xl border border-slate-700/50 h-48 flex items-center justify-center gap-3 text-slate-400">
      <Loader2 className="w-6 h-6 animate-spin" />
      <span className="text-sm">Loading dispatch scorecard…</span>
    </div>
  )

  if (error) return (
    <div className="glass rounded-xl border border-red-500/30 p-6 text-red-400 text-sm">{error}</div>
  )

  const dispatchers = data?.dispatchers || []
  const scored = dispatchers.filter(d => !d.observer)

  // Sort: rows with real data first (by chosen column), then loading/no-data rows at bottom
  const col = COLS.find(c => c.key === sortCol) || COLS[1]
  const sorted = [...scored].sort((a, b) => {
    const aLoading = a.total === null
    const bLoading = b.total === null
    const aNoData  = !aLoading && a.score === null
    const bNoData  = !bLoading && b.score === null
    // Push loading and no-data rows to the bottom always
    if (aLoading !== bLoading) return aLoading ? 1 : -1
    if (aNoData  !== bNoData)  return aNoData  ? 1 : -1
    const av = col.sortFn(a), bv = col.sortFn(b)
    if (av === bv) return 0
    // For response/arrival lower is better — natural asc sort shows best first when desc
    const mul = sortDir === 'asc' ? 1 : -1
    return av < bv ? -mul : mul
  })

  const active = scored.filter(d => d.score !== null && d.total !== null)

  return (
    <>
      {selected && <DispatchScoreDetail dispatcher={selected} onClose={() => setSelected(null)} />}

      <div className="space-y-4">
        {/* Header */}
        <div className="glass rounded-xl border border-slate-700/50 px-4 py-3 flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-slate-200">Dispatcher Scorecard</p>
            <p className="text-xs text-slate-500 mt-0.5">
              {computing
                ? <span className="flex items-center gap-1.5">
                    <Loader2 className="w-3 h-3 animate-spin inline" />
                    Computing scores — updating automatically…
                  </span>
                : <>Rolling 90 days · {active.length} scored · Generated {fmtTs(data?.generated_at)}</>
              }
            </p>
          </div>
          <button onClick={forceRefresh} disabled={refreshing || computing}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-slate-600/50 text-slate-300 hover:bg-slate-800/60 disabled:opacity-50 transition-all">
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing || computing ? 'animate-spin' : ''}`} />
            {refreshing ? 'Refreshing…' : computing ? 'Computing…' : 'Force Refresh'}
          </button>
        </div>

        {/* Tier legend */}
        <div className="flex flex-wrap gap-3 text-xs">
          {[['Elite', '85–100'], ['Proficient', '70–84'], ['Developing', '50–69'], ['Needs Support', '<50']].map(([tier, range]) => (
            <div key={tier} className={`px-2.5 py-1 rounded-full border ${TIER_STYLES[tier]}`}>
              <span className="font-semibold">{tier}</span>
              <span className="ml-1 opacity-70">{range}</span>
            </div>
          ))}
          <div className="ml-auto text-slate-500 self-center text-[11px]">
            Score = Completion (40) + Speed (25) + Reliability (20) + Volume (15) · PTA = on-time arrivals
          </div>
        </div>

        {/* Scoring guide */}
        <ScoringGuide />

        {/* Sortable table */}
        {sorted.length === 0 ? (
          <div className="glass rounded-xl border border-slate-700/50 py-12 text-center text-slate-600">
            No dispatcher data found
          </div>
        ) : (
          <div className="glass rounded-xl border border-slate-700/50 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-700/50 bg-slate-800/40">
                  {COLS.map(c => (
                    <th key={c.key}
                      onClick={() => handleSort(c.key)}
                      className={`px-4 py-2.5 text-[11px] font-semibold text-slate-400 uppercase tracking-wider cursor-pointer hover:text-slate-200 select-none whitespace-nowrap ${c.align === 'right' ? 'text-right' : 'text-left'}`}>
                      {c.label}
                      <SortIcon col={c.key} sortCol={sortCol} sortDir={sortDir} />
                    </th>
                  ))}
                  <th className="px-3 py-2.5 text-[11px] font-semibold text-slate-600 uppercase tracking-wider text-center w-10" title="Regenerate AI insight">AI</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/30">
                {sorted.map(d => {
                  const isLoading = d.total === null
                  const isNoData  = !isLoading && d.score === null

                  if (isLoading) return (
                    <tr key={d.username} className="opacity-50">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          <div className="w-9 h-9 rounded-full bg-slate-800 flex items-center justify-center shrink-0">
                            <Loader2 className="w-4 h-4 text-slate-600 animate-spin" />
                          </div>
                          <div>
                            <span className="text-slate-300 font-medium">{d.name}</span>
                            {d.channel && (
                              <span className="ml-2 px-1.5 py-0.5 rounded text-[9px] font-bold border bg-slate-700/30 text-slate-500 border-slate-700/40">
                                {d.channel}
                              </span>
                            )}
                            <div className="text-[10px] text-slate-600 mt-0.5 capitalize">{(d.role || '').replace('ers-', '')}</div>
                          </div>
                        </div>
                      </td>
                      {[1,2,3,4,5].map(i => (
                        <td key={i} className="px-4 py-3 text-right">
                          <div className="h-3 w-10 bg-slate-800/60 rounded ml-auto animate-pulse" />
                        </td>
                      ))}
                      <td className="px-3 py-3" />
                    </tr>
                  )

                  if (isNoData) return (
                    <tr key={d.username} className="opacity-40">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          <div className="w-9 h-9 rounded-full bg-slate-800 shrink-0" />
                          <div>
                            <span className="text-slate-400 font-medium">{d.name}</span>
                            {d.channel && (
                              <span className="ml-2 px-1.5 py-0.5 rounded text-[9px] font-bold border bg-slate-700/30 text-slate-500 border-slate-700/40">
                                {d.channel}
                              </span>
                            )}
                            <div className="text-[10px] text-slate-600 mt-0.5 capitalize">{(d.role || '').replace('ers-', '')} · No dispatches</div>
                          </div>
                        </div>
                      </td>
                      {[1,2,3,4,5].map(i => <td key={i} className="px-4 py-3 text-right text-slate-600">—</td>)}
                      <td className="px-3 py-3" />
                    </tr>
                  )

                  return (
                    <tr key={d.username}
                      onClick={() => setSelected(d)}
                      className="cursor-pointer hover:bg-slate-800/40 transition-colors group">
                      {/* Name + channel */}
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          <MiniRing score={d.score} tier={d.tier} />
                          <div>
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="text-slate-100 font-medium group-hover:text-white">{d.name}</span>
                              {d.channel && (
                                <span className="px-1.5 py-0.5 rounded text-[9px] font-bold border bg-slate-700/30 text-slate-400 border-slate-700/40">
                                  {d.channel}
                                </span>
                              )}
                            </div>
                            <div className="text-[10px] text-slate-500 mt-0.5 capitalize">{(d.role || '').replace('ers-', '')}</div>
                          </div>
                        </div>
                      </td>
                      {/* Score / Tier */}
                      <td className="px-4 py-3 text-right">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${TIER_STYLES[d.tier] || ''}`}>
                          {d.tier}
                        </span>
                      </td>
                      {/* Peer Rank */}
                      <td className="px-4 py-3 text-right text-xs text-slate-400">
                        {d.channel_rank != null && d.channel_size != null
                          ? <span>
                              <span className={d.channel_rank === 1 ? 'text-amber-400 font-semibold' : ''}>
                                #{d.channel_rank}
                              </span>
                              <span className="text-slate-600"> of {d.channel_size}</span>
                            </span>
                          : <span className="text-slate-700">—</span>}
                      </td>
                      {/* Fair Completion */}
                      <td className={`px-4 py-3 text-right font-mono text-xs font-semibold ${
                        d.adj_comp_pct >= 90 ? 'text-emerald-400' : d.adj_comp_pct >= 80 ? 'text-amber-400' : 'text-red-400'}`}>
                        {d.adj_comp_pct}%
                      </td>
                      {/* PTA Rate */}
                      <td className={`px-4 py-3 text-right font-mono text-xs font-semibold ${
                        d.pta_rate == null ? 'text-slate-600'
                          : d.pta_rate >= 80 ? 'text-emerald-400'
                          : d.pta_rate >= 65 ? 'text-amber-400' : 'text-red-400'}`}>
                        {d.pta_rate != null ? `${d.pta_rate}%` : '—'}
                      </td>
                      {/* Avg Response */}
                      <td className={`px-4 py-3 text-right font-mono text-xs font-semibold ${
                        d.median_rt_min <= 10 ? 'text-emerald-400' : d.median_rt_min <= 20 ? 'text-amber-400' : 'text-red-400'}`}>
                        {d.median_rt_min}m
                      </td>
                      {/* Per-row AI insight regenerate */}
                      <td className="px-3 py-3 text-center" onClick={e => e.stopPropagation()}>
                        {rowInsightLoading[d.username] === 'done' ? (
                          <Check className="w-3.5 h-3.5 text-emerald-400 mx-auto" />
                        ) : rowInsightLoading[d.username] === 'loading' ? (
                          <Loader2 className="w-3.5 h-3.5 text-purple-400 animate-spin mx-auto" />
                        ) : (
                          <button
                            onClick={e => regenerateInsight(e, d.username)}
                            title="Regenerate AI insight"
                            className="text-slate-700 hover:text-purple-400 transition-colors">
                            <Sparkles className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}
