/**
 * OptimizerDecisionBrowser.jsx
 *
 * Hierarchical drill: pick run → garage(s) → SA → decision page.
 * - When the picked run has a batch_id, ALL sibling chunks (each one a separate
 *   territory's run) are loaded and rendered as their own garage section.
 * - Search box filters SAs across every garage in the batch.
 * - Each SA remembers its source run_id so the right pane resolves correctly.
 *
 * Right pane is OptimizerSADecisionPage (SAReport-style summary).
 */

import { useState, useEffect, useMemo } from 'react'
import {
  ChevronDown, ChevronRight, RefreshCw, Search, Warehouse,
  CheckCircle2, AlertTriangle, Pause, Sparkles, Info,
} from 'lucide-react'
import { optimizerGetRun, optimizerGetRuns } from '../api'
import OptimizerSADecisionPage from './OptimizerSADecisionPage'

// ── helpers ─────────────────────────────────────────────────────────────────
function parseUtc(iso) {
  if (!iso) return null
  return new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + 'Z')
}

function fmtClock(iso) {
  const d = parseUtc(iso); if (!d) return ''
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
}

// Normalize SA search input to match SA-XXXXXXXX format
function normalizeSA(input) {
  const s = (input || '').trim().toUpperCase()
  if (!s) return ''
  if (s.startsWith('SA-')) return s
  if (/^\d+$/.test(s)) return 'SA-' + s.padStart(8, '0')
  return s
}

const ACTION_GROUPS = [
  { key: 'Scheduled',   label: 'Scheduled',   color: '#4ade80', Icon: CheckCircle2 },
  { key: 'Unscheduled', label: 'Unscheduled', color: '#fbbf24', Icon: AlertTriangle },
  { key: 'Unchanged',   label: 'Unchanged',   color: '#94a3b8', Icon: Pause },
]

// ── Sub-group inside a garage ───────────────────────────────────────────────
function ActionGroup({ groupKey, label, color, Icon, decisions, selected, onPick, indent = 18 }) {
  const [open, setOpen] = useState(groupKey !== 'Unchanged')   // default-open, except Unchanged
  if (decisions.length === 0) return null
  return (
    <div>
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-1.5 hover:bg-slate-800/40 transition-colors text-left"
        style={{ paddingLeft: indent, paddingRight: 8, paddingTop: 4, paddingBottom: 4 }}
      >
        {open ? <ChevronDown size={10} className="text-slate-500" />
              : <ChevronRight size={10} className="text-slate-500" />}
        <Icon size={11} style={{ color }} />
        <span className="text-[11px] font-medium" style={{ color }}>{label}</span>
        <span className="text-[10px] text-slate-500 ml-auto">{decisions.length}</span>
      </button>
      {open && decisions.map(d => {
        const active = selected && selected.saNumber === d.sa_number && selected.runId === d._runId
        return (
          <button
            key={`${d._runId}__${d.id}`}
            onClick={() => onPick({ saNumber: d.sa_number, runId: d._runId })}
            className={`w-full text-left transition-colors border-l-2 ${
              active
                ? 'bg-indigo-600/15 border-l-indigo-500'
                : 'hover:bg-slate-800/30 border-l-transparent'
            }`}
            style={{ paddingLeft: indent + 18, paddingRight: 10, paddingTop: 4, paddingBottom: 4 }}
          >
            <div className="flex items-center gap-2">
              <span className={`text-[11px] font-mono ${active ? 'text-indigo-300' : 'text-slate-300'}`}>
                {d.sa_number}
              </span>
              {d.priority != null && (
                <span className="text-[9px] font-mono text-slate-500" title="Priority">
                  P{d.priority}
                </span>
              )}
              {d.sched_start && (
                <span className="text-[9px] text-slate-500 ml-auto">
                  {fmtClock(d.sched_start)}
                </span>
              )}
            </div>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className="text-[9px] text-slate-600 truncate flex-1">
                {d.sa_work_type || '—'}
              </span>
              {d.winner_driver_name && (
                <span className="text-[9px] text-emerald-500/80 truncate" title={d.winner_driver_name}
                      style={{ maxWidth: 90 }}>
                  → {d.winner_driver_name}
                </span>
              )}
            </div>
          </button>
        )
      })}
    </div>
  )
}

