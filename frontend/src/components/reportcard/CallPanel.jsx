import { useContext } from 'react'
import { Link } from 'react-router-dom'
import { X, ExternalLink, BookOpen } from 'lucide-react'
import { SAReportContext } from '../../contexts/SAReportContext'
import { verdictColour, fmtTime, fmtMin } from './reportCardStyles'

const CLASS_LABEL = {
  FSL_ENGINE: 'FSL optimizer', FSL_AUTO_SCHEDULE: 'FSL auto-schedule', INTEGRATION: 'IT System User, no auto-schedule', HUMAN: 'AAA dispatcher',
  GARAGE_DISPATCHER: 'Garage dispatcher', DRIVER: 'Driver', TOWBOOK_SYNC: 'Towbook sync', OTHER: 'Other',
}
const mi = v => (v == null ? '—' : `${v.toFixed(1)} mi`)

function Row({ label, children }) {
  return (
    <div className="flex justify-between gap-3 py-1 border-b border-slate-800/50 text-xs">
      <span className="text-slate-500 shrink-0">{label}</span>
      <span className="text-slate-200 text-right">{children}</span>
    </div>
  )
}

export default function CallPanel({ sa, catalog, onClose, callStory }) {
  const ctx = useContext(SAReportContext)
  if (!sa) return null
  const v = sa.verdict
  const e = v?.evidence || {}
  const d = sa.decision
  const m = sa.milestones
  const label = catalog.find(c => c.code === v?.code)?.label
  return (
    <div className="glass rounded-xl p-4 space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-sm font-semibold text-white">{sa.number}</div>
          <div className="text-[11px] text-slate-400">{sa.work_type} · created {fmtTime(sa.created)} · {sa.status}</div>
        </div>
        <button onClick={onClose} className="p-1 text-slate-500 hover:text-white" title="Close"><X className="w-4 h-4" /></button>
      </div>

      {v && (
        <div className="rounded-lg border px-3 py-2" style={{ borderColor: verdictColour(v.code), background: `${verdictColour(v.code)}14` }}>
          <div className="text-xs font-semibold" style={{ color: verdictColour(v.code) }}>{v.code.replaceAll('_', ' ')}</div>
          {label && <div className="text-[11px] text-slate-300 mt-0.5">{label}</div>}
          {v.flags.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1.5">
              {v.flags.map(f => <span key={f} className="text-[9px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300">{f.replaceAll('_', ' ')}</span>)}
            </div>
          )}
        </div>
      )}

      <div>
        <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Who assigned</div>
        <Row label="Final decision">{d.final_actor || '—'} {d.final_actor_class && <span className="text-slate-500">({CLASS_LABEL[d.final_actor_class]})</span>}</Row>
        <Row label="First pick">{d.first_actor || '—'} {d.first_actor_class && <span className="text-slate-500">({CLASS_LABEL[d.first_actor_class]})</span>}</Row>
        <Row label="Driver">{sa.driver_name || '—'}</Row>
        <Row label="Picks / before dispatch">{d.n_picks} / {d.n_pre_dispatch_picks}</Row>
        {(d.pullbacks > 0 || d.reassign_after_dispatch > 0) && <Row label="Pull-backs / changes after dispatch">{d.pullbacks} / {d.reassign_after_dispatch}</Row>}
        {sa.territory_moves.in > 0 && <Row label="Moved in from">{sa.territory_moves.from.join(', ')}</Row>}
        <Row label="Record creator (audit)">{d.ar_creator?.name || '—'}</Row>
      </div>

      <div>
        <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Distance at decision (straight line)</div>
        {e.graded ? (<>
          <Row label="Picked driver">{mi(e.pick_miles)} · {e.pick_open_jobs} open job{e.pick_open_jobs === 1 ? '' : 's'}</Row>
          <Row label="Closest qualified">{e.picked_closest ? 'the pick' : `${e.closest_driver} · ${mi(e.closest_q_miles)}`}</Row>
          <Row label="Closest free qualified">{e.closest_free_driver ? (e.picked_closest_free ? 'the pick' : `${e.closest_free_driver} · ${mi(e.closest_free_q_miles)}`) : 'none free'}</Row>
          {e.idle_closer?.length > 0 && <Row label="Idle and closer">{e.idle_closer.map(([n, x]) => `${n} ${x} mi`).join(', ')}</Row>}
          <Row label="Candidates">{e.n_candidates} on shift, qualified, fresh GPS</Row>
        </>) : <div className="text-[11px] text-slate-500 py-1">Not graded: no fresh GPS for the picked driver at decision time.</div>}
      </div>

      <div>
        <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Response</div>
        <Row label="Response vs PTA">{fmtMin(e.response_min)} vs {sa.pta_min ? `${sa.pta_min} min` : '—'}</Row>
        <Row label="PTA met">{e.pta_met == null ? '—' : e.pta_met ? 'Yes' : <span className="text-rose-400">No</span>}</Row>
        <Row label="Assigned → dispatched">{fmtMin(e.release_min)}</Row>
        <Row label="Assigned → en route">{fmtMin(e.queue_wait_min)}</Row>
        <Row label="Timeline">
          {fmtTime(m.t_asg)} assigned · {fmtTime(m.t_disp)} dispatched · {fmtTime(m.t_er)} en route · {fmtTime(m.arrival)} on scene · {fmtTime(m.t_end)} {m.end_status || ''}
        </Row>
      </div>

      {callStory && (
        <Link to={`/call-story?q=${sa.number}`}
          className="w-full flex items-center justify-center gap-1.5 text-xs py-1.5 rounded-lg bg-slate-800 text-slate-200 hover:bg-slate-700">
          <BookOpen className="w-3.5 h-3.5" />Open call story
        </Link>
      )}
      <button onClick={() => ctx?.open(sa.number)}
        className="w-full flex items-center justify-center gap-1.5 text-xs py-1.5 rounded-lg bg-brand-600/20 text-brand-300 hover:bg-brand-600/30">
        <ExternalLink className="w-3.5 h-3.5" />Open full SA report
      </button>
    </div>
  )
}
