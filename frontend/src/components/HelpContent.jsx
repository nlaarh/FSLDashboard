import { useState, useEffect, useMemo } from 'react'
import {
  BarChart3, Clock, CheckCircle2, ThumbsUp, TrendingDown, Zap, XCircle,
  ArrowRightLeft, Truck, AlertTriangle, Loader2, RefreshCw, Filter,
} from 'lucide-react'
import { clsx } from 'clsx'
import { motion } from 'framer-motion'
import { SectionHeader } from './HelpHowItWorks'
import { fetchDataQuality, refreshDataQuality } from '../api'

const fadeUp = { hidden: { opacity: 0, y: 18 }, show: { opacity: 1, y: 0 } }
const stagger = (staggerChildren = 0.06) => ({
  hidden: {},
  show: { transition: { staggerChildren } },
})

const METRICS = [
  {
    name: 'Total Calls', icon: BarChart3,
    what: 'Count of all Service Appointments dispatched to this garage in the selected period. Includes dispatched, completed, canceled, assigned, unable to complete, and no-show calls. Tow Drop-Offs are excluded because they are the second leg of a tow — the member\'s wait is measured on the Pick-Up SA only.',
    formula: `SELECT COUNT(ServiceAppointment.Id)
FROM ServiceAppointment
WHERE ServiceAppointment.ServiceTerritoryId = '{this garage}'
  AND ServiceAppointment.CreatedDate >= {period_start}
  AND ServiceAppointment.Status IN ('Dispatched','Completed','Canceled',
      'Cancel Call - Service Not En Route','Cancel Call - Service En Route',
      'Unable to Complete','Assigned','No-Show')
  AND WorkType.Name != 'Tow Drop-Off'`,
  },
  {
    name: 'Completion Rate', icon: CheckCircle2,
    what: 'Percentage of dispatched calls this garage actually finished. Of all the calls sent to this garage, how many did they complete? Example: if a garage got 100 calls and completed 80, the rate is 80%.',
    formula: `completion_rate = COUNT(Status = 'Completed') ÷ Total Calls × 100`,
    target: '95%',
  },
  {
    name: 'Median Response Time', icon: Clock,
    what: 'The middle value of how long members waited — from when the call was created to when the driver physically arrived on scene. Uses the median (not average) so a few extreme outliers don\'t skew the number. Includes both fleet and Towbook dispatches. Excludes Tow Drop-Offs.',
    formula: `For each SA where Status = 'Completed' AND WorkType.Name != 'Tow Drop-Off':
  response_minutes = (ActualStartTime − CreatedDate) in minutes
Guardrail: discard if response_minutes ≤ 0 or > 480 (bad data).
Sort all valid values → take the middle value (median).`,
    target: '45 min',
  },
  {
    name: '45-Min SLA Hit Rate', icon: Target,
    what: 'Percentage of completed calls where the driver arrived within 45 minutes of the call being created. This is the single most important metric — it carries 30% of the composite score weight. A garage hitting 100% means every member was helped within 45 minutes.',
    formula: `sla_hit_rate = COUNT(response_minutes ≤ 45) ÷ COUNT(all valid response_minutes) × 100

Fields: ActualStartTime, CreatedDate, Status = 'Completed', WorkType.Name != 'Tow Drop-Off'`,
    target: '100%',
  },
  {
    name: 'PTA Accuracy (ETA Accuracy)', icon: Zap,
    what: 'Of completed calls that had a promised ETA, what percentage had the driver arrive within the promised time? Measures whether the time estimate given to the member at dispatch was realistic. Values of 0 and 999 are ignored (no valid ETA was given).',
    formula: `For each SA where Status = 'Completed' AND ERS_PTA__c BETWEEN 1 AND 998:
  actual_wait = (ActualStartTime − CreatedDate) in minutes
  on_time = actual_wait ≤ ERS_PTA__c
pta_accuracy = COUNT(on_time = true) ÷ COUNT(evaluated) × 100`,
    target: '90%',
  },
  {
    name: 'Primary Acceptance Rate', icon: CheckCircle2,
    what: 'When a call is auto-dispatched to this garage as the primary (first choice) garage, what percentage does the garage accept? A declined call cascades to the next garage in the zone chain, adding delay for the member.',
    formula: `Filter: ERS_Auto_Assign__c = true
accepted = ERS_Facility_Decline_Reason__c IS NULL
acceptance_rate = COUNT(accepted) ÷ COUNT(all auto-assigned) × 100`,
  },
  {
    name: '1st Call vs 2nd+ Call Acceptance', icon: ArrowRightLeft,
    what: 'Was this garage the first one assigned to the call, or did it receive the call after another garage declined? "1st Call" means the system originally sent it here. "2nd+ Call" means another garage got it first, declined, and it cascaded to this garage.',
    formula: `Primary method: Query ServiceAppointmentHistory WHERE Field = 'ServiceTerritoryId'
ORDER BY CreatedDate ASC
First NewValue = first territory assigned.
If first NewValue = this garage → "1st Call"
If first NewValue ≠ this garage → "2nd+ Call" (received after cascade)

Fallback: ERS_Spotting_Number__c on SA (1 = 1st Call, >1 = 2nd+ Call)`,
  },
  {
    name: 'Completion of Accepted', icon: CheckCircle2,
    what: 'Of all the calls this garage accepted (did not decline), what percentage were actually completed? Separates "willingness to take the call" from "ability to finish the job."',
    formula: `Filter: ERS_Facility_Decline_Reason__c IS NULL (accepted only)
completion_of_accepted = COUNT(Status = 'Completed') ÷ COUNT(accepted) × 100`,
  },
  {
    name: 'Customer Satisfaction', icon: ThumbsUp,
    what: 'Percentage of members who rated "Totally Satisfied" on their post-call survey. Surveys are sent by Qualtrics after the call and matched back to the garage via the Work Order number.',
    formula: `Step 1: SELECT WorkOrderNumber FROM WorkOrder WHERE ServiceTerritoryId = '{garage}'
Step 2: SELECT ERS_Overall_Satisfaction__c FROM Survey_Result__c
        WHERE ERS_Work_Order_Number__c IN ({WO numbers})
satisfaction = COUNT('Totally Satisfied') ÷ COUNT(all surveys) × 100`,
    target: '82%',
  },
  {
    name: '"Could Not Wait" Rate', icon: XCircle,
    what: 'Percentage of calls canceled because the member gave up waiting for the driver. A high rate means response times are too slow — members are abandoning before help arrives.',
    formula: `cnw_count = COUNT(ERS_Cancellation_Reason__c LIKE 'Member Could Not Wait%')
cnw_rate = cnw_count ÷ Total Calls × 100`,
    target: '< 3%',
  },
  {
    name: 'Facility Decline Rate', icon: TrendingDown,
    what: 'Percentage of calls where the garage declined the assignment. When a garage declines, the call cascades to the next garage in the zone chain, adding delay.',
    formula: `decline_count = COUNT(ERS_Facility_Decline_Reason__c IS NOT NULL)
decline_rate = decline_count ÷ Total Calls × 100`,
    target: '< 2%',
  },
  {
    name: 'Dispatch Speed', icon: Zap,
    what: 'Median time from call creation to driver scheduled. Measures how fast the system assigns a driver. Slow dispatch = calls sitting in queue.',
    formula: `dispatch_minutes = (SchedStartTime − CreatedDate) in minutes
Guardrail: discard if < 0 or ≥ 1440. Take median.`,
    target: '≤ 5 min',
  },
  {
    name: 'Dispatch Mix', icon: BarChart3,
    what: 'Percentage split between internal fleet drivers (Field Services) and external contractors (Towbook).',
    formula: `fleet_pct = COUNT(ERS_Dispatch_Method__c = 'Field Services') ÷ Total × 100
towbook_pct = COUNT(ERS_Dispatch_Method__c = 'Towbook') ÷ Total × 100`,
  },
  {
    name: 'Response Time Decomposition', icon: Clock,
    what: 'Breaks total wait into: (1) dispatch queue time, (2) driver travel time, (3) on-site duration. Pinpoints where delays happen.',
    formula: `(1) dispatch_queue = SchedStartTime − CreatedDate
(2) travel = ActualStartTime − SchedStartTime
(3) on_site = ActualEndTime − ActualStartTime`,
  },
  {
    name: 'PTS-ATA (Promised vs Actual)', icon: Clock,
    what: 'Compares ETA promised to member vs actual arrival. Shows on-time %, late %, and average delta.',
    formula: `expected_arrival = CreatedDate + ERS_PTA__c minutes
delta = ActualStartTime − expected_arrival
delta ≤ 0 → on time or early | delta > 0 → late by delta minutes`,
  },
]

