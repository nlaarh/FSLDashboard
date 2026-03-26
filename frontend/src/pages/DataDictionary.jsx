import { useState, useEffect, useMemo } from 'react'
import { clsx } from 'clsx'
import {
  Search, BookOpen, ShieldCheck, AlertTriangle, CheckCircle2,
  XCircle, ChevronDown, ChevronRight, Clock, Loader2,
  Database, ArrowRight, RefreshCw, Filter,
} from 'lucide-react'
import { fetchDataQuality, refreshDataQuality } from '../api'

// ── Full Field Dictionary ────────────────────────────────────────────────────
// Every field used across the app, grouped by lifecycle stage

const DICTIONARY = [
  // ── 1. CALL CREATION ──
  {
    group: 'Call Creation',
    description: 'Fields set when AAA receives the member call and creates the Service Appointment.',
    fields: [
      {
        field: 'ServiceAppointment.Id',
        object: 'ServiceAppointment',
        label: 'SA Record ID',
        type: 'ID (18-char)',
        description: 'Unique Salesforce record ID for the Service Appointment. Primary key used in all joins and lookups.',
        usedIn: ['All pages'],
      },
      {
        field: 'ServiceAppointment.AppointmentNumber',
        object: 'ServiceAppointment',
        label: 'SA Number',
        type: 'Auto-Number',
        description: 'Human-readable appointment number (e.g., SA-00012345). Displayed in SA lookup, queue board, and detail views.',
        usedIn: ['Command Center SA Lookup', 'Queue Board', 'Garage Detail'],
      },
      {
        field: 'ServiceAppointment.CreatedDate',
        object: 'ServiceAppointment',
        label: 'Call Created Time',
        type: 'DateTime',
        description: 'When the SA was created in Salesforce — the moment the call was received from AAA National. This is the START of the clock for all response time calculations. Fleet ATA = ActualStartTime − CreatedDate. Towbook ATA = On Location history timestamp − CreatedDate.',
        usedIn: ['Response Time', 'SLA Hit Rate', 'ATA', 'Dispatch Speed', 'Wait Time', 'All dashboards'],
      },
      {
        field: 'ServiceAppointment.Status',
        object: 'ServiceAppointment',
        label: 'SA Status',
        type: 'Picklist',
        description: 'Current lifecycle status. Values used: Dispatched (driver assigned, en route), Assigned (waiting for driver), Completed (job done), Canceled, Cancel Call - Service Not En Route, Cancel Call - Service En Route, Unable to Complete, No-Show. Status drives completion rate and open call counts.',
        usedIn: ['Completion Rate', 'Open Calls', 'All dashboards'],
      },
      {
        field: 'WorkOrder.WorkOrderNumber',
        object: 'WorkOrder',
        label: 'Work Order Number',
        type: 'Auto-Number',
        description: 'Parent Work Order number. Used to join SAs to Survey_Result__c records (surveys reference the WO number, not the SA ID).',
        usedIn: ['Satisfaction metrics'],
      },
      {
        field: 'ServiceAppointment.WorkType.Name',
        object: 'WorkType (lookup)',
        label: 'Work Type',
        type: 'Text (via lookup)',
        description: 'Type of service: Tow, Battery, Tire, Lockout, Locksmith, Winch Out, Fuel / Miscellaneous, PVS, Jumpstart, Tow Drop-Off. "Tow Drop-Off" is the second leg of a tow (paired SA) — excluded from all counts to avoid double-counting. Work type determines driver skill matching.',
        usedIn: ['Volume by Type', 'Driver Skill Matching', 'Cascade', 'All dashboards'],
      },
      {
        field: 'ServiceAppointment.Latitude / Longitude',
        object: 'ServiceAppointment',
        label: 'Call Location (GPS)',
        type: 'Number (Geolocation)',
        description: 'GPS coordinates of the member\'s stranded location. Used for map display and distance calculations for driver recommendations.',
        usedIn: ['Command Center Map', 'Dispatch Map', 'Driver Recommendations'],
      },
      {
        field: 'ServiceAppointment.Street / City / PostalCode',
        object: 'ServiceAppointment',
        label: 'Call Address',
        type: 'Text',
        description: 'Address components of the member\'s stranded location. Displayed in SA detail views and territory detail.',
        usedIn: ['Garage Detail', 'Queue Board'],
      },
    ],
  },

  // ── 2. DISPATCH ──
  {
    group: 'Dispatch & Assignment',
    description: 'Fields set during the dispatch process — when a garage accepts and a driver is assigned.',
    fields: [
      {
        field: 'ServiceAppointment.ServiceTerritoryId',
        object: 'ServiceAppointment',
        label: 'Assigned Garage (Territory)',
        type: 'Lookup (ServiceTerritory)',
        description: 'The garage/territory currently assigned to handle this call. This is the garage whose metrics are affected. Changes when a call is cascaded/reassigned to a different garage.',
        usedIn: ['All garage-level metrics', 'Territory grouping'],
      },
      {
        field: 'ServiceTerritory.Name',
        object: 'ServiceTerritory',
        label: 'Garage Name',
        type: 'Text',
        description: 'Display name of the territory/garage (e.g., "Tonawanda Towing"). Shown in the garage list, headers, and map labels.',
        usedIn: ['Garage Operations table', 'All headers'],
      },
      {
        field: 'ServiceTerritory.Latitude / Longitude',
        object: 'ServiceTerritory',
        label: 'Garage Location (GPS)',
        type: 'Number (Geolocation)',
        description: 'GPS coordinates of the garage facility. Used for map display and distance calculations.',
        usedIn: ['Command Center Map', 'Garage Map Markers'],
      },
      {
        field: 'ServiceTerritory.City / State / Street',
        object: 'ServiceTerritory',
        label: 'Garage Address',
        type: 'Text',
        description: 'Address of the garage facility.',
        usedIn: ['Garage Operations table', 'Garage Detail'],
      },
      {
        field: 'ServiceAppointment.ERS_Dispatch_Method__c',
        object: 'ServiceAppointment',
        label: 'Dispatch Method',
        type: 'Picklist (Custom)',
        description: '"Field Services" = internal fleet dispatched via FSL optimization engine. "Towbook" = external contractor dispatched via Towbook system. Determines which dispatch badge (Fleet/Contractor) appears on the garage dashboard.',
        usedIn: ['Dispatch Mix', 'Fleet/Contractor badge', 'Garage Dashboard'],
      },
      {
        field: 'ServiceAppointment.ERS_Auto_Assign__c',
        object: 'ServiceAppointment',
        label: 'Auto-Assigned Flag',
        type: 'Checkbox (Custom)',
        description: 'True = SA was automatically dispatched by FSL optimization (primary/1st-choice dispatch). False/null = manually dispatched (secondary, backup, or Towbook). Drives the Primary vs Secondary acceptance split.',
        usedIn: ['Acceptance Rate (Primary vs Secondary)'],
      },
      {
        field: 'ServiceAppointment.ERS_Parent_Territory__c',
        object: 'ServiceAppointment',
        label: 'Parent (Spotted) Territory',
        type: 'Lookup (Custom)',
        description: 'The zone/territory where the member is stranded (the "spotted" zone). Combined with ERS_Territory_Priority_Matrix__c to determine if this garage is rank 1 (primary/1st call) or rank 2+ (secondary/backup) for that zone.',
        usedIn: ['1st Call %', '2nd+ Call %', 'Primary/Secondary labels'],
      },
      {
        field: 'ServiceAppointment.SchedStartTime',
        object: 'ServiceAppointment',
        label: 'Scheduled Start (Predicted Arrival)',
        type: 'DateTime',
        description: 'The scheduler\'s prediction of when the driver will arrive on site and begin service. Set by FSL optimization engine during auto-dispatch, or manually by a dispatcher. Updated each time the scheduler re-optimizes. Correct decomposition: Dispatch Queue = CreatedDate → AssignedResource.CreatedDate (time waiting for assignment). Estimated Travel = AssignedResource.CreatedDate → SchedStartTime (scheduler\'s predicted travel time). Prediction Error = SchedStartTime → ActualStartTime (how far off the estimate was — positive = late, negative = early).',
        usedIn: ['SA History Report (ETA per assignment)', 'Response Decomposition'],
      },
      {
        field: 'ServiceAppointment.ERS_Facility_Decline_Reason__c',
        object: 'ServiceAppointment',
        label: 'Facility Decline Reason',
        type: 'Picklist (Custom)',
        description: 'Why a garage declined the call (e.g., "No Trucks Available", "Out of Service Area"). Non-null = garage declined. Used for acceptance rate, decline analysis, and the decline reason breakdown chart.',
        usedIn: ['Acceptance Rate', 'Decline Analysis', 'Decline Rate (Scorer)'],
      },
      {
        field: 'ServiceAppointment.ERS_Cancellation_Reason__c',
        object: 'ServiceAppointment',
        label: 'Cancellation Reason',
        type: 'Picklist (Custom)',
        description: 'Why the call was canceled. Key value: "Member Could Not Wait%" — counted for the "Could Not Wait" rate in the scorer. Other values shown in the cancellation breakdown chart.',
        usedIn: ['Cancel Analysis', 'Could Not Wait Rate (Scorer)'],
      },
      {
        field: 'ServiceAppointment.ERS_Spotting_Number__c',
        object: 'ServiceAppointment',
        label: 'Spotting Number',
        type: 'Number (Custom)',
        description: 'Legacy field: which position this SA was in the dispatch sequence. 1 = first garage spotted. > 1 = cascaded. Used as a fallback for 1st Call vs 2nd+ Call classification when SA History is unavailable.',
        usedIn: ['1st Call % (fallback)'],
      },
      {
        field: 'AssignedResource',
        object: 'AssignedResource (junction)',
        label: 'Driver Assignment',
        type: 'Junction Object',
        description: 'Links a ServiceAppointment to a ServiceResource (driver/truck). Created when a driver is assigned. Queried to build the Driver Leaderboard — each AssignedResource row gives us the driver name and lets us join SA timing data to a specific driver.',
        usedIn: ['Driver Leaderboard', 'Dispatch Map'],
      },
      {
        field: 'ServiceResource.Name',
        object: 'ServiceResource',
        label: 'Driver / Truck Name',
        type: 'Text',
        description: 'Name of the driver or truck resource. For Fleet: driver name (e.g., "John Smith"). For Towbook: may be truck identifier (e.g., "Towbook Truck 123"). Displayed on Driver Leaderboard.',
        usedIn: ['Driver Leaderboard', 'Dispatch Recommendations'],
      },
      {
        field: 'ServiceResource.LastKnownLatitude / Longitude',
        object: 'ServiceResource',
        label: 'Driver GPS Position',
        type: 'Number (Geolocation)',
        description: 'Last known GPS position of the driver/truck. Updated by FSL mobile app. Used for distance calculations in driver recommendations and the Command Center driver layer.',
        usedIn: ['Driver Recommendations', 'Command Center Map (Drivers layer)'],
      },
    ],
  },

  // ── 3. PTA / ETA ──
  {
    group: 'PTA / ETA Promise',
    description: 'Fields related to the Promised Time of Arrival given to the member.',
    fields: [
      {
        field: 'ServiceAppointment.ERS_PTA__c',
        object: 'ServiceAppointment',
        label: 'PTA (Minutes)',
        type: 'Number (Custom)',
        description: 'Minutes promised to the member at dispatch time. For Fleet: calculated by FSL optimization based on driver distance + availability. For Towbook: entered by Towbook dispatcher (often a rough estimate). Values of 0 or >= 999 are sentinel/invalid and excluded from calculations.',
        usedIn: ['Avg PTA', 'PTA Accuracy', 'ETA Accuracy', 'PTA Advisor', 'PTA-ATA Delta'],
      },
      {
        field: 'ServiceAppointment.ERS_PTA_Due__c',
        object: 'ServiceAppointment',
        label: 'PTA Due Time',
        type: 'DateTime (Custom)',
        description: 'The absolute timestamp when the driver was promised to arrive (CreatedDate + ERS_PTA__c minutes). Displayed in the Queue Board to show when calls are approaching or past their PTA deadline.',
        usedIn: ['Queue Board (PTA due indicator)'],
      },
    ],
  },

  // ── 4. ARRIVAL & COMPLETION ──
  {
    group: 'Arrival & Completion',
    description: 'Fields set when the driver arrives and completes the job.',
    fields: [
      {
        field: 'ServiceAppointment.ActualStartTime',
        object: 'ServiceAppointment',
        label: 'Driver Arrival Time',
        type: 'DateTime',
        description: 'For Fleet: set when driver taps "Arrived" in the FSL mobile app — real arrival time. For Towbook: written by "Integrations Towbook" at completion as a future estimate (NOT real arrival). Towbook real arrival comes from ServiceAppointmentHistory Status = "On Location" timestamp. ATA = arrival - CreatedDate.',
        usedIn: ['ATA', 'SLA Hit Rate', 'Response Time', 'ETA Accuracy', 'Driver Leaderboard', 'On-Site Duration start'],
      },
      {
        field: 'ServiceAppointment.ActualEndTime',
        object: 'ServiceAppointment',
        label: 'Job Completion Time',
        type: 'DateTime',
        description: 'When the driver finished the job and marked the SA complete. On-Site Duration = ActualEndTime - ActualStartTime. Total Call Duration = ActualEndTime - CreatedDate.',
        usedIn: ['On-Site Duration', 'Response Decomposition', 'Driver Leaderboard (on-site column)'],
      },
    ],
  },

  // ── 5. TERRITORY MATRIX ──
  {
    group: 'Territory Priority Matrix',
    description: 'Custom object defining which garages serve which zones, and in what priority order.',
    fields: [
      {
        field: 'ERS_Territory_Priority_Matrix__c.ERS_Parent_Service_Territory__c',
        object: 'ERS_Territory_Priority_Matrix__c',
        label: 'Parent Zone (Spotted Territory)',
        type: 'Lookup (Custom)',
        description: 'The zone/territory where members can be stranded. Each parent zone has one or more garages assigned to serve it in priority order.',
        usedIn: ['Territory Matrix page', 'Primary/Secondary labels', '1st Call / 2nd+ Call'],
      },
      {
        field: 'ERS_Territory_Priority_Matrix__c.ERS_Spotted_Territory__c',
        object: 'ERS_Territory_Priority_Matrix__c',
        label: 'Serving Garage',
        type: 'Lookup (Custom)',
        description: 'The garage assigned to serve the parent zone. Multiple garages can serve the same zone at different priority levels.',
        usedIn: ['Territory Matrix page', 'Primary/Secondary labels'],
      },
      {
        field: 'ERS_Territory_Priority_Matrix__c.ERS_Priority__c',
        object: 'ERS_Territory_Priority_Matrix__c',
        label: 'Priority Number',
        type: 'Number (Custom)',
        description: 'Priority ranking for this garage in the zone. Lowest number = first call (primary). Higher numbers = backup (secondary). Rank 1 = "Primary" label on dashboard, Rank 2+ = "Secondary" label.',
        usedIn: ['Primary/Secondary labels', '1st Call %', '2nd+ Call %'],
      },
      {
        field: 'ERS_Territory_Priority_Matrix__c.ERS_Worktype__c',
        object: 'ERS_Territory_Priority_Matrix__c',
        label: 'Work Type Filter',
        type: 'Text (Custom)',
        description: 'Which work types this priority applies to (e.g., "Tow", "Battery/Light"). Some garages may be primary for tow but secondary for battery in the same zone.',
        usedIn: ['Territory Matrix page'],
      },
    ],
  },

  // ── 6. FLEET / RESOURCES ──
  {
    group: 'Fleet & Resources',
    description: 'Driver, truck, and skill data for capacity planning.',
    fields: [
      {
        field: 'ServiceTerritoryMember',
        object: 'ServiceTerritoryMember (junction)',
        label: 'Territory Membership',
        type: 'Junction Object',
        description: 'Links a ServiceResource (driver) to a ServiceTerritory (garage). TerritoryType field distinguishes primary vs secondary membership. Used to count drivers per garage and determine who can be assigned.',
        usedIn: ['Fleet & Volume (Scorecard)', 'Driver count', 'Cascade'],
      },
      {
        field: 'ServiceResourceSkill',
        object: 'ServiceResourceSkill (junction)',
        label: 'Driver Skills',
        type: 'Junction Object',
        description: 'Links a ServiceResource to a Skill (e.g., Tow, Battery, Tire, Lockout). Skill.MasterLabel = skill name. Used to classify drivers as tow/light/battery and determine cross-skill cascade eligibility.',
        usedIn: ['Cascade Opportunities', 'Driver Tier Classification'],
      },
      {
        field: 'ERS_Facility_Account__r (on ServiceTerritory)',
        object: 'Account (via lookup)',
        label: 'Facility Account',
        type: 'Lookup',
        description: 'The Account record for the garage facility. Provides Phone and Dispatch_Method__c (account-level dispatch method, used in Command Center garage layer).',
        usedIn: ['Command Center (Garage Layer)', 'Ops Garages'],
      },
    ],
  },

  // ── 7. SURVEY ──
  {
    group: 'Member Satisfaction',
    description: 'Post-service survey data used for satisfaction metrics.',
    fields: [
      {
        field: 'Survey_Result__c.ERS_Overall_Satisfaction__c',
        object: 'Survey_Result__c (Custom)',
        label: 'Overall Satisfaction',
        type: 'Picklist (Custom)',
        description: 'Member\'s satisfaction rating: "Totally Satisfied", "Satisfied", "Neither", "Dissatisfied", "Totally Dissatisfied". AAA accreditation target: 82% "Totally Satisfied" + "Satisfied" combined.',
        usedIn: ['Satisfaction %', 'Garage Score (Satisfaction dimension)'],
      },
      {
        field: 'Survey_Result__c.ERS_Work_Order_Number__c',
        object: 'Survey_Result__c (Custom)',
        label: 'Work Order Number (Survey Join)',
        type: 'Text (Custom)',
        description: 'Matches WorkOrder.WorkOrderNumber to link surveys back to SAs. This is the join key — surveys reference the WO number as text, not a Salesforce lookup.',
        usedIn: ['Satisfaction metrics (join key)'],
      },
    ],
  },

  // ── 8. SA HISTORY ──
  {
    group: 'Audit & History',
    description: 'History tracking records used for 1st Call / 2nd+ Call classification.',
    fields: [
      {
        field: 'ServiceAppointmentHistory',
        object: 'ServiceAppointmentHistory',
        label: 'SA Field Change History',
        type: 'History Object',
        description: 'Standard Salesforce field history tracking. We query WHERE Field = "ServiceTerritory" to see the sequence of garage assignments. First NewValue = first garage assigned (1st call). If this garage appears later in the sequence, it was a cascade (2nd+ call).',
        usedIn: ['1st Call vs 2nd+ Call', 'Acceptance metrics'],
      },
    ],
  },
]

