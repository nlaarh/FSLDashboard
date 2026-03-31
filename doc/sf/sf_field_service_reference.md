# Salesforce Field Service -- Comprehensive Reference (Extracted from Official Documentation)

---

## 1. FIELD SERVICE OBJECT FIELDS

### 1.1 Service Appointment Fields

| Field Name | Description |
|---|---|
| Account | (Read only) Account associated with appointment. Inherited from parent WO/WOLI. |
| Actual Duration (Minutes) | Minutes resource took to complete after arriving. Auto-populated from Actual Start/End difference on first entry. Does NOT re-update if Actual Start/End change later -- must manually update. |
| Actual End | Actual date/time appointment ended. |
| Actual Start | Actual date/time appointment started. |
| Address | Where appointment takes place. Inherited from parent WO/WOLI. |
| Appointment Number | Auto-assigned number identifying the appointment. |
| Arrival Window End | End of window mobile worker is scheduled to arrive. Typically larger than Scheduled Start/End window. Share with customer; keep Scheduled Start/End internal. |
| Arrival Window Start | Beginning of arrival window. Same guidance as Arrival Window End. |
| Bundle | Boolean -- indicates if this SA is a bundle appointment. Default false. |
| Bundle Member | Boolean -- indicates if this SA is a bundle member. Default false. |
| Bundle Policy | Reference to the bundle policy associated with this SA. |
| Contact | Contact associated with appointment. Inherited from parent WO/WOLI. |
| Description | Description of the appointment. |
| Due Date | Date by which appointment must be completed. Reflects SLA terms with customer. |
| Duration | Estimated length. Inherited from parent but can be manually updated. Unit depends on Duration Type. |
| Duration Type | Minutes or Hours. |
| Earliest Start Permitted | Date after which appointment can start. Reflects SLA terms with customer. |
| Latitude | Precise geolocation (API only). Range -90 to 90, up to 15 decimal places. Map to ServiceAppointment.Latitude, NOT FSL__InternalSLRGeolocation. |
| Longitude | Precise geolocation (API only). Range -180 to 180, up to 15 decimal places. Map to ServiceAppointment.Longitude, NOT FSL__InternalSLRGeolocation. |
| Manually Bundled | Read-only. Indicates if bundle was created manually. Default false. |
| Offsite Appointment | (Enhanced S&O only) Whether appointment can be done remotely. If selected, no travel time added. E.g., remote tech assistance, report filing. |
| Parent Record | Parent record (WO, WOLI, Account, Asset, Lead, Opportunity). Cannot be updated after SA creation. |
| Parent Record Status Category | (Read only) Status Category of parent record if WO or WOLI. |
| Parent Record Type | (Read only) Type: Account, Asset, Lead, Opportunity, Work Order, or Work Order Line Item. |
| Related Bundle | The bundle this SA is a member of. |
| Scheduled End | Time appointment is scheduled to end. Auto-populated when assigned to resource via scheduling optimizer. Scheduled End - Scheduled Start = Estimated Duration. |
| Scheduled Start | Time appointment is scheduled to start. Auto-populated when assigned to resource via scheduling optimizer. |
| Schedule Mode | (Read only) Shows how appointment was scheduled: Auto, Manual, Drag and Drop, Schedule, Global Optimization, In-Day Optimization, or Resource Optimization. |
| Service Note | Appointment summary or recommendations. May appear on customer-facing service report. |
| Service Territory | Territory associated with appointment. Inherited from parent WO/WOLI. |
| Status | Status picklist: None (default), Scheduled, Dispatched, In Progress, Cannot Complete, Completed, Canceled. Customizable. |
| Status Category | Category each Status falls into. Same values as standard Status. Custom statuses must specify a category. Referenced by many FS processes. |
| Subject | Short phrase describing the appointment. |
| Work Type | (Read only) Inherited from parent WO/WOLI. If Lightning Scheduler is also in use, field is editable. |

### 1.2 Assigned Resource Fields

| Field Name | Description |
|---|---|
| Actual Travel Time (Minutes) | Actual travel time in minutes to work site. |
| Assigned Resource Number | Auto-generated identifying number. |
| Estimated Travel Time (Minutes) | Estimated travel time in minutes to work site. Auto-populated by system. For crews, can't track individual members unless separate AR records are created. |
| Approximate Travel Time From (Minutes) | Auto-populated by system only for the LAST service appointment of the day -- estimate of travel time from SA to resource's home base. |
| Estimated Travel Distance From | Estimated mileage from assigned appointment location to home base (km or miles). |
| Estimated Travel Distance To | Estimated mileage to the assigned appointment location from prior SA, absence location, or home base. |
| Estimated Travel Time From Source | Shows calculation method (Aerial, SLR, Predictive). Travel From calculated only for last appointment of day. |
| Service Appointment | Related service appointment. |
| Service Crew | Service crew assigned (hidden by default; update FLS to use). |
| Service Resource | Service resource assigned to the appointment. |

