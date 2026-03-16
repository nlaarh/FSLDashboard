import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import {
  BookOpen, Calculator, Database, Target, ChevronDown, ChevronUp,
  BarChart3, Clock, CheckCircle2, ThumbsUp, TrendingDown, Zap, XCircle,
  ArrowRightLeft, Search, ShieldCheck, AlertTriangle, Share2,
  ArrowUpDown, Filter, RefreshCw, Loader2, HelpCircle, Radio,
  LayoutDashboard, ListOrdered, CloudSun, Layers, Workflow,
  MessageCircle, Send, X, Bot, User, ArrowLeft, Phone, MapPin,
  Truck, Users, Award, ChevronRight, Wrench,
} from 'lucide-react'
import { clsx } from 'clsx'
import { motion, AnimatePresence } from 'framer-motion'
import { fetchDataQuality, refreshDataQuality, askChatbot, fetchFeatures } from '../api'

/* ── Framer Motion helpers ── */
const fadeUp = { hidden: { opacity: 0, y: 18 }, show: { opacity: 1, y: 0 } }
const fadeSide = { hidden: { opacity: 0, x: -20 }, show: { opacity: 1, x: 0 } }
const stagger = (staggerChildren = 0.06) => ({
  hidden: {},
  show: { transition: { staggerChildren } },
})
const collapseVariants = {
  hidden: { opacity: 0, y: -8 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.3, ease: 'easeOut' } },
  exit: { opacity: 0, y: -8, transition: { duration: 0.2 } },
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION DEFINITIONS
// ═══════════════════════════════════════════════════════════════════════════════

const SECTIONS = [
  { id: 'howitworks', label: 'How It Works',          icon: Workflow,       desc: 'End-to-end operations guide — territories, dispatch, fleet vs contractors, scoring, and the full call lifecycle.' },
  { id: 'overview',   label: 'Dispatch Manager Guide', icon: BookOpen,      desc: 'Page-by-page guide — what to look for, how to read the data, and when to take action.' },
  { id: 'metrics',    label: 'Metric Definitions',   icon: Calculator,     desc: 'Every metric — what it measures, how it is calculated, and which Salesforce fields are used.' },
  { id: 'scoring',    label: 'How Garages Are Rated', icon: Target,         desc: 'Plain English guide to how the system scores and grades each garage from A to F.' },
  { id: 'data',       label: 'Data & Model',         icon: Database,       desc: 'Searchable field dictionary and entity-relationship diagram — all Salesforce objects in one place.' },
  { id: 'quality',    label: 'Data Quality',         icon: ShieldCheck,    desc: 'Live field-level quality audit with severity ratings and recommendations.' },
  { id: 'rules',      label: 'Business Rules',       icon: AlertTriangle,  desc: 'Key filters, guardrails, and exclusions that affect metric calculations.' },
  { id: 'ops',        label: 'Ops Recommendations',   icon: Truck,          desc: 'How to improve driver assignment — Fleet vs Towbook challenges and actionable fixes.' },
]

// ═══════════════════════════════════════════════════════════════════════════════
// METRIC DEFINITIONS DATA
// ═══════════════════════════════════════════════════════════════════════════════

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

// ── Composite Score ──
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

const GRADES = [
  { grade: 'A', range: '90 – 100', color: 'text-emerald-400 bg-emerald-950/40 border-emerald-700/30' },
  { grade: 'B', range: '80 – 89',  color: 'text-blue-400 bg-blue-950/40 border-blue-700/30' },
  { grade: 'C', range: '70 – 79',  color: 'text-amber-400 bg-amber-950/40 border-amber-700/30' },
  { grade: 'D', range: '60 – 69',  color: 'text-orange-400 bg-orange-950/40 border-orange-700/30' },
  { grade: 'F', range: '0 – 59',   color: 'text-red-400 bg-red-950/40 border-red-700/30' },
]

// ── Page Guide Data ──
const PAGES = [
  { name: 'Command Center', route: '/', icon: Radio, desc: 'Real-time operational dashboard showing all territories, open calls, driver status, and alerts.' },
  { name: 'Garages', route: '/garages', icon: LayoutDashboard, desc: 'All garage territories with composite score, grade, and key metrics. Click a garage for deep-dive.' },
  { name: 'Queue Board', route: '/queue', icon: ListOrdered, desc: 'Live dispatch queue — open SAs waiting for assignment with driver recommendations and cascade status.' },
  { name: 'PTA Advisor', route: '/pta', icon: Clock, desc: 'Analyzes Promised Time of Arrival patterns. Identifies garages over-promising or under-delivering on ETAs.' },
  { name: 'Forecast', route: '/forecast', icon: CloudSun, desc: '16-day demand forecast using day-of-week patterns and weather data for staffing planning.' },
  { name: 'Territory Matrix', route: '/matrix', icon: ArrowRightLeft, desc: 'Priority matrix advisor — cascade chain effectiveness and zone primary swap recommendations.' },
]

// ═══════════════════════════════════════════════════════════════════════════════
// LANDING CARDS — shown when no section is selected
// ═══════════════════════════════════════════════════════════════════════════════

