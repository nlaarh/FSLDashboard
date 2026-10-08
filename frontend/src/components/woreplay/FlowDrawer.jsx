import { useEffect, useRef } from 'react'
import { iconFor } from './explainIcons'
import { KINDS, DRAWER_W } from './woReplayModel'

export const fmtDelta = s => (s < 60 ? `${s} s` : s < 3600 ? `${Math.floor(s / 60)} min ${s % 60 ? `${s % 60} s` : ''}`.trim() : `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min`)

/** The flow column beside the map: every step in order, the current one lit; a click jumps there. `top` slots in the contact panel when a mark is open. */
export default function FlowDrawer({ steps, i, open, onStep, top }) {
  const listRef = useRef(null)
  useEffect(() => {
    const row = listRef.current?.querySelector(`[data-step="${i}"]`)
    if (row && open && i >= 0) listRef.current.scrollTo({ top: row.offsetTop - 120, behavior: 'smooth' })
  }, [i, open])
  return (
    <div style={{ width: open ? DRAWER_W : 0, transition: 'width .35s cubic-bezier(.2,.8,.2,1)', overflow: 'hidden', flexShrink: 0, background: 'rgba(15,23,42,.97)' }}>
      <div style={{ width: DRAWER_W, height: '100%', color: '#e2e8f0', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '12px 16px', borderBottom: '1px solid #33415588' }}>
          <div style={{ fontSize: 11, letterSpacing: 1.8, textTransform: 'uppercase', color: '#94a3b8' }}>Flow</div>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#fff' }}>{steps.length} events in order</div>
        </div>
        {top}
        <div ref={listRef} style={{ flex: 1, overflowY: 'auto', padding: '6px 0', position: 'relative' }}>
          {steps.map((st, k) => {
            const kd = KINDS[st.kind] || KINDS.system, now = k === i, done = k < i
            const FI = st.explain ? iconFor(st.explain.icon) : null
            return (
              <button key={st.id} data-step={k} onClick={() => onStep(k)}
                style={{ display: 'block', width: '100%', textAlign: 'left', padding: '8px 16px 8px 40px', position: 'relative', border: 'none', cursor: 'pointer', color: 'inherit',
                  background: now ? `${kd.colour}33` : 'transparent', opacity: done || now ? 1 : 0.55, borderLeft: `3px solid ${now ? kd.colour : 'transparent'}` }}>
                <span style={{ position: 'absolute', left: 17, top: 0, bottom: 0, width: 2, background: '#33415588' }} />
                <span style={{ position: 'absolute', left: 11, top: 12, width: 14, height: 14, borderRadius: '50%', background: st.flag ? '#f43f5e' : kd.colour, border: '2px solid #0f172a', boxShadow: now ? `0 0 0 4px ${kd.colour}55` : 'none' }} />
                <span style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11.5, color: '#94a3b8', fontVariantNumeric: 'tabular-nums' }}>
                  <span>{st.clock}</span><span>{st.dt ? `+${fmtDelta(st.dt)}` : 'start'}</span>
                </span>
                <span style={{ display: 'block', fontSize: 13.5, fontWeight: now ? 700 : 600, color: '#fff', lineHeight: '17px' }}>{st.title}</span>
                <span style={{ display: 'block', fontSize: 11.5, color: kd.colour }}>{[kd.label, st.actor].filter(Boolean).join(' · ')}</span>
                {FI && <span style={{ position: 'absolute', right: 12, top: 26, color: st.flag?.level === 'bad' ? '#fb7185' : '#fbbf24' }} title={st.explain.title}><FI size={16} /></span>}
                {st.flag && <span style={{ display: 'block', fontSize: 11.5, color: '#fda4af', fontWeight: 700 }}>{st.flag.text}</span>}
                {st.why && <span style={{ display: 'block', fontSize: 11.5, color: '#fde68a', fontWeight: 600 }}>Why: {st.why.headline}</span>}
                {now && (st.content || []).slice(0, 3).map((l, n) => <span key={n} style={{ display: 'block', fontSize: 11.5, color: '#cbd5e1' }}>{l}</span>)}
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}
