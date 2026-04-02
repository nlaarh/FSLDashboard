import { useState, useEffect } from 'react'
import {
  ChevronDown, ChevronRight, CheckCircle2, AlertTriangle,
  MapPin, Phone, Truck, Wrench, Zap, ArrowRightLeft,
} from 'lucide-react'
import { clsx } from 'clsx'
import { motion, AnimatePresence } from 'framer-motion'
import { fetchFeatures } from '../api'

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

export function FieldTag({ name, className }) {
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

export function InfoCard({ title, icon: Icon, color, children }) {
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

export function SectionHeader({ title, subtitle }) {
  return (
    <div className="mb-2">
      <h2 className="text-lg font-bold text-white">{title}</h2>
      {subtitle && <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>}
    </div>
  )
}

export default function HowItWorksSection({ renderTopics567 }) {
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

      {renderTopics567 && renderTopics567({ expandedTopic, toggle })}
    </div>
  )
}