function LandingCards({ onSelect }) {
  return (
    <div>
      <motion.div className="text-center mb-8" initial={{ opacity: 0, y: -12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
        <HelpCircle className="w-10 h-10 text-brand-400 mx-auto mb-3" />
        <h1 className="text-2xl font-bold text-white mb-2">Help Center</h1>
        <p className="text-sm text-slate-400 max-w-lg mx-auto">
          Everything you need to understand FSL App — metrics, scoring, data fields, quality audits, and business rules.
        </p>
      </motion.div>
      <motion.div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 max-w-5xl mx-auto"
        variants={stagger(0.07)} initial="hidden" animate="show">
        {SECTIONS.map(s => (
          <motion.button key={s.id} onClick={() => onSelect(s.id)} variants={fadeUp}
            transition={{ type: 'spring', stiffness: 260, damping: 22 }}
            whileHover={{ scale: 1.03, y: -3 }} whileTap={{ scale: 0.97 }}
            className="group glass rounded-xl p-5 border border-slate-700/20 hover:border-brand-500/40 transition-colors text-left">
            <div className="w-10 h-10 rounded-xl bg-brand-600/10 border border-brand-500/20 flex items-center justify-center mb-3 group-hover:bg-brand-600/20 transition-colors">
              <s.icon className="w-5 h-5 text-brand-400" />
            </div>
            <h3 className="font-semibold text-sm text-white mb-1">{s.label}</h3>
            <p className="text-[11px] text-slate-500 leading-relaxed">{s.desc}</p>
          </motion.button>
        ))}
      </motion.div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// SUB-COMPONENTS — Sections
// ═══════════════════════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════════════
// HOW IT WORKS — End-to-end Operations Guide
// ═══════════════════════════════════════════════════════════════════════════════

/* ── Reusable visual building blocks ── */

function FieldTag({ name, className }) {
  return (
    <code className={clsx('inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono bg-brand-950/40 text-brand-300 border border-brand-800/30', className)}>
      {name}
    </code>
  )
}

function FlowStep({ number, color, icon: Icon, title, children }) {
  return (
    <motion.div className="flex gap-4"
      initial={{ opacity: 0, x: -16 }} animate={{ opacity: 1, x: 0 }}
      transition={{ type: 'spring', stiffness: 300, damping: 24, delay: (number - 1) * 0.1 }}>
      <div className="flex flex-col items-center">
        <motion.div className={clsx('w-10 h-10 rounded-xl flex items-center justify-center shrink-0 border', color)}
          initial={{ scale: 0 }} animate={{ scale: 1 }}
          transition={{ type: 'spring', stiffness: 400, damping: 15, delay: (number - 1) * 0.1 + 0.05 }}>
          <Icon className="w-5 h-5" />
        </motion.div>
        <div className="w-0.5 flex-1 bg-slate-800 mt-2" />
      </div>
      <div className="pb-8 flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-600">Step {number}</span>
          <h3 className="text-sm font-bold text-white">{title}</h3>
        </div>
        <div className="text-xs text-slate-400 leading-relaxed space-y-2">
          {children}
        </div>
      </div>
    </motion.div>
  )
}

function InfoCard({ title, icon: Icon, color, children }) {
  return (
    <div className="glass rounded-xl p-4 border border-slate-700/20">
      <div className="flex items-center gap-2 mb-3">
        <div className={clsx('w-8 h-8 rounded-lg flex items-center justify-center border', color)}>
          <Icon className="w-4 h-4" />
        </div>
        <h4 className="font-semibold text-sm text-white">{title}</h4>
      </div>
      <div className="text-xs text-slate-400 leading-relaxed space-y-2">{children}</div>
    </div>
  )
}

function HowItWorksSection() {
  const [expandedTopic, setExpandedTopic] = useState(null)
  const [videoUrl, setVideoUrl] = useState('')
  const toggle = (id) => setExpandedTopic(prev => prev === id ? null : id)

  useEffect(() => {
    fetchFeatures().then(f => setVideoUrl(f.help_video_url || '')).catch(() => {})
  }, [])

  return (
    <div>
      <SectionHeader
        title="How It Works"
        subtitle="End-to-end guide to AAA WNYC Field Service operations — from member call to garage scorecard."
      />

      {/* ═══ VIDEO OVERVIEW ═══ */}
      {videoUrl && (() => {
        const m = videoUrl.match(/(?:youtu\.be\/|youtube\.com\/(?:watch\?v=|embed\/|shorts\/))([a-zA-Z0-9_-]{11})/)
        const vid = m ? m[1] : null
        if (!vid) return null
        return (
          <a href={videoUrl} target="_blank" rel="noopener noreferrer"
            className="block glass rounded-xl border border-slate-700/20 p-4 mt-4 mb-4 hover:border-brand-500/30 transition-all group">
            <div className="flex items-center gap-4">
              <div className="relative flex-shrink-0 rounded-lg overflow-hidden w-48 h-28 bg-slate-800">
                <img src={`https://img.youtube.com/vi/${vid}/hqdefault.jpg`} alt="FleetPulse Overview"
                  className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" />
                <div className="absolute inset-0 flex items-center justify-center bg-black/30 group-hover:bg-black/10 transition-colors">
                  <div className="w-12 h-12 rounded-full bg-red-600 flex items-center justify-center shadow-lg">
                    <svg className="w-5 h-5 text-white ml-0.5" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
                  </div>
                </div>
              </div>
              <div>
                <h3 className="text-sm font-bold text-white group-hover:text-brand-300 transition-colors">Watch: FleetPulse Overview</h3>
                <p className="text-[11px] text-slate-500 mt-1">See how the system works end-to-end — from member call to garage scoring.</p>
                <span className="text-[10px] text-brand-400 mt-2 inline-block">youtube.com — Click to watch</span>
              </div>
            </div>
          </a>
        )
      })()}

      {/* ═══ VISUAL OVERVIEW — Call Lifecycle Pipeline ═══ */}
      <div className="glass rounded-xl border border-slate-700/20 p-5 mt-4 mb-6 overflow-x-auto">
        <h3 className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-4">Call Lifecycle Pipeline</h3>
        <motion.div className="flex items-start gap-0 min-w-[900px]" variants={stagger(0.08)} initial="hidden" animate="show">
          {[
            { label: 'Member Calls', sub: 'SA Created', color: 'bg-blue-500', fields: ['CreatedDate', 'Lat/Long', 'WorkTypeId'] },
            { label: 'Zone Identified', sub: 'Spotted Territory', color: 'bg-indigo-500', fields: ['ERS_Parent_Territory__c', 'Priority Matrix'] },
            { label: 'Auto-Dispatch', sub: 'Primary Garage', color: 'bg-violet-500', fields: ['ServiceTerritoryId', 'ERS_Auto_Assign__c'] },
            { label: 'Accepted?', sub: 'Accept or Decline', color: 'bg-amber-500', fields: ['ERS_Facility_Decline_Reason__c'] },
            { label: 'Driver Assigned', sub: 'Scheduled', color: 'bg-emerald-500', fields: ['SchedStartTime', 'AssignedResource', 'ERS_PTA__c'] },
            { label: 'En Route', sub: 'Driver Traveling', color: 'bg-teal-500', fields: ['FSL GPS', 'ERS_Dispatch_Method__c'] },
            { label: 'On Scene', sub: 'Driver Arrived', color: 'bg-green-500', fields: ['ActualStartTime', 'SA History'] },
            { label: 'Completed', sub: 'Job Done', color: 'bg-emerald-600', fields: ['ActualEndTime', 'Status'] },
            { label: 'Scored', sub: 'Metrics Updated', color: 'bg-brand-500', fields: ['Composite Score', 'Survey_Result__c'] },
          ].map((step, i, arr) => (
            <motion.div key={step.label} className="flex items-start flex-1 min-w-0" variants={fadeUp}
              transition={{ type: 'spring', stiffness: 300, damping: 24 }}>
              <div className="flex flex-col items-center text-center w-full">
                <motion.div className={clsx('w-9 h-9 rounded-full flex items-center justify-center text-white text-xs font-bold shadow-lg', step.color)}
                  initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ type: 'spring', stiffness: 400, damping: 15, delay: i * 0.08 + 0.1 }}>
                  {i + 1}
                </motion.div>
                <div className="mt-2 font-semibold text-[11px] text-white">{step.label}</div>
                <div className="text-[9px] text-slate-500 mt-0.5">{step.sub}</div>
                <div className="mt-2 flex flex-col gap-1 items-center">
                  {step.fields.map(f => (
                    <code key={f} className="text-[8px] text-brand-300/70 bg-slate-900/60 rounded px-1.5 py-0.5 whitespace-nowrap">{f}</code>
                  ))}
                </div>
              </div>
              {i < arr.length - 1 && (
                <motion.div className="flex items-center pt-3 px-0.5 shrink-0"
                  initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.08 + 0.15 }}>
                  <ChevronRight className="w-4 h-4 text-slate-700" />
                </motion.div>
              )}
            </motion.div>
          ))}
        </motion.div>
      </div>

      {/* ═══ TOPIC 1: Territory & Zone Structure ═══ */}
      <div className="space-y-3 mb-6">
        <button onClick={() => toggle('territory')}
          className="w-full flex items-center gap-3 glass rounded-xl p-4 border border-slate-700/20 hover:border-brand-500/30 transition-all text-left">
          <div className="w-10 h-10 rounded-xl bg-indigo-600/15 border border-indigo-500/25 flex items-center justify-center shrink-0">
            <MapPin className="w-5 h-5 text-indigo-400" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="font-bold text-sm text-white">1. Territory & Zone Structure</h3>
            <p className="text-[11px] text-slate-500 mt-0.5">How garages, zones, and cascade chains are organized</p>
          </div>
          <ChevronDown className={clsx('w-4 h-4 text-slate-500 transition-transform', expandedTopic === 'territory' && 'rotate-180')} />
        </button>

        <AnimatePresence initial={false}>
        {expandedTopic === 'territory' && (
          <motion.div className="ml-4 pl-4 border-l-2 border-indigo-800/30 space-y-4"
            variants={collapseVariants} initial="hidden" animate="visible" exit="exit">
            {/* Territory Visual */}
            <div className="glass rounded-xl p-5 border border-slate-700/20 overflow-x-auto">
              <div className="min-w-[700px]">
                <svg width="700" height="280" viewBox="0 0 700 280">
                  {/* Zone polygon */}
                  <polygon points="50,40 350,40 380,140 320,220 80,220 20,140" fill="#312e81" fillOpacity="0.15" stroke="#6366f1" strokeWidth="1.5" strokeDasharray="6 3" />
                  <text x="180" y="25" fill="#818cf8" fontSize="11" fontWeight="bold">ZONE A (Spotted Territory)</text>

                  {/* Primary garage */}
                  <rect x="100" y="70" width="200" height="60" rx="10" fill="#0f172a" stroke="#8b5cf6" strokeWidth="2" />
                  <circle cx="120" cy="100" r="10" fill="#8b5cf6" />
                  <text x="122" y="104" fill="white" fontSize="9" fontWeight="bold" textAnchor="middle">1</text>
                  <text x="140" y="92" fill="white" fontSize="11" fontWeight="bold">Tonawanda Towing</text>
                  <text x="140" y="106" fill="#94a3b8" fontSize="9">Primary Garage (Rank 1)</text>
                  <text x="140" y="120" fill="#818cf8" fontSize="8" fontFamily="monospace">ServiceTerritory.Id = '0HhXX...'</text>

                  {/* Cascade arrow to secondary */}
                  <line x1="300" y1="100" x2="400" y2="100" stroke="#f59e0b" strokeWidth="1.5" strokeDasharray="4 2" markerEnd="url(#arrowAmber)" />
                  <text x="350" y="90" fill="#f59e0b" fontSize="8" textAnchor="middle">DECLINE</text>

                  {/* Secondary garage */}
                  <rect x="420" y="70" width="200" height="60" rx="10" fill="#0f172a" stroke="#6366f1" strokeWidth="1.5" />
                  <circle cx="440" cy="100" r="10" fill="#6366f1" />
                  <text x="442" y="104" fill="white" fontSize="9" fontWeight="bold" textAnchor="middle">2</text>
                  <text x="460" y="92" fill="white" fontSize="11" fontWeight="bold">AAA Buffalo Fleet</text>
                  <text x="460" y="106" fill="#94a3b8" fontSize="9">Backup Garage (Rank 2)</text>

                  {/* Cascade arrow to tertiary */}
                  <line x1="520" y1="130" x2="520" y2="170" stroke="#f59e0b" strokeWidth="1.5" strokeDasharray="4 2" markerEnd="url(#arrowAmber)" />
                  <text x="545" y="155" fill="#f59e0b" fontSize="8">DECLINE</text>

                  {/* Tertiary garage */}
                  <rect x="420" y="180" width="200" height="60" rx="10" fill="#0f172a" stroke="#64748b" strokeWidth="1.5" />
                  <circle cx="440" cy="210" r="10" fill="#64748b" />
                  <text x="442" y="214" fill="white" fontSize="9" fontWeight="bold" textAnchor="middle">3</text>
                  <text x="460" y="202" fill="white" fontSize="11" fontWeight="bold">NFB Emergency</text>
                  <text x="460" y="216" fill="#94a3b8" fontSize="9">Tertiary Garage (Rank 3)</text>

                  {/* Field callouts */}
                  <rect x="40" y="240" width="180" height="20" rx="4" fill="#1e1b4b" stroke="#4338ca" strokeWidth="0.5" />
                  <text x="130" y="254" fill="#818cf8" fontSize="8" fontFamily="monospace" textAnchor="middle">ERS_Territory_Priority_Matrix__c</text>

                  <rect x="260" y="240" width="180" height="20" rx="4" fill="#1e1b4b" stroke="#4338ca" strokeWidth="0.5" />
                  <text x="350" y="254" fill="#818cf8" fontSize="8" fontFamily="monospace" textAnchor="middle">FSL__Polygon__c (KML boundary)</text>

                  <rect x="480" y="240" width="180" height="20" rx="4" fill="#451a03" stroke="#92400e" strokeWidth="0.5" />
                  <text x="570" y="254" fill="#fbbf24" fontSize="8" fontFamily="monospace" textAnchor="middle">ERS_Facility_Decline_Reason__c</text>

                  <defs>
                    <marker id="arrowAmber" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="6" markerHeight="6" orient="auto">
                      <path d="M0,0 L10,5 L0,10 z" fill="#f59e0b" />
                    </marker>
                  </defs>
                </svg>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="glass rounded-xl p-4 border border-slate-700/20">
                <h4 className="font-semibold text-xs text-white mb-2">What is a Territory?</h4>
                <p className="text-xs text-slate-400 leading-relaxed">
                  Each garage is a <FieldTag name="ServiceTerritory" /> in Salesforce. It has a physical address
                  (<FieldTag name="Street" />, <FieldTag name="City" />), GPS coordinates (<FieldTag name="Latitude" />, <FieldTag name="Longitude" />),
                  and a geographic boundary drawn as a polygon (<FieldTag name="FSL__Polygon__c.FSL__KML__c" />).
                  Each territory is linked to a business entity via <FieldTag name="ERS_Facility_Account__r" /> (Account).
                </p>
              </div>
              <div className="glass rounded-xl p-4 border border-slate-700/20">
                <h4 className="font-semibold text-xs text-white mb-2">What is a Zone & Cascade Chain?</h4>
                <p className="text-xs text-slate-400 leading-relaxed">
                  The <FieldTag name="ERS_Territory_Priority_Matrix__c" /> defines which garages serve which zones, in
                  what priority order, and for which <FieldTag name="WorkType" />. When a member calls from Zone A, the
                  system dispatches to the Rank 1 (primary) garage. If that garage declines
                  (<FieldTag name="ERS_Facility_Decline_Reason__c" /> is set), it cascades to Rank 2, then Rank 3.
                  The member's spotted zone is stored in <FieldTag name="ERS_Parent_Territory__c" />.
                </p>
              </div>
            </div>
          </motion.div>
        )}
        </AnimatePresence>
      </div>

      {/* ═══ TOPIC 2: Fleet vs Contractors ═══ */}
      <div className="space-y-3 mb-6">
        <button onClick={() => toggle('fleet')}
          className="w-full flex items-center gap-3 glass rounded-xl p-4 border border-slate-700/20 hover:border-brand-500/30 transition-all text-left">
          <div className="w-10 h-10 rounded-xl bg-emerald-600/15 border border-emerald-500/25 flex items-center justify-center shrink-0">
            <Truck className="w-5 h-5 text-emerald-400" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="font-bold text-sm text-white">2. Fleet vs Contractors (Towbook)</h3>
            <p className="text-[11px] text-slate-500 mt-0.5">Two dispatch systems, same metrics — how fleet and contractor calls differ</p>
          </div>
          <ChevronDown className={clsx('w-4 h-4 text-slate-500 transition-transform', expandedTopic === 'fleet' && 'rotate-180')} />
        </button>

        <AnimatePresence initial={false}>
        {expandedTopic === 'fleet' && (
          <motion.div className="ml-4 pl-4 border-l-2 border-emerald-800/30 space-y-4"
            variants={collapseVariants} initial="hidden" animate="visible" exit="exit">
            {/* Side-by-side comparison */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="glass rounded-xl border-2 border-blue-800/30 overflow-hidden">
                <div className="bg-blue-950/30 px-4 py-3 border-b border-blue-800/20">
                  <div className="flex items-center gap-2">
                    <div className="w-3 h-3 rounded-full bg-blue-500" />
                    <span className="font-bold text-sm text-blue-300">Internal Fleet</span>
                  </div>
                  <code className="text-[9px] text-blue-400/70 mt-1 block">ERS_Dispatch_Method__c = 'Field Services'</code>
                </div>
                <div className="p-4 space-y-3 text-xs text-slate-400">
                  <div>
                    <span className="text-slate-200 font-medium">Drivers:</span> AAA employees with the FSL mobile app.
                    Each driver is a <FieldTag name="ServiceResource" /> with <FieldTag name="IsActive" /> = true
                    and <FieldTag name="ResourceType" /> = 'T' (Technician).
                  </div>
                  <div>
                    <span className="text-slate-200 font-medium">GPS:</span> Real-time location from the FSL mobile app.
                    <FieldTag name="LastKnownLatitude" /> and <FieldTag name="LastKnownLongitude" /> update live
                    on <FieldTag name="ServiceResource" />.
                  </div>
                  <div>
                    <span className="text-slate-200 font-medium">Trucks:</span> <FieldTag name="Asset" /> (RecordType = 'ERS Truck')
                    linked to driver via <FieldTag name="ERS_Driver__c" />. Truck capabilities
                    (<FieldTag name="ERS_Truck_Capabilities__c" />) must match the call's work type.
                  </div>
                  <div>
                    <span className="text-slate-200 font-medium">Arrival Time:</span> <FieldTag name="ActualStartTime" /> is set
                    when driver taps "Arrived" in the mobile app — <span className="text-emerald-400 font-semibold">this is the real arrival</span>.
                  </div>
                  <div>
                    <span className="text-slate-200 font-medium">Scheduling:</span> Auto-dispatched by the FSL optimization engine
                    using <FieldTag name="FSL__Scheduling_Policy__c" /> rules and goals.
                    <FieldTag name="ERS_Auto_Assign__c" /> = true.
                  </div>
                </div>
              </div>

              <div className="glass rounded-xl border-2 border-orange-800/30 overflow-hidden">
                <div className="bg-orange-950/30 px-4 py-3 border-b border-orange-800/20">
                  <div className="flex items-center gap-2">
                    <div className="w-3 h-3 rounded-full bg-orange-500" />
                    <span className="font-bold text-sm text-orange-300">Towbook Contractors</span>
                  </div>
                  <code className="text-[9px] text-orange-400/70 mt-1 block">ERS_Dispatch_Method__c = 'Towbook'</code>
                </div>
                <div className="p-4 space-y-3 text-xs text-slate-400">
                  <div>
                    <span className="text-slate-200 font-medium">Drivers:</span> External contractors dispatched through
                    the Towbook system. Identified by <FieldTag name="Off_Platform_Driver__c" /> (lookup to ServiceResource)
                    and <FieldTag name="Off_Platform_Truck_Id__c" />.
                  </div>
                  <div>
                    <span className="text-slate-200 font-medium">GPS:</span> No real-time tracking in Salesforce.
                    Location comes from the Towbook platform, not the FSL mobile app.
                  </div>
                  <div>
                    <span className="text-slate-200 font-medium">Trucks:</span> Contractor-owned vehicles. Capabilities
                    are managed in Towbook, not Salesforce Asset records.
                  </div>
                  <div>
                    <span className="text-slate-200 font-medium">Arrival Time:</span> <FieldTag name="ActualStartTime" /> is
                    written by the "Integrations Towbook" user at completion —
                    <span className="text-amber-400 font-semibold">this is NOT the real arrival</span>. The actual arrival
                    is captured in <FieldTag name="ServiceAppointmentHistory" /> when Status → "On Location".
                  </div>
                  <div>
                    <span className="text-slate-200 font-medium">PTA:</span> <FieldTag name="ERS_PTA__c" /> is entered
                    by the Towbook dispatcher — often a rough estimate, less reliable than fleet PTA.
                  </div>
                </div>
              </div>
            </div>

            <div className="glass rounded-xl p-4 border border-amber-800/20 bg-amber-950/10">
              <div className="flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                <div>
                  <h4 className="font-semibold text-xs text-amber-300 mb-1">Key Distinction for Metrics</h4>
                  <p className="text-xs text-slate-400 leading-relaxed">
                    Both fleet and Towbook calls count toward ALL metrics (response time, SLA, completion rate).
                    The field <FieldTag name="ERS_Dispatch_Method__c" /> distinguishes them for the Dispatch Mix chart.
                    For Towbook, the app uses SA History "On Location" timestamp as the real arrival instead of ActualStartTime.
                  </p>
                </div>
              </div>
            </div>
          </motion.div>
        )}
        </AnimatePresence>
      </div>

      {/* ═══ TOPIC 3: Call Creation & Dispatch ═══ */}
      <div className="space-y-3 mb-6">
        <button onClick={() => toggle('dispatch')}
          className="w-full flex items-center gap-3 glass rounded-xl p-4 border border-slate-700/20 hover:border-brand-500/30 transition-all text-left">
          <div className="w-10 h-10 rounded-xl bg-violet-600/15 border border-violet-500/25 flex items-center justify-center shrink-0">
            <Phone className="w-5 h-5 text-violet-400" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="font-bold text-sm text-white">3. Call Creation & Dispatch Logic</h3>
            <p className="text-[11px] text-slate-500 mt-0.5">From member phone call to driver assignment — step by step</p>
          </div>
          <ChevronDown className={clsx('w-4 h-4 text-slate-500 transition-transform', expandedTopic === 'dispatch' && 'rotate-180')} />
        </button>

        <AnimatePresence initial={false}>
        {expandedTopic === 'dispatch' && (
          <motion.div className="ml-4 pl-4 border-l-2 border-violet-800/30 space-y-1"
            variants={collapseVariants} initial="hidden" animate="visible" exit="exit">
            <FlowStep number={1} color="bg-blue-950/40 border-blue-700/30 text-blue-400" icon={Phone} title="Member Calls AAA">
              <p>
                A member is stranded and calls AAA. The call center creates a <FieldTag name="WorkOrder" /> and a child
                <FieldTag name="ServiceAppointment" /> in Salesforce. The SA captures:
              </p>
              <div className="grid grid-cols-2 gap-2 mt-2">
                <div className="bg-slate-900/40 rounded-lg p-2">
                  <span className="text-slate-500 text-[10px]">Location:</span>
                  <div className="mt-1 space-y-0.5">
                    <div><FieldTag name="Latitude" /> <FieldTag name="Longitude" /> — GPS pin</div>
                    <div><FieldTag name="Street" /> <FieldTag name="City" /> <FieldTag name="State" /> — address</div>
                  </div>
                </div>
                <div className="bg-slate-900/40 rounded-lg p-2">
                  <span className="text-slate-500 text-[10px]">Call Details:</span>
                  <div className="mt-1 space-y-0.5">
                    <div><FieldTag name="CreatedDate" /> — clock starts NOW</div>
                    <div><FieldTag name="WorkTypeId" /> — Tow, Battery, Tire, etc.</div>
                    <div><FieldTag name="Status" /> — initially "None" or "Assigned"</div>
                  </div>
                </div>
              </div>
            </FlowStep>

            <FlowStep number={2} color="bg-indigo-950/40 border-indigo-700/30 text-indigo-400" icon={MapPin} title="Zone Identification">
              <p>
                The system uses the member's GPS (<FieldTag name="Latitude" />, <FieldTag name="Longitude" />) to determine
                which zone they are in. The zone is recorded as <FieldTag name="ERS_Parent_Territory__c" /> (the "spotted territory").
                The <FieldTag name="ERS_Territory_Priority_Matrix__c" /> is then consulted to find the cascade chain
                for that zone and work type.
              </p>
            </FlowStep>

            <FlowStep number={3} color="bg-violet-950/40 border-violet-700/30 text-violet-400" icon={Zap} title="Auto-Dispatch to Primary Garage">
              <p>
                The FSL optimization engine assigns the call to the Rank 1 (primary) garage for the zone.
                <FieldTag name="ServiceTerritoryId" /> is set to the primary garage.
                <FieldTag name="ERS_Auto_Assign__c" /> = true indicates auto-dispatch.
                <FieldTag name="SchedStartTime" /> is set — this is when a driver is scheduled to respond.
                The member is given a promised arrival time: <FieldTag name="ERS_PTA__c" /> (minutes).
              </p>
            </FlowStep>

            <FlowStep number={4} color="bg-amber-950/40 border-amber-700/30 text-amber-400" icon={ArrowRightLeft} title="Accept or Cascade">
              <p>
                The garage either accepts or declines the call:
              </p>
              <div className="grid grid-cols-2 gap-2 mt-2">
                <div className="bg-emerald-950/20 rounded-lg p-2 border border-emerald-800/20">
                  <span className="text-emerald-400 font-semibold text-[10px]">ACCEPTED</span>
                  <p className="mt-1"><FieldTag name="ERS_Facility_Decline_Reason__c" /> is NULL. Driver gets dispatched. This is a "1st Call" for this garage.</p>
                </div>
                <div className="bg-red-950/20 rounded-lg p-2 border border-red-800/20">
                  <span className="text-red-400 font-semibold text-[10px]">DECLINED</span>
                  <p className="mt-1"><FieldTag name="ERS_Facility_Decline_Reason__c" /> is set (e.g., "No Trucks Available").
                    <FieldTag name="ServiceTerritoryId" /> changes to the next garage in the cascade. The SA History records the territory change.
                    The next garage receives it as a "2nd+ Call."</p>
                </div>
              </div>
            </FlowStep>

            <FlowStep number={5} color="bg-emerald-950/40 border-emerald-700/30 text-emerald-400" icon={Truck} title="Driver Assignment & Travel">
              <p>
                A qualified driver is matched. The <FieldTag name="AssignedResource" /> junction record links the
                <FieldTag name="ServiceAppointment" /> to the <FieldTag name="ServiceResource" /> (driver). The driver
                must have the required <FieldTag name="Skill" /> (via <FieldTag name="ServiceResourceSkill" />) matching
                the work type's <FieldTag name="SkillRequirement" />. The truck (<FieldTag name="Asset" />) must have
                matching <FieldTag name="ERS_Truck_Capabilities__c" />.
              </p>
              <div className="bg-slate-900/40 rounded-lg p-2 mt-2">
                <span className="text-slate-500 text-[10px]">Driver must also be available:</span>
                <p className="mt-1">
                  Active <FieldTag name="Shift" /> covering the current time window, no overlapping
                  <FieldTag name="ResourceAbsence" />, and a valid <FieldTag name="ServiceTerritoryMember" /> link to the garage.
                </p>
              </div>
            </FlowStep>

            <FlowStep number={6} color="bg-green-950/40 border-green-700/30 text-green-400" icon={CheckCircle2} title="Arrival & Completion">
              <p>
                <strong className="text-slate-200">Fleet:</strong> Driver taps "Arrived" → <FieldTag name="ActualStartTime" /> is set.
                Taps "Complete" → <FieldTag name="ActualEndTime" /> is set. <FieldTag name="Status" /> = "Completed".
              </p>
              <p>
                <strong className="text-slate-200">Towbook:</strong> Arrival captured in <FieldTag name="ServiceAppointmentHistory" /> when
                Status changes to "On Location" by the "Integrations Towbook" user. <FieldTag name="ActualStartTime" /> is
                written later at completion.
              </p>
              <div className="bg-slate-900/40 rounded-lg p-2 mt-2">
                <span className="text-brand-300 text-[10px] font-semibold">Key Response Time Formula:</span>
                <code className="block mt-1 text-[10px] text-brand-300/80">ATA = ActualStartTime − CreatedDate (in minutes)</code>
                <code className="block text-[10px] text-brand-300/80">SLA Hit = ATA ≤ 45 minutes</code>
              </div>
            </FlowStep>
          </motion.div>
        )}
        </AnimatePresence>
      </div>

      {/* ═══ TOPIC 4: Skills & Truck Matching ═══ */}
      <div className="space-y-3 mb-6">
        <button onClick={() => toggle('skills')}
          className="w-full flex items-center gap-3 glass rounded-xl p-4 border border-slate-700/20 hover:border-brand-500/30 transition-all text-left">
          <div className="w-10 h-10 rounded-xl bg-teal-600/15 border border-teal-500/25 flex items-center justify-center shrink-0">
            <Wrench className="w-5 h-5 text-teal-400" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="font-bold text-sm text-white">4. Skills, Trucks & Driver Matching</h3>
            <p className="text-[11px] text-slate-500 mt-0.5">How the system ensures the right driver with the right truck handles each call</p>
          </div>
          <ChevronDown className={clsx('w-4 h-4 text-slate-500 transition-transform', expandedTopic === 'skills' && 'rotate-180')} />
        </button>

        <AnimatePresence initial={false}>
        {expandedTopic === 'skills' && (
          <motion.div className="ml-4 pl-4 border-l-2 border-teal-800/30 space-y-4"
            variants={collapseVariants} initial="hidden" animate="visible" exit="exit">
            {/* Matching visual */}
            <div className="glass rounded-xl p-5 border border-slate-700/20 overflow-x-auto">
              <div className="min-w-[650px]">
                <svg width="650" height="200" viewBox="0 0 650 200">
                  {/* Work Type */}
                  <rect x="10" y="60" width="140" height="60" rx="10" fill="#0f172a" stroke="#8b5cf6" strokeWidth="2" />
                  <text x="80" y="82" fill="white" fontSize="11" fontWeight="bold" textAnchor="middle">WorkType</text>
                  <text x="80" y="97" fill="#a78bfa" fontSize="9" textAnchor="middle">"Tow"</text>
                  <text x="80" y="112" fill="#64748b" fontSize="8" textAnchor="middle">requires: Tow, Flat Bed</text>

                  {/* SkillRequirement junction */}
                  <rect x="190" y="70" width="120" height="40" rx="8" fill="#0f172a" stroke="#10b981" strokeWidth="1.5" />
                  <text x="250" y="93" fill="#6ee7b7" fontSize="9" textAnchor="middle">SkillRequirement</text>
                  <line x1="150" y1="90" x2="190" y2="90" stroke="#334155" strokeWidth="1.5" markerEnd="url(#arrowGray)" />

                  {/* Skill */}
                  <rect x="350" y="20" width="100" height="40" rx="8" fill="#0f172a" stroke="#6366f1" strokeWidth="1.5" />
                  <text x="400" y="44" fill="#a5b4fc" fontSize="10" textAnchor="middle">Skill: Tow</text>
                  <line x1="310" y1="85" x2="350" y2="45" stroke="#334155" strokeWidth="1.5" markerEnd="url(#arrowGray)" />

                  <rect x="350" y="80" width="100" height="40" rx="8" fill="#0f172a" stroke="#6366f1" strokeWidth="1.5" />
                  <text x="400" y="104" fill="#a5b4fc" fontSize="10" textAnchor="middle">Skill: Flat Bed</text>
                  <line x1="310" y1="92" x2="350" y2="98" stroke="#334155" strokeWidth="1.5" markerEnd="url(#arrowGray)" />

                  {/* ServiceResourceSkill junction */}
                  <rect x="490" y="70" width="130" height="40" rx="8" fill="#0f172a" stroke="#10b981" strokeWidth="1.5" />
                  <text x="555" y="93" fill="#6ee7b7" fontSize="9" textAnchor="middle">ServiceResourceSkill</text>
                  <line x1="450" y1="45" x2="490" y2="85" stroke="#334155" strokeWidth="1.5" markerEnd="url(#arrowGray)" />
                  <line x1="450" y1="98" x2="490" y2="92" stroke="#334155" strokeWidth="1.5" markerEnd="url(#arrowGray)" />

                  {/* Driver */}
                  <rect x="490" y="140" width="130" height="50" rx="10" fill="#0f172a" stroke="#6366f1" strokeWidth="2" />
                  <text x="555" y="162" fill="white" fontSize="11" fontWeight="bold" textAnchor="middle">ServiceResource</text>
                  <text x="555" y="177" fill="#94a3b8" fontSize="9" textAnchor="middle">Driver: John Smith</text>
                  <line x1="555" y1="140" x2="555" y2="110" stroke="#334155" strokeWidth="1.5" markerEnd="url(#arrowGray)" />

                  {/* Truck */}
                  <rect x="200" y="140" width="140" height="50" rx="10" fill="#0f172a" stroke="#6366f1" strokeWidth="2" />
                  <text x="270" y="162" fill="white" fontSize="11" fontWeight="bold" textAnchor="middle">Asset (ERS Truck)</text>
                  <text x="270" y="177" fill="#94a3b8" fontSize="9" textAnchor="middle">Capabilities: Tow, Flat Bed</text>
                  <line x1="340" y1="165" x2="490" y2="165" stroke="#22c55e" strokeWidth="1.5" strokeDasharray="4 2" markerEnd="url(#arrowGreen)" />
                  <text x="415" y="158" fill="#22c55e" fontSize="8" textAnchor="middle">ERS_Driver__c</text>

                  {/* Match indicator */}
                  <text x="415" y="30" fill="#22c55e" fontSize="10" fontWeight="bold" textAnchor="middle">MATCH = Driver can take this call</text>

                  <defs>
                    <marker id="arrowGray" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="5" markerHeight="5" orient="auto">
                      <path d="M0,0 L10,5 L0,10 z" fill="#475569" />
                    </marker>
                    <marker id="arrowGreen" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="5" markerHeight="5" orient="auto">
                      <path d="M0,0 L10,5 L0,10 z" fill="#22c55e" />
                    </marker>
                  </defs>
                </svg>
              </div>
            </div>

            <p className="text-xs text-slate-400 leading-relaxed">
              The matching chain works like this: A <FieldTag name="WorkType" /> (e.g., "Tow") has
              <FieldTag name="SkillRequirement" /> records defining which skills are needed. Each driver
              (<FieldTag name="ServiceResource" />) has <FieldTag name="ServiceResourceSkill" /> records listing what
              they can do. The driver's truck (<FieldTag name="Asset" /> with <FieldTag name="ERS_Truck_Capabilities__c" />)
              must also be capable. Only when skills AND truck capabilities match is the driver eligible.
            </p>
          </motion.div>
        )}
        </AnimatePresence>
      </div>

      {/* ═══ TOPIC 5: PTA & Time Tracking ═══ */}
      <div className="space-y-3 mb-6">
        <button onClick={() => toggle('pta')}
          className="w-full flex items-center gap-3 glass rounded-xl p-4 border border-slate-700/20 hover:border-brand-500/30 transition-all text-left">
          <div className="w-10 h-10 rounded-xl bg-amber-600/15 border border-amber-500/25 flex items-center justify-center shrink-0">
            <Clock className="w-5 h-5 text-amber-400" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="font-bold text-sm text-white">5. PTA Promise & Time Tracking</h3>
            <p className="text-[11px] text-slate-500 mt-0.5">How arrival times are promised, tracked, and measured</p>
          </div>
          <ChevronDown className={clsx('w-4 h-4 text-slate-500 transition-transform', expandedTopic === 'pta' && 'rotate-180')} />
        </button>

        <AnimatePresence initial={false}>
        {expandedTopic === 'pta' && (
          <motion.div className="ml-4 pl-4 border-l-2 border-amber-800/30 space-y-4"
            variants={collapseVariants} initial="hidden" animate="visible" exit="exit">
            {/* Timeline visual */}
            <div className="glass rounded-xl p-5 border border-slate-700/20 overflow-x-auto">
              <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-3">Response Time Decomposition</h4>
              <div className="min-w-[600px]">
                <div className="relative h-16 mx-4">
                  {/* Time bar */}
                  <div className="absolute top-6 left-0 right-0 h-4 flex rounded-full overflow-hidden">
                    <div className="bg-amber-600/60 flex-[2]" title="Dispatch Queue" />
                    <div className="bg-blue-600/60 flex-[3]" title="Travel Time" />
                    <div className="bg-emerald-600/60 flex-[1.5]" title="On-Site" />
                  </div>
                  {/* Labels below */}
                  <div className="absolute top-12 left-0 right-0 flex text-[9px]">
                    <div className="flex-[2] text-center text-amber-400">Dispatch Queue</div>
                    <div className="flex-[3] text-center text-blue-400">Travel Time</div>
                    <div className="flex-[1.5] text-center text-emerald-400">On-Site</div>
                  </div>
                  {/* Field markers above */}
                  <div className="absolute top-0 left-0 flex items-end h-5">
                    <code className="text-[8px] text-slate-500 bg-slate-900 px-1 rounded">CreatedDate</code>
                  </div>
                  <div className="absolute top-0 left-[30%] flex items-end h-5" style={{ transform: 'translateX(-50%)' }}>
                    <code className="text-[8px] text-slate-500 bg-slate-900 px-1 rounded">SchedStartTime</code>
                  </div>
                  <div className="absolute top-0 left-[77%] flex items-end h-5" style={{ transform: 'translateX(-50%)' }}>
                    <code className="text-[8px] text-slate-500 bg-slate-900 px-1 rounded">ActualStartTime</code>
                  </div>
                  <div className="absolute top-0 right-0 flex items-end h-5">
                    <code className="text-[8px] text-slate-500 bg-slate-900 px-1 rounded">ActualEndTime</code>
                  </div>
                </div>
              </div>
              <div className="flex items-center justify-center gap-4 mt-8 text-[10px]">
                <span className="flex items-center gap-1.5"><span className="w-3 h-2 rounded bg-amber-600/60" />Dispatch Queue = SchedStartTime − CreatedDate</span>
                <span className="flex items-center gap-1.5"><span className="w-3 h-2 rounded bg-blue-600/60" />Travel = ActualStartTime − SchedStartTime</span>
                <span className="flex items-center gap-1.5"><span className="w-3 h-2 rounded bg-emerald-600/60" />On-Site = ActualEndTime − ActualStartTime</span>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="glass rounded-xl p-4 border border-slate-700/20">
                <h4 className="font-semibold text-xs text-white mb-2">PTA = Promised Time of Arrival</h4>
                <p className="text-xs text-slate-400 leading-relaxed">
                  When a call is dispatched, the member is told "we'll be there in X minutes."
                  This promise is stored in <FieldTag name="ERS_PTA__c" /> (minutes). The absolute deadline
                  is <FieldTag name="ERS_PTA_Due__c" /> = CreatedDate + ERS_PTA__c.
                  PTA targets per garage+work type are configured in <FieldTag name="ERS_Service_Appointment_PTA__c" />.
                </p>
              </div>
              <div className="glass rounded-xl p-4 border border-slate-700/20">
                <h4 className="font-semibold text-xs text-white mb-2">PTA Accuracy</h4>
                <p className="text-xs text-slate-400 leading-relaxed">
                  PTA Accuracy = did the driver arrive before the promised time?
                  <code className="block mt-1 text-[10px] text-brand-300 bg-slate-900/50 rounded px-2 py-1">
                    actual_wait = ActualStartTime − CreatedDate<br/>
                    on_time = actual_wait ≤ ERS_PTA__c
                  </code>
                  Values of 0 and 999 in <FieldTag name="ERS_PTA__c" /> are sentinel values (no valid ETA) and excluded.
                </p>
              </div>
            </div>
          </motion.div>
        )}
        </AnimatePresence>
      </div>

      {/* ═══ TOPIC 6: Scoring & Grading ═══ */}
      <div className="space-y-3 mb-6">
        <button onClick={() => toggle('scoring')}
          className="w-full flex items-center gap-3 glass rounded-xl p-4 border border-slate-700/20 hover:border-brand-500/30 transition-all text-left">
          <div className="w-10 h-10 rounded-xl bg-brand-600/15 border border-brand-500/25 flex items-center justify-center shrink-0">
            <Award className="w-5 h-5 text-brand-400" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="font-bold text-sm text-white">6. Scoring & Garage Grading</h3>
            <p className="text-[11px] text-slate-500 mt-0.5">How each garage gets a composite score (0–100) and letter grade (A–F)</p>
          </div>
          <ChevronDown className={clsx('w-4 h-4 text-slate-500 transition-transform', expandedTopic === 'scoring' && 'rotate-180')} />
        </button>

        <AnimatePresence initial={false}>
        {expandedTopic === 'scoring' && (
          <motion.div className="ml-4 pl-4 border-l-2 border-brand-800/30 space-y-4"
            variants={collapseVariants} initial="hidden" animate="visible" exit="exit">
            {/* Scoring pyramid */}
            <div className="glass rounded-xl p-5 border border-slate-700/20">
              <div className="flex items-center gap-6">
                <div className="flex flex-col gap-1.5 flex-1">
                  {[
                    { dim: '45-Min SLA Hit Rate', w: '30%', field: 'ActualStartTime − CreatedDate ≤ 45', pct: 100, color: 'bg-violet-500' },
                    { dim: 'Completion Rate', w: '15%', field: 'Status = Completed ÷ Total', pct: 50, color: 'bg-blue-500' },
                    { dim: 'Customer Satisfaction', w: '15%', field: 'Survey_Result__c.ERS_Overall_Satisfaction__c', pct: 50, color: 'bg-emerald-500' },
                    { dim: 'Median Response Time', w: '10%', field: 'MEDIAN(ActualStartTime − CreatedDate)', pct: 33, color: 'bg-teal-500' },
                    { dim: 'PTA Accuracy', w: '10%', field: 'ATA ≤ ERS_PTA__c', pct: 33, color: 'bg-amber-500' },
                    { dim: '"Could Not Wait" Rate', w: '10%', field: 'ERS_Cancellation_Reason__c LIKE Member Could Not Wait%', pct: 33, color: 'bg-orange-500' },
                    { dim: 'Dispatch Speed', w: '5%', field: 'SchedStartTime − CreatedDate', pct: 17, color: 'bg-pink-500' },
                    { dim: 'Facility Decline Rate', w: '5%', field: 'ERS_Facility_Decline_Reason__c IS NOT NULL', pct: 17, color: 'bg-red-500' },
                  ].map((d, i) => (
                    <motion.div key={d.dim} className="flex items-center gap-3"
                      initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: i * 0.06 + 0.1 }}>
                      <motion.div className={clsx('h-3 rounded-full', d.color)}
                        style={{ opacity: 0.6 }}
                        initial={{ width: 0 }} animate={{ width: `${d.pct}%` }}
                        transition={{ duration: 0.6, delay: i * 0.06 + 0.2, ease: 'easeOut' }} />
                      <span className="text-[10px] text-white font-medium shrink-0 w-40">{d.dim}</span>
                      <span className="text-[10px] text-brand-300 font-bold shrink-0 w-8">{d.w}</span>
                      <code className="text-[8px] text-slate-500 truncate">{d.field}</code>
                    </motion.div>
                  ))}
                </div>
                <motion.div className="shrink-0 text-center"
                  initial={{ scale: 0, rotate: -10 }} animate={{ scale: 1, rotate: 0 }}
                  transition={{ type: 'spring', stiffness: 300, damping: 15, delay: 0.5 }}>
                  <div className="w-20 h-20 rounded-2xl bg-emerald-950/40 border-2 border-emerald-700/30 flex flex-col items-center justify-center">
                    <div className="text-3xl font-black text-emerald-400">A</div>
                    <div className="text-[10px] text-emerald-400/80">92/100</div>
                  </div>
                  <div className="text-[9px] text-slate-500 mt-2">Composite<br/>Score</div>
                </motion.div>
              </div>
            </div>

            <p className="text-xs text-slate-400 leading-relaxed">
              Every garage is scored across 8 dimensions. Each dimension pulls from specific Salesforce fields,
              is normalized to 0–100, multiplied by its weight, and summed into a composite score.
              The score maps to a letter grade: A (90–100), B (80–89), C (70–79), D (60–69), F (0–59).
              Customer satisfaction comes from <FieldTag name="Survey_Result__c" /> matched to garages via
              <FieldTag name="WorkOrder.WorkOrderNumber" />.
            </p>
          </motion.div>
        )}
        </AnimatePresence>
      </div>

      {/* ═══ TOPIC 7: Member Experience ═══ */}
      <div className="space-y-3 mb-2">
        <button onClick={() => toggle('member')}
          className="w-full flex items-center gap-3 glass rounded-xl p-4 border border-slate-700/20 hover:border-brand-500/30 transition-all text-left">
          <div className="w-10 h-10 rounded-xl bg-blue-600/15 border border-blue-500/25 flex items-center justify-center shrink-0">
            <Users className="w-5 h-5 text-blue-400" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="font-bold text-sm text-white">7. Member Experience & Satisfaction</h3>
            <p className="text-[11px] text-slate-500 mt-0.5">How member wait times and satisfaction are tracked and measured</p>
          </div>
          <ChevronDown className={clsx('w-4 h-4 text-slate-500 transition-transform', expandedTopic === 'member' && 'rotate-180')} />
        </button>

        <AnimatePresence initial={false}>
        {expandedTopic === 'member' && (
          <motion.div className="ml-4 pl-4 border-l-2 border-blue-800/30 space-y-4"
            variants={collapseVariants} initial="hidden" animate="visible" exit="exit">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <InfoCard title="Response Time" icon={Clock} color="bg-blue-950/40 border-blue-700/30 text-blue-400">
                <p>
                  The #1 member experience metric. Measured as <FieldTag name="ActualStartTime" /> minus <FieldTag name="CreatedDate" />.
                  Target: ≤ 45 minutes. The 45-min SLA Hit Rate carries 30% of the composite score weight.
                </p>
              </InfoCard>
              <InfoCard title="Could Not Wait" icon={XCircle} color="bg-red-950/40 border-red-700/30 text-red-400">
                <p>
                  When response is too slow, members cancel. Tracked via <FieldTag name="ERS_Cancellation_Reason__c" /> =
                  "Member Could Not Wait%". A high rate = direct member frustration signal.
                </p>
              </InfoCard>
              <InfoCard title="CSAT Survey" icon={ThumbsUp} color="bg-emerald-950/40 border-emerald-700/30 text-emerald-400">
                <p>
                  Post-service survey from Qualtrics, stored in <FieldTag name="Survey_Result__c" />.
                  Matched to garage via <FieldTag name="ERS_Work_Order_Number__c" />. Key field:
                  <FieldTag name="ERS_Overall_Satisfaction__c" /> — "Totally Satisfied" = success.
                </p>
              </InfoCard>
            </div>
            <div className="glass rounded-xl p-4 border border-slate-700/20">
              <h4 className="font-semibold text-xs text-white mb-2">The Member's Timeline (What They Experience)</h4>
              <div className="flex items-center gap-2 text-[10px] text-slate-400 flex-wrap">
                <span className="bg-blue-950/30 rounded-lg px-2 py-1 border border-blue-800/20">Calls AAA</span>
                <ChevronRight className="w-3 h-3 text-slate-700" />
                <span className="bg-blue-950/30 rounded-lg px-2 py-1 border border-blue-800/20">Told "X minutes"<br/><code className="text-[8px] text-brand-300">ERS_PTA__c</code></span>
                <ChevronRight className="w-3 h-3 text-slate-700" />
                <span className="bg-amber-950/30 rounded-lg px-2 py-1 border border-amber-800/20">Waiting...<br/><code className="text-[8px] text-amber-300">CreatedDate → now</code></span>
                <ChevronRight className="w-3 h-3 text-slate-700" />
                <span className="bg-emerald-950/30 rounded-lg px-2 py-1 border border-emerald-800/20">Driver arrives<br/><code className="text-[8px] text-emerald-300">ActualStartTime</code></span>
                <ChevronRight className="w-3 h-3 text-slate-700" />
                <span className="bg-emerald-950/30 rounded-lg px-2 py-1 border border-emerald-800/20">Service done<br/><code className="text-[8px] text-emerald-300">ActualEndTime</code></span>
                <ChevronRight className="w-3 h-3 text-slate-700" />
                <span className="bg-purple-950/30 rounded-lg px-2 py-1 border border-purple-800/20">Survey sent<br/><code className="text-[8px] text-purple-300">Survey_Result__c</code></span>
              </div>
            </div>
          </motion.div>
        )}
        </AnimatePresence>
      </div>
    </div>
  )
}

