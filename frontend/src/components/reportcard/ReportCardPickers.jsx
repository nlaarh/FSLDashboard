import { useEffect, useMemo, useState } from 'react'
import { fetchGarages, fetchReportCardGarages } from '../../api'
import MiniDatePicker from '../MiniDatePicker'
import { yesterdayEastern } from './reportCardStyles'

/**
 * Pick the day first; the garage list then shows ONLY the garages that had work orders that day (with their counts),
 * not every garage. If that list cannot be loaded, it falls back to the full garage list so the picker never dead-ends.
 */
export default function ReportCardPickers({ garage, date, onChange }) {
  const [list, setList] = useState([])            // [{ id, name, count? }]
  const [phase, setPhase] = useState('idle')      // idle | loading | ready | fallback

  useEffect(() => {
    if (!date) { setList([]); setPhase('idle'); return undefined }
    let live = true
    setPhase('loading')
    fetchReportCardGarages(date)
      .then(({ status, data }) => {
        if (!live) return
        if (status === 200) { setList(data); setPhase('ready') } else throw new Error(`garages ${status}`)
      })
      .catch(() => fetchGarages()
        .then(all => { if (live) { setList([...all].sort((a, b) => (a.name || '').localeCompare(b.name || ''))); setPhase('fallback') } })
        .catch(() => { if (live) { setList([]); setPhase('fallback') } }))
    return () => { live = false }
  }, [date])

  // a garage that had no work orders on the newly picked day cannot be shown: clear it instead of showing an empty day
  useEffect(() => {
    if (phase === 'ready' && garage && !list.some(g => g.id === garage)) onChange({ garage: '', date })
  }, [phase, list]) // eslint-disable-line react-hooks/exhaustive-deps

  const options = useMemo(() => list.map(g => ({ id: g.id, label: g.count != null ? `${g.name} (${g.count})` : g.name })), [list])
  const placeholder = !date ? 'Pick a day first' : phase === 'loading' ? 'Finding garages with work orders…'
    : phase === 'ready' ? (options.length ? `Select a garage (${options.length} had work orders)` : 'No garage had work orders that day') : 'Select a garage…'
  return (
    <div className="flex flex-wrap items-center gap-2">
      <MiniDatePicker value={date} max={yesterdayEastern()} placeholder="Pick a past day" onChange={d => onChange({ garage, date: d })} />
      <select value={garage || ''} disabled={!date || phase === 'loading'} onChange={e => onChange({ garage: e.target.value, date })}
        className="bg-slate-900 border border-slate-700 rounded-lg text-xs px-3 py-2 min-w-[300px] text-white focus:outline-none focus:ring-2 focus:ring-brand-500/40 disabled:opacity-60">
        <option value="">{placeholder}</option>
        {options.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
      </select>
    </div>
  )
}
