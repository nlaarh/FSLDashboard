/**
 * Metric help panel for the Dispatcher Scorecard detail view.
 * Extracted to keep DispatchScoreDetail.jsx under the 600-line ceiling.
 */
import { X } from 'lucide-react'

const METRIC_HELP = [
  {
    label: 'Score (0–100)',
    color: 'text-slate-200',
    def: 'Overall score built from four areas: Completion Quality (40 pts) + Speed (25 pts) + Reliability (20 pts) + Volume (15 pts). Tiers: Elite 85+, Proficient 70–84, Developing 50–69, Needs Support under 50.',
    use: 'Use to rank dispatchers and set coaching priorities. Click into the four bars below the score to see which area is pulling the number down.',
  },
  {
    label: 'Completion Quality (40 pts)',
    color: 'text-emerald-400',
    def: 'Did the drivers this dispatcher assigned actually complete the call? Harder call types count more than easy ones — a tow pick-up or winch-out is worth more than a battery call. This way a dispatcher handling tough calls is not unfairly compared to one handling easy ones.',
    use: 'Low here almost always means driver selection — wrong skill, wrong territory, or a lower-tier driver sent on a complex call. Look at the Call Type Mix to see what types are in the queue.',
  },
  {
    label: 'Speed (25 pts)',
    color: 'text-blue-400',
    def: 'Typical minutes from when a service call lands in the queue to when the dispatcher assigns a driver. Calls that waited over 2 hours are excluded — those are usually calls inherited from the previous shift and are not fair to count.',
    use: 'If this score is low, the dispatcher is slow to pick up new calls. Coach on checking the queue more frequently and staying on top of FSLPulse Live Dispatch.',
  },
  {
    label: 'Reliability (20 pts)',
    color: 'text-amber-400',
    def: 'What percentage of calls took over 30 minutes to get a driver? A dispatcher can have a decent average and still leave many members waiting a long time because of specific spikes.',
    use: 'High percentage here with an acceptable average usually points to a specific time window — shift change, busy hours, or certain call types. Look at the Response Time chart to spot the pattern.',
  },
  {
    label: 'Volume (15 pts)',
    color: 'text-purple-400',
    def: 'Total calls dispatched in the last 90 days. With fewer than 20 calls, the other scores are not reliable enough to act on.',
    use: 'Low volume means interpret the other scores cautiously. This applies to supervisors and part-time dispatchers. Volume is weighted lowest so full-time dispatchers are not penalized against part-time.',
  },
  {
    label: 'PTA Rate',
    color: 'text-emerald-400',
    def: "Percentage of calls where the driver arrived On Location before the territory's promised arrival time (SA DueDate). DueDate = call start + territory PTA window (typically 60–120 min depending on garage).",
    use: 'The most direct measure of member experience. Below 75% means members are routinely waiting longer than promised — investigate whether the issue is driver selection (wrong driver far away) or PTA windows that are unrealistically short for certain territories.',
  },
  {
    label: 'Fair Completion Rate',
    color: 'text-slate-300',
    def: 'Completion rate where harder calls count more than easy ones — tow pick-ups and winch-outs are worth more than lockouts or battery calls. This is the most accurate way to compare dispatchers with different call mixes.',
    use: 'This is the number that matters most for outcome coaching. Under 80% is a concern regardless of what types of calls this dispatcher handles.',
  },
  {
    label: 'Typical Response Time',
    color: 'text-slate-300',
    def: 'The midpoint speed — half of all assignments happened faster, half took longer. Calls over 2 hours are excluded to avoid overnight backlog distorting the number.',
    use: 'The single best speed indicator. Above 20 minutes means the dispatcher is routinely slow to assign drivers, not just occasionally.',
  },
  {
    label: 'Late Assignments',
    color: 'text-slate-300',
    def: 'Percentage of calls where it took more than 30 minutes to assign a driver.',
    use: 'Catches patterns that the average misses. High Late Assignments with a decent Typical Response Time = specific hours or situations causing delays. Use FSLPulse Dispatch Trends to find when.',
  },
  {
    label: 'Typical Arrival',
    color: 'text-slate-300',
    def: 'Median time from driver assignment to the driver arriving On Location. This is what the member actually experiences — how long they wait after being told a driver is on the way. Calls over 4 hours are excluded.',
    use: 'The most direct signal of driver selection quality. A dispatcher who assigns quickly but picks a driver 90 minutes away still creates a bad experience. Compare within the same channel (Fleet vs Towbook) — contractor travel inherently takes longer.',
  },
  {
    label: 'Late Arrivals',
    color: 'text-slate-300',
    def: 'Percentage of assignments where the driver took over 60 minutes to arrive after being assigned.',
    use: 'High late arrivals with a reasonable Typical Arrival = specific calls or times where driver selection went wrong. Look at the call type mix for clues — complex calls with under-qualified or distant drivers drive this number up.',
  },
]

export function MetricHelpPanel({ onClose }) {
  return (
    <div className="mx-6 mt-0 mb-2 rounded-xl border border-slate-700/50 bg-slate-900/80 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-700/40">
        <span className="text-xs font-semibold text-slate-300">Score Definitions &amp; How to Use</span>
        <button onClick={onClose} className="text-slate-500 hover:text-slate-300 transition-colors">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
      <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-3">
        {METRIC_HELP.map(m => (
          <div key={m.label} className="bg-slate-800/40 rounded-lg border border-slate-700/30 p-3 space-y-1.5">
            <span className={`text-[11px] font-bold ${m.color}`}>{m.label}</span>
            <p className="text-[10px] text-slate-400 leading-relaxed"><span className="text-slate-500 font-semibold">What: </span>{m.def}</p>
            <p className="text-[10px] text-slate-500 leading-relaxed"><span className="text-slate-600 font-semibold">Use: </span>{m.use}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
