/**
 * OptimizerSADecisionPage.jsx
 *
 * Comprehensive per-SA decision page styled like SAReportModal.
 * Renders WHY the winner won and SPECIFICALLY why each non-winner did not.
 *
 * Used by OptimizerDecisionBrowser when user picks an SA.
 */

import { useState, useEffect } from 'react'
import {
  Loader2, Truck, MapPin, Clock, Award, AlertOctagon, Users,
  CheckCircle, XCircle, Activity, Sparkles,
} from 'lucide-react'
import { optimizerGetSA } from '../api'

// ── helpers ─────────────────────────────────────────────────────────────────
function parseUtc(iso) {
  if (!iso) return null
  return new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + 'Z')
}

function fmtTime(iso) {
  const d = parseUtc(iso)
  if (!d) return '—'
  return d.toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

function fmtMin(m) {
  if (m == null) return '—'
  if (m < 60) return `${Math.round(m)}m`
  return `${Math.floor(m / 60)}h ${Math.round(m % 60)}m`
}

function fmtMi(d) {
  if (d == null) return '—'
  return `${d.toFixed(1)} mi`
}

function fmtDelta(value, baseline, unit) {
  if (value == null || baseline == null) return ''
  const diff = value - baseline
  if (Math.abs(diff) < 0.05) return `(same as winner)`
  const sign = diff > 0 ? '+' : ''
  return `(${sign}${diff.toFixed(1)} ${unit} vs winner)`
}

const ACTION_COLOR = {
  Scheduled:   { bg: 'rgba(34,197,94,0.15)',   color: '#4ade80', border: '#22c55e' },
  Unscheduled: { bg: 'rgba(245,158,11,0.15)',  color: '#fbbf24', border: '#f59e0b' },
  Unchanged:   { bg: 'rgba(100,116,139,0.15)', color: '#94a3b8', border: '#64748b' },
}

// ── Section primitives (match SAReportModal style) ──────────────────────────
function SectionLabel({ children }) {
  return (
    <div style={{
      fontSize: 11, fontWeight: 700, color: '#64748b',
      textTransform: 'uppercase', letterSpacing: 1, marginBottom: 10,
    }}>
      {children}
    </div>
  )
}

function Card({ children, accent = null, style = {} }) {
  return (
    <div style={{
      background: '#0f172a',
      border: '1px solid #1e293b',
      borderLeft: accent ? `3px solid ${accent}` : '1px solid #1e293b',
      borderRadius: 8,
      padding: '14px 16px',
      ...style,
    }}>
      {children}
    </div>
  )
}

function Stat({ label, value, valueColor = '#e2e8f0', sub = null }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5 }}>
        {label}
      </div>
      <div style={{ fontSize: 18, fontWeight: 700, color: valueColor, marginTop: 2 }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 10, color: '#475569', marginTop: 1 }}>{sub}</div>}
    </div>
  )
}

