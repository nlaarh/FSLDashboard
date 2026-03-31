# FSL Fields, Intelligence & Advanced Features — Complete Reference

Source: Salesforce Field Service Guide (Spring '26)
PDF: https://resources.docs.salesforce.com/latest/latest/en-us/sfdc/pdf/support_field_service.pdf

---

## Key Object Fields Reference

### Service Appointment Fields (Critical for Scheduling)

| Field | API Name | Type | Description |
|-------|----------|------|-------------|
| Appointment Number | AppointmentNumber | Auto | Unique ID |
| Status | Status | Picklist | Lifecycle status |
| Earliest Start Permitted | EarliestStartPermitted | DateTime | Earliest scheduling allowed (MANDATORY for scheduling) |
| Due Date | DueDate | DateTime | Latest scheduling allowed (MANDATORY for scheduling) |
| Scheduled Start | SchedStartTime | DateTime | Assigned start time |
| Scheduled End | SchedEndTime | DateTime | Assigned end time |
| Actual Start | ActualStartTime | DateTime | Real work start (Fleet: real arrival; Towbook: FAKE) |
| Actual End | ActualEndTime | DateTime | Real work end |
| Duration | Duration | Number | Estimated duration in minutes |
| Duration Type | DurationType | Picklist | Hours or Minutes |
| Arrival Window Start | ArrivalWindowStart | DateTime | Customer-facing window start |
| Arrival Window End | ArrivalWindowEnd | DateTime | Customer-facing window end |
| Service Territory | ServiceTerritoryId | Lookup | Territory assignment |
| Parent Record | ParentRecordId | Lookup | Work order or WOLI |
| Address | Street/City/State/Zip/Country | Address | Job location |
| Latitude | Latitude | Number | Job geocoordinate |
| Longitude | Longitude | Number | Job geocoordinate |
| Auto Schedule | FSL__Auto_Schedule__c | Checkbox | Auto-schedule on creation |
| Scheduling Policy Used | FSL__Scheduling_Policy_Used__c | Lookup | Policy for auto-scheduling |
| Pinned | FSL__Pinned__c | Checkbox | Exclude from optimization |
| Is Offsite | IsOffsiteAppointment | Checkbox | Virtual/locationless (ESO) |
| Schedule over lower priority | FSL__Schedule_over_lower_priority_appointment__c | Checkbox | Can displace lower priority SAs |
| Estimated Travel Time | FSL__EstimatedTravelTime__c | Number | Calculated travel to appointment |
| In Jeopardy | FSL__InJeopardy__c | Checkbox | At risk of missing SLA |
| In Jeopardy Reason | FSL__InJeopardyReason__c | Text | Why it's in jeopardy |

### AAA Custom Fields on SA
| Field | Description |
|-------|-------------|
| ERS_PTA__c | Promised Time of Arrival (minutes) |
| ERS_Dispatch_Method__c | Formula: 'Field Services' or 'Towbook' (CANNOT GROUP BY in SOQL) |
| ERS_Cancellation_Reason__c | Cancellation reason picklist |
| ERS_Facility_Decline_Reason__c | Garage decline reason |
| Off_Platform_Driver__c | Towbook driver Contact lookup |
| Off_Platform_Truck_Id__c | Towbook truck ID |
| ERS_Auto_Assign__c | UNRELIABLE — don't use for dispatch method detection |

### Service Resource Fields

| Field | API Name | Type | Description |
|-------|----------|------|-------------|
| Name | Name | Text | Resource name |
| Is Active | IsActive | Checkbox | Available for scheduling |
| Resource Type | ResourceType | Picklist | Technician, Agent, Crew |
| Last Known Latitude | LastKnownLatitude | Number | Current GPS lat |
| Last Known Longitude | LastKnownLongitude | Number | Current GPS lon |
| Last Known Location Date | LastKnownLocationDate | DateTime | GPS freshness timestamp |
| Efficiency | FSL__Efficiency__c | Percent | Work speed factor |
| Travel Speed | FSL__Travel_Speed__c | Number | Override travel speed |
| Capacity | FSL__Capacity__c | Number | For capacity-based resources |

### Service Territory Fields

| Field | API Name | Type | Description |
|-------|----------|------|-------------|
| Name | Name | Text | Territory name |
| Is Active | IsActive | Checkbox | Active for scheduling |
| Operating Hours | OperatingHoursId | Lookup | Default operating hours |
| Parent Territory | ParentTerritoryId | Lookup | Hierarchy parent |
| Address | Street/City/State/Zip/Country | Address | Territory location |
| Latitude | Latitude | Number | Territory geocoordinate |
| Longitude | Longitude | Number | Territory geocoordinate |
| Travel Mode | FSL__Travel_Mode__c | Lookup | ESO travel mode |

### ServiceTerritoryMember Fields

| Field | API Name | Type | Description |
|-------|----------|------|-------------|
| Service Resource | ServiceResourceId | Lookup | The resource |
| Service Territory | ServiceTerritoryId | Lookup | The territory |
| Territory Type | TerritoryType | Picklist | Primary / Secondary / Relocation |
| Effective Start Date | EffectiveStartDate | DateTime | Membership start |
| Effective End Date | EffectiveEndDate | DateTime | Membership end |
| Operating Hours | OperatingHoursId | Lookup | Override territory hours |
| Street/City/State/Zip | Address fields | Address | HOME BASE address for scheduling |
| Latitude | Latitude | Number | Home base geocoordinate |
| Longitude | Longitude | Number | Home base geocoordinate |
| Travel Mode | FSL__Travel_Mode__c | Lookup | Override territory travel mode (ESO, primary only) |

### Work Order Fields

| Field | API Name | Type | Description |
|-------|----------|------|-------------|
| Work Order Number | WorkOrderNumber | Auto | Unique ID |
| Status | Status | Picklist | Lifecycle status |
| Service Territory | ServiceTerritoryId | Lookup | Territory |
| Work Type | WorkTypeId | Lookup | Work type template |
| Priority | Priority | Picklist | Work priority |
| Duration | Duration | Number | Estimated duration |
| Address | Street/City/State/Zip | Address | Job site |
| Latitude/Longitude | Lat/Lon | Number | Geocoordinates |

### Assigned Resource (ServiceAppointment ↔ ServiceResource)

| Field | API Name | Type | Description |
|-------|----------|------|-------------|
| Service Appointment | ServiceAppointmentId | Lookup | The SA |
| Service Resource | ServiceResourceId | Lookup | The assigned resource |
| Estimated Travel Time | EstimatedTravelTime | Number | Travel to appointment |
| Actual Travel Time | ActualTravelTime | Number | Actual travel (from mobile app) |
| Created By | CreatedById | Lookup | WHO assigned — key for dispatch method detection |

---

## Einstein / Agentforce for Field Service

### Autonomous Scheduling
- AI-driven scheduling that can operate without human dispatcher
- Learns from historical patterns
- Available as Agentforce capability

### Agentforce for Dispatchers
- AI assistant for dispatchers in console
- Recommendations for schedule optimization
- Natural language interaction

### Agentforce for Mobile Workers
- AI assistance in the field
- Work order guidance
- Knowledge article suggestions

### Appointment Insights (Beta, ESO)
- AI recommendations for schedule improvement
- Identifies sub-optimal assignments
- Suggests better scheduling options

---

## Field Service Intelligence (FSI)

### What It Is
Data-driven solution displaying key field service performance metrics. Includes Data Cloud, CRM Analytics, and Service Cloud.

### Key Metrics Available
- First-time fix rate
- Mean time to completion
- Resource utilization
- Travel time efficiency
- SLA compliance
- Customer satisfaction
- Schedule adherence
- Appointment completion rate

### Optimization Hub (ESO)
- Before-and-after metrics when running optimization
- Tracks: appointments scheduled, utilization, travel time, gaps, overtime
- Baseline comparison across optimization runs
- Per-territory breakdown

### Optimization Insights (Legacy)
- Similar to Optimization Hub but for standard engine
- Captures optimization results
- Gantt visualization of schedule changes

---

## Scheduling Overlaps

### What They Are
When two SAs are scheduled at overlapping times for the same resource. Unrealistic — resource can't do two jobs at once.

### Detection
- Visible on Gantt as overlapping bars
- Rule violation indicators
- Monitoring via scheduling history

### Resolution Methods

| Method | When to Use | What It Does |
|--------|-----------|-------------|
| **Fix Overlaps (policy checkbox)** | During optimization | Unschedules overlapping SAs if can't find valid slot |
| **Fix Overlaps (Gantt action)** | Manual dispatcher action | Reschedules overlapping SAs |
| **Fix Overlaps Flow (ESO Beta)** | Auto-trigger on late appointments | Flow-based, replaces recipes |
| **RSO** | When you also want schedule optimization | Fixes overlap + optimizes resource's full schedule |
| **ESO behavior** | Always | ESO ALWAYS resolves overlaps on non-pinned SAs |

### Fix Overlap Settings
- When can't find valid slot: put in jeopardy, unschedule, or reshuffle others
- Pin Criteria: statuses that prevent movement during overlap fixing
- Keep Scheduled Criteria: SAs that can move but not drop

---

## Appointment Bundling

### What It Is
Group multiple SAs at nearby/same locations into one unit (bundle). Bundle members scheduled, rescheduled, and executed together.

### Use Cases
- Multiple visits at same customer location
- Utility meter readings at apartment complex
- Package deliveries in same area

### Configuration
- Bundle Config: defines bundling rules
- Bundle Policy: matching criteria
- Bundle Sort Policy: ordering within bundle
- Bundle Restriction Policy: constraints
- Bundle Aggregation: duration calculation

### Limits
- Max 50 appointments in Group Nearby action
- 60 second max runtime for Group Nearby

---

## Scheduling History

### ServiceAppointmentHistory
- Tracks ALL field changes on SAs
- `Field = 'Status'` + `NewValue` = status transitions
- `CreatedDate` of history row = when change happened
- **Critical for AAA**: Towbook real ATA = `On Location` history entry CreatedDate

### Optimization Request Monitoring
- Track optimization request status
- Completion rate, runtime, conflicts
- Available via Optimization Hub (ESO) or Optimization Insights (Legacy)

### Activity Reports (Beta, ESO)
- Detailed scheduling activity logs
- Who did what, when, why

### Optimization Request Files (Beta, ESO)
- Downloadable optimization result data
- For deep analysis of optimization decisions

---

## Key Performance Indicators (KPIs)

### SF Recommended KPIs for Field Service
| KPI | What It Measures |
|-----|-----------------|
| **First-Time Fix Rate** | % of jobs completed on first visit |
| **Utilization** | % of available time spent on productive work |
| **Travel Time** | Average travel between appointments |
| **SLA Compliance** | % of appointments meeting SLA |
| **Schedule Adherence** | Actual vs planned schedule accuracy |
| **Customer Satisfaction** | Post-service customer rating |
| **Completion Rate** | % of scheduled appointments completed |
| **Mean Time to Service** | Average time from request to service delivery |

### AAA-Specific KPIs (from METRICS_KNOWLEDGE_BASE.md)
| KPI | Formula |
|-----|---------|
| **ATA** | Fleet: ActualStartTime - CreatedDate. Towbook: OnLocation history - CreatedDate |
| **PTA Compliance** | ATA ≤ PTA (% of SAs meeting promised time) |
| **ATA Under 45** | % of completed SAs with ATA ≤ 45 min |
| **CNW Rate** | % cancelled with "Member Could Not Wait" |
| **Completion Rate** | Completed / Total SAs |
| **Auto Dispatch %** | AssignedResource.CreatedBy = 'IT System User' |