const SCORE_DIMENSIONS = [
  { key: 'sla_hit_rate',    label: '45-Min SLA Hit Rate', weight: '30%', target: '100%' },
  { key: 'completion_rate',  label: 'Completion Rate',     weight: '15%', target: '95%' },
  { key: 'satisfaction',     label: 'Customer Satisfaction', weight: '15%', target: '82%' },
  { key: 'median_response',  label: 'Median Response Time', weight: '10%', target: '≤ 45 min' },
  { key: 'pta_accuracy',     label: 'PTA Accuracy',        weight: '10%', target: '90%' },
  { key: 'could_not_wait',   label: '"Could Not Wait" Rate', weight: '10%', target: '< 3%' },
  { key: 'dispatch_speed',   label: 'Dispatch Speed',      weight: '5%',  target: '≤ 5 min' },
  { key: 'decline_rate',     label: 'Facility Decline Rate', weight: '5%',  target: '< 2%' },
]

export function MetricsSection() {
  return (
    <div>
      <SectionHeader title="Metric Definitions" subtitle="Every metric in the app — what it measures, how it is calculated, and which Salesforce fields are used." />
      <motion.div className="space-y-3 mt-4" variants={stagger(0.05)} initial="hidden" animate="show">
        {METRICS.map(m => (
          <motion.div key={m.name} className="glass rounded-xl border border-slate-700/20 overflow-hidden"
            variants={fadeUp} transition={{ type: 'spring', stiffness: 300, damping: 24 }}>
            <div className="flex items-center gap-3 px-4 py-3 border-b border-slate-700/20">
              <m.icon className="w-4 h-4 text-brand-400 shrink-0" />
              <span className="font-semibold text-sm text-slate-200">{m.name}</span>
              {m.target && (
                <span className="ml-auto text-[10px] font-bold text-emerald-400 bg-emerald-950/40 border border-emerald-800/30 rounded px-2 py-0.5">
                  Target: {m.target}
                </span>
              )}
            </div>
            <div className="px-4 py-3 space-y-2.5">
              <div>
                <div className="text-[9px] font-bold uppercase tracking-wider text-slate-500 mb-1">What it measures</div>
                <p className="text-xs text-slate-300 leading-relaxed">{m.what}</p>
              </div>
              <div>
                <div className="text-[9px] font-bold uppercase tracking-wider text-slate-500 mb-1">Salesforce Query & Fields</div>
                <pre className="text-[11px] text-brand-300/80 leading-relaxed bg-slate-900/50 rounded-lg p-3 border border-slate-700/20 whitespace-pre-wrap font-mono overflow-x-auto">
                  {m.formula}
                </pre>
              </div>
            </div>
          </motion.div>
        ))}
      </motion.div>
    </div>
  )
}

