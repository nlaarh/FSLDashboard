/**
 * SAReportModal.jsx
 *
 * Full-screen SA History Report modal.
 * Shows:  timeline  •  per-assignment driver snapshots (map + table)  •  narrative
 *
 * Opened via SAReportContext (see App.jsx).
 * Can also be opened directly: <SAReportModal saNumber="SA-717120" onClose={fn} />
 */

import { useState, useEffect, useRef } from 'react'
import { MapContainer, TileLayer, Marker, Popup, Tooltip } from 'react-leaflet'
import { X, Printer, Loader2, AlertCircle, CheckCircle2, Clock,
         MapPin, Truck, User, ChevronDown, ChevronUp } from 'lucide-react'
import { fetchSAReport } from '../api'
import { truckIcon, CUSTOMER_ICON, TRUCK_COLORS } from '../mapIcons'
import { getMapConfig } from '../mapStyles'

// ── Timeline event icons / colors ─────────────────────────────────────────────
const EVENT_STYLE = {
  'Received':           { color: '#64748b', label: 'Received' },
  'Assigned':           { color: '#3b82f6', label: 'Assigned' },
  'Reassigned':         { color: '#f97316', label: 'Reassigned' },
  'Dispatched':         { color: '#6366f1', label: 'Dispatched' },
  'En Route':           { color: '#8b5cf6', label: 'En Route' },
  'On Location':        { color: '#22c55e', label: 'On Location' },
  'Completed':          { color: '#10b981', label: 'Completed' },
  'Canceled':           { color: '#ef4444', label: 'Canceled' },
  'No-Show':            { color: '#f59e0b', label: 'No-Show' },
  'Unable to Complete': { color: '#f59e0b', label: 'Unable' },
}

function TimelineDot({ event }) {
  const s = EVENT_STYLE[event] || { color: '#94a3b8', label: event }
  return (
    <div style={{
      width: 12, height: 12, borderRadius: '50%',
      background: s.color, flexShrink: 0, marginTop: 3,
    }} />
  )
}

