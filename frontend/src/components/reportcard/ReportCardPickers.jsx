import { useEffect, useState } from 'react'
import { fetchGarages } from '../../api'
import MiniDatePicker from '../MiniDatePicker'
import { yesterdayEastern } from './reportCardStyles'

/** Garage select (existing /api/garages list) + a date picker capped at yesterday (Eastern). */
export default function ReportCardPickers({ garage, date, onChange }) {
  const [garages, setGarages] = useState([])
  useEffect(() => {
    fetchGarages()
      .then(list => setGarages([...list].sort((a, b) => (a.name || '').localeCompare(b.name || ''))))
      .catch(() => setGarages([]))
  }, [])
  return (
    <div className="flex flex-wrap items-center gap-2">
      <select value={garage || ''} onChange={e => onChange({ garage: e.target.value, date })}
        className="bg-slate-900 border border-slate-700 rounded-lg text-xs px-3 py-2 min-w-[260px] text-white focus:outline-none focus:ring-2 focus:ring-brand-500/40">
        <option value="">Select a garage…</option>
        {garages.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
      </select>
      <MiniDatePicker value={date} max={yesterdayEastern()} placeholder="Pick a past day"
        onChange={d => onChange({ garage, date: d })} />
    </div>
  )
}
