import { useMemo, useState } from 'react'
import { ReactFlow, Controls, Background, Handle, Position } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Trophy, XCircle, AlertCircle, Maximize2, Minimize2, MapPin, Clock } from 'lucide-react'

// ── Rule config ───────────────────────────────────────────────────────────────

const REASON = {
  territory: { label: 'Wrong Territory', color: '#fb923c', dim: 'rgba(251,146,60,0.12)', border: 'rgba(251,146,60,0.35)' },
  skill:     { label: 'Missing Skill',   color: '#fbbf24', dim: 'rgba(251,191,36,0.12)', border: 'rgba(251,191,36,0.35)' },
  absent:    { label: 'Absent / Leave',  color: '#c084fc', dim: 'rgba(192,132,252,0.12)', border: 'rgba(192,132,252,0.35)' },
  capacity:  { label: 'At Capacity',     color: '#f87171', dim: 'rgba(248,113,113,0.12)', border: 'rgba(248,113,113,0.35)' },
}

const RULE_ORDER = ['territory', 'skill', 'absent', 'capacity']
const RULE_LABEL = { territory: 'Territory Check', skill: 'Skill Match', absent: 'Availability', capacity: 'Capacity' }
const RULE_DESC  = {
  territory: "Driver's territory must include this SA",
  skill:     'Driver must have required work-type skills',
  absent:    'Driver must not have approved absence overlap',
  capacity:  "Driver's shift must have open time slots",
}

function fmtMin(m) {
  if (m == null) return null
  return m < 60 ? `${Math.round(m)}m` : `${(m / 60).toFixed(1)}h`
}

// ── Custom node components ────────────────────────────────────────────────────

