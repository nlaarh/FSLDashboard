import { useState, useEffect, useRef } from 'react'
import { RefreshCw, ChevronDown, ChevronRight, AlertTriangle, CheckCircle, XCircle } from 'lucide-react'
import { optimizerGetRuns } from '../api'

const TERRITORY_DOT = {
  'WNY Fleet': 'bg-blue-500',
  '076DO':     'bg-purple-500',
  '089DO':     'bg-emerald-500',
}

function statusDot(run) {
  if (run.unscheduled_count > 5)  return 'bg-red-500'
  if (run.unscheduled_count > 0)  return 'bg-amber-400'
  return 'bg-emerald-500'
}

function fmtTime(iso) {
  if (!iso) return '?'
  return new Date(iso).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
}

function fmtDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const today = new Date()
  const yest  = new Date(today); yest.setDate(today.getDate() - 1)
  if (d.toDateString() === today.toDateString()) return 'Today'
  if (d.toDateString() === yest.toDateString())  return 'Yesterday'
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function schedDelta(run) {
  const d = (run.post_scheduled ?? 0) - (run.pre_scheduled ?? 0)
  if (d === 0) return null
  return d > 0 ? `+${d}` : `${d}`
}

export default function OptimizerTimeline({ onSelectRun, selectedId }) {
  const [runs, setRuns]         = useState([])
  const [loading, setLoading]   = useState(true)
  const [collapsed, setCollapsed] = useState({})
  const timerRef = useRef(null)

  const load = async () => {
    setLoading(true)
    try {
      const now  = new Date()
      const from = new Date(now - 7 * 24 * 3600 * 1000)
      const data = await optimizerGetRuns({ from_dt: from.toISOString(), to_dt: now.toISOString() })
      setRuns(data)
    } catch { /* ignore */ } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    timerRef.current = setInterval(load, 2 * 60 * 1000)
    return () => clearInterval(timerRef.current)
  }, [])

  // Group runs by date + territory
  const groups = []
  const seen   = {}
  for (const r of runs) {
    const date = fmtDate(r.run_at)
    const key  = `${date}__${r.territory_name}`
    if (!seen[key]) {
      seen[key] = { date, territory: r.territory_name, runs: [] }
      groups.push(seen[key])
    }
    seen[key].runs.push(r)
  }

  // Detect synthetic seed data (run names start with 'Seed-')
  const hasTestData = runs.some(r => (r.name || '').startsWith('Seed-'))

  return (
    <div className="flex flex-col h-full text-xs">
      {/* Header */}
      <div className="px-3 py-2.5 bg-slate-800/60 border-b border-slate-700/50 flex items-center gap-2 shrink-0">
        <span className="text-[11px] font-semibold text-slate-300 uppercase tracking-wide">Optimizer Runs</span>
        {hasTestData && (
          <span
            className="text-[9px] font-bold px-1.5 py-0.5 rounded tracking-wider"
            style={{ background: '#f59e0b', color: '#1c1917', letterSpacing: '0.08em' }}
            title="Currently showing synthetic test data, not real Salesforce dispatch decisions"
          >
            PREVIEW
          </span>
        )}
        <button
          onClick={load}
          title="Refresh"
          className="ml-auto text-slate-500 hover:text-slate-300 transition-colors p-0.5"
        >
          <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Run list */}
      <div className="flex-1 overflow-y-auto">
        {!loading && runs.length === 0 && (
          <div className="p-5 text-center text-[11px] text-slate-500 leading-relaxed">
            No runs in the last 7 days.<br />
            Sync checks every 15 min.
          </div>
        )}

        {groups.map(g => {
          const key    = `${g.date}__${g.territory}`
          const isOpen = collapsed[key] !== false   // default: open
          const dot    = TERRITORY_DOT[g.territory] || 'bg-slate-500'

          // Group-level summary
          const total        = g.runs.reduce((s, r) => s + (r.services_count ?? 0), 0)
          const totalUnsched = g.runs.reduce((s, r) => s + (r.unscheduled_count ?? 0), 0)

          return (
            <div key={key}>
              {/* Section header */}
              <button
                className="w-full px-3 py-2 flex items-center gap-2 bg-slate-900/50 hover:bg-slate-800/50 transition-colors text-left border-b border-slate-800/60"
                onClick={() => setCollapsed(s => ({ ...s, [key]: !isOpen }))}
              >
                {isOpen
                  ? <ChevronDown size={10} className="text-slate-500 shrink-0" />
                  : <ChevronRight size={10} className="text-slate-500 shrink-0" />
                }
                <span className={`w-2 h-2 rounded-full shrink-0 ${dot}`} />
                <span className="text-[11px] font-medium text-slate-300 truncate flex-1">{g.territory}</span>
                <span className="text-[10px] text-slate-500 shrink-0">{g.date}</span>
              </button>

              {/* Runs */}
              {isOpen && g.runs.map(r => {
                const active = selectedId === r.id
                const delta  = schedDelta(r)
                return (
                  <button
                    key={r.id}
                    className={`w-full px-4 py-2.5 text-left border-b border-slate-800/40 transition-colors
                      ${active
                        ? 'bg-brand-600/15 border-l-2 border-l-brand-500'
                        : 'hover:bg-slate-800/30 border-l-2 border-l-transparent'
                      }`}
                    onClick={() => onSelectRun(r)}
                  >
                    <div className="flex items-center gap-2">
                      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${statusDot(r)}`} />
                      <span className={`text-[11px] flex-1 ${active ? 'text-brand-300' : 'text-slate-300'}`}>
                        {fmtTime(r.run_at)}
                      </span>
                      {r.unscheduled_count > 0 && (
                        <span className="text-[10px] text-amber-400 flex items-center gap-0.5 shrink-0">
                          <AlertTriangle size={9} />{r.unscheduled_count}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2.5 mt-0.5 pl-3.5">
                      <span className="text-[10px] text-slate-500">{r.services_count ?? 0} SAs</span>
                      {delta && (
                        <span className={`text-[10px] font-mono ${delta.startsWith('+') ? 'text-emerald-500' : 'text-red-400'}`}>
                          {delta} sched
                        </span>
                      )}
                    </div>
                  </button>
                )
              })}
            </div>
          )
        })}
      </div>

      {/* Footer summary */}
      {runs.length > 0 && (
        <div className="px-3 py-2 border-t border-slate-800/60 bg-slate-900/30 shrink-0">
          <span className="text-[10px] text-slate-600">
            {runs.length} runs · last 7 days
          </span>
        </div>
      )}
    </div>
  )
}
