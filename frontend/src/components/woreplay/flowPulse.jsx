import { HUD, isSlot } from './woReplayModel'

/** A hop between two channel spheres: an arc above the row, so it never slides across the spheres in between. */
export function arcPts(a, b, n = 20) {
  const y0 = a.y - 19, h = Math.min(30, 12 + Math.abs(b.x - a.x) * 0.035), cx = (a.x + b.x) / 2, cy = y0 - 2 * h
  return Array.from({ length: n + 1 }, (_, k) => {
    const t = k / n
    return { x: (1 - t) * (1 - t) * a.x + 2 * (1 - t) * t * cx + t * t * b.x, y: (1 - t) * (1 - t) * y0 + 2 * (1 - t) * t * cy + t * t * (b.y - 19) }
  })
}

/**
 * The route one step's message flies: a hop between two spheres is an arc over the row; a hop between the bar and the map drops
 * straight down from (or rises straight up to) the sphere, so nothing crosses a label or another channel.
 * pt(id) gives a container pixel {x, y} or null. Returns [{x, y}...] or null when a stop cannot be placed (map not ready).
 */
export function pulsePath(step, pt) {
  const ids = [step.from, step.via, step.to].filter(Boolean)
  if (new Set(ids).size < 2) return null
  const path = []
  for (let k = 0; k < ids.length; k++) {
    const id = ids[k], q = pt(id)
    if (!q) return null
    const slot = isSlot(id), prev = ids[k - 1], next = ids[k + 1]
    if (slot && prev && !isSlot(prev)) path.push({ x: q.x, y: HUD.edgeY })
    if (slot && prev && isSlot(prev) && pt(prev)) path.push(...arcPts(pt(prev), q).slice(1))
    path.push(q)
    if (slot && next && !isSlot(next)) path.push({ x: q.x, y: HUD.edgeY })
  }
  return path.length > 1 ? path : null
}

/** The corner of the stage where the message card sits furthest from the action; it only moves when clearly better (hysteresis). */
export function pickDock(w, h, cardW, cardH, action, prevId) {
  const corners = [
    { id: 'tl', x: 70, y: HUD.edgeY + 6 }, { id: 'tr', x: w - cardW - 84, y: HUD.edgeY + 6 },
    { id: 'br', x: w - cardW - 84, y: h - 84 - cardH },
  ]
  const gap = c => Math.min(9999, ...action.map(q => Math.hypot(Math.max(c.x - q.x, 0, q.x - (c.x + cardW)), Math.max(c.y - q.y, 0, q.y - (c.y + cardH)))))
  const best = corners.reduce((a, c) => (gap(c) > gap(a) ? c : a), corners[0])
  const cur = corners.find(c => c.id === prevId)
  return cur && !(gap(cur) < 50 && gap(best) > gap(cur) + 40) ? cur : best
}

/** The glowing dot that flies along fx.path for 0.9 s (SVG animateMotion, no React per frame); the trail fades out after. */
export function FlowPulse({ fx }) {
  if (!fx?.path) return null
  const d = `M${fx.path.map(q => `${q.x.toFixed(1)} ${q.y.toFixed(1)}`).join(' L')}`
  const end = fx.path[fx.path.length - 1]
  return (
    <svg key={fx.key} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none', zIndex: 1050 }}>
      <path d={d} fill="none" stroke={fx.colour} strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" strokeDasharray={fx.dash || undefined} opacity=".85">
        <animate attributeName="opacity" values=".9;.9;0" keyTimes="0;.55;1" dur="2.2s" fill="freeze" />
      </path>
      <circle r="13" fill="#fff" stroke={fx.colour} strokeWidth="5">
        <animateMotion dur=".9s" fill="freeze" path={d} />
        <animate attributeName="opacity" values="1;1;0" keyTimes="0;.9;1" dur="1.1s" fill="freeze" />
      </circle>
      <circle cx={end.x} cy={end.y} r="10" fill="none" stroke={fx.colour} strokeWidth="4" opacity="0">
        <animate attributeName="r" values="10;38" begin=".85s" dur=".7s" fill="freeze" />
        <animate attributeName="opacity" values=".8;0" begin=".85s" dur=".7s" fill="freeze" />
      </circle>
    </svg>
  )
}
