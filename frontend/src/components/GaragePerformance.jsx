/**
 * GaragePerformance.jsx — "Performance" tab in Garage Dashboard
 *
 * Shows: 4 satisfaction scores, primary vs secondary, driver breakdown with bonus,
 * drill-down to individual surveys, AI executive summary.
 */

import { useState, useEffect, useContext } from 'react'
import { Loader2, ChevronDown, ChevronUp, DollarSign, Star, AlertTriangle, Sparkles, Download, Mail, FileText, Eye, EyeOff } from 'lucide-react'
import { clsx } from 'clsx'
import { fetchGarageScorecard, fetchGarageAiSummary, exportGarageScorecard, emailGarageReport, fetchDriverSAs } from '../api'
import { SAReportContext } from '../contexts/SAReportContext'
import SALink from './SALink'

// Score card colors
const scoreColor = (pct) =>
  pct == null ? 'text-slate-600' :
  pct >= 92 ? 'text-emerald-400' :
  pct >= 82 ? 'text-blue-400' :
  pct >= 70 ? 'text-amber-400' : 'text-red-400'

const scoreBg = (pct) =>
  pct == null ? 'bg-slate-800' :
  pct >= 92 ? 'bg-emerald-500' :
  pct >= 82 ? 'bg-blue-500' :
  pct >= 70 ? 'bg-amber-500' : 'bg-red-500'


function ScoreCard({ label, pct, subtitle }) {
  return (
    <div className="glass rounded-xl p-4 border border-slate-700/30">
      <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">{label}</div>
      <div className={clsx('text-3xl font-black', scoreColor(pct))}>
        {pct != null ? `${pct}%` : '—'}
      </div>
      <div className="h-1.5 rounded-full bg-slate-800 mt-2 overflow-hidden">
        {pct != null && <div className={clsx('h-full rounded-full', scoreBg(pct))} style={{ width: `${Math.min(pct, 100)}%` }} />}
      </div>
      {subtitle && <div className="text-[9px] text-slate-600 mt-1">{subtitle}</div>}
    </div>
  )
}

function LazyDrillDown({ garageId, driverName, type, startDate, endDate }) {
  const [items, setItems] = useState(null)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    fetchDriverSAs(garageId, driverName, type, startDate, endDate)
      .then(r => setItems(r?.items || []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false))
  }, [garageId, driverName, type, startDate, endDate])

  if (loading) return <div className="flex items-center gap-2 py-3 justify-center"><Loader2 className="w-4 h-4 animate-spin text-slate-500" /><span className="text-xs text-slate-500">Loading SAs...</span></div>
  if (!items?.length) return <div className="text-xs text-slate-600 text-center py-3">No {type} SAs</div>
  return (
    <div className="space-y-0.5">
      <div className="flex text-[9px] text-slate-600 uppercase tracking-wide gap-3 px-2 pb-1 border-b border-slate-800/50">
        <span className="w-24">SA #</span><span className="w-20">Date</span>
        <span className="w-32">Work Type</span><span className="w-20">Status</span>
        {type === 'declined' && <span className="flex-1">Decline Reason</span>}
      </div>
      {items.map((sa, i) => (
        <div key={i} className={clsx('flex text-[10px] gap-3 px-2 py-1 rounded items-center',
          type === 'declined' ? 'bg-red-950/10 text-red-300/80' : 'bg-slate-800/20 text-slate-400'
        )}>
          <span className="w-24">{sa.sa_number ? <SALink number={sa.sa_number} style={{ fontFamily: 'monospace', fontSize: 10 }} /> : '—'}</span>
          <span className="w-20">{sa.date || '—'}</span>
          <span className="w-32 truncate">{sa.work_type || '—'}</span>
          <span className="w-20">{sa.status || '—'}</span>
          {type === 'declined' && <span className="flex-1 text-red-400/70">{sa.decline_reason || '—'}</span>}
        </div>
      ))}
    </div>
  )
}

