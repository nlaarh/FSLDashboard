import { clsx } from 'clsx'
import { Layers, Loader2, CheckCircle2, Zap, Truck, Navigation, Clock } from 'lucide-react'
import SALink from './SALink'

// ── Legend bar (below map) ───────────────────────────────────────────────────

export function MapLegend({ selected }) {
  return (
    <div className="flex flex-wrap gap-4 text-xs text-slate-400">
      <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded" style={{background:'#ef4444'}} /> Customer</span>
      {selected.timeline?.dispatch_method !== 'Towbook' && <>
        <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded" style={{background:'#22c55e'}} /> Closest Driver</span>
        <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded" style={{background:'#f97316'}} /> Dispatched Position</span>
        <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded" style={{background:'#64748b'}} /> Eligible</span>
        <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded" style={{background:'#334155'}} /> Not Eligible</span>
      </>}
      <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded" style={{background:'#a855f7'}} /> Facility</span>
    </div>
  )
}

// ── Floating layer toggle panel ──────────────────────────────────────────────

export function LayerPanel({ layers, setLayers, layerLoading }) {
  return (
    <div className="absolute top-3 right-3 z-[1000]" style={{ minWidth: 130 }}>
      <div className="bg-slate-900/95 backdrop-blur-xl border border-slate-600/40 rounded-xl shadow-2xl overflow-hidden">
        <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-800/60">
          <Layers className="w-3.5 h-3.5 text-brand-400" />
          <span className="text-[10px] font-bold text-white uppercase tracking-wide">Layers</span>
        </div>
        <div className="px-3 py-2.5 space-y-2">
          {[
            { key: 'grid',    emoji: '\uD83D\uDDFA\uFE0F', label: 'Grid',    color: 'text-indigo-400' },
            { key: 'weather', emoji: '\uD83C\uDF21\uFE0F', label: 'Weather', color: 'text-cyan-400' },
          ].map(({ key, emoji, label, color }) => (
            <label key={key} className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={layers[key]}
                onChange={e => setLayers(l => ({ ...l, [key]: e.target.checked }))}
                className="w-3 h-3 rounded accent-indigo-500"
              />
              <span className="text-sm leading-none">{emoji}</span>
              <span className={`text-[10px] font-medium flex-1 ${layers[key] ? color : 'text-slate-500'}`}>
                {label}
              </span>
              {layerLoading[key] && <Loader2 className="w-2.5 h-2.5 text-brand-400 animate-spin" />}
            </label>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Timeline Components ─────────────────────────────────────────────────────

export function TimeStep({ icon, label, time, sub, color = 'text-slate-400' }) {
  return (
    <div className="flex flex-col items-center min-w-[70px]">
      <div className={clsx('flex items-center gap-1 text-[10px] uppercase tracking-wider', color)}>{icon} {label}</div>
      <div className="text-xs font-bold text-white mt-0.5">{time || '\u2014'}</div>
      {sub && <div className="text-[9px] text-slate-500">{sub}</div>}
    </div>
  )
}

export function TimeArrow({ label }) {
  return (
    <div className="flex flex-col items-center px-1">
      <div className="text-[9px] text-slate-500 mb-0.5">{label}</div>
      <div className="w-8 h-px bg-slate-700 relative">
        <div className="absolute right-0 top-[-2px] w-0 h-0 border-l-4 border-l-slate-700 border-y-2 border-y-transparent" />
      </div>
    </div>
  )
}

export function SumCard({ label, value, sub, color = 'text-white' }) {
  return (
    <div className="glass rounded-xl p-3">
      <div className="text-[10px] text-slate-400 uppercase tracking-wider">{label}</div>
      <div className={clsx('text-xl font-bold mt-0.5', color)}>
        {value}{sub && <span className="text-sm font-normal text-slate-500 ml-1">{sub}</span>}
      </div>
    </div>
  )
}

export function MiniStat({ label, value, sub, color = 'text-slate-200' }) {
  return (
    <div>
      <div className="text-[10px] text-slate-500 uppercase">{label}</div>
      <div className={clsx('text-sm font-semibold', color)}>{value}</div>
      {sub && <div className="text-[10px] text-slate-500">{sub}</div>}
    </div>
  )
}
