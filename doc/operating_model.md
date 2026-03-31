# AAA Western & Central NY — ERS Operating Model

How Emergency Roadside Service works end-to-end and how every piece is captured in Salesforce.

---

## 1. The Two-Channel Model

AAA WCNY runs ERS through two dispatch channels:

| | **Fleet (Field Services)** | **External Garages (Towbook)** |
|---|---|---|
| **Volume** | ~26% of calls | ~74% of calls |
| **Drivers** | ~115 on-shift at any time (internal AAA employees) | ~73 garage facilities with their own drivers |
| **Dispatch** | Mulesoft assigns directly to a driver | Mulesoft sends to garage → garage assigns their own driver |
| **GPS** | Real-time (ServiceResource.LastKnownLat/Lon) | Static garage location only (ServiceTerritory lat/lon) |
| **Arrival Time** | Reliable (driver marks arrival in mobile app → ActualStartTime) | **UNRELIABLE** (ActualStartTime bulk-synced at midnight, NOT real arrival) |
| **SF Resource** | Named ServiceResource (e.g., "John Smith") | Placeholder ServiceResource (e.g., "Towbook-053", one per garage) |
| **Identifier** | `ERS_Dispatch_Method__c = 'Field Services'` | `ERS_Dispatch_Method__c = 'Towbook'` |

---

## 2. End-to-End Call Flow

```
Member calls AAA → D3/Axis platform creates WorkOrder + WOLI + ServiceAppointment
    ↓
Mulesoft (ERS_SA_AutoSchedule) picks up the SA
    ↓
Looks up ServiceTerritory for member's geolocation
    ↓
Checks Priority Matrix → finds Rank 1 garage for that zone
    ↓
┌─────────────────────────────────┐
│ Is Rank 1 garage Fleet or       │
│ Towbook?                        │
├────────────┬────────────────────┤
│ FLEET      │ TOWBOOK            │
│            │                    │
│ Query Asset│ Send to Towbook    │
│ for logged-│ API (external      │
│ in drivers │ platform)          │
│            │                    │
│ Pick best  │ Garage dispatcher  │
│ driver by  │ assigns their own  │
│ proximity +│ driver             │
│ skill +    │                    │
│ workload   │                    │
├────────────┴────────────────────┤
│ Driver/Garage accepts or declines│
├──────────────┬──────────────────┤
│ ACCEPTED     │ DECLINED          │
│              │                   │
│ Status →     │ Record decline    │
│ Dispatched   │ reason, loop to   │
│ → En Route   │ Rank 2 garage     │
│ → On Location│ (cascade)         │
│ → Completed  │                   │
└──────────────┴──────────────────┘
```

**Important**: Salesforce FSL scheduling engine is NOT used for dispatch. Zero SAs graded, zero updated by optimization. Mulesoft handles everything independently.

---

## 3. Territories & Garages

### What a "Territory" Represents
Each ServiceTerritory is either a **zone** (geographic area) or a **garage** (physical facility):
- 443 total territories (405 active, 38 inactive)
- Top-level territories represent dispatch zones
- Child territories represent individual garages within a zone
- `ServiceTerritory.Latitude/Longitude` = garage physical address or zone center
- `ERS_Facility_Account__r.Dispatch_Method__c` = 'Fleet' or 'Towbook'

### How Garages are Linked
```
ServiceTerritory (garage)
  ├── ERS_Facility_Account__c → Account (Facility RecordType, 1,465 total)
  │     ├── Name, Phone, BillingAddress
  │     └── Dispatch_Method__c ('Fleet' or 'Towbook')
  ├── Latitude, Longitude (garage location)
  ├── OperatingHoursId → OperatingHours (shift schedule)
  └── ServiceTerritoryMember[] → ServiceResource[] (drivers assigned to this garage)
```

---

## 4. The Priority Matrix (Dispatch Cascade)