// ── Page Guide Section ──
function OverviewSection() {
  const PAGE_GUIDES = [
    {
      name: 'Command Center', route: '/', icon: Radio,
      color: 'border-red-800/30 bg-red-950/10',
      iconColor: 'bg-red-950/40 border-red-700/30 text-red-400',
      what: 'Your real-time war room. Shows every territory, every open call, every driver, and every alert — right now.',
      when: 'This is your morning start page and the page you keep open all day. Check it first thing, and come back whenever you need a pulse on what\'s happening across all garages.',
      lookFor: [
        { label: 'Open Calls count', meaning: 'How many members are currently waiting for a driver. If this number is climbing, you\'re falling behind.' },
        { label: 'Red/amber territory cards', meaning: 'Garages that are struggling right now — long wait times, too many open calls, or drivers unavailable.' },
        { label: 'Driver pins on the map', meaning: 'Where your fleet drivers are physically located. Gaps on the map = zones with no coverage.' },
        { label: 'Alerts banner', meaning: 'Calls that have been waiting too long, approaching or past their promised arrival time (PTA). These need immediate attention.' },
      ],
      howToRead: 'Each territory card shows the garage name, open call count, average wait time, and available drivers. Green = healthy. Amber = watch closely. Red = take action now. The map shows member locations (call pins) and driver locations (truck pins) so you can visually spot mismatches — for example, a cluster of calls with no nearby drivers.',
      tips: 'If you see a territory going red, drill into it to see individual calls. If a specific call has been waiting 30+ minutes, consider manually reassigning it or calling the garage.',
    },
    {
      name: 'Garages', route: '/garages', icon: LayoutDashboard,
      color: 'border-blue-800/30 bg-blue-950/10',
      iconColor: 'bg-blue-950/40 border-blue-700/30 text-blue-400',
      what: 'A report card for every garage. Shows composite scores (0–100), letter grades (A–F), and all key performance metrics over a time period you choose.',
      when: 'Use this for weekly performance reviews, when evaluating garage contracts, or when a garage complains about their score. Click any garage row to drill into the deep-dive with charts and trends.',
      lookFor: [
        { label: 'Letter grade (A–F)', meaning: 'The overall health of the garage. A/B = performing well. C = needs attention. D/F = serious issues that affect member experience.' },
        { label: 'SLA Hit Rate column', meaning: 'The single most important number. This is what percentage of members got help within 45 minutes. Anything below 80% is a problem.' },
        { label: 'Decline Rate', meaning: 'How often the garage refuses calls. High decline = calls cascade to other garages, adding delay. Should be < 2%.' },
        { label: 'Completion Rate', meaning: 'Are they finishing the jobs they accept? Below 90% means something is wrong — trucks breaking down, drivers leaving mid-job, etc.' },
      ],
      howToRead: 'The table is sorted by composite score by default — worst garages at the bottom. Each row is one garage with their grade, score, and key metrics for the selected time period (default: last 4 weeks). Click a garage to see trend charts, dispatch mix, response time breakdown, driver leaderboard, and more.',
      tips: 'Compare the same garage across different time periods (use the weeks selector) to spot trends. A garage dropping from B to D over 2 months needs a conversation. Also compare fleet garages vs contractor garages — their performance patterns are often very different.',
    },
    {
      name: 'Queue Board', route: '/queue', icon: ListOrdered,
      color: 'border-violet-800/30 bg-violet-950/10',
      iconColor: 'bg-violet-950/40 border-violet-700/30 text-violet-400',
      what: 'Live list of every open Service Appointment waiting for a driver. Shows who\'s waiting, how long, what they need, and which garage has it.',
      when: 'Monitor this throughout the day, especially during peak hours (morning commute, bad weather). This is where you catch calls falling through the cracks.',
      lookFor: [
        { label: 'Wait time column', meaning: 'How long the member has been waiting since their call was created. Anything over 30 minutes in the queue = danger zone.' },
        { label: 'PTA Due indicator', meaning: 'When we promised the member a driver would arrive. If the current time is past the PTA Due, we\'ve already broken our promise. Red = overdue.' },
        { label: 'Work Type', meaning: 'What kind of service — Tow, Battery, Tire, etc. Tows take longer to dispatch because fewer trucks are tow-capable.' },
        { label: 'Cascade status', meaning: 'Has this call already been declined by another garage? "2nd+ Call" means it was bounced — the member has been waiting even longer than the timer shows.' },
      ],
      howToRead: 'Each row is one open call. They\'re sorted by wait time (longest first). The driver recommendation column suggests which available driver is closest and qualified. The territory column shows which garage currently owns the call. If a call has been in the queue for a long time with no recommendation, it likely means no qualified drivers are available — you may need to manually intervene.',
      tips: 'Sort by PTA Due to see which promises are about to be broken. If multiple calls are stacking up for the same garage, that garage may be overwhelmed — consider redistributing or calling for backup.',
    },
    {
      name: 'PTA Advisor', route: '/pta', icon: Clock,
      color: 'border-amber-800/30 bg-amber-950/10',
      iconColor: 'bg-amber-950/40 border-amber-700/30 text-amber-400',
      what: 'Analyzes whether the arrival times we promise members are realistic. Compares what we told members vs. how long it actually took.',
      when: 'Use this in weekly reviews or when members complain about broken promises. Also use it when adjusting PTA settings for specific garages or work types.',
      lookFor: [
        { label: 'PTA Accuracy %', meaning: 'Of calls where we gave an ETA, what percentage had the driver arrive on time? Below 80% means we\'re consistently over-promising.' },
        { label: 'Avg PTA vs Avg Actual', meaning: 'If the average PTA is 35 minutes but average actual arrival is 55 minutes, we\'re telling members 35 min when it really takes 55. The gap is the problem.' },
        { label: 'By Work Type breakdown', meaning: 'Tows often have worse PTA accuracy than battery calls because they require specialized trucks. Check if specific work types are dragging the number down.' },
        { label: 'By Garage breakdown', meaning: 'Some garages consistently miss their PTA while others are on target. This identifies which garages need their PTA settings adjusted.' },
      ],
      howToRead: 'Each garage row shows the average minutes promised (PTA), the average actual arrival time, the gap between them, and the on-time percentage. Green rows = promises are realistic. Red rows = we\'re telling members one thing and delivering another. The "projected" column shows what the PTA should be based on actual performance.',
      tips: 'If a garage\'s actual arrival time is consistently 20 minutes more than their PTA, either increase their PTA settings (so we promise realistic times) or investigate why they\'re so slow (driver shortage? too many declines?).',
    },
    {
      name: 'Forecast', route: '/forecast', icon: CloudSun,
      color: 'border-teal-800/30 bg-teal-950/10',
      iconColor: 'bg-teal-950/40 border-teal-700/30 text-teal-400',
      what: 'Predicts how many calls each territory will get over the next 16 days, based on historical day-of-week patterns and weather conditions.',
      when: 'Use this for staffing decisions — how many drivers to schedule next week, when to have extra coverage, when to expect light days.',
      lookFor: [
        { label: 'Daily volume bars', meaning: 'Predicted number of calls per day. Tall bars = busy days. Mondays and bad-weather days are typically highest.' },
        { label: 'Weather overlay', meaning: 'Rain, snow, and extreme temperatures drive call volume up. The forecast flags days with weather that historically increases demand.' },
        { label: 'Day-of-week pattern', meaning: 'Most territories have a consistent pattern — e.g., busy Mon/Tue, quiet weekends. If the forecast shows a spike on a normally quiet day, weather or a holiday is probably the reason.' },
        { label: 'Territory comparison', meaning: 'Compare territories side by side to see where demand will be heaviest. Useful for shifting drivers between garages.' },
      ],
      howToRead: 'The chart shows one bar per day. The height is the predicted call count based on the last 8 weeks of history for that day of the week (e.g., "average Mondays for this territory"). Weather icons indicate conditions that historically increase or decrease volume. The confidence band (lighter shading) shows the range — actual volume will likely fall within that band.',
      tips: 'Use the forecast to pre-position drivers. If Tuesday is predicted to be 30% busier than normal due to a winter storm, schedule extra coverage. If a territory shows consistently low volume on weekends, consider reducing weekend staffing there and shifting those drivers to busier territories.',
    },
    {
      name: 'Territory Matrix', route: '/matrix', icon: ArrowRightLeft,
      color: 'border-pink-800/30 bg-pink-950/10',
      iconColor: 'bg-pink-950/40 border-pink-700/30 text-pink-400',
      what: 'Shows the cascade chain for each zone — which garage is primary, secondary, tertiary — and analyzes whether the current priority order is actually working.',
      when: 'Use this quarterly or when you notice certain zones have consistently bad response times despite having garages nearby. This helps you decide whether to swap which garage is primary for a zone.',
      lookFor: [
        { label: 'Cascade effectiveness', meaning: 'When the primary garage declines and the call goes to the backup — how much extra time does the member wait? High cascade delay = the backup garage is too far away or too slow.' },
        { label: 'Swap recommendations', meaning: 'The advisor flags zones where the current secondary garage actually performs better than the primary. It suggests swapping them to reduce member wait times.' },
        { label: 'Decline patterns by zone', meaning: 'If a primary garage declines 30% of calls from a specific zone, maybe that zone should be reassigned to a garage that actually wants the work.' },
        { label: '1st Call vs 2nd+ Call split', meaning: 'What percentage of a garage\'s calls are original assignments vs cascaded from other garages? A garage receiving mostly 2nd+ calls is picking up other garages\' slack.' },
      ],
      howToRead: 'The matrix table shows each zone, its priority chain (Rank 1, 2, 3 garages), and performance metrics for each position. The "swap" indicator highlights zones where reordering the cascade chain would improve response times. Click a zone to see detailed cascade flow and timing data.',
      tips: 'Don\'t swap primaries just because one month is bad — look at 2-3 months of data. Seasonal patterns (winter vs summer) can change which garage performs best for a zone. Also consider the cascade chain holistically — changing one zone\'s primary affects the workload of all garages in that chain.',
    },
  ]

  return (
    <div>
      <SectionHeader title="Page-by-Page Guide for Dispatch Managers" subtitle="How to use each page to manage your operation — what to look for, what the numbers mean, and how to take action." />

      {/* Quick orientation */}
      <div className="glass rounded-xl p-5 border border-brand-500/20 bg-brand-950/10 mt-4 mb-6">
        <h3 className="font-bold text-sm text-white mb-2">Your Daily Workflow</h3>
        <div className="text-xs text-slate-300 leading-relaxed space-y-1.5">
          <p>
            <strong className="text-white">Start of shift →</strong> Open the <strong className="text-brand-300">Command Center</strong> to see the current state of all territories, open calls, and driver positions.
          </p>
          <p>
            <strong className="text-white">Throughout the day →</strong> Monitor the <strong className="text-brand-300">Queue Board</strong> for calls waiting too long, broken PTA promises, and cascaded calls piling up.
          </p>
          <p>
            <strong className="text-white">Weekly reviews →</strong> Check <strong className="text-brand-300">Garages</strong> for performance trends, <strong className="text-brand-300">PTA Advisor</strong> for promise accuracy, and the <strong className="text-brand-300">Forecast</strong> for next week's staffing needs.
          </p>
          <p>
            <strong className="text-white">Quarterly planning →</strong> Use the <strong className="text-brand-300">Territory Matrix</strong> to evaluate cascade chains and consider zone reassignments.
          </p>
        </div>
      </div>

      {/* Page-by-page guides */}
      <motion.div className="space-y-4" variants={stagger(0.08)} initial="hidden" animate="show">
        {PAGE_GUIDES.map(p => (
          <motion.div key={p.name} className={clsx('rounded-xl border overflow-hidden', p.color)}
            variants={fadeUp} transition={{ type: 'spring', stiffness: 260, damping: 22 }}>
            {/* Header */}
            <div className="px-5 py-4 border-b border-slate-800/30">
              <div className="flex items-center gap-3">
                <div className={clsx('w-10 h-10 rounded-xl flex items-center justify-center border', p.iconColor)}>
                  <p.icon className="w-5 h-5" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-bold text-base text-white">{p.name}</h3>
                    <code className="text-[9px] text-slate-500 bg-slate-900/60 rounded px-1.5 py-0.5">{p.route}</code>
                  </div>
                  <p className="text-xs text-slate-400 mt-0.5">{p.what}</p>
                </div>
              </div>
            </div>

            <div className="px-5 py-4 space-y-4">
              {/* When to use */}
              <div>
                <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-1.5">When to Use This Page</h4>
                <p className="text-xs text-slate-300 leading-relaxed">{p.when}</p>
              </div>

              {/* What to look for */}
              <div>
                <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-2">What to Look For</h4>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {p.lookFor.map(item => (
                    <div key={item.label} className="bg-slate-900/30 rounded-lg p-3 border border-slate-800/30">
                      <div className="font-semibold text-[11px] text-white mb-1">{item.label}</div>
                      <p className="text-[11px] text-slate-400 leading-relaxed">{item.meaning}</p>
                    </div>
                  ))}
                </div>
              </div>

              {/* How to read it */}
              <div>
                <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-1.5">How to Read It</h4>
                <p className="text-xs text-slate-300 leading-relaxed">{p.howToRead}</p>
              </div>

              {/* Pro tips */}
              <div className="bg-slate-900/30 rounded-lg p-3 border border-slate-800/30">
                <h4 className="text-[10px] font-bold uppercase tracking-wider text-brand-400 mb-1">Pro Tip</h4>
                <p className="text-[11px] text-slate-400 leading-relaxed">{p.tips}</p>
              </div>
            </div>
          </motion.div>
        ))}
      </motion.div>
    </div>
  )
}