### 1.3 Service Resource Fields

| Field Name | Description |
|---|---|
| Active | Whether resource can be assigned to work orders. Resources can't be deleted, only deactivated. |
| Capacity-Based | Limited to certain number of hours or appointments per time period. See Capacities related list. |
| Description | Description of the resource. |
| Efficiency | Value 0.1--10. Formula: Duration / Efficiency = Actual time to perform. 1 = average speed. >1 = faster. <1 = slower. Rounded up in Enhanced S&O. |
| Include in Scheduling Optimization | (Managed package) Whether resource is considered during optimization. Requires Field Service Scheduling PSL. |
| Location | Location associated with resource (e.g., service vehicle). |
| Name | Resource's name. |
| Resource Type | Technician (mobile worker), Dispatcher, or Crew. Dispatchers can't be capacity-based or included in optimization. Only users with FS Dispatcher PSL can be dispatchers. |
| Service Crew | Associated service crew (hidden by default). |
| User | Associated user. Blank if resource represents a crew. |

**Resource Absence Fields:**
| Field Name | Description |
|---|---|
| Absence Number | (Read only) Auto-generated number. |
| Absence Type | Meeting, Training, Medical, or Vacation. "Break" is reserved for managed package. |
| Address | Address associated with absence. |
| Description | Description. |
| End Time | Date/time absence ends. |
| Resource Name | The absent service resource. |
| Start Time | Date/time absence begins. |

**Resource Capacity Fields:**
| Field Name | Description |
|---|---|
| End Date | When capacity ends. |
| Hours per Time Period | Hours resource can work per period. |
| Start Date | When capacity takes effect. |
| Time Period | Day, Week, or Month. Enhanced S&O supports only Day. |
| Work Items per Time Period | Total SAs resource can complete per period. |

**Resource Preference Fields:**
| Field Name | Description |
|---|---|
| Preference Type | Preferred, Required, or Excluded. These are suggestions, not hard requirements. |
| Related Record | Work order or account with the preference. |
| Service Resource | The preferred/required/excluded resource. |

### 1.4 Service Territory Fields

| Field Name | Description |
|---|---|
| Active | Whether territory can be used. Inactive = can't add members or link to WO/SA. |
| Address | Territory headquarters. Primary members use this as home base unless overridden on STM record. Used for travel calculation at start/end of day. Must be geocoded. |
| Average Travel Time (in minutes) | Average travel time for territory. Added to Work Capacity Usage for each scheduled SA. Must include travel time buffer if defined. |
| Description | Description of territory. |
| Name | Territory name. |
| Operating Hours | When SAs within territory occur. Members inherit these unless different hours specified on STM record. |
| Parent Territory | Parent in hierarchy. E.g., Northern California -> State of California. |
| Top-Level Territory | (Read only) Top-level territory in hierarchy. |
| Travel Mode | Travel mode for calculations (car, walking, toll roads, hazmat). |
| Typical In-Territory Travel Time | Estimated minutes from one location to another within territory. For Apex customization. |

**Service Territory Member Fields:**
| Field Name | Description |
|---|---|
| Address | Member's address (e.g., resource's home). |
| End Date | When resource is no longer a member. Leave blank for indefinite. |
| Operating Hours | Member's operating hours (inherited from territory). |
| Service Resource | Resource assigned to territory. |
| Service Territory | Territory the resource is assigned to. |
| Start Date | When resource becomes a member. |
| Territory Type | Primary (one per resource at a time), Secondary (multiple allowed, overlapping dates OK), Relocation (temporary move, serves as primary during active dates). |

**Territory Sizing Best Practices:**
- Up to 50 service resources per territory
- Up to 1,000 service appointments per day per territory
- Up to 20 qualified service resources per service appointment
- Memberships should be 24+ hours, start/end at same hour (recommend 00:00)
- Territories must NOT span multiple time zones

### 1.5 Work Order Fields

