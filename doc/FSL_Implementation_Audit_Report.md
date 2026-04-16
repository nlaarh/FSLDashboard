# AAA Western & Central New York — FSL Implementation Audit Report

**Prepared:** April 8, 2026
**Purpose:** Comprehensive review of Salesforce Field Service (FSL) implementation for auditor assessment and optimization recommendations
**Org:** AAA WCNY Emergency Roadside Service (ERS)

---

## 1. Executive Summary

AAA WCNY operates an Emergency Roadside Service (ERS) program using Salesforce Field Service Lightning (FSL) to manage dispatch of tow trucks and service vehicles across Western and Central New York. The implementation uses a two-channel dispatch model: Fleet drivers dispatched via the FSL Scheduler, and external contractors dispatched via Towbook (a third-party towing dispatch platform).

**Key Findings:**

- 406 active Service Territories organized in a regional hierarchy
- 519 active Service Resources (drivers) across 4 driver types
- 5 Scheduling Policies exist, all focused on proximity — none include workload balancing
- On-Platform Contractor facilities lack shifts, operating hours, and capacity configuration
- Auto-assignment creates "hot driver" patterns where the system repeatedly assigns the same driver based on proximity, requiring manual dispatcher intervention to redistribute

---

## 2. Territory Architecture

### 2.1 Territory Hierarchy

The org uses a two-level territory hierarchy:

**Parent Territories (Regions):**

| Region Code | Region | Child Facilities |
|---|---|---|
| WNY M | Western New York Metro | 22 |
| ROC M | Rochester Metro | 23 |
| CNYM | Central New York Metro | 41 |
| ST | Southern Tier | 38 |
| NC | North Country | varies |
| WM | Western Market | 62 |
| CR | Central Region | 61 |
| RR | Rochester Region | 35 |
| RM | Rochester Market | 31 |
| WR | Western Region | 23 |

**Total:** 406 active territories (44 inactive), organized under ~16 parent regions.

### 2.2 Territory Types

Each facility is a child Service Territory under its regional parent. Territories represent:

- **Fleet Territories** — AAA-owned trucks and drivers (e.g., "100 - WESTERN NEW YORK FLEET")
- **On-Platform Contractor Facilities** — External garages using the FSL platform (e.g., "076DO - TRANSIT AUTO DETAIL")
- **Off-Platform (Towbook) Facilities** — External garages dispatched via Towbook integration
- **Spot Territories** — Temporary coverage areas (e.g., "000- WNY M SPOT")

### 2.3 Operating Hours

Territories are assigned operating hours defining when they accept dispatches:

| Operating Hours | Usage |
|---|---|
| AAA 24/7/365 Operating Hours | Most common — majority of facilities |
| Sun-Sat, 7a-11p | Fleet territories and some contractors |
| Sun-Sat, 7a-10p | Several contractor facilities |
| Mon-Fri, 8a-5p | Limited weekday-only facilities |
| Mon-Sat, 7a-10p | Some contractor facilities |
| Various others | Facility-specific schedules |

**Issue Identified:** While territories have operating hours, individual Service Resources (drivers) at On-Platform Contractor facilities have NO operating hours set on their ServiceTerritoryMember records and NO shift records. This means the system cannot determine individual driver availability windows.

---

## 3. Service Resources (Drivers)

### 3.1 Driver Population

| Driver Type | Active Count |
|---|---|
| On-Platform Contractor Driver | 240 |
| (null — not classified) | 123 |
| Fleet Driver | 85 |
| Off-Platform Contractor Driver | 71 |
| **Total** | **519** |

### 3.2 Resource Configuration

Each ServiceResource record contains:

| Field | Purpose | Current State |
|---|---|---|
| `IsActive` | Whether driver is active | Set for all active drivers |
| `IsOptimizationCapable` | Include in scheduling optimization | Mostly `true`; some contractors set to `false` |
| `FSL__Efficiency__c` | Efficiency rating for scheduling | **null for all drivers** — not configured |
| `FSL__Priority__c` | Priority ranking for Resource Priority objective | **null for all drivers** — not configured |
| `FSL__Travel_Speed__c` | Custom travel speed | **null for all drivers** — not configured |
| `Schedule_Type__c` (Commute Type) | On Schedule / Off Schedule | 271 On Schedule, 117 Off Schedule, 131 null |
| `AAA_ERS_MaxTravelDuration__c` | Max travel time to a call | "Unlimited" for most drivers |
| `LastKnownLatitude/Longitude` | Real-time GPS position | Updated via mobile app when driver is active |
| `ERS_Driver_Type__c` | Fleet / On-Platform / Off-Platform | Set per driver |

### 3.3 Territory Membership

