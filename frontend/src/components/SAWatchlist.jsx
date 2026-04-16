/**
 * SAWatchlist.jsx
 *
 * Self-contained watchlist of SAs that dispatchers should follow closely:
 * manually reassigned, driver-rejected, or dispatch-thrashed SAs.
 * Auto-refreshes every 60 seconds.
 * Reuses DriverRow + CheckpointTracker from LiveDispatchUtils (no duplication).
 */

import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { clsx } from 'clsx'
import {
  Star, Search, Clock, Lock, AlertTriangle, HelpCircle,
  Loader2, User, Radio, CheckCircle2, X,
} from 'lucide-react'
import { SAWithTimeline, fmtDuration } from './LiveDispatchUtils'
import CheckpointTracker from './CheckpointTracker'
import DriverMapPopup from './DriverMapPopup'
import { fetchWatchlist, unfollowSA } from '../api'

// ── Time helpers ────────────────────────────────────────────────────────────

function toET(utcStr) {
  if (!utcStr) return '--'
  try {
    const d = new Date(utcStr)
    return d.toLocaleTimeString('en-US', {
      timeZone: 'America/New_York',
      hour: 'numeric', minute: '2-digit', hour12: true,
    }) + ' ET'
  } catch { return '--' }
}

function minutesAgo(utcStr) {
  if (!utcStr) return null
  return Math.round((Date.now() - new Date(utcStr).getTime()) / 60000)
}

// ── Main Component ──────────────────────────────────────────────────────────