### What It Is
`ERS_Territory_Priority_Matrix__c` maps every zone to an ordered list of garages. When a call comes in for Zone X, Mulesoft knows to try Garage A first (rank 1), then Garage B (rank 2), etc.

### Structure
| Field | Description |
|---|---|
| `ERS_Parent_Service_Territory__c` | The zone where the member is located |
| `ERS_Spotted_Territory__c` | The garage being ranked for this zone |
| `ERS_Priority__c` | Numeric rank (lower = higher priority) |
| `ERS_Worktype__c` | Optional filter (some garages only handle certain work types) |

### How Spotting Number Works
- `ERS_Spotting_Number__c` on ServiceAppointment is a **formula field**
- Returns the assigned garage's rank for the SA's zone
- **1** = This garage was the primary (first call)
- **2+** = This garage was secondary (called after primary declined)
- **null** = No priority matrix entry exists (common for Towbook garages)

### Cascade Example
```
Member breaks down in Zone "Buffalo East"
  → Priority Matrix lookup:
    Rank 1: "076 - Downtown Fleet"      → Fleet, try first
    Rank 2: "Towbook-053 - Joe's Tow"   → Towbook, if Fleet declines
    Rank 3: "Towbook-081 - AAA Towing"   → Towbook, if both decline
```

If Rank 1 declines (e.g., "End of Shift", "Meal/Break", "Out of Area"), Mulesoft cascades to Rank 2, then 3, etc.

### Decline Reasons (ERS_Facility_Decline_Reason__c)
| Reason | Count | Notes |
|---|---|---|
| Towbook Decline | 24,000 | Generic Towbook platform decline |
| End of Shift | 3,293 | Garage closing / drivers going home |
| Meal/Break | 2,431 | Drivers on break |
| Out of Area | 1,478 | Member too far from garage |
| Truck not capable | 1,051 | Skill mismatch |
| Long tow | 486 | Tow distance too far for garage |

---

## 5. How Drivers Work

### Fleet Driver Login (On-Shift Detection)
Fleet drivers "login" by being assigned to an Asset (ERS Truck):
```
Asset (RecordType = 'ERS Truck')
  ├── ERS_Driver__c → ServiceResource.Id (the driver)
  ├── Name: "076 - Service Unit 1" (truck identifier)
  ├── ERS_Truck_Capabilities__c: "Tow, Light Service" or "Battery"
  └── ERS_LegacyTruckID__c: Legacy system ID
```
**Query for on-shift drivers:**
```sql
SELECT ERS_Driver__c, Name, ERS_Truck_Capabilities__c
FROM Asset
WHERE RecordType.Name = 'ERS Truck'
  AND ERS_Driver__c != null
```
Returns ~115 drivers at any time. This replaced the old GPS freshness check (2-hour cutoff was unreliable).

### GPS Tracking
- `ServiceResource.LastKnownLatitude/Longitude` — updated real-time from mobile app
- `ServiceResource.LastKnownLocationDate` — when GPS last pinged
- Travel speed assumption: 25 mph (Buffalo metro average)
- Only Fleet drivers have GPS via ServiceResource.LastKnownLatitude/Longitude
- **Towbook drivers ARE visible** via SA fields:
  - `Off_Platform_Driver__r.Name` — real driver name (e.g., "Daniel Brusie")
  - `Off_Platform_Truck_Id__c` — truck ID (e.g., "076DO-173072")
  - `ERS_OffPlatformDriverLocation__c` — driver GPS location
  - `ERS_OffPlatformDriverTrackingLink__c` — tracking link
  - `ERS_Assigned_Resource__r.Name` is generic "Towbook-076DO" (one per garage), NOT useful for individual drivers

