import { iconFor } from './explainIcons'
import { KINDS } from './woReplayModel'
import { fmtDelta } from './FlowDrawer'

/** The message card docked in a corner of the stage: what this step is, who did it, and (when flagged) why it may have happened. */
export function StepCard({ step, dock, w, maxH, onEnter, onLeave }) {
  const kind = KINDS[step.kind] || KINDS.system
  const XI = step.explain ? iconFor(step.explain.icon) : null
  return (
    <div onMouseEnter={onEnter} onMouseLeave={onLeave} className="rp-glass"
      style={{ position: 'absolute', left: dock.x, top: dock.y, zIndex: 1060, width: w, maxHeight: maxH, overflowY: 'auto', padding: '8px 12px', borderRadius: 14, color: '#e2e8f0',
        border: `2px solid ${step.flag ? '#f43f5e' : kind.colour}` }}>
      <div style={{ fontSize: 10.5, letterSpacing: 1.5, textTransform: 'uppercase', fontWeight: 700, color: step.flag ? '#fda4af' : kind.colour }}>{step.clock} · {kind.label}{step.actor ? ` · ${step.actor}` : ''}</div>
      <div style={{ fontSize: 14, fontWeight: 700, color: '#fff', marginTop: 1 }}>{step.title}</div>
      {(step.content || []).map((l, k) => <div key={k} style={{ fontSize: 12, color: '#cbd5e1', marginTop: 1 }}>{l}</div>)}
      {step.flag && <div style={{ fontSize: 12.5, fontWeight: 700, color: '#fda4af', marginTop: 4 }}>{step.flag.text}</div>}
      {XI && (
        <div style={{ marginTop: 7, paddingTop: 6, borderTop: '1px solid #475569' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10.5, letterSpacing: 1.3, textTransform: 'uppercase', fontWeight: 700, color: '#fca5a5' }}><XI size={14} />Why this may have happened</div>
          {step.explain.why.slice(0, 3).map((l, k) => <div key={k} style={{ fontSize: 12, color: l.startsWith('This call:') ? '#fde68a' : '#cbd5e1', marginTop: 3 }}>{l}</div>)}
          {step.explain.check[0] && <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}><b style={{ color: '#cbd5e1' }}>Check:</b> {step.explain.check[0]}</div>}
        </div>
      )}
      {step.why && (
        <div style={{ marginTop: 7, paddingTop: 6, borderTop: '1px solid #475569' }}>
          <div style={{ fontSize: 10.5, letterSpacing: 1.5, textTransform: 'uppercase', fontWeight: 700, color: '#fbbf24' }}>Why this driver</div>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#fde68a', marginTop: 1 }}>{step.why.headline}</div>
          {step.why.lines.map((l, k) => <div key={k} style={{ fontSize: 12, color: l.startsWith('Computed') ? '#fcd34d' : '#cbd5e1', marginTop: 2 }}>{l}</div>)}
        </div>
      )}
    </div>
  )
}

/** The slim caption along the bottom of the stage: time, how far into the call, what happened, who did it. */
export function StepCaption({ step, i, n }) {
  const kind = KINDS[step.kind] || KINDS.system
  return (
    <div className="rp-glass" style={{ position: 'absolute', left: 10, right: 10, bottom: 10, zIndex: 1060, padding: '8px 18px', borderRadius: 14, color: '#e2e8f0', display: 'flex', alignItems: 'center', gap: 18, pointerEvents: 'none',
      borderColor: step.flag ? '#f43f5ecc' : `${kind.colour}88` }}>
      <div style={{ fontSize: 22, fontWeight: 800, fontVariantNumeric: 'tabular-nums', color: '#fff', minWidth: 128 }}>{step.clock}</div>
      <div style={{ fontSize: 12, color: '#94a3b8', minWidth: 118 }}>{step.dt === 0 ? 'Call starts' : `${fmtDelta(step.dt)} into the call`}</div>
      <div style={{ flex: 1, minWidth: 0, fontSize: 16, fontWeight: 700, color: '#fff', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
        <span style={{ fontSize: 10.5, letterSpacing: 1.4, textTransform: 'uppercase', color: kind.colour, marginRight: 10 }}>{kind.label}</span>{step.title}
        {step.flag && <span style={{ marginLeft: 10, padding: '1px 9px', borderRadius: 999, fontSize: 12, background: step.flag.level === 'bad' ? '#f43f5e33' : '#f59e0b33', color: step.flag.level === 'bad' ? '#fda4af' : '#fcd34d' }}>{step.flag.text}</span>}
      </div>
      {step.actor && <div style={{ textAlign: 'right', whiteSpace: 'nowrap' }}><span style={{ fontSize: 13.5, fontWeight: 600, color: '#fff' }}>{step.actor}</span><span style={{ fontSize: 12, color: kind.colour, marginLeft: 8 }}>{step.role}</span></div>}
      <div style={{ fontSize: 12, color: '#64748b', whiteSpace: 'nowrap' }}>{i + 1} / {n}</div>
    </div>
  )
}
