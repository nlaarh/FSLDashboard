import { useState, useEffect, useCallback } from 'react'
import { Loader2, AlertTriangle, GitBranch, ChevronDown, ChevronUp, ArrowRight, Clock, XCircle, TrendingDown, HelpCircle, X } from 'lucide-react'
import { fetchMatrixHealth } from '../api'

const PERIODS = [
  { key: '2026-01', label: 'January' },
  { key: '2026-02', label: 'February' },
  { key: 'mtd', label: 'This Month' },
  { key: 'ytd', label: 'YTD' },
]

export default function MatrixAdvisor() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [period, setPeriod] = useState('2026-02')
  const [tab, setTab] = useState('cascade')
  const [expandedZone, setExpandedZone] = useState(null)
  const [expandedGarage, setExpandedGarage] = useState(null)
  const [showHelp, setShowHelp] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const d = await fetchMatrixHealth(period)
      setData(d)
    } catch (e) {
      setError('Failed to load matrix data')
    } finally {
      setLoading(false)
    }
  }, [period])

  useEffect(() => { load() }, [load])

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="w-8 h-8 animate-spin text-brand-400" />
      </div>
    )
  }

  if (error && !data) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <AlertTriangle className="w-8 h-8 text-amber-400 mx-auto mb-3" />
          <p className="text-slate-400">{error}</p>
          <button onClick={load} className="mt-3 px-4 py-2 bg-brand-600 rounded-lg text-sm">Retry</button>
        </div>
      </div>
    )
  }

  const summary = data?.summary || {}
  const zones = data?.zones || []
  const garages = data?.garages || []
  const recommendations = data?.recommendations || []
  const cascadeDepth = data?.cascade_depth || []

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-brand-600/20 flex items-center justify-center">
            <GitBranch className="w-5 h-5 text-brand-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white">Matrix Advisor</h1>
            <p className="text-xs text-slate-500">
              Priority matrix cascade analysis — are calls going to the right garages?
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {loading && <Loader2 className="w-4 h-4 animate-spin text-brand-400" />}
          <button onClick={() => setShowHelp(!showHelp)}
            className={`p-1.5 rounded-lg transition-colors ${showHelp ? 'text-brand-400 bg-brand-600/20' : 'text-slate-600 hover:text-slate-400'}`}
            title="How it Works">
            <HelpCircle className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Period selector */}
      <div className="flex items-center gap-2">
        <div className="flex items-center bg-slate-800/50 rounded-lg p-0.5">
          {PERIODS.map(p => (
            <button key={p.key} onClick={() => setPeriod(p.key)}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                period === p.key ? 'bg-brand-600/20 text-brand-300' : 'text-slate-500 hover:text-white'
              }`}>
              {p.label}
            </button>
          ))}
        </div>
        {data?.computed_at && (
          <span className="text-[10px] text-slate-600 ml-auto">
            Computed {new Date(data.computed_at).toLocaleTimeString()}
          </span>
        )}
      </div>

      {/* How it Works */}
      {showHelp && <HowItWorks onClose={() => setShowHelp(false)} />}

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <SummaryCard label="Total Calls" value={summary.total_calls?.toLocaleString()} />
        <SummaryCard label="Total Declined" value={summary.total_declined?.toLocaleString()}
          color={summary.total_declined > 1000 ? 'text-red-400' : 'text-amber-400'} />
        <SummaryCard label="Could Not Wait" value={summary.total_cnw?.toLocaleString()}
          color={summary.total_cnw > 500 ? 'text-red-400' : 'text-amber-400'} />
        <SummaryCard label="Garages" value={summary.garages_analyzed} />
        <SummaryCard label="Recommendations" value={summary.recommendations_count}
          color={summary.recommendations_count > 0 ? 'text-amber-400' : 'text-emerald-400'} />
      </div>

      {/* Cascade depth distribution bar */}
      {cascadeDepth.length > 0 && (
        <div className="glass rounded-xl p-3">
          <h3 className="text-[10px] text-slate-500 uppercase tracking-wider mb-2">Cascade Depth Distribution</h3>
          <div className="flex items-end gap-1 h-12">
            {cascadeDepth.filter(d => d.rank <= 8).map(d => {
              const maxCount = Math.max(...cascadeDepth.map(x => x.count))
              const pct = d.count / maxCount
              return (
                <div key={d.rank} className="flex-1 flex flex-col items-center gap-0.5 group relative">
                  <div className="w-full rounded-t" style={{
                    height: `${Math.max(pct * 48, 2)}px`,
                    backgroundColor: d.rank <= 2 ? 'rgb(99 102 241 / 0.5)' : d.rank <= 4 ? 'rgb(245 158 11 / 0.4)' : 'rgb(239 68 68 / 0.4)',
                  }} />
                  <span className="text-[8px] text-slate-600">{d.rank === 2 ? 'Primary' : `R${d.rank}`}</span>
                  <div className="absolute -top-6 left-1/2 -translate-x-1/2 bg-slate-800 text-[9px] text-white px-1.5 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap z-10">
                    Rank {d.rank}: {d.count.toLocaleString()} SAs
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-slate-800/50 pb-0.5">
        {[
          ['cascade', 'Zone Health', zones.length],
          ['garages', 'Garage Performance', garages.length],
          ['recommendations', 'Recommendations', recommendations.length],
        ].map(([key, label, count]) => (
          <button key={key} onClick={() => setTab(key)}
            className={`px-4 py-2 text-xs font-medium transition-colors rounded-t-lg ${
              tab === key ? 'bg-slate-800/50 text-white border-b-2 border-brand-400' : 'text-slate-500 hover:text-white'
            }`}>
            {label} {count > 0 && <span className="text-slate-600 ml-1">({count})</span>}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === 'cascade' && <CascadeTab zones={zones} expandedZone={expandedZone} setExpandedZone={setExpandedZone} />}
      {tab === 'garages' && <GaragesTab garages={garages} expandedGarage={expandedGarage} setExpandedGarage={setExpandedGarage} />}
      {tab === 'recommendations' && <RecommendationsTab recommendations={recommendations} />}
    </div>
  )
}


function SummaryCard({ label, value, color = 'text-white' }) {
  return (
    <div className="glass rounded-xl p-3">
      <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">{label}</div>
      <div className={`text-lg font-bold ${color}`}>{value ?? '—'}</div>
    </div>
  )
}


function CascadeTab({ zones, expandedZone, setExpandedZone }) {
  const [sortBy, setSortBy] = useState('cascade')

  const sorted = [...zones].sort((a, b) => {
    if (sortBy === 'cascade') return b.cascade_pct - a.cascade_pct
    if (sortBy === 'volume') return b.primary_volume - a.primary_volume
    if (sortBy === 'accept') return (a.primary_accept_pct ?? 999) - (b.primary_accept_pct ?? 999)
    if (sortBy === 'cnw') return b.cnw - a.cnw
    return 0
  })

  if (!zones.length) return <div className="text-center text-slate-600 py-12">No zone data for this period</div>

  return (
    <div className="space-y-2">
      {/* Sort controls */}
      <div className="flex items-center gap-1.5 mb-1">
        <span className="text-[10px] text-slate-600 uppercase">Sort:</span>
        {[['cascade', 'Decline %'], ['volume', 'Volume'], ['cnw', 'CNW'], ['accept', 'Accept %']].map(([key, label]) => (
          <button key={key} onClick={() => setSortBy(key)}
            className={`px-2 py-1 rounded text-[11px] font-medium transition-colors ${
              sortBy === key ? 'bg-slate-700 text-white' : 'text-slate-500 hover:text-white'
            }`}>{label}</button>
        ))}
      </div>

      {/* Header row */}
      <div className="grid grid-cols-12 gap-2 px-4 py-2 text-[10px] text-slate-600 uppercase tracking-wider">
        <div className="col-span-2">Zone</div>
        <div className="col-span-3">Primary Garage</div>
        <div className="col-span-1 text-right">Accept %</div>
        <div className="col-span-1 text-right">Volume</div>
        <div className="col-span-1 text-right">Declined</div>
        <div className="col-span-1 text-right">Decline %</div>
        <div className="col-span-1 text-right">Delay</div>
        <div className="col-span-1 text-right">CNW</div>
        <div className="col-span-1"></div>
      </div>

      {sorted.map(z => {
        const expanded = expandedZone === z.zone
        const acceptColor = z.primary_accept_pct == null ? 'text-slate-600' :
          z.primary_accept_pct >= 80 ? 'text-emerald-400' :
          z.primary_accept_pct >= 60 ? 'text-amber-400' : 'text-red-400'

        return (
          <div key={z.zone} className={`glass rounded-xl overflow-hidden ${z.cascade_pct > 10 ? 'border border-amber-500/20' : ''}`}>
            <button onClick={() => setExpandedZone(expanded ? null : z.zone)}
              className="w-full grid grid-cols-12 gap-2 px-4 py-3 text-left hover:bg-slate-800/30 transition-colors items-center">
              <div className="col-span-2 text-sm font-medium text-white truncate">{z.zone}</div>
              <div className="col-span-3 text-xs text-slate-400 truncate">{z.primary_garage}</div>
              <div className={`col-span-1 text-right text-xs font-bold ${acceptColor}`}>
                {z.primary_accept_pct != null ? `${z.primary_accept_pct}%` : '—'}
              </div>
              <div className="col-span-1 text-right text-xs text-slate-400">{z.primary_volume?.toLocaleString()}</div>
              <div className="col-span-1 text-right text-xs text-slate-400">{z.primary_declined}</div>
              <div className={`col-span-1 text-right text-xs font-bold ${
                z.cascade_pct > 10 ? 'text-red-400' : z.cascade_pct > 5 ? 'text-amber-400' : 'text-slate-400'
              }`}>{z.cascade_pct}%</div>
              <div className="col-span-1 text-right text-xs text-slate-500">
                {z.cascade_delay_min != null ? `${z.cascade_delay_min}m` : '—'}
              </div>
              <div className={`col-span-1 text-right text-xs ${z.cnw > 10 ? 'text-red-400 font-bold' : 'text-slate-500'}`}>
                {z.cnw}
              </div>
              <div className="col-span-1 text-right text-slate-600">
                {expanded ? <ChevronUp className="w-3.5 h-3.5 inline" /> : <ChevronDown className="w-3.5 h-3.5 inline" />}
              </div>
            </button>

            {expanded && z.chain && (
              <div className="px-4 pb-4 border-t border-slate-800/50 pt-3">
                <h4 className="text-xs font-semibold text-slate-400 mb-2">Priority Matrix Chain</h4>
                <div className="space-y-1.5">
                  {z.chain.map((c, i) => (
                    <div key={i} className="flex items-center gap-3 text-xs">
                      <span className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold ${
                        i === 0 ? 'bg-brand-600/20 text-brand-400' : 'bg-slate-800 text-slate-500'
                      }`}>{Math.round(c.rank)}</span>
                      <span className="text-slate-300 flex-1 truncate">{c.garage}</span>
                      <span className={`font-medium ${
                        c.accept_pct == null ? 'text-slate-600' :
                        c.accept_pct >= 80 ? 'text-emerald-400' :
                        c.accept_pct >= 60 ? 'text-amber-400' : 'text-red-400'
                      }`}>{c.accept_pct != null ? `${c.accept_pct}% accept` : 'no data'}</span>
                      <span className="text-slate-600">{c.total.toLocaleString()} calls</span>
                      {c.declined > 0 && <span className="text-red-400/70">{c.declined} declined</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}


function GaragesTab({ garages, expandedGarage, setExpandedGarage }) {
  const [sortBy, setSortBy] = useState('total')

  const sorted = [...garages].sort((a, b) => {
    if (sortBy === 'total') return b.total - a.total
    if (sortBy === 'accept') return (a.accept_pct ?? 999) - (b.accept_pct ?? 999)
    if (sortBy === 'cnw') return b.cnw - a.cnw
    if (sortBy === 'declined') return b.declined - a.declined
    return 0
  })

  return (
    <div className="space-y-2">
      {/* Sort controls */}
      <div className="flex items-center gap-1.5 mb-1">
        <span className="text-[10px] text-slate-600 uppercase">Sort:</span>
        {[['total', 'Volume'], ['declined', 'Declines'], ['cnw', 'CNW'], ['accept', 'Accept %']].map(([key, label]) => (
          <button key={key} onClick={() => setSortBy(key)}
            className={`px-2 py-1 rounded text-[11px] font-medium transition-colors ${
              sortBy === key ? 'bg-slate-700 text-white' : 'text-slate-500 hover:text-white'
            }`}>{label}</button>
        ))}
      </div>

      {sorted.map(g => {
        const expanded = expandedGarage === g.name
        const acceptColor = g.accept_pct == null ? 'text-slate-600' :
          g.accept_pct >= 80 ? 'text-emerald-400' :
          g.accept_pct >= 60 ? 'text-amber-400' : 'text-red-400'

        return (
          <div key={g.name} className="glass rounded-xl overflow-hidden">
            <button onClick={() => setExpandedGarage(expanded ? null : g.name)}
              className="w-full px-4 py-3 flex items-center gap-4 text-left hover:bg-slate-800/30 transition-colors">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-white truncate">{g.name}</span>
                  <span className={`text-[9px] px-1.5 py-0.5 rounded font-medium ${
                    g.dispatch_method === 'Field Services'
                      ? 'bg-brand-500/10 text-brand-400 border border-brand-500/20'
                      : 'bg-slate-700/50 text-slate-500'
                  }`}>{g.dispatch_method === 'Field Services' ? 'Fleet' : 'Contractor'}</span>
                </div>
                <div className="text-[10px] text-slate-500 flex items-center gap-3 mt-0.5">
                  <span>{g.total.toLocaleString()} calls</span>
                  <span>{g.completion_pct}% completed</span>
                  {g.avg_pta && <span>PTA {g.avg_pta}m</span>}
                </div>
              </div>
              <div className="flex items-center gap-3">
                <div className="text-right">
                  <div className={`text-xs font-bold ${acceptColor}`}>
                    {g.accept_pct != null ? `${g.accept_pct}%` : '—'}
                  </div>
                  <div className="text-[9px] text-slate-600">accept</div>
                </div>
                <div className="text-right">
                  <div className={`text-xs font-bold ${g.decline_pct > 5 ? 'text-red-400' : 'text-slate-400'}`}>
                    {g.declined} <span className="text-[9px] text-slate-600">({g.decline_pct}%)</span>
                  </div>
                  <div className="text-[9px] text-slate-600">declined</div>
                </div>
                <div className="text-right">
                  <div className={`text-xs font-bold ${g.cnw_pct > 5 ? 'text-red-400' : 'text-slate-400'}`}>
                    {g.cnw} <span className="text-[9px] text-slate-600">({g.cnw_pct}%)</span>
                  </div>
                  <div className="text-[9px] text-slate-600">CNW</div>
                </div>
                {g.satisfaction_pct != null && (
                  <div className="text-right">
                    <div className={`text-xs font-bold ${
                      g.satisfaction_pct >= 82 ? 'text-emerald-400' :
                      g.satisfaction_pct >= 70 ? 'text-amber-400' : 'text-red-400'
                    }`}>
                      {g.satisfaction_pct}%
                    </div>
                    <div className="text-[9px] text-slate-600">CSAT</div>
                  </div>
                )}
                <div className="text-slate-600">
                  {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                </div>
              </div>
            </button>

            {expanded && (
              <div className="px-4 pb-4 border-t border-slate-800/50 pt-3 space-y-4">
                {/* Decline reasons */}
                {g.top_decline_reasons?.length > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold text-slate-400 mb-2">Top Decline Reasons</h4>
                    <div className="space-y-1.5">
                      {g.top_decline_reasons.map((d, i) => {
                        const pct = g.declined > 0 ? Math.round(100 * d.count / g.declined) : 0
                        return (
                          <div key={i} className="flex items-center gap-2 text-xs">
                            <div className="flex-1">
                              <div className="flex items-center justify-between mb-0.5">
                                <span className="text-slate-300">{d.reason}</span>
                                <span className="text-slate-500">{d.count} ({pct}%)</span>
                              </div>
                              <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
                                <div className="h-full bg-red-500/40 rounded-full" style={{ width: `${pct}%` }} />
                              </div>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}

                {/* Cancellation reasons */}
                {g.top_cancel_reasons?.length > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold text-slate-400 mb-2">Top Cancellation Reasons</h4>
                    <div className="space-y-1">
                      {g.top_cancel_reasons.map((c, i) => (
                        <div key={i} className="flex items-center justify-between text-xs">
                          <span className="text-slate-400">{c.reason}</span>
                          <span className="text-slate-500">{c.count}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Hourly decline heatmap */}
                {g.hourly_declines && g.hourly_declines.some(v => v > 0) && (
                  <div>
                    <h4 className="text-xs font-semibold text-slate-400 mb-2">Decline Pattern by Hour</h4>
                    <div className="flex gap-0.5">
                      {g.hourly_declines.map((v, h) => {
                        const max = Math.max(...g.hourly_declines, 1)
                        const intensity = v / max
                        return (
                          <div key={h} className="flex-1 group relative">
                            <div className="h-8 rounded-sm" style={{
                              backgroundColor: v === 0 ? 'rgb(30 41 59 / 0.5)' :
                                `rgba(239, 68, 68, ${0.15 + intensity * 0.6})`
                            }} />
                            <div className="text-[8px] text-slate-600 text-center mt-0.5">
                              {h % 3 === 0 ? `${h}` : ''}
                            </div>
                            {v > 0 && (
                              <div className="absolute -top-6 left-1/2 -translate-x-1/2 bg-slate-800 text-[9px] text-white px-1 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap z-10">
                                {h}:00 — {v} declines
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                    <div className="flex justify-between text-[8px] text-slate-600 mt-0.5">
                      <span>12 AM</span>
                      <span>6 AM</span>
                      <span>12 PM</span>
                      <span>6 PM</span>
                      <span>12 AM</span>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}


function HowItWorks({ onClose }) {
  const Section = ({ title, children }) => (
    <div className="mb-4 last:mb-0">
      <h3 className="text-sm font-semibold text-brand-400 mb-1.5">{title}</h3>
      <div className="text-xs text-slate-400 space-y-1.5 leading-relaxed">{children}</div>
    </div>
  )

  return (
    <div className="glass rounded-xl border border-brand-500/20 p-5 relative">
      <button onClick={onClose} className="absolute top-3 right-3 text-slate-600 hover:text-white">
        <X className="w-4 h-4" />
      </button>
      <h2 className="text-base font-bold text-white mb-4">How Matrix Advisor Works</h2>

      <Section title="Purpose">
        <p>The Priority Matrix defines which garage gets called first for each dispatch zone.
          When the primary garage declines, the call cascades down the chain. Each cascade step
          adds ~8 minutes of delay for the member waiting on the road.</p>
        <p>Matrix Advisor analyzes this cascade pattern to find zones where the wrong garage
          is ranked first — causing unnecessary delays and "Could Not Wait" cancellations.</p>
      </Section>

      <Section title="Decisions You Can Make">
        <p><span className="text-white font-medium">1. Identify underperforming primaries</span> — Which garages
          frequently decline calls when they're the first option? A high decline rate means
          members wait longer while the call cascades.</p>
        <p><span className="text-white font-medium">2. Swap priority rankings</span> — If the Rank 3 garage has
          a 95% accept rate and the primary has 60%, swapping them could eliminate hundreds
          of cascade steps per month.</p>
        <p><span className="text-white font-medium">3. Spot decline patterns</span> — The hourly heatmap shows
          WHEN garages decline most. End-of-shift declines (5-6 PM) suggest capacity issues.
          Morning declines may signal staffing gaps.</p>
        <p><span className="text-white font-medium">4. Track CNW correlation</span> — "Could Not Wait" cancellations
          are members who gave up. High CNW in a zone directly correlates with cascade depth.
          Fixing the cascade fixes the CNW.</p>
      </Section>

      <div className="border-t border-slate-800/50 pt-4 mt-4">
        <Section title="Zone Health Tab">
          <p>Shows each dispatch zone with its primary garage and priority chain.
            <span className="text-white"> Decline %</span> = primary garage's decline count / total volume.
            Click any zone to expand and see the full cascade chain with per-garage accept rates.</p>
        </Section>

        <Section title="Garage Performance Tab">
          <p>Ranks all garages by volume, declines, or CNW. Expand any garage to see:</p>
          <p><span className="text-slate-300">Decline Reasons:</span> Why they declined (End of Shift, Meal Break, etc.) with proportional bars.</p>
          <p><span className="text-slate-300">Cancellation Reasons:</span> Top member cancellation types.</p>
          <p><span className="text-slate-300">Hourly Heatmap:</span> When declines happen by hour — darker red = more declines at that hour.</p>
        </Section>

        <Section title="Recommendations Tab">
          <p>Auto-generated when a primary garage's accept rate drops below 75% and a better
            alternative exists in the same zone chain (10%+ higher accept rate, 10+ calls minimum).</p>
          <p><span className="text-slate-300">Impact metrics:</span></p>
          <p><span className="text-white">Cascades Avoided</span> = calls that would no longer need to cascade if the swap is made.</p>
          <p><span className="text-white">Time Saved</span> = cascades avoided x 8 min per cascade step.</p>
          <p><span className="text-white">CNW Avoided</span> = estimated cancellations prevented (based on zone's CNW rate).</p>
        </Section>

        <Section title="How Calculations Work">
          <p><span className="text-slate-300">Primary Garage:</span> The first real garage in the priority matrix chain
            (skipping placeholders like "LS - LOCKSMITH REQUIRED" or "000-" entries).</p>
          <p><span className="text-slate-300">Accept Rate:</span> Primary accepted calls / (primary accepted + total declines).
            Uses ERS_Spotting_Number__c to identify primary accepts — when the spotting number matches the
            garage's rank in the zone chain, they accepted as primary.</p>
          <p><span className="text-slate-300">Data Source:</span> 5 parallel Salesforce queries: all SAs for the period,
            decline reasons (aggregate), cancellation reasons (aggregate), priority matrix configuration,
            and hourly decline pattern (aggregate).</p>
          <p><span className="text-slate-300">Caching:</span> Past months are cached for 24 hours (data is immutable).
            Current month is refreshed every 15 minutes.</p>
        </Section>
      </div>
    </div>
  )
}


function RecommendationsTab({ recommendations }) {
  if (!recommendations.length) {
    return (
      <div className="text-center py-12">
        <div className="text-slate-600 text-sm">No recommendations for this period</div>
        <p className="text-[10px] text-slate-700 mt-1">All primary garages accepting above 75% threshold</p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {recommendations.map((r, i) => (
        <div key={i} className="glass rounded-xl border border-amber-500/20 p-4">
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 rounded-lg bg-amber-500/10 flex items-center justify-center flex-shrink-0">
              <span className="text-sm font-bold text-amber-400">#{i + 1}</span>
            </div>
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-sm font-semibold text-white">Swap Primary in {r.zone}</span>
                <span className={`text-[9px] px-1.5 py-0.5 rounded font-medium ${
                  r.confidence === 'high'
                    ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                    : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                }`}>{r.confidence === 'high' ? 'High Confidence' : 'Medium'}</span>
              </div>

              <div className="flex items-center gap-2 text-xs text-slate-400 mb-3 flex-wrap">
                <span className="text-red-400">{r.current_primary}</span>
                <span className="text-slate-600">({r.current_accept_pct}% accept{r.current_satisfaction != null ? `, ${r.current_satisfaction}% CSAT` : ''})</span>
                <ArrowRight className="w-3 h-3 text-slate-600" />
                <span className="text-emerald-400">{r.suggested_primary}</span>
                <span className="text-slate-600">({r.suggested_accept_pct}% accept{r.suggested_satisfaction != null ? `, ${r.suggested_satisfaction}% CSAT` : ''})</span>
                {r.suggested_satisfaction != null && r.current_satisfaction != null && r.suggested_satisfaction < r.current_satisfaction && (
                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">
                    Lower CSAT
                  </span>
                )}
              </div>

              {/* Impact cards */}
              <div className="grid grid-cols-3 gap-3">
                <div className="bg-slate-800/50 rounded-lg p-2.5">
                  <div className="flex items-center gap-1.5 mb-1">
                    <Clock className="w-3 h-3 text-brand-400" />
                    <span className="text-[9px] text-slate-500 uppercase">Time Saved</span>
                  </div>
                  <div className="text-base font-bold text-white">
                    {r.impact.minutes_saved.toLocaleString()} <span className="text-xs text-slate-500">min</span>
                  </div>
                  <div className="text-[9px] text-slate-600">per period</div>
                </div>
                <div className="bg-slate-800/50 rounded-lg p-2.5">
                  <div className="flex items-center gap-1.5 mb-1">
                    <XCircle className="w-3 h-3 text-red-400" />
                    <span className="text-[9px] text-slate-500 uppercase">CNW Avoided</span>
                  </div>
                  <div className="text-base font-bold text-white">
                    {r.impact.cnw_avoided}
                  </div>
                  <div className="text-[9px] text-slate-600">cancellations</div>
                </div>
                <div className="bg-slate-800/50 rounded-lg p-2.5">
                  <div className="flex items-center gap-1.5 mb-1">
                    <TrendingDown className="w-3 h-3 text-emerald-400" />
                    <span className="text-[9px] text-slate-500 uppercase">Cascades Avoided</span>
                  </div>
                  <div className="text-base font-bold text-white">
                    {r.impact.cascades_avoided}
                  </div>
                  <div className="text-[9px] text-slate-600">{r.impact.primary_volume?.toLocaleString()} calls in zone</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
