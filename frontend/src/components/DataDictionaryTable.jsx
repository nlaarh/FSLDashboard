/**
 * DataDictionaryTable.jsx
 *
 * Extracted from DataDictionary.jsx:
 * - DICTIONARY constant (all field definitions)
 * - DictionaryTab component (search + grouped field list)
 */

import { useState, useMemo } from 'react'
import { Search, ChevronDown, ChevronRight } from 'lucide-react'

// ── Full Field Dictionary ────────────────────────────────────────────────────
// Every field used across the app, grouped by lifecycle stage

export const DICTIONARY = [
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

// ── Dictionary Tab Component ────────────────────────────────────────────────

export default function DictionaryTab() {
  const [search, setSearch] = useState('')
  const [expandedGroup, setExpandedGroup] = useState(null)

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

  return (
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
  )
}
