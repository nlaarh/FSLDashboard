import { useEffect, useState } from 'react'
import { Loader2, RefreshCw, Target, ChevronDown, ChevronUp, HelpCircle } from 'lucide-react'
import { fetchDispatchScore, refreshDispatchScore } from '../api'
import DispatchScoreDetail from './DispatchScoreDetail'

const TIER_STYLES = {
  Elite:         'bg-amber-500/15 text-amber-300 border-amber-500/30',
  Proficient:    'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  Developing:    'bg-blue-500/15 text-blue-400 border-blue-500/30',
  'Needs Support': 'bg-red-500/15 text-red-400 border-red-500/30',
}

const TIER_BAR = {
  Elite:         'bg-amber-400',
  Proficient:    'bg-emerald-400',
  Developing:    'bg-blue-400',
  'Needs Support': 'bg-red-400',
}

function ScoreRing({ score, tier }) {
  const pct = Math.max(0, Math.min(100, score || 0))
  const barColor = TIER_BAR[tier] || 'bg-slate-500'
  return (
    <div className="flex flex-col items-center gap-1">
      <div className="relative w-14 h-14 flex items-center justify-center">
        <svg className="w-14 h-14 -rotate-90" viewBox="0 0 56 56">
          <circle cx="28" cy="28" r="24" fill="none" stroke="rgb(51,65,85)" strokeWidth="5" />
          <circle
            cx="28" cy="28" r="24" fill="none"
            className={`transition-all duration-700`}
            stroke={tier === 'Elite' ? '#fbbf24' : tier === 'Proficient' ? '#34d399' : tier === 'Developing' ? '#60a5fa' : '#f87171'}
            strokeWidth="5"
            strokeDasharray={`${(pct / 100) * 150.8} 150.8`}
            strokeLinecap="round"
          />
        </svg>
        <span className="absolute text-base font-bold text-slate-100">{score}</span>
      </div>
      <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold border ${TIER_STYLES[tier] || 'bg-slate-700/30 text-slate-400 border-slate-700/40'}`}>
        {tier}
      </span>
    </div>
  )
}

function StatMini({ label, value, tone = 'text-slate-200' }) {
  return (
    <div className="text-center">
      <div className={`text-sm font-bold ${tone}`}>{value}</div>
      <div className="text-[10px] text-slate-500 mt-0.5">{label}</div>
    </div>
  )
}

function DispatcherCard({ d, onClick }) {
  if (d.observer || d.score === null) {
    return (
      <div className="glass rounded-xl border border-slate-700/30 p-4 flex items-start gap-4 opacity-50">
        <div className="w-14 h-14 rounded-full bg-slate-800 flex items-center justify-center text-slate-600">
          <Target className="w-5 h-5" />
        </div>
        <div>
          <div className="text-sm font-semibold text-slate-400">{d.name}</div>
          <div className="text-[11px] text-slate-600 capitalize">{d.role.replace('ers-', '')} · No dispatches</div>
        </div>
      </div>
    )
  }

  return (
    <button
      onClick={() => onClick(d)}
      className="glass rounded-xl border border-slate-700/50 p-4 hover:border-slate-600 hover:bg-slate-800/40 transition-all text-left w-full group">
      <div className="flex items-start gap-4">
        <ScoreRing score={d.score} tier={d.tier} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-slate-100 group-hover:text-white">{d.name}</span>
            <span className="text-[10px] text-slate-500 capitalize">{d.role.replace('ers-', '')}</span>
            {d.channel && (
              <span className="px-1.5 py-0.5 rounded text-[9px] font-bold border bg-slate-700/30 text-slate-400 border-slate-700/40">
                {d.channel}
              </span>
            )}
          </div>
          <div className="grid grid-cols-4 gap-3 mt-3">
            <StatMini label="Dispatches" value={d.total.toLocaleString()} />
            <StatMini label="Fair Completion" value={`${d.adj_comp_pct}%`}
              tone={d.adj_comp_pct >= 90 ? 'text-emerald-400' : d.adj_comp_pct >= 80 ? 'text-amber-400' : 'text-red-400'} />
            <StatMini label="Typical Response" value={`${d.median_rt_min}m`}
              tone={d.median_rt_min <= 10 ? 'text-emerald-400' : d.median_rt_min <= 20 ? 'text-amber-400' : 'text-red-400'} />
            <StatMini
              label="Typical Arrival"
              value={d.median_arrival_min != null ? `${d.median_arrival_min}m` : '—'}
              tone={d.median_arrival_min == null ? 'text-slate-500' : d.median_arrival_min <= 30 ? 'text-emerald-400' : d.median_arrival_min <= 60 ? 'text-amber-400' : 'text-red-400'} />
          </div>
        </div>
        <div className="self-center text-slate-600 group-hover:text-slate-400 transition-colors text-xs">›</div>
      </div>
    </button>
  )
}

const fmtTs = (epoch) => epoch
  ? new Date(epoch * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
  : '—'

const SCORE_GUIDE = [
  {
    label: 'Completion Quality', max: 40, color: 'text-emerald-400',
    what: 'Did the drivers this dispatcher assigned actually complete the call?',
    how: 'Harder call types count more than easy ones — Winch Out is worth 2×, Tow Pick-Up 1.2×, Locksmith 1.3×, Tire 1.1×, Battery and Lockout 1.0×, Tow Drop-Off 0.8×. A dispatcher handling tough calls is not penalized for a lower raw number.',
    thresholds: '≥95% → 40 pts · ≥90% → 35 · ≥85% → 30 · ≥80% → 25 · ≥75% → 20 · ≥70% → 15 · ≥60% → 10 · <60% → 5',
    why: 'This is the highest-weighted area because completing the member\'s call is the job. Low score usually means driver selection — wrong skill level, wrong territory, or the wrong driver for a hard call.',
  },
  {
    label: 'Speed', max: 25, color: 'text-blue-400',
    what: 'Typical minutes from when a service call lands in the queue to when the dispatcher assigns a driver.',
    how: 'The clock starts when the call enters the queue and stops at the first driver assignment. Calls that waited over 2 hours are excluded — those are usually inherited from the previous shift and should not count against the dispatcher.',
    thresholds: '≤5 min → 25 pts · ≤10 min → 20 · ≤15 min → 15 · ≤20 min → 10 · ≤30 min → 5 · >30 min → 0',
    why: 'Measures how quickly the dispatcher moves calls from the queue to an assigned driver. Slow scores usually reflect monitoring habits — dispatchers who stay on Live Dispatch and the Watchlist respond faster.',
  },
  {
    label: 'Reliability', max: 20, color: 'text-amber-400',
    what: 'What percentage of calls took over 30 minutes to get a driver assigned?',
    how: 'Even if the average time looks fine, a high percentage here means many individual members waited a long time. A dispatcher can average 12 minutes but still have 35% of calls take over 30 minutes.',
    thresholds: '<10% late → 20 pts · <20% → 15 · <30% → 10 · <40% → 5 · ≥40% → 0',
    why: 'Catches shift-change spikes and specific time windows with poor coverage. A low score here alongside a decent average almost always points to a particular hour or situation causing the delays.',
  },
  {
    label: 'Volume', max: 15, color: 'text-purple-400',
    what: 'Total calls dispatched in the 90-day window.',
    how: 'With fewer calls, the other scores are less reliable. A dispatcher with 3 dispatches at 100% would score Elite, which would be misleading.',
    thresholds: '≥300 → 15 pts · ≥200 → 12 · ≥100 → 9 · ≥50 → 6 · ≥20 → 3 · <20 → 0',
    why: 'Volume is weighted lowest (15 pts) so full-time dispatchers are not unfairly compared to part-time. But it ensures the other three scores are based on enough data to be meaningful.',
  },
]

function ScoringGuide() {
  const [open, setOpen] = useState(false)
  return (
    <div className="glass rounded-xl border border-slate-700/40 overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 px-4 py-3 text-left hover:bg-slate-800/30 transition-colors">
        <HelpCircle className="w-3.5 h-3.5 text-slate-500 shrink-0" />
        <span className="text-xs font-medium text-slate-400">How is the score calculated?</span>
        {open
          ? <ChevronUp className="w-3.5 h-3.5 text-slate-500 ml-auto" />
          : <ChevronDown className="w-3.5 h-3.5 text-slate-500 ml-auto" />
        }
      </button>

      {open && (
        <div className="px-4 pb-4 space-y-4 border-t border-slate-700/40 pt-4">
          <p className="text-xs text-slate-400">
            Each dispatcher receives a score of <span className="text-slate-200 font-semibold">0–100</span> built
            from four dimensions. The score is based on a rolling 90-day window and refreshes monthly.
            Response times over 120 minutes are capped to protect against overnight shift-change backlog distorting results.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {SCORE_GUIDE.map(g => (
              <div key={g.label} className="bg-slate-800/40 rounded-lg border border-slate-700/30 p-3 space-y-2">
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
          <div className="bg-slate-800/30 rounded-lg border border-slate-700/30 p-3">
            <p className="text-[10px] text-slate-500 leading-relaxed">
              <span className="text-slate-400 font-semibold">Call difficulty factors: </span>
              Tow Drop-Off 0.8× · Battery 1.0× · Lockout 1.0× · Tire 1.1× · Tow Pick-Up 1.2× · Locksmith 1.3× · Winch Out 2.0× —
              A dispatcher whose queue is full of tow pick-ups and winch-outs should be compared on their fair completion rate, not a simple count.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

export default function DispatchScoreTab() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState(null)

  const load = async () => {
    setLoading(true)
    setError('')
    try { setData(await fetchDispatchScore()) }
    catch (e) { setError(e.response?.data?.detail || 'Failed to load scorecard') }
    finally { setLoading(false) }
  }

  const forceRefresh = async () => {
    setRefreshing(true)
    setError('')
    try { setData(await refreshDispatchScore()) }
    catch (e) { setError(e.response?.data?.detail || 'Refresh failed') }
    finally { setRefreshing(false) }
  }

  useEffect(() => { load() }, [])

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
  const active = dispatchers.filter(d => !d.observer && d.score !== null)

  const fleet     = dispatchers.filter(d => d.channel === 'Fleet' && !d.observer)
  const towbook   = dispatchers.filter(d => d.channel === 'Towbook' && !d.observer)
  const mixed     = dispatchers.filter(d => d.channel === 'Mixed' && !d.observer)
  const overnight = dispatchers.filter(d => d.channel === 'Overnight' && !d.observer)
  const supervisor = dispatchers.filter(d => d.channel === 'Supervisor')
  const observers  = dispatchers.filter(d => d.observer)

  const ChannelSection = ({ label, note, items }) => {
    if (!items.length) return null
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">{label}</p>
          {note && <p className="text-[10px] text-slate-600">{note}</p>}
        </div>
        {items.map(d => <DispatcherCard key={d.username} d={d} onClick={setSelected} />)}
      </div>
    )
  }

  return (
    <>
      {selected && (
        <DispatchScoreDetail
          dispatcher={selected}
          onClose={() => setSelected(null)}
        />
      )}

      <div className="space-y-4">
        {/* Header */}
        <div className="glass rounded-xl border border-slate-700/50 px-4 py-3 flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-slate-200">Dispatcher Scorecard</p>
            <p className="text-xs text-slate-500 mt-0.5">
              Rolling 90 days · {active.length} active dispatchers · Generated {fmtTs(data?.generated_at)}
            </p>
          </div>
          <button
            onClick={forceRefresh}
            disabled={refreshing}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-slate-600/50 text-slate-300 hover:bg-slate-800/60 disabled:opacity-50 transition-all">
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} />
            {refreshing ? 'Refreshing…' : 'Force Refresh'}
          </button>
        </div>

        {/* Score legend */}
        <div className="flex flex-wrap gap-3 text-xs">
          {[['Elite', '85–100'], ['Proficient', '70–84'], ['Developing', '50–69'], ['Needs Support', '<50']].map(([tier, range]) => (
            <div key={tier} className={`px-2.5 py-1 rounded-full border ${TIER_STYLES[tier]}`}>
              <span className="font-semibold">{tier}</span>
              <span className="ml-1 opacity-70">{range}</span>
            </div>
          ))}
          <div className="ml-auto text-slate-500 self-center">Score = Completion Quality (40) + Speed (25) + Reliability (20) + Volume (15)</div>
        </div>

        {/* Scoring guide */}
        <ScoringGuide />

        {/* Dispatcher cards — grouped by channel */}
        <div className="space-y-6">
          <ChannelSection label="Fleet" note="Pre-rostered AAA drivers · Battery, Tire, Lockout" items={fleet} />
          <ChannelSection label="Towbook" note="Independent contractors · Tow, Winch Out, Locksmith" items={towbook} />
          {mixed.length > 0 && <ChannelSection label="Mixed" items={mixed} />}
          {overnight.length > 0 && <ChannelSection label="Overnight" items={overnight} />}
          {supervisor.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Supervisor</p>
                <p className="text-[10px] text-slate-600">Specialist interventions — not compared to general dispatcher queue</p>
              </div>
              {supervisor.map(d => <DispatcherCard key={d.username} d={d} onClick={setSelected} />)}
            </div>
          )}
          {observers.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">No Dispatches</p>
              {observers.map(d => <DispatcherCard key={d.username} d={d} onClick={setSelected} />)}
            </div>
          )}
          {dispatchers.length === 0 && (
            <div className="glass rounded-xl border border-slate-700/50 py-12 text-center text-slate-600">
              No dispatcher data found
            </div>
          )}
        </div>
      </div>
    </>
  )
}