Drivers are linked to territories via ServiceTerritoryMember:

| Membership Type | Count |
|---|---|
| Primary (P) | 764 |
| Secondary (S) | 233 |

**ServiceTerritoryMember Configuration:**

| Field | Expected | Actual State |
|---|---|---|
| Latitude/Longitude (homebase) | Driver's home location for travel calculation | **Newly added (April 2026)** — was null for all drivers in original setup |
| Operating Hours | Driver-specific schedule | **null for all On-Platform Contractor drivers** |
| Street/City/State/PostalCode | Home address | **null for all drivers** — addresses not populated |

**Issue Identified:** Without coordinates on the STM, the FSL Scheduler cannot calculate accurate travel times from the driver's homebase. The system falls back to `LastKnownLocation` on the ServiceResource, which only updates when the driver's mobile app reports GPS. Drivers who aren't actively using the app appear "invisible" to the scheduler.

---

## 4. Skills Framework

### 4.1 How Skills Work

Skills are **dynamically assigned** based on the truck a driver logs into. When a driver starts their shift and logs into a specific vehicle, the system assigns the skills associated with that truck's capabilities. When they log out, skills are removed.

This means a driver's skill set changes throughout the day based on what truck they're operating.

### 4.2 Skill Inventory (ERS-related)

| Skill | Active Assignments | Category |
|---|---|---|
| EV | 365 | Base (all drivers) |
| Driver Tire | 362 | Base (all drivers) |
| Miscellaneous | 193 | Service truck |
| Lockout | 187 | Service truck |
| Fuel - Gasoline | 187 | Service truck |
| Tire | 185 | Service truck |
| Fuel - Diesel | 185 | Service truck |
| Tow | 170 | Tow truck |
| Extrication - Driveway | 170 | Tow truck |
| Battery Certified | 159 | Service truck |
| Flat Bed | 155 | Tow truck (flatbed) |
| Extrication - Highway/Roadway | 155 | Tow truck |
| Battery Service | 125 | Service truck |
| Jumpstart | 125 | Service truck |
| Wheel Lift Truck | 102 | Tow truck (wheel lift) |
| Low clearance | 96 | Tow truck (specialty) |
| Motorcycle Tow | 86 | Tow truck (specialty) |
| Long Tow | 82 | Tow truck (long distance) |

### 4.3 Skill Categories by Truck Type

**Base skills (all drivers when logged in):** EV, Driver Tire

**Tow Truck skills:** Tow, Flat Bed, Extrication-Driveway, Extrication-Highway/Roadway, Low clearance, Motorcycle Tow, Wheel Lift Truck, Long Tow

**Service Truck skills:** Battery Certified, Battery Service, Jumpstart, Fuel-Gasoline, Fuel-Diesel, Lockout, Tire, Miscellaneous

### 4.4 Skill Matching in Dispatch

The "Match Skills" work rule is active on all scheduling policies. When a Service Appointment requires "Tow" skill, only drivers currently logged into a tow truck (who have the Tow skill) are eligible candidates. This is the primary filter that determines which drivers can be assigned to which calls.

**Issue Identified:** At any given facility, only a subset of drivers are logged into trucks. For example, at 076DO - Transit Auto Detail, only 13 of 50 drivers were logged into tow trucks on April 8, 2026 — and 30 drivers had only base skills (not logged into any truck). This dramatically narrows the candidate pool for auto-assignment.

---

## 5. Work Types

ERS-relevant Work Types:

| Work Type | Description |
|---|---|
| Tow Pick-Up | Tow service — pick up member's vehicle |
| Tow Drop-Off | Tow service — deliver vehicle to destination |
| Battery | Battery testing and replacement |
| Lockout | Vehicle lockout service |
| Tow | Generic tow (legacy) |

Tow Pick-Up and Tow Drop-Off are always created in pairs — one SA for the pickup location, one for the drop-off destination. Both are assigned to the same driver.

---

## 6. Dispatch Architecture

### 6.1 Two-Channel Model

```
Incoming ERS Call
       │
       ▼
  Mulesoft Routing Engine
       │
       ├── Fleet Territory? ──► FSL Scheduler (auto-assign)
       │                            │
       │                            ▼
       │                    Closest Driver policy
       │                    (skills + proximity)
       │
       ├── On-Platform Contractor? ──► IT System User (Flow/Apex automation)
       │                                    │
       │                                    ▼
       │                             Auto-assign to closest
       │                             skill-matched driver
       │
       └── Off-Platform? ──► Towbook Integration
                                    │
                                    ▼
                             Towbook placeholder resource
                             (facility manages own dispatch)
```

### 6.2 Assignment Sources