| Field Name | Description |
|---|---|
| Account | Account associated with WO. |
| Address | Compound address where WO is completed. SA and WOLI inherit address. |
| Asset | Asset associated with WO. |
| Business Hours | Business hours associated with WO. |
| Case | Case associated with WO. |
| Contact | Contact associated with WO. |
| Description | Description. Recommend describing steps to mark WO Completed. |
| Discount | (Read only) Weighted average of discounts on all line items. |
| Duration | Estimated time to complete. Independent of WOLI duration. |
| Duration Type | Minutes or Hours. |
| End Date | Date WO completed. Blank unless automation configured. |
| Entitlement | Entitlement associated with WO. |
| Generated from maintenance plan | (Read only) Whether WO was generated from a maintenance plan. |
| Grand Total | (Read only) Total price with tax. |
| Is Closed | Whether WO is closed. For reporting closed vs open WOs. |
| Latitude/Longitude | Precise geolocation. |
| Location | Location associated (e.g., work site). |
| Maintenance Plan | Associated maintenance plan. Auto-populated when WO is auto-generated. |
| Milestone Status | Compliant, Open Violation, Closed Violation. |
| Minimum Crew Size | Minimum crew size allowed. Scheduling optimizer uses this for crew assignment. |
| Parent Work Order | Parent WO in hierarchy. |
| Post-Work Summary | Summary of completed WO. Can be entered manually or generated by Einstein Copilot. |
| Pre-Work Brief Prompt Template ID | ID of activated Pre-Work Brief prompt template. |
| Priority | Low, Medium, High, Critical. Customizable. |
| Recommended Crew Size | Recommended number on assigned crew. |
| Root Work Order | (Read only) Top-level WO in hierarchy. |
| Service Appointment Count | Number of SAs on WO. |
| Service Contract | Service contract associated with WO. |
| Service Report Language | Language for all service reports created for WO. |
| Service Territory | Where WO takes place. |
| Start Date | When WO goes into effect. Blank unless automation configured. |
| Status | New, In Progress, On Hold, Completed, Cannot Complete, Closed, Canceled. Customizable. Changing WO status does NOT affect WOLI or SA status. |
| Status Category | Category each status falls into. 8 defaults: 7 matching Status values + None. |
| Subject | Subject of WO. Max 255 characters. |
| Suggested Maintenance Date | Auto-populated from maintenance plan settings. |
| Tax | Total tax on WO. |
| Total Price | (Read only) Total of WOLI price after discounts before tax. |
| Work Order Number | Auto-generated number. |
| Work Type | Associated work type. WO inherits Duration, Duration Type, and required skills from work type. |

---

## 2. SCHEDULING AND OPTIMIZATION SERVICES

### 2.1 Scheduling Services
- **Appointment Booking** -- Book appointments via global actions with scheduling policy grading
- **Bulk Schedule** -- Mass-schedule unscheduled appointments
- **Drag & Drop** -- Manually place appointments on Gantt
- **Emergency Wizard** -- Quick schedule/dispatch for emergencies with real-time map
- **Get Candidates** -- Generate list of candidate resources/slots
- **Keep Scheduled** -- Preserve existing schedule during optimization
- **Reshuffle** -- Available for scheduling and appointment booking
- **Schedule** -- Standard scheduling action
- **Schedule over lower priority** -- Replace lower-priority appointments when no slots available

### 2.2 Dynamic Gantt Features
- **Fill-in Schedule** -- Find optimal schedule to fill resource gaps
- **Fix Overlaps** -- Resolve overlapping appointments
- **Group Nearby** -- Minimize travel by grouping nearby appointments

### 2.3 Optimization Services
Optimization fixes non-pinned rule-violating SAs. If no valid schedule exists, SAs are unscheduled. Pinned SAs remain in place.
- **Global Optimization** -- Optimize across all resources/territories
- **In-Day Optimization** -- Optimize for current day
- **Resource Schedule Optimization (RSO)** -- Optimize individual resource's schedule
- **Scheduling Recipes** -- Event-driven automations (replaced by Fix Schedule Overlaps flow in Enhanced S&O)

### 2.4 Enhanced Scheduling and Optimization (ESO)
- Enabled by default for orgs created after Summer '23
- Uses point-to-point predictive routing regardless of routing settings
- Backward compatible with existing implementations
- Service resources must have geocoded home base locations
- Up to 5,000 objects (SAs + SRs) supported in any optimization action
- Travel Time Buffer can be defined per territory

### 2.5 Work Rules (Available in ESO)
| Work Rule | Notes |
|---|---|
| Count Rule | Limits daily SA count per resource. Complex work supported. |
| Designated Work | Shifts and time slots. |
| Excluded Resources | -- |
| Extended Match | Time-phased can affect performance in global optimization. |
| Match Boolean | -- |
| Match Fields | -- |
| Match Skills | -- |
| Match Territory | Scheduling outside working hours can result in violation. |
| Match Time | Check Rules doesn't distinguish which time rule caused violation. |
| Maximum Travel from Home | Always uses aerial routing regardless of settings. |
| Overtime | Supported only after a shift, not during. |
| Required Resources | -- |
| Service Crew Resources Availability | -- |
| Service Resource Availability | MUST include in scheduling policy. Travel From/To Home fields can't be empty. |
| Service Resource Availability - Flexible Breaks | Up to 3 breaks. |
| Visiting Hours | -- |
| Working Territories | For secondary territories. |

