# FSL Territories, Resources & Setup — Complete Reference

Source: Salesforce Field Service Guide (Spring '26)
PDF: https://resources.docs.salesforce.com/latest/latest/en-us/sfdc/pdf/support_field_service.pdf

---

## Service Territories

### What They Are
Service territories represent regions where mobile workers provide services. They form a hierarchy for organizing resources and scheduling.

### Territory Hierarchy
- **Root territories**: Top-level (e.g., state/region)
- **Child territories**: Subdivisions (e.g., city/district)
- Max 10,000 territories in a hierarchy
- Modular structure enhances optimization's ability to build effective schedules

### Territory Membership Types
| Type | Description | Scheduling Behavior |
|------|-------------|-------------------|
| **Primary** | Resource's main territory | Always considered for scheduling |
| **Secondary** | Additional territories resource can cover | Considered when Working Territories rule allows |
| **Relocation** | Temporary reassignment territory | Used during relocation period |

### Key Fields
- **Operating Hours**: When work can be performed in this territory
- **Travel Mode** (ESO): Transportation type for routing calculations
- **Active**: Whether territory is active for scheduling

### Territory Sizing Guidelines (RECOMMENDED)
- **Up to 50 service resources** per territory
- **Up to 1,000 service appointments per day** per territory
- **Up to 20 qualified service resources** per SA (after work rules filter)

### Territory Best Practices
- Create highest-level territories first, then build down
- Must NOT span multiple time zones (split if needed)
- Address on territory = home base for travel calculations
- STM memberships should be 24+ hours, start/end at midnight (00:00)
- For optimization, memberships can't be longer than 3 years (leave End Date blank for longer)
- STMs must have home base location geocoded
- Only ONE primary territory per resource
- Use Map Polygons (KML) for geographic boundaries

### Territory and AAA
- Each AAA garage = a Service Territory
- Garage code starts with 100 (Fleet) or 800 (Fleet)
- Towbook garages are also territories but dispatched by Towbook
- Territory hierarchy: AAA org → state → garage

---

## Service Resources

### What They Are
Service resources are mobile workers assignable to service appointments. In AAA: ERS drivers.

### Resource Types
| Type | Description | AAA Mapping |
|------|-------------|------------|
| **Individual** | Single worker | ERS driver |
| **Crew** | Group of workers | Not used in AAA ERS |
| **Capacity-based** | Resource with capacity units | Not used in AAA ERS |

### Key Fields
| Field | Purpose | AAA Notes |
|-------|---------|-----------|
| **Name** | Resource name | Driver name |
| **IsActive** | Whether available for scheduling | Must be true |
| **LastKnownLatitude/Longitude** | Current GPS position | Updated by FSL mobile app. Towbook: NEVER updated (0/72 have data) |
| **LastKnownLocationDate** | When GPS was last updated | Stale > 30 min = unreliable |
| **ERS_Driver_Type__c** | Fleet Driver / On-Platform Contractor / Off-Platform Contractor | Custom field distinguishing driver types |
| **Efficiency** | Work speed factor (1.0 = normal) | Rounded up in ESO |

### Resource → Territory Membership (ServiceTerritoryMember)
- Links a resource to a territory
- **Address fields** on STM = "home base" for Maximum Travel from Home rule
- **AAA problem**: 0/501 STM addresses populated → Scheduler can't calculate travel from home
- **Operating Hours** on STM override territory operating hours for that resource
- Max 100 STMs per resource (recommended)
- Only primary STMs can have Travel Mode assigned (ESO)

### Skills
- Assigned to resources via ServiceResourceSkill
- Required skills defined on WO/WOLI
- Match Skills work rule enforces skill requirements
- Max 250 skills per resource (ESO)
- **Skill Level**: proficiency rating (used by Skill Level objective)
- **Skill Preference**: priority within skill type (used by Skill Preference objective, ESO only)

### AAA Skill Hierarchy
```
Tow (highest) → can do everything
Battery → can do battery + light service
Light (lowest) → light service only
```
- TOW_SKILLS: Tow, Flat Bed, Wheel Lift, Winch Out
- BATTERY_SKILLS: Battery, Jumpstart
- LIGHT_SKILLS: Tire, Lockout, Fuel Delivery

### Resource Absences
- Mark resource as unavailable for a time period
- Used by Service Resource Availability work rule
- **AAA workaround**: Create absences for drivers without GPS/app login to remove them from candidate pool
- This improved auto-assignment from 0% to 83%

---

## Operating Hours

### What They Are
Define when resources are available and customers accept visits. Critical for scheduling.

### Types of Operating Hours
| Applied To | Purpose |
|-----------|---------|
| **Service Territory** | When work can be done in the territory |
| **Service Territory Member** | Override territory hours for specific resource |
| **Service Appointment** | Customer visiting hours |
| **Account** | Customer-level availability |

### Configuration
- Defined as time slots per day of week
- Can include breaks (ESO: up to 3 flexible breaks)
- Extended hours (overtime) can be configured separately
- Max 2,000 operating hours records in lookup

### Operating Hours Limitations
- Can't span full 24 hours — use 00:00 to 23:58
- 24-hour coverage NOT supported for mobile workers and capacity-based resources
- For 24h capacity-based: use 12:00 AM to 23:59
- Without managed package: operating hours are suggestions only
- With managed package: enforced during optimization
- ESO: "Respect secondary STM operating hours" setting available
- Holidays: ESO required for holidays to actually impact scheduling (otherwise cosmetic only)

### AAA Operating Hours
- ERS runs 24/7 → operating hours must reflect this (use 00:00-23:58)
- All ERS territories need 24/7 operating hours
- No overtime concept for ERS (drivers work shifts, but service is continuous)

---

## Work Types

### What They Are
Templates for common field service work. Define duration, skills required, and auto-create SAs.

### Key Fields
| Field | Purpose |
|-------|---------|
| **Name** | Work type name (e.g., "Tow", "Battery Service") |
| **Estimated Duration** | How long the work takes |
| **Auto-Create Service Appointment** | Whether SA is auto-created on WO/WOLI |
| **Due Date Offset** | Days between created date and due date for auto-created SAs |
| **Timeframe Start/End** | Time-of-day restrictions |

### Duration Best Practices
- Base on historical data + resource feedback
- Review frequently at start, less frequently as estimates stabilize
- Better estimates = less scheduling uncertainty

### AAA Work Type Durations (from utils.py)
| Work Type | Cycle Time (min) |
|-----------|-----------------|
| Tow | 115 |
| Battery | 38 |
| Light Service | 33 |

---

## Service Appointments

### Lifecycle / Status Categories
| Status Category | Description |
|----------------|-------------|
| **None** | Initial state, not yet scheduled |
| **Scheduled** | Assigned to resource + time slot |
| **Dispatched** | Sent to mobile worker |
| **In Progress** | Work started |
| **Completed** | Work finished |
| **Canceled** | Cancelled before completion |
| **Cannot Complete** | Started but couldn't finish |

### Key Time Fields
| Field | Description | AAA Notes |
|-------|-------------|-----------|
| **CreatedDate** | When SA was created | Start of clock for all time metrics |
| **EarliestStartPermitted** | Earliest scheduling allowed | Mandatory for scheduling |
| **DueDate** | Latest scheduling allowed | Mandatory for scheduling |
| **SchedStartTime** | Scheduled start time | When scheduler assigned driver |
| **SchedEndTime** | Scheduled end time | Based on duration |
| **ActualStartTime** | Actual work start | Fleet: real arrival. Towbook: FAKE |
| **ActualEndTime** | Actual work end | Completion time |
| **ArrivalWindowStart/End** | Customer-facing arrival window | Promised time window |
| **EstimatedTravelTime** | Calculated travel time | From previous appointment or home |

### Scheduling Fields
| Field | Description |
|-------|-------------|
| **ServiceTerritoryId** | Territory this SA belongs to |
| **Auto Schedule** | Checkbox — auto-schedule on creation |
| **Scheduling Policy Used** | Which policy to use for auto-scheduling |
| **IsOffsiteAppointment** | Virtual/locationless appointment (ESO) |
| **Pinned** | Exclude from optimization |

### SA Priorities
- Priority field controls scheduling order
- Higher priority SAs scheduled first
- With sliding + reshuffling (ESO): lower priority SAs can be dropped to make room
- Dynamic priorities possible (e.g., increase as due date approaches)

---

## Assigned Resources

### What They Are
Junction object linking Service Appointments to Service Resources.

### Key Fields
| Field | Description | AAA Notes |
|-------|-------------|-----------|
| **ServiceResourceId** | The assigned resource | Driver |
| **ServiceAppointmentId** | The appointment | The call |
| **CreatedBy** | Who created the assignment | Key for dispatch method detection (IT System User = auto, human = manual) |
| **EstimatedTravelTime** | Travel time to appointment | Calculated by scheduler |
| **EstimatedTravelTimeFrom** | Travel time from previous appointment | — |
| **ActualTravelTime** | Actual travel time | From mobile app |

---

## Dispatch Methods

### Manual Dispatch (Dispatcher Console)
- Dispatch from appointment list or Gantt
- Changes status: Scheduled → Dispatched

### Auto-Dispatch (Scheduled Jobs)
- Field Service Settings > Dispatch > Scheduled Jobs
- Select territories, timing, filter criteria, horizon
- Dispatches based on STM (primary + relocation), not SA territories
- Option: mention assigned resources via Chatter

### Drip Feed
- Dispatches at steady pace — maintains N appointments in each worker's queue
- Configurable default, overridable per territory
- When Dispatched/InProgress SA → Completed/Canceled, next SA dispatched

### SA Limitations
- SA with Scheduled Start/End but NO Assigned Resource = **corrupted, unexpected behavior**
- Seconds/milliseconds NOT supported in datetime fields
- Max 200 SAs per resource per day (bundled counts as 1)
- Max 50,000 SAs optimized per rolling 24 hours
- Max 56 calendar days for multiday SAs
- Owner and Parent Record fields not available in custom report types or formulas/flows

---

## Dispatcher Console

### Components
1. **Appointment List**: Filterable list of SAs (max 3,000)
2. **Gantt Chart**: Visual schedule timeline (max 500 rows)
3. **Map**: Interactive map with resources, appointments, territories
4. **Resource List**: All resources with status

### Key Actions from Console
- Schedule/Unschedule appointments
- Drag & drop assignments
- Run optimization (Global, In-Day, RSO)
- Fix overlaps
- Group nearby appointments (max 50 at once)
- Fill-in schedule gaps
- Emergency wizard
- Get candidates for an SA

### Gantt Features
- Long-term view (up to 1,000 SAs)
- Rule violation indicators
- Skills filter (max 2,000 skills)
- Map polygons for territory visualization (max 30,000 polygons)
- Report markers (max 500)

---

## Data Integration Rules

### Geolocation Resolution
- Built-in service resolves addresses → lat/lon coordinates
- Used for travel time calculations between appointments
- If addresses have data issues (missing house number, ZIP) → inaccurate geolocations → bad scheduling
- **Use validation rules** on address fields to ensure data integrity
- Report on lat/lon fields to find gaps

### Travel Time Calculations
- **Legacy**: Street-level routing (SLR) or airline distance
- **ESO**: Point-to-point predictive routing (always, regardless of routing settings)
- Travel modes (ESO): Car, Light Truck, Heavy Truck, Bicycle, Walking
- Toll roads and hazmat considerations per travel mode