Based on AssignedResource.CreatedBy analysis:

| Assigner | Type | Description |
|---|---|---|
| IT System User | System | Salesforce Flow/Apex automation — primary auto-assigner |
| Mulesoft Integration | System | Mulesoft dispatch routing |
| Platform Integration User | System | Platform-level integration |
| Replicant Integration User | System | AI/IVR call handling integration |
| Daniel Fisher, Anne Hassan, Kenneth White, etc. | Human | Contact center dispatchers — manual assignment |

**Observation:** At On-Platform Contractor facilities like 076DO, approximately 78% of assignments come from system users (primarily IT System User), with 22% from human dispatchers. Human dispatchers frequently reassign SAs that were auto-assigned to redistribute workload.

### 6.3 The "Hot Driver" Problem

When the automation assigns drivers based purely on proximity:

1. Driver A completes a job — GPS updates to that location
2. New SA arrives nearby
3. System queries: "Who is closest with matching skills?"
4. Driver A is still closest (just finished nearby)
5. Driver A gets assigned again
6. Other qualified drivers with no current assignment are skipped
7. Dispatcher must manually intervene to redistribute

**Real-world example (April 8, 2026, 076DO):**
Thomas Shultz received 4 consecutive auto-assignments between 8:46am and 10:07am (81 minutes), while drivers like Jacob Geisler received only 1 auto-assignment in the same period. Human dispatcher Daniel Fisher had to manually assign calls to other drivers to balance the load.

---

## 7. Scheduling Policies

### 7.1 Policy Inventory

| Policy Name | Service Objectives | Purpose |
|---|---|---|
| Closest Driver | Minimize Travel (weight 100) | Find nearest available driver |
| Emergency | ASAP (700) + Minimize Travel (300) | Urgent calls — speed over proximity |
| Highest Priority | ASAP (9000) + Minimize Travel (1000) | Top priority calls |
| Copy of Highest Priority | ASAP (1500) + Minimize Travel (10) | Variant of highest priority |
| DF TEST - Closest Driver | Minimize Travel (100) | Test policy |

### 7.2 Work Rules on "Closest Driver" Policy

| Work Rule | Type | Purpose |
|---|---|---|
| Match Skills | Filter | Only candidates with required skills |
| Working Territories | Filter | Only candidates assigned to the territory |
| Active Resources | Filter | Only active service resources |
| Resource Availability | Filter | Only available (not busy) resources |
| On Schedule Platform Contractors Resource Availability | Filter | On-schedule contractor availability |
| Off Schedule Platform Contractors Resource Availability | Filter | Off-schedule contractor availability |
| Off Platform Contractors Resource Availability | Filter | Off-platform contractor availability |
| Maximum Travel From Home | Filter | Travel time limits (10/20/30/40/50/60 min variants) |
| Earliest Start Permitted | Filter | Respect earliest start time |
| Due Date | Filter | Respect due date |
| Scheduled Start / End | Filter | Respect schedule boundaries |
| Required Service Resource | Filter | Honor required resource preferences |
| Excluded Resources | Filter | Honor resource exclusions |
| PTA Window Work Rule | Filter | Respect Promised Time of Arrival window |
| Assign Passenger Transport Tows by Truck Passenger Space | Filter | Match truck passenger capacity |

### 7.3 Available Service Objectives (Not Currently Used)

| Objective | What It Does | Currently Used? |
|---|---|---|
| ASAP | Schedule at earliest time | Yes (Emergency, Highest Priority) |
| Minimize Travel | Nearest driver | Yes (all policies) |
| **Minimize Overtime** | Prefer drivers within standard hours | **NO** |
| **Resource Priority** | Use driver priority ranking | **NO** |
| **Preferred Resource** | Prefer specific driver | **NO** |
| **Skill Level** | Prefer higher-skilled driver | **NO** |

**Critical Gap:** No policy includes Minimize Overtime or Resource Priority, which are the standard FSL mechanisms for workload distribution.

---

## 8. Identified Challenges and Issues

### 8.1 No Workload Balancing

**Severity: HIGH**

All scheduling policies optimize exclusively for proximity (Minimize Travel) and/or speed (ASAP). There is no mechanism to distribute work evenly across available drivers. This creates the "hot driver" pattern where the nearest driver gets stacked with assignments while other qualified drivers sit idle.

**Impact:** Human dispatchers must manually intervene to redistribute 20-30% of auto-assigned SAs.

### 8.2 Missing Driver Availability Configuration

**Severity: HIGH**

On-Platform Contractor drivers lack:
- **Shifts:** Zero shift records exist for any contractor driver
- **Operating Hours on STM:** All null
- **Efficiency ratings:** All null
- **Priority rankings:** All null
- **Capacity records:** Not configured

