/**
 * Cancellations.jsx
 *
 * Every ERS call cancelled on one Eastern day (today unless a date is picked), newest first. Click a column heading to sort; the row under it filters. All of it lives in the URL
 * (?tab=cancellations&ctype=en-route&csort=garage&cdir=asc&cf_garage=NAME&cpage=2) so a view can be shared and survives a reload.
 * Each call number opens the SA report; the Replay link opens the call on the map. Refreshes every 60 s while visible.
 */

import { useState, useEffect, useMemo } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { clsx } from 'clsx'
import { Loader2, AlertTriangle, PlayCircle } from 'lucide-react'
import { fetchCancellations } from '../api'
import { pollWhileVisible } from '../utils/pollWhileVisible'
import SALink from './SALink'

const PAGE = 25
const REFRESH_S = 60
const MAX_DAYS_BACK = 31
const etDay = (offset = 0) => new Date(Date.now() - offset * 86400000).toLocaleDateString('en-CA', { timeZone: 'America/New_York' })   // YYYY-MM-DD
const TYPES = [
  ['all', 'All'],
  ['en-route', 'After truck en route'],
  ['before', 'Before truck en route'],
  ['other', 'Not specified'],
]
const TYPE_OF = { 'After truck en route': 'en-route', 'Before truck en route': 'before', 'Canceled': 'other' }
const BADGE = {
  'en-route': 'bg-red-500/20 text-red-300 border-red-500/40',
  'before': 'bg-slate-500/20 text-slate-300 border-slate-500/40',
  'other': 'bg-amber-500/20 text-amber-300 border-amber-500/40',
}

const norm = t => String(t).toLowerCase().replace(/[^a-z0-9]/g, '')     // 'SA-717120', 'sa 717120' and '717120' all match the same call
const etTime = iso => iso ? new Date(iso).toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit', hour12: true }) : '--'
const fmtWait = m => m == null ? '--' : m < 60 ? `${m} min` : `${Math.floor(m / 60)}h ${m % 60}m`

function Stat({ label, value, tone }) {
  return (
    <span className="inline-flex items-baseline gap-1.5 rounded-md border border-slate-700/50 bg-slate-900/60 px-2.5 py-1 text-[11px] text-slate-500">
      {label} <b className={clsx('text-sm', tone || 'text-white')}>{value ?? '--'}</b>
    </span>
  )
}

const Phone = ({ n }) => n ? <a href={`tel:${n}`} className="block text-[11px] text-sky-300 hover:text-sky-200">{n}</a> : null

// One entry per column: how to read its value, how to compare it, and what kind of filter it gets.
const COLS = [
  { k: 'number', h: 'SA', val: i => i.number, filter: 'text' },
  { k: 'wo', h: 'Work order', val: i => i.work_order || '', filter: 'text' },
  { k: 'cancelled', h: 'Cancelled at', val: i => i.cancelled_et || '', num: false },
  { k: 'type', h: 'Type', val: i => i.type, filter: 'select' },
  { k: 'by', h: 'Cancelled by', val: i => i.cancelled_by || '', filter: 'select' },
  { k: 'garage', h: 'Garage', val: i => i.garage || '', filter: 'select' },
  { k: 'driver', h: 'Driver', val: i => i.driver || '', filter: 'select' },
  { k: 'reason', h: 'Reason', val: i => i.reason, filter: 'select' },
  { k: 'waited', h: 'Waited', val: i => i.minutes_before_cancel ?? -1, num: true },
  { k: 'pta', h: 'PTA', val: i => i.pta_min ?? -1, num: true },
  { k: 'work', h: 'Work type', val: i => i.work_type || '', filter: 'select' },
]

