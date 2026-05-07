/**
 * SAWatchlist.jsx
 *
 * SA Watchlist — 2 sub-tabs:
 * 1. Operational Watchlist — flag-based alerts (PTA at risk, not assigned, not closed, priority late)
 * 2. Manual Dispatch SAs — progress-tracker rows (reassigned, rejected, thrashed)
 * Auto-refreshes every 60 seconds.
 */

import { useState, useEffect, useRef, useMemo } from 'react'
import { clsx } from 'clsx'
import {
  Search, Clock, Lock, AlertTriangle, HelpCircle,
  Loader2, User, Radio, CheckCircle2, X, ExternalLink, MapPin, Mail,
} from 'lucide-react'
import { SAWithTimeline, fmtDuration } from './LiveDispatchUtils'
import CheckpointTracker from './CheckpointTracker'
import DriverMapPopup from './DriverMapPopup'
import LiveDispatchBoard from './LiveDispatchBoard'
import { fetchWatchlist } from '../api'

// ── Salesforce URL helper ───────────────────────────────────────────────────
const SF_BASE = 'https://aaawcny.lightning.force.com'
const sfLink = (id) => id ? `${SF_BASE}/lightning/r/${id}/view` : '#'

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

// ── Flag badge colors ───────────────────────────────────────────────────────
const FLAG_COLORS = {
  'Call At Risk of Missing PTA': 'bg-red-500/20 text-red-400 border-red-500/40',
  'High Priority Call Late': 'bg-orange-500/20 text-orange-400 border-orange-500/40',
  'Call Not Assigned': 'bg-yellow-500/20 text-yellow-400 border-yellow-500/40',
  'Call Not Assigned - Rejected': 'bg-rose-500/20 text-rose-400 border-rose-500/40',
  'Call Not Assigned - Received': 'bg-amber-500/20 text-amber-400 border-amber-500/40',
  'Call Not Closed': 'bg-purple-500/20 text-purple-400 border-purple-500/40',
}

// ── Operational Alerts Table ────────────────────────────────────────────────