// ── Metrics Section ──
function MetricsSection() {
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

// ── Scoring Section ──
function ScoringSection() {
  const PLAIN_DIMS = [
    {
      key: 'sla_hit_rate', label: '45-Min SLA Hit Rate', weight: '30%', target: '100%',
      plain: 'Of all completed calls, what percentage had the driver arrive within 45 minutes?',
      formula: 'Count how many completed calls had the driver arrive in ≤ 45 min, divide by total completed calls, multiply by 100.',
      example: 'If 80 out of 100 calls were under 45 min → SLA Hit Rate = 80%.',
      color: 'border-violet-800/30 bg-violet-950/10',
    },
    {
      key: 'completion_rate', label: 'Completion Rate', weight: '15%', target: '95%',
      plain: 'Of all calls sent to this garage, what percentage did they actually finish?',
      formula: 'Count calls with Status = "Completed", divide by total calls sent to the garage, multiply by 100.',
      example: 'Garage got 100 calls, completed 92 → Completion Rate = 92%.',
      color: 'border-blue-800/30 bg-blue-950/10',
    },
    {
      key: 'satisfaction', label: 'Customer Satisfaction', weight: '15%', target: '82%',
      plain: 'Of members who filled out the post-service survey, what percentage said "Totally Satisfied"?',
      formula: 'Count surveys where overall satisfaction = "Totally Satisfied", divide by total surveys for this garage, multiply by 100.',
      example: '41 out of 50 surveys said Totally Satisfied → CSAT = 82%.',
      color: 'border-emerald-800/30 bg-emerald-950/10',
    },
    {
      key: 'median_response', label: 'Median Response Time', weight: '10%', target: '≤ 45 min',
      plain: 'The middle value of how long members waited for a driver to arrive. Uses the median so one really slow call doesn\'t ruin the number.',
      formula: 'For each completed call, calculate minutes from when the call was created to when the driver actually arrived. Sort all values, pick the one in the middle.',
      example: 'If 5 calls took 20, 30, 35, 50, 120 min → median = 35 min (the middle one).',
      color: 'border-teal-800/30 bg-teal-950/10',
    },
    {
      key: 'pta_accuracy', label: 'PTA Accuracy (ETA Accuracy)', weight: '10%', target: '90%',
      plain: 'When we told the member "we\'ll be there in X minutes", did the driver actually arrive within that time?',
      formula: 'For each call that had a valid promised time (ERS_PTA__c between 1–998), check if the actual wait was ≤ the promise. Count the on-time ones, divide by total evaluated.',
      example: 'Promised 45 min, driver arrived in 40 → on time. Promised 30 min, arrived in 50 → late.',
      color: 'border-amber-800/30 bg-amber-950/10',
    },
    {
      key: 'could_not_wait', label: '"Could Not Wait" Rate', weight: '10%', target: '< 3%',
      plain: 'What percentage of members gave up and cancelled because they waited too long for a driver?',
      formula: 'Count calls where cancellation reason starts with "Member Could Not Wait", divide by total calls, multiply by 100. Lower is better.',
      example: '3 out of 100 members cancelled because they couldn\'t wait → CNW Rate = 3%.',
      color: 'border-orange-800/30 bg-orange-950/10',
    },
    {
      key: 'dispatch_speed', label: 'Dispatch Speed', weight: '5%', target: '≤ 5 min',
      plain: 'How fast does a driver get assigned after the call comes in? Measures how long the call sits in the queue.',
      formula: 'For each call, calculate minutes from when the call was created (CreatedDate) to when a driver was scheduled (SchedStartTime). Take the middle value.',
      example: 'Call created at 2:00 PM, driver scheduled at 2:03 PM → dispatch took 3 min.',
      color: 'border-pink-800/30 bg-pink-950/10',
    },
    {
      key: 'decline_rate', label: 'Facility Decline Rate', weight: '5%', target: '< 2%',
      plain: 'What percentage of calls did this garage refuse to handle? Declines delay the member because the call has to be sent to another garage.',
      formula: 'Count calls where a decline reason was recorded (ERS_Facility_Decline_Reason__c is not empty), divide by total calls, multiply by 100. Lower is better.',
      example: '2 out of 100 calls declined → Decline Rate = 2%.',
      color: 'border-red-800/30 bg-red-950/10',
    },
  ]

  return (
    <div>
      <SectionHeader title="How Garages Are Rated" subtitle="Every garage gets a report card — here's exactly how the grade is calculated, in plain English." />

      {/* Plain English Summary */}
      <div className="glass rounded-xl p-5 border border-brand-500/20 bg-brand-950/10 mt-4 mb-6">
        <h3 className="font-bold text-sm text-white mb-3">The Big Picture</h3>
        <div className="text-xs text-slate-300 leading-relaxed space-y-2">
          <p>
            The system looks at <strong className="text-white">8 things</strong> that matter most for member experience — like
            how fast drivers arrive, how often garages complete calls, whether members are satisfied, and how
            often garages decline calls. Each of these 8 things gets a score from 0 to 100.
          </p>
          <p>
            Not all 8 things count equally. <strong className="text-white">Getting a driver there in under 45 minutes is the
            most important</strong> — it counts for 30% of the grade. Customer satisfaction and completion rate each
            count 15%. The rest fill in the remaining 30%.
          </p>
          <p>
            The system multiplies each score by its weight, adds them up, and produces a final number from 0 to 100.
            That number becomes a letter grade:
            <strong className="text-emerald-400"> A</strong> = excellent (90–100),
            <strong className="text-blue-400"> B</strong> = good (80–89),
            <strong className="text-amber-400"> C</strong> = needs work (70–79),
            <strong className="text-orange-400"> D</strong> = concerning (60–69),
            <strong className="text-red-400"> F</strong> = failing (below 60).
          </p>
        </div>
      </div>

      {/* Grade Scale */}
      <motion.div className="flex gap-2 mb-6" variants={stagger(0.06)} initial="hidden" animate="show">
        {GRADES.map(g => (
          <motion.div key={g.grade} className={clsx('flex-1 text-center rounded-xl py-3 border', g.color)}
            variants={fadeUp} transition={{ type: 'spring', stiffness: 400, damping: 20 }}>
            <div className="text-xl font-black">{g.grade}</div>
            <div className="text-[10px] mt-0.5 opacity-80">{g.range}</div>
          </motion.div>
        ))}
      </motion.div>

      {/* The 8 Dimensions — Plain English Cards */}
      <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-3">The 8 Things We Measure</h4>
      <motion.div className="space-y-3 mb-6" variants={stagger(0.06)} initial="hidden" animate="show">
        {PLAIN_DIMS.map((d, i) => (
          <motion.div key={d.key} className={clsx('rounded-xl border p-4', d.color)}
            variants={fadeSide} transition={{ type: 'spring', stiffness: 280, damping: 22 }}>
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded-lg bg-slate-900/60 flex items-center justify-center shrink-0 border border-slate-700/30">
                <span className="text-sm font-black text-brand-300">{i + 1}</span>
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3 mb-1.5">
                  <h4 className="font-bold text-sm text-white">{d.label}</h4>
                  <span className="text-[10px] font-bold text-brand-300 bg-brand-950/40 border border-brand-800/30 rounded px-2 py-0.5">
                    Weight: {d.weight}
                  </span>
                  <span className="text-[10px] font-bold text-emerald-400 bg-emerald-950/40 border border-emerald-800/30 rounded px-2 py-0.5">
                    Target: {d.target}
                  </span>
                </div>
                <p className="text-xs text-slate-200 leading-relaxed mb-2">
                  {d.plain}
                </p>
                <div className="bg-slate-900/40 rounded-lg p-3 space-y-1.5">
                  <div>
                    <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">How it's calculated:</span>
                    <p className="text-[11px] text-slate-300 mt-0.5">{d.formula}</p>
                  </div>
                  <div>
                    <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Example:</span>
                    <p className="text-[11px] text-brand-300/80 mt-0.5">{d.example}</p>
                  </div>
                </div>
              </div>
            </div>
          </motion.div>
        ))}
      </motion.div>

      {/* How the Final Score is Calculated — Plain English */}
      <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-2">How the Final Score is Calculated</h4>
      <div className="glass rounded-xl p-5 border border-slate-700/20 space-y-4">
        <div>
          <h5 className="font-semibold text-xs text-white mb-1">For metrics where higher is better (SLA, Completion, Satisfaction, PTA Accuracy):</h5>
          <div className="bg-slate-900/50 rounded-lg p-3 text-xs text-slate-300 leading-relaxed">
            <p>Take the garage's actual number, divide it by the target, and multiply by 100. Cap it at 100 (you can't score above perfect).</p>
            <p className="text-brand-300 mt-1.5">Example: If a garage's SLA Hit Rate is 85% and the target is 100%, the score = 85 ÷ 100 × 100 = <strong>85 points</strong>.</p>
          </div>
        </div>
        <div>
          <h5 className="font-semibold text-xs text-white mb-1">For metrics where lower is better (Response Time, Could Not Wait, Decline, Dispatch Speed):</h5>
          <div className="bg-slate-900/50 rounded-lg p-3 text-xs text-slate-300 leading-relaxed">
            <p>If the garage meets or beats the target, they get a perfect 100. If they're worse than the target, the score drops proportionally — the further past the target, the lower the score.</p>
            <p className="text-brand-300 mt-1.5">Example: If median response time is 45 min (the target), score = <strong>100 points</strong>. If it's 60 min (15 min over), score drops to about <strong>67 points</strong>.</p>
          </div>
        </div>
        <div>
          <h5 className="font-semibold text-xs text-white mb-1">Putting it all together:</h5>
          <div className="bg-slate-900/50 rounded-lg p-3 text-xs text-slate-300 leading-relaxed">
            <p>Multiply each dimension's score by its weight, add everything up. If a dimension has no data (e.g., no surveys yet), it's skipped and the other weights are adjusted so it still adds to 100%.</p>
            <p className="text-brand-300 mt-1.5">
              Example: SLA score 85 × 30% = 25.5, Completion 95 × 15% = 14.25, Satisfaction 80 × 15% = 12, Response 100 × 10% = 10,
              PTA 90 × 10% = 9, CNW 100 × 10% = 10, Dispatch 100 × 5% = 5, Decline 100 × 5% = 5.
              Total = 25.5 + 14.25 + 12 + 10 + 9 + 10 + 5 + 5 = <strong>90.75 → Grade A</strong>.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Business Rules Section ──
function RulesSection() {
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

// ═══════════════════════════════════════════════════════════════════════════════
// OPS RECOMMENDATIONS SECTION — Fleet vs Towbook driver assignment challenges
// ═══════════════════════════════════════════════════════════════════════════════

function OpsRecommendationsSection() {
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

// ═══════════════════════════════════════════════════════════════════════════════
// DATA DICTIONARY SECTION — Searchable & Sortable Table
// ═══════════════════════════════════════════════════════════════════════════════

function DictionarySection({ data }) {
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState('entity')
  const [sortDir, setSortDir] = useState('asc')
  const [entityFilter, setEntityFilter] = useState('all')

  const toggleSort = useCallback((key) => {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('asc') }
  }, [sortKey])

  const entities = useMemo(() => {
    if (!data?.entities) return []
    return data.entities.map(e => e.name).sort()
  }, [data])

  const filtered = useMemo(() => {
    if (!data?.fields) return []
    let rows = data.fields
    if (entityFilter !== 'all') rows = rows.filter(f => f.entity === entityFilter)
    if (search) {
      const q = search.toLowerCase()
      rows = rows.filter(f =>
        f.entity.toLowerCase().includes(q) ||
        f.entityLabel.toLowerCase().includes(q) ||
        f.apiName.toLowerCase().includes(q) ||
        f.label.toLowerCase().includes(q) ||
        f.description.toLowerCase().includes(q) ||
        f.type.toLowerCase().includes(q) ||
        f.fleetContractor.toLowerCase().includes(q) ||
        (f.usedIn || []).some(u => u.toLowerCase().includes(q)) ||
        f.category.toLowerCase().includes(q)
      )
    }
    rows = [...rows].sort((a, b) => {
      let va, vb
      switch (sortKey) {
        case 'entity': va = a.entityLabel; vb = b.entityLabel; break
        case 'field': va = a.label; vb = b.label; break
        case 'type': va = a.type; vb = b.type; break
        case 'fleet': va = a.fleetContractor; vb = b.fleetContractor; break
        default: va = a.entityLabel; vb = b.entityLabel
      }
      const cmp = va.localeCompare(vb)
      return sortDir === 'asc' ? cmp : -cmp
    })
    return rows
  }, [data, search, sortKey, sortDir, entityFilter])

  if (!data) return <div className="flex items-center justify-center py-20 gap-3"><Loader2 className="w-5 h-5 animate-spin text-brand-400" /><span className="text-slate-500 text-sm">Loading dictionary...</span></div>

  const SortHeader = ({ k, children, className }) => (
    <th onClick={() => toggleSort(k)}
      className={clsx('text-left py-2.5 px-3 text-[10px] font-bold uppercase tracking-wider text-slate-500 cursor-pointer hover:text-brand-300 select-none', className)}>
      <span className="inline-flex items-center gap-1">
        {children}
        {sortKey === k && <ArrowUpDown className="w-3 h-3 text-brand-400" />}
      </span>
    </th>
  )

  return (
    <div>
      <SectionHeader title="Data Dictionary" subtitle={`${data.fields.length} fields across ${data.entities.length} Salesforce objects — every field used in this app.`} />

      {/* Search + Entity filter */}
      <div className="flex flex-wrap gap-3 mt-4 mb-4">
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
          <input value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search fields, descriptions, usage..."
            className="w-full pl-9 pr-4 py-2 bg-slate-900 border border-slate-700 rounded-xl text-sm placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-brand-500/40" />
        </div>
        <div className="flex items-center gap-2">
          <Filter className="w-3.5 h-3.5 text-slate-500" />
          <select value={entityFilter} onChange={e => setEntityFilter(e.target.value)}
            className="bg-slate-900 border border-slate-700 rounded-lg text-xs text-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand-500/40">
            <option value="all">All Entities ({data.fields.length})</option>
            {entities.map(e => {
              const cnt = data.fields.filter(f => f.entity === e).length
              return <option key={e} value={e}>{e} ({cnt})</option>
            })}
          </select>
        </div>
      </div>

      <div className="text-[10px] text-slate-600 mb-2">
        {filtered.length} field{filtered.length !== 1 ? 's' : ''} shown
        {search && ` matching "${search}"`}
      </div>

      {/* Table */}
      <div className="glass rounded-xl overflow-hidden border border-slate-700/20">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="border-b border-slate-700/50 bg-slate-900/30">
              <tr>
                <SortHeader k="entity" className="w-[160px]">Entity</SortHeader>
                <SortHeader k="field" className="w-[180px]">Field</SortHeader>
                <SortHeader k="type" className="w-[100px]">Type</SortHeader>
                <th className="text-left py-2.5 px-3 text-[10px] font-bold uppercase tracking-wider text-slate-500">Description</th>
                <SortHeader k="fleet" className="w-[110px]">Fleet / Contractor</SortHeader>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/30">
              {filtered.map((f, i) => (
                <tr key={`${f.entity}.${f.apiName}`} className={clsx('hover:bg-slate-800/20', i % 2 === 0 && 'bg-slate-900/10')}>
                  <td className="px-3 py-3 align-top">
                    <div className="font-semibold text-slate-300 text-[11px]">{f.entityLabel}</div>
                    <div className="text-[9px] text-slate-600 mt-0.5">{f.entity}</div>
                  </td>
                  <td className="px-3 py-3 align-top">
                    <div className="font-semibold text-brand-300 text-[11px]">{f.label}</div>
                    <div className="font-mono text-[9px] text-slate-500 mt-0.5">{f.apiName}</div>
                    {f.custom && <span className="inline-block mt-1 text-[8px] bg-amber-950/30 text-amber-400 border border-amber-800/30 rounded px-1 py-0.5 font-bold">CUSTOM</span>}
                  </td>
                  <td className="px-3 py-3 align-top text-slate-400 whitespace-nowrap">{f.type}</td>
                  <td className="px-3 py-3 align-top">
                    <p className="text-slate-300 leading-relaxed">{f.description}</p>
                    {f.usedIn && f.usedIn.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1.5">
                        {f.usedIn.map(u => (
                          <span key={u} className="px-1.5 py-0.5 bg-slate-800 text-slate-500 rounded text-[9px]">{u}</span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-3 align-top">
                    <span className={clsx('text-[10px] font-medium',
                      f.fleetContractor === 'Both' ? 'text-slate-400' :
                      f.fleetContractor.includes('Fleet') ? 'text-blue-400' :
                      f.fleetContractor.includes('Contractor') ? 'text-orange-400' :
                      f.fleetContractor.includes('Distinguishes') ? 'text-purple-400' :
                      'text-slate-400'
                    )}>
                      {f.fleetContractor}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {filtered.length === 0 && (
          <div className="text-center py-12 text-slate-600 text-sm">No fields match your search.</div>
        )}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// FLOATING CHAT — Bottom-right overlay (Intercom/Zendesk style)
// ═══════════════════════════════════════════════════════════════════════════════

function FloatingChat() {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [complexity, setComplexity] = useState('mid')
  const scrollRef = useRef(null)

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages, loading])

  const send = async () => {
    const q = input.trim()
    if (!q || loading) return
    setInput('')
    setError('')
    const userMsg = { role: 'user', content: q }
    setMessages(prev => [...prev, userMsg])
    setLoading(true)
    try {
      const history = messages.map(m => ({ role: m.role, content: m.content }))
      const res = await askChatbot(q, complexity, history)
      setMessages(prev => [...prev, { role: 'assistant', content: res.answer, model: res.model }])
    } catch (e) {
      const detail = e.response?.data?.detail || e.message
      // Critical security violation — force logout
      if (detail === 'security_violation' || e.response?.status === 403) {
        setMessages(prev => [...prev, { role: 'assistant', content: 'Session terminated due to security policy violation. You have been logged out.', isError: true }])
        setTimeout(() => { window.location.href = '/login' }, 2000)
        return
      }
      setError(detail)
      setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${detail}`, isError: true }])
    } finally { setLoading(false) }
  }

  const handleKey = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }

  return (
    <>
      {/* Floating Action Button */}
      <button onClick={() => setOpen(o => !o)}
        className={clsx(
          'fixed bottom-6 right-6 z-50 w-14 h-14 rounded-full shadow-2xl flex items-center justify-center transition-all',
          open
            ? 'bg-slate-700 hover:bg-slate-600 rotate-0'
            : 'bg-brand-600 hover:bg-brand-500 shadow-brand-600/30'
        )}>
        {open
          ? <X className="w-6 h-6 text-white" />
          : <MessageCircle className="w-6 h-6 text-white" />
        }
      </button>

      {/* Chat Panel */}
      {open && (
        <div className="fixed bottom-24 right-6 z-50 w-[380px] glass rounded-2xl border border-slate-700/40 shadow-2xl shadow-black/40 flex flex-col"
          style={{ height: 'min(560px, calc(100vh - 140px))' }}>
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/30 rounded-t-2xl">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full bg-brand-600/20 flex items-center justify-center">
                <Bot className="w-4 h-4 text-brand-400" />
              </div>
              <div>
                <div className="font-semibold text-sm text-white">FleetPulse Assistant</div>
                <div className="text-[10px] text-slate-500">Ask about data, metrics, calculations</div>
              </div>
            </div>
            <select value={complexity} onChange={e => setComplexity(e.target.value)}
              className="bg-slate-900 border border-slate-700 rounded text-[10px] text-slate-400 px-1.5 py-1 focus:outline-none">
              <option value="low">Quick</option>
              <option value="mid">Standard</option>
              <option value="high">Deep</option>
            </select>
          </div>

          {/* Messages */}
          <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
            {messages.length === 0 && (
              <div className="text-center py-6 space-y-3">
                <Bot className="w-8 h-8 text-brand-400/40 mx-auto" />
                <p className="text-xs text-slate-500">Ask me anything about FSL data, metrics, or calculations.</p>
                <div className="space-y-1.5">
                  {['How do you calculate ATA?', 'What fields capture when a call is assigned?', 'How does the composite score work?'].map(q => (
                    <button key={q} onClick={() => setInput(q)}
                      className="block w-full text-left text-[11px] text-slate-400 hover:text-brand-300 bg-slate-800/30 hover:bg-slate-800/60 rounded-lg px-3 py-2 transition-colors">
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={clsx('flex gap-2', m.role === 'user' ? 'justify-end' : 'justify-start')}>
                {m.role === 'assistant' && (
                  <div className="w-6 h-6 rounded-full bg-brand-600/20 flex items-center justify-center shrink-0 mt-0.5">
                    <Bot className="w-3.5 h-3.5 text-brand-400" />
                  </div>
                )}
                <div className={clsx('rounded-xl px-3 py-2 text-xs leading-relaxed max-w-[85%]',
                  m.role === 'user'
                    ? 'bg-brand-600/20 text-brand-200'
                    : m.isError ? 'bg-red-950/30 text-red-300 border border-red-800/30'
                    : 'bg-slate-800/50 text-slate-300'
                )}>
                  <div className="whitespace-pre-wrap">{m.content}</div>
                  {m.model && <div className="text-[9px] text-slate-600 mt-1">{m.model}</div>}
                </div>
                {m.role === 'user' && (
                  <div className="w-6 h-6 rounded-full bg-slate-700/50 flex items-center justify-center shrink-0 mt-0.5">
                    <User className="w-3.5 h-3.5 text-slate-400" />
                  </div>
                )}
              </div>
            ))}
            {loading && (
              <div className="flex gap-2">
                <div className="w-6 h-6 rounded-full bg-brand-600/20 flex items-center justify-center shrink-0">
                  <Bot className="w-3.5 h-3.5 text-brand-400" />
                </div>
                <div className="bg-slate-800/50 rounded-xl px-3 py-2">
                  <Loader2 className="w-4 h-4 animate-spin text-brand-400" />
                </div>
              </div>
            )}
          </div>

          {/* Input */}
          <div className="px-3 py-3 border-t border-slate-700/30 rounded-b-2xl">
            <div className="flex gap-2">
              <input value={input} onChange={e => setInput(e.target.value)} onKeyDown={handleKey}
                placeholder="Ask about fields, metrics, calculations..."
                disabled={loading}
                className="flex-1 bg-slate-900 border border-slate-700 rounded-lg text-xs px-3 py-2 placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-brand-500/40 disabled:opacity-50" />
              <button onClick={send} disabled={!input.trim() || loading}
                className="px-3 py-2 bg-brand-600 hover:bg-brand-500 disabled:opacity-30 rounded-lg text-white transition-colors">
                <Send className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// DATA QUALITY SECTION
// ═══════════════════════════════════════════════════════════════════════════════

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

function QualitySection() {
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

// ═══════════════════════════════════════════════════════════════════════════════
// DATA MODEL DIAGRAM — Custom ER Visualization
// ═══════════════════════════════════════════════════════════════════════════════

const MODEL_ENTITIES = [
  // Row 0 — top (Work Type + Skills)
  { id: 'WorkType',           label: 'WorkType',              x: 60,  y: 10,  w: 150, h: 54, color: '#6366f1', fields: 2,  cat: 'Core' },
  { id: 'SkillReq',           label: 'SkillRequirement',      x: 400, y: 10,  w: 170, h: 54, color: '#10b981', fields: 3,  cat: 'Junction' },
  { id: 'Skill',              label: 'Skill',                 x: 700, y: 10,  w: 150, h: 54, color: '#6366f1', fields: 2,  cat: 'Fleet' },
  // Row 1 — core objects
  { id: 'WorkOrder',          label: 'WorkOrder',             x: 10,  y: 120, w: 160, h: 54, color: '#6366f1', fields: 4,  cat: 'Core' },
  { id: 'ServiceAppointment', label: 'ServiceAppointment',    x: 220, y: 100, w: 210, h: 80, color: '#8b5cf6', fields: 31, cat: 'Core', primary: true },
  { id: 'ServiceTerritory',   label: 'ServiceTerritory',      x: 490, y: 120, w: 180, h: 54, color: '#6366f1', fields: 10, cat: 'Core' },
  { id: 'Account',            label: 'Account',               x: 720, y: 120, w: 150, h: 54, color: '#64748b', fields: 3,  cat: 'Core' },
  // Row 2 — junctions + custom
  { id: 'SAHistory',          label: 'SA History',             x: 10,  y: 240, w: 160, h: 54, color: '#f59e0b', fields: 5,  cat: 'Audit' },
  { id: 'AssignedResource',   label: 'AssignedResource',       x: 220, y: 240, w: 170, h: 54, color: '#10b981', fields: 2,  cat: 'Junction' },
  { id: 'STMember',           label: 'ServiceTerritoryMember', x: 440, y: 240, w: 200, h: 54, color: '#10b981', fields: 3,  cat: 'Junction' },
  { id: 'PriorityMatrix',     label: 'ERS_Territory_Priority_Matrix__c', x: 680, y: 240, w: 200, h: 54, color: '#f97316', fields: 4, cat: 'Custom' },
  // Row 3 — fleet & resources
  { id: 'Survey',             label: 'Survey_Result__c',       x: 10,  y: 350, w: 170, h: 54, color: '#f97316', fields: 3,  cat: 'Custom' },
  { id: 'ServiceResource',    label: 'ServiceResource',        x: 280, y: 350, w: 180, h: 54, color: '#6366f1', fields: 8,  cat: 'Fleet' },
  { id: 'SRSkill',            label: 'ServiceResourceSkill',   x: 530, y: 350, w: 190, h: 54, color: '#10b981', fields: 2,  cat: 'Junction' },
  { id: 'Polygon',            label: 'FSL__Polygon__c',        x: 770, y: 350, w: 150, h: 54, color: '#64748b', fields: 5,  cat: 'Managed' },
  // Row 4 — availability + trucks
  { id: 'Asset',              label: 'Asset (ERS Truck)',      x: 10,  y: 460, w: 170, h: 54, color: '#6366f1', fields: 5,  cat: 'Fleet' },
  { id: 'Shift',              label: 'Shift',                  x: 240, y: 460, w: 150, h: 54, color: '#6366f1', fields: 6,  cat: 'Fleet' },
  { id: 'ResAbsence',         label: 'ResourceAbsence',        x: 440, y: 460, w: 180, h: 54, color: '#6366f1', fields: 5,  cat: 'Fleet' },
  { id: 'PTAConfig',          label: 'ERS_SA_PTA__c',          x: 680, y: 460, w: 170, h: 54, color: '#f97316', fields: 3,  cat: 'Custom' },
  // Row 5 — scheduling engine
  { id: 'SchedPolicy',        label: 'Scheduling_Policy__c',   x: 60,  y: 560, w: 190, h: 54, color: '#64748b', fields: 3,  cat: 'Managed' },
  { id: 'PolicyGoal',         label: 'Policy_Goal__c',         x: 300, y: 560, w: 170, h: 54, color: '#64748b', fields: 3,  cat: 'Managed' },
  { id: 'ServiceGoal',        label: 'Service_Goal__c',        x: 520, y: 560, w: 170, h: 54, color: '#64748b', fields: 2,  cat: 'Managed' },
  { id: 'PolicyRule',          label: 'Policy_Work_Rule__c',   x: 300, y: 640, w: 170, h: 54, color: '#64748b', fields: 2,  cat: 'Managed' },
  { id: 'WorkRule',            label: 'Work_Rule__c',          x: 520, y: 640, w: 170, h: 54, color: '#64748b', fields: 2,  cat: 'Managed' },
]

const MODEL_LINES = [
  // Core SA relationships
  { from: 'ServiceAppointment', to: 'ServiceTerritory',   label: 'ServiceTerritoryId', type: 'M:1' },
  { from: 'ServiceAppointment', to: 'WorkType',           label: 'WorkTypeId',         type: 'M:1' },
  { from: 'WorkOrder',          to: 'ServiceAppointment', label: 'parent',             type: '1:M' },
  { from: 'WorkOrder',          to: 'Survey',             label: 'WO Number join',     type: '1:M' },
  { from: 'AssignedResource',   to: 'ServiceAppointment', label: 'SA ↔ Driver',        type: 'M:1' },
  { from: 'AssignedResource',   to: 'ServiceResource',    label: 'ResourceId',         type: 'M:1' },
  { from: 'SAHistory',          to: 'ServiceAppointment', label: 'audit trail',        type: 'M:1' },
  // Territory relationships
  { from: 'STMember',           to: 'ServiceTerritory',   label: 'TerritoryId',        type: 'M:1' },
  { from: 'STMember',           to: 'ServiceResource',    label: 'ResourceId',         type: 'M:1' },
  { from: 'ServiceTerritory',   to: 'Account',            label: 'Facility Account',   type: 'M:1' },
  { from: 'PriorityMatrix',     to: 'ServiceTerritory',   label: 'Parent / Spotted',   type: 'M:1' },
  { from: 'Polygon',            to: 'ServiceTerritory',   label: 'Territory boundary', type: 'M:1' },
  // Skill chain
  { from: 'SRSkill',            to: 'ServiceResource',    label: 'ResourceId',         type: 'M:1' },
  { from: 'SRSkill',            to: 'Skill',              label: 'SkillId',            type: 'M:1' },
  { from: 'SkillReq',           to: 'WorkType',           label: 'RelatedRecordId',    type: 'M:1' },
  { from: 'SkillReq',           to: 'Skill',              label: 'SkillId',            type: 'M:1' },
  // Fleet availability
  { from: 'Asset',              to: 'ServiceResource',    label: 'ERS_Driver__c',      type: 'M:1' },
  { from: 'Shift',              to: 'ServiceResource',    label: 'ServiceResourceId',  type: 'M:1' },
  { from: 'Shift',              to: 'ServiceTerritory',   label: 'ServiceTerritoryId', type: 'M:1' },
  { from: 'ResAbsence',         to: 'ServiceResource',    label: 'ResourceId',         type: 'M:1' },
  { from: 'PTAConfig',          to: 'ServiceTerritory',   label: 'ERS_Service_Territory__c', type: 'M:1' },
  // Scheduling engine
  { from: 'PolicyGoal',         to: 'SchedPolicy',        label: 'Policy ref',         type: 'M:1' },
  { from: 'PolicyGoal',         to: 'ServiceGoal',        label: 'Goal ref',           type: 'M:1' },
  { from: 'PolicyRule',         to: 'SchedPolicy',        label: 'Policy ref',         type: 'M:1' },
  { from: 'PolicyRule',         to: 'WorkRule',            label: 'Rule ref',           type: 'M:1' },
]

// Map MODEL_ENTITIES id → dictionary entity name
const ENTITY_ID_TO_NAME = {
  WorkType: 'WorkType', SkillReq: 'SkillRequirement', Skill: 'Skill',
  WorkOrder: 'WorkOrder', ServiceAppointment: 'ServiceAppointment',
  ServiceTerritory: 'ServiceTerritory', Account: 'Account',
  SAHistory: 'ServiceAppointmentHistory', AssignedResource: 'AssignedResource',
  STMember: 'ServiceTerritoryMember', PriorityMatrix: 'ERS_Territory_Priority_Matrix__c',
  Survey: 'Survey_Result__c', ServiceResource: 'ServiceResource',
  SRSkill: 'ServiceResourceSkill', Polygon: 'FSL__Polygon__c',
  Asset: 'Asset', Shift: 'Shift', ResAbsence: 'ResourceAbsence',
  PTAConfig: 'ERS_Service_Appointment_PTA__c', SchedPolicy: 'FSL__Scheduling_Policy__c',
  PolicyGoal: 'FSL__Policy_Goal__c', ServiceGoal: 'FSL__Service_Goal__c',
  PolicyRule: 'FSL__Policy_Work_Rule__c', WorkRule: 'FSL__Work_Rule__c',
}

function DataModelSection({ data }) {
  const svgW = 940
  const svgH = 720
  const [selectedEntity, setSelectedEntity] = useState(null)
  const detailRef = useRef(null)

  // Build field lookup: entityName → fields[]
  const fieldsByEntity = useMemo(() => {
    if (!data?.fields) return {}
    const map = {}
    data.fields.forEach(f => {
      if (!map[f.entity]) map[f.entity] = []
      map[f.entity].push(f)
    })
    return map
  }, [data])

  // Build entity description lookup
  const entityDesc = useMemo(() => {
    if (!data?.entities) return {}
    const map = {}
    data.entities.forEach(e => { map[e.name] = e })
    return map
  }, [data])

  const getCenter = (id) => {
    const e = MODEL_ENTITIES.find(n => n.id === id)
    if (!e) return { x: 0, y: 0 }
    return { x: e.x + e.w / 2, y: e.y + e.h / 2 }
  }

  const handleEntityClick = (entityId) => {
    setSelectedEntity(prev => prev === entityId ? null : entityId)
    setTimeout(() => detailRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 100)
  }

  const selName = selectedEntity ? ENTITY_ID_TO_NAME[selectedEntity] : null
  const selMeta = selName ? entityDesc[selName] : null
  const selFields = selName ? (fieldsByEntity[selName] || []) : []

  return (
    <div>
      {/* Legend */}
      <div className="flex flex-wrap gap-4 mt-1 mb-4 text-[10px]">
        <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded bg-[#8b5cf6]" /> Primary Object</span>
        <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded bg-[#6366f1]" /> Standard Object</span>
        <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded bg-[#10b981]" /> Junction Object</span>
        <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded bg-[#f97316]" /> Custom Object</span>
        <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded bg-[#64748b]" /> Supporting</span>
        <span className="text-slate-600 ml-2">Click any entity to see its fields</span>
      </div>

      {/* Diagram */}
      <div className="glass rounded-xl border border-slate-700/20 overflow-x-auto p-4">
        <div className="relative" style={{ width: svgW, height: svgH, minWidth: svgW }}>
          {/* SVG lines */}
          <svg className="absolute inset-0" width={svgW} height={svgH} style={{ pointerEvents: 'none' }}>
            <defs>
              <marker id="arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="6" markerHeight="6" orient="auto">
                <path d="M0,0 L10,5 L0,10 z" fill="#475569" />
              </marker>
            </defs>
            {MODEL_LINES.map((line, i) => {
              const from = getCenter(line.from)
              const to = getCenter(line.to)
              const mx = (from.x + to.x) / 2
              const my = (from.y + to.y) / 2
              return (
                <g key={i}>
                  <line x1={from.x} y1={from.y} x2={to.x} y2={to.y}
                    stroke="#334155" strokeWidth="1.5" markerEnd="url(#arrow)" />
                  <rect x={mx - 35} y={my - 8} width={70} height={16} rx={4} fill="#0f172a" stroke="#334155" strokeWidth="0.5" />
                  <text x={mx} y={my + 3} textAnchor="middle" fill="#64748b" fontSize="8" fontFamily="monospace">
                    {line.type}
                  </text>
                </g>
              )
            })}
          </svg>

          {/* Entity boxes */}
          {MODEL_ENTITIES.map(e => {
            const isSelected = selectedEntity === e.id
            return (
              <div key={e.id}
                onClick={() => handleEntityClick(e.id)}
                className={clsx(
                  'absolute rounded-lg border-2 px-3 py-2 shadow-lg cursor-pointer transition-all hover:brightness-125',
                  e.primary && 'ring-2 ring-purple-500/30',
                  isSelected && 'ring-2 ring-brand-400/60 brightness-125'
                )}
                style={{
                  left: e.x, top: e.y, width: e.w, height: e.h,
                  backgroundColor: '#0f172a',
                  borderColor: isSelected ? '#60a5fa' : e.color + '60',
                }}>
                <div className="flex items-center gap-1.5">
                  <div className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: e.color }} />
                  <span className="font-bold text-[10px] text-white truncate">{e.label}</span>
                </div>
                <div className="flex items-center justify-between mt-1">
                  <span className="text-[9px] text-slate-500">{e.cat}</span>
                  <span className="text-[9px] text-slate-600">{e.fields} fields</span>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Selected entity field detail */}
      {selectedEntity && selFields.length > 0 && (
        <div ref={detailRef} className="mt-4 glass rounded-xl border border-brand-500/30 p-4">
          <div className="flex items-start justify-between mb-3">
            <div>
              <h4 className="text-sm font-bold text-white flex items-center gap-2">
                <Database className="w-4 h-4 text-brand-400" />
                {selMeta?.label || selectedEntity}
                <code className="text-[10px] font-mono text-slate-500 ml-1">{selName}</code>
              </h4>
              {selMeta?.description && (
                <p className="text-[11px] text-slate-400 mt-1 max-w-3xl leading-relaxed">{selMeta.description}</p>
              )}
            </div>
            <button onClick={() => setSelectedEntity(null)} className="p-1 rounded hover:bg-slate-800 text-slate-500 hover:text-white">
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="border-b border-slate-700/50 bg-slate-900/30">
                <tr>
                  <th className="text-left py-2 px-3 text-[10px] font-bold uppercase tracking-wider text-slate-500 w-[200px]">SF Field (API Name)</th>
                  <th className="text-left py-2 px-3 text-[10px] font-bold uppercase tracking-wider text-slate-500 w-[140px]">Label</th>
                  <th className="text-left py-2 px-3 text-[10px] font-bold uppercase tracking-wider text-slate-500 w-[80px]">Type</th>
                  <th className="text-left py-2 px-3 text-[10px] font-bold uppercase tracking-wider text-slate-500">Description</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/30">
                {selFields.map((f, i) => (
                  <tr key={f.apiName} className={i % 2 === 0 ? 'bg-slate-900/10' : ''}>
                    <td className="px-3 py-2 font-mono text-brand-300 text-[11px]">
                      {f.apiName}
                      {f.custom && <span className="ml-1.5 text-[8px] bg-amber-950/30 text-amber-400 border border-amber-800/30 rounded px-1 py-0.5 font-bold">CUSTOM</span>}
                    </td>
                    <td className="px-3 py-2 text-slate-300 text-[11px]">{f.label}</td>
                    <td className="px-3 py-2 text-slate-500 whitespace-nowrap">{f.type}</td>
                    <td className="px-3 py-2 text-slate-400 leading-relaxed">{f.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {selectedEntity && selFields.length === 0 && (
        <div ref={detailRef} className="mt-4 glass rounded-xl border border-slate-700/20 p-4 text-center text-sm text-slate-500">
          No field data available for this entity in the dictionary.
        </div>
      )}

      {/* Relationship table */}
      <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mt-6 mb-2">Relationships</h4>
      <div className="glass rounded-xl overflow-hidden border border-slate-700/20">
        <table className="w-full text-xs">
          <thead className="border-b border-slate-700/50 bg-slate-900/30">
            <tr>
              <th className="text-left py-2 px-3 text-[10px] font-bold uppercase tracking-wider text-slate-500 w-[200px]">From</th>
              <th className="text-center py-2 px-3 text-[10px] font-bold uppercase tracking-wider text-slate-500 w-[60px]">Type</th>
              <th className="text-left py-2 px-3 text-[10px] font-bold uppercase tracking-wider text-slate-500 w-[200px]">To</th>
              <th className="text-left py-2 px-3 text-[10px] font-bold uppercase tracking-wider text-slate-500">Relationship</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/30">
            {MODEL_LINES.map((r, i) => (
              <tr key={i} className={i % 2 === 0 ? 'bg-slate-900/10' : ''}>
                <td className="px-3 py-2 font-mono text-brand-300 text-[11px]">{r.from}</td>
                <td className="px-3 py-2 text-center text-slate-500 text-[10px] font-bold">{r.type}</td>
                <td className="px-3 py-2 font-mono text-brand-300 text-[11px]">{r.to}</td>
                <td className="px-3 py-2 text-slate-400">{r.label}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// COMBINED DATA & MODEL — Tabbed view (Dictionary + ER Diagram)
// ═══════════════════════════════════════════════════════════════════════════════

function DataSection({ data }) {
  const [tab, setTab] = useState('dictionary')
  return (
    <div>
      <SectionHeader title="Data & Model" subtitle="All Salesforce objects, fields, and relationships in one place." />
      <div className="flex gap-1 mb-5 border-b border-slate-800/50 pb-2">
        <button onClick={() => setTab('dictionary')}
          className={clsx('flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-all',
            tab === 'dictionary'
              ? 'bg-brand-600/20 text-brand-300 border border-brand-500/30'
              : 'text-slate-400 hover:text-white hover:bg-slate-800/50 border border-transparent'
          )}>
          <Database className="w-3.5 h-3.5" /> Dictionary
        </button>
        <button onClick={() => setTab('model')}
          className={clsx('flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-all',
            tab === 'model'
              ? 'bg-brand-600/20 text-brand-300 border border-brand-500/30'
              : 'text-slate-400 hover:text-white hover:bg-slate-800/50 border border-transparent'
          )}>
          <Share2 className="w-3.5 h-3.5" /> Data Model
        </button>
      </div>
      {tab === 'dictionary' ? <DictionarySection data={data} /> : <DataModelSection data={data} />}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// SHARED COMPONENTS
// ═══════════════════════════════════════════════════════════════════════════════

function SectionHeader({ title, subtitle }) {
  return (
    <div className="mb-2">
      <h2 className="text-lg font-bold text-white">{title}</h2>
      {subtitle && <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT — Horizontal Tabs + Landing Cards + Floating Chat
// ═══════════════════════════════════════════════════════════════════════════════

export default function Help() {
  const [activeSection, setActiveSection] = useState(null) // null = landing
  const [dictionary, setDictionary] = useState(null)

  useEffect(() => {
    fetch('/data/fsl-dictionary.json')
      .then(r => r.json())
      .then(setDictionary)
      .catch(() => {})
  }, [])

  const renderSection = () => {
    switch (activeSection) {
      case 'howitworks': return <HowItWorksSection />
      case 'overview':   return <OverviewSection />
      case 'metrics':    return <MetricsSection />
      case 'scoring':    return <ScoringSection />
      case 'data':       return <DataSection data={dictionary} />
      case 'quality':    return <QualitySection />
      case 'rules':      return <RulesSection />
      case 'ops':        return <OpsRecommendationsSection />
      default:           return <LandingCards onSelect={setActiveSection} />
    }
  }

  return (
    <div style={{ minHeight: 'calc(100vh - 120px)' }}>
      {/* ── Horizontal Tab Bar ── */}
      {activeSection && (
        <div className="flex items-center gap-1 mb-6 pb-3 border-b border-slate-800/50 overflow-x-auto">
          <button onClick={() => setActiveSection(null)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm text-slate-500 hover:text-white hover:bg-slate-800 transition-all shrink-0 mr-1">
            <ArrowLeft className="w-3.5 h-3.5" />
            <span className="text-xs">All Topics</span>
          </button>
          <div className="w-px h-5 bg-slate-800 mr-1" />
          {SECTIONS.map(s => (
            <button key={s.id} onClick={() => setActiveSection(s.id)}
              className={clsx(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-all whitespace-nowrap shrink-0',
                activeSection === s.id
                  ? 'bg-brand-600/20 text-brand-300 border border-brand-500/30'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800/50 border border-transparent'
              )}>
              <s.icon className="w-3.5 h-3.5" />
              {s.label}
            </button>
          ))}
        </div>
      )}

      {/* ── Content ── */}
      <AnimatePresence mode="wait">
        <motion.div key={activeSection || 'landing'}
          initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}
          transition={{ duration: 0.25 }}>
          {renderSection()}
        </motion.div>
      </AnimatePresence>

      {/* Chat is now global in Layout */}
    </div>
  )
}