export default function Cancellations() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [left, setLeft] = useState(REFRESH_S)           // seconds to the next refresh
  const [params, setParams] = useSearchParams()
  const today = etDay()
  const picked = /^\d{4}-\d{2}-\d{2}$/.test(params.get('cdate') || '') && params.get('cdate') >= etDay(MAX_DAYS_BACK) && params.get('cdate') <= today ? params.get('cdate') : today
  const isToday = picked === today
  const ctype = TYPES.some(([k]) => k === params.get('ctype')) ? params.get('ctype') : 'all'
  const page = Math.max(1, parseInt(params.get('cpage') || '1', 10) || 1)
  const sortKey = COLS.some(c => c.k === params.get('csort')) ? params.get('csort') : 'cancelled'
  const sortDir = params.get('cdir') === 'asc' ? 'asc' : 'desc'
  const filt = k => params.get('cf_' + k) || ''
  const set = (patch) => setParams(p => {
    const n = new URLSearchParams(p)
    for (const [k, v] of Object.entries(patch)) (v === '' || v == null || v === 'all' || v === 1) ? n.delete(k) : n.set(k, v)
    return n
  }, { replace: true })

  useEffect(() => {
    let live = true
    setBusy(true)
    const load = () => fetchCancellations(picked).then(d => { if (live) { setData(d); setError(null); setLeft(REFRESH_S) } })
      .catch(e => live && setError(e.response?.data?.detail || e.message))
      .finally(() => live && setBusy(false))
    load()
    if (!isToday) return () => { live = false }                   // a past day does not change: no polling
    const stop = pollWhileVisible(load, REFRESH_S * 1000)
    const tick = setInterval(() => setLeft(l => Math.max(0, l - 1)), 1000)
    return () => { live = false; stop(); clearInterval(tick) }
  }, [picked])

  const items = data?.items || []
  const options = useMemo(() => Object.fromEntries(COLS.filter(c => c.filter === 'select')
    .map(c => [c.k, [...new Set(items.map(c.val).filter(Boolean))].sort()])), [items])
  const shown = useMemo(() => {
    const out = items.filter(i => (ctype === 'all' || TYPE_OF[i.type] === ctype) && COLS.every(c => {
      const f = filt(c.k)
      if (!f) return true
      const v = String(c.val(i))
      return c.filter === 'text' ? norm(v).includes(norm(f)) : v === f
    }))
    const col = COLS.find(c => c.k === sortKey)
    out.sort((x, y) => { const a = col.val(x), b = col.val(y); return (a < b ? -1 : a > b ? 1 : 0) * (sortDir === 'asc' ? 1 : -1) })
    return out
  }, [items, ctype, params])                                   // eslint-disable-line react-hooks/exhaustive-deps
  const clickSort = k => set(k === sortKey ? { cdir: sortDir === 'asc' ? 'desc' : 'asc', cpage: 1 } : { csort: k, cdir: 'asc', cpage: 1 })
  const pages = Math.max(1, Math.ceil(shown.length / PAGE))
  const cur = Math.min(page, pages)
  const rows = shown.slice((cur - 1) * PAGE, cur * PAGE)
  const count = k => k === 'all' ? items.length : items.filter(i => TYPE_OF[i.type] === k).length
  const s = data?.summary

  if (!data && !error) return <div className="w-full h-full flex items-center justify-center bg-slate-950"><Loader2 className="w-6 h-6 animate-spin text-slate-500" /></div>
  if (!data) return <div className="p-6 text-sm text-red-300 flex items-center gap-2"><AlertTriangle className="w-4 h-4" /> {error}</div>

  return (
    <div className="h-full overflow-auto bg-slate-950 px-6 py-4 space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <input type="date" value={picked} min={etDay(MAX_DAYS_BACK)} max={today}
          onChange={e => e.target.value && set({ cdate: e.target.value === today ? '' : e.target.value, cpage: 1 })}
          style={{ colorScheme: 'dark' }} title="Pick a day (Eastern time)"
          className="bg-slate-900 border border-slate-700 rounded-md text-xs text-slate-200 px-2 py-1" />
        {busy && <Loader2 className="w-3.5 h-3.5 animate-spin text-slate-500" />}
        <Stat label="Cancelled" value={s.total} />
        <Stat label="Rate" value={s.rate_pct != null ? `${s.rate_pct}% of ${s.calls_today}` : '--'} />
        <Stat label="Avg wait" value={s.avg_minutes_before_cancel != null ? fmtWait(s.avg_minutes_before_cancel) : '--'} />
        {isToday && <span className="ml-auto text-[11px] text-slate-500">Next refresh in {left}s</span>}
        {s.by_reason.map(r => <span key={r.reason} className="text-[11px] text-slate-500">· {r.reason} <b className="text-slate-300">{r.count}</b></span>)}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {TYPES.map(([k, label]) => (
          <button key={k} onClick={() => set({ ctype: k, cpage: 1 })}
            className={clsx('px-3 py-1.5 rounded-md text-xs font-semibold border transition-all',
              ctype === k ? 'bg-indigo-600/20 border-indigo-500 text-indigo-200' : 'border-slate-700/60 text-slate-400 hover:text-white')}>
            {label} <span className={clsx(k === 'en-route' && count(k) > 0 ? 'text-red-300 font-bold' : 'opacity-70')}>{count(k)}</span>
          </button>
        ))}
      </div>

      <div className="rounded-lg border border-slate-700/50 overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-slate-900 text-slate-500 uppercase text-[10px] tracking-wide">
            <tr>
              {COLS.map(c => (
                <th key={c.k} onClick={() => clickSort(c.k)} className="text-left px-3 py-2 font-semibold cursor-pointer select-none whitespace-nowrap hover:text-slate-200">
                  {c.h} {sortKey === c.k ? (sortDir === 'asc' ? '▲' : '▼') : ''}
                </th>
              ))}
              <th />
            </tr>
            <tr className="normal-case">
              {COLS.map(c => (
                <th key={c.k} className="px-2 pb-2 font-normal">
                  {c.filter === 'text' && <input value={filt(c.k)} onChange={e => set({ ['cf_' + c.k]: e.target.value, cpage: 1 })} placeholder="Filter"
                    className="w-full bg-slate-950 border border-slate-700 rounded px-1.5 py-0.5 text-[11px] text-slate-200" />}
                  {c.filter === 'select' && <select value={filt(c.k)} onChange={e => set({ ['cf_' + c.k]: e.target.value, cpage: 1 })}
                    style={{ colorScheme: 'dark' }}                              // the open list is dark too, not light-on-light
                    className="w-full bg-slate-950 border border-slate-700 rounded px-1 py-0.5 text-[11px] text-slate-200">
                    <option value="" className="bg-slate-900 text-slate-100">All</option>
                    {options[c.k].map(o => <option key={o} value={o} className="bg-slate-900 text-slate-100">{o}</option>)}
                  </select>}
                </th>
              ))}
              <th />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {rows.map(i => (
              <tr key={i.id} className="hover:bg-slate-800/40">
                <td className="px-3 py-2 font-semibold text-indigo-300"><SALink number={i.number} /></td>
                <td className="px-3 py-2 text-slate-300 whitespace-nowrap">{i.work_order || '--'}</td>
                <td className="px-3 py-2 text-slate-200 whitespace-nowrap">{etTime(i.cancelled_et)}</td>
                <td className="px-3 py-2"><span className={clsx('px-2 py-0.5 rounded border text-[10px] font-semibold', BADGE[TYPE_OF[i.type]])}>{i.type}</span></td>
                <td className="px-3 py-2 text-slate-300" title={i.cancelled_by_profile || ''}>{i.cancelled_by || '--'}</td>
                <td className="px-3 py-2 text-slate-300">{i.garage}<Phone n={i.garage_phone} /></td>
                <td className="px-3 py-2 text-slate-300">{i.driver || '--'}<Phone n={i.driver_phone} /></td>
                <td className="px-3 py-2 text-slate-400">{i.reason}</td>
                <td className="px-3 py-2 text-slate-300 whitespace-nowrap">{fmtWait(i.minutes_before_cancel)}</td>
                <td className="px-3 py-2 text-slate-400 whitespace-nowrap">{i.pta_min != null ? `${Math.round(i.pta_min)} min` : '--'}</td>
                <td className="px-3 py-2 text-slate-400">{i.work_type || '--'}</td>
                <td className="px-3 py-2">
                  {i.en_route && !/towbook/i.test(i.dispatch_method || '')
                    ? <Link to={`/replay?sa=${encodeURIComponent(i.number)}`} className="inline-flex items-center gap-1 text-emerald-300 hover:text-emerald-200"><PlayCircle className="w-3.5 h-3.5" /> Replay</Link>
                    : null}
                </td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={12} className="px-3 py-10 text-center text-slate-500">{items.length === 0 ? `No cancellations ${isToday ? 'yet today' : 'on this day'}.` : 'No cancellations match.'}</td></tr>}
          </tbody>
        </table>
      </div>

      {pages > 1 && (
        <div className="flex items-center justify-end gap-3 text-xs text-slate-400">
          <span>{(cur - 1) * PAGE + 1}-{Math.min(cur * PAGE, shown.length)} of {shown.length}</span>
          <button disabled={cur <= 1} onClick={() => set({ cpage: cur - 1 })} className="px-2 py-1 rounded border border-slate-700 disabled:opacity-40">Prev</button>
          <button disabled={cur >= pages} onClick={() => set({ cpage: cur + 1 })} className="px-2 py-1 rounded border border-slate-700 disabled:opacity-40">Next</button>
        </div>
      )}
    </div>
  )
}