// ── Garage section ──────────────────────────────────────────────────────────
function GarageSection({ territory, runId, runName, chunkNum, decisions, selected, onPick, defaultOpen }) {
  const [open, setOpen] = useState(defaultOpen)
  const groups = useMemo(() => {
    const out = {}
    for (const d of decisions) {
      const k = d.action || 'Other'
      if (!out[k]) out[k] = []
      out[k].push(d)
    }
    for (const k of Object.keys(out)) {
      out[k].sort((a, b) => (b.priority ?? -1) - (a.priority ?? -1))
    }
    return out
  }, [decisions])

  // Detect "all unchanged" state for inline explainer
  const allUnchanged = decisions.length > 0
                       && (groups.Unchanged?.length || 0) === decisions.length

  return (
    <div className="border-b border-slate-800/40">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 px-3 py-2 bg-slate-900/60 hover:bg-slate-800/50 transition-colors text-left"
      >
        {open ? <ChevronDown size={11} className="text-slate-500" />
              : <ChevronRight size={11} className="text-slate-500" />}
        <Warehouse size={12} className="text-indigo-400" />
        <span className="text-[12px] font-semibold text-slate-200 truncate flex-1">
          {territory || '— Unknown Garage'}
        </span>
        {chunkNum != null && (
          <span className="text-[9px] font-mono text-amber-400/70" title={`Chunk ${chunkNum} · ${runName}`}>
            #{chunkNum}
          </span>
        )}
        <span className="text-[10px] text-slate-500">{decisions.length} SAs</span>
      </button>
      {open && (
        <div className="py-1">
          {allUnchanged && (
            <div className="mx-3 my-1 px-2 py-1.5 rounded bg-slate-800/40 border border-slate-700/40
                            flex items-start gap-1.5 text-[10px] text-slate-400 leading-snug">
              <Info size={10} className="text-slate-500 mt-px shrink-0" />
              <span>
                Optimizer ran but kept every prior assignment — In-Day Optimization only re-deliberates SAs that need it.
              </span>
            </div>
          )}
          {ACTION_GROUPS.map(g => (
            <ActionGroup key={g.key}
                         groupKey={g.key} label={g.label} color={g.color} Icon={g.Icon}
                         decisions={groups[g.key] || []}
                         selected={selected}
                         onPick={onPick} />
          ))}
          {Object.keys(groups)
            .filter(k => !ACTION_GROUPS.find(g => g.key === k))
            .map(k => (
              <ActionGroup key={k} groupKey={k} label={k} color="#94a3b8" Icon={Pause}
                           decisions={groups[k]}
                           selected={selected}
                           onPick={onPick} />
            ))}
        </div>
      )}
    </div>
  )
}

