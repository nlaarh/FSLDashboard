import { useState } from 'react'
import {
  DollarSign, ShieldAlert, Navigation, Sparkles, BarChart3, ChevronDown, ChevronUp,
} from 'lucide-react'

const CAPABILITIES = [
  {
    icon: DollarSign,
    title: 'Every open WOA in one place',
    color: 'text-emerald-400',
    border: 'border-emerald-500/20',
    bg: 'bg-emerald-500/5',
    points: [
      'What each garage requested, what was billed, and the outstanding delta — side by side',
      'Full audit panel per WOA: service details, all line items, and the complete service timeline from call received to job completed',
    ],
  },
  {
    icon: Navigation,
    title: 'Automated verification',
    color: 'text-blue-400',
    border: 'border-blue-500/20',
    bg: 'bg-blue-500/5',
    points: [
      'GPS mileage check — actual miles driven from real GPS data vs what the vendor submitted',
      'Automatic toll detection — the route is run through Google Maps and any tolls along the path are identified',
      'Live route map — see exactly where the driver went, start to finish, on a real map so you can verify every mile visually',
    ],
  },
  {
    icon: ShieldAlert,
    title: 'Per-WOA AI audit',
    color: 'text-amber-400',
    border: 'border-amber-500/20',
    bg: 'bg-amber-500/5',
    points: [
      'For each work order, the AI generates a recommendation (PAY, REVIEW, or DENY) with a confidence level',
      'Fraud signals when found: GPS that does not support the claimed distance, En Route and On Location timestamps seconds apart (driver never actually drove), claimed minutes far exceeding actual on-scene time',
      'Anomalies flagged separately — unusual findings that do not rise to fraud but warrant a closer look',
      'Specific actions for the accountant and questions to ask the garage if the WOA is under review',
    ],
  },
  {
    icon: Sparkles,
    title: 'AI Accounting Advisor',
    color: 'text-indigo-400',
    border: 'border-indigo-500/20',
    bg: 'bg-indigo-500/5',
    points: [
      'Portfolio-level AI analysis: a plain-English headline and narrative summarizing the entire open WOA backlog',
      'Top concerns with specific garage names and dollar amounts — not general observations',
      'Root causes identified across the portfolio (mileage inflation, wait time padding, duplicate submissions)',
      'A prioritized action plan for the week and a watch list of garages or submitters to monitor',
    ],
  },
  {
    icon: BarChart3,
    title: 'Analytics tab',
    color: 'text-purple-400',
    border: 'border-purple-500/20',
    bg: 'bg-purple-500/5',
    points: [
      'Three auto-flagged alert cards at the top: largest review backlog, worst approval rate, and top dispute driver — no setup required',
      'AI analysis loads automatically and delivers which garages to call today, root causes, and a week\'s action plan',
      'Garage leaderboard ranked by risk — how many invoices are unresolved per garage, with approval rate and top billing codes shown inline',
      'Product line chart shows which billing codes generate the most disputes — click any bar to filter the WOA list to just that code',
      'Submitter chart: who files the most WOAs and what percentage get flagged — a person filing a high volume with a low approval rate warrants a closer look',
      'Expandable heatmap showing which billing codes each garage uses across the portfolio',
    ],
  },
]

function CapabilityCard({ cap }) {
  const [open, setOpen] = useState(true)
  const Icon = cap.icon
  return (
    <div className={`rounded-xl border ${cap.border} ${cap.bg} overflow-hidden`}>
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full px-4 py-3 flex items-center justify-between hover:bg-white/5 transition-colors"
      >
        <div className="flex items-center gap-2.5">
          <Icon className={`w-4 h-4 ${cap.color}`} />
          <span className="text-sm font-semibold text-white">{cap.title}</span>
        </div>
        {open
          ? <ChevronUp className="w-3.5 h-3.5 text-slate-500" />
          : <ChevronDown className="w-3.5 h-3.5 text-slate-500" />}
      </button>
      {open && (
        <ul className="px-5 pb-4 space-y-1.5">
          {cap.points.map((p, i) => (
            <li key={i} className="flex items-start gap-2 text-[12px] text-slate-300 leading-relaxed">
              <span className={`mt-1.5 w-1 h-1 rounded-full shrink-0 ${cap.color.replace('text-', 'bg-')}`} />
              {p}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function HelpAccounting() {
  return (
    <div className="max-w-5xl mx-auto space-y-6">

      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-white mb-1">Accounting Module Guide</h2>
        <p className="text-sm text-slate-400 leading-relaxed">
          FleetPulse Accounting is an AI agent designed to automate the review and audit of roadside
          service billing. This is a work in progress — the AI will continue to improve as it is
          trained on more data — but what it does today is already meaningful.
        </p>
      </div>

      {/* Capability cards */}
      <div className="space-y-3">
        {CAPABILITIES.map(cap => (
          <CapabilityCard key={cap.title} cap={cap} />
        ))}
      </div>

      {/* PDF Guide */}
      <div className="glass rounded-xl border border-slate-700/30 overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-800/60 flex items-center gap-2">
          <DollarSign className="w-4 h-4 text-brand-400" />
          <span className="text-sm font-semibold text-slate-200">Full Accounting Guide (PDF)</span>
          <a
            href="/FleetPulse_Accounting_Guide.pdf"
            target="_blank"
            rel="noreferrer"
            className="ml-auto text-[11px] text-brand-400 hover:text-brand-300 transition-colors"
          >
            Open in new tab ↗
          </a>
        </div>
        <iframe
          src="/FleetPulse_Accounting_Guide.pdf"
          title="FleetPulse Accounting Guide"
          className="w-full"
          style={{ height: '80vh', border: 'none' }}
        />
      </div>

    </div>
  )
}
