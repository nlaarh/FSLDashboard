import { channelSplit } from './channels'

/** How the day's calls came in: one stacked bar plus a chip per channel (count and %). Click a chip to filter the list; click again to clear. */
export default function ChannelSplit({ calls, flags, active, onPick }) {
  const { total, rows } = channelSplit(calls, flags)
  if (!total) return null
  return (
    <div className="px-3 py-2 border-b border-slate-700/60 space-y-1.5">
      <div className="text-[11px] text-slate-400">How the {total} calls came in</div>
      <div className="flex h-2 rounded-full overflow-hidden bg-slate-800">
        {rows.map(r => <span key={r.key} title={`${r.long}: ${r.n} (${r.pct}%)`} style={{ width: `${(100 * r.n) / total}%`, background: r.bar, opacity: !active || active === r.key ? 1 : 0.25 }} />)}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {rows.map(r => (
          <button key={r.key} onClick={() => onPick(active === r.key ? '' : r.key)} title={`${r.long}: ${r.n} of ${total}`}
            className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] border ${active === r.key ? 'bg-brand-600/30 border-brand-500 text-white' : 'border-slate-700 text-slate-300 hover:text-white'}`}>
            <span className="w-2 h-2 rounded-full" style={{ background: r.bar }} />{r.label} {r.n} · {r.pct}%
          </button>
        ))}
      </div>
    </div>
  )
}