export function RulesSection() {
  const rules = [
    { title: 'Tow Drop-Off Exclusion', text: 'Tow Drop-Off SAs are excluded from all response time and metric calculations. The member\'s response time is measured on the Pick-Up SA only — the Drop-Off is a separate leg that happens after the member is already helped.' },
    { title: 'Towbook ActualStartTime', text: 'Towbook-dispatched SAs have their ActualStartTime synced from Towbook via the "Integrations Towbook" user. Real arrival time comes from SA History "On Location" status. Both Fleet and Towbook SAs are included in all metrics.' },
    { title: 'Response Time Guardrails', text: 'Response times > 8 hours (480 min) or ≤ 0 are excluded as bad data. For the composite score, the cap is 24 hours (1440 min). These thresholds prevent data anomalies from skewing averages.' },
    { title: 'Survey Matching', text: 'Satisfaction surveys (Survey_Result__c) are matched to garages via the Work Order number. Surveys arrive days after the call, so recent periods may have incomplete survey data.' },
    { title: 'PTA (ERS_PTA__c)', text: 'Values of 0 and 999 are excluded from PTA analysis. 999 typically means "no ETA given" and 0 means the field was not populated. Valid PTA range: 1–998 minutes.' },
    { title: 'Caching', text: 'All data is cached in-memory with TTL: live ops data = 2 min, scorecard/performance = 30–60 min. Use Admin → Flush Cache to force a refresh.' },
  ]
  return (
    <div>
      <SectionHeader title="Key Business Rules & Filters" subtitle="Important rules that affect how data is processed and metrics are calculated." />
      <motion.div className="space-y-3 mt-4" variants={stagger(0.06)} initial="hidden" animate="show">
        {rules.map(r => (
          <motion.div key={r.title} className="glass rounded-xl p-4 border border-slate-700/20"
            variants={fadeUp} transition={{ type: 'spring', stiffness: 300, damping: 24 }}>
            <h4 className="font-semibold text-sm text-slate-200 mb-1.5">{r.title}</h4>
            <p className="text-xs text-slate-400 leading-relaxed">{r.text}</p>
          </motion.div>
        ))}
      </motion.div>
    </div>
  )
}