### 2.6 Service Objectives
Each assignment scored 0-100 per objective. Highest-scoring assignments preferred.

| Objective | Notes |
|---|---|
| Custom Objects | -- |
| Minimize Overtime | Relevance groups based on STMs only. |
| Minimize Travel | Relevance groups based on STMs only. Exclude Home Base Travel NOT supported by ESO. |
| Preferred Resource | -- |
| Resource Priority | -- |
| Same Site | -- |
| Schedule ASAP | Relevance groups based on SA definitions only. |
| Service Appointment Priority | Non-configurable objective. |
| Skill Level | -- |
| Skill Preference | -- |

### 2.7 Resource and Service Types
- Capacity-based resources
- Complex work
- Crews
- Individual service resources
- Multiday work (supported in all ESO services except Appointment Booking)
- Resource Efficiency (rounded up in ESO)
- Standard service appointments

### 2.8 Routing Options
1. **Aerial routing** -- Straight-line distance between two locations
2. **Street-level routing (SLR)** -- Road-based distance using road speed measurements
3. **Predictive travel** -- SLR + time-of-day data. Optimization only (not Appointment Booking)
4. **Point-to-point predictive routing** -- Exact SA location + time of day. Used across all scheduling/optimization. Default for new orgs since Spring '21. ESO always uses this.

### 2.9 Appointment Booking Settings
| Setting | Description |
|---|---|
| Default scheduling policy | Policy for arrival windows/time slots. Default: Customer First. |
| Default operating hours | Arrival window slots offered to customers. Default: Gold Appointments Calendar (2hr slots, Mon-Fri, 9AM-5PM). |
| Ideal grading threshold | Score 0-100. Appointments at or above get "Ideal" flag. |
| Recommended grading threshold | Score 0-100. Below ideal but at/above this get "Recommended" flag. |
| Minimum Grade | Score 0-100. Below this = not shown. |
| Number of hours for initial search | If ESP-DueDate gap > this, shows initial list while searching continues. |
| Show grades explanation | Shows score breakdown per service objective. |
| Pin three highest graded time slots | Highlight top 3 in Golden Slots section. |
| Disable service territory picker | Hide territory field in Book Appointment. |
| Open extended view by default | Show ESP and Due Date fields by default. |
| Automatically search for scheduling options | Auto-search on page load. |

---

## 3. MANAGE SCHEDULING OVERLAPS

### 3.1 Overview
Overlapping SAs are unrealistic since a resource can't perform more than one service at a time. Multiple features exist to resolve overlaps.

### 3.2 Features When Using Enhanced S&O
1. **Fix Schedule Overlaps Flow (Beta)** -- Salesforce Flow triggers RSO when overlap detected. Addresses same-day late-ending appointments. Minimum overlap: 10 minutes. Replaces scheduling recipes.
2. **Resource Schedule Optimization** -- Dispatchers reschedule overlapping appointments for one resource's schedule. Can also schedule additional work and optimize.
3. **In-Day and Global Optimization** -- Always fix overlaps regardless of Fix Overlaps setting. Priority determines which SAs to keep vs. drop.

### 3.3 Features When NOT Using Enhanced S&O
1. **Scheduling Recipes** -- Event-driven automations triggering RSO (canceled appointments, shortened appointments, late-end overlap, emergency overlap).
2. **Fix Overlaps in Gantt** -- Dispatchers manually fix from console. Configurable settings for how unscheduled SAs are rescheduled.
3. **Fix Overlaps in Scheduling Policies** -- If selected, overlaps addressed during in-day/global optimization.
4. **Resource Schedule Optimization** -- Same as above.

### 3.4 Fix Overlap Settings
| Setting | Options |
|---|---|
| When attempting to fix overlaps | "Schedule to original resource only" OR "Schedule to all resources" |
| After unscheduling, reschedule by | Priority order or keep original schedule order |
| If valid schedule not found | Put in jeopardy, unschedule, or reshuffle other assignments |

### 3.5 Fix Overlap Considerations
- Respects original order of scheduled appointments
- Reschedules only within the given day (unless Reshuffle progresses to another day)
- Considers only SAs in Scheduled or Dispatched Status Category
- Doesn't run on past SAs
- Not supported for capacity-based resources
- Ignores SA lifecycle settings when rescheduling
- Pinned SAs are never rescheduled or unscheduled