// ── Narrative builder — explains the run in plain English ───────────────────
function buildNarrative(decision) {
  const lines = []
  const winner = decision.verdicts?.find(v => v.status === 'winner')
  const eligible = decision.verdicts?.filter(v => v.status === 'eligible') || []
  const excluded = decision.verdicts?.filter(v => v.status === 'excluded') || []

  if (decision.action === 'Unchanged') {
    lines.push(
      `Optimizer left this SA unchanged — the previous assignment ` +
      (decision.winner_driver_name ? `(${decision.winner_driver_name}) ` : '') +
      `was kept and not re-deliberated this run.`,
    )
  } else if (decision.action === 'Unscheduled') {
    lines.push(
      `Optimizer could NOT schedule this SA. ` +
      (decision.unscheduled_reason ? `Reason: ${decision.unscheduled_reason}.` : ''),
    )
    if (excluded.length > 0) {
      lines.push(`Every considered driver was excluded — ${excluded.length} drivers ruled out.`)
    }
  } else if (winner) {
    lines.push(
      `Won by ${winner.driver_name} ` +
      `(travel ${fmtMin(winner.travel_time_min)}, ${fmtMi(winner.travel_dist_mi)}).`,
    )
  }

  if (eligible.length > 0 && winner) {
    const closest = eligible
      .filter(e => e.travel_dist_mi != null)
      .sort((a, b) => a.travel_dist_mi - b.travel_dist_mi)[0]
    if (closest) {
      const delta = closest.travel_dist_mi - (winner.travel_dist_mi || 0)
      lines.push(
        `${eligible.length} other driver${eligible.length > 1 ? 's were' : ' was'} eligible but lost on travel — ` +
        `closest runner-up (${closest.driver_name}) was ${delta.toFixed(1)} mi farther.`,
      )
    } else {
      lines.push(`${eligible.length} other driver${eligible.length > 1 ? 's were' : ' was'} eligible but lost.`)
    }
  }

  if (excluded.length > 0) {
    // Group by reason and surface top 2
    const byReason = {}
    for (const e of excluded) {
      const r = e.exclusion_reason || 'unknown'
      byReason[r] = (byReason[r] || 0) + 1
    }
    const top = Object.entries(byReason).sort((a, b) => b[1] - a[1]).slice(0, 2)
    const phrase = top.map(([r, c]) => `${c} ${r.toLowerCase()}`).join(', ')
    lines.push(`${excluded.length} excluded — ${phrase}.`)
  }

  return lines
}

// ── Driver row component (winner / eligible / excluded) ─────────────────────
function DriverRow({ driver, winner = null, kind = 'eligible' }) {
  const accent = kind === 'winner' ? '#22c55e'
               : kind === 'eligible' ? '#6366f1'
               : '#475569'
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '1fr auto auto auto',
      gap: 10, alignItems: 'center',
      padding: '8px 12px',
      borderBottom: '1px solid #1e293b',
      fontSize: 12,
    }}>
      <div style={{ minWidth: 0 }}>
        <div style={{
          color: kind === 'excluded' ? '#94a3b8' : '#e2e8f0',
          fontWeight: kind === 'winner' ? 700 : 500,
          display: 'flex', alignItems: 'center', gap: 6,
        }}>
          {kind === 'winner' && <Award size={12} color={accent} />}
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {driver.driver_name}
          </span>
        </div>
        {driver.driver_territory && (
          <div style={{ fontSize: 10, color: '#64748b', marginTop: 1 }}>
            home: {driver.driver_territory}
            {driver.driver_skills && (
              <span style={{ marginLeft: 8 }} title={driver.driver_skills}>
                · skills: {driver.driver_skills.length > 40
                            ? driver.driver_skills.slice(0, 40) + '…'
                            : driver.driver_skills}
              </span>
            )}
          </div>
        )}
      </div>
      <div style={{ textAlign: 'right', fontFamily: 'monospace', color: '#cbd5e1', minWidth: 60 }}>
        {fmtMin(driver.travel_time_min)}
      </div>
      <div style={{ textAlign: 'right', fontFamily: 'monospace', color: '#cbd5e1', minWidth: 70 }}>
        {fmtMi(driver.travel_dist_mi)}
      </div>
      <div style={{ textAlign: 'right', minWidth: 140, fontSize: 10, color: '#94a3b8' }}>
        {kind === 'eligible' && winner && fmtDelta(driver.travel_dist_mi, winner.travel_dist_mi, 'mi')}
        {kind === 'excluded' && driver.exclusion_reason && (
          <span style={{ color: '#fb923c', fontStyle: 'italic' }}>{driver.exclusion_reason}</span>
        )}
      </div>
    </div>
  )
}

