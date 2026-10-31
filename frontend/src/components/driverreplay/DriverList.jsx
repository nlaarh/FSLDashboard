import { useState } from 'react'
import { ArrowDownAZ, ArrowUpZA } from 'lucide-react'
import { shortDriverName } from '../../utils/driverName'
import { SORTS, sortDrivers, DRIVER_COLOURS } from './driverModel'

const hhmm = s => new Date(s * 1000).toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit' })

/** The garage's on-platform drivers for the day, shown in the Garage replay's left list when it is switched to Drivers (same place,
 *  size and look as the Work orders list). Click a driver to replay their day, the way a work order is
 *  clicked (version 1: one driver at a time). rows = driverRows(). Towbook drivers send no location, so they are not listed. */
export default function DriverList({ rows, selected, onSelect, loading = false }) {
  const [sort, setSort] = useState('name')
  const shown = sortDrivers(rows, sort)
  const nameSort = sort === 'name' || sort === 'name_desc'
  return (
    <div className="glass rounded-xl overflow-hidden">
      <div className="px-3 py-2 text-xs font-semibold text-slate-300 border-b border-slate-700/60">On-platform drivers · {shown.length}</div>
      <div className="px-3 py-2 border-b border-slate-700/60 flex items-center gap-1.5">
        <button type="button" onClick={() => setSort(sort === 'name' ? 'name_desc' : 'name')} title="Sort by name (click again to reverse)"
          className={`px-2 py-0.5 rounded-md text-[11px] border flex items-center gap-1 ${nameSort ? 'bg-brand-600/30 border-brand-500 text-white' : 'border-slate-700 text-slate-400 hover:text-white'}`}>
          {sort === 'name_desc' ? <ArrowUpZA className="w-3.5 h-3.5" /> : <ArrowDownAZ className="w-3.5 h-3.5" />}Name
        </button>
        <select value={nameSort ? '' : sort} onChange={e => setSort(e.target.value || 'name')} aria-label="Sort drivers"
          className="bg-slate-900 border border-slate-700 rounded-md text-[11px] text-slate-300 px-1.5 py-0.5 flex-1">
          <option value="">Other sort…</option>
          {SORTS.filter(s => !s.id.startsWith('name')).map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
        </select>
      </div>
      <div className="max-h-[70vh] overflow-y-auto">
        {shown.map(r => {
          const on = selected === r.id
          return (
            <button key={r.id} type="button" onClick={() => onSelect(r.id)} aria-pressed={on}
              className={`w-full text-left px-3 py-2 border-b border-slate-800/80 flex items-center gap-2.5 transition-colors ${on ? 'bg-brand-600/20' : 'hover:bg-slate-800/60'}`}>
              <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: on ? DRIVER_COLOURS[0] : '#475569', boxShadow: on ? `0 0 8px ${DRIVER_COLOURS[0]}` : undefined }} />
              <span className="min-w-0 flex-1">
                <span className="block text-xs text-white font-medium truncate">{shortDriverName(r.name)}</span>
                <span className="block text-[11px] text-slate-400 truncate">
                  {r.calls} call{r.calls === 1 ? '' : 's'}{r.overnight ? ' · on shift overnight' : r.start ? ` · on shift ${hhmm(r.start)}` : ' · no shift on record'}
                </span>
              </span>
            </button>
          )
        })}
        {!shown.length && <div className="px-3 py-4 text-xs text-slate-500">{loading ? 'Loading drivers…' : 'No on-platform driver sent GPS this day.'}</div>}
      </div>
    </div>
  )
}