### 3.6 Scheduling Recipes (Non-ESO)
Scenarios addressed:
- **Canceled Appointment** -- Triggers RSO to fill the gap
- **Shortened Appointment** -- Mobile worker finishes early, fill the gap
- **Late-End Overlap** -- Mobile worker finishes late, overlapping next appointment
- **Emergency Overlap** -- Emergency appointment causes overlaps

Configuration:
- Up to 75 active recipes per category, 1000 per org
- Status Categories field limits which SAs recipe applies to
- Initiating User Permission Set controls who triggers recipe (Resource, Dispatcher, Agent, Admin, Community)
- Recipes support only operating hours/timeslots, NOT shifts

---

## 4. APPOINTMENT BUNDLING

### 4.1 Concept
Bundle = multiple SAs defined as a single entity. Bundle members = individual SAs within.

**Benefits:**
- Simplifies dispatcher work (one large job instead of many small ones)
- Helps mobile workers work efficiently (assembly line manner)
- Improves customer satisfaction (single visit for all services)
- Low computational overhead (only bundle is scheduled)
- Flexibility (add/remove members, perform in any sequence)
- Better tracking (individual incomplete members aren't forgotten)

**Use Cases:**
- Same customer scheduling (all SAs for one customer)
- Same site scheduling (all SAs in one building)
- Out-of-town scheduling (bundle all SAs for a remote location)
- Similar tasks scheduling (all network-related SAs on one day)

### 4.2 Bundle Policy Fields
| Field | Description |
|---|---|
| Automatic Bundling | Whether policy applies to automatic bundling. |
| Manual Bundling | Whether policy applies to manual bundling. Default false. |
| Filter Criteria | Recordset filter for which SAs can be bundled. |
| Limit Amount of Bundle Members | Maximum members per bundle. |
| Limit Duration of Bundle | Maximum bundle duration. |
| Priority | Priority when bundle policies are analyzed in automatic mode. |
| Time Calculation by Bundle Duration Field | Whether bundle duration is validated by start/end time difference. |

### 4.3 Bundle Config Fields
| Field | Description |
|---|---|
| Add to Bundle Statuses | SA statuses allowed to be bundled. Default: None. |
| Add travel time to bundle duration | Add travel between members to bundle duration. Default false. |
| Bundle Member Statuses not to be Propagated | Member statuses NOT overridden when bundle status updates. |
| Bundle Statuses to Propagate | Bundle statuses that propagate to members. |
| Criteria for Automatic Unbundling | Recordset filter that causes automatic unbundling. |
| Remove from Bundle Statuses | SA statuses allowed to be removed from bundle. |
| Status on Removal from Bundle | Status assigned when SA is removed from bundle. |
| Statuses not to Update on Unbundling | Statuses not updated during unbundling. |

### 4.4 Bundle Aggregation Policy Fields
| Field | Description |
|---|---|
| Source Field | SA field in bundle member from which value is taken. |
| Bundle's Target Field | Target field in bundle where value goes. |
| Aggregation Action | The aggregation action to perform. |
| Aggregation Field Type | Boolean, Date, Numeric, Picklist, Picklist-Multi, Skills, String. |
| Maximum Bundle Duration | Max duration from members after downscaling. |
| Recordset Filter Criteria | Filter for which members to aggregate. |

### 4.5 Bundle Restriction Policy Fields
| Field | Description |
|---|---|
| Allow Empty | Allow members with empty restriction field to be bundled. |
| Restrict by Date Only | Restrict by calendar date only, ignore time. |
| Restrict in Automatic Mode | Apply in automatic bundling. |
| Restrict in Manual Mode | Apply in manual bundling. |
| Restriction Field Name | SA field used for restriction. |

### 4.6 Bundle Sort Policy Fields
| Field | Description |
|---|---|
| Sort Direction | Ascending or Descending. |
| Sort Field Name | SA field used for sorting members. |
| Sort Type | "Sort for Automatic Bundling" (order for examining candidates) OR "Sort Within a Bundle" (order of members). |

### 4.7 Setup Steps
1. Add permissions (Field Service Admin, Field Service Integration)
2. Enable bundling in Field Service Settings > Scheduling > Bundling
3. Configure automatic bundling (Automated Bundling and/or Live Bundling)
4. Create recordset filter criteria (optional)
5. Create bundle policy (or use default)
6. Create bundle config (or edit default)
7. Test configuration

---

## 5. EINSTEIN FOR FIELD SERVICE / AI CAPABILITIES

### 5.1 Einstein Generative AI Features
Available in Einstein 1 Field Service Edition. Requires Einstein for Field Service license.

**Pre-Work Brief:**
- Uses generative AI to tell mobile workers everything they need to know about upcoming work order
- Configured via Prompt Builder with "Field Service Pre-Work Brief" template type
- Uses Flow "Field Service Mobile: Generate Pre-Work Brief"
- Data sources: Account, Case, Contact, Pricebook, Service Appointment, Work Order, Work Order Line Item, Work Plans, Work Steps
- Generated first time mobile worker views WO while connected to internet
- Mobile workers can provide feedback
- Multiple flows can be created for different scenarios (e.g., emergency vs. standard)

**Einstein Copilot for Field Service:**
- Natural language interactions to surface customer data
- Out-of-the-box copilot actions
- Available in Dispatcher Console and for mobile workers

### 5.2 Einstein Copilot in Dispatcher Console

**Daily Summary:**
- Immediate overview of critical SAs requiring attention
- Categories: Unscheduled appointments due today, Emergencies, In-jeopardy appointments
- With ESO enabled: also Appointments with rule violations, Overlapping appointments
- Creates filters in appointment list for each category
- Based on up to 4,000 records

**Search and Filter:**
- Search for SAs using natural language
- Create filters from search criteria
- Filters saved in "My Copilot Searches" section

**Customizable Summary Categories:**
- Standard categories: Unscheduled due today, Emergencies, In-jeopardy
- ESO adds: Rule violations, Overlapping appointments
- Admins can add custom categories via dashboards and reports in "Field Service Copilot Dashboards" folder

### 5.3 Recommended Copilot Utterances
- "Summarize my schedule"
- "Summarize my schedule for territories X and Y"
- "Show me unscheduled appointments that are due today"
- "Create a filter for these appointments"
- "Display in the appointments list"

---

## 6. APPOINTMENT ASSISTANT (Customer-Facing Scheduling)

### 6.1 Overview
Keeps track of customer service experience from contact to mobile worker arrival. Requires separate Appointment Assistant managed package and permission set license.

### 6.2 Features

**Real-Time Location:**
- Live tracking of mobile workers via Messaging (SMS, WhatsApp)
- Customers get notifications as mobile worker approaches
- Tracking limited to En Route status until arrival
- Location updates every 60 seconds during tracking
- Worker identification (name, photo) for safety
- Follows Salesforce Ethical Use Principles

**Self-Service Scheduling:**
- Customers book, confirm, reschedule, or cancel appointments
- Only one Appointment Assistant license per org needed
- Supports authenticated users (contacts) and guest users
- Complex work support with ESO enabled
- Authentication flow with verification code via messaging
- Experience Builder site required (NOT LWR templates)

**Contactless Signature:**
- Customers sign service reports on their own device
- Requires service report template and digital signature setup

**Surveys:**
- Salesforce Surveys integration for post-appointment feedback
- GetFeedback integration option

**Pay Now:**
- Flow-based payment link for customers

### 6.3 Setup Requirements
1. Install Appointment Assistant package
2. Create Experience Builder site (NOT LWR templates)
3. Optional: Set up Digital Engagement for SMS/WhatsApp
4. Assign Field Service Appointment Assistant permission set license to each mobile worker
5. Configure geolocation settings
6. Add Real-Time Location to Experience Builder site
7. Create message templates and flows

### 6.4 Geolocation Settings for Real-Time Location
- Enable "Collect service resource geolocation history"
- Set "Geolocation Update Frequency in Minutes"
- Set "Geolocation Update Frequency in Minutes (Background Mode)"
- During tracking, geolocation overridden to update every 60 seconds

### 6.5 Guest User Required Object Access
- Assets: Read
- Contacts: Read
- Locations: Read
- Operating Hours: Read
- Recordset Filter Criteria: Read
- Service Appointments: Read, Create
- Service Crews: Read
- Service Resource Preferences: Read
- Service Resources: Read
- Service Territories: Read
- Service Territory Member: Read
- Shifts: Read
- Work Orders: Read, Create
- Work Type Groups: Read
- Work Types: Read

---

## 7. FIELD SERVICE INTELLIGENCE

### 7.1 Overview
Data-driven solution displaying key contact center performance metrics. Requires Data Cloud + CRM Analytics + Service Cloud in same org. Available in Einstein 1 Field Service Edition or as add-on.

### 7.2 Requirements
- Data Cloud enabled and configured
- CRM Analytics enabled
- Service Cloud features enabled (Email Drafts, Email-to-Case, Omni-Channel, Skills-based Routing, Surveys)
- Field Service Intelligence Admin permission set for setup
- Field Service Intelligence User permission set for access
- Data refresh scheduled (hourly or daily)

### 7.3 Dashboards and KPIs

#### Assets Management Dashboard
| KPI | Calculation |
|---|---|
| Total Assets | Total number of assets. |
| Total Installed Assets | Total number of installed assets. |
| Availability (%) | Average availability from Asset.Availability field. |
| Average Time Between Failures | From Asset.AverageTimeBetweenFailures field. |
| Reliability (%) | Average reliability from Asset.Reliability field. |
| Mean Time to Repair | From Asset.AverageTimeBetweenRepairs field. |
| Unscheduled Downtime | Average unplanned downtime from Asset.UnscheduledDowntime field. |
| Total assets by status | Grouped by status. |
| Total assets by product type | Sorted by product type. |

#### Service Appointments Dashboard
| KPI | Calculation |
|---|---|
| Total Appointments | Total number of SAs. |
| Unscheduled | Total SAs in unscheduled status. |
| Scheduled | Total SAs in scheduled status. |
| Average Travel Time | Estimated travel time from Assigned Resource object. |
| Average Appointment Duration | Average minutes to complete a SA. |
| First Time Fix Rate | % of SAs marked Complete vs total (Complete + Cannot Complete). |
| Due Date (violations) | Total SAs past due date without activity or status. |
| SA by status | Grouped by status. |
| SA by territory | Grouped by service territory. |
| SA by work type | Grouped by work type. |
| SA by time | By day/week/month/year based on scheduled start date. |

#### Work Orders Dashboard
| KPI | Calculation |
|---|---|
| Total Work Order Count | Total WOs created in past 30 days. |
| New Work Orders | Total WOs in New status. |
| Closed Work Orders | Total WOs in Closed status. |
| In Progress Work Orders | Total WOs in progress. |
| Average Response Time | Time between WO creation and SA creation/scheduling. |
| Average Completion Time | Time between WO creation and WO closure. |
| WO by status | Grouped by status. |
| WO by priority | Grouped by priority. |
| WO by account | Grouped by account. |
| WO by time | By day/week/month based on created date. |

#### Parts and Inventory Dashboard
| KPI | Calculation |
|---|---|
| Total Product Items | Sum of Quantity On Hand from ProductItem. |
| Total Products Required | Sum of Quantity Required from ProductRequired. |
| Total Products Consumed | Sum of Quantity Consumed from ProductConsumed. |
| Total Product Requests | Sum of Quantity Requested from ProductRequest line items. |
| Products Required by Work Type | Top products required by work type. |
| Product Requests by Status | Grouped by status. |

#### Resource Management Dashboard
| KPI | Calculation |
|---|---|
| Total Active Resources | Total SRs with Active status. |
| Average Technician Utilization (%) | Hours worked / total available hours. |
| Average Travel Time (Hours) | Estimated travel time for all resources. |
| Average Travel Distance | From AssignedResource.TravelDistance field. |
| On Time Arrival | Total SAs where Actual Start occurs before Scheduled Start. |
| Overtime (Hours) | Total overtime hours. |
| Average Closed Service Appointments | Closed SAs / number of resources for date range. |
| Average Incomplete Service Appointments | Cannot Complete SAs / number of resources for date range. |
| Technician Utilization | Hours worked / available hours by day/week/month/year. |

---

## 8. FIELD SERVICE OPERATIONS HOME & MONITORING

### 8.1 Operations Home
Track and monitor health of field service workforce, assets, processes, and customers.

**Insight Cards (KPIs with Good/Warning/Critical badges):**

| Category | Insight | Description |
|---|---|---|
| Assets | Average Time Between Failures | Track length of time between asset failures. |
| Assets | Unscheduled Downtime | Count of Unplanned Asset Downtime Period records. |
| Resources | Average Travel Time | Average time for assigned resource to travel to appointment. |
| Resources | Resource Utilization Rate | % of hours worked vs total available (SAs + travel + breaks vs absences; availability = operating hours vs timeslots/shifts). |
| Service Appointments | First-Time Fix Rate | % of SAs marked Complete. |
| Service Appointments | Average Appointment Duration | Average duration of Completed SAs (from Duration field). |
| Service Appointments | On-Time Arrival Rate | SAs where Actual Start < Scheduled Start. |
| Service Appointments | Due Date Violations | SAs assigned to resource, past due date, status = None. |
| Service Appointments | Can't Complete SA | SAs with Cannot Complete status. |
| Service Appointments | Unscheduled SAs | SAs with None status. |
| Work Orders | Average WO Response Time | Average time to schedule WO after creation. |
| Work Orders | New Work Orders | Total WOs with New status. |

**Configuration:**
- Click "Manage Insights" to select metrics
- Click "Reorder Followed Insights" to prioritize display
- Adjust KPI thresholds (lower/upper limits)
- Apply filters
- Save custom views (My Views > Save View)

### 8.2 Optimization Hub (ESO Only)
Centralized dashboard for operations managers and business analysts.

**Tabs:**
1. **Home** -- High-level metrics trade-off overview. Before/after optimization comparison.
2. **Schedule** -- SA travel times, break-related metrics before/after. Travel time broken into: from home base, between appointments, back to home base.
3. **Resources** -- Resource types, workloads, availability, utilization before/after. Utilization formula: (Scheduled Duration + Non-Availability + Lunch Breaks + Travel From Home + Travel Between + Travel To Home) / (Overtime Availability + Normal Availability).
4. **Policy** -- How optimization performed vs scheduling policy and service objectives.

**Limitations:**
- KPIs calculated only for primary or relocation members
- Available only for global and in-day optimization requests
- Multiple STM memberships: uses primary territory to prevent double-counting

### 8.3 Activity Reports (Beta, ESO Only)
Monitor scheduling and optimization activities.

**Supported Request Types:**
- Drag and Drop, Get Candidates, Book Appointment, Schedule
- Resource Schedule Optimization, Global Optimization, In Day Optimization
- Fix Schedule Overlaps, Bundling (Manual Requests), Appointment Insights

**Report Fields:**
- Start Time (UTC), End Time (UTC), Duration (ms)
- Object ID (SA ID for Schedule requests)
- Optimization Request ID
- Transaction ID
- Error Label
- Secondary Operations (sliding affecting other SAs)

**Configuration:**
- Generate for specific date range (up to 24 hours within last 30 days)
- Filter by request type and status (succeeded/failed/both)
- Output delayed up to 1 hour
- Downloads as CSV

### 8.4 Appointment Insights (Beta, ESO Only)
Understand why a SA can't be scheduled and which work rules prevent scheduling.

- Checks candidates within 200km radius or 1.5x max travel distance (whichever greater)
- Applies relaxation strategies to suggest scheduling policy changes
- Suggests changes to qualify additional time slots and candidates

### 8.5 Optimization Request Files (Beta, ESO Only)
Retrieve request/response files of optimization requests in JSON format for troubleshooting.

---

## 9. STATUS CATEGORIES AND THEIR USAGE

Status Category is referenced (instead of Status) in these processes:
- Status-based sharing rules for WO, WOLI, SA
- Status-based paths
- Preventive maintenance (Complete = Cannot Complete, Canceled, Completed, Closed)
- Dispatcher console appointment list filters
- Dispatch scheduled jobs (triggered by Dispatched status category)
- Dispatch drip feed (triggers on Dispatched/In-Progress changing to Canceled/Completed/Cannot Complete)
- Calendar syncing (checks for Dispatched status category)
- Completed icon on dispatcher console map (Completed status category)
- KPI for completed SAs on Gantt/capacity view (Completed status category)

---

## 10. KEY BEST PRACTICES

### Scheduling
- Use scheduling policy WITHOUT service objectives for gradeless appointment booking (improved performance)
- Include Service Resource Availability work rule in every scheduling policy
- Resources must have geocoded home base locations
- Territory membership start/end at midnight (00:00) recommended
- Keep territories under 50 resources, 1000 SAs/day, 20 qualified resources per SA
- Assign fewer than 50 skills per service resource
- Don't delete Street Level Routing Cache custom object

### Travel Time
- Three travel time fields on Assigned Resource: Actual (manual), Estimated (system), Approximate Travel Time From (last SA only)
- Emergency work uses Real-Time Travel from Google
- ESO uses point-to-point predictive routing regardless of settings
- Travel Time Buffer adds setup time (parking, walking) -- not added to consecutive same-site appointments

### Time Zones
- Each territory must align with ONE time zone only
- Use Map Polygons to define geographical boundaries
- Appointment booking ignores timezone on arrival windows operating hours -- uses territory's timezone instead
- Date/time fields auto-convert to viewer's timezone

### Status Management
- Always create custom Status values with proper Status Category assignment
- Status Category determines process behavior, not Status value
- WO status changes do NOT cascade to WOLI or SA

### Data Integrity
- Map external latitude/longitude to ServiceAppointment.Latitude/Longitude, NOT internal SLR geolocation fields
- Resource efficiency ranges from 0.1 to 10 (1 = average)
- Capacity-based resources support only Day time period in ESO