function DriverRow({ driver, onToggle, expanded, garageId, startDate, endDate }) {
  const saCtx = useContext(SAReportContext)
  const [showCompleted, setShowCompleted] = useState(false)
  const [showDeclined, setShowDeclined] = useState(false)
  return (
    <div className="border-b border-slate-800/50 last:border-0">
      <div
        className="flex items-center gap-3 px-3 py-2.5 cursor-pointer hover:bg-slate-800/30 transition"
        onClick={onToggle}
      >
        <div className="w-4">
          {expanded ? <ChevronUp className="w-3.5 h-3.5 text-slate-500" /> : <ChevronDown className="w-3.5 h-3.5 text-slate-500" />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-xs font-semibold text-white truncate">{driver.name}</div>
          <div className="text-[9px] text-slate-500">{driver.survey_count} surveys</div>
        </div>
        <div className="text-center w-14" onClick={e => { e.stopPropagation(); if ((driver.completed ?? 0) > 0) setShowCompleted(!showCompleted) }}>
          <div className={clsx('text-xs font-bold', (driver.completed ?? 0) > 0 ? 'text-blue-400 hover:underline cursor-pointer' : 'text-slate-200')}>{driver.completed ?? 0}</div>
          <div className="text-[8px] text-slate-600">Completed</div>
        </div>
        <div className="text-center w-14" onClick={e => { e.stopPropagation(); if ((driver.declined ?? 0) > 0) setShowDeclined(!showDeclined) }}>
          <div className={clsx('text-xs font-bold', (driver.declined ?? 0) > 0 ? 'text-red-400 hover:underline cursor-pointer' : 'text-slate-500')}>{driver.declined ?? 0}</div>
          <div className="text-[8px] text-slate-600">Declined</div>
        </div>
        <div className="text-center w-14">
          <div className={clsx('text-xs font-bold', driver.avg_ata != null && driver.avg_ata <= 45 ? 'text-cyan-400' : driver.avg_ata != null ? 'text-amber-400' : 'text-slate-500')}>{driver.avg_ata != null ? `${driver.avg_ata}m` : '—'}</div>
          <div className="text-[8px] text-slate-600">Avg ATA</div>
        </div>
        <div className="text-center w-14">
          <div className={clsx('text-xs font-bold', scoreColor(driver.overall_pct))}>{driver.overall_pct ?? '—'}%</div>
          <div className="text-[8px] text-slate-600">Overall</div>
        </div>
        <div className="text-center w-14">
          <div className={clsx('text-xs font-bold', scoreColor(driver.response_time_pct))}>{driver.response_time_pct ?? '—'}%</div>
          <div className="text-[8px] text-slate-600">Resp Time</div>
        </div>
        <div className="text-center w-14">
          <div className={clsx('text-xs font-bold', scoreColor(driver.technician_pct))}>{driver.technician_pct ?? '—'}%</div>
          <div className="text-[8px] text-slate-600">Tech</div>
        </div>
        <div className="text-center w-14">
          <div className={clsx('text-xs font-bold', scoreColor(driver.kept_informed_pct))}>{driver.kept_informed_pct ?? '—'}%</div>
          <div className="text-[8px] text-slate-600">Informed</div>
        </div>
      </div>
      {/* SA drill-down: completed SAs (lazy-fetched) */}
      {showCompleted && <div className="bg-slate-900/40 px-4 py-2"><LazyDrillDown garageId={garageId} driverName={driver.name} type="completed" startDate={startDate} endDate={endDate} /></div>}
      {/* SA drill-down: declined SAs (lazy-fetched) */}
      {showDeclined && <div className="bg-red-950/20 px-4 py-2"><LazyDrillDown garageId={garageId} driverName={driver.name} type="declined" startDate={startDate} endDate={endDate} /></div>}
      {/* Survey drill-down: satisfaction details */}
      {expanded && driver.surveys && (
        <div className="bg-slate-900/40 px-4 py-2 space-y-1.5">
          <div className="grid grid-cols-[100px_70px_60px_60px_60px_60px_1fr] gap-2 text-[8px] text-slate-600 uppercase tracking-wider pb-1 border-b border-slate-800/40">
            <span>SA #</span><span>Date</span><span>Overall</span><span>Resp</span><span>Tech</span><span>Informed</span><span>Comment</span>
          </div>
          {driver.surveys.map((sv, i) => {
            const satBadge = (val) => {
              if (!val) return <span className="text-slate-700">—</span>
              const v = val.toLowerCase()
              const cls = v === 'totally satisfied' ? 'text-emerald-400' :
                v === 'satisfied' ? 'text-green-400' :
                v.includes('neither') ? 'text-slate-400' :
                v === 'dissatisfied' ? 'text-amber-400' : 'text-red-400'
              const short = v === 'totally satisfied' ? 'TS' :
                v === 'satisfied' ? 'S' :
                v.includes('neither') ? 'N' :
                v === 'dissatisfied' ? 'D' : 'TD'
              return <span className={clsx('font-semibold', cls)}>{short}</span>
            }
            return (
              <div key={i} className="grid grid-cols-[100px_70px_60px_60px_60px_60px_1fr] gap-2 text-[10px] items-start">
                <span className="text-slate-400">
                  {sv.sa_number ? (
                    <button className="text-blue-400 hover:underline font-mono" onClick={(e) => { e.stopPropagation(); saCtx?.open(sv.sa_number) }}>
                      {sv.sa_number}
                    </button>
                  ) : sv.call_date}
                </span>
                <span className="text-slate-500">{sv.call_date}</span>
                {satBadge(sv.overall)}
                {satBadge(sv.response_time)}
                {satBadge(sv.technician)}
                {satBadge(sv.kept_informed)}
                <span className="text-slate-400 italic text-[9px] truncate" title={sv.comment || ''}>
                  {sv.comment || '—'}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default function GaragePerformance({ garageId, garageName, startDate, endDate, refreshKey }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [aiSummary, setAiSummary] = useState(null)
  const [aiLoading, setAiLoading] = useState(false)
  const [expandedDriver, setExpandedDriver] = useState(null)
  const [sortBy, setSortBy] = useState('survey_count')
  const [sortDir, setSortDir] = useState('desc')
  const [exporting, setExporting] = useState(false)
  const [emailTo, setEmailTo] = useState('')
  const [emailOpen, setEmailOpen] = useState(false)
  const [emailSending, setEmailSending] = useState(false)
  const [emailSent, setEmailSent] = useState(false)

  useEffect(() => {
    if (!startDate || !endDate) return
    setLoading(true)
    setError(null)
    setAiSummary(null)
    fetchGarageScorecard(garageId, startDate, endDate)
      .then(d => {
        setData(d)
        setAiLoading(true)
        fetchGarageAiSummary(garageId, startDate, endDate)
          .then(r => setAiSummary(r.summary))
          .catch(() => setAiSummary('Failed to generate AI summary.'))
          .finally(() => setAiLoading(false))
      })
      .catch(e => setError(e.response?.data?.detail || e.message || 'Failed'))
      .finally(() => setLoading(false))
  }, [garageId, startDate, endDate, refreshKey])

  const gs = data?.garage_summary || {}
  const ps = data?.primary_vs_secondary || {}
  const isContractor = data?.garage_type === 'contractor'
  const drivers = data?.drivers || []

  // Sort drivers
  const sorted = [...drivers].sort((a, b) => {
    const va = a[sortBy] ?? -1, vb = b[sortBy] ?? -1
    return sortDir === 'desc' ? vb - va : va - vb
  })

  const toggleSort = (field) => {
    if (sortBy === field) setSortDir(d => d === 'desc' ? 'asc' : 'desc')
    else { setSortBy(field); setSortDir('desc') }
  }

  // Shared HTML report builder for Email + PDF
  const buildReportHtml = () => {
    const ov = ps.overall || {}
    const sc = (pct) => pct == null ? '#999' : pct >= 92 ? '#34d399' : pct >= 82 ? '#60a5fa' : pct >= 70 ? '#fbbf24' : '#f87171'
    const driverTableRows = sorted.map(d => {
      const ataColor = d.avg_ata != null && d.avg_ata <= 45 ? '#10b981' : d.avg_ata != null ? '#ef4444' : '#999'
      const decColor = (d.declined ?? 0) > 0 ? '#ef4444' : '#64748b'
      return `<tr>
        <td style="padding:6px 10px;border-bottom:1px solid #e2e8f0;font-weight:600">${d.name}</td>
        <td style="padding:6px 10px;border-bottom:1px solid #e2e8f0;text-align:center">${d.completed ?? 0}</td>
        <td style="padding:6px 10px;border-bottom:1px solid #e2e8f0;text-align:center;color:${decColor};font-weight:700">${d.declined ?? 0}</td>
        <td style="padding:6px 10px;border-bottom:1px solid #e2e8f0;text-align:center;color:${ataColor};font-weight:700">${d.avg_ata != null ? d.avg_ata + 'm' : '—'}</td>
        <td style="padding:6px 10px;border-bottom:1px solid #e2e8f0;text-align:center">${d.survey_count}</td>
        <td style="padding:6px 10px;border-bottom:1px solid #e2e8f0;text-align:center;color:${sc(d.overall_pct)};font-weight:700">${d.overall_pct ?? '—'}%</td>
        <td style="padding:6px 10px;border-bottom:1px solid #e2e8f0;text-align:center;color:${sc(d.response_time_pct)};font-weight:700">${d.response_time_pct ?? '—'}%</td>
        <td style="padding:6px 10px;border-bottom:1px solid #e2e8f0;text-align:center;color:${sc(d.technician_pct)};font-weight:700">${d.technician_pct ?? '—'}%</td>
        <td style="padding:6px 10px;border-bottom:1px solid #e2e8f0;text-align:center;color:${sc(d.kept_informed_pct)};font-weight:700">${d.kept_informed_pct ?? '—'}%</td>
      </tr>`
    }).join('')
    const bonusColor = (gs.bonus_per_sa ?? 0) > 0 ? '#34d399' : '#999'
    const bonusHtml = isContractor ? `
        <div style="background:${(gs.bonus_per_sa ?? 0) > 0 ? '#ecfdf5' : '#f8fafc'};border:1px solid ${(gs.bonus_per_sa ?? 0) > 0 ? '#a7f3d0' : '#e2e8f0'};border-radius:8px;padding:12px;margin-bottom:16px">
            <span style="font-size:13px;font-weight:700;color:${bonusColor}">Garage Bonus: Tech ${gs.technician_pct ?? '—'}% → $${gs.bonus_per_sa ?? 0}/SA × ${gs.total_completed ?? 0} completed = $${gs.total_bonus ?? 0}</span>
        </div>` : ''
    return `
      <div style="font-family:Segoe UI,Arial,sans-serif;max-width:700px;color:#1e293b">
        <h2 style="margin:0 0 4px;color:#0f172a">${garageName}</h2>
        <p style="margin:0 0 20px;color:#64748b;font-size:13px">Performance Report — ${startDate} to ${endDate}</p>
        <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:16px;margin-bottom:16px">
          <h3 style="margin:0 0 8px;color:#7c3aed;font-size:14px">Executive Summary</h3>
          <p style="margin:0;font-size:13px;line-height:1.6;color:#334155">${(aiSummary || 'No AI summary available.').replace(/\n/g, '<br>')}</p>
        </div>
        <table style="width:100%;border-collapse:collapse;margin-bottom:16px">
          <tr>
            <td style="padding:10px;text-align:center;background:#f1f5f9;border-radius:6px 0 0 6px">
              <div style="font-size:22px;font-weight:800;color:#0f172a">${ov.total_sas ?? 0}</div>
              <div style="font-size:11px;color:#64748b">Total SAs</div>
            </td>
            <td style="padding:10px;text-align:center;background:#f1f5f9">
              <div style="font-size:22px;font-weight:800;color:#10b981">${ov.completed ?? 0}</div>
              <div style="font-size:11px;color:#64748b">Completed</div>
            </td>
            <td style="padding:10px;text-align:center;background:#f1f5f9">
              <div style="font-size:22px;font-weight:800;color:#ef4444">${ov.declined ?? 0}</div>
              <div style="font-size:11px;color:#64748b">Declined</div>
            </td>
            <td style="padding:10px;text-align:center;background:#f1f5f9">
              <div style="font-size:18px;font-weight:700;color:${(ov.avg_ata ?? 999) <= 45 ? '#10b981' : '#ef4444'}">${ov.avg_ata != null ? ov.avg_ata + 'm' : '—'}</div>
              <div style="font-size:11px;color:#64748b">Avg ATA</div>
            </td>
            <td style="padding:10px;text-align:center;background:#f1f5f9;border-radius:0 6px 6px 0">
              <div style="font-size:18px;font-weight:700;color:${(ov.pta_hit_pct ?? 0) >= 80 ? '#10b981' : '#ef4444'}">${ov.pta_hit_pct != null ? ov.pta_hit_pct + '%' : '—'}</div>
              <div style="font-size:11px;color:#64748b">PTA Hit Rate</div>
            </td>
          </tr>
        </table>
        <h3 style="margin:0 0 8px;font-size:13px;color:#64748b;text-transform:uppercase;letter-spacing:1px">Satisfaction Scores (Totally Satisfied %)</h3>
        <table style="width:100%;border-collapse:collapse;margin-bottom:16px">
          <tr>
            ${[['Overall', gs.overall_pct], ['Response Time', gs.response_time_pct], ['Technician', gs.technician_pct], ['Kept Informed', gs.kept_informed_pct]].map(([l, p]) =>
              `<td style="padding:10px;text-align:center;background:#f8fafc;border:1px solid #e2e8f0">
                <div style="font-size:11px;color:#64748b">${l}</div>
                <div style="font-size:24px;font-weight:800;color:${sc(p)}">${p ?? '—'}%</div>
              </td>`
            ).join('')}
          </tr>
        </table>
        ${bonusHtml}
        <h3 style="margin:0 0 8px;font-size:13px;color:#64748b;text-transform:uppercase;letter-spacing:1px">Driver Breakdown (${drivers.length} drivers)</h3>
        <table style="width:100%;border-collapse:collapse;font-size:13px;margin-bottom:16px">
          <tr style="background:#1e293b;color:#fff">
            <th style="padding:8px 10px;text-align:left">Driver</th>
            <th style="padding:8px 10px;text-align:center">Completed</th>
            <th style="padding:8px 10px;text-align:center">Declined</th>
            <th style="padding:8px 10px;text-align:center">Avg ATA</th>
            <th style="padding:8px 10px;text-align:center">Surveys</th>
            <th style="padding:8px 10px;text-align:center">Overall</th>
            <th style="padding:8px 10px;text-align:center">Resp Time</th>
            <th style="padding:8px 10px;text-align:center">Technician</th>
            <th style="padding:8px 10px;text-align:center">Informed</th>
          </tr>
          ${driverTableRows}
        </table>
        <p style="font-size:11px;color:#94a3b8;margin:16px 0 0">Generated by <strong style="color:#6366f1">FleetPulse</strong> · ${gs.total_surveys ?? 0} surveys · ${startDate} to ${endDate}</p>
        <p style="font-size:10px;color:#64748b;margin:2px 0 0">@NourLaaroubi</p>
      </div>`
  }

  return (
    <div className="space-y-4">
      {/* Date range info + Export */}
      <div className="flex items-center justify-between">
        <div className="text-[10px] text-slate-500">
          {gs.total_surveys || 0} surveys · {gs.total_completed || 0} completed SAs · {startDate} to {endDate}
        </div>
        {data && !loading && (
          <div className="flex items-center gap-2">
            <div className="relative">
              <button
                onClick={() => { setEmailOpen(!emailOpen); setEmailSent(false) }}
                className={clsx("flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-medium border rounded-lg transition",
                  emailOpen ? "text-blue-400 bg-blue-900/30 border-blue-500/40" : "text-blue-300 bg-blue-900/20 hover:bg-blue-800/30 border-blue-700/40")}
              >
                <Mail className="w-3.5 h-3.5" />
                Email Report
              </button>
              {emailOpen && (
                <div className="absolute top-full right-0 mt-1 bg-slate-800 border border-slate-700 rounded-lg p-3 shadow-xl z-20 w-72">
                  {emailSent ? (
                    <div className="text-emerald-400 text-xs font-medium text-center py-2">Sent!</div>
                  ) : (
                    <div className="flex gap-2">
                      <input type="email" value={emailTo} onChange={e => setEmailTo(e.target.value)}
                        placeholder="recipient@email.com"
                        className="flex-1 bg-slate-900 border border-slate-700 rounded-md px-2.5 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-blue-500/50"
                        onKeyDown={e => {
                          if (e.key === 'Enter' && emailTo) {
                            setEmailSending(true)
                            emailGarageReport(garageId, emailTo, startDate, endDate, garageName)
                              .then(() => { setEmailSent(true); setTimeout(() => { setEmailOpen(false); setEmailSent(false) }, 2000) })
                              .catch(err => alert(err.response?.data?.detail || 'Failed to send'))
                              .finally(() => setEmailSending(false))
                          }
                        }}
                      />
                      <button
                        disabled={emailSending || !emailTo}
                        onClick={() => {
                          setEmailSending(true)
                          emailGarageReport(garageId, emailTo, startDate, endDate, garageName)
                            .then(() => { setEmailSent(true); setTimeout(() => { setEmailOpen(false); setEmailSent(false) }, 2000) })
                            .catch(err => alert(err.response?.data?.detail || 'Failed to send'))
                            .finally(() => setEmailSending(false))
                        }}
                        className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 text-white text-xs font-medium rounded-md transition"
                      >
                        {emailSending ? '...' : 'Send'}
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
            <button
              onClick={() => {
                const w = window.open('', '_blank')
                w.document.write(`<!DOCTYPE html><html><head><title>${garageName} — Performance Report</title>
                  <style>@media print { body { -webkit-print-color-adjust: exact; print-color-adjust: exact; } } body { margin: 40px; }</style>
                </head><body>${buildReportHtml()}</body></html>`)
                w.document.close()
                setTimeout(() => w.print(), 300)
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-medium border rounded-lg transition text-slate-300 bg-slate-800/60 hover:bg-slate-700/60 border-slate-700/40"
            >
              <FileText className="w-3.5 h-3.5" />
              PDF
            </button>
            <button
              disabled={exporting}
              onClick={() => {
                setExporting(true)
                exportGarageScorecard(garageId, startDate, endDate)
                setTimeout(() => setExporting(false), 5000)
              }}
              className={clsx("flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-medium border rounded-lg transition",
                exporting
                  ? "text-amber-400 bg-amber-900/20 border-amber-700/40 cursor-wait"
                  : "text-slate-300 bg-slate-800/60 hover:bg-slate-700/60 border-slate-700/40"
              )}
            >
              {exporting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
              {exporting ? 'Generating...' : 'Export Excel'}
            </button>
          </div>
        )}
      </div>

      {error && <div className="text-red-400 text-sm bg-red-950/30 rounded-lg p-3 border border-red-800/30">{error}</div>}

      {loading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
          <span className="ml-2 text-sm text-slate-500">Loading scorecard...</span>
        </div>
      )}

      {data && !loading && (<>
        {/* AI Executive Summary — first, async loaded */}
        <div className="glass rounded-xl p-4 border border-purple-800/20">
          <div className="flex items-center gap-2 mb-3">
            <Sparkles className="w-4 h-4 text-purple-400" />
            <span className="text-xs font-bold text-white uppercase tracking-wide">AI Executive Summary</span>
          </div>
          {aiLoading && (
            <div className="flex items-center gap-2 py-4">
              <Loader2 className="w-4 h-4 animate-spin text-purple-400" />
              <span className="text-xs text-slate-500">Generating analysis...</span>
            </div>
          )}
          {aiSummary && !aiLoading && (
            <div className="text-xs text-slate-300 leading-relaxed whitespace-pre-wrap">{aiSummary}</div>
          )}
          {!aiSummary && !aiLoading && (
            <div className="text-xs text-slate-600 py-2">No AI summary available. Configure AI in Admin → AI Assistant.</div>
          )}
        </div>

        {/* ══ Overall Garage Stats ══ */}
        {(() => {
          const ov = ps.overall || {}
          return (
            <div className="glass rounded-xl p-4 border border-slate-700/30 space-y-3">
              <div className="text-xs font-bold text-white uppercase tracking-wide">Overall Garage Performance</div>

              {/* SA Metrics */}
              <div className="grid grid-cols-3 md:grid-cols-5 gap-2">
                <div className="bg-slate-800/40 rounded-lg p-2 text-center">
                  <div className="text-lg font-bold text-white">{ov.total_sas ?? 0}</div>
                  <div className="text-[10px] text-slate-400">Total SAs</div>
                </div>
                <div className="bg-slate-800/40 rounded-lg p-2 text-center">
                  <div className="text-lg font-bold text-emerald-400">{ov.completed ?? 0}</div>
                  <div className="text-[10px] text-slate-400">Completed</div>
                </div>
                <div className="bg-slate-800/40 rounded-lg p-2 text-center">
                  <div className="text-lg font-bold text-red-400">{ov.declined ?? 0}</div>
                  <div className="text-[10px] text-slate-400">Declined</div>
                </div>
                <div className="bg-slate-800/40 rounded-lg p-2 text-center">
                  <div className={clsx('text-sm font-bold', (ov.avg_ata ?? 999) <= 45 ? 'text-emerald-400' : (ov.avg_ata ?? 999) <= 60 ? 'text-amber-400' : 'text-red-400')}>
                    {ov.avg_ata != null ? `${ov.avg_ata}m` : '—'}
                  </div>
                  <div className="text-[10px] text-slate-400">Avg ATA</div>
                </div>
                <div className="bg-slate-800/40 rounded-lg p-2 text-center">
                  <div className={clsx('text-sm font-bold', (ov.pta_hit_pct ?? 0) >= 80 ? 'text-emerald-400' : (ov.pta_hit_pct ?? 0) >= 60 ? 'text-amber-400' : 'text-red-400')}>
                    {ov.pta_hit_pct != null ? `${ov.pta_hit_pct}%` : '—'}
                  </div>
                  <div className="text-[10px] text-slate-400">PTA Hit Rate</div>
                </div>
              </div>

              {/* Satisfaction Scores */}
              <div className="grid grid-cols-4 gap-2 text-center pt-2 border-t border-slate-800/40">
                {[['Overall', ov.overall_pct], ['Response Time', ov.response_time_pct], ['Technician', ov.technician_pct], ['Kept Informed', ov.kept_informed_pct]].map(([lbl, pct]) => (
                  <div key={lbl}>
                    <div className="text-[10px] text-slate-400 mb-0.5">{lbl}</div>
                    <div className={clsx('text-lg font-bold', scoreColor(pct))}>{pct ?? '—'}%</div>
                  </div>
                ))}
              </div>

              {/* Garage-level Bonus (contractors only — fleet are internal employees) */}
              {isContractor && gs.technician_pct != null && (
                <div className={clsx('flex items-center gap-2 pt-2 border-t border-slate-800/40 text-xs',
                  gs.bonus_per_sa > 0 ? 'text-emerald-400' : 'text-slate-500')}>
                  <DollarSign className="w-4 h-4" />
                  <span className="font-bold">
                    Garage Bonus: Tech {gs.technician_pct}% → ${gs.bonus_per_sa}/SA × {gs.total_completed} completed = <span className="text-white">${gs.total_bonus}</span>
                  </span>
                </div>
              )}
              <div className="text-[9px] text-slate-600 text-right">{ov.survey_count || 0} surveys</div>
            </div>
          )
        })()}

        {/* ══ Primary vs Secondary ══ */}
        <div className="glass rounded-xl p-4 border border-slate-700/30">
          <div className="text-xs font-bold text-white uppercase tracking-wide mb-3">Primary vs Secondary Assignments</div>
          <div className="grid grid-cols-2 gap-4">
            {['primary', 'secondary'].map(type => {
              const g = ps[type] || {}
              const label = type === 'primary' ? 'Primary (First Assigned)' : 'Secondary (Reassigned Here)'
              return (
                <div key={type} className="bg-slate-900/40 rounded-lg p-3 space-y-3">
                  <div className="text-[10px] text-slate-500 uppercase font-bold">{label}</div>

                  {/* SA Metrics */}
                  <div className="grid grid-cols-3 gap-2">
                    <div className="bg-slate-800/40 rounded-lg p-2 text-center">
                      <div className="text-lg font-bold text-white">{g.total_sas ?? 0}</div>
                      <div className="text-[10px] text-slate-400">Total SAs</div>
                    </div>
                    <div className="bg-slate-800/40 rounded-lg p-2 text-center">
                      <div className="text-lg font-bold text-emerald-400">{g.completed ?? 0}</div>
                      <div className="text-[10px] text-slate-400">Completed</div>
                    </div>
                    <div className="bg-slate-800/40 rounded-lg p-2 text-center">
                      <div className="text-lg font-bold text-red-400">{g.declined ?? 0}</div>
                      <div className="text-[10px] text-slate-400">Declined</div>
                    </div>
                  </div>

                  {/* ATA + PTA */}
                  <div className="grid grid-cols-2 gap-2">
                    <div className="bg-slate-800/40 rounded-lg p-2 text-center">
                      <div className={clsx('text-sm font-bold', (g.avg_ata ?? 999) <= 45 ? 'text-emerald-400' : (g.avg_ata ?? 999) <= 60 ? 'text-amber-400' : 'text-red-400')}>
                        {g.avg_ata != null ? `${g.avg_ata}m` : '—'}
                      </div>
                      <div className="text-[10px] text-slate-400">Avg ATA</div>
                    </div>
                    <div className="bg-slate-800/40 rounded-lg p-2 text-center">
                      <div className={clsx('text-sm font-bold', (g.pta_hit_pct ?? 0) >= 80 ? 'text-emerald-400' : (g.pta_hit_pct ?? 0) >= 60 ? 'text-amber-400' : 'text-red-400')}>
                        {g.pta_hit_pct != null ? `${g.pta_hit_pct}%` : '—'}
                      </div>
                      <div className="text-[10px] text-slate-400">PTA Hit Rate</div>
                    </div>
                  </div>

                  {/* Satisfaction Scores */}
                  <div className="grid grid-cols-4 gap-2 text-center pt-2 border-t border-slate-800/40">
                    {[['Overall', g.overall_pct], ['Response Time', g.response_time_pct], ['Technician', g.technician_pct], ['Kept Informed', g.kept_informed_pct]].map(([lbl, pct]) => (
                      <div key={lbl}>
                        <div className="text-[10px] text-slate-400 mb-0.5">{lbl}</div>
                        <div className={clsx('text-lg font-bold', scoreColor(pct))}>{pct ?? '—'}%</div>
                      </div>
                    ))}
                  </div>
                  <div className="text-[9px] text-slate-600 text-right">{g.survey_count || 0} surveys</div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Driver Breakdown */}
        <div className="glass rounded-xl border border-slate-700/30 overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-800/50 flex items-center gap-2">
            <Star className="w-4 h-4 text-amber-400" />
            <span className="text-xs font-bold text-white uppercase tracking-wide">Driver Breakdown</span>
            <span className="text-[10px] text-slate-500 ml-auto">{drivers.length} drivers</span>
          </div>
          {/* Sort header */}
          <div className="flex items-center gap-3 px-3 py-1.5 bg-slate-900/60 text-[10px] text-slate-400 uppercase tracking-wider border-b border-slate-800/40">
            <div className="w-4" />
            <div className="flex-1">Driver</div>
            {[['completed', 'Compl', 'w-14'], ['declined', 'Decl', 'w-14'], ['avg_ata', 'ATA', 'w-14'], ['overall_pct', 'Overall', 'w-14'], ['response_time_pct', 'Resp', 'w-14'], ['technician_pct', 'Tech', 'w-14'], ['kept_informed_pct', 'Informed', 'w-14']].map(([field, label, w]) => (
              <button key={field} className={clsx('text-center cursor-pointer hover:text-white transition', w, sortBy === field && 'text-blue-400')}
                onClick={() => toggleSort(field)}>
                {label} {sortBy === field && (sortDir === 'desc' ? '↓' : '↑')}
              </button>
            ))}
          </div>
          <div className="max-h-[500px] overflow-y-auto">
            {sorted.map((d, i) => (
              <DriverRow key={i} driver={d}
                expanded={expandedDriver === d.name}
                onToggle={() => setExpandedDriver(expandedDriver === d.name ? null : d.name)}
                garageId={garageId} startDate={startDate} endDate={endDate} />
            ))}
          </div>
        </div>
      </>)}
    </div>
  )
}
