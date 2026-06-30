/**
 * GarageAcceptanceCards.jsx
 *
 * The two completion-based acceptance cards, shared by the Performance and
 * Operations tabs. Self-contained: fetches /api/garages/{id}/acceptance, handles
 * the "computing" first-load state (shows the wait message + spinner and polls
 * until ready), renders the two cards, and owns the drill-down modal.
 *
 * Definition (completion-based):
 *   1st Call Acceptance — calls where THIS garage was first spotted to.
 *     Accepted = this garage completed the WO. Not Accepted = another garage (or none) did.
 *   2nd+ Call Acceptance — calls moved to this garage after it was NOT first.
 *     Accepted = this garage completed the WO. Not Accepted = another garage (or none) did.
 */

import { useState, useEffect, useRef } from 'react'
import { Zap, Loader2, AlertTriangle } from 'lucide-react'
import { MetricCard } from './GarageOperationsUtils'
import AcceptanceDetailModal from './AcceptanceDetailModal'
import { fetchAcceptance } from '../api'

const FIRST_DEF =
  '1st Call Acceptance — calls where THIS garage was the FIRST garage the work order ' +
  'was spotted to. Accepted = this garage completed the work order. Not Accepted = a ' +
  'different garage (or none) completed it.'
const SECOND_DEF =
  '2nd+ Call Acceptance — calls where this garage was NOT first, but the work order was ' +
  'moved to it at some point. Accepted = this garage completed it. Not Accepted = a ' +
  'different garage (or none) completed it.'

const color = (p) =>
  p == null ? 'text-slate-500' : p >= 90 ? 'text-emerald-400' : p >= 75 ? 'text-amber-400' : 'text-red-400'
const border = (p) => (p >= 90 ? 'border-emerald-800/30' : 'border-amber-800/30')

export default function GarageAcceptanceCards({ garageId, startDate, endDate, refreshKey }) {
  const [state, setState] = useState({ status: 'loading', data: null, message: '' })
  const [activeDef, setActiveDef] = useState(null)
  const [drillView, setDrillView] = useState(null)
  const pollRef = useRef(null)

  useEffect(() => {
    let ignore = false
    const clearPoll = () => { if (pollRef.current) { clearTimeout(pollRef.current); pollRef.current = null } }
    setState({ status: 'loading', data: null, message: '' })

    const load = () => {
      fetchAcceptance(garageId, startDate, endDate)
        .then(d => {
          if (ignore) return
          if (d.status === 'computing') {
            setState({ status: 'computing', data: null, message: d.message || 'Calculating…' })
            pollRef.current = setTimeout(load, 5000)  // poll until the map is ready
          } else {
            setState({ status: 'ready', data: d, message: '' })
          }
        })
        .catch(e => {
          if (ignore) return
          setState({
            status: 'error', data: null,
            message: e.response?.data?.detail || e.message || 'Failed to load acceptance',
          })
        })
    }
    load()
    return () => { ignore = true; clearPoll() }
  }, [garageId, startDate, endDate, refreshKey])

  const { status, data, message } = state
  const ready = status === 'ready' && data
  const calc = status === 'loading' || status === 'computing'
  // Card shells ALWAYS render (never hold the page) — values fill in when the
  // metric finishes computing. While calculating, value shows a spinner.
  const calcVal = <span className="inline-flex items-center"><Loader2 className="w-4 h-4 animate-spin text-slate-500" /></span>

  return (
    <>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <MetricCard label="1st Call Acceptance" icon={Zap}
          value={ready ? (data.first_call_pct != null ? `${data.first_call_pct}%` : 'N/A') : calcVal}
          sub={ready
            ? (data.first_call_total > 0 ? `${data.first_call_accepted} / ${data.first_call_total} first calls completed here` : 'No first calls')
            : 'Calculating…'}
          color={ready ? color(data.first_call_pct) : 'text-slate-500'} border={ready ? border(data.first_call_pct) : 'border-slate-800/40'}
          onClick={ready ? () => setDrillView('first_call') : undefined}
          definition={FIRST_DEF} defId="first_call" activeDef={activeDef} setActiveDef={setActiveDef} />
        <MetricCard label="2nd+ Call Acceptance" icon={Zap}
          value={ready ? (data.second_call_pct != null ? `${data.second_call_pct}%` : 'N/A') : calcVal}
          sub={ready
            ? (data.second_call_total > 0 ? `${data.second_call_accepted} / ${data.second_call_total} moved-in calls completed here` : 'No moved-in calls')
            : 'Calculating…'}
          color={ready ? color(data.second_call_pct) : 'text-slate-500'} border={ready ? border(data.second_call_pct) : 'border-slate-800/40'}
          onClick={ready ? () => setDrillView('second_call') : undefined}
          definition={SECOND_DEF} defId="second_call" activeDef={activeDef} setActiveDef={setActiveDef} />
      </div>

      {/* Small non-blocking note while the org-wide map computes (first time per period) */}
      {status === 'computing' && message && (
        <div className="flex items-center gap-2 text-[11px] text-slate-500 px-1 mt-1">
          <Loader2 className="w-3.5 h-3.5 animate-spin text-brand-400 shrink-0" /> {message}
        </div>
      )}
      {status === 'error' && (
        <div className="flex items-center gap-2 text-[11px] text-red-300 px-1 mt-1">
          <AlertTriangle className="w-3.5 h-3.5 text-red-400 shrink-0" /> {message}
        </div>
      )}

      {drillView && ready && (
        <AcceptanceDetailModal view={drillView} territoryId={garageId}
          startDate={startDate} endDate={endDate} onClose={() => setDrillView(null)} />
      )}
    </>
  )
}
