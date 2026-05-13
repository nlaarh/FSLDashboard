import { useState, useRef } from 'react'
import { X, Sparkles, Loader2, ChevronRight, AlertCircle, Printer, Mail, AlertTriangle, HelpCircle } from 'lucide-react'
import { fetchDispatcherInsight } from '../api'
import { MetricHelpPanel } from './DispatchScoreDetailHelp'

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
         <tr><td colspan="2" style="padding:4px 0 8px;color:#111827;font-weight:600">${insight.headline || insight.summary || ''}</td></tr>
         ${insight.manager_action ? `<tr><td colspan="2" style="padding:4px 0 12px;color:#2563eb;border-left:3px solid #3b82f6;padding-left:8px"><strong>Manager's Next Step:</strong> ${insight.manager_action}</td></tr>` : ''}`
      : ''

    const strengthItems = insight?.what_works || insight?.strengths || []
    const strengthRows = strengthItems.length
      ? strengthItems.map(s =>
          `<tr><td style="padding:3px 8px 3px 0;color:#059669;font-weight:600;white-space:nowrap">✓ ${s.title}</td><td style="padding:3px 0;color:#4b5563">${s.detail}</td></tr>`
        ).join('')
      : ''

    const devItems = insight?.the_gap
      ? [{ title: insight.the_gap.title, detail: `${insight.the_gap.detail}${insight.the_gap.root_cause ? ' Root cause: ' + insight.the_gap.root_cause : ''}` }]
      : (insight?.development_areas || [])
    const devRows = devItems.length
      ? devItems.map(s =>
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
      <th style="border:1px solid #d1d5db;padding:6px 10px;text-align:left;font-size:12px">PTA Rate</th>
      <th style="border:1px solid #d1d5db;padding:6px 10px;text-align:left;font-size:12px">Avg Response</th>
      <th style="border:1px solid #d1d5db;padding:6px 10px;text-align:left;font-size:12px">Dispatches</th>
    </tr>
    <tr>
      <td style="border:1px solid #d1d5db;padding:6px 10px;font-weight:bold">${d.score}/100</td>
      <td style="border:1px solid #d1d5db;padding:6px 10px">${tierStr}</td>
      <td style="border:1px solid #d1d5db;padding:6px 10px">${d.adj_comp_pct}%</td>
      <td style="border:1px solid #d1d5db;padding:6px 10px">${d.pta_rate != null ? d.pta_rate + '%' : '—'}</td>
      <td style="border:1px solid #d1d5db;padding:6px 10px">${d.median_rt_min}m</td>
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
            <p className="text-xs text-slate-500 mt-0.5 capitalize flex items-center gap-2 flex-wrap">
              {d.role.replace('ers-', '')} · 90-day rolling window · {d.total?.toLocaleString()} dispatches
              {d.channel && (
                <span className="px-1.5 py-0.5 rounded text-[9px] font-bold border bg-slate-700/30 text-slate-400 border-slate-700/40 normal-case">
                  {d.channel}
                </span>
              )}
              {d.channel_rank != null && d.channel_size != null && (
                <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold border normal-case ${
                  d.channel_rank === 1
                    ? 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                    : 'bg-slate-700/30 text-slate-400 border-slate-700/40'
                }`}>
                  {d.channel} #{d.channel_rank} of {d.channel_size}
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
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              { label: 'Fair Completion',  value: `${d.adj_comp_pct}%`,
                tone: d.adj_comp_pct >= 90 ? 'text-emerald-400' : d.adj_comp_pct >= 80 ? 'text-amber-400' : 'text-red-400',
                sub: 'complexity-adjusted' },
              { label: 'PTA Rate',         value: d.pta_rate != null ? `${d.pta_rate}%` : '—',
                tone: d.pta_rate == null ? 'text-slate-500' : d.pta_rate >= 80 ? 'text-emerald-400' : d.pta_rate >= 65 ? 'text-amber-400' : 'text-red-400',
                sub: 'on-time arrivals' },
              { label: 'Late Assignments', value: `${d.slow_pct}%`,
                tone: d.slow_pct < 15 ? 'text-emerald-400' : d.slow_pct < 30 ? 'text-amber-400' : 'text-red-400',
                sub: '>30 min to assign' },
              { label: 'Fast Dispatch',    value: `${d.fast_pct}%`,
                tone: d.fast_pct >= 50 ? 'text-emerald-400' : d.fast_pct >= 25 ? 'text-amber-400' : 'text-red-400',
                sub: '≤5 min response' },
            ].map(({ label, value, tone, sub }) => (
              <div key={label} className="glass rounded-xl border border-slate-700/40 p-3 text-center">
                <div className={`text-xl font-bold ${tone}`}>{value}</div>
                <div className="text-[10px] text-slate-500 mt-1">{label}</div>
                {sub && <div className="text-[9px] text-slate-700 mt-0.5">{sub}</div>}
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
                ) : insight.headline ? (
                  /* v2/v3 format: headline + what_works + the_gap + coaching_starters + development_plan + manager_action */
                  <>
                    {insight.headline && (
                      <p className="text-sm font-bold text-slate-100 leading-snug border-l-2 border-purple-500/50 pl-3">
                        {insight.headline}
                      </p>
                    )}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <InsightSection
                        title="What's Working"
                        items={insight.what_works}
                        tone="text-emerald-400"
                        dot="bg-emerald-500"
                      />
                      {insight.the_gap && (
                        <div>
                          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Focus Area</p>
                          <div className="flex gap-2">
                            <div className="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 bg-amber-500" />
                            <div>
                              <span className="text-xs font-semibold text-amber-400">{insight.the_gap.title} — </span>
                              <span className="text-xs text-slate-400">{insight.the_gap.detail}</span>
                              {insight.the_gap.root_cause && (
                                <p className="text-[10px] text-slate-600 mt-1 italic">Root cause: {insight.the_gap.root_cause}</p>
                              )}
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                    {insight.coaching_starters?.length > 0 && (
                      <CoachingStarters items={insight.coaching_starters} />
                    )}
                    {insight.development_plan && (
                      <div className="rounded-lg border border-slate-700/40 bg-slate-800/30 p-3 space-y-1">
                        <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">30-Day Development Plan</p>
                        <p className="text-xs text-slate-300 leading-relaxed whitespace-pre-line">{insight.development_plan}</p>
                      </div>
                    )}
                    {insight.manager_action && (
                      <div className="rounded-lg border border-brand-500/30 bg-brand-500/5 p-3">
                        <p className="text-[10px] font-bold text-brand-400 uppercase tracking-wider mb-1.5">Manager&apos;s Next Step</p>
                        <p className="text-xs text-slate-200">{insight.manager_action}</p>
                      </div>
                    )}
                  </>
                ) : (
                  /* Legacy v1 format: summary + strengths + development_areas + coaching_starters */
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
