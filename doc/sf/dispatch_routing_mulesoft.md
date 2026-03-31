# Dispatch Routing & Mulesoft Integration (Verified Mar 15, 2026)

## Architecture: Who Dispatches What

```
                    Call Comes In
                         │
                    ┌────▼────┐
                    │ Replicant│  (AI/IVR creates WO)
                    │ or Human │
                    └────┬────┘
                         │
                    ┌────▼────────────────┐
                    │ WO Created in SF     │
                    │ → Apex Trigger fires  │
                    │ → Geocode address     │
                    │ → Spot territory      │
                    │ → Set PTA             │
                    │ → Set Auto_Assign     │
                    └────┬────────────────┘
                         │
              ┌──────────┼──────────┐
              │                     │
        ┌─────▼─────┐        ┌─────▼─────┐
        │ Mulesoft   │        │ Human     │
        │ Auto-Sched │        │ Dispatcher│
        │ (~78%)     │        │ (~22%)    │
        └─────┬─────┘        └─────┬─────┘
              │                     │
     ┌────────┼────────┐           │
     │                 │           │
┌────▼────┐     ┌──────▼──┐  ┌────▼────┐
│ Field   │     │ Towbook  │  │ Manual  │
│ Services│     │ Dispatch │  │ Assign  │
│ (26%)   │     │ (74%)    │  │         │
└────┬────┘     └────┬─────┘  └────┬────┘
     │               │             │
     │               │             │
  Driver          Garage         Driver
  assigned        assigns        assigned
  by Mulesoft     own driver     by human
```

## Mulesoft's Dispatch Algorithm (ERS_SA_AutoSchedule)

Mulesoft does NOT use FSL's scheduling engine. It runs its own logic:

### Step 1: Territory Selection (Priority Matrix)
```
1. Read SA.ServiceTerritoryId (spotted garage)
2. Query ERS_Territory_Priority_Matrix__c WHERE Spotted_Territory = {garage}
3. Filter by matching work type
4. Sort by ERS_Priority__c ASC
5. Offer to P2 garages first
```

### Step 2: Fleet vs Towbook Decision
```
IF territory.ERS_Auto_Schedule__c = true
  AND AAA_ERS_Services__mdt.ERS_Auto_Schedule__c = true
THEN:
  SA.ERS_Auto_Assign__c = true
  SA.FSL__Auto_Schedule__c = true
  → Mulesoft picks the driver (Field Services)
ELSE:
  → Towbook dispatch (garage picks own driver)
```

### Step 3: Field Services Driver Selection
For Fleet garages, Mulesoft selects the driver. The algorithm is NOT the FSL scheduler.
**Evidence**: 0 SAs graded, 0 optimized, only 1 SA has scheduling policy recorded.

**What we know about Mulesoft's driver logic:**
- Picks closest driver only ~26% of the time (verified from dispatch data)
- Likely uses a capacity/availability check + some proximity factor
- Exact algorithm is in Mulesoft, NOT visible from Salesforce side
- Result: driver assigned via AssignedResource record creation

### Step 4: Towbook Garage Notification
For Towbook garages:
```
1. SA created with Status = Spotted/Assigned
2. Platform event or API call to Towbook system
3. Garage sees call in their Towbook interface
4. Garage assigns their own driver
5. Towbook updates SA via ERS_Towbook_AppointmentController (REST API)
6. Off-platform driver info written to:
   - SA.Off_Platform_Driver__r (ServiceResource lookup)
   - SA.Off_Platform_Truck_Id__c (truck identifier)
   - SA.ERS_OffPlatformDriverLocation__c (GPS)
```

## Cascade Mechanics

### When Cascade Happens
1. Garage **declines** the call → `ERS_Facility_Decline_Reason__c` set
2. Mulesoft reads next priority level from Matrix
3. SA.ServiceTerritoryId updated to next garage
4. `ServiceAppointmentHistory` records the territory change
5. Process repeats until accepted or 000-SPOT fallback reached