Without these, the system treats all 50 drivers at a facility as "always available" and cannot make intelligent scheduling decisions about who is actually working.

### 8.3 ServiceTerritoryMember Homebase Coordinates

**Severity: MEDIUM (Recently Addressed)**

Originally (December 2024 setup), all STM records had null Latitude/Longitude. This was corrected on April 8, 2026, when coordinates were added to new STM records. However:
- Street addresses remain null
- Coordinates appear to be GPS-derived rather than verified home addresses

### 8.4 Drivers Not Logged Into Trucks

**Severity: MEDIUM**

At any facility, a significant portion of drivers only have base skills (EV + Driver Tire), indicating they are not logged into any truck. At 076DO on April 8, 2026:
- 13 of 50 drivers were on tow trucks (26%)
- 7 of 50 were on service trucks (14%)
- 30 of 50 had base skills only (60%)

These 30 drivers are invisible to the dispatch system for actual ERS calls. It's unclear whether these are off-duty drivers who remain on the territory roster, or active drivers who haven't completed their truck login.

### 8.5 FSL Scheduler Not Used for All Facilities

**Severity: HIGH**

The `FSL__Scheduling_Policy_Used__c` field is null on all SAs at On-Platform Contractor facilities. Auto-assignment is handled by a custom Flow/Apex (IT System User) rather than the FSL Scheduler. This custom automation:
- Does not leverage scheduling policy objectives
- Has no workload balancing logic
- Cannot benefit from adding new service objectives to policies

### 8.6 Towbook ActualStartTime Reliability

**Severity: MEDIUM**

For Towbook-dispatched (Off-Platform) SAs, the `ActualStartTime` field is unreliable — it gets bulk-updated at midnight rather than reflecting actual arrival time. The true arrival time must be sourced from `ServiceAppointmentHistory` where the status changed to "On Location."

### 8.7 Duplicate Service Resources

**Severity: LOW**

Some drivers have two ServiceResource records — one old (inactive, from December 2024) and one new (active, from March-April 2026). This occurred during the facility migration/reconfiguration. The old records retain historical assignment data.

---

## 9. Recommendations

### 9.1 Immediate — Add Workload Balancing to Policies

1. Add **"Resource Priority"** service objective to the "Closest Driver" policy with moderate weight (e.g., 30-50 alongside Minimize Travel at 100)
2. Set `FSL__Priority__c` equally on all drivers to enable round-robin behavior when travel times are similar
3. This requires no shift/hours setup and provides immediate improvement

### 9.2 Short-term — Driver Availability Configuration

1. Define **shifts or operating hours** for each driver at On-Platform Contractor facilities
2. This enables the "Minimize Overtime" service objective
3. Allows the system to distinguish between on-duty and off-duty drivers

### 9.3 Medium-term — Migrate to FSL Scheduler

1. Move On-Platform Contractor facilities from custom automation (IT System User) to the FSL Scheduler
2. This enables all scheduling policy objectives and work rules
3. Provides a standard, auditable dispatch decision trail via `FSL__Scheduling_Policy_Used__c`

### 9.4 Long-term — Full Configuration

1. Populate `FSL__Efficiency__c` on drivers based on performance data
2. Configure `ServiceResourceCapacity` for shift-based capacity management
3. Add verified home addresses to STM records
4. Implement "Minimize Overtime" + "Resource Priority" objectives together
5. Consider the FSL Enhanced Scheduling and Optimization (ESO) engine for more sophisticated scheduling

---

## 10. Reference: Salesforce Documentation

- Scheduling Policies Overview: https://trailhead.salesforce.com/content/learn/modules/field-service-lightning-scheduling-basics/examine-scheduling-policies
- Customize Scheduling Policies: https://trailhead.salesforce.com/content/learn/modules/field-service-lightning-scheduling-basics/customize-a-scheduling-policy
- Understanding Optimization: https://trailhead.salesforce.com/content/learn/modules/field-service-lightning-optimization/explore-optimization
- Service Objectives: https://help.salesforce.com/s/articleView?id=service.pfs_optimization_theory_service_objectives.htm
- Scheduling Policies: https://help.salesforce.com/s/articleView?id=service.pfs_scheduling.htm
- Policy Tuning: https://help.salesforce.com/s/articleView?id=service.pfs_scheduling_policy_tuning.htm
- Optimization: https://help.salesforce.com/s/articleView?id=service.pfs_optimization.htm
- Priority Optimization: https://help.salesforce.com/s/articleView?id=service.pfs_scheduling_priority_optimization.htm

---

*Report generated from live Salesforce org data on April 8, 2026.*
