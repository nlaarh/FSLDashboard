/**
 * SAReportModal.jsx
 *
 * Full-screen SA History Report modal.
 * Shows:  timeline  *  per-assignment driver snapshots (map + table)  *  narrative
 *
 * Opened via SAReportContext (see App.jsx).
 * Can also be opened directly: <SAReportModal saNumber="SA-717120" onClose={fn} />
 */

import { useState, useEffect, useRef } from 'react'
import { X, Printer, Loader2, Truck, ExternalLink } from 'lucide-react'
import { fetchSAReport } from '../api'
import { TimelineSection, AssignStepsSection } from './SAReportTimeline'

// ── Main modal ────────────────────────────────────────────────────────────────
export default function SAReportModal({ saNumber, onClose }) {
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const printRef = useRef(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchSAReport(saNumber)
      .then(setReport)
      .catch(e => setError(e.response?.data?.detail || 'Failed to load report'))
      .finally(() => setLoading(false))
  }, [saNumber])

  // Close on Escape
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const handlePrint = () => {
    const el = printRef.current
    if (!el) return
    const orig = document.body.innerHTML
    document.body.innerHTML = el.innerHTML
    window.print()
    document.body.innerHTML = orig
    window.location.reload()
  }

  const sa    = report?.sa_summary
  const tl    = report?.timeline || []
  const steps = report?.assign_steps || []
  const narr  = report?.narrative || []

  // Status color
  const statusColor = {
    Completed:            '#10b981',
    Canceled:             '#ef4444',
    'On Location':        '#22c55e',
    'En Route':           '#8b5cf6',
    Dispatched:           '#6366f1',
    Assigned:             '#3b82f6',
  }[sa?.status] || '#94a3b8'

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 9999,
      background: 'rgba(0,0,0,0.85)', display: 'flex', alignItems: 'flex-start',
      justifyContent: 'center', overflowY: 'auto', padding: '24px 16px',
    }}>
      <div style={{
        width: '100%', maxWidth: 900, background: '#0b1120',
        borderRadius: 12, border: '1px solid #1e293b',
        boxShadow: '0 24px 64px rgba(0,0,0,0.8)',
      }}>
        {/* ── Header ──────────────────────────────────────────────────────── */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 12, padding: '16px 20px',
          borderBottom: '1px solid #1e293b',
        }}>
          <Truck size={18} color="#6366f1" />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 16, fontWeight: 700, color: '#e2e8f0' }}>
              SA History Report — {saNumber}
            </div>
            {sa && (
              <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>
                {sa.work_type} · {sa.territory} · Created {sa.created}
                {/* Garage type badge */}
                {sa.garage_type && (() => {
                  const gt = sa.garage_type
                  const cfg = gt === 'Fleet'
                    ? { bg: 'rgba(99,102,241,0.12)', color: '#818cf8' }
                    : gt === 'Towbook'
                    ? { bg: 'rgba(239,68,68,0.1)',   color: '#ef4444' }
                    : { bg: 'rgba(234,179,8,0.1)',   color: '#eab308' }  // On-Platform Contractor
                  return (
                    <span style={{
                      marginLeft: 8, padding: '1px 6px', borderRadius: 4,
                      fontSize: 10, fontWeight: 700,
                      background: cfg.bg, color: cfg.color,
                    }}>
                      {gt}
                    </span>
                  )
                })()}
                {sa.status && (
                  <span style={{
                    marginLeft: 6, padding: '1px 6px', borderRadius: 4, fontSize: 10, fontWeight: 600,
                    background: `${statusColor}15`, color: statusColor,
                  }}>
                    {sa.status}
                  </span>
                )}
              </div>
            )}
          </div>
          {report?.sa_summary?.sf_url && (
            <a href={report.sa_summary.sf_url} target="_blank" rel="noopener noreferrer"
              style={{ background: 'none', border: '1px solid #334155', borderRadius: 6, padding: '4px 10px',
                       cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 5,
                       color: '#94a3b8', fontSize: 11, textDecoration: 'none' }}>
              <ExternalLink size={13} /> Salesforce
            </a>
          )}
          <button onClick={handlePrint}
            style={{ background: 'none', border: '1px solid #334155', borderRadius: 6, padding: '4px 10px',
                     cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 5,
                     color: '#94a3b8', fontSize: 11 }}>
            <Printer size={13} /> Print
          </button>
          <button onClick={onClose}
            style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}>
            <X size={20} color="#64748b" />
          </button>
        </div>

        {/* ── Body ────────────────────────────────────────────────────────── */}
        <div ref={printRef} style={{ padding: '20px' }}>
          {loading && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#64748b',
                          justifyContent: 'center', padding: '40px 0' }}>
              <Loader2 size={18} className="animate-spin" />
              Loading SA report...
            </div>
          )}

          {error && (
            <div style={{ color: '#ef4444', padding: '20px', textAlign: 'center' }}>
              {error}
            </div>
          )}

          {report && (
            <>
              {/* ── Narrative ─────────────────────────────────────────────── */}
              {narr.length > 0 && (
                <section style={{ marginBottom: 24 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b',
                                textTransform: 'uppercase', letterSpacing: 1, marginBottom: 10 }}>
                    Summary
                  </div>
                  <div style={{
                    background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8,
                    padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 6,
                  }}>
                    {narr.map((line, i) => (
                      <div key={i} style={{ fontSize: 12, color: '#cbd5e1', lineHeight: 1.6 }}>
                        {line}
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* ── Phase Bar — time spent in each lifecycle phase ───────── */}
              {report.phases?.length > 0 && (() => {
                const phases = report.phases
                const totalMin = phases.reduce((s, p) => s + p.minutes, 0)
                const fmtMin = v => v < 1 ? '<1m' : `${Math.round(v)}m`
                const fmtTotal = totalMin < 1 ? '<1 min' : `${Math.round(totalMin * 10) / 10} min`
                return (
                  <section style={{ marginBottom: 24 }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b',
                                  textTransform: 'uppercase', letterSpacing: 1, marginBottom: 10 }}>
                      Time Breakdown — {fmtTotal} total
                    </div>
                    {/* Visual bar */}
                    <div style={{
                      display: 'flex', borderRadius: 6, overflow: 'hidden', height: 28,
                      border: '1px solid #1e293b', background: '#0f172a',
                    }}>
                      {phases.map((p, i) => {
                        const pct = Math.max((p.minutes / totalMin) * 100, 2)
                        return (
                          <div key={i} title={`${p.label}: ${p.minutes} min (${p.start_time} \u2192 ${p.end_time})`}
                            style={{
                              width: `${pct}%`, background: p.color, opacity: 0.85,
                              display: 'flex', alignItems: 'center', justifyContent: 'center',
                              fontSize: 9, fontWeight: 700, color: '#fff',
                              borderRight: i < phases.length - 1 ? '1px solid #0b1120' : 'none',
                              whiteSpace: 'nowrap', overflow: 'hidden', cursor: 'default',
                            }}>
                            {pct > 8 ? fmtMin(p.minutes) : ''}
                          </div>
                        )
                      })}
                    </div>
                    {/* Legend */}
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 16px', marginTop: 8 }}>
                      {phases.map((p, i) => (
                        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 10 }}>
                          <span style={{ width: 8, height: 8, borderRadius: 2, background: p.color, flexShrink: 0 }} />
                          <span style={{ color: '#94a3b8' }}>{p.label}</span>
                          <span style={{ color: '#e2e8f0', fontWeight: 700 }}>{fmtMin(p.minutes)}</span>
                          {p.driver && <span style={{ color: '#64748b' }}>({p.driver})</span>}
                          {p.reason && <span style={{ color: '#fb923c', fontSize: 9, fontStyle: 'italic' }}>{p.reason}</span>}
                        </div>
                      ))}
                    </div>
                  </section>
                )
              })()}

              {/* ── Reassignment Impact ──────────────────────────────────── */}
              {report.reassignment_impact && (() => {
                const ri = report.reassignment_impact
                const delta = ri.pta_delta_minutes
                const borderColor = delta > 0 ? '#ef4444' : delta < 0 ? '#22c55e' : delta === 0 ? '#22c55e' : '#64748b'
                return (
                  <section style={{ marginBottom: 24 }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b',
                                  textTransform: 'uppercase', letterSpacing: 1, marginBottom: 10 }}>
                      Reassignment Impact — {ri.reassignment_count} reassignment{ri.reassignment_count > 1 ? 's' : ''}
                    </div>
                    <div style={{
                      background: '#0f172a', border: `1px solid ${borderColor}40`, borderRadius: 8,
                      padding: '14px 16px', borderLeft: `3px solid ${borderColor}`,
                    }}>
                      <div style={{ fontSize: 12, color: '#94a3b8', fontStyle: 'italic', marginBottom: 10 }}>
                        Did the member get what they were promised?
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
                        <div>
                          <div style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase' }}>PTA (Promised)</div>
                          <div style={{ fontSize: 22, color: '#e2e8f0', fontWeight: 800 }}>
                            {ri.pta_minutes ? `${ri.pta_minutes}m` : '\u2014'}
                          </div>
                        </div>
                        <div>
                          <div style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase' }}>ATA (Actual)</div>
                          <div style={{ fontSize: 22, color: '#e2e8f0', fontWeight: 800 }}>
                            {ri.actual_ata_minutes ? `${ri.actual_ata_minutes}m` : '\u2014'}
                          </div>
                        </div>
                        <div>
                          <div style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase' }}>Result</div>
                          <div style={{ fontSize: 22, fontWeight: 800, color: borderColor }}>
                            {delta != null ? (delta > 0 ? `${delta}m late` : delta < 0 ? `${Math.abs(delta)}m early` : 'On time') : '\u2014'}
                          </div>
                        </div>
                      </div>
                      <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 12, display: 'flex', gap: 20 }}>
                        <span>First: {ri.first_driver}</span>
                        <span>Final: {ri.final_driver}</span>
                        {ri.on_location_time && <span>On Location: {ri.on_location_time}</span>}
                      </div>
                      <div style={{ fontSize: 11, color: '#64748b', marginTop: 8, borderTop: '1px solid #1e293b', paddingTop: 6 }}>
                        PTA ({ri.pta_minutes}m) \u2212 ATA ({ri.actual_ata_minutes}m) = {ri.actual_ata_minutes && ri.pta_minutes ? `${Math.abs(delta)}m ${delta > 0 ? 'late' : delta < 0 ? 'early' : 'on time'}` : '\u2014'}
                      </div>
                      {/* vs Original Plan — scheduler prediction accuracy */}
                      {(() => {
                        if (!steps.length || !steps[0].sched_start_initial) return null
                        const firstEta = steps[0].sched_start_initial
                        const completedEv = tl.find(e => e.event === 'Completed')
                        if (!completedEv) return null
                        const parseT = (t) => {
                          const m = t.match(/(\d+):(\d+)\s*(AM|PM)/i)
                          if (!m) return null
                          let h = parseInt(m[1]), mi = parseInt(m[2])
                          if (m[3].toUpperCase() === 'PM' && h !== 12) h += 12
                          if (m[3].toUpperCase() === 'AM' && h === 12) h = 0
                          return h * 60 + mi
                        }
                        const cMatch = completedEv.time && completedEv.time.match(/\d+:\d+\s*[AP]M/i)
                        const cLabel = cMatch ? cMatch[0] : null
                        const cTime = cMatch ? parseT(cMatch[0]) : null
                        const eTime = parseT(firstEta)
                        if (cTime == null || eTime == null) return null
                        const planDelta = cTime - eTime
                        return (
                          <div style={{ marginTop: 12, borderTop: '1px solid #1e293b', paddingTop: 10 }}>
                            <div style={{ fontSize: 12, color: '#94a3b8', fontStyle: 'italic', marginBottom: 6 }}>
                              Did the job finish on the scheduler's original plan?
                            </div>
                            <div style={{ fontSize: 18, fontWeight: 700, color: planDelta <= 0 ? '#22c55e' : '#f97316' }}>
                              {planDelta <= 0 ? `${Math.abs(planDelta)}m early` : `${planDelta}m late`}
                              <span style={{ fontSize: 12, fontWeight: 400, color: '#64748b' }}> vs original plan</span>
                            </div>
                            <div style={{ fontSize: 11, color: '#64748b', marginTop: 3 }}>
                              Completed ({cLabel}) \u2212 First ETA ({firstEta}) = {Math.abs(planDelta)}m
                            </div>
                          </div>
                        )
                      })()}
                    </div>
                  </section>
                )
              })()}

              {/* ── Timeline (extracted) ──────────────────────────────────── */}
              <TimelineSection tl={tl} steps={steps} />

              {/* ── Assignment steps (extracted) ──────────────────────────── */}
              <AssignStepsSection steps={steps} sa={sa} />

              {/* SA detail footer */}
              {sa && (
                <div style={{
                  background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8,
                  padding: '12px 16px', fontSize: 11, color: '#64748b',
                  display: 'flex', flexWrap: 'wrap', gap: '6px 20px',
                }}>
                  <span><span style={{ color: '#475569' }}>Address:</span> {sa.address || '\u2014'}</span>
                  {sa.pta && sa.pta > 0 && sa.pta < 999 &&
                    <span><span style={{ color: '#475569' }}>PTA:</span> {sa.pta} min</span>}
                  {sa.response_min &&
                    <span><span style={{ color: '#475569' }}>Response:</span> {sa.response_min} min</span>}
                  {sa.truck_id &&
                    <span><span style={{ color: '#475569' }}>Truck:</span> {sa.truck_id}</span>}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
