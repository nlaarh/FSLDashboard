/**
 * LiveDispatchBoard.jsx
 *
 * ERS Live Dispatch Board — real-time driver progress dashboard.
 * Shows all active SAs with checkpoint trackers, search, filters, and drill-down.
 * Auto-refreshes every 60 seconds.
 *
 * Shared sub-components live in LiveDispatchUtils.jsx to stay under 600 lines.
 */

import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { clsx } from 'clsx'
import {
  Search, Radio, AlertTriangle, Clock, Star, RefreshCw,
  Filter, Activity, Loader2, X, HelpCircle,
} from 'lucide-react'
import { fetchLiveDispatch, fetchWatchlistManual, followSA, unfollowSA } from '../api'
import { KpiStrip, PhaseFunnel, DriverRow, FlagBadge, AgingBadge, StatusChip, SAWithTimeline, fmtDuration } from './LiveDispatchUtils'
import CheckpointTracker from './CheckpointTracker'
import { DrillDown } from './CommandCenterUtils'
import SALink from './SALink'
import DriverMapPopup from './DriverMapPopup'

// ── Phase & Channel constants ────────────────────────────────────────────────
const PHASES = ['Dispatched', 'Accepted', 'En Route', 'On Location', 'In Progress']
const CHANNELS = ['Fleet', 'On-Platform', 'Off-Platform']

// ── Chip toggle helper ───────────────────────────────────────────────────────
function toggleFilter(current, setCurrent, value) {
  setCurrent(current === value ? null : value)
}

// ── Filter chip button ───────────────────────────────────────────────────────
function Chip({ label, active, onClick, variant = 'default', count }) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        'px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 border',
        variant === 'flag' && active && 'bg-red-500/25 text-red-300 border-red-400/60 ring-1 ring-red-500/30',
        variant === 'flag' && !active && 'text-slate-500 hover:text-red-400 hover:bg-red-950/20 border-slate-700/40',
        variant === 'default' && active && 'bg-amber-500/20 text-amber-300 border-amber-400/60 ring-1 ring-amber-500/30',
        variant === 'default' && !active && 'text-slate-500 hover:text-slate-300 hover:bg-slate-800/40 border-slate-700/40',
      )}
    >
      {variant === 'flag' && <AlertTriangle className="w-3 h-3" />}
      {label}
      {count != null && (
        <span className={clsx(
          'text-[10px] font-mono px-1.5 py-0.5 rounded-full',
          active ? 'bg-white/15 text-white' : 'bg-slate-800/60',
        )}>{count}</span>
      )}
    </button>
  )
}