// ── Severity badge ───────────────────────────────────────────────────────────

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
      <Icon className="w-3 h-3" />
      {s.label}
    </span>
  )
}

// ── Progress bar ─────────────────────────────────────────────────────────────

function QualityBar({ pct, severity }) {
  const color = severity === 'critical' ? 'bg-red-500' : severity === 'warn' ? 'bg-amber-500' : 'bg-emerald-500'
  return (
    <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
      <div className={clsx('h-full rounded-full transition-all', color)} style={{ width: `${Math.min(pct || 0, 100)}%` }} />
    </div>
  )
}

// ── Main Page ────────────────────────────────────────────────────────────────

const TABS = [
  { key: 'dictionary', label: 'Field Dictionary', icon: BookOpen },
  { key: 'quality',    label: 'Data Quality Audit', icon: ShieldCheck },
]

export default function DataDictionary() {
  const [tab, setTab] = useState('dictionary')
  const [search, setSearch] = useState('')
  const [expandedGroup, setExpandedGroup] = useState(null)
  const [quality, setQuality] = useState(null)
  const [qLoading, setQLoading] = useState(false)
  const [qError, setQError] = useState(null)
  const [groupFilter, setGroupFilter] = useState('all')

  // Load data quality when tab is selected
  useEffect(() => {
    if (tab === 'quality' && !quality && !qLoading) {
      setQLoading(true)
      setQError(null)
      fetchDataQuality()
        .then(setQuality)
        .catch(e => setQError(e.response?.data?.detail || e.message))
        .finally(() => setQLoading(false))
    }
  }, [tab])

  // ── Dictionary search + filter ──
  const filteredDictionary = useMemo(() => {
    const q = search.toLowerCase()
    if (!q) return DICTIONARY
    return DICTIONARY.map(group => ({
      ...group,
      fields: group.fields.filter(f =>
        f.field.toLowerCase().includes(q) ||
        f.label.toLowerCase().includes(q) ||
        f.description.toLowerCase().includes(q) ||
        f.object.toLowerCase().includes(q) ||
        (f.usedIn || []).some(u => u.toLowerCase().includes(q))
      ),
    })).filter(g => g.fields.length > 0)
  }, [search])

  const totalFields = DICTIONARY.reduce((s, g) => s + g.fields.length, 0)

  // ── Quality filter ──
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
    if (groupFilter === 'issues') {
      return qualityGroups.map(g => ({
        ...g,
        fields: g.fields.filter(f => f.severity !== 'ok'),
      })).filter(g => g.fields.length > 0)
    }
    return qualityGroups.filter(g => g.name === groupFilter)
  }, [qualityGroups, groupFilter])

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <Database className="w-6 h-6 text-brand-400" />
            Data Dictionary & Quality
          </h1>
          <p className="text-slate-500 text-xs mt-0.5">
            {totalFields} fields across {DICTIONARY.length} groups — every Salesforce field used in this app
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 bg-slate-900 rounded-xl mb-6 w-fit">
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={clsx(
              'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all',
              tab === t.key
                ? 'bg-brand-600 text-white shadow-lg shadow-brand-600/20'
                : 'text-slate-400 hover:text-white hover:bg-slate-800'
            )}
          >
            <t.icon className="w-4 h-4" />
            {t.label}
            {t.key === 'quality' && quality?.summary && (
              <span className={clsx('ml-1 px-1.5 py-0.5 rounded-full text-[9px] font-bold',
                quality.summary.critical_issues > 0 ? 'bg-red-500 text-white' : 'bg-emerald-500 text-white')}>
                {quality.summary.critical_issues > 0 ? `${quality.summary.critical_issues} issues` : 'OK'}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ═══ DICTIONARY TAB ══════════════════════════════════════════════════════ */}
      {tab === 'dictionary' && (
        <div>
          {/* Search */}
          <div className="relative max-w-md mb-5">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search fields, objects, descriptions..."
              className="w-full pl-9 pr-4 py-2 bg-slate-900 border border-slate-700 rounded-xl text-sm
                         placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-brand-500/40"
            />
          </div>

          {/* Grouped field list */}
          <div className="space-y-4">
            {filteredDictionary.map(group => {
              const isExpanded = expandedGroup === group.group || search.length > 0
              return (
                <div key={group.group} className="glass rounded-xl overflow-hidden">
                  {/* Group header */}
                  <button
                    onClick={() => setExpandedGroup(isExpanded && !search ? null : group.group)}
                    className="w-full flex items-center gap-3 px-5 py-4 hover:bg-slate-800/30 transition-colors text-left"
                  >
                    {isExpanded
                      ? <ChevronDown className="w-4 h-4 text-brand-400 shrink-0" />
                      : <ChevronRight className="w-4 h-4 text-slate-500 shrink-0" />
                    }
                    <div className="flex-1 min-w-0">
                      <div className="font-semibold text-white text-sm">{group.group}</div>
                      <div className="text-[11px] text-slate-500 mt-0.5">{group.description}</div>
                    </div>
                    <span className="text-[10px] text-slate-600 bg-slate-800 px-2 py-1 rounded-lg shrink-0">
                      {group.fields.length} fields
                    </span>
                  </button>

                  {/* Fields table */}
                  {isExpanded && (
                    <div className="border-t border-slate-800/60">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="text-slate-500 text-[10px] uppercase tracking-wider">
                            <th className="text-left px-5 py-2.5 w-[220px]">Field (API Name)</th>
                            <th className="text-left px-3 py-2.5 w-[140px]">Object</th>
                            <th className="text-left px-3 py-2.5 w-[80px]">Type</th>
                            <th className="text-left px-3 py-2.5">Description</th>
                            <th className="text-left px-3 py-2.5 w-[180px]">Used In</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800/30">
                          {group.fields.map(f => (
                            <tr key={f.field} className="hover:bg-slate-800/20">
                              <td className="px-5 py-3 font-mono text-brand-300 text-[11px] break-all">{f.field}</td>
                              <td className="px-3 py-3 text-slate-400 whitespace-nowrap">{f.object}</td>
                              <td className="px-3 py-3 text-slate-500 whitespace-nowrap">{f.type}</td>
                              <td className="px-3 py-3 text-slate-300 leading-relaxed">{f.description}</td>
                              <td className="px-3 py-3">
                                <div className="flex flex-wrap gap-1">
                                  {(f.usedIn || []).map(u => (
                                    <span key={u} className="px-1.5 py-0.5 bg-slate-800 text-slate-400 rounded text-[9px]">{u}</span>
                                  ))}
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {filteredDictionary.length === 0 && (
            <div className="text-center py-16 text-slate-600 text-sm">No fields match your search.</div>
          )}
        </div>
      )}

      {/* ═══ DATA QUALITY TAB ════════════════════════════════════════════════════ */}
      {tab === 'quality' && (
        <div>
          {/* Loading */}
          {qLoading && (
            <div className="flex items-center justify-center py-20 gap-3">
              <Loader2 className="w-6 h-6 animate-spin text-brand-400" />
              <span className="text-slate-400">Auditing field quality across {'>'}28 days of data...</span>
            </div>
          )}

          {/* Error */}
          {qError && !qLoading && (
            <div className="rounded-xl bg-red-950/30 border border-red-800/30 p-4 text-red-300 text-sm">
              Failed to load data quality: {qError}
            </div>
          )}

          {/* Results */}
          {quality && !qLoading && (
            <>
              {/* Summary cards */}
              <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-5">
                <div className="glass rounded-xl p-4">
                  <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Period</div>
                  <div className="text-sm font-bold text-white">{quality.period}</div>
                  {quality.refreshed_at && (
                    <div className="text-[9px] text-slate-600 mt-1">Refreshed: {quality.refreshed_at}</div>
                  )}
                </div>
                <div className="glass rounded-xl p-4">
                  <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Total SAs</div>
                  <div className="text-lg font-bold text-white">{quality.total_sas?.toLocaleString()}</div>
                  <div className="text-[10px] text-slate-500">{quality.completed_sas?.toLocaleString()} completed</div>
                </div>
                <div className={clsx('glass rounded-xl p-4', quality.summary.critical_issues > 0 && 'border border-red-800/30')}>
                  <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Critical Issues</div>
                  <div className={clsx('text-lg font-bold', quality.summary.critical_issues > 0 ? 'text-red-400' : 'text-emerald-400')}>
                    {quality.summary.critical_issues}
                  </div>
                </div>
                <div className="glass rounded-xl p-4">
                  <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Warnings</div>
                  <div className={clsx('text-lg font-bold', quality.summary.warnings > 0 ? 'text-amber-400' : 'text-slate-500')}>
                    {quality.summary.warnings}
                  </div>
                </div>
                <div className="glass rounded-xl p-4">
                  <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Healthy</div>
                  <div className="text-lg font-bold text-emerald-400">{quality.summary.healthy}</div>
                  <div className="text-[10px] text-slate-500">of {quality.summary.total_fields_checked} checked</div>
                </div>
              </div>

              {/* Critical issues callout */}
              {quality.summary.critical_issues > 0 && (
                <div className="mb-5 p-4 rounded-xl border border-red-800/30 bg-red-950/10">
                  <div className="flex items-center gap-2 mb-2">
                    <XCircle className="w-4 h-4 text-red-400" />
                    <span className="text-xs font-bold text-red-300 uppercase tracking-wide">
                      {quality.summary.critical_issues} Critical Data Quality Issue{quality.summary.critical_issues > 1 ? 's' : ''}
                    </span>
                  </div>
                  <div className="text-xs text-red-300/80">
                    {quality.summary.critical_field_names.join(', ')} — these affect core metrics like response time and SLA rates.
                  </div>
                </div>
              )}

              {/* Filter bar */}
              <div className="flex items-center gap-2 mb-4">
                <Filter className="w-3.5 h-3.5 text-slate-500" />
                <div className="flex gap-1 flex-wrap">
                  {[
                    { key: 'all', label: 'All Fields' },
                    { key: 'issues', label: 'Issues Only' },
                    ...qualityGroups.map(g => ({ key: g.name, label: g.name })),
                  ].map(f => (
                    <button
                      key={f.key}
                      onClick={() => setGroupFilter(f.key)}
                      className={clsx(
                        'px-2.5 py-1 rounded-lg text-[10px] font-medium transition-all',
                        groupFilter === f.key
                          ? 'bg-brand-600/30 text-brand-300 border border-brand-500/30'
                          : 'text-slate-500 hover:text-white hover:bg-slate-800 border border-transparent'
                      )}
                    >
                      {f.label}
                    </button>
                  ))}
                </div>
                <button
                  onClick={() => { setQuality(null); setQLoading(true); setQError(null); refreshDataQuality().then(setQuality).catch(e => setQError(e.response?.data?.detail || e.message)).finally(() => setQLoading(false)) }}
                  disabled={qLoading}
                  className="ml-auto flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[10px] text-slate-500 hover:text-white hover:bg-slate-800 transition-all disabled:opacity-50"
                >
                  <RefreshCw className={clsx('w-3 h-3', qLoading && 'animate-spin')} />
                  {qLoading ? 'Refreshing...' : 'Refresh from Salesforce'}
                </button>
              </div>

              {/* Quality cards by group */}
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
                            {/* Left: field info */}
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 mb-1.5">
                                <span className="font-semibold text-white text-sm">{f.label}</span>
                                <SevBadge severity={f.severity} />
                              </div>
                              <div className="font-mono text-[11px] text-brand-300/70 mb-2">{f.field}</div>
                              <div className="text-xs text-slate-400 leading-relaxed mb-3">{f.description}</div>

                              {/* Issues */}
                              <div className="text-xs text-slate-300 bg-slate-800/40 rounded-lg px-3 py-2 mb-2">
                                <span className="text-slate-500 font-medium">Issues: </span>
                                {f.issues}
                              </div>

                              {/* Impact */}
                              <div className="text-xs text-slate-400">
                                <span className="text-slate-500 font-medium">Impact on metrics: </span>
                                {f.impact}
                              </div>
                            </div>

                            {/* Right: stats */}
                            <div className="w-48 shrink-0 space-y-2">
                              <div className="flex justify-between items-baseline">
                                <span className="text-[10px] text-slate-500">Populated</span>
                                <span className={clsx('text-sm font-bold', f.pct >= 90 ? 'text-emerald-400' : f.pct >= 70 ? 'text-amber-400' : 'text-red-400')}>
                                  {f.pct != null ? `${f.pct}%` : 'N/A'}
                                </span>
                              </div>
                              <QualityBar pct={f.pct} severity={f.severity} />
                              <div className="text-[10px] text-slate-600">
                                {f.populated?.toLocaleString()} of {f.total?.toLocaleString()} records
                              </div>

                              {/* Detail breakdown if available */}
                              {f.detail && f.detail.breakdown && (
                                <div className="pt-2 border-t border-slate-800/40 space-y-1">
                                  {Object.entries(f.detail.breakdown).map(([k, v]) => (
                                    <div key={k} className="flex justify-between text-[10px]">
                                      <span className="text-slate-500">{k}</span>
                                      <span className="text-slate-400">{v?.toLocaleString()}</span>
                                    </div>
                                  ))}
                                </div>
                              )}
                              {f.detail && f.detail.usable != null && (
                                <div className="pt-2 border-t border-slate-800/40 space-y-1 text-[10px]">
                                  <div className="flex justify-between">
                                    <span className="text-slate-500">Usable values</span>
                                    <span className="text-emerald-400 font-bold">{f.detail.usable?.toLocaleString()}</span>
                                  </div>
                                  <div className="flex justify-between">
                                    <span className="text-slate-500">Invalid (0 / 999+)</span>
                                    <span className="text-red-400">{f.detail.sentinel_zero_or_999?.toLocaleString()}</span>
                                  </div>
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

              {filteredQuality.length === 0 && (
                <div className="text-center py-16 text-slate-600 text-sm">No fields match this filter.</div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