### Skill Hierarchy
Drivers have skills tied to their truck type. Skills overlap in a hierarchy:
```
TOW DRIVER (can do everything)
  ├── Tow, Flat Bed, Wheel Lift
  ├── Light Service: Tire, Lockout, Winch, Fuel
  └── Battery, Jumpstart

LIGHT SERVICE DRIVER
  ├── Tire, Lockout, Winch, Fuel, Locksmith
  └── Battery, Jumpstart

BATTERY DRIVER (most limited)
  └── Battery, Jumpstart only
```
**Key insight**: Fleets are NOT independent. An idle Tow driver CAN cover a Battery call. An idle Light driver CAN cover a Battery call. This is the basis for cross-skill cascade dispatch.

### 55 Skills in the System
| Category | Skills |
|---|---|
| ERS Core | Tow (322K reqs), Battery (91K), Flat Bed (81K), Tire (42K), Lockout (25K) |
| ERS Other | Winch Out, Fuel, Locksmith, EV, Extrication, PVS, Jumpstart |
| Non-ERS | Insurance, Travel, Membership (different business lines) |

---

## 6. Service Appointment Lifecycle

### Status Flow
```
Scheduled → Assigned → Dispatched → En Route → On Location → Completed
                 ↓            ↓           ↓
           Cancel-NotEnRoute  Cancel-EnRoute  Unable to Complete
                                               No-Show
```

### What Each Status Means
| Status | Meaning | StatusCategory |
|---|---|---|
| Scheduled | Call logged, waiting for dispatch | Scheduled |
| Assigned | Garage/driver assigned, not yet acknowledged | Scheduled |
| Dispatched | Driver notified, waiting for acceptance | Dispatched |
| En Route | Driver accepted, driving to member | InProgress |
| On Location | Driver arrived at member | InProgress |
| Completed | Work done | Completed |
| Cancel Call - Service Not En Route | Member canceled before driver departed | Canceled |
| Cancel Call - Service En Route | Member canceled while driver was driving | CannotComplete |
| Unable to Complete | Driver couldn't fix / member refused | CannotComplete |
| No-Show | Driver never arrived | Canceled |

### Cancellation Reasons (ERS_Cancellation_Reason__c)
| Reason | Count | Notes |
|---|---|---|
| Member got going | 28,741 | Member fixed it or got a ride |
| Could Not Wait | 17,799 | Wait too long → PTA breach |
| Facility initiated | 14,799 | Garage canceled after accepting |

---

## 7. The Tow Dual-SA Pattern

Every tow call creates **two** ServiceAppointments, linked via `ERS_Tow_Pick_Up_Drop_off__c`:

```
Tow Pick-Up SA (where driver meets member)
  ├── ERS_Tow_Pick_Up_Drop_off__c → Drop-Off SA
  ├── WorkType: "Tow Pick-Up" (162K SAs)
  ├── Geolocation: Member's breakdown location
  └── Response time = CreatedDate → ActualStartTime (THIS is the member's wait)

Tow Drop-Off SA (where driver takes the vehicle)
  ├── ERS_Tow_Pick_Up_Drop_off__c → Pick-Up SA
  ├── WorkType: "Tow Drop-Off" (164K SAs)
  ├── Geolocation: Destination (repair shop, home, etc.)
  └── EXCLUDE from response time metrics
```

315,891 SAs have this link. Always exclude Drop-Off from member-facing response time analysis.

---

## 8. How Performance is Measured

### Response Time (ATA = Actual Time to Arrival)
- **Formula**: `ActualStartTime - CreatedDate` (in minutes)
- **Only reliable for Field Services** (driver marks arrival real-time)
- **Towbook**: ActualStartTime is bulk-synced at midnight → shows 300+ min → EXCLUDE
- **Exclusions**: Tow Drop-Off SAs (member wait = Pick-Up only)
- **Typical range**: 17-88 min (Field Services)

### Promised Time to Arrival (PTA)
- `ERS_PTA__c` = minutes promised by Mulesoft
- `ERS_PTA_Due__c` = timestamp when PTA expires
- PTA breach = member waited longer than promised → drives "Could Not Wait" cancellations

