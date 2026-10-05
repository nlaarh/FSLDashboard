import { useState } from 'react'
import { Sparkles, Loader2, Hammer, AlertTriangle } from 'lucide-react'
import { fetchCallStoryNarrative, buildReportCard } from '../../api'
import { verdictColour } from '../reportcard/reportCardStyles'

/** Headline cause, deterministic bullets, the report-card verdict and the optional AI summary. */
export default function StoryVerdict({ story, onHighlight, onRebuilt }) {
  const [narr, setNarr] = useState(null)
  const [building, setBuilding] = useState(false)
  const v = story.verdict
  const sel = story.resolution.legs.find(l => l.selected)
  const head = story.causes.find(c => c.headline)

  const writeSummary = async () => {
    setNarr({ loading: true })
    const { status, data } = await fetchCallStoryNarrative(sel.sa_id).catch(e => ({ status: 0, data: { detail: e.message } }))
    setNarr(status === 200 ? data : { error: data?.detail || data?.status || `Summary unavailable (${status})` })
  }
  const build = async () => {
    setBuilding(true)
    const { status } = await buildReportCard(v.build.territory_id, v.build.date)
    setBuilding(false)
    if (status === 200 || status === 202) onRebuilt(status === 202)
  }
  const unalias = t => (narr?.people ? t.replace(/\b(Driver|Dispatcher|Call taker|Garage dispatcher|Person) [A-Z]\b/g, m => narr.people[m] || m) : t)

  return (
    <div className="glass rounded-xl p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {v.primary ? (
          <span className="text-xs px-2 py-0.5 rounded border font-semibold"
            style={{ borderColor: verdictColour(v.primary), color: verdictColour(v.primary) }}>
            {v.primary.replaceAll('_', ' ')}
          </span>
        ) : <span className="text-xs text-slate-400 flex items-center gap-1"><AlertTriangle className="w-3.5 h-3.5" />{v.note}</span>}
        {(v.flags || []).map(f => <span key={f} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">{f.replaceAll('_', ' ')}</span>)}
        {v.primary && v.note && <span className="text-[11px] text-slate-500">{v.note}</span>}
        {v.source === 'day_snapshot' && <span className="text-[10px] text-slate-500">Same verdict as the Report Card day view</span>}
        {v.build?.allowed && v.source !== 'day_snapshot' && (
          <button onClick={build} disabled={building}
            className="ml-auto text-[11px] px-2.5 py-1 rounded-lg bg-brand-600/20 text-brand-300 hover:bg-brand-600/30 flex items-center gap-1">
            {building ? <Loader2 className="w-3 h-3 animate-spin" /> : <Hammer className="w-3 h-3" />}Build garage-day
          </button>
        )}
      </div>
      {head && <div className="text-sm text-white font-medium">Main reason: {story.bullets.find(b => b.headline)?.text}</div>}
      <ul className="space-y-1">
        {story.bullets.filter(b => !b.headline).map((b, i) => (
          <li key={i} onMouseEnter={() => onHighlight(b.event_ids)} onMouseLeave={() => onHighlight([])}
            className={`text-[13px] leading-snug pl-3 border-l-2 ${b.headline ? 'border-rose-400 text-slate-100' : 'border-slate-700 text-slate-300'}`}>
            {b.text}
            {b.cause_codes.length > 0 && <span className="ml-1.5 text-[9px] font-mono text-slate-500">{b.cause_codes.join(' ')}</span>}
          </li>
        ))}
      </ul>
      <div className="pt-1">
        {!narr && (
          <button onClick={writeSummary} className="text-[11px] px-2.5 py-1 rounded-lg bg-slate-800 text-slate-200 hover:bg-slate-700 flex items-center gap-1">
            <Sparkles className="w-3 h-3 text-brand-300" />Write summary
          </button>
        )}
        {narr?.loading && <div className="text-xs text-slate-400 flex items-center gap-1.5"><Loader2 className="w-3 h-3 animate-spin" />Writing from the facts above…</div>}
        {narr?.error && <div className="text-xs text-rose-300">{narr.error}</div>}
        {narr?.sentences && (
          <div className="rounded-lg border border-slate-700/60 p-3 space-y-1">
            <div className="text-[10px] text-slate-500">{narr.source === 'ai' ? `AI summary · ${narr.model} · every number, name and cause checked against the facts`
              : `Summary unavailable (${narr.validation?.reason || 'AI answer rejected'}): showing the bullets above`}</div>
            {narr.sentences.map((s, i) => (
              <p key={i} onMouseEnter={() => onHighlight(s.event_ids)} onMouseLeave={() => onHighlight([])}
                className="text-[13px] text-slate-200">{unalias(s.text)}</p>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
