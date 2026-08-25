import { useState, useEffect, useCallback } from 'react'
import { Search, Loader2, RefreshCw, AlertCircle } from 'lucide-react'

// UNRELEASED — rendered only when the backend `contractor_dispatch` flag is on.
// Dispatch board for a contractor's own garages. Read-only by design: no new
// call, no driver messaging, no surveys.

const BUCKETS = [
  ['current',   'Current'],
  ['waiting',   'Waiting'],
  ['active',    'Active'],
  ['completed', 'Completed'],
  ['scheduled', 'Scheduled'],
  ['cancelled', 'Cancelled'],
  ['unable',    'Unable to Complete'],
]

const STATUS_TONE = {
  'Assigned':    'bg-slate-500/15 text-slate-300 border-slate-500/30',
  'Dispatched':  'bg-blue-500/15 text-blue-300 border-blue-500/30',
  'Accepted':    'bg-indigo-500/15 text-indigo-300 border-indigo-500/30',
  'En Route':    'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  'On Location': 'bg-teal-500/15 text-teal-300 border-teal-500/30',
  'In Progress': 'bg-teal-500/15 text-teal-300 border-teal-500/30',
  'Completed':   'bg-slate-600/20 text-slate-400 border-slate-600/30',
}

const tone = s => STATUS_TONE[s] || 'bg-slate-700/20 text-slate-400 border-slate-600/30'

function age(iso) {
  if (!iso) return ''
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min`
  const h = Math.floor(mins / 60)
  return h < 24 ? `${h}h ${mins % 60}m` : `${Math.floor(h / 24)}d`
}

const clock = iso => iso
  ? new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  : ''

export default function ContractorDispatch() {
  const [bucket, setBucket] = useState('current')
  const [q, setQ] = useState('')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    setLoading(true); setErr('')
    const p = new URLSearchParams({ bucket })
    if (q.trim()) p.set('q', q.trim())
    fetch(`/api/contractor/dispatch?${p}`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(setData)
      .catch(e => setErr(e.message || 'Failed to load'))
      .finally(() => setLoading(false))
  }, [bucket, q])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    const t = setInterval(load, 60000)   // keep the board current
    return () => clearInterval(t)
  }, [load])

  const counts = data?.counts || {}
  const items = data?.items || []

  return (
    <div className="max-w-[1600px] mx-auto px-6 py-5">
      <div className="flex items-center gap-3 mb-4">
        <h1 className="text-xl font-semibold text-white">Dispatch</h1>
        <span className="text-xs text-slate-500">
          {data?.facilities?.length ? `${data.facilities.join(', ')}` : ''}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              value={q} onChange={e => setQ(e.target.value)}
              placeholder="Call #, WO #, vehicle, plate, address, driver"
              className="w-80 bg-slate-900 border border-slate-700 rounded-lg pl-8 pr-3 py-1.5
                         text-sm text-slate-200 placeholder-slate-600
                         focus:outline-none focus:border-brand-500"
            />
          </div>
          <button onClick={load} title="Refresh"
            className="p-2 rounded-lg border border-slate-700 text-slate-400 hover:text-white hover:bg-slate-800">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      <div className="flex gap-5">
        {/* bucket rail */}
        <aside className="w-52 flex-shrink-0">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-2 px-2">Choose a list</div>
          {BUCKETS.map(([key, label]) => (
            <button key={key} onClick={() => setBucket(key)}
              className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-sm mb-0.5 transition-all ${
                bucket === key
                  ? 'bg-brand-600/20 text-brand-300 font-medium'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
              }`}>
              <span>{label}</span>
              <span className="text-xs tabular-nums text-slate-500">({counts[key] ?? 0})</span>
            </button>
          ))}
        </aside>

        {/* call list */}
        <div className="flex-1 min-w-0">
          {err && (
            <div className="flex items-center gap-2 text-sm text-red-300 bg-red-500/10
                            border border-red-500/25 rounded-lg px-3 py-2 mb-3">
              <AlertCircle size={14} /> {err}
            </div>
          )}

          {loading && !data ? (
            <div className="flex items-center gap-2 text-slate-500 text-sm py-10 justify-center">
              <Loader2 size={16} className="animate-spin" /> Loading calls…
            </div>
          ) : items.length === 0 ? (
            <div className="text-center py-16 text-slate-500 text-sm">
              No calls in <span className="text-slate-300">{BUCKETS.find(b => b[0] === bucket)?.[1]}</span>
              {q.trim() && <> matching “{q.trim()}”</>}.
            </div>
          ) : (
            <div className="border border-slate-800 rounded-xl overflow-hidden">
              {items.map((c, i) => (
                <div key={c.sa_id}
                  className={`grid grid-cols-12 gap-4 px-4 py-3 text-sm ${
                    i % 2 ? 'bg-slate-900/40' : 'bg-slate-900/20'
                  } hover:bg-slate-800/50 border-b border-slate-800/60 last:border-0`}>

                  {/* call + vehicle */}
                  <div className="col-span-3 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-slate-500 tabular-nums">{c.sa_number}</span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded border ${tone(c.status)}`}>
                        {c.status}
                      </span>
                    </div>
                    <div className="text-slate-100 font-medium truncate mt-0.5">
                      {c.vehicle || c.work_type || '—'}
                    </div>
                    {c.plate && <div className="text-xs text-slate-500">{c.plate}</div>}
                  </div>

                  {/* location */}
                  <div className="col-span-4 min-w-0">
                    <div className="text-xs text-slate-500">Location</div>
                    <div className="text-slate-300 truncate">{c.address || '—'}</div>
                    <div className="text-xs text-slate-500 truncate">
                      {c.work_type}{c.reason ? ` · ${c.reason}` : ''}
                    </div>
                  </div>

                  {/* driver */}
                  <div className="col-span-2 min-w-0">
                    <div className="text-xs text-slate-500">Driver</div>
                    <div className={`truncate ${c.driver ? 'text-slate-300' : 'text-amber-400/80'}`}>
                      {c.driver || 'Unassigned'}
                    </div>
                    {c.truck && <div className="text-xs text-slate-500 truncate">{c.truck}</div>}
                  </div>

                  {/* account */}
                  <div className="col-span-2 min-w-0">
                    <div className="text-xs text-slate-500">Account</div>
                    <div className="text-slate-300 truncate">{c.account || c.territory || '—'}</div>
                    {c.coverage && <div className="text-xs text-slate-500">{c.coverage}</div>}
                  </div>

                  {/* timing */}
                  <div className="col-span-1 text-right">
                    <div className="text-xs text-slate-500">Age</div>
                    <div className="text-slate-300 tabular-nums">{age(c.created)}</div>
                    {c.eta && <div className="text-xs text-slate-500 tabular-nums">ETA {clock(c.eta)}</div>}
                  </div>
                </div>
              ))}
            </div>
          )}

          {data && (
            <div className="text-xs text-slate-600 mt-3">
              {items.length} shown · refreshes every 60s · your garages only
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