export default function SAWatchlist() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState('')
  const [countdown, setCountdown] = useState(60)
  const [mapDriver, setMapDriver] = useState(null)
  const [showHelp, setShowHelp] = useState(false)
  const searchRef = useRef(null)

  // ── Data fetching with auto-refresh ──
  useEffect(() => {
    const load = () => {
      fetchWatchlist()
        .then(d => { setData(d); setCountdown(60); setError(null) })
        .catch(e => setError(e.message))
        .finally(() => setLoading(false))
    }
    load()
    const iv = setInterval(load, 60000)
    return () => clearInterval(iv)
  }, [])

  // ── Countdown ticker ──
  useEffect(() => {
    const t = setInterval(() => setCountdown(c => Math.max(c - 1, 0)), 1000)
    return () => clearInterval(t)
  }, [])

  // ── Keyboard shortcuts ──
  useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        searchRef.current?.focus()
      }
      if (e.key === 'Escape') {
        setSearch('')
        searchRef.current?.blur()
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [])

  // ── Unfollow (remove manual follow, instant + refetch) ──
  const handleUnfollow = useCallback((sa) => {
    unfollowSA(sa.sa_number).catch(() => {})
    // Optimistic remove from local data
    setData(prev => {
      if (!prev) return prev
      return {
        ...prev,
        watchlist: prev.watchlist.filter(w => w.sa_number !== sa.sa_number),
        total: Math.max(0, (prev.total || 0) - 1),
      }
    })
  }, [])

  // ── Search filter ──
  const filtered = useMemo(() => {
    return (data?.watchlist || []).filter(item => {
      if (!search) return true
      const q = search.toLowerCase()
      const haystack = [
        item.sa_number, item.driver_name, item.territory, item.human_dispatcher,
      ].filter(Boolean).join(' ').toLowerCase()
      return haystack.includes(q)
    })
  }, [data, search])

  // ── Loading state ──
  if (loading && !data) {
    return (
      <div className="flex items-center justify-center h-full bg-slate-950">
        <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
      </div>
    )
  }

  const totalCount = data?.watchlist?.length ?? 0

  return (
    <div className="w-full h-full bg-slate-950 overflow-y-auto">
      {/* ── Error banner ────────────────────────────────────────────── */}
      {error && (
        <div className="mx-6 mt-2 px-4 py-2 rounded-lg bg-red-950/40 border border-red-800/40 text-red-400 text-xs flex items-center gap-2">
          <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
          <span>Failed to refresh: {error}</span>
        </div>
      )}

      <div className="max-w-7xl mx-auto px-6 pt-4 pb-8 space-y-4">
        {/* ── Header ──────────────────────────────────────────────────── */}
        <div className="flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-2 flex-shrink-0">
            <Star className="w-5 h-5 text-amber-400" />
            <div>
              <h2 className="text-base font-bold text-white leading-tight">SA Watchlist</h2>
              <p className="text-[10px] text-slate-500">Auto-tracked SAs requiring dispatcher attention</p>
            </div>
            <button onClick={() => setShowHelp(true)} className="text-slate-500 hover:text-amber-400 transition-colors" title="How to use the Watchlist">
              <HelpCircle className="w-4 h-4" />
            </button>
          </div>

          {/* Search */}
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 pointer-events-none" />
            <input
              ref={searchRef}
              type="text"
              placeholder="Search SA, driver, or garage..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full pl-8 pr-8 py-2 bg-slate-800/70 border border-slate-700/50 rounded-lg text-xs font-mono
                         placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-amber-500/40 focus:border-amber-500/40"
            />
            {search && (
              <button onClick={() => setSearch('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white">
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          {/* Live indicator + count */}
          <div className="flex items-center gap-3 flex-shrink-0 ml-auto">
            <div className="flex items-center gap-1.5 text-[10px] text-slate-500 font-mono">
              <Radio className="w-3 h-3 text-emerald-400 animate-pulse" />
              <span>LIVE</span>
              <span className="tabular-nums">{countdown}s</span>
            </div>
            <span className="text-[10px] font-bold font-mono px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-400 border border-amber-500/30">
              {totalCount} watched
            </span>
          </div>
        </div>

        {/* ── Empty state ─────────────────────────────────────────────── */}
        {totalCount === 0 && !loading && (
          <div className="bg-slate-800/30 border border-emerald-800/30 rounded-xl py-12 text-center">
            <CheckCircle2 className="w-8 h-8 text-emerald-500 mx-auto mb-2" />
            <p className="text-sm font-medium text-emerald-400">All clear — no SAs currently need close monitoring</p>
          </div>
        )}

        {/* ── No search results ───────────────────────────────────────── */}
        {totalCount > 0 && filtered.length === 0 && (
          <div className="text-center py-12 text-xs text-slate-500 font-mono">
            No SAs match "{search}"
          </div>
        )}

        {/* ── Table using DriverRow (same as Live Board) ──────────────── */}
        {filtered.length > 0 && (
          <div className="bg-slate-800/50 backdrop-blur border border-slate-700/50 rounded-xl overflow-visible">
            {/* Column headers — exact same grid as ERS Live Board */}
            <div className="grid grid-cols-[40px_1fr_2.5fr_36px] items-center gap-2 px-3 py-2 border-b border-slate-700/50 text-[10px] text-slate-500 uppercase tracking-wider font-semibold">
              <div />
              <div>Driver / SA</div>
              <div>Progress</div>
              <div />
            </div>

            {/* Rows — exact same grid layout as ERS Live Board */}
            {filtered.map(sa => {
              const isStuck = (sa.flag || '').toString().toLowerCase() === 'stuck'
              const completedAgo = minutesAgo(sa.completed_at)
              const isRecentlyCompleted = completedAgo != null && completedAgo <= 5

              return (
                <div key={sa.sa_id} className={clsx(
                  'border-b border-slate-800/40 transition-colors',
                  isRecentlyCompleted && 'opacity-50',
                  isStuck && 'bg-red-950/20',
                  !isStuck && 'hover:bg-slate-800/60',
                )}>
                  {/* Main row — same grid as Live Board */}
                  <div className="grid grid-cols-[40px_1fr_2.5fr_36px] items-center gap-2 px-3 py-2">
                    {/* Avatar */}
                    <div className="flex items-center justify-center">
                      <div className={clsx(
                        'w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold',
                        sa.channel === 'Fleet' && 'bg-indigo-600/30 text-indigo-400',
                        sa.channel === 'On-Platform' && 'bg-cyan-600/30 text-cyan-400',
                        sa.channel === 'Off-Platform' && 'bg-amber-600/30 text-amber-400',
                        !sa.channel && 'bg-slate-700/60 text-slate-300',
                      )}>
                        {(sa.driver_name || '??').split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase()}
                      </div>
                    </div>

                    {/* Driver name + SA number + territory */}
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <button
                          onClick={(e) => { e.stopPropagation(); setMapDriver(sa) }}
                          className="text-sm text-white font-medium truncate hover:text-blue-400 transition-colors text-left cursor-pointer"
                          title="View on map"
                        >
                          {sa.driver_name || 'Unassigned'}
                        </button>
                        <SAWithTimeline number={sa.sa_number} driver={sa} />
                      </div>
                      <div className="text-[10px] text-slate-500 truncate">{sa.territory || '—'}</div>
                    </div>

                    {/* Checkpoint tracker — with saInfo for tooltips */}
                    <div className="px-1">
                      <CheckpointTracker
                        phases={sa.phases || []}
                        isStuck={isStuck}
                        saInfo={{ work_type: sa.work_type, address: sa.address, description: sa.description }}
                      />
                    </div>

                    {/* Star: unfollow (manual) or lock (auto-detected) */}
                    {sa.manual_follow ? (
                      <button
                        onClick={(e) => { e.stopPropagation(); handleUnfollow(sa) }}
                        title="Remove from Watchlist"
                        className="p-1.5 rounded-md transition-all flex-shrink-0 text-amber-400 bg-amber-500/15 hover:bg-red-500/20 hover:text-red-400"
                      >
                        <Star className="w-3.5 h-3.5 fill-amber-400 hover:fill-red-400" />
                      </button>
                    ) : (
                      <div
                        title="Auto-tracked (manual reassign / rejection / thrash)"
                        className="p-1.5 flex-shrink-0 text-slate-600"
                      >
                        <Lock className="w-3.5 h-3.5" />
                      </div>
                    )}
                  </div>

                  {/* Watchlist context — reason + dispatcher */}
                  <div className="px-12 pb-2 flex items-center gap-4 flex-wrap text-[10px]">
                    {sa.reason && (
                      <span className={clsx('font-mono', isStuck ? 'text-red-400' : 'text-amber-400')}>
                        ⚡ {sa.reason}
                      </span>
                    )}
                    {sa.human_dispatcher && (
                      <span className="flex items-center gap-1 text-slate-400">
                        <User className="w-2.5 h-2.5" /> {sa.human_dispatcher}
                      </span>
                    )}
                    {isRecentlyCompleted && (
                      <span className="font-bold px-1.5 py-0.5 rounded bg-green-950/40 text-green-400 border border-green-500/30">
                        Completed {completedAgo}m ago
                      </span>
                    )}
                  </div>
                </div>
              )
            })}

            {/* Footer */}
            <div className="px-3 py-2 text-[10px] text-slate-600 font-mono flex justify-between">
              <span>Showing {filtered.length} of {totalCount} watched SAs</span>
              <span>Auto-follow: manual reassign · driver reject · 3+ driver swaps</span>
            </div>
          </div>
        )}
      </div>

      {/* ── Driver Map Popup ────────────────────────────────────────── */}
      {mapDriver && (
        <DriverMapPopup driver={mapDriver} onClose={() => setMapDriver(null)} />
      )}

      {/* Help modal */}
      {showHelp && (
        <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={() => setShowHelp(false)}>
          <div className="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl max-w-lg w-full mx-4 overflow-hidden" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
              <h2 className="text-sm font-bold text-white">How to Use the SA Watchlist</h2>
              <button onClick={() => setShowHelp(false)} className="text-slate-500 hover:text-white"><X className="w-4 h-4" /></button>
            </div>
            <div className="px-5 py-4 space-y-3 text-xs text-slate-300 max-h-[70vh] overflow-y-auto">
              <div>
                <h3 className="font-bold text-white mb-1">What is this?</h3>
                <p className="text-slate-400">The Watchlist shows SAs that need close dispatcher attention. It combines auto-detected problem calls with SAs you've manually starred from the ERS Live Board.</p>
              </div>
              <div>
                <h3 className="font-bold text-white mb-1">How SAs get here</h3>
                <div className="space-y-1.5 text-slate-400">
                  <p><span className="text-amber-400 font-bold">Auto-tracked</span> (lock icon) — The system automatically adds SAs when:</p>
                  <ul className="list-disc list-inside pl-2 space-y-0.5">
                    <li>A human dispatcher manually reassigned the driver</li>
                    <li>A driver rejected the call</li>
                    <li>3 or more different drivers were assigned (dispatch thrash)</li>
                  </ul>
                  <p><span className="text-amber-400 font-bold">Manually starred</span> (star icon) — Any dispatcher can star an SA from the ERS Live Board to add it here. Visible to all dispatchers.</p>
                </div>
              </div>
              <div>
                <h3 className="font-bold text-white mb-1">★ Star vs Lock</h3>
                <p className="text-slate-400"><span className="text-amber-400">★ Filled star</span> = manually followed. Click to remove from watchlist. <span className="text-slate-400">🔒 Lock</span> = auto-tracked by the system. Cannot be manually removed — drops automatically when the SA completes.</p>
              </div>
              <div>
                <h3 className="font-bold text-white mb-1">Context Row</h3>
                <p className="text-slate-400">Below each SA row you'll see: <span className="text-amber-400">why it's being watched</span> (e.g., "8 reassignments, driver rejected"), the <span className="text-slate-300">human dispatcher</span> managing it, and the created time.</p>
              </div>
              <div>
                <h3 className="font-bold text-white mb-1">Progress Tracker + Tooltips</h3>
                <p className="text-slate-400">Same as the Live Board — hover any checkpoint dot for phase details, hover the SA number for the full timeline. Click a driver name for the map popup.</p>
              </div>
              <div>
                <h3 className="font-bold text-white mb-1">Auto-Cleanup</h3>
                <p className="text-slate-400">Completed and canceled SAs are automatically removed from the watchlist. No manual cleanup needed.</p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
