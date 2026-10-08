import { useEffect, useRef } from 'react'
import { HUD, NODE_ORDER, NODE_INFO, slotX } from './woReplayModel'
import { clockLabel } from '../replay/replayMath'

/** The command-center bar across the top: the live clock, and every channel a call can pass through (lit when this call touched it). */
export default function StageHud({ engine, hud, stageW, t0, pastPromise, pulse }) {
  const clockRef = useRef(null)
  useEffect(() => {
    const paint = t => { if (clockRef.current) clockRef.current.textContent = clockLabel(Math.max(t, t0), true) }
    paint(engine.ref.current.t)
    return engine.subscribe(paint)
  }, [engine, t0])
  return (
    <>
      <div style={{ position: 'absolute', left: 10, right: 10, top: 10, height: HUD.h, borderRadius: 16, zIndex: 1040, pointerEvents: 'none', transition: 'background .4s',
        background: pastPromise ? 'rgba(127,29,29,.9)' : 'rgba(15,23,42,.86)', backdropFilter: 'blur(10px)', border: '1px solid rgba(100,116,139,.35)', boxShadow: '0 8px 24px rgba(0,0,0,.35)' }} />
      <div style={{ position: 'absolute', left: 22, top: 30, zIndex: 1060, pointerEvents: 'none', color: '#fff', width: 200 }}>
        <div ref={clockRef} style={{ fontSize: 26, fontWeight: 800, fontVariantNumeric: 'tabular-nums', lineHeight: 1.05 }} />
        <div style={{ fontSize: 11.5, color: '#cbd5e1', marginTop: 2, whiteSpace: 'nowrap' }}>Call received {clockLabel(t0)}{pastPromise ? ' · promise passed' : ''}</div>
      </div>
      <div style={{ position: 'absolute', inset: 0, zIndex: 1060, pointerEvents: 'none' }}>
        {NODE_ORDER.map(id => {
          const info = NODE_INFO[id], on = hud.touched.has(id), act = hud.active.has(id), lab = on && hud.labels[id] ? hud.labels[id] : info
          const x = slotX(id, stageW)
          return (
            <div key={id} style={{ opacity: on ? 1 : 0.4, transition: 'opacity .3s' }}>
              <div key={act ? `on${pulse}` : 'off'} style={{ position: 'absolute', left: x - 18, top: HUD.y - 18, width: 36, height: 36, borderRadius: '50%',
                background: `radial-gradient(circle at 32% 28%, #ffffffcc 0, ${info.colour} 38%, #0f172a 130%)`,
                boxShadow: act ? `0 0 0 4px ${info.colour}66, 0 0 22px ${info.colour}` : '0 3px 8px rgba(0,0,0,.45)', transition: 'box-shadow .3s',
                animation: act ? 'rp-sphere .9s ease-out' : undefined }} />
              <div style={{ position: 'absolute', left: x - 55, top: HUD.y + 22, width: 110, textAlign: 'center', background: 'rgba(15,23,42,.6)', borderRadius: 7, padding: '1px 3px' }}>
                <div style={{ fontSize: 12.5, fontWeight: 700, color: '#fff', lineHeight: '15px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{lab.label}</div>
                <div style={{ fontSize: 10.5, color: '#94a3b8', lineHeight: '13px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{lab.sub}</div>
              </div>
            </div>
          )
        })}
      </div>
    </>
  )
}
