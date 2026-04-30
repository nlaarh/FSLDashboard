import { Sparkles, ShieldAlert, Lightbulb, CheckSquare, List } from 'lucide-react'

export default function AccountingAnalyticsAiCard({ insight }) {
  if (!insight) return null
  return (
    <div className="mt-3 glass rounded-xl border border-blue-800/30 overflow-hidden">
      <div className="px-4 py-2.5 border-b border-blue-900/30 flex items-center gap-2">
        <Sparkles className="w-3.5 h-3.5 text-blue-400" />
        <span className="text-[10px] font-bold text-blue-400 uppercase tracking-wider">Accounting Advisor Summary</span>
      </div>
      <div className="px-4 py-3 space-y-3">
        {insight.headline && (
          <div className="text-[12px] font-semibold text-slate-200 leading-snug">{insight.headline}</div>
        )}
        {insight.story && (
          <div className="text-[11px] text-slate-300 leading-relaxed">{insight.story}</div>
        )}
        {insight.top_concerns?.length > 0 && (
          <div>
            <div className="flex items-center gap-1.5 mb-1.5">
              <ShieldAlert className="w-3 h-3 text-red-400" />
              <span className="text-[9px] font-bold text-red-400 uppercase tracking-wider">Top Concerns</span>
            </div>
            {insight.top_concerns.map((s, i) => (
              <div key={i} className="flex items-start gap-2 text-[10px] text-red-300">
                <span className="text-red-500 mt-0.5">●</span>{s}
              </div>
            ))}
          </div>
        )}
        {insight.root_causes?.length > 0 && (
          <div>
            <div className="flex items-center gap-1.5 mb-1.5">
              <Lightbulb className="w-3 h-3 text-amber-400" />
              <span className="text-[9px] font-bold text-amber-400 uppercase tracking-wider">Root Causes</span>
            </div>
            {insight.root_causes.map((s, i) => (
              <div key={i} className="flex items-start gap-2 text-[10px] text-amber-300">
                <span className="text-amber-500 mt-0.5">●</span>{s}
              </div>
            ))}
          </div>
        )}
        {insight.action_plan?.length > 0 && (
          <div>
            <div className="flex items-center gap-1.5 mb-1.5">
              <CheckSquare className="w-3 h-3 text-emerald-400" />
              <span className="text-[9px] font-bold text-emerald-400 uppercase tracking-wider">Action Plan</span>
            </div>
            {insight.action_plan.map((s, i) => (
              <div key={i} className="flex items-start gap-2 text-[10px] text-emerald-300">
                <span className="text-emerald-600 font-bold mt-0.5">{i + 1}.</span>{s}
              </div>
            ))}
          </div>
        )}
        {insight.watch_list?.length > 0 && (
          <div>
            <div className="flex items-center gap-1.5 mb-1.5">
              <List className="w-3 h-3 text-slate-400" />
              <span className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">Watch List</span>
            </div>
            {insight.watch_list.map((s, i) => (
              <div key={i} className="flex items-start gap-2 text-[10px] text-slate-400">
                <span className="mt-0.5">—</span>{s}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