### Decline Reasons (from SA data)
| Reason | Count | Meaning |
|--------|-------|---------|
| Towbook Decline | 24,000+ | Garage declined via Towbook |
| Long Tow | 486 | Tow distance too far |
| Unable ETA | 185 | Can't meet the PTA |

### Rejection Reasons (driver-level)
| Reason | Count | Meaning |
|--------|-------|---------|
| End of Shift | 3,293 | Driver going off-duty |
| Meal/Break | 2,431 | Driver on break |
| Out of Area | 1,478 | Driver too far |
| Truck Not Capable | 1,051 | Wrong truck type |

## Platform Events & Integration Points

### Towbook Communication
The org uses **Change Data Capture (CDC)** events, NOT custom Platform Events:
- `ServiceAppointment__ChangeEvent` — triggers when SA fields change
- Work Order scenario manager flows publish/consume these events
- `ERS_Towbook_AppointmentController` (Apex REST) — endpoint for Towbook to update SAs

### Key Flows for Integration
- `Subflow_Work_Order_ERS_Scenario_Manager` (Scenario_Type = "Dispatch") — orchestrates dispatch routing
- `AAA_ERS_Share_Off_Platform_Record_to_Towbook_User` — shares SA records
- `AAA_ERS_SA_Retrigger_Towbook_Event` — re-sends Towbook notifications

### Mulesoft Touchpoints (from Apex code analysis)
Mulesoft interacts via:
1. **Direct DML** — creates WO/WOLI/SA/AR records (triggers fire)
2. **ERS_SA_AutoSchedule** — custom auto-dispatch logic
3. **ERS_Dispatch_Method__c** — Formula field on SA, derives 'Field Services' or 'Towbook' from facility account
4. **REST API** — ERS_Towbook_AppointmentController for external updates
5. **Platform Events** — CDC events consumed by Flows

## Data Elements Used by Dispatch

### Fields SET by Dispatch System
| Field | Set By | Value |
|-------|--------|-------|
| SA.ERS_Dispatch_Method__c | Formula (auto) | Derives 'Field Services' or 'Towbook' from facility account — not set directly |
| SA.ERS_Auto_Assign__c | Apex trigger | true/false (from territory + metadata settings) |
| SA.FSL__Auto_Schedule__c | Apex trigger | mirrors ERS_Auto_Assign__c |
| SA.ERS_PTA__c | Apex trigger | minutes from PTA settings table |
| SA.DueDate | Apex trigger | EarliestStartTime + PTA minutes |
| SA.ServiceTerritoryId | Apex (spotting) | from geocoded address |
| SA.SchedStartTime/End | Apex (Towbook reassign) | set to NOW + duration |
| AR.ServiceResourceId | Mulesoft or human | the assigned driver |

### Fields READ by Dispatch System
| Field | Read By | Purpose |
|-------|---------|---------|
| SA.Latitude/Longitude | Spotting logic | determine territory |
| SA.WorkTypeId | Matrix lookup | worktype-aware cascade |
| ServiceTerritory.ERS_Auto_Schedule__c | Auto-assign check | fleet vs Towbook |
| ERS_Territory_Priority_Matrix__c | Cascade routing | which garage next |
| ERS_Service_Appointment_PTA__c | PTA setting | promise time |
| Asset.ERS_Driver__c | Driver availability | who's logged in |

## FSLAPP Implications

### What We Can Build
1. **Cascade Visualizer**: Show the full priority matrix for any garage — who gets offered calls first
2. **Cascade Depth Analysis**: How many cascade steps before a call gets accepted (from SA history)
3. **Decline Pattern Analysis**: Which garages decline most, at what times, for what work types
4. **Response Time by Cascade Depth**: P2 acceptance should be faster than P5
5. **Matrix Coverage Audit**: Find garages with incomplete cascades (missing worktypes)
6. **Real-time Cascade Tracker**: For live calls, show where in the cascade the call currently is

### What We Cannot See
- Mulesoft's internal driver selection algorithm (black box from SF side)
- Real-time Towbook garage capacity/availability
- Why Mulesoft picks closest driver only 26% of the time
