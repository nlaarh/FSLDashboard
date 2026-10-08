import { useEffect, useRef } from 'react'
import { Bot, MonitorSmartphone, Headset, Handshake, Workflow, Cloud, BrainCircuit, UserRound, Truck } from 'lucide-react'
import { HUD, NODE_ORDER, NODE_INFO, slotX } from './woReplayModel'
import { clockLabel } from '../replay/replayMath'

const ICON = { src_ivr: Bot, src_drr: MonitorSmartphone, src_mcc: Headset, src_partner: Handshake, intake: Workflow, sf: Cloud, fsl: BrainCircuit, dispatcher: UserRound, towbook: Truck }
const BRAND = '#818cf8'   // brand-400

/** The actor strip across the top: the live clock, then every channel a call can pass through as a small icon and label.
 *  Lit when this call touched it, underlined in the brand colour while it is the one acting. Past the promise a small red badge shows. */
export default function StageHud({ engine, hud, stageW, t0, pastPromise, pulse }) {
  const clockRef = useRef(null)
  useEffect(() => {
    const paint = t => { if (clockRef.current) clockRef.current.textContent = clockLabel(Math.max(t, t0), true) }
    paint(engine.ref.current.t)
    return engine.subscribe(paint)
  }, [engine, t0])
  const cell = (stageW - 16 - 232) / NODE_ORDER.length
  return (
    <>
      <div style={{ position: 'absolute', left: 10, right: 10, top: 10, height: HUD.h, borderRadius: 12, zIndex: 1040, pointerEvents: 'none',
        background: 'rgba(11,18,32,.82)', backdropFilter: 'blur(10px)', border: '1px solid rgba(100,116,139,.3)', boxShadow: '0 6px 18px rgba(0,0,0,.35)' }} />
      <div style={{ position: 'absolute', left: 24, top: 15, zIndex: 1060, pointerEvents: 'none', color: '#fff', width: 200 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div ref={clockRef} style={{ fontSize: 22, fontWeight: 800, fontVariantNumeric: 'tabular-nums', lineHeight: '26px' }} />
          {pastPromise && <span style={{ background: '#dc2626', color: '#fff', fontSize: 10, fontWeight: 700, borderRadius: 999, padding: '1px 7px', lineHeight: '14px' }}>Promise passed</span>}
        </div>
        <div style={{ fontSize: 11, color: '#94a3b8', whiteSpace: 'nowrap' }}>Call received {clockLabel(t0)}</div>
      </div>
      <div style={{ position: 'absolute', inset: 0, zIndex: 1060, pointerEvents: 'none' }}>
        {NODE_ORDER.map(id => {
          const info = NODE_INFO[id], on = hud.touched.has(id), act = hud.active.has(id), lab = on && hud.labels[id] ? hud.labels[id] : info
          const Icon = ICON[id], x = slotX(id, stageW)
          return (
            <div key={id} style={{ position: 'absolute', left: x - cell / 2 + 3, top: 10, width: cell - 6, height: HUD.h, opacity: on ? 1 : 0.4, transition: 'opacity .3s',
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7 }}>
              <span key={act ? `on${pulse}` : 'off'} style={{ color: act ? '#fff' : on ? '#cbd5e1' : '#94a3b8', display: 'flex', flexShrink: 0,
                filter: act ? `drop-shadow(0 0 6px ${BRAND})` : undefined, animation: act ? 'rp-sphere .6s ease-out' : undefined }}>
                <Icon size={19} strokeWidth={2} />
              </span>
              <span style={{ minWidth: 0 }}>
                <span style={{ display: 'block', fontSize: 12, fontWeight: 700, color: '#fff', lineHeight: '15px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{lab.label}</span>
                <span style={{ display: 'block', fontSize: 10, color: '#94a3b8', lineHeight: '12px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{lab.sub}</span>
              </span>
              <span style={{ position: 'absolute', left: 8, right: 8, bottom: 3, height: 3, borderRadius: 2, background: BRAND, boxShadow: `0 0 10px ${BRAND}`,
                opacity: act ? 1 : 0, transform: act ? 'scaleX(1)' : 'scaleX(.3)', transition: 'opacity .25s, transform .25s' }} />
            </div>
          )
        })}
      </div>
    </>
  )
}