// ── SA Detail drill-down content ─────────────────────────────────────────────
function SADrillDetail({ saNumber }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    lookupSA(saNumber)
      .then(setData)
      .catch(e => setError(e.message || 'Failed to load SA details'))
      .finally(() => setLoading(false))
  }, [saNumber])

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-slate-500 py-4 justify-center">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading SA details...
      </div>
    )
  }

  if (error) {
    return <div className="text-xs text-red-400 py-2 text-center">{error}</div>
  }

  if (!data) {
    return <div className="text-xs text-slate-600 py-3 text-center">No data found</div>
  }

  const history = data.history || data.status_changes || []

  return (
    <div className="space-y-2 py-1">
      {/* SA summary row */}
      <div className="flex items-center gap-3 text-xs">
        <SALink number={saNumber} className="text-xs" />
        {data.work_type && (
          <span className="text-slate-400">{data.work_type}</span>
        )}
        {data.territory && (
          <span className="text-slate-500 font-mono">{data.territory}</span>
        )}
        {data.member_name && (
          <span className="text-slate-500">Member: {data.member_name}</span>
        )}
      </div>

      {/* Timeline of status changes */}
      {history.length > 0 ? (
        <div className="space-y-0.5">
          <div className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold mb-1">
            Status Timeline
          </div>
          {history.map((entry, i) => (
            <div key={i} className="flex items-center gap-2 text-xs py-0.5">
              <span className="text-slate-600 font-mono w-32 flex-shrink-0">
                {entry.timestamp || entry.created_date || '—'}
              </span>
              <span className={clsx(
                'font-medium',
                entry.new_value === 'Completed' && 'text-emerald-400',
                entry.new_value === 'Canceled' && 'text-red-400',
                entry.new_value === 'Dispatched' && 'text-blue-400',
                entry.new_value === 'En Route' && 'text-cyan-400',
                entry.new_value === 'On Location' && 'text-amber-400',
                !['Completed', 'Canceled', 'Dispatched', 'En Route', 'On Location'].includes(entry.new_value) && 'text-slate-300',
              )}>
                {entry.new_value || entry.status || '—'}
              </span>
              {entry.old_value && (
                <span className="text-slate-600">from {entry.old_value}</span>
              )}
              {entry.driver_name && (
                <span className="text-slate-500 ml-auto">{entry.driver_name}</span>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="text-xs text-slate-600 py-2">No status history available</div>
      )}

      {/* Driver assignments */}
      {data.assignments && data.assignments.length > 0 && (
        <div className="space-y-0.5 mt-2">
          <div className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold mb-1">
            Driver Assignments
          </div>
          {data.assignments.map((a, i) => (
            <div key={i} className="flex items-center gap-2 text-xs py-0.5">
              <span className="text-slate-600 font-mono w-32 flex-shrink-0">
                {a.created_date || '—'}
              </span>
              <span className="text-slate-300 font-medium">{a.resource_name || '—'}</span>
              {a.dispatch_method && (
                <span className="text-slate-500 text-[10px]">({a.dispatch_method})</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Expandable table row ─────────────────────────────────────────────────────
function ExpandableDriverRow({ driver, onDriverClick, isFollowed, onToggleFollow }) {

  return (
    <div className={clsx(
      'border-b border-slate-800/40 transition-colors',
      driver.flag && 'bg-red-950/20',
      !driver.flag && 'hover:bg-slate-800/60',
    )}>
      {/* Main row */}
      <div className="grid grid-cols-[40px_1fr_2.5fr_36px] items-center gap-2 px-3 py-2">
        {/* Avatar */}
        <div className="flex items-center justify-center">
          <div className={clsx(
            'w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold',
            driver.channel === 'Fleet' && 'bg-indigo-600/30 text-indigo-400',
            driver.channel === 'On-Platform' && 'bg-cyan-600/30 text-cyan-400',
            driver.channel === 'Off-Platform' && 'bg-amber-600/30 text-amber-400',
          )}>
            {(driver.driver_name || '??').split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase()}
          </div>
        </div>

        {/* Driver name + SA + territory */}
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <button
              onClick={(e) => { e.stopPropagation(); onDriverClick?.(driver) }}
              className="text-sm text-white font-medium truncate hover:text-blue-400 transition-colors text-left cursor-pointer"
              title="View on map"
            >
              {driver.driver_name}
            </button>
            <SAWithTimeline number={driver.sa_number} driver={driver} />
          </div>
          <div className="text-[10px] text-slate-500 truncate">{driver.territory || '—'}</div>
        </div>

        {/* Checkpoint tracker */}
        <div className="px-1">
          <CheckpointTracker phases={driver.phases || []} isStuck={!!driver.flag} saInfo={{ work_type: driver.work_type, address: driver.address, description: driver.description }} />
        </div>

        {/* Follow / unfollow star */}
        <button
          onClick={(e) => { e.stopPropagation(); onToggleFollow?.(driver) }}
          title={isFollowed ? 'Remove from Watchlist' : 'Add to Watchlist'}
          className={clsx(
            'p-1.5 rounded-md transition-all flex-shrink-0',
            isFollowed
              ? 'text-amber-400 bg-amber-500/15 hover:bg-amber-500/25'
              : 'text-slate-600 hover:text-amber-400 hover:bg-slate-800/60',
          )}
        >
          <Star className={clsx('w-3.5 h-3.5', isFollowed && 'fill-amber-400')} />
        </button>
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ══════════════════════════════════════════════════════════════════════════════
export default function LiveDispatchBoard() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState('')
  const [phaseFilter, setPhaseFilter] = useState(null)
  const [channelFilter, setChannelFilter] = useState(null)
  const [flagFilter, setFlagFilter] = useState(false)
  const [countdown, setCountdown] = useState(60)
  const [mapDriver, setMapDriver] = useState(null)
  const [showHelp, setShowHelp] = useState(false)

  const searchRef = useRef(null)

  // ── Data fetching with 60s auto-refresh ──────────────────────────────────
  useEffect(() => {
    const load = () => {
      fetchLiveDispatch()
        .then(d => { setData(d); setError(null); setCountdown(60) })
        .catch(e => setError(e.message))
        .finally(() => setLoading(false))
    }
    load()
    const iv = setInterval(load, 60000)
    return () => clearInterval(iv)
  }, [])

  // ── Manual watchlist follow state (shared across all dispatchers) ─────────
  const [followedSAs, setFollowedSAs] = useState(new Set())

  useEffect(() => {
    fetchWatchlistManual().then(d => setFollowedSAs(new Set(d.followed || []))).catch(() => {})
  }, [])

  const toggleFollow = useCallback((driver) => {
    const saNum = driver.sa_number
    if (followedSAs.has(saNum)) {
      unfollowSA(saNum).catch(() => {})
      setFollowedSAs(prev => { const s = new Set(prev); s.delete(saNum); return s })
    } else {
      followSA(saNum, driver.sa_id || '').catch(() => {})
      setFollowedSAs(prev => new Set(prev).add(saNum))
    }
  }, [followedSAs])

  // ── Countdown timer ──────────────────────────────────────────────────────
  useEffect(() => {
    const t = setInterval(() => setCountdown(c => Math.max(0, c - 1)), 1000)
    return () => clearInterval(t)
  }, [])

  // ── Keyboard shortcuts ───────────────────────────────────────────────────
  useEffect(() => {
    const handleKey = (e) => {
      // Cmd+K or Ctrl+K focuses search
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        searchRef.current?.focus()
      }
      // Escape clears search and all filters
      if (e.key === 'Escape') {
        setSearch('')
        setPhaseFilter(null)
        setChannelFilter(null)
        setFlagFilter(false)
        searchRef.current?.blur()
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [])

  // ── Filtering ────────────────────────────────────────────────────────────
  const filtered = useMemo(() => {
    return (data?.drivers || []).filter(d => {
      if (search) {
        const q = search.toLowerCase()
        const haystack = `${d.driver_name} ${d.sa_number} ${d.territory}`.toLowerCase()
        if (!haystack.includes(q)) return false
      }
      if (phaseFilter && d.current_status.toLowerCase() !== phaseFilter.toLowerCase()) return false
      if (channelFilter && d.channel !== channelFilter) return false
      if (flagFilter && !d.flag) return false
      return true
    })
  }, [data, search, phaseFilter, channelFilter, flagFilter])

  // ── Phase counts for chip badges ─────────────────────────────────────────
  const phaseCounts = useMemo(() => {
    const counts = {}
    PHASES.forEach(p => { counts[p] = 0 })
    ;(data?.drivers || []).forEach(d => {
      const s = d.current_status
      if (counts[s] != null) counts[s]++
    })
    return counts
  }, [data])

  const channelCounts = useMemo(() => {
    const counts = {}
    CHANNELS.forEach(c => { counts[c] = 0 })
    ;(data?.drivers || []).forEach(d => {
      if (counts[d.channel] != null) counts[d.channel]++
    })
    return counts
  }, [data])

  const flagCount = useMemo(() => (data?.drivers || []).filter(d => d.flag).length, [data])

  const hasActiveFilters = phaseFilter || channelFilter || flagFilter || search

  const clearAllFilters = useCallback(() => {
    setSearch('')
    setPhaseFilter(null)
    setChannelFilter(null)
    setFlagFilter(false)
  }, [])

  // ── Loading state ────────────────────────────────────────────────────────
  if (loading && !data) {
    return (
      <div className="flex items-center justify-center h-full bg-slate-950">
        <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
      </div>
    )
  }

  return (
    <div className="w-full h-full bg-slate-950 overflow-y-auto">
      {/* ── Error banner (non-blocking — keeps stale data visible) ──────── */}
      {error && (
        <div className="mx-6 mt-2 px-4 py-2 rounded-lg bg-red-950/40 border border-red-800/40 text-red-400 text-xs flex items-center gap-2">
          <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
          <span>Failed to refresh: {error}</span>
          <span className="text-red-600 ml-auto">Showing stale data</span>
        </div>
      )}

      {/* ── Header bar ─────────────────────────────────────────────────── */}
      <div className="sticky top-0 z-30 bg-slate-950/95 backdrop-blur border-b border-slate-800/50 px-6 py-3">
        <div className="max-w-7xl mx-auto flex items-center gap-4">
          {/* Title */}
          <div className="flex items-center gap-2 flex-shrink-0">
            <Activity className="w-5 h-5 text-blue-400" />
            <h1 className="text-lg font-bold text-white tracking-tight">ERS Live Dispatch Board</h1>
            <button onClick={() => setShowHelp(true)} className="text-slate-500 hover:text-blue-400 transition-colors" title="How to use this board">
              <HelpCircle className="w-4 h-4" />
            </button>
          </div>

          {/* Search input — centered, prominent */}
          <div className="flex-1 max-w-md mx-auto relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input
              ref={searchRef}
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search driver, SA number, or garage..."
              className="w-full pl-9 pr-8 py-2 rounded-lg bg-slate-800/60 border border-slate-700/50 text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/20 transition-colors"
            />
            {search && (
              <button
                onClick={() => setSearch('')}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white transition-colors"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
            <kbd className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[9px] text-slate-600 bg-slate-800 border border-slate-700 rounded px-1 py-0.5 pointer-events-none" style={{ display: search ? 'none' : 'block' }}>
              {"\u2318"}K
            </kbd>
          </div>

          {/* Live indicator + countdown */}
          <div className="flex items-center gap-2 flex-shrink-0">
            <div className="flex items-center gap-1.5">
              <span className="relative flex h-2.5 w-2.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
              </span>
              <span className="text-xs text-emerald-400 font-semibold">LIVE</span>
              <span className="text-xs text-slate-500 font-mono">{"\u00B7"} 60s</span>
            </div>
            <div className="flex items-center gap-1 text-xs text-slate-500 ml-2">
              <RefreshCw className={clsx('w-3 h-3', countdown <= 5 && 'animate-spin text-blue-400')} />
              <span className="font-mono w-6 text-right">{countdown}s</span>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 pt-4 pb-8 space-y-4">
        {/* ── KPI Strip ──────────────────────────────────────────────── */}
        {data?.kpis && <KpiStrip kpis={data.kpis} />}

        {/* ── Filter bar ─────────────────────────────────────────────── */}
        <div className="bg-slate-800/50 backdrop-blur border border-slate-700/50 rounded-xl p-3">
          <div className="flex items-center gap-2 flex-wrap">
            <Filter className="w-3.5 h-3.5 text-slate-500 flex-shrink-0" />

            {/* Phase chips */}
            <div className="flex items-center gap-1">
              {PHASES.map(phase => (
                <Chip
                  key={phase}
                  label={phase}
                  active={phaseFilter === phase}
                  onClick={() => toggleFilter(phaseFilter, setPhaseFilter, phase)}
                  count={phaseCounts[phase] || 0}
                />
              ))}
            </div>

            <div className="w-px h-6 bg-slate-700/50 mx-1" />

            {/* Channel chips */}
            <div className="flex items-center gap-1">
              {CHANNELS.map(ch => (
                <Chip
                  key={ch}
                  label={ch}
                  active={channelFilter === ch}
                  onClick={() => toggleFilter(channelFilter, setChannelFilter, ch)}
                  count={channelCounts[ch] || 0}
                />
              ))}
            </div>

            <div className="w-px h-6 bg-slate-700/50 mx-1" />

            {/* Flag chip */}
            <Chip
              label="Aging / Stuck"
              active={flagFilter}
              onClick={() => setFlagFilter(f => !f)}
              variant="flag"
              count={flagCount}
            />

            {/* Clear all */}
            {hasActiveFilters && (
              <button
                onClick={clearAllFilters}
                className="ml-auto text-xs text-slate-500 hover:text-white transition-colors flex items-center gap-1"
              >
                <X className="w-3 h-3" /> Clear
              </button>
            )}
          </div>
        </div>

        {/* ── Phase Funnel ───────────────────────────────────────────── */}
        {/* ── Driver table ───────────────────────────────────────────── */}
        <div className="bg-slate-800/50 backdrop-blur border border-slate-700/50 rounded-xl overflow-visible">
          {/* Column headers */}
          <div className="grid grid-cols-[40px_1fr_2.5fr_36px] items-center gap-2 px-3 py-2 border-b border-slate-700/50 text-[10px] text-slate-500 uppercase tracking-wider font-semibold">
            <div />
            <div>Driver / SA</div>
            <div>Progress</div>
            <div />
          </div>

          {/* Rows */}
          {filtered.length > 0 ? (
            filtered.map((driver, i) => (
              <ExpandableDriverRow key={driver.sa_number || i} driver={driver} onDriverClick={setMapDriver} isFollowed={followedSAs.has(driver.sa_number)} onToggleFollow={toggleFollow} />
            ))
          ) : (
            <div className="py-12 text-center">
              {hasActiveFilters ? (
                <div className="space-y-2">
                  <Search className="w-6 h-6 text-slate-600 mx-auto" />
                  <div className="text-sm text-slate-500">No drivers or SAs match your search.</div>
                  <button
                    onClick={clearAllFilters}
                    className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
                  >
                    Clear all filters
                  </button>
                </div>
              ) : (
                <div className="space-y-2">
                  <Activity className="w-6 h-6 text-slate-600 mx-auto" />
                  <div className="text-sm text-slate-500">No active dispatches</div>
                </div>
              )}
            </div>
          )}

          {/* Row count footer */}
          {filtered.length > 0 && (
            <div className="px-3 py-2 border-t border-slate-800/40 text-[10px] text-slate-600 flex items-center justify-between">
              <span>
                Showing {filtered.length} of {(data?.drivers || []).length} active dispatch{(data?.drivers || []).length !== 1 ? 'es' : ''}
              </span>
              {hasActiveFilters && (
                <span className="text-blue-400/60">Filters active</span>
              )}
            </div>
          )}
        </div>
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
              <h2 className="text-sm font-bold text-white">How to Use the ERS Live Board</h2>
              <button onClick={() => setShowHelp(false)} className="text-slate-500 hover:text-white"><X className="w-4 h-4" /></button>
            </div>
            <div className="px-5 py-4 space-y-3 text-xs text-slate-300 max-h-[70vh] overflow-y-auto">
              <div>
                <h3 className="font-bold text-white mb-1">What is this?</h3>
                <p className="text-slate-400">Real-time view of all active ERS Service Appointments currently being dispatched. Shows every driver with an active call, their progress through each phase, and flags problems.</p>
              </div>
              <div>
                <h3 className="font-bold text-white mb-1">Progress Tracker</h3>
                <p className="text-slate-400">Each row shows a driver's journey: <span className="text-slate-300">Dispatched</span> → <span className="text-slate-300">Accepted</span> → <span className="text-slate-300">En Route</span> → <span className="text-slate-300">On Location</span> → <span className="text-slate-300">In Progress</span> → <span className="text-slate-300">Complete</span>.</p>
                <p className="text-slate-400 mt-1"><span className="text-slate-200">Filled dots</span> = completed phases. <span className="text-amber-400">Pulsing amber dot</span> = current phase. <span className="text-red-400">Pulsing red dot</span> = stuck/at risk. Hover any dot for time details.</p>
              </div>
              <div>
                <h3 className="font-bold text-white mb-1">SA Number Tooltip</h3>
                <p className="text-slate-400">Hover the <span className="text-blue-400">SA number</span> next to the driver name to see a full timeline with phase durations, timestamps, and who triggered each status change — without opening the SA report.</p>
              </div>
              <div>
                <h3 className="font-bold text-white mb-1">Driver Name → Map</h3>
                <p className="text-slate-400">Click a <span className="text-blue-400">driver name</span> to see a mini map showing their GPS location vs. the customer, with distance and estimated drive time.</p>
              </div>
              <div>
                <h3 className="font-bold text-white mb-1">★ Star — Add to Watchlist</h3>
                <p className="text-slate-400"><span className="text-slate-200">☆ Outline star</span> = not on watchlist. Click to add. <span className="text-amber-400">★ Filled star</span> = on watchlist. Click to remove. Starred SAs appear on the SA Watchlist tab for all dispatchers. Stars auto-clear when the SA completes.</p>
              </div>
              <div>
                <h3 className="font-bold text-white mb-1">Filters</h3>
                <p className="text-slate-400">Use filter chips to narrow by phase (En Route, On Location, etc.), channel (Fleet, On-Platform, Off-Platform), or flag (Aging/Stuck). Search by driver name, SA number, or garage.</p>
              </div>
              <div>
                <h3 className="font-bold text-white mb-1">Auto-Refresh</h3>
                <p className="text-slate-400">Data refreshes every 60 seconds automatically. The countdown shows next refresh time.</p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
