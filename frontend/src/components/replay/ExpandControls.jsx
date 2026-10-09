import { Maximize2, Minimize2, ArrowLeft } from 'lucide-react'

/** The Expand button that sits on a replay map. */
export function ExpandButton({ expand, className = '' }) {
  return (
    <button type="button" onClick={expand.open} title="Expand to fill the screen: the map, the slider and the details together"
      className={`rp-glass rounded-lg px-2.5 py-1.5 text-xs font-semibold text-white flex items-center gap-1.5 hover:brightness-125 ${className}`}>
      <Maximize2 className="w-3.5 h-3.5" />Expand
    </button>
  )
}

/** Top strip of the expanded replay: the return arrow on the left, browser full screen on the right. Shows nothing when not expanded. */
export function ExpandBar({ expand, title, className = '' }) {
  if (!expand.expanded) return null
  return (
    <div className={`flex items-center gap-3 shrink-0 ${className}`}>
      <button type="button" onClick={expand.close} title="Back (Esc)" aria-label="Back"
        className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-white text-sm font-semibold flex items-center gap-2"><ArrowLeft className="w-5 h-5" />Back</button>
      <div className="text-base font-semibold text-white truncate">{title}</div>
      <button type="button" onClick={expand.toggleFs} title={expand.isFs ? 'Exit full screen' : 'Full screen'}
        className="ml-auto px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-sm flex items-center gap-2">
        {expand.isFs ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}{expand.isFs ? 'Exit full screen' : 'Full screen'}
      </button>
    </div>
  )
}