### 1st Call Acceptance
- When garage is primary (ERS_Spotting_Number__c = 1), what % accepted without declining?
- **Pitfall**: Formula field, returns int `1` or float `1.0` → check `in (1, 1.0)`
- **Pitfall**: Many garages have no spotting data → fallback to overall acceptance rate
- In FSLAPP: `first_call_source` = 'spotting' (primary rank data exists) or 'acceptance' (fallback)

### Completion Rate
- `Completed / Total dispatched` (all statuses except pure cancellations)

### Survey Satisfaction (the Business KPI)
- **KPI**: Total Satisfied % (NOT NPS)
- **Target**: ~82% (accreditation requirement)
- **Current**: 79% Totally Satisfied + 9% Satisfied = 88% total
- **Matched by**: WorkOrder number (surveys arrive days later)
- **Fields**: `ERS_Overall_Satisfaction__c`, `ERS_Response_Time_Satisfaction__c`, `ERS_Technician_Satisfaction__c`

### Cycle Times (Verified from 076DO territory, Jan-Mar 2026)
| Work Type | Total | Travel-To | On-Site | Notes |
|---|---|---|---|---|
| Tow | 115 min | 21 min (8.8 mi) | 17 min pick-up + 34 min drive + 43 min drop-off | Longest cycle |
| Battery | 38 min | 18 min (7.3 mi) | 20 min on-site | Most common |
| Light Service | 33 min | 20 min (8.5 mi) | 13 min weighted avg | Tire 14.5, Lockout 7.5, Winch 14.5, Fuel 7.4 |

---

## 9. Volume Drivers & Seasonality

| Factor | Impact | Notes |
|---|---|---|
| Day-of-Week | **#1 driver** | Mon 1,742 calls vs Sun 976 (1.8x) |
| Cold Temps | **#2 driver** | Freezing → +28% volume (battery failures) |
| Snow | **#3 driver** | 1.15x multiplier |
| December | **Peak month** | 1,635/day (cold + holidays + battery) |
| Jan-Apr 2025 | Exclude | System not fully live, only ~90 SAs/day |

### Weather Severity Impact
| Severity | Conditions | Volume Impact |
|---|---|---|
| Clear/Mild | Normal | Baseline |
| Moderate | Snow <6", 15-32°F | +5-10% |
| Severe | Snow 6-12", sub-zero | +15-30%, longer response |
| Extreme | Blizzard, ice storm, <-10°F | Surge + delays + high cancellations |

---

## 10. Key SF Object Relationships (Visual)

```
Account (Member, 1.24M Person Accounts)
  │
  ├── WorkOrder
  │     ├── WorkOrderLineItem (WOLI)
  │     │     └── ServiceAppointment (SA) ← THE CORE RECORD
  │     │           ├── ServiceTerritory (zone/garage)
  │     │           ├── WorkType (Tow, Battery, etc.)
  │     │           ├── AssignedResource → ServiceResource (driver)
  │     │           │                        ├── ServiceTerritoryMember (territory assignment)
  │     │           │                        ├── ServiceResourceSkill (capabilities)
  │     │           │                        └── LastKnownLat/Lon (GPS)
  │     │           └── ERS_Tow_Pick_Up_Drop_off__c → other SA (tow pair)
  │     │
  │     └── Survey_Result__c (matched by WO number)
  │
  ├── Asset (ERS Truck, for Fleet vehicle login)
  │     ├── ERS_Driver__c → ServiceResource
  │     └── ERS_Truck_Capabilities__c
  │
  └── Contact (member contact info)

Account (Facility, 1,465 garages)
  ├── Dispatch_Method__c ('Fleet' or 'Towbook')
  └── ServiceTerritory.ERS_Facility_Account__c (backlink)

ERS_Territory_Priority_Matrix__c (cascade rules)
  ├── ERS_Parent_Service_Territory__c → ServiceTerritory (zone)
  ├── ERS_Spotted_Territory__c → ServiceTerritory (garage)
  └── ERS_Priority__c (rank 1, 2, 3...)
```