export function OpsRecommendationsSection() {
  const challenges = [
    {
      title: 'The Core Problem: Scheduler Was Built for Plumbers, Not Roadside',
      severity: 'critical',
      text: 'The FSL Enhanced Scheduler was designed for technicians (electricians, plumbers, HVAC) who start from home each morning. It calculates travel from the driver\'s home address (ServiceTerritoryMember), not their real-time GPS. AAA drivers are already on the road — their home address is irrelevant.',
      example: 'A driver 3 miles from a flat tire gets skipped because his home is 75 miles away. A driver 35 miles away gets sent because her home is only 5 miles from the call. The customer waits 40 extra minutes.',
    },
    {
      title: 'Fleet Drivers (89 drivers — use FSL App)',
      severity: 'warning',
      text: 'Fleet drivers run the FSL mobile app and most have real-time GPS when logged in. The problem: the Scheduler ignores their GPS and calculates from home address. Zero out of 501 ServiceTerritoryMember records have a street address populated.',
      fixes: [
        'Fill in garage/shop addresses on STM records (not actual home) — gives the Scheduler a better starting point',
        'Get the 41 fleet drivers without GPS to log into the FSL app at shift start',
        'Monitor GPS Health in Command Center to track compliance',
      ],
    },
    {
      title: 'Towbook Drivers (72 drivers — Towbook\'s Responsibility)',
      severity: 'warning',
      text: 'Towbook facilities handle their own driver assignment — when a call goes to a Towbook garage, their dispatchers pick the driver. We don\'t control this. However, we DO track whether Towbook sends the closest driver, using last-job-location as a GPS estimate. This gives AAA visibility into Towbook dispatch quality for contract and performance conversations.',
      fixes: [
        'Towbook closest-driver % is tracked in Command Center (Dispatch Insights panel)',
        'We use last completed SA location as GPS estimate (Towbook never sends real GPS)',
        'Focus your operational improvements on Fleet drivers — that\'s where you have control',
      ],
    },
    {
      title: 'Resource Absences: The Current Workaround',
      severity: 'info',
      text: 'Resource Absences remove untraceable drivers from the Scheduler\'s candidate pool. After configuring these in UAT on March 13, auto-assignment jumped from 0% to 83%. This doesn\'t fix the home-base problem — it just gives the Scheduler a smaller, cleaner pool to work with.',
    },
    {
      title: 'The 25-Minute Rule: AAA\'s Dispatch Philosophy',
      severity: 'info',
      text: 'AAA balances cost vs customer service. If the closest driver arrives within ~25 minutes of a faster driver, send the closest (saves fuel, mileage, truck wear). If the closest driver would be 25+ minutes later, send the faster driver — customer service wins.',
    },
    {
      title: 'Garage Over-Capacity Detection',
      severity: 'info',
      text: 'The system detects when a garage has more open calls than available drivers can handle. Available drivers = active drivers in the territory with fresh GPS (updated within 4 hours, meaning they\'re logged into the FSL app and working). Open calls ÷ available drivers gives the capacity ratio.',
      fixes: [
        'Normal (ratio < 1): More drivers than calls — garage is handling demand fine',
        'Busy (ratio 1-2): Every driver has a call, new ones will queue — shown as yellow "Busy" badge',
        'Over Capacity (ratio 2+, or no drivers): Calls stacking faster than drivers can handle — shown as red "Over Cap" badge with pulse animation',
        'Visible on both Garage Operations table (badge next to name + driver count under Open) and Command Center territory cards',
      ],
    },
  ]

  const actions = [
    { when: 'Today', what: 'Get 41 missing fleet drivers logged into the FSL mobile app', who: 'Operations / Fleet Managers' },
    { when: 'This Week', what: 'Fill garage addresses on ServiceTerritoryMember records (0 of 501 have addresses)', who: 'SF Admin / Data Team' },
    { when: 'This Month', what: 'Build smart recommendation layer using 4.25M GPS history records + 25-min rule', who: 'Dev Team (FSLAPP)' },
  ]

  const severityColors = {
    critical: 'border-red-500/30 bg-red-500/5',
    warning: 'border-amber-500/30 bg-amber-500/5',
    info: 'border-blue-500/30 bg-blue-500/5',
  }
  const severityBadge = {
    critical: 'bg-red-500/20 text-red-400',
    warning: 'bg-amber-500/20 text-amber-400',
    info: 'bg-blue-500/20 text-blue-400',
  }

  return (
    <div>
      <SectionHeader title="Operational Recommendations" subtitle="How to improve driver assignment — challenges by driver type and actionable fixes." />

      <motion.div className="space-y-4 mt-4" variants={stagger(0.07)} initial="hidden" animate="show">
        {challenges.map(c => (
          <motion.div key={c.title} className={clsx('rounded-xl p-4 border', severityColors[c.severity])}
            variants={fadeUp} transition={{ type: 'spring', stiffness: 260, damping: 22 }}>
            <div className="flex items-start gap-2 mb-2">
              <span className={clsx('text-[9px] uppercase font-bold px-1.5 py-0.5 rounded', severityBadge[c.severity])}>{c.severity}</span>
              <h4 className="font-semibold text-sm text-slate-200">{c.title}</h4>
            </div>
            <p className="text-xs text-slate-400 leading-relaxed mb-2">{c.text}</p>
            {c.example && (
              <div className="bg-slate-900/60 rounded-lg p-3 mb-2 border border-slate-700/30">
                <p className="text-[11px] text-slate-500 uppercase tracking-wider mb-1">Example</p>
                <p className="text-xs text-slate-300 leading-relaxed">{c.example}</p>
              </div>
            )}
            {c.fixes && (
              <div className="mt-2">
                <p className="text-[10px] text-emerald-400 uppercase tracking-wider mb-1 font-semibold">How to fix</p>
                <ul className="space-y-1">
                  {c.fixes.map((f, i) => (
                    <li key={i} className="flex items-start gap-2 text-xs text-slate-300">
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 mt-0.5 shrink-0" />
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </motion.div>
        ))}
      </motion.div>

      {/* Action Plan Table */}
      <div className="mt-6">
        <h3 className="text-sm font-bold text-white mb-3">Action Plan</h3>
        <div className="glass rounded-xl border border-slate-700/20 overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-700/30 text-slate-500 uppercase tracking-wider">
                <th className="text-left p-3">When</th>
                <th className="text-left p-3">What</th>
                <th className="text-left p-3">Who</th>
              </tr>
            </thead>
            <tbody>
              {actions.map(a => (
                <tr key={a.when} className="border-b border-slate-800/40 last:border-0">
                  <td className="p-3 text-amber-400 font-semibold whitespace-nowrap">{a.when}</td>
                  <td className="p-3 text-slate-300">{a.what}</td>
                  <td className="p-3 text-slate-500 whitespace-nowrap">{a.who}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Key Discovery */}
      <div className="mt-6 glass rounded-xl p-4 border border-emerald-500/20 bg-emerald-500/5">
        <h4 className="font-semibold text-sm text-emerald-400 mb-2">Key Discovery: 4.25M GPS History Records</h4>
        <p className="text-xs text-slate-400 leading-relaxed">
          ServiceResourceHistory contains 4.25 million GPS records tracking every position change for FSL app drivers.
          This enables calculating exactly which driver was closest at the time of each assignment — not just using
          current GPS (which changes by the minute). This is the foundation for building a true "closest driver" recommendation engine.
        </p>
      </div>

      {/* Full Report PDF */}
      <div className="mt-6 glass rounded-xl p-4 border border-brand-500/20 bg-brand-500/5">
        <div className="flex items-center justify-between">
          <div>
            <h4 className="font-semibold text-sm text-brand-400 mb-1">Fleet Optimization Report (PDF)</h4>
            <p className="text-xs text-slate-400">
              Full findings with statistics, data tables, and recommendations. Share with leadership and stakeholders.
            </p>
          </div>
          <a href="/data/Fleet_Optimization_Report.pdf" target="_blank" rel="noopener noreferrer"
            className="shrink-0 ml-4 px-4 py-2 rounded-lg bg-brand-600/20 text-brand-300 text-xs font-semibold
                       border border-brand-500/30 hover:bg-brand-600/30 transition-colors">
            Download PDF
          </a>
        </div>
      </div>
    </div>
  )
}

const SEV = {
  critical: { bg: 'bg-red-950/30', border: 'border-red-800/40', text: 'text-red-400', icon: XCircle, label: 'Critical' },
  warn:     { bg: 'bg-amber-950/20', border: 'border-amber-800/30', text: 'text-amber-400', icon: AlertTriangle, label: 'Warning' },
  ok:       { bg: 'bg-emerald-950/20', border: 'border-emerald-800/30', text: 'text-emerald-400', icon: CheckCircle2, label: 'OK' },
}
function SevBadge({ severity }) {
  const s = SEV[severity] || SEV.ok
  const Icon = s.icon
  return (
    <span className={clsx('inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border', s.bg, s.border, s.text)}>
      <Icon className="w-3 h-3" />{s.label}
    </span>
  )
}
function QualityBar({ pct, severity }) {
  const color = severity === 'critical' ? 'bg-red-500' : severity === 'warn' ? 'bg-amber-500' : 'bg-emerald-500'
  return (
    <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
      <div className={clsx('h-full rounded-full transition-all', color)} style={{ width: `${Math.min(pct || 0, 100)}%` }} />
    </div>
  )
}
export function QualitySection() {
  const [quality, setQuality] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [groupFilter, setGroupFilter] = useState('all')

  useEffect(() => {
    if (!quality && !loading) {
      setLoading(true)
      fetchDataQuality()
        .then(setQuality)
        .catch(e => setError(e.response?.data?.detail || e.message))
        .finally(() => setLoading(false))
    }
  }, [])

  const qualityGroups = useMemo(() => {
    if (!quality) return []
    const groups = {}
    for (const f of quality.fields) {
      if (!groups[f.group]) groups[f.group] = []
      groups[f.group].push(f)
    }
    return Object.entries(groups).map(([name, fields]) => ({ name, fields }))
  }, [quality])

  const filteredQuality = useMemo(() => {
    if (groupFilter === 'all') return qualityGroups
    if (groupFilter === 'issues') return qualityGroups.map(g => ({ ...g, fields: g.fields.filter(f => f.severity !== 'ok') })).filter(g => g.fields.length > 0)
    return qualityGroups.filter(g => g.name === groupFilter)
  }, [qualityGroups, groupFilter])

  const doRefresh = () => {
    setQuality(null); setLoading(true); setError(null)
    refreshDataQuality().then(setQuality).catch(e => setError(e.response?.data?.detail || e.message)).finally(() => setLoading(false))
  }
  return (
    <div>
      <SectionHeader title="Data Quality Audit" subtitle="Live field-level quality analysis from Salesforce data." />
      {loading && (
        <div className="flex items-center justify-center py-20 gap-3">
          <Loader2 className="w-6 h-6 animate-spin text-brand-400" />
          <span className="text-slate-400">Auditing field quality...</span>
        </div>
      )}
      {error && !loading && (
        <div className="rounded-xl bg-red-950/30 border border-red-800/30 p-4 text-red-300 text-sm mt-4">
          Failed to load data quality: {error}
        </div>
      )}
      {quality && !loading && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mt-4 mb-5">
            <div className="glass rounded-xl p-4">
              <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Period</div>
              <div className="text-sm font-bold text-white">{quality.period}</div>
            </div>
            <div className="glass rounded-xl p-4">
              <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Total SAs</div>
              <div className="text-lg font-bold text-white">{quality.total_sas?.toLocaleString()}</div>
            </div>
            <div className={clsx('glass rounded-xl p-4', quality.summary?.critical_issues > 0 && 'border border-red-800/30')}>
              <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Critical</div>
              <div className={clsx('text-lg font-bold', quality.summary?.critical_issues > 0 ? 'text-red-400' : 'text-emerald-400')}>
                {quality.summary?.critical_issues || 0}
              </div>
            </div>
            <div className="glass rounded-xl p-4">
              <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Warnings</div>
              <div className={clsx('text-lg font-bold', quality.summary?.warnings > 0 ? 'text-amber-400' : 'text-slate-500')}>
                {quality.summary?.warnings || 0}
              </div>
            </div>
            <div className="glass rounded-xl p-4">
              <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Healthy</div>
              <div className="text-lg font-bold text-emerald-400">{quality.summary?.healthy || 0}</div>
            </div>
          </div>
          {/* Filter bar */}
          <div className="flex items-center gap-2 mb-4 flex-wrap">
            <Filter className="w-3.5 h-3.5 text-slate-500" />
            {[{ key: 'all', label: 'All Fields' }, { key: 'issues', label: 'Issues Only' },
              ...qualityGroups.map(g => ({ key: g.name, label: g.name }))
            ].map(f => (
              <button key={f.key} onClick={() => setGroupFilter(f.key)}
                className={clsx('px-2.5 py-1 rounded-lg text-[10px] font-medium transition-all',
                  groupFilter === f.key
                    ? 'bg-brand-600/30 text-brand-300 border border-brand-500/30'
                    : 'text-slate-500 hover:text-white hover:bg-slate-800 border border-transparent'
                )}>
                {f.label}
              </button>
            ))}
            <button onClick={doRefresh} disabled={loading}
              className="ml-auto flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[10px] text-slate-500 hover:text-white hover:bg-slate-800 transition-all disabled:opacity-50">
              <RefreshCw className={clsx('w-3 h-3', loading && 'animate-spin')} /> Refresh
            </button>
          </div>
          {/* Quality cards */}
          <div className="space-y-4">
            {filteredQuality.map(group => (
              <div key={group.name} className="glass rounded-xl overflow-hidden">
                <div className="px-5 py-3 border-b border-slate-800/60">
                  <h3 className="text-sm font-semibold text-slate-200">{group.name}</h3>
                </div>
                <div className="divide-y divide-slate-800/30">
                  {group.fields.map(f => (
                    <div key={f.field} className={clsx('px-5 py-4', f.severity === 'critical' && 'bg-red-950/5')}>
                      <div className="flex items-start gap-4">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1.5">
                            <span className="font-semibold text-white text-sm">{f.label}</span>
                            <SevBadge severity={f.severity} />
                          </div>
                          <div className="font-mono text-[11px] text-brand-300/70 mb-2">{f.field}</div>
                          <div className="text-xs text-slate-400 leading-relaxed mb-2">{f.description}</div>
                          <div className="text-xs text-slate-300 bg-slate-800/40 rounded-lg px-3 py-2 mb-2">
                            <span className="text-slate-500 font-medium">Issues: </span>{f.issues}
                          </div>
                          <div className="text-xs text-slate-400">
                            <span className="text-slate-500 font-medium">Impact: </span>{f.impact}
                          </div>
                        </div>
                        <div className="w-48 shrink-0 space-y-2">
                          <div className="flex justify-between items-baseline">
                            <span className="text-[10px] text-slate-500">Populated</span>
                            <span className={clsx('text-sm font-bold', f.pct >= 90 ? 'text-emerald-400' : f.pct >= 70 ? 'text-amber-400' : 'text-red-400')}>
                              {f.pct != null ? `${f.pct}%` : 'N/A'}
                            </span>
                          </div>
                          <QualityBar pct={f.pct} severity={f.severity} />
                          <div className="text-[10px] text-slate-600">
                            {f.populated?.toLocaleString()} of {f.total?.toLocaleString()}
                          </div>
                          {f.detail?.breakdown && (
                            <div className="pt-2 border-t border-slate-800/40 space-y-1">
                              {Object.entries(f.detail.breakdown).map(([k, v]) => (
                                <div key={k} className="flex justify-between text-[10px]">
                                  <span className="text-slate-500">{k}</span>
                                  <span className="text-slate-400">{v?.toLocaleString()}</span>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