// ── Main Browser ────────────────────────────────────────────────────────────
export default function OptimizerDecisionBrowser({ run, onAskAI }) {
  // garages = [{ runId, runName, territory, chunkNum, decisions }]
  const [garages, setGarages]       = useState([])
  const [loading, setLoading]       = useState(false)
  const [batchInfo, setBatchInfo]   = useState(null)   // { batchId, fsl_type, policy_name, run_at }
  const [selected, setSelected]     = useState(null)   // { saNumber, runId }
  const [search, setSearch]         = useState('')

  useEffect(() => {
    if (!run?.id) {
      setGarages([]); setSelected(null); setBatchInfo(null); return
    }

    let cancelled = false
    setLoading(true)
    setSelected(null)

    const run_at_iso = run.run_at

    // 1. Load picked run's detail FIRST — this gives us its batch_id.
    optimizerGetRun(run.id).then(async (detail) => {
      if (cancelled) return
      const r = detail?.run || run
      const batchId = r.batch_id
      const decisions = (detail?.decisions || []).map(d => ({ ...d, _runId: r.id }))
      const pickedGarage = {
        runId: r.id,
        runName: r.name || run.name,
        territory: r.territory_name || run.territory_name,
        chunkNum: r.chunk_num ?? null,
        decisions,
      }

      setBatchInfo({
        batchId,
        fsl_type: r.fsl_type,
        policy_name: r.policy_name,
        run_at: r.run_at,
      })

      // 2. If part of a batch, find sibling chunks within ±20 min and load them in parallel.
      if (batchId) {
        try {
          const t = parseUtc(run_at_iso) || new Date()
          const from_dt = new Date(t.getTime() - 20 * 60 * 1000).toISOString()
          const to_dt   = new Date(t.getTime() + 20 * 60 * 1000).toISOString()
          const siblings = await optimizerGetRuns({ from_dt, to_dt })
          const sibIds = siblings
            .filter(s => s.batch_id === batchId && s.id !== r.id)
            .map(s => ({ id: s.id, name: s.name, territory_name: s.territory_name, chunk_num: s.chunk_num }))

          // Fetch each sibling's detail in parallel
          const sibDetails = await Promise.all(
            sibIds.map(s => optimizerGetRun(s.id).catch(() => null))
          )
          if (cancelled) return

          const sibGarages = sibDetails.map((det, i) => {
            if (!det) return null
            const dr = det.run || sibIds[i]
            return {
              runId: dr.id,
              runName: dr.name || sibIds[i].name,
              territory: dr.territory_name || sibIds[i].territory_name,
              chunkNum: dr.chunk_num ?? sibIds[i].chunk_num,
              decisions: (det.decisions || []).map(d => ({ ...d, _runId: dr.id })),
            }
          }).filter(Boolean)

          // Sort: picked run first, then by chunk_num
          const all = [pickedGarage, ...sibGarages].sort((a, b) => {
            if (a.runId === r.id) return -1
            if (b.runId === r.id) return 1
            return (a.chunkNum ?? 99) - (b.chunkNum ?? 99)
          })
          setGarages(all)
        } catch {
          setGarages([pickedGarage])
        }
      } else {
        setGarages([pickedGarage])
      }
    }).catch(() => {
      if (!cancelled) setGarages([])
    }).finally(() => {
      if (!cancelled) setLoading(false)
    })

    return () => { cancelled = true }
  }, [run?.id])

  // All decisions across all garages (used for search + footer counts)
  const allDecisions = useMemo(
    () => garages.flatMap(g => g.decisions),
    [garages],
  )

  // Search filter — applied across all garages
  const filtered = useMemo(() => {
    if (!search.trim()) return null
    const q = search.trim().toUpperCase()
    const exact = normalizeSA(search)
    return allDecisions.filter(d => {
      const sa = (d.sa_number || '').toUpperCase()
      return sa.includes(q) || sa === exact
    })
  }, [search, allDecisions])

  // ── Empty state when no run picked ──
  if (!run) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3 text-center px-6">
        <div className="w-10 h-10 rounded-xl bg-slate-800/60 border border-slate-700/40 flex items-center justify-center">
          <ChevronRight size={18} className="text-slate-600" />
        </div>
        <p className="text-slate-500 text-sm">Select a run from the left</p>
        <p className="text-slate-600 text-xs">Then drill into garages and SAs to see every decision</p>
      </div>
    )
  }

  return (
    <div className="flex h-full overflow-hidden">
      {/* ── Left rail ─────────────────────────────────────────────── */}
      <div className="w-72 border-r border-slate-700/50 flex flex-col shrink-0 overflow-hidden bg-slate-900/40">
        {/* Run header strip */}
        <div className="px-3 py-2.5 bg-slate-800/60 border-b border-slate-700/50 shrink-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[11px] font-semibold text-slate-200 truncate flex-1">
              {run.name || run.id}
            </span>
            {onAskAI && (
              <button
                onClick={() => onAskAI(run)}
                className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-md bg-brand-600/20 hover:bg-brand-600/30 text-brand-300 border border-brand-500/25 transition-colors"
              >
                <Sparkles size={9} />Ask AI
              </button>
            )}
          </div>
          <div className="text-[10px] text-slate-500 truncate">
            {fmtClock(run.run_at)}
            {batchInfo?.fsl_type && ` · ${batchInfo.fsl_type}`}
            {batchInfo?.policy_name && ` · ${batchInfo.policy_name}`}
          </div>
          {batchInfo?.batchId && garages.length > 1 && (
            <div className="text-[10px] text-amber-400/80 mt-1 truncate"
                 title={`Batch ${batchInfo.batchId}`}>
              Batch · {garages.length} garages · {allDecisions.length} SAs total
            </div>
          )}
        </div>

        {/* Search */}
        <div className="px-3 py-2 border-b border-slate-700/50 shrink-0">
          <div className="relative">
            <Search size={11} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search SA in this run…"
              className="w-full pl-7 pr-2 py-1.5 bg-slate-900/60 border border-slate-700/50 rounded text-[11px] text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500"
            />
          </div>
          {filtered && (
            <div className="text-[10px] text-slate-500 mt-1">
              {filtered.length} match{filtered.length !== 1 ? 'es' : ''}
            </div>
          )}
        </div>

        {/* Tree */}
        <div className="flex-1 overflow-y-auto">
          {loading && (
            <div className="flex items-center justify-center gap-2 py-6 text-slate-500 text-[11px]">
              <RefreshCw size={11} className="animate-spin" />
              Loading SAs…
            </div>
          )}

          {!loading && garages.length === 0 && (
            <div className="text-center text-[11px] text-slate-500 py-6 px-4">
              No SA decisions recorded for this run.
            </div>
          )}

          {!loading && filtered != null && (
            // Search-mode flat list — shows territory chip per row since results may span garages
            <div className="py-1">
              {filtered.length === 0 ? (
                <div className="text-center text-[11px] text-slate-600 py-4">
                  No SAs match “{search}”
                </div>
              ) : (
                filtered.map(d => {
                  const active = selected && selected.saNumber === d.sa_number && selected.runId === d._runId
                  const cfg = ACTION_GROUPS.find(g => g.key === d.action)
                  const garage = garages.find(g => g.runId === d._runId)
                  return (
                    <button
                      key={`${d._runId}__${d.id}`}
                      onClick={() => setSelected({ saNumber: d.sa_number, runId: d._runId })}
                      className={`w-full text-left transition-colors border-l-2 ${
                        active
                          ? 'bg-indigo-600/15 border-l-indigo-500'
                          : 'hover:bg-slate-800/30 border-l-transparent'
                      }`}
                      style={{ padding: '5px 12px' }}
                    >
                      <div className="flex items-center gap-2">
                        {cfg && <cfg.Icon size={10} style={{ color: cfg.color }} />}
                        <span className={`text-[11px] font-mono ${active ? 'text-indigo-300' : 'text-slate-300'}`}>
                          {d.sa_number}
                        </span>
                        {d.priority != null && (
                          <span className="text-[9px] font-mono text-slate-500">P{d.priority}</span>
                        )}
                        {d.sched_start && (
                          <span className="text-[9px] text-slate-500 ml-auto">
                            {fmtClock(d.sched_start)}
                          </span>
                        )}
                      </div>
                      <div className="text-[9px] text-slate-600 truncate mt-0.5">
                        {garage && (
                          <span className="text-indigo-400/70 mr-1">
                            {garage.territory?.split(' - ')[0] || '?'} ·
                          </span>
                        )}
                        {d.sa_work_type || '—'}
                        {d.winner_driver_name && <span className="text-emerald-500/80"> → {d.winner_driver_name}</span>}
                      </div>
                    </button>
                  )
                })
              )}
            </div>
          )}

          {!loading && filtered == null && garages.map(g => (
            <GarageSection
              key={g.runId}
              territory={g.territory}
              runId={g.runId}
              runName={g.runName}
              chunkNum={g.chunkNum}
              decisions={g.decisions}
              selected={selected}
              onPick={setSelected}
              defaultOpen={g.runId === run.id}   // only the picked run is auto-expanded
            />
          ))}
        </div>

        {/* Footer counts */}
        {allDecisions.length > 0 && (
          <div className="px-3 py-2 border-t border-slate-800/60 bg-slate-900/40 shrink-0 flex gap-3 text-[10px] flex-wrap">
            {ACTION_GROUPS.map(g => {
              const c = allDecisions.filter(d => d.action === g.key).length
              if (c === 0) return null
              return (
                <span key={g.key} style={{ color: g.color }} className="font-medium">
                  {c} {g.label.toLowerCase()}
                </span>
              )
            })}
          </div>
        )}
      </div>

      {/* ── Right pane (decision page) ────────────────────────────── */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <OptimizerSADecisionPage
          runId={selected?.runId}
          saNumber={selected?.saNumber}
          runMeta={garages.find(g => g.runId === selected?.runId)
                   ? { territory_name: garages.find(g => g.runId === selected?.runId).territory }
                   : null}
        />
      </div>
    </div>
  )
}