function NodeSA({ data }) {
  return (
    <div style={{
      padding: '10px 18px', borderRadius: 12, textAlign: 'center',
      background: 'rgba(99,102,241,0.12)', border: '1.5px solid rgba(99,102,241,0.4)',
      minWidth: 200,
    }}>
      <div style={{ fontFamily: 'monospace', fontWeight: 700, color: '#e0e7ff', fontSize: 15 }}>{data.sa_number}</div>
      {data.sa_work_type && (
        <div style={{ color: '#a5b4fc', fontSize: 11, marginTop: 3 }}>{data.sa_work_type}</div>
      )}
      {data.territory_name && (
        <div style={{ color: '#6366f1', fontSize: 10, marginTop: 2, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 3 }}>
          <MapPin size={9} /> {data.territory_name}
        </div>
      )}
      {data.run_at && (
        <div style={{ color: '#3f3f70', fontSize: 10, marginTop: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 3 }}>
          <Clock size={9} /> {new Date(data.run_at).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} style={{ background: '#6366f1', width: 8, height: 8 }} />
    </div>
  )
}

function NodeRule({ data }) {
  const open = !!data.expanded   // controlled by parent via onNodeClick
  const allPass = data.passed === data.total
  const pct = data.total > 0 ? Math.round((data.passed / data.total) * 100) : 0
  const barColor = allPass ? '#34d399' : pct >= 50 ? '#60a5fa' : '#f87171'
  const passDrivers = data.passDrivers || []
  const failDrivers = data.failDrivers || []
  return (
    <div
      style={{
        padding: '8px 14px 10px', borderRadius: 10,
        background: 'rgba(15,23,42,0.95)',
        border: open ? '1px solid #475569' : '1px solid #1e293b',
        minWidth: 190, boxShadow: open ? '0 4px 20px rgba(0,0,0,0.6)' : '0 2px 12px rgba(0,0,0,0.4)',
        cursor: 'pointer', transition: 'border-color 0.15s, box-shadow 0.15s',
      }}
      title="Click to see who passed and who failed"
    >
      <Handle type="target" position={Position.Top} style={{ background: '#334155', width: 8, height: 8 }} />

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
        <div style={{ fontSize: 10, color: '#64748b', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          {data.label}
        </div>
        <span style={{
          fontSize: 9, color: open ? '#94a3b8' : '#64748b',
          background: 'rgba(51,65,85,0.5)', borderRadius: 4,
          padding: '1px 6px', fontFamily: 'monospace',
        }}>
          {open ? '▼ click to close' : '▶ click for drivers'}
        </span>
      </div>
      <div style={{ fontSize: 10, color: '#475569', marginBottom: 6, lineHeight: 1.4 }}>{data.desc}</div>

      {/* Pass/fail bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
        <div style={{ flex: 1, height: 4, borderRadius: 4, background: '#0f172a', overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${pct}%`, background: barColor, borderRadius: 4, transition: 'width 0.4s' }} />
        </div>
        <span style={{ fontFamily: 'monospace', fontSize: 11, color: barColor, fontWeight: 600 }}>{data.passed}/{data.total}</span>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
        <div style={{ fontSize: 10, color: '#22c55e' }}>✓ {data.passed} pass</div>
        {data.failed > 0 && <div style={{ fontSize: 10, color: '#ef4444' }}>✗ {data.failed} fail</div>}
      </div>

      {/* Expandable detail — drivers who passed and who failed */}
      {open && (
        <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid rgba(71,85,105,0.3)',
                       display: 'flex', flexDirection: 'column', gap: 6 }}>
          {passDrivers.length > 0 && (
            <div>
              <div style={{ fontSize: 9, color: '#22c55e', fontWeight: 700, textTransform: 'uppercase',
                            letterSpacing: '0.06em', marginBottom: 3 }}>
                ✓ Pass ({passDrivers.length})
              </div>
              {passDrivers.map((d, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between',
                                       fontSize: 10, color: '#cbd5e1', padding: '1px 0' }}>
                  <span>{d.driver_name}</span>
                  <span style={{ color: '#475569', fontFamily: 'monospace', fontSize: 9 }}>
                    {d.driver_territory || ''}
                  </span>
                </div>
              ))}
            </div>
          )}
          {failDrivers.length > 0 && (
            <div>
              <div style={{ fontSize: 9, color: '#ef4444', fontWeight: 700, textTransform: 'uppercase',
                            letterSpacing: '0.06em', marginBottom: 3 }}>
                ✗ Fail ({failDrivers.length})
              </div>
              {failDrivers.map((d, i) => (
                <div key={i} style={{ display: 'flex', flexDirection: 'column', padding: '1px 0' }}>
                  <span style={{ fontSize: 10, color: '#fca5a5' }}>{d.driver_name}</span>
                  <span style={{ fontSize: 9, color: '#7f1d1d', fontFamily: 'monospace', paddingLeft: 8 }}>
                    {data.rule === 'territory' && `home: ${d.driver_territory || '?'}`}
                    {data.rule === 'skill' && `has: ${(d.driver_skills || '').split(',').slice(0, 3).join(', ')}…`}
                    {data.rule === 'absent' && 'on approved leave'}
                    {data.rule === 'capacity' && 'shift full'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <Handle type="source" id="pass" position={Position.Bottom}
        style={{ background: '#22c55e', left: '35%', width: 8, height: 8 }} />
      {data.failed > 0 && (
        <Handle type="source" id="fail" position={Position.Right}
          style={{ background: '#ef4444', width: 8, height: 8 }} />
      )}
    </div>
  )
}

function NodeExcluded({ data }) {
  const cfg = REASON[data.reason] || { label: data.reason, color: '#94a3b8', dim: 'rgba(148,163,184,0.1)', border: 'rgba(148,163,184,0.25)' }
  return (
    <div style={{
      padding: '8px 12px', borderRadius: 10,
      background: cfg.dim, border: `1px solid ${cfg.border}`,
      minWidth: 180, maxWidth: 280,
    }}>
      <Handle type="target" position={Position.Left} style={{ background: cfg.color, width: 8, height: 8 }} />
      <div style={{ color: cfg.color, fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 5 }}>
        {cfg.label}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {data.drivers.map((d, i) => (
          <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 1, paddingBottom: 3,
                                 borderBottom: i < data.drivers.length - 1 ? '1px solid rgba(148,163,184,0.1)' : 'none' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 5, color: '#cbd5e1', fontSize: 11, fontWeight: 500 }}>
              <XCircle size={10} color={cfg.color} style={{ flexShrink: 0 }} />
              {d.driver_name}
            </div>
            <div style={{ display: 'flex', gap: 8, paddingLeft: 15, color: '#64748b', fontSize: 9, fontFamily: 'monospace' }}>
              {d.driver_territory && <span>📍{d.driver_territory}</span>}
              {d.travel_dist_mi != null && <span>~{d.travel_dist_mi.toFixed(1)}mi</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function NodeWinner({ data }) {
  return (
    <div style={{
      padding: '10px 16px', borderRadius: 12,
      background: 'rgba(16,185,129,0.08)', border: '1.5px solid rgba(16,185,129,0.35)',
      minWidth: 200,
    }}>
      <Handle type="target" position={Position.Top} style={{ background: '#10b981', width: 8, height: 8 }} />

      {/* Winner — may be null if SA was unscheduled despite having eligible drivers */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8, justifyContent: 'center' }}>
        <Trophy size={13} color="#34d399" />
        <span style={{ color: '#34d399', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          {data.winner ? 'Winner — Closest Driver' : 'Eligible Pool — No Winner Picked'}
        </span>
      </div>
      <div style={{ textAlign: 'center', marginBottom: 6 }}>
        {data.winner ? (
          <>
            <div style={{ color: '#ecfdf5', fontSize: 14, fontWeight: 700 }}>{data.winner.driver_name}</div>
            {data.winner.travel_time_min != null && (
              <div style={{ color: '#6ee7b7', fontSize: 12, fontFamily: 'monospace', marginTop: 2 }}>
                {fmtMin(data.winner.travel_time_min)} travel time
                {data.winner.travel_dist_mi != null && ` · ${data.winner.travel_dist_mi.toFixed(1)}mi`}
              </div>
            )}
          </>
        ) : (
          <div style={{ color: '#6ee7b7', fontSize: 11, fontStyle: 'italic' }}>
            Optimizer rejected all candidates (rule violation)
          </div>
        )}
      </div>

      {/* Eligible — runners-up sorted by travel time */}
      {data.eligible?.length > 0 && (
        <div style={{ borderTop: '1px solid rgba(16,185,129,0.15)', paddingTop: 7, marginTop: 4 }}>
          <div style={{ color: '#475569', fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4, textAlign: 'center' }}>
            Qualified but farther away ({data.eligible.length})
          </div>
          {[...data.eligible]
            .sort((a, b) => (a.travel_time_min ?? 9999) - (b.travel_time_min ?? 9999))
            .map((d, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                     gap: 8, color: '#93c5fd', fontSize: 11, padding: '2px 0' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                  <span style={{ color: '#334155', fontFamily: 'monospace', fontSize: 10 }}>{i + 2}.</span>
                  {d.driver_name}
                </div>
                <span style={{ color: '#475569', fontFamily: 'monospace', fontSize: 10 }}>
                  {d.travel_time_min != null ? `${fmtMin(d.travel_time_min)}` : '—'}
                  {d.travel_dist_mi != null && ` · ${d.travel_dist_mi.toFixed(1)}mi`}
                </span>
              </div>
            ))}
        </div>
      )}
    </div>
  )
}

function NodeUnscheduled({ data }) {
  return (
    <div style={{
      padding: '10px 14px', borderRadius: 12,
      background: 'rgba(245,158,11,0.08)', border: '1.5px solid rgba(245,158,11,0.3)',
      minWidth: 200, textAlign: 'center',
    }}>
      <Handle type="target" position={Position.Top} style={{ background: '#f59e0b', width: 8, height: 8 }} />
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5, marginBottom: 5 }}>
        <AlertCircle size={12} color="#fbbf24" />
        <span style={{ color: '#fbbf24', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Unscheduled</span>
      </div>
      {data.reason && (
        <div style={{ color: '#92400e', fontSize: 10, lineHeight: 1.4, maxWidth: 200 }}>{data.reason}</div>
      )}
    </div>
  )
}

const NODE_TYPES = {
  saNode:          NodeSA,
  ruleNode:        NodeRule,
  excludedNode:    NodeExcluded,
  winnerNode:      NodeWinner,
  unscheduledNode: NodeUnscheduled,
}

// ── Graph builder ─────────────────────────────────────────────────────────────

function buildGraph(data) {
  const {
    sa_number, sa_work_type, territory_name, run_at,
    winner, eligible = [], excluded = {}, action, unscheduled_reason,
    all_verdicts = [],
  } = data

  const nodes = []
  const edges = []
  let uid = 0
  const id = () => `n${uid++}`

  const CX = 0          // center column x (left-edge of center nodes, width ~200)
  const EX = 280        // exclusion column x
  const RULE_H = 135    // vertical spacing between rule nodes

  // SA root
  const saId = id()
  nodes.push({ id: saId, type: 'saNode', position: { x: CX, y: 0 }, data: { sa_number, sa_work_type, territory_name, run_at } })

  let prevId = saId
  let y = 100
  // Pool of drivers still in contention at this gate. Starts as all considered.
  let remainingDrivers = [...all_verdicts]

  for (const rule of RULE_ORDER) {
    const excl   = excluded[rule] || []
    const failed = excl.length
    const remaining = remainingDrivers.length
    const passed = remaining - failed

    if (remaining === 0) break

    // failDrivers = drivers excluded AT THIS gate (full verdict objects)
    const failedIds = new Set(excl.map(d => d.driver_id))
    const failDrivers = remainingDrivers.filter(d => failedIds.has(d.driver_id))
    // passDrivers = those who survive to next gate
    const passDrivers = remainingDrivers.filter(d => !failedIds.has(d.driver_id))

    const ruleId = id()
    nodes.push({
      id: ruleId, type: 'ruleNode',
      position: { x: CX, y },
      data: {
        label: RULE_LABEL[rule], desc: RULE_DESC[rule], rule,
        passed, total: remaining, failed,
        passDrivers, failDrivers,
      },
    })
    edges.push({
      id: `e-${prevId}-${ruleId}`,
      source: prevId, target: ruleId,
      sourceHandle: prevId === saId ? undefined : 'pass',
      type: 'smoothstep',
      style: { stroke: '#334155', strokeWidth: 1.5 },
    })

    if (failed > 0) {
      const exclId = id()
      nodes.push({
        id: exclId, type: 'excludedNode',
        position: { x: EX, y: y + 10 },
        data: { reason: rule, drivers: excl },
      })
      edges.push({
        id: `e-${ruleId}-${exclId}`,
        source: ruleId, target: exclId,
        sourceHandle: 'fail',
        type: 'smoothstep',
        label: 'excluded',
        style: { stroke: '#ef444450', strokeDasharray: '5 3', strokeWidth: 1.5 },
        labelStyle: { fill: '#ef4444', fontSize: 9, fontWeight: 600 },
        labelBgStyle: { fill: 'transparent' },
      })
    }

    prevId = ruleId
    remainingDrivers = passDrivers
    y += RULE_H
  }

  // Result node
  if (winner || eligible.length > 0) {
    const wId = id()
    nodes.push({
      id: wId, type: 'winnerNode',
      position: { x: CX, y },
      data: { winner, eligible },
    })
    edges.push({
      id: `e-${prevId}-${wId}`,
      source: prevId, target: wId,
      sourceHandle: 'pass',
      type: 'smoothstep',
      label: 'ranked by travel time',
      style: { stroke: '#10b981', strokeWidth: 1.5 },
      labelStyle: { fill: '#10b981', fontSize: 9, fontWeight: 600 },
      labelBgStyle: { fill: 'rgba(2,6,23,0.85)', padding: [2, 4] },
    })
  } else {
    const uId = id()
    nodes.push({
      id: uId, type: 'unscheduledNode',
      position: { x: CX, y },
      data: { reason: unscheduled_reason },
    })
    edges.push({
      id: `e-${prevId}-${uId}`,
      source: prevId, target: uId,
      sourceHandle: 'pass',
      type: 'smoothstep',
      style: { stroke: '#f59e0b', strokeWidth: 1.5 },
    })
  }

  return { nodes, edges, totalHeight: y + 180 }
}

// ── Driver detail grid (every considered driver with full data) ──────────────

function DriverDetailGrid({ verdicts }) {
  if (!verdicts?.length) return null
  const sorted = [...verdicts].sort((a, b) => {
    const order = { winner: 0, eligible: 1, excluded: 2 }
    if (order[a.status] !== order[b.status]) return order[a.status] - order[b.status]
    return (a.travel_time_min ?? 9999) - (b.travel_time_min ?? 9999)
  })

  const STATUS_COLORS = {
    winner:   { bg: 'rgba(16,185,129,0.10)', text: '#34d399', label: 'WINNER' },
    eligible: { bg: 'rgba(96,165,250,0.08)', text: '#93c5fd', label: 'ELIGIBLE' },
    excluded: { bg: 'rgba(248,113,113,0.06)', text: '#f87171', label: 'EXCLUDED' },
  }

  return (
    <div style={{
      marginTop: 12, borderRadius: 10, overflow: 'hidden',
      border: '1px solid #1e293b', background: '#0a0f1e',
    }}>
      <div style={{
        padding: '8px 14px', borderBottom: '1px solid #1e293b',
        background: 'rgba(15,23,42,0.6)',
        fontSize: 10, color: '#94a3b8', fontWeight: 700,
        textTransform: 'uppercase', letterSpacing: '0.06em',
      }}>
        All Drivers Considered ({verdicts.length})
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
          <thead>
            <tr style={{ background: 'rgba(15,23,42,0.4)', color: '#64748b', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              <th style={{ textAlign: 'left',  padding: '6px 12px', fontWeight: 600 }}>Driver</th>
              <th style={{ textAlign: 'left',  padding: '6px 12px', fontWeight: 600 }}>Verdict</th>
              <th style={{ textAlign: 'left',  padding: '6px 12px', fontWeight: 600 }}>Reason</th>
              <th style={{ textAlign: 'right', padding: '6px 12px', fontWeight: 600 }}>Travel Time</th>
              <th style={{ textAlign: 'right', padding: '6px 12px', fontWeight: 600 }}>Distance</th>
              <th style={{ textAlign: 'left',  padding: '6px 12px', fontWeight: 600 }}>Territory</th>
              <th style={{ textAlign: 'left',  padding: '6px 12px', fontWeight: 600 }}>Skills</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((v, i) => {
              const sc = STATUS_COLORS[v.status] || STATUS_COLORS.eligible
              const reasonCfg = v.exclusion_reason ? REASON[v.exclusion_reason] : null
              return (
                <tr key={i} style={{
                  background: sc.bg,
                  borderTop: '1px solid rgba(30,41,59,0.5)',
                }}>
                  <td style={{ padding: '6px 12px', color: '#e2e8f0', fontWeight: 600 }}>
                    {v.status === 'winner' && <Trophy size={10} color="#34d399" style={{ marginRight: 5, display: 'inline', verticalAlign: 'middle' }} />}
                    {v.driver_name}
                  </td>
                  <td style={{ padding: '6px 12px' }}>
                    <span style={{ color: sc.text, fontSize: 9, fontWeight: 700, fontFamily: 'monospace' }}>
                      {sc.label}
                    </span>
                  </td>
                  <td style={{ padding: '6px 12px', color: reasonCfg?.color || '#64748b', fontSize: 10 }}>
                    {reasonCfg?.label || (v.status === 'winner' ? 'Closest qualified driver' : '—')}
                  </td>
                  <td style={{ padding: '6px 12px', textAlign: 'right', fontFamily: 'monospace', color: '#cbd5e1' }}>
                    {v.travel_time_min != null ? fmtMin(v.travel_time_min) : '—'}
                  </td>
                  <td style={{ padding: '6px 12px', textAlign: 'right', fontFamily: 'monospace', color: '#cbd5e1' }}>
                    {v.travel_dist_mi != null ? `${v.travel_dist_mi.toFixed(1)}mi` : '—'}
                  </td>
                  <td style={{ padding: '6px 12px', color: '#94a3b8', fontFamily: 'monospace', fontSize: 10 }}>
                    {v.driver_territory || '—'}
                  </td>
                  <td style={{ padding: '6px 12px', color: '#64748b', fontSize: 10, maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={v.driver_skills}>
                    {v.driver_skills || '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Main export ───────────────────────────────────────────────────────────────

export default function OptDecisionTree({ data }) {
  const [expanded, setExpanded] = useState(false)
  const [expandedGateId, setExpandedGateId] = useState(null)

  if (!data) return null

  const built = useMemo(() => buildGraph(data), [data])

  // Inject the expanded flag into the matching gate node's data so NodeRule renders open
  const nodes = useMemo(
    () => built.nodes.map(n =>
      n.type === 'ruleNode'
        ? { ...n, data: { ...n.data, expanded: n.id === expandedGateId } }
        : n
    ),
    [built.nodes, expandedGateId]
  )

  const handleNodeClick = (_evt, node) => {
    if (node.type !== 'ruleNode') return
    setExpandedGateId(prev => (prev === node.id ? null : node.id))
  }

  const flowProps = {
    nodes,
    edges: built.edges,
    nodeTypes: NODE_TYPES,
    fitView: true,
    fitViewOptions: { padding: 0.15 },
    proOptions: { hideAttribution: true },
    minZoom: 0.25,
    maxZoom: 2,
    nodesDraggable: false,
    nodesConnectable: false,
    elementsSelectable: true,    // required for onNodeClick to fire
    panOnScroll: true,
    zoomOnScroll: false,
    onNodeClick: handleNodeClick,
  }
  const totalHeight = built.totalHeight

  if (expanded) {
    return (
      <div style={{
        position: 'fixed', inset: 0, zIndex: 9999,
        background: '#0a0f1e', display: 'flex', flexDirection: 'column',
      }}>
        {/* Expand header */}
        <div style={{
          padding: '10px 20px', borderBottom: '1px solid #1e293b',
          display: 'flex', alignItems: 'center', gap: 12, background: '#0f172a', flexShrink: 0,
        }}>
          <span style={{ fontFamily: 'monospace', fontWeight: 700, color: '#e0e7ff', fontSize: 15 }}>
            {data.sa_number}
          </span>
          {data.sa_work_type && (
            <span style={{ color: '#818cf8', fontSize: 12 }}>{data.sa_work_type}</span>
          )}
          <span style={{ color: '#334155', fontSize: 11 }}>Optimizer Decision Tree</span>
          <button
            onClick={() => setExpanded(false)}
            style={{
              marginLeft: 'auto', color: '#94a3b8', background: 'none',
              border: '1px solid #334155', borderRadius: 6, padding: '5px 12px',
              cursor: 'pointer', fontSize: 12, display: 'flex', alignItems: 'center', gap: 5,
            }}
          >
            <Minimize2 size={12} /> Close
          </button>
        </div>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <div style={{ flex: 1, minHeight: 0 }}>
            <ReactFlow {...flowProps}>
              <Controls />
              <Background color="#1e293b" gap={24} size={1} />
            </ReactFlow>
          </div>
          <div style={{ padding: '0 20px 20px', maxHeight: '40%', overflow: 'auto' }}>
            <DriverDetailGrid verdicts={data.all_verdicts} />
          </div>
        </div>
      </div>
    )
  }

  // Inline (embedded in table expand row)
  const inlineH = Math.min(totalHeight, 520)

  return (
    <div style={{ marginTop: 4 }}>
      <div style={{
        position: 'relative', borderRadius: 12, overflow: 'hidden',
        border: '1px solid #1e293b', background: '#0a0f1e',
      }}>
        <button
          onClick={() => setExpanded(true)}
          style={{
            position: 'absolute', top: 8, right: 8, zIndex: 10,
            color: '#64748b', background: 'rgba(15,23,42,0.9)',
            border: '1px solid #1e293b', borderRadius: 6, padding: '4px 9px',
            cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4, fontSize: 11,
          }}
        >
          <Maximize2 size={11} /> Expand canvas
        </button>
        <div style={{ height: inlineH, width: '100%' }}>
          <ReactFlow {...flowProps}>
            <Controls showInteractive={false} />
            <Background color="#1e293b" gap={24} size={1} />
          </ReactFlow>
        </div>
      </div>

      {/* Detail grid — every driver considered, with full data */}
      <DriverDetailGrid verdicts={data.all_verdicts} />
    </div>
  )
}
