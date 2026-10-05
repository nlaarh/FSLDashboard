import { fmtTime, fmtMin } from './storyStyles'

const CHANNEL = { fleet: 'Fleet', on_platform_contractor: 'On-Platform', towbook: 'Towbook', spot: 'SPOT' }

function PtaBadge({ pta }) {
  if (pta.met_initial == null) return <span className="text-xs text-slate-400">PTA not graded</span>
  const met = pta.met_initial
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className={`text-xs px-2 py-0.5 rounded border font-medium ${met
        ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' : 'bg-rose-500/15 text-rose-300 border-rose-500/30'}`}>
        PTA {pta.initial_min} min {met ? 'met' : 'missed'}
        {pta.margin_initial_min != null && ` by ${Math.abs(Math.round(pta.margin_initial_min))} min`}
      </span>
      {pta.rebased && (
        <span className="text-xs px-2 py-0.5 rounded border bg-amber-500/10 text-amber-300 border-amber-500/30"
          title={`Changed ${fmtTime(pta.rebased.ts)} by ${pta.rebased.actor}`}>
          PTA re-based to {pta.final_min} min ({pta.met_final ? 'met' : 'missed'} against it)
        </span>
      )}
      <span className="text-xs text-slate-400">
        Arrival {fmtMin(pta.response_min)} after the call{pta.arrival_source === 'history' ? ' (from history)' : ''}
      </span>
    </div>
  )
}

/** Call ids, grid, the garages it passed through and the member's promise. */
export default function StoryHeader({ story, onPickLeg }) {
  const h = story.header
  const legs = story.resolution.legs || []
  const wo = story.resolution.wo || {}
  return (
    <div className="glass rounded-xl p-4 space-y-3">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="text-lg font-semibold text-white">{legs.find(l => l.selected)?.number}</span>
        <span className="text-sm text-slate-300">{h.work_type}{h.tow ? ' · tow' : ''}</span>
        <span className="text-xs text-slate-500">WO {wo.number}{wo.call_key ? ` · ${wo.call_key}` : ''}</span>
        <span className="text-xs text-slate-500">{h.city} {h.postal_code} · grid {h.grid?.name || '—'}</span>
        <span className="text-xs text-slate-500">{h.source ? `source ${h.source}` : ''}{h.priority ? ` · priority ${h.priority}` : ''}</span>
      </div>
      {legs.length > 1 && (
        <div className="flex gap-1">
          {legs.map(l => (
            <button key={l.sa_id} disabled={l.role === 'drop_off'} onClick={() => onPickLeg(l.number)}
              className={`text-[11px] px-2 py-0.5 rounded border ${l.selected ? 'border-brand-400 text-brand-200'
                : 'border-slate-700 text-slate-400 hover:text-white'} disabled:opacity-50 disabled:cursor-default`}>
              {l.number} {l.role === 'drop_off' ? '(drop-off leg)' : ''}
            </button>
          ))}
        </div>
      )}
      <PtaBadge pta={story.pta} />
      <div className="flex flex-wrap items-center gap-1 text-[11px]">
        {(h.channel_path || []).map((hop, i) => (
          <span key={i} className="flex items-center gap-1">
            {i > 0 && <span className="text-slate-600">→</span>}
            <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-200" title={fmtTime(hop.ts)}>
              {hop.garage}{hop.channel ? ` · ${CHANNEL[hop.channel] || hop.channel}` : ''}
            </span>
          </span>
        ))}
        {story.performer && <span className="text-slate-400 ml-2">Work done by {story.performer} (Towbook)</span>}
      </div>
    </div>
  )
}