function OperationalAlertsTable({ alerts, onShowHelp }) {
  if (!alerts || alerts.length === 0) return null

  const handleEmail = () => {
    // Build an HTML table for the email body
    const rows = alerts.map(a =>
      `<tr>
        <td style="border:1px solid #ccc;padding:4px 8px">${a.wo_number || '—'}</td>
        <td style="border:1px solid #ccc;padding:4px 8px">${a.sa_number || '—'}</td>
        <td style="border:1px solid #ccc;padding:4px 8px">${a.priority_code || '—'}</td>
        <td style="border:1px solid #ccc;padding:4px 8px">${a.gantt_label || '—'}</td>
        <td style="border:1px solid #ccc;padding:4px 8px">${a.pta_delta_min != null ? a.pta_delta_min + ' min' : '—'}</td>
        <td style="border:1px solid #ccc;padding:4px 8px">${a.current_wait != null ? Math.round(a.current_wait) + ' min' : '—'}</td>
        <td style="border:1px solid #ccc;padding:4px 8px">${a.territory || '—'}</td>
        <td style="border:1px solid #ccc;padding:4px 8px">${a.city || '—'}</td>
        <td style="border:1px solid #ccc;padding:4px 8px">${a.work_type || '—'}</td>
        <td style="border:1px solid #ccc;padding:4px 8px;font-family:monospace;font-size:10px">${a.work_type_id || '—'}</td>
        <td style="border:1px solid #ccc;padding:4px 8px">${a.flag}</td>
      </tr>`
    ).join('')

    const htmlTable = `
      <h3>Operational Alerts — ${alerts.length} items (${new Date().toLocaleString()})</h3>
      <table style="border-collapse:collapse;font-family:Calibri,sans-serif;font-size:12px">
        <thead>
          <tr style="background:#f0f0f0">
            <th style="border:1px solid #ccc;padding:4px 8px">Work Order</th>
            <th style="border:1px solid #ccc;padding:4px 8px">SA #</th>
            <th style="border:1px solid #ccc;padding:4px 8px">Priority</th>
            <th style="border:1px solid #ccc;padding:4px 8px">Gantt Label</th>
            <th style="border:1px solid #ccc;padding:4px 8px">PTA Delta</th>
            <th style="border:1px solid #ccc;padding:4px 8px">Current Wait</th>
            <th style="border:1px solid #ccc;padding:4px 8px">Territory</th>
            <th style="border:1px solid #ccc;padding:4px 8px">City</th>
            <th style="border:1px solid #ccc;padding:4px 8px">Work Type</th>
            <th style="border:1px solid #ccc;padding:4px 8px">Work Type ID</th>
            <th style="border:1px solid #ccc;padding:4px 8px">Flag</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `

    // Copy HTML to clipboard so user can paste into email body
    const blob = new Blob([htmlTable], { type: 'text/html' })
    const clipItem = new ClipboardItem({ 'text/html': blob })
    navigator.clipboard.write([clipItem])

    // Open Outlook compose
    const subject = encodeURIComponent(`Operational Alerts — ${alerts.length} items (${new Date().toLocaleDateString()})`)
    window.open(`https://outlook.cloud.microsoft/mail/deeplink/compose?subject=${subject}`, '_blank')
  }

  return (
    <div className="bg-slate-800/50 backdrop-blur border border-red-800/40 rounded-xl overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-slate-700/50 bg-red-950/20">
        <AlertTriangle className="w-4 h-4 text-red-400" />
        <h3 className="text-xs font-bold text-red-300 uppercase tracking-wider">Operational Alerts</h3>
        <button onClick={onShowHelp} className="text-slate-500 hover:text-red-300 transition-colors" title="What are Operational Alerts?">
          <HelpCircle className="w-3.5 h-3.5" />
        </button>
        <span className="ml-auto flex items-center gap-3">
          <button onClick={handleEmail} className="text-slate-400 hover:text-blue-300 transition-colors group relative" title="Email alerts">
            <Mail className="w-4 h-4" />
            <span className="absolute top-full right-0 mt-2 hidden group-hover:block w-52 text-[10px] text-slate-200 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 shadow-xl z-50 whitespace-normal">
              Click to copy table &amp; open Outlook. Then press ⌘V (Ctrl+V) to paste the alerts into your email.
            </span>
          </button>
          <span className="text-[10px] font-bold font-mono px-2 py-0.5 rounded-full bg-red-500/15 text-red-400 border border-red-500/30">
            {alerts.length}
          </span>
        </span>
      </div>

      {/* Table header */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-slate-700/50 text-[10px] text-slate-500 uppercase tracking-wider">
              <th className="px-3 py-2 text-left font-semibold">Work Order</th>
              <th className="px-3 py-2 text-left font-semibold">Appointment #</th>
              <th className="px-3 py-2 text-left font-semibold">Priority</th>
              <th className="px-3 py-2 text-left font-semibold">Gantt Label</th>
              <th className="px-3 py-2 text-left font-semibold">PTA Delta</th>
              <th className="px-3 py-2 text-left font-semibold">Current Wait</th>
              <th className="px-3 py-2 text-left font-semibold">Territory</th>
              <th className="px-3 py-2 text-left font-semibold">City</th>
              <th className="px-3 py-2 text-left font-semibold">Work Type</th>
              <th className="px-3 py-2 text-left font-semibold">Flag</th>
            </tr>
          </thead>
          <tbody>
            {alerts.map((alert, idx) => (
              <tr key={`${alert.sa_id}-${alert.flag}-${idx}`}
                className="border-b border-slate-800/40 hover:bg-slate-800/60 transition-colors">
                {/* Work Order */}
                <td className="px-3 py-2">
                  {alert.wo_number ? (
                    <a href={sfLink(alert.wo_id)} target="_blank" rel="noopener noreferrer"
                      className="text-blue-400 hover:text-blue-300 font-mono flex items-center gap-1">
                      {alert.wo_number}
                      <ExternalLink className="w-2.5 h-2.5 opacity-60" />
                    </a>
                  ) : <span className="text-slate-600">—</span>}
                </td>
                {/* SA Number — with timeline hover */}
                <td className="px-3 py-2">
                  <div className="flex items-center gap-1">
                    <SAWithTimeline number={alert.sa_number} driver={alert} />
                    <a href={sfLink(alert.sa_id)} target="_blank" rel="noopener noreferrer"
                      className="text-slate-500 hover:text-blue-400" title="Open in Salesforce">
                      <ExternalLink className="w-2.5 h-2.5" />
                    </a>
                  </div>
                </td>
                {/* Priority */}
                <td className="px-3 py-2">
                  {alert.priority_code ? (
                    <span className="font-bold text-white">{alert.priority_code}</span>
                  ) : <span className="text-slate-600">—</span>}
                </td>
                {/* Gantt Label */}
                <td className="px-3 py-2 text-slate-300 max-w-[140px] truncate" title={alert.gantt_label}>
                  {alert.gantt_label || '—'}
                </td>
                {/* PTA Delta */}
                <td className="px-3 py-2">
                  {alert.pta_delta_min != null ? (
                    <span className={clsx('font-mono font-bold',
                      alert.pta_delta_min > 0 ? 'text-red-400' : 'text-emerald-400')}>
                      {alert.pta_delta_min > 0 ? '+' : ''}{alert.pta_delta_min} min
                    </span>
                  ) : <span className="text-slate-600">—</span>}
                </td>
                {/* Current Wait */}
                <td className="px-3 py-2">
                  {alert.current_wait != null ? (
                    <span className="font-mono text-slate-300">{Math.round(alert.current_wait)} min</span>
                  ) : <span className="text-slate-600">—</span>}
                </td>
                {/* Territory */}
                <td className="px-3 py-2 text-slate-300 max-w-[160px] truncate" title={alert.territory}>
                  {alert.territory || '—'}
                </td>
                {/* City */}
                <td className="px-3 py-2 text-slate-300 flex items-center gap-1">
                  {alert.city || '—'}
                  {alert.latitude && alert.longitude && (
                    <MapPin className="w-2.5 h-2.5 text-slate-500" title={`${alert.latitude}, ${alert.longitude}`} />
                  )}
                </td>
                {/* Work Type */}
                <td className="px-3 py-2 text-slate-300 text-xs">
                  {alert.work_type || '—'}
                </td>
                {/* Flag */}
                <td className="px-3 py-2">
                  <span className={clsx('text-[10px] font-bold px-2 py-0.5 rounded-full border whitespace-nowrap',
                    FLAG_COLORS[alert.flag] || 'bg-slate-700/50 text-slate-300 border-slate-600/50')}>
                    {alert.flag}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
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
  const [activeTab, setActiveTab] = useState('alerts')
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

  // ── Search filter (applies to manual dispatch rows) ──
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
  const operationalAlerts = data?.operational_alerts || []

  const TAB_STYLES = {
    alerts: { active: 'border-red-500 text-red-300 bg-red-600/10', badge: 'bg-red-500/20 text-red-400' },
    manual: { active: 'border-amber-500 text-amber-300 bg-amber-600/10', badge: 'bg-amber-500/20 text-amber-400' },
  }

  return (
    <div className="w-full h-full bg-slate-950 flex flex-col overflow-hidden">
      {/* ── Error banner ────────────────────────────────────────────── */}
      {error && (
        <div className="mx-6 mt-2 px-4 py-2 rounded-lg bg-red-950/40 border border-red-800/40 text-red-400 text-xs flex items-center gap-2">
          <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
          <span>Failed to refresh: {error}</span>
        </div>
      )}

      {/* ── Sub-tab bar ──────────────────────────────────────────────── */}
      <div className="flex-shrink-0 flex items-center gap-1 px-6 pt-3 pb-0">
        {/* Operational Watchlist tab */}
        <button onClick={() => setActiveTab('alerts')}
          className={clsx('flex items-center gap-1.5 px-3 py-2 text-xs font-bold uppercase tracking-wide transition-all border-b-2 rounded-t-md',
            activeTab === 'alerts' ? TAB_STYLES.alerts.active : 'border-transparent text-slate-500 hover:text-white hover:bg-slate-800/40')}>
          <AlertTriangle className="w-3.5 h-3.5" />
          Operational Watchlist
          {operationalAlerts.length > 0 && (
            <span className={clsx('text-[9px] font-mono ml-1 px-1.5 py-0.5 rounded-full',
              activeTab === 'alerts' ? TAB_STYLES.alerts.badge : 'bg-slate-700/50 text-slate-400')}>
              {operationalAlerts.length}
            </span>
          )}
        </button>

        {/* Manual Dispatch SAs tab */}
        <button onClick={() => setActiveTab('manual')}
          className={clsx('flex items-center gap-1.5 px-3 py-2 text-xs font-bold uppercase tracking-wide transition-all border-b-2 rounded-t-md',
            activeTab === 'manual' ? TAB_STYLES.manual.active : 'border-transparent text-slate-500 hover:text-white hover:bg-slate-800/40')}>
          <Lock className="w-3.5 h-3.5" />
          Manually Dispatched SAs
          {totalCount > 0 && (
            <span className={clsx('text-[9px] font-mono ml-1 px-1.5 py-0.5 rounded-full',
              activeTab === 'manual' ? TAB_STYLES.manual.badge : 'bg-slate-700/50 text-slate-400')}>
              {totalCount}
            </span>
          )}
        </button>

        {/* ERS Live Board tab */}
        <button onClick={() => setActiveTab('live')}
          className={clsx('flex items-center gap-1.5 px-3 py-2 text-xs font-bold uppercase tracking-wide transition-all border-b-2 rounded-t-md',
            activeTab === 'live' ? 'border-emerald-500 text-emerald-300 bg-emerald-600/10' : 'border-transparent text-slate-500 hover:text-white hover:bg-slate-800/40')}>
          <Radio className="w-3.5 h-3.5" />
          ERS Live Board
        </button>

        {/* Live indicator */}
        <div className="ml-auto flex items-center gap-1.5 text-[10px] text-slate-500 font-mono">
          <Radio className="w-3 h-3 text-emerald-400 animate-pulse" />
          <span>LIVE</span>
          <span className="tabular-nums">{countdown}s</span>
        </div>
      </div>

      <div className="border-b border-slate-700/50" />

      {/* ══════════════════════════════════════════════════════════════ */}
      {/* TAB 1: Operational Watchlist                                  */}
      {/* ══════════════════════════════════════════════════════════════ */}
      {activeTab === 'alerts' && (
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-7xl mx-auto px-6 pt-4 pb-8 space-y-4">
            <OperationalAlertsTable alerts={operationalAlerts} onShowHelp={() => setShowHelp(true)} />

            {operationalAlerts.length === 0 && !loading && (
              <div className="bg-slate-800/30 border border-emerald-800/30 rounded-xl py-12 text-center">
                <CheckCircle2 className="w-8 h-8 text-emerald-500 mx-auto mb-2" />
                <p className="text-sm font-medium text-emerald-400">All clear — no operational alerts right now</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ══════════════════════════════════════════════════════════════ */}
      {/* TAB 2: Manual Dispatch SAs                                    */}
      {/* ══════════════════════════════════════════════════════════════ */}
      {activeTab === 'manual' && (
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-7xl mx-auto px-6 pt-4 pb-8 space-y-4">
            {/* Search bar */}
            <div className="relative max-w-md">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 pointer-events-none" />
              <input
                ref={searchRef}
                type="text"
                placeholder="Search SA, driver, or territory..."
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

            {/* Empty state */}
            {totalCount === 0 && !loading && (
              <div className="bg-slate-800/30 border border-emerald-800/30 rounded-xl py-12 text-center">
                <CheckCircle2 className="w-8 h-8 text-emerald-500 mx-auto mb-2" />
                <p className="text-sm font-medium text-emerald-400">No manual dispatch SAs currently being tracked</p>
              </div>
            )}

            {/* No search results */}
            {totalCount > 0 && filtered.length === 0 && search && (
              <div className="text-center py-12 text-xs text-slate-500 font-mono">
                No SAs match "{search}"
              </div>
            )}

            {/* Progress Tracker Rows */}
            {filtered.length > 0 && (
              <div className="bg-slate-800/50 backdrop-blur border border-slate-700/50 rounded-xl overflow-visible">
                {/* Column headers */}
                <div className="grid grid-cols-[40px_1fr_2.5fr_36px] items-center gap-2 px-3 py-2 border-b border-slate-700/50 text-[10px] text-slate-500 uppercase tracking-wider font-semibold">
                  <div />
                  <div>Driver / SA</div>
                  <div>Progress</div>
                  <div />
                </div>

                {/* Rows */}
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
                      {/* Main row */}
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

                        {/* Checkpoint tracker */}
                        <div className="px-1">
                          <CheckpointTracker
                            phases={sa.phases || []}
                            isStuck={isStuck}
                            saInfo={{ work_type: sa.work_type, address: sa.address, description: sa.description }}
                          />
                        </div>

                        {/* Lock indicator (auto-tracked) */}
                        <div title="Auto-tracked (manual reassign / rejection / thrash)" className="p-1.5 flex-shrink-0 text-slate-600">
                          <Lock className="w-3.5 h-3.5" />
                        </div>
                      </div>

                      {/* Context — reason + dispatcher */}
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
                  <span>Showing {filtered.length} of {totalCount}</span>
                  <span>Auto-tracked: manual reassign · driver reject · 3+ driver swaps</span>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ══════════════════════════════════════════════════════════════ */}
      {/* TAB 3: ERS Live Board                                         */}
      {/* ══════════════════════════════════════════════════════════════ */}
      {activeTab === 'live' && (
        <div className="flex-1 overflow-hidden">
          <LiveDispatchBoard />
        </div>
      )}

      {/* ── Driver Map Popup ────────────────────────────────────────── */}
      {mapDriver && (
        <DriverMapPopup driver={mapDriver} onClose={() => setMapDriver(null)} />
      )}

      {/* ── Help modal ──────────────────────────────────────────────── */}
      {showHelp && (
        <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={() => setShowHelp(false)}>
          <div className="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl max-w-lg w-full mx-4 overflow-hidden" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
              <h2 className="text-sm font-bold text-white">Operational Alerts — Reference</h2>
              <button onClick={() => setShowHelp(false)} className="text-slate-500 hover:text-white"><X className="w-4 h-4" /></button>
            </div>
            <div className="px-5 py-4 space-y-3 text-xs text-slate-300 max-h-[70vh] overflow-y-auto">
              <div>
                <h3 className="font-bold text-white mb-1">What are Operational Alerts?</h3>
                <p className="text-slate-400">
                  SAs that match one of 6 flag conditions indicating dispatcher intervention may be needed.
                  The system evaluates all open SAs every 60 seconds and flags those that meet criteria.
                </p>
              </div>
              <div>
                <h3 className="font-bold text-white mb-1">Flag Definitions</h3>
                <div className="space-y-2 text-slate-400">
                  <div>
                    <span className="text-red-400 font-bold">Call At Risk of Missing PTA</span>
                    <p className="pl-2 mt-0.5">Within 20 minutes of PTA due time, status not yet En Route or On Location. PTA Due = CreatedDate + ERS_PTA__c (minutes).</p>
                  </div>
                  <div>
                    <span className="text-yellow-400 font-bold">Call Not Assigned</span>
                    <p className="pl-2 mt-0.5">Facility account name starts with '000' — indicates no facility has been assigned to the call.</p>
                  </div>
                  <div>
                    <span className="text-rose-400 font-bold">Call Not Assigned - Rejected</span>
                    <p className="pl-2 mt-0.5">SA status is 'Rejected' — driver declined the call.</p>
                  </div>
                  <div>
                    <span className="text-amber-400 font-bold">Call Not Assigned - Received</span>
                    <p className="pl-2 mt-0.5">SA status is 'Received' — call entered the system but hasn't been dispatched yet.</p>
                  </div>
                  <div>
                    <span className="text-purple-400 font-bold">Call Not Closed</span>
                    <p className="pl-2 mt-0.5">Status is On Location or En Route for more than 2 hours — driver may have forgotten to close the call.</p>
                  </div>
                  <div>
                    <span className="text-orange-400 font-bold">High Priority Call Late</span>
                    <p className="pl-2 mt-0.5">Priority code P1–P7, created more than 30 minutes ago, still not resolved.</p>
                  </div>
                </div>
              </div>
              <div>
                <h3 className="font-bold text-white mb-1">Table Columns</h3>
                <ul className="list-disc list-inside pl-2 space-y-0.5 text-slate-400">
                  <li><strong>Work Order</strong> — WO number (links to Salesforce)</li>
                  <li><strong>Appointment #</strong> — SA number with timeline on hover</li>
                  <li><strong>Priority</strong> — WO Priority Code (P1–P10, SN, etc.)</li>
                  <li><strong>Gantt Label</strong> — FSL scheduler label (emoji + coded info)</li>
                  <li><strong>PTA Delta</strong> — minutes until/past PTA due time</li>
                  <li><strong>Current Wait</strong> — total member wait in minutes</li>
                  <li><strong>Territory</strong> — assigned service territory</li>
                  <li><strong>City</strong> — customer location</li>
                  <li><strong>Flag</strong> — which alert condition triggered</li>
                </ul>
              </div>
              <div>
                <h3 className="font-bold text-white mb-1">Interactions</h3>
                <ul className="list-disc list-inside pl-2 space-y-0.5 text-slate-400">
                  <li>Hover SA number → full status timeline with elapsed durations</li>
                  <li>Click WO/SA links → opens Salesforce record</li>
                  <li>Click 📍 pin → view customer location on map</li>
                </ul>
              </div>
              <div>
                <h3 className="font-bold text-white mb-1">Exclusions</h3>
                <p className="text-slate-400">Tow Drop-Off SAs are excluded from all flags except "Call Not Assigned - Received". Only ERS Service Appointment record types are evaluated.</p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
