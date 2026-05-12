import { useState, useRef } from 'react'
import { X, Sparkles, Loader2, ChevronRight, AlertCircle, Printer, Mail, AlertTriangle, HelpCircle } from 'lucide-react'
import { fetchDispatcherInsight } from '../api'

const TIER_COLOR = {
  Elite:           'text-amber-300',
  Proficient:      'text-emerald-400',
  Developing:      'text-blue-400',
  'Needs Support': 'text-red-400',
}

const TIER_BG = {
  Elite:           'bg-amber-500/10 border-amber-500/20',
  Proficient:      'bg-emerald-500/10 border-emerald-500/20',
  Developing:      'bg-blue-500/10 border-blue-500/20',
  'Needs Support': 'bg-red-500/10 border-red-500/20',
}

function ScoreBar({ label, value, max, color = 'bg-brand-500' }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-slate-400">{label}</span>
        <span className="text-xs font-semibold text-slate-200">{value}/{max}</span>
      </div>
      <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-700 ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

const METRIC_HELP = [
  {
    label: 'Score (0–100)',
    color: 'text-slate-200',
    def: 'Overall score built from four areas: Completion Quality (40 pts) + Speed (25 pts) + Reliability (20 pts) + Volume (15 pts). Tiers: Elite 85+, Proficient 70–84, Developing 50–69, Needs Support under 50.',
    use: 'Use to rank dispatchers and set coaching priorities. Click into the four bars below the score to see which area is pulling the number down.',
  },
  {
    label: 'Completion Quality (40 pts)',
    color: 'text-emerald-400',
    def: 'Did the drivers this dispatcher assigned actually complete the call? Harder call types count more than easy ones — a tow pick-up or winch-out is worth more than a battery call. This way a dispatcher handling tough calls is not unfairly compared to one handling easy ones.',
    use: 'Low here almost always means driver selection — wrong skill, wrong territory, or a lower-tier driver sent on a complex call. Look at the Call Type Mix to see what types are in the queue.',
  },
  {
    label: 'Speed (25 pts)',
    color: 'text-blue-400',
    def: 'Typical minutes from when a service call lands in the queue to when the dispatcher assigns a driver. Calls that waited over 2 hours are excluded — those are usually calls inherited from the previous shift and are not fair to count.',
    use: 'If this score is low, the dispatcher is slow to pick up new calls. Coach on checking the queue more frequently and staying on top of FSLPulse Live Dispatch.',
  },
  {
    label: 'Reliability (20 pts)',
    color: 'text-amber-400',
    def: 'What percentage of calls took over 30 minutes to get a driver? A dispatcher can have a decent average and still leave many members waiting a long time because of specific spikes.',
    use: 'High percentage here with an acceptable average usually points to a specific time window — shift change, busy hours, or certain call types. Look at the Response Time chart to spot the pattern.',
  },
  {
    label: 'Volume (15 pts)',
    color: 'text-purple-400',
    def: 'Total calls dispatched in the last 90 days. With fewer than 20 calls, the other scores are not reliable enough to act on.',
    use: 'Low volume means interpret the other scores cautiously. This applies to supervisors and part-time dispatchers. Volume is weighted lowest so full-time dispatchers are not penalized against part-time.',
  },
  {
    label: 'Completion Rate',
    color: 'text-slate-300',
    def: 'Simple percentage of assigned calls that were completed — no adjustments for call difficulty.',
    use: 'Compare to Fair Completion Rate below. A big gap between the two means this dispatcher handles many hard calls and should be recognized for it.',
  },
  {
    label: 'Fair Completion Rate',
    color: 'text-slate-300',
    def: 'Completion rate where harder calls count more than easy ones — tow pick-ups and winch-outs are worth more than lockouts or battery calls. This is the most accurate way to compare dispatchers with different call mixes.',
    use: 'This is the number that matters most for outcome coaching. Under 80% is a concern regardless of what types of calls this dispatcher handles.',
  },
  {
    label: 'Typical Response Time',
    color: 'text-slate-300',
    def: 'The midpoint speed — half of all assignments happened faster, half took longer. Calls over 2 hours are excluded to avoid overnight backlog distorting the number.',
    use: 'The single best speed indicator. Above 20 minutes means the dispatcher is routinely slow to assign drivers, not just occasionally.',
  },
  {
    label: 'Late Assignments',
    color: 'text-slate-300',
    def: 'Percentage of calls where it took more than 30 minutes to assign a driver.',
    use: 'Catches patterns that the average misses. High Late Assignments with a decent Typical Response Time = specific hours or situations causing delays. Use FSLPulse Dispatch Trends to find when.',
  },
  {
    label: 'Typical Arrival',
    color: 'text-slate-300',
    def: 'Median time from driver assignment to the driver arriving On Location. This is what the member actually experiences — how long they wait after being told a driver is on the way. Calls over 4 hours are excluded.',
    use: 'The most direct signal of driver selection quality. A dispatcher who assigns quickly but picks a driver 90 minutes away still creates a bad experience. Compare within the same channel (Fleet vs Towbook) — contractor travel inherently takes longer.',
  },
  {
    label: 'Late Arrivals',
    color: 'text-slate-300',
    def: 'Percentage of assignments where the driver took over 60 minutes to arrive after being assigned.',
    use: 'High late arrivals with a reasonable Typical Arrival = specific calls or times where driver selection went wrong. Look at the call type mix for clues — complex calls with under-qualified or distant drivers drive this number up.',
  },
]

function MetricHelpPanel({ onClose }) {
  return (
    <div className="mx-6 mt-0 mb-2 rounded-xl border border-slate-700/50 bg-slate-900/80 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-700/40">
        <span className="text-xs font-semibold text-slate-300">Score Definitions &amp; How to Use</span>
        <button onClick={onClose} className="text-slate-500 hover:text-slate-300 transition-colors">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
      <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-3">
        {METRIC_HELP.map(m => (
          <div key={m.label} className="bg-slate-800/40 rounded-lg border border-slate-700/30 p-3 space-y-1.5">
            <span className={`text-[11px] font-bold ${m.color}`}>{m.label}</span>
            <p className="text-[10px] text-slate-400 leading-relaxed"><span className="text-slate-500 font-semibold">What: </span>{m.def}</p>
            <p className="text-[10px] text-slate-500 leading-relaxed"><span className="text-slate-600 font-semibold">Use: </span>{m.use}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

function BarChart({ buckets }) {
  const labels = ['≤5m', '5–15m', '15–30m', '30–60m', '60–120m']
  const keys   = ['le5', '5_15', '15_30', '30_60', '60_120']
  const values = keys.map(k => buckets[k] || 0)
  const maxVal = Math.max(...values, 1)
  const colors = ['bg-emerald-500', 'bg-emerald-400', 'bg-amber-400', 'bg-orange-500', 'bg-red-500']

  return (
    <div className="space-y-1.5">
      {labels.map((label, i) => (
        <div key={label} className="flex items-center gap-2">
          <span className="text-[10px] text-slate-500 w-12 text-right shrink-0">{label}</span>
          <div className="flex-1 h-4 bg-slate-800/60 rounded overflow-hidden">
            <div
              className={`h-full rounded transition-all duration-500 ${colors[i]}`}
              style={{ width: `${(values[i] / maxVal) * 100}%` }}
            />
          </div>
          <span className="text-[10px] text-slate-400 w-8 shrink-0">{values[i]}</span>
        </div>
      ))}
    </div>
  )
}

function CallTypePie({ callTypes, total }) {
  const colors = ['bg-brand-500', 'bg-emerald-500', 'bg-amber-500', 'bg-blue-500', 'bg-purple-500', 'bg-rose-500', 'bg-teal-500']
  const top = callTypes.slice(0, 7)

  return (
    <div className="space-y-1.5">
      {top.map((ct, i) => (
        <div key={ct.type} className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full shrink-0 ${colors[i % colors.length]}`} />
          <span className="text-[11px] text-slate-300 flex-1 truncate">{ct.type}</span>
          <div className="w-20 h-2 bg-slate-800 rounded-full overflow-hidden">
            <div className={`h-full rounded-full ${colors[i % colors.length]}`} style={{ width: `${ct.pct}%` }} />
          </div>
          <span className="text-[10px] text-slate-400 w-8 text-right">{ct.pct}%</span>
        </div>
      ))}
    </div>
  )
}

function InsightSection({ title, items, tone = 'text-slate-300', dot = 'bg-slate-500' }) {
  if (!items || items.length === 0) return null
  return (
    <div>
      <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">{title}</p>
      <div className="space-y-2">
        {items.map((item, i) => (
          <div key={i} className="flex gap-2">
            <div className={`w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 ${dot}`} />
            <div>
              {item.title && <span className={`text-xs font-semibold ${tone}`}>{item.title} — </span>}
              <span className="text-xs text-slate-400">{item.detail || item}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function CoachingStarters({ items }) {
  if (!items || items.length === 0) return null
  return (
    <div>
      <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Coaching Questions</p>
      <div className="space-y-1.5">
        {items.map((q, i) => (
          <div key={i} className="flex gap-2 items-start">
            <ChevronRight className="w-3 h-3 text-purple-400 mt-0.5 shrink-0" />
            <span className="text-xs text-slate-300 italic">"{q}"</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function DispatchScoreDetail({ dispatcher: d, onClose }) {
  const [insight, setInsight] = useState(null)
  const [insightLoading, setInsightLoading] = useState(false)
  const [insightError, setInsightError] = useState('')
  const [clipError, setClipError] = useState(false)
  const [showHelp, setShowHelp] = useState(false)
  const printRef = useRef(null)

  const loadInsight = async (force = false) => {
    setInsightLoading(true)
    setInsightError('')
    try {
      setInsight(await fetchDispatcherInsight(d.username, force))
    } catch (e) {
      setInsightError(e.response?.data?.detail || 'Failed to load AI insights')
    } finally {
      setInsightLoading(false)
    }
  }

  const handlePrint = () => {
    const el = printRef.current
    if (!el) return
    const orig = document.body.innerHTML
    document.body.innerHTML = el.innerHTML
    window.print()
    document.body.innerHTML = orig
    window.location.reload()
  }

  const handleEmail = async () => {
    const bd = d.score_breakdown || {}
    const tierStr = d.tier || ''
    const date = new Date().toLocaleDateString([], { month: 'long', day: 'numeric', year: 'numeric' })

    const insightRows = insight && !insight.error
      ? `<tr><td colspan="2" style="padding:8px 0 4px;font-weight:bold;color:#374151">AI Coaching Summary</td></tr>
         <tr><td colspan="2" style="padding:4px 0 12px;color:#4b5563;font-style:italic">${insight.summary || ''}</td></tr>`
      : ''

    const strengthRows = insight?.strengths?.length
      ? insight.strengths.map(s =>
          `<tr><td style="padding:3px 8px 3px 0;color:#059669;font-weight:600;white-space:nowrap">✓ ${s.title}</td><td style="padding:3px 0;color:#4b5563">${s.detail}</td></tr>`
        ).join('')
      : ''

    const devRows = insight?.development_areas?.length
      ? insight.development_areas.map(s =>
          `<tr><td style="padding:3px 8px 3px 0;color:#d97706;font-weight:600;white-space:nowrap">△ ${s.title}</td><td style="padding:3px 0;color:#4b5563">${s.detail}</td></tr>`
        ).join('')
      : ''

    const htmlBody = `
<div style="font-family:Calibri,Arial,sans-serif;font-size:13px;color:#111827;max-width:700px">
  <h2 style="margin:0 0 4px;font-size:18px;color:#111827">Dispatcher Performance Report</h2>
  <p style="margin:0 0 16px;color:#6b7280;font-size:12px">${d.name} · ${d.role?.replace('ers-','')} · 90-day rolling window · ${date}</p>

  <table style="border-collapse:collapse;width:100%;margin-bottom:16px">
    <tr style="background:#f3f4f6">
      <th style="border:1px solid #d1d5db;padding:6px 10px;text-align:left;font-size:12px">Score</th>
      <th style="border:1px solid #d1d5db;padding:6px 10px;text-align:left;font-size:12px">Tier</th>
      <th style="border:1px solid #d1d5db;padding:6px 10px;text-align:left;font-size:12px">Fair Completion</th>
      <th style="border:1px solid #d1d5db;padding:6px 10px;text-align:left;font-size:12px">Typical Response Time</th>
      <th style="border:1px solid #d1d5db;padding:6px 10px;text-align:left;font-size:12px">Late Assignments</th>
      <th style="border:1px solid #d1d5db;padding:6px 10px;text-align:left;font-size:12px">Dispatches</th>
    </tr>
    <tr>
      <td style="border:1px solid #d1d5db;padding:6px 10px;font-weight:bold">${d.score}/100</td>
      <td style="border:1px solid #d1d5db;padding:6px 10px">${tierStr}</td>
      <td style="border:1px solid #d1d5db;padding:6px 10px">${d.adj_comp_pct}%</td>
      <td style="border:1px solid #d1d5db;padding:6px 10px">${d.median_rt_min}m</td>
      <td style="border:1px solid #d1d5db;padding:6px 10px">${d.slow_pct}%</td>
      <td style="border:1px solid #d1d5db;padding:6px 10px">${d.total?.toLocaleString()}</td>
    </tr>
  </table>

  <table style="border-collapse:collapse;width:100%;margin-bottom:16px">
    <tr style="background:#f3f4f6">
      <th style="border:1px solid #d1d5db;padding:6px 10px;text-align:left;font-size:12px">Completion Quality /40</th>
      <th style="border:1px solid #d1d5db;padding:6px 10px;text-align:left;font-size:12px">Speed /25</th>
      <th style="border:1px solid #d1d5db;padding:6px 10px;text-align:left;font-size:12px">Reliability /20</th>
      <th style="border:1px solid #d1d5db;padding:6px 10px;text-align:left;font-size:12px">Volume /15</th>
    </tr>
    <tr>
      <td style="border:1px solid #d1d5db;padding:6px 10px">${bd.outcome ?? '—'}</td>
      <td style="border:1px solid #d1d5db;padding:6px 10px">${bd.speed ?? '—'}</td>
      <td style="border:1px solid #d1d5db;padding:6px 10px">${bd.consistency ?? '—'}</td>
      <td style="border:1px solid #d1d5db;padding:6px 10px">${bd.volume ?? '—'}</td>
    </tr>
  </table>

  ${insightRows ? `<table style="border-collapse:collapse;width:100%;margin-bottom:16px"><tbody>${insightRows}</tbody></table>` : ''}
  ${strengthRows ? `<p style="font-weight:bold;margin:12px 0 4px">Strengths</p><table style="border-collapse:collapse;width:100%"><tbody>${strengthRows}</tbody></table>` : ''}
  ${devRows ? `<p style="font-weight:bold;margin:12px 0 4px">Development Areas</p><table style="border-collapse:collapse;width:100%"><tbody>${devRows}</tbody></table>` : ''}

  <p style="margin:16px 0 0;color:#9ca3af;font-size:11px">Generated by FSLPulse · ${date}</p>
</div>`

    const blob = new Blob([htmlBody], { type: 'text/html' })
    const clipItem = new ClipboardItem({ 'text/html': blob })
    try {
      await navigator.clipboard.write([clipItem])
      setClipError(false)
    } catch {
      setClipError(true)
    }

    const subject = encodeURIComponent(`Dispatcher Performance Report — ${d.name} (${tierStr})`)
    window.open(`https://outlook.cloud.microsoft/mail/deeplink/compose?subject=${subject}`, '_blank')
  }

  const bd = d.score_breakdown || {}
  const tierColor = TIER_COLOR[d.tier] || 'text-slate-300'
  const tierBg    = TIER_BG[d.tier]   || 'bg-slate-700/20 border-slate-700/30'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
      <div className="glass rounded-2xl border border-slate-700/50 w-full max-w-3xl max-h-[90vh] overflow-y-auto">

        {/* Header */}
        <div className="sticky top-0 z-10 bg-slate-900/95 backdrop-blur border-b border-slate-700/50 px-6 py-4 flex items-start justify-between">
          <div>
            <h2 className="text-lg font-bold text-slate-100">{d.name}</h2>
            <p className="text-xs text-slate-500 mt-0.5 capitalize flex items-center gap-2">
              {d.role.replace('ers-', '')} · 90-day rolling window · {d.total?.toLocaleString()} dispatches
              {d.channel && (
                <span className="px-1.5 py-0.5 rounded text-[9px] font-bold border bg-slate-700/30 text-slate-400 border-slate-700/40 normal-case">
                  {d.channel}
                </span>
              )}
            </p>
          </div>
          <div className="flex items-center gap-2 ml-4 mt-0.5">
            <button
              onClick={() => setShowHelp(h => !h)}
              title="How is this scored?"
              className={`transition-colors group relative ${showHelp ? 'text-brand-400' : 'text-slate-500 hover:text-slate-300'}`}>
              <HelpCircle className="w-4 h-4" />
              <span className="absolute top-full right-0 mt-2 hidden group-hover:block w-36 text-[10px] text-slate-200 bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 shadow-xl z-50 whitespace-normal">
                How is this scored?
              </span>
            </button>
            <button
              onClick={handlePrint}
              title="Save as PDF"
              className="text-slate-500 hover:text-slate-300 transition-colors group relative">
              <Printer className="w-4 h-4" />
              <span className="absolute top-full right-0 mt-2 hidden group-hover:block w-36 text-[10px] text-slate-200 bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 shadow-xl z-50 whitespace-normal">
                Print or save as PDF
              </span>
            </button>
            <button
              onClick={handleEmail}
              title="Email report"
              className="text-slate-500 hover:text-blue-400 transition-colors group relative">
              <Mail className="w-4 h-4" />
              <span className="absolute top-full right-0 mt-2 hidden group-hover:block w-52 text-[10px] text-slate-200 bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 shadow-xl z-50 whitespace-normal">
                Copy report &amp; open Outlook. Press ⌘V (Ctrl+V) to paste.
              </span>
            </button>
            <button onClick={onClose} className="text-slate-500 hover:text-white transition-colors">
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Clipboard error banner */}
        {clipError && (
          <div className="mx-6 mt-4 px-3 py-2 rounded-lg bg-amber-950/40 border border-amber-800/40 text-amber-400 text-xs flex items-center gap-2">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
            <span>Clipboard access denied — Outlook is open. Select All (⌘A) then Copy (⌘C) in Outlook.</span>
            <button onClick={() => setClipError(false)} className="ml-auto text-amber-500 hover:text-amber-300">
              <X className="w-3 h-3" />
            </button>
          </div>
        )}

        {showHelp && <MetricHelpPanel onClose={() => setShowHelp(false)} />}

        <div ref={printRef} className="p-6 space-y-6">

          {/* Score overview */}
          <div className={`rounded-xl border p-4 ${tierBg}`}>
            <div className="flex items-center gap-6">
              <div className="text-center">
                <div className={`text-5xl font-black ${tierColor}`}>{d.score}</div>
                <div className="text-xs text-slate-500 mt-1">/ 100</div>
              </div>
              <div className="flex-1 space-y-3">
                <ScoreBar label="Completion Quality" value={bd.outcome} max={40}
                  color={bd.outcome >= 30 ? 'bg-emerald-500' : bd.outcome >= 20 ? 'bg-amber-500' : 'bg-red-500'} />
                <ScoreBar label="Speed" value={bd.speed} max={25}
                  color={bd.speed >= 20 ? 'bg-emerald-500' : bd.speed >= 12 ? 'bg-amber-500' : 'bg-red-500'} />
                <ScoreBar label="Reliability" value={bd.consistency} max={20}
                  color={bd.consistency >= 17 ? 'bg-emerald-500' : bd.consistency >= 10 ? 'bg-amber-500' : 'bg-red-500'} />
                <ScoreBar label="Volume" value={bd.volume} max={15}
                  color={bd.volume >= 12 ? 'bg-emerald-500' : bd.volume >= 7 ? 'bg-amber-500' : 'bg-red-500'} />
              </div>
              <div className="text-center">
                <div className={`text-sm font-bold px-3 py-1 rounded-full border ${TIER_BG[d.tier]} ${tierColor}`}>
                  {d.tier}
                </div>
              </div>
            </div>
          </div>

          {/* Key stats */}
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {[
              { label: 'Completion Rate',      value: `${d.raw_comp_pct}%`,  tone: d.raw_comp_pct >= 90 ? 'text-emerald-400' : d.raw_comp_pct >= 80 ? 'text-amber-400' : 'text-red-400' },
              { label: 'Fair Completion Rate', value: `${d.adj_comp_pct}%`,  tone: d.adj_comp_pct >= 90 ? 'text-emerald-400' : d.adj_comp_pct >= 80 ? 'text-amber-400' : 'text-red-400' },
              { label: 'Late Assignments',     value: `${d.slow_pct}%`,      tone: d.slow_pct < 15 ? 'text-emerald-400' : d.slow_pct < 30 ? 'text-amber-400' : 'text-red-400' },
            ].map(({ label, value, tone }) => (
              <div key={label} className="glass rounded-xl border border-slate-700/40 p-3 text-center">
                <div className={`text-xl font-bold ${tone}`}>{value}</div>
                <div className="text-[10px] text-slate-500 mt-1">{label}</div>
              </div>
            ))}
          </div>
          {/* Timing stats — assignment speed + arrival */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              { label: 'Typical Response Time', value: `${d.median_rt_min}m`, tone: d.median_rt_min <= 10 ? 'text-emerald-400' : d.median_rt_min <= 20 ? 'text-amber-400' : 'text-red-400', sub: 'queue → assigned' },
              { label: 'Typical Arrival',        value: d.median_arrival_min != null ? `${d.median_arrival_min}m` : '—', tone: d.median_arrival_min == null ? 'text-slate-500' : d.median_arrival_min <= 30 ? 'text-emerald-400' : d.median_arrival_min <= 60 ? 'text-amber-400' : 'text-red-400', sub: 'assigned → on location' },
              { label: 'Late Arrivals (>60m)',   value: d.late_arrival_pct != null ? `${d.late_arrival_pct}%` : '—',  tone: d.late_arrival_pct == null ? 'text-slate-500' : d.late_arrival_pct < 15 ? 'text-emerald-400' : d.late_arrival_pct < 30 ? 'text-amber-400' : 'text-red-400', sub: 'of dispatches' },
              { label: 'Arrival P90',            value: d.p90_arrival_min != null ? `${d.p90_arrival_min}m` : '—',   tone: d.p90_arrival_min == null ? 'text-slate-500' : d.p90_arrival_min <= 60 ? 'text-emerald-400' : d.p90_arrival_min <= 100 ? 'text-amber-400' : 'text-red-400', sub: 'worst 10% of calls' },
            ].map(({ label, value, tone, sub }) => (
              <div key={label} className="glass rounded-xl border border-slate-700/40 p-3 text-center">
                <div className={`text-xl font-bold ${tone}`}>{value}</div>
                <div className="text-[10px] text-slate-500 mt-0.5">{label}</div>
                <div className="text-[9px] text-slate-700 mt-0.5">{sub}</div>
              </div>
            ))}
          </div>

          {/* Charts row */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="glass rounded-xl border border-slate-700/40 p-4">
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                Response Time Distribution
              </p>
              <p className="text-[10px] text-slate-600 mb-3">Calls that waited over 2 hours are excluded — those are inherited from a previous shift and should not count against this dispatcher</p>
              <BarChart buckets={d.rt_buckets || {}} />
            </div>
            <div className="glass rounded-xl border border-slate-700/40 p-4">
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                Call Type Mix
              </p>
              <CallTypePie callTypes={d.call_types || []} total={d.total} />
            </div>
          </div>

          {/* AI insights */}
          <div className="glass rounded-xl border border-slate-700/40 p-4">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-purple-400" />
                <p className="text-sm font-semibold text-slate-200">AI Coaching Insights</p>
              </div>
              <div className="flex gap-2">
                {insight && (
                  <button
                    onClick={() => loadInsight(true)}
                    disabled={insightLoading}
                    className="text-[11px] text-slate-500 hover:text-slate-300 border border-slate-700/50 px-2 py-1 rounded transition-all">
                    Regenerate
                  </button>
                )}
                {!insight && !insightLoading && (
                  <button
                    onClick={() => loadInsight(false)}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-purple-600/20 text-purple-400 border border-purple-500/30 hover:bg-purple-600/30 transition-all">
                    <Sparkles className="w-3.5 h-3.5" />Generate Insights
                  </button>
                )}
              </div>
            </div>

            {insightLoading && (
              <div className="flex items-center gap-2 text-slate-400 py-4">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span className="text-xs">Generating coaching insights…</span>
              </div>
            )}

            {insightError && (
              <div className="flex items-center gap-2 text-red-400 text-xs">
                <AlertCircle className="w-4 h-4 shrink-0" />
                {insightError}
              </div>
            )}

            {!insight && !insightLoading && !insightError && (
              <p className="text-xs text-slate-600 py-2">
                Click "Generate Insights" to create a personalized coaching report using AI. Cached for the current month.
              </p>
            )}

            {insight && !insightLoading && (
              <div className="space-y-4">
                {insight.error ? (
                  <div className="flex items-center gap-2 text-amber-400 text-xs">
                    <AlertCircle className="w-4 h-4 shrink-0" />
                    {insight.error}
                  </div>
                ) : (
                  <>
                    {insight.summary && (
                      <p className="text-sm text-slate-300 leading-relaxed border-l-2 border-purple-500/40 pl-3">
                        {insight.summary}
                      </p>
                    )}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <InsightSection
                        title="Strengths"
                        items={insight.strengths}
                        tone="text-emerald-400"
                        dot="bg-emerald-500"
                      />
                      <InsightSection
                        title="Development Areas"
                        items={insight.development_areas}
                        tone="text-amber-400"
                        dot="bg-amber-500"
                      />
                    </div>
                    <CoachingStarters items={insight.coaching_starters} />
                  </>
                )}
              </div>
            )}
          </div>

        </div>
      </div>
    </div>
  )
}
