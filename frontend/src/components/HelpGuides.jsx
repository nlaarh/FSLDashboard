import { useState } from 'react'
import {
  Radio, LayoutDashboard, ListOrdered, Clock, CloudSun, ArrowRightLeft,
  ChevronDown, ChevronRight, CheckCircle2, ThumbsUp, XCircle, Award, Users,
} from 'lucide-react'
import { clsx } from 'clsx'
import { motion, AnimatePresence } from 'framer-motion'
import { SectionHeader, FieldTag, InfoCard } from './HelpHowItWorks'

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
const GRADES = [
  { grade: 'A', range: '90 – 100', color: 'text-emerald-400 bg-emerald-950/40 border-emerald-700/30' },
  { grade: 'B', range: '80 – 89',  color: 'text-blue-400 bg-blue-950/40 border-blue-700/30' },
  { grade: 'C', range: '70 – 79',  color: 'text-amber-400 bg-amber-950/40 border-amber-700/30' },
  { grade: 'D', range: '60 – 69',  color: 'text-orange-400 bg-orange-950/40 border-orange-700/30' },
  { grade: 'F', range: '0 – 59',   color: 'text-red-400 bg-red-950/40 border-red-700/30' },
]

const PAGES = [
  { name: 'Command Center', route: '/', icon: Radio, desc: 'Real-time operational dashboard showing all territories, open calls, driver status, and alerts.' },
  { name: 'Garages', route: '/garages', icon: LayoutDashboard, desc: 'All garage territories with composite score, grade, and key metrics. Click a garage for deep-dive.' },
  { name: 'Queue Board', route: '/queue', icon: ListOrdered, desc: 'Live dispatch queue — open SAs waiting for assignment with driver recommendations and cascade status.' },
  { name: 'PTA Advisor', route: '/pta', icon: Clock, desc: 'Analyzes Promised Time of Arrival patterns. Identifies garages over-promising or under-delivering on ETAs.' },
  { name: 'Forecast', route: '/forecast', icon: CloudSun, desc: '16-day demand forecast using day-of-week patterns and weather data for staffing planning.' },
  { name: 'Territory Matrix', route: '/matrix', icon: ArrowRightLeft, desc: 'Priority matrix advisor — cascade chain effectiveness and zone primary swap recommendations.' },
]

export function HowItWorksTopics567({ expandedTopic, toggle }) {
  return (
    <>
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
    </>
  )
}
export function OverviewSection() {
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

export function ScoringSection() {
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