// ── Main Page ───────────────────────────────────────────────────────────────
export default function OptimizerSADecisionPage({ runId, saNumber, runMeta }) {
  const [decision, setDecision] = useState(null)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState(null)

  useEffect(() => {
    if (!runId || !saNumber) { setDecision(null); return }
    setLoading(true)
    setError(null)
    // Server-side filter to this exact run — avoids paging through dozens of
    // recent runs that may have touched this SA.
    optimizerGetSA(saNumber, 5, runId)
      .then(rows => {
        const match = rows[0]
        if (!match) {
          setDecision(null)
          setError(`No decision found for ${saNumber} in this run.`)
        } else {
          setDecision(match)
        }
      })
      .catch(e => setError(e.response?.data?.detail || e.message || 'Failed to load decision'))
      .finally(() => setLoading(false))
  }, [runId, saNumber])

  // ── Empty state ──
  if (!saNumber) {
    return (
      <div style={{
        flex: 1, display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        color: '#475569', gap: 12, padding: 24,
      }}>
        <Truck size={36} style={{ opacity: 0.4 }} />
        <div style={{ fontSize: 13, color: '#64748b' }}>Pick an SA from the left</div>
        <div style={{ fontSize: 11, color: '#475569', textAlign: 'center', maxWidth: 280 }}>
          Click any SA to see the full decision summary — winner + every driver that was considered + why each non-winner was passed over.
        </div>
      </div>
    )
  }

  // ── Loading ──
  if (loading) {
    return (
      <div style={{
        flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: '#64748b', gap: 10,
      }}>
        <Loader2 size={16} className="animate-spin" />
        Loading decision for {saNumber}…
      </div>
    )
  }

  // ── Error ──
  if (error) {
    return (
      <div style={{
        flex: 1, display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        color: '#ef4444', padding: 24, textAlign: 'center', gap: 8,
      }}>
        <AlertOctagon size={28} />
        <div style={{ fontSize: 12 }}>{error}</div>
      </div>
    )
  }

  if (!decision) return null

  const verdicts = decision.verdicts || []
  let winner = verdicts.find(v => v.status === 'winner')
  // Unchanged SAs don't get verdict rows (the optimizer didn't re-deliberate),
  // but the previous assignment IS on the decision row — surface it as the
  // "kept assignment" so the right pane stays consistent with the narrative.
  const isKeptAssignment = !winner && decision.action === 'Unchanged' && decision.winner_driver_name
  if (isKeptAssignment) {
    winner = {
      driver_id:        decision.winner_driver_id,
      driver_name:      decision.winner_driver_name,
      travel_time_min:  decision.winner_travel_time_min,
      travel_dist_mi:   decision.winner_travel_dist_mi,
      driver_skills:    null,
      driver_territory: null,
      status:           'kept',
    }
  }
  const eligible = verdicts.filter(v => v.status === 'eligible')
                            .sort((a, b) => (a.travel_dist_mi ?? 999) - (b.travel_dist_mi ?? 999))
  const excludedByReason = {}
  for (const v of verdicts.filter(v => v.status === 'excluded')) {
    const r = v.exclusion_reason || 'unknown'
    if (!excludedByReason[r]) excludedByReason[r] = []
    excludedByReason[r].push(v)
  }
  const excludedReasonsSorted = Object.entries(excludedByReason)
    .sort((a, b) => b[1].length - a[1].length)

  const narrative = buildNarrative(decision)
  const actionCfg = ACTION_COLOR[decision.action] || ACTION_COLOR.Unchanged

  return (
    <div style={{
      flex: 1, overflowY: 'auto', background: '#0b1120',
      padding: '20px 24px',
    }}>
      {/* ── Header ────────────────────────────────────────────────── */}
      <div style={{ marginBottom: 18 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
          <Truck size={18} color="#6366f1" />
          <div style={{ fontSize: 16, fontWeight: 700, color: '#e2e8f0' }}>
            SA Decision Report — {decision.sa_number}
          </div>
          <span style={{
            marginLeft: 6, padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 700,
            background: actionCfg.bg, color: actionCfg.color,
            border: `1px solid ${actionCfg.border}40`,
          }}>
            {decision.action || '—'}
          </span>
        </div>
        <div style={{ fontSize: 11, color: '#64748b', marginLeft: 28 }}>
          {decision.sa_work_type || '—'}
          {' · '}
          {decision.territory_name || runMeta?.territory_name || '—'}
          {' · run '}
          {fmtTime(decision.run_at)}
          {decision.policy_name && (
            <>
              {' · policy '}
              <span style={{ color: '#94a3b8' }}>{decision.policy_name}</span>
            </>
          )}
        </div>
      </div>

      {/* ── Narrative summary ─────────────────────────────────────── */}
      {narrative.length > 0 && (
        <section style={{ marginBottom: 22 }}>
          <SectionLabel>Summary</SectionLabel>
          <Card>
            {narrative.map((line, i) => (
              <div key={i} style={{ fontSize: 12, color: '#cbd5e1', lineHeight: 1.6, marginBottom: 4 }}>
                {line}
              </div>
            ))}
          </Card>
        </section>
      )}

      {/* ── SA Profile ────────────────────────────────────────────── */}
      <section style={{ marginBottom: 22 }}>
        <SectionLabel>SA Profile</SectionLabel>
        <Card>
          <div style={{
            display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)',
            gap: 14, marginBottom: 12,
          }}>
            <Stat label="Priority"
                  value={decision.priority != null ? decision.priority : '—'} />
            <Stat label="Duration"
                  value={fmtMin(decision.duration_min)} />
            <Stat label="SA Status"
                  value={decision.sa_status || '—'}
                  valueColor="#cbd5e1" />
            <Stat label="Location"
                  value={decision.sa_lat != null
                          ? `${decision.sa_lat.toFixed(3)}, ${decision.sa_lon.toFixed(3)}`
                          : '—'}
                  valueColor="#94a3b8" />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14 }}>
            <Stat label="Earliest Start" value={fmtTime(decision.earliest_start)} valueColor="#94a3b8" />
            <Stat label="Scheduled" value={fmtTime(decision.sched_start)}
                  valueColor={decision.sched_start ? '#4ade80' : '#94a3b8'} />
            <Stat label="Due By" value={fmtTime(decision.due_date)} valueColor="#94a3b8" />
          </div>
          {decision.required_skills && (
            <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid #1e293b' }}>
              <div style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', marginBottom: 4 }}>
                Required Skills
              </div>
              <div style={{ fontSize: 11, color: '#cbd5e1', fontFamily: 'monospace' }}>
                {decision.required_skills}
              </div>
            </div>
          )}
        </Card>
      </section>

      {/* ── Picked Driver ─────────────────────────────────────────── */}
      <section style={{ marginBottom: 22 }}>
        <SectionLabel>{isKeptAssignment ? 'Kept Assignment' : 'Picked Driver'}</SectionLabel>
        {winner ? (
          <Card accent={isKeptAssignment ? '#94a3b8' : '#22c55e'}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
              <Award size={16} color={isKeptAssignment ? '#94a3b8' : '#4ade80'} />
              <div style={{ fontSize: 14, fontWeight: 700, color: '#e2e8f0' }}>
                {winner.driver_name}
              </div>
              <span style={{
                marginLeft: 'auto', padding: '2px 8px', borderRadius: 4,
                fontSize: 10, fontWeight: 700,
                background: isKeptAssignment ? 'rgba(148,163,184,0.15)' : 'rgba(34,197,94,0.15)',
                color: isKeptAssignment ? '#cbd5e1' : '#4ade80',
              }}>
                {isKeptAssignment ? 'KEPT FROM PRIOR RUN' : 'WINNER'}
              </span>
            </div>
            {isKeptAssignment && (
              <div style={{
                fontSize: 11, color: '#94a3b8', fontStyle: 'italic', marginBottom: 10,
                paddingBottom: 10, borderBottom: '1px solid #1e293b',
              }}>
                The optimizer did not re-deliberate this SA — driver verdicts are not recorded for unchanged SAs.
                Travel and skills below reflect the prior run's decision (where available).
              </div>
            )}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14 }}>
              <Stat label="Travel Time" value={fmtMin(winner.travel_time_min)}
                    valueColor={isKeptAssignment ? '#cbd5e1' : '#4ade80'} />
              <Stat label="Travel Dist" value={fmtMi(winner.travel_dist_mi)}
                    valueColor={isKeptAssignment ? '#cbd5e1' : '#4ade80'} />
              <Stat label="Home Garage" value={winner.driver_territory || '—'} valueColor="#cbd5e1" />
              <Stat label="Skills" value={winner.driver_skills ? '✓ matches' : '—'} valueColor="#94a3b8"
                    sub={winner.driver_skills
                          ? (winner.driver_skills.length > 30
                              ? winner.driver_skills.slice(0, 30) + '…'
                              : winner.driver_skills)
                          : null} />
            </div>
          </Card>
        ) : (
          <Card accent="#f59e0b">
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <AlertOctagon size={16} color="#fbbf24" />
              <div style={{ fontSize: 13, color: '#fbbf24', fontWeight: 600 }}>
                No driver was assigned this run
              </div>
            </div>
            {decision.unscheduled_reason && (
              <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 6, marginLeft: 26 }}>
                Reason: {decision.unscheduled_reason}
              </div>
            )}
          </Card>
        )}
      </section>

      {/* ── Lost on Travel ────────────────────────────────────────── */}
      {eligible.length > 0 && (
        <section style={{ marginBottom: 22 }}>
          <SectionLabel>
            Other Eligible Drivers — Lost on Travel ({eligible.length})
          </SectionLabel>
          <Card style={{ padding: 0, overflow: 'hidden' }}>
            <div style={{
              display: 'grid', gridTemplateColumns: '1fr auto auto auto',
              gap: 10, padding: '6px 12px',
              fontSize: 9, fontWeight: 700, color: '#475569',
              textTransform: 'uppercase', letterSpacing: 0.5,
              borderBottom: '1px solid #1e293b', background: '#0a1424',
            }}>
              <div>Driver</div>
              <div style={{ textAlign: 'right', minWidth: 60 }}>Time</div>
              <div style={{ textAlign: 'right', minWidth: 70 }}>Dist</div>
              <div style={{ textAlign: 'right', minWidth: 140 }}>Margin</div>
            </div>
            {eligible.map(d => (
              <DriverRow key={d.driver_id} driver={d} winner={winner} kind="eligible" />
            ))}
          </Card>
        </section>
      )}

      {/* ── Excluded (grouped by reason) ──────────────────────────── */}
      {excludedReasonsSorted.length > 0 && (
        <section style={{ marginBottom: 12 }}>
          <SectionLabel>
            Drivers Excluded — Did Not Reach Scoring
          </SectionLabel>
          {excludedReasonsSorted.map(([reason, drivers]) => (
            <div key={reason} style={{ marginBottom: 12 }}>
              <div style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '6px 10px',
                background: 'rgba(239,68,68,0.08)',
                border: '1px solid rgba(239,68,68,0.2)',
                borderRadius: 6,
                marginBottom: 6,
              }}>
                <XCircle size={11} color="#fb923c" />
                <span style={{ fontSize: 11, fontWeight: 600, color: '#fbbf24' }}>
                  {reason}
                </span>
                <span style={{ fontSize: 10, color: '#94a3b8', marginLeft: 'auto' }}>
                  {drivers.length} driver{drivers.length > 1 ? 's' : ''}
                </span>
              </div>
              <Card style={{ padding: 0, overflow: 'hidden' }}>
                {drivers.map(d => (
                  <DriverRow key={d.driver_id} driver={d} kind="excluded" />
                ))}
              </Card>
            </div>
          ))}
        </section>
      )}
    </div>
  )
}