// ── Driver snapshot mini-map ──────────────────────────────────────────────────
function StepMap({ step, saLat, saLon }) {
  const mapCfg = getMapConfig()
  const drivers = step.step_drivers || []
  if (!saLat || !saLon || drivers.length === 0) return null

  return (
    <div style={{ height: 220, borderRadius: 8, overflow: 'hidden', border: '1px solid #1e293b' }}>
      <MapContainer
        center={[saLat, saLon]} zoom={11}
        style={{ height: '100%', width: '100%' }}
        zoomControl={false} attributionControl={false}
      >
        <TileLayer url={mapCfg.url} />

        {/* Customer */}
        <Marker position={[saLat, saLon]} icon={CUSTOMER_ICON} zIndexOffset={1000}>
          <Popup>
            <div style={{ fontSize: 11, color: '#e2e8f0' }}>Member location</div>
          </Popup>
        </Marker>

        {/* Drivers */}
        {drivers.map(d => {
          if (!d.lat || !d.lon) return null
          let colorKey = 'eligible'
          if (d.is_assigned && d.is_closest) colorKey = 'assigned_closest'
          else if (d.is_assigned) colorKey = 'dispatched'
          else if (d.is_closest) colorKey = 'closest'
          else if (!d.has_skills) colorKey = 'ineligible'
          const distLabel = d.distance != null ? `${d.distance} mi` : '?'
          const roleLabel = d.is_assigned && d.is_closest ? 'ASSIGNED · CLOSEST'
                          : d.is_assigned                 ? 'ASSIGNED'
                          : d.is_closest                  ? 'CLOSEST ELIGIBLE'
                          : d.has_skills                  ? 'ELIGIBLE'
                          : 'NO MATCHING SKILLS'
          const roleColor = d.is_assigned && d.is_closest ? '#facc15'
                          : d.is_assigned                 ? '#f97316'
                          : d.is_closest                  ? '#22c55e'
                          : d.has_skills                  ? '#64748b'
                          : '#334155'
          return (
            <Marker key={d.driver_id} position={[d.lat, d.lon]}
              icon={truckIcon(colorKey, distLabel, d.is_assigned)}
              zIndexOffset={d.is_assigned ? 900 : d.is_closest ? 800 : 100}>
              <Tooltip direction="top" offset={[0, -12]} opacity={0.97} permanent={false}>
                <div style={{ fontSize: 11, color: '#e2e8f0', minWidth: 160,
                              fontFamily: '-apple-system, sans-serif', lineHeight: 1.5 }}>
                  <div style={{ fontWeight: 700, fontSize: 13 }}>{d.name}</div>
                  <div style={{ color: '#94a3b8', marginTop: 1 }}>
                    {d.distance != null ? `${d.distance} mi from member` : 'Distance unknown'}
                  </div>
                  <div style={{ color: roleColor, fontWeight: 700, fontSize: 10,
                                marginTop: 3, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                    {roleLabel}
                  </div>
                </div>
              </Tooltip>
            </Marker>
          )
        })}
      </MapContainer>
    </div>
  )
}

// ── Driver table for one assignment step ──────────────────────────────────────
function StepDriverTable({ drivers }) {
  if (!drivers || drivers.length === 0) return null
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
      <thead>
        <tr style={{ color: '#64748b', textAlign: 'left' }}>
          <th style={{ padding: '4px 6px', borderBottom: '1px solid #1e293b' }}>Driver</th>
          <th style={{ padding: '4px 6px', borderBottom: '1px solid #1e293b', textAlign: 'right' }}>Distance</th>
          <th style={{ padding: '4px 6px', borderBottom: '1px solid #1e293b' }}>Role</th>
        </tr>
      </thead>
      <tbody>
        {drivers.map(d => {
          let roleTag = null
          let rowBg = 'transparent'
          if (d.is_assigned && d.is_closest) {
            roleTag = <span style={{ color: '#facc15', fontWeight: 700 }}>ASSIGNED + CLOSEST</span>
            rowBg = 'rgba(250,204,21,0.06)'
          } else if (d.is_assigned && d.no_gps) {
            roleTag = <span style={{ color: '#f97316', fontWeight: 700 }}>ASSIGNED — no GPS location</span>
            rowBg = 'rgba(249,115,22,0.06)'
          } else if (d.is_assigned) {
            roleTag = <span style={{ color: '#f97316', fontWeight: 700 }}>ASSIGNED</span>
            rowBg = 'rgba(249,115,22,0.06)'
          } else if (d.is_closest) {
            roleTag = <span style={{ color: '#22c55e', fontWeight: 700 }}>CLOSEST</span>
            rowBg = 'rgba(34,197,94,0.06)'
          } else if (!d.has_skills) {
            roleTag = <span style={{ color: '#475569' }}>No skills</span>
          }
          return (
            <tr key={d.driver_id} style={{ background: rowBg }}>
              <td style={{ padding: '4px 6px', color: '#e2e8f0' }}>{d.name}</td>
              <td style={{ padding: '4px 6px', color: '#94a3b8', textAlign: 'right' }}>
                {d.distance != null ? `${d.distance} mi` : '—'}
              </td>
              <td style={{ padding: '4px 6px' }}>{roleTag}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

// ── Single assignment step card ───────────────────────────────────────────────
function AssignStepCard({ step, index, saLat, saLon }) {
  const [expanded, setExpanded] = useState(index === 0)
  const isHuman   = step.is_human
  const drivers   = step.step_drivers || []
  const assigned  = drivers.find(d => d.is_assigned)
  const closest   = drivers.find(d => d.is_closest)
  const isOptimal = assigned && assigned.is_closest

  // Towbook step: driver name starts with 'Towbook-' or no fleet GPS data at all
  const isTowbookStep = (step.driver || '').toLowerCase().startsWith('towbook')
    || (step.is_reassignment && drivers.length === 0)

  const driversWithGps = drivers.filter(d => d.lat && d.lon)
  const hasMap = !isTowbookStep && saLat && saLon && driversWithGps.length > 0

  return (
    <div style={{ border: '1px solid #1e293b', borderRadius: 8, overflow: 'hidden', marginBottom: 8 }}>
      {/* Header row */}
      <button
        onClick={() => setExpanded(v => !v)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', gap: 10,
          padding: '10px 14px', background: '#0f172a', cursor: 'pointer',
          border: 'none', textAlign: 'left',
        }}
      >
        <div style={{
          width: 24, height: 24, borderRadius: '50%', flexShrink: 0,
          background: step.is_reassignment ? 'rgba(249,115,22,0.15)' : 'rgba(59,130,246,0.15)',
          border: `1px solid ${step.is_reassignment ? '#f97316' : '#3b82f6'}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 10, fontWeight: 700,
          color: step.is_reassignment ? '#f97316' : '#3b82f6',
        }}>
          {index + 1}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: '#e2e8f0' }}>
              {step.is_reassignment ? 'Reassigned' : 'First Dispatch'} → {step.driver}
            </span>
            {assigned && assigned.distance != null && !assigned.no_gps && (
              <span style={{ fontSize: 10, fontWeight: 700, color: assigned.is_closest ? '#22c55e' : '#f97316' }}>
                {assigned.distance} mi
              </span>
            )}
            {assigned && assigned.no_gps && (
              <span style={{ fontSize: 9, color: '#64748b', fontStyle: 'italic' }}>no GPS location</span>
            )}
            {step.reason && (
              <span style={{ fontSize: 9, color: '#fb923c', fontStyle: 'italic' }}>{step.reason}</span>
            )}
            {isTowbookStep && (
              <span style={{
                fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 3,
                background: 'rgba(217,70,239,0.12)', color: '#e879f9', textTransform: 'uppercase',
              }}>Towbook</span>
            )}
          </div>
          <div style={{ fontSize: 10, color: '#94a3b8' }}>
            {step.time}
            {isHuman && <span style={{ color: '#f97316', marginLeft: 6 }}>by {step.by_name} (manual)</span>}
            {assigned && closest && !isOptimal && (
              <span style={{ marginLeft: 6, color: '#64748b' }}>
                Closest was {closest.name} at {closest.distance} mi
              </span>
            )}
          </div>
        </div>
        {!isTowbookStep && (isOptimal
          ? <CheckCircle2 size={14} color="#22c55e" title="Optimal — closest driver assigned" />
          : assigned && <AlertCircle size={14} color="#f97316" title="Closest driver was not assigned" />)}
        {expanded ? <ChevronUp size={14} color="#475569" /> : <ChevronDown size={14} color="#475569" />}
      </button>

      {expanded && (
        <div style={{
          padding: '12px 14px', background: '#070f1a', display: 'grid', gap: 12,
          gridTemplateColumns: hasMap ? '1fr 1fr' : '1fr',
        }}>
          {isTowbookStep ? (
            <div style={{
              fontSize: 11, color: '#94a3b8', padding: '10px 12px',
              background: 'rgba(217,70,239,0.06)', border: '1px solid rgba(217,70,239,0.15)',
              borderRadius: 6,
            }}>
              <span style={{ color: '#e879f9', fontWeight: 700 }}>Towbook contractor</span>
              {' — '}off-platform dispatch. Driver location is not tracked on the FSL map.
            </div>
          ) : (
            <>
              <StepDriverTable drivers={drivers} />
              <StepMap step={step} saLat={saLat} saLon={saLon} />
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ── Map legend ────────────────────────────────────────────────────────────────
function MapLegend() {
  const items = [
    { color: TRUCK_COLORS.dispatched.fill,       label: 'Assigned driver' },
    { color: TRUCK_COLORS.closest.fill,          label: 'Closest eligible' },
    { color: TRUCK_COLORS.assigned_closest.fill, label: 'Assigned + closest (optimal)' },
    { color: TRUCK_COLORS.eligible.fill,         label: 'Other eligible driver' },
    { color: TRUCK_COLORS.ineligible.fill,       label: 'Missing skills' },
  ]
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 16px', fontSize: 10, color: '#64748b' }}>
      {items.map(({ color, label }) => (
        <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <div style={{ width: 10, height: 10, borderRadius: 2, background: color, flexShrink: 0 }} />
          {label}
        </div>
      ))}
    </div>
  )
}

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
              Loading SA report…
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
                const fmtTotal = totalMin < 1 ? '<1 min' : `${Math.round(totalMin)} min`
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
                          <div key={i} title={`${p.label}: ${p.minutes} min (${p.start_time} → ${p.end_time})`}
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

              {/* ── Timeline ──────────────────────────────────────────────── */}
              {tl.length > 0 && (
                <section style={{ marginBottom: 24 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b',
                                textTransform: 'uppercase', letterSpacing: 1, marginBottom: 10 }}>
                    Timeline
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
                    {tl.map((ev, i) => {
                      const s = EVENT_STYLE[ev.event] || { color: '#94a3b8' }
                      return (
                        <div key={i} style={{ display: 'flex', gap: 12, paddingLeft: 4 }}>
                          {/* Dot + connector */}
                          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 12 }}>
                            <TimelineDot event={ev.event} />
                            {i < tl.length - 1 && (
                              <div style={{ width: 1, flex: 1, minHeight: 14, background: '#1e293b', margin: '2px 0' }} />
                            )}
                          </div>
                          {/* Content */}
                          <div style={{ paddingBottom: 10, flex: 1 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                              <span style={{ fontSize: 12, fontWeight: 600, color: s.color }}>
                                {ev.event}
                              </span>
                              {ev.driver && (
                                <span style={{ fontSize: 11, color: '#e2e8f0' }}>→ {ev.driver}</span>
                              )}
                              {ev.reason && (
                                <span style={{ fontSize: 9, color: '#fb923c', fontStyle: 'italic' }}>{ev.reason}</span>
                              )}
                              <span style={{ fontSize: 10, color: '#475569' }}>{ev.time}</span>
                              {ev.by_name && ev.by_name.toLowerCase() !== 'mulesoft integration' &&
                               ev.by_name.toLowerCase() !== 'automated process' && (
                                <span style={{
                                  fontSize: 9, padding: '1px 5px', borderRadius: 3,
                                  background: ev.is_human ? 'rgba(249,115,22,0.1)' : 'rgba(100,116,139,0.1)',
                                  color: ev.is_human ? '#f97316' : '#64748b', fontWeight: 600,
                                }}>
                                  {ev.is_human ? '👤 ' : ''}{ev.by_name}
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </section>
              )}

              {/* ── Assignment steps ──────────────────────────────────────── */}
              {steps.length > 0 && (
                <section style={{ marginBottom: 24 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b',
                                textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>
                    Dispatch Snapshots
                  </div>
                  <div style={{ marginBottom: 10 }}>
                    <MapLegend />
                  </div>
                  {steps.map((step, i) => (
                    <AssignStepCard
                      key={i} step={step} index={i}
                      saLat={sa?.lat ? parseFloat(sa.lat) : null}
                      saLon={sa?.lon ? parseFloat(sa.lon) : null}
                    />
                  ))}
                </section>
              )}

              {/* SA detail footer */}
              {sa && (
                <div style={{
                  background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8,
                  padding: '12px 16px', fontSize: 11, color: '#64748b',
                  display: 'flex', flexWrap: 'wrap', gap: '6px 20px',
                }}>
                  <span><span style={{ color: '#475569' }}>Address:</span> {sa.address || '—'}</span>
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
