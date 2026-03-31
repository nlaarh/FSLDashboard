---
name: SF Org Automation — Complete Apex + Flow + Trigger Technical Reference
description: How every key field is used by Apex triggers, Flows, and Mulesoft. 27 triggers, 377 flows, SA lifecycle state machine, tow dual-SA pattern, dispatch routing, cost rollups. Verified Mar 15, 2026.
type: project
---

# Salesforce Org Automation — Complete Technical Reference (Mar 15, 2026)

## Architecture Overview

The org runs on a dual-layer automation framework:
- **27 Apex Triggers** — using `rflib_TriggerManager` framework for dispatch to handler classes
- **377 Flows** — record-triggered, scheduled, screen, and auto-launched
- **Mulesoft Integration** — handles ~78% of dispatch (ERS_SA_AutoSchedule)
- **FSL Scheduling Engine** — NOT used for dispatching (0 SAs graded, 0 optimized)

---

## TRIGGERS (27 total)

### Core ERS Triggers (dispatch & fulfillment)

| Trigger | Object | Events | Handler |
|---------|--------|--------|---------|
| ERS_ServiceAppointmentTrigger | ServiceAppointment | BI, AI, BU, AU, BD, AUnd | rflib_TriggerManager → ERS_ServiceAppointmentTriggerHandler |
| ERS_WorkOrderTrigger | WorkOrder | BI, AI, BU, AU, BD, AUnd | rflib_TriggerManager → ERS_WorkOrderTriggerHandler |
| ERS_AssignedResourceTrigger | AssignedResource | BI, AI, BU, AU, BD, AUnd, AD | rflib_TriggerManager → ERS_AssignedResourceTriggerHandler |
| ERS_ServiceResourceTrigger | ServiceResource | BI, AI, BU, AU, BD, AUnd, AD | rflib_TriggerManager → ERS_ServiceResourceTriggerHandler |
| ERS_WorkOrderLineItemTrigger | WorkOrderLineItem | BI, BU, AI, AU, BD, AD | Custom Apex (NOT rflib) |

### Financial Triggers

| Trigger | Object | Handler | Purpose |
|---------|--------|---------|---------|
| ERS_WorkOrderCostTrigger | ERS_Work_Order_Cost__c | Custom Apex | Cost/tax rollup to parent WO |
| ERS_FacilityContractCalculatorTrigger | ERS_Facility_Contract_Calculator__c | rflib | Facility contract calculations |
| ERS_PaymentRunTrigger | ERS_Payment_Run__c | rflib | Payment processing |
| ERS_QuoteTrigger | Quote | rflib | Quote management |
| ERS_ReciprocalCostTrigger | ERS_Reciprocal_Cost__c | rflib | Reciprocal cost tracking |
| ERS_ReciprocalTrigger | ERS_Reciprocal__c | rflib | Reciprocal record management |
| ERS_ReciprocalErrorTrigger | ERS_Reciprocal_Error__c | rflib | Reciprocal error handling |

### CRM Triggers

| Trigger | Object | Handler | Purpose |
|---------|--------|---------|---------|
| TS_CaseTrigger | Case | TS_CaseTriggerHandler | Status tracking, contact sync |
| TS_LeadTrigger | Lead | TS_LeadTriggerHandler | Status tracking, SLA |
| TS_TaskTrigger | Task | TS_TaskTriggerHandler | Lead engagement (LastCallDate) |
| TS_AccountTrigger | Account | TS_AccountTriggerHandler | Address consistency |
| TS_AssetTrigger | Asset | TS_AssetTriggerHandler | Truck↔Driver linking |
| UserTrigger | User | UserTriggerHelper | Cash drawer values |

### Other (rflib framework)
TS_OpportunityTrigger, TS_PolicyTrigger, TS_OppContactRoleTrigger, TS_CreditCardTrigger, LeadTrigger, ContentDocumentTrigger, ContentVersionTrigger, ContentDocumentLinkTrigger

---

## APEX FIELD USAGE — HOW EACH FIELD IS READ/WRITTEN

### ServiceAppointment Fields

**ERS_Dispatch_Method__c** — NEVER written by Apex. Set by Mulesoft.
- READ in: ERS_AssignedResourceTriggerHandler (line 68, 95, 97), ERS_ServiceAppointmentTriggerHandler (line 147, 160, 202), ERS_SADripFeedBatch (line 26), ERS_workOrderGeoQueuable (line 144, 199)
- Logic: Controls routing — 'Towbook' vs 'Field Services'. Determines messaging, scheduling, pinning, territory reassignment behavior.

**ERS_Auto_Assign__c** — Custom field (NOT FSL native).
- WRITE in: ERS_workOrderGeoQueuable (line 157, 209), ERS_ServiceAppointmentTriggerHandler (line 417, 517)
- READ in: ERS_ServiceAppointmentTriggerHandler (line 199)
- Logic: Set at SA creation based on `AAA_ERS_Services__mdt.ERS_Auto_Schedule__c AND ServiceTerritory.ERS_Auto_Schedule__c`. When true, also sets FSL__Auto_Schedule__c = true.

**ERS_PTA__c** — Promised Time Allowance (minutes).
- WRITE in: ERS_ServiceAppointmentTriggerHandler (line 420, 520, 620) via `setERSptaforSA()` method
- READ in: ERS_ServiceAppointmentTriggerHandler (line 633), ERS_Towbook_AppointmentController (line 73, 251)
- Logic: Looked up from `ERS_Service_Appointment_PTA__c` custom metadata (by territory + worktype). DueDate = EarliestStartTime.addMinutes(ERS_PTA__c).

**Status** — SA lifecycle state machine.
- READ/WRITE extensively in ERS_ServiceAppointmentTriggerHandler (30+ references)
- States: None → Spotted → Assigned → Dispatched → Accepted → En Route → On Location → Completed | Cancel-EnRoute | Cancel-Not-EnRoute | Unable to Complete | No-Show
- Each transition triggers: messaging, pinning, HAAS alerts, territory reassignment, driver notifications

**ERS_Tow_Pick_Up_Drop_off__c** — Links Drop-Off SA to Pick-Up SA.
- READ in: ERS_AssignedResourceTriggerHandler (line 67, 88, 90-91, 110), ERS_workOrderGeoQueuable (line 89, 117, 147, 185, 204)
- Logic: Drop-Off gets same driver as Pick-Up. Auto-pinning cascades. Cannot reassign independently.

**Latitude / Longitude** — SA geolocation.
- WRITE in: ERS_workOrderGeoQueuable (line 123-124, 191-192) — set from WOLI when address changes
- READ in: ERS_workOrderGeoQueuable (line 108) — passed to `ERS_Utilities.getSpottedTerritory()` for territory assignment

**ServiceTerritoryId** — Links SA to facility.
- WRITE in: ERS_workOrderGeoQueuable (line 109, 116, 129, 145, 196, 289, 296-297, 302-303, 308, 317)
- READ in: ERS_AssignedResourceTriggerHandler (line 105)
- Logic: Assigned by geolocation spotting. Reassigned when address changes or driver from different facility.

**SchedStartTime / SchedEndTime** — Scheduled appointment window.
- WRITE in: ERS_workOrderGeoQueuable (line 145-146, 200-201) — set to NOW + duration for Towbook reassignment
- READ in: ERS_SADripFeedBatch (line 23, 27, 42), ERS_ServiceResourceTriggerHandler (line 67)

**ActualStartTime / ActualEndTime** — Driver arrival/completion.
- READ only in: ERS_QualtricsWorkOrderService (line 106-107) — for survey correlation
- Updated by FSL mobile app, not Apex. Towbook ActualStartTime is UNRELIABLE (midnight bulk-update).

**DueDate** — Customer promise deadline.
- WRITE in: ERS_ServiceAppointmentTriggerHandler (line 633) — `EarliestStartTime.addMinutes(ERS_PTA__c)`

**FSL__Appointment_Grade__c / FSL__Scheduling_Policy_Used__c** — NOT used anywhere in Apex. FSL scheduler never runs.

### ServiceResource Fields

**LastKnownLatitude / LastKnownLongitude / LastKnownLocationDate** — Live GPS from FSL app.
- READ in: ERS_ServiceResourceTriggerHandler (line 60, 72-73) — AFTER_UPDATE detects location changes for HAAS alerts
- READ in: ERS_ServiceAppointmentTriggerHandler (line 245, 286-287) — passed to inbound messaging
- NOT written by Apex — updated by FSL mobile app automatically

**ERS_Driver_Type__c** — Fleet Driver / On-Platform Contractor / Off-Platform Contractor.
- READ in: ERS_ServiceAppointmentTriggerHandler (line 281) — checks 'Off-Platform Contractor Driver' for messaging routing
- NOT written by Apex — set manually/by admin

**ResourceType / IsActive** — Standard filters.
- READ throughout: `ResourceType='T'` (Technician) and `IsActive=true` in all driver queries

### AssignedResource Fields

**ServiceResourceId / ServiceAppointmentId** — Junction object: driver ↔ appointment.
- READ/WRITE in: ERS_AssignedResourceTriggerHandler (line 44-45, 70-80, 102-105)
- Logic: When AR created → updates SA.ERS_Assigned_Resource__c, SA.ServiceTerritoryId, applies auto-pinning. When AR deleted → unassigns SA.

### ServiceTerritoryMember Fields
- READ in: ERS_workOrderGeoQueuable (line 302-308) — maps Territory → Resource for off-platform assignments
- Lat/Long rarely populated (90.6% blank). FSL app updates coordinates for drivers who have it.

### ResourceAbsence Fields
- NOT directly used in Apex code. Managed entirely by Flows.

### WorkOrder Fields
- Lat/Long: WRITE by ERS_workOrderGeoQueuable via Google Geocoding API when address changes
- ServiceTerritoryId: WRITE by spotting logic
- Tow_Destination coordinates: WRITE by geocoding

### WorkOrderLineItem Fields
- WorkTypeId: READ extensively — determines service type
- Pricing/quantity: managed by ERS_WorkOrderPricingEngine, ERS_SalesTaxEngine, ERS_WorkOrderCostHandler in trigger

---

## FLOW AUTOMATION — MASTER → SUBFLOW ARCHITECTURE

### Master Flow Chain (SA Lifecycle)

**AAA Master Service Appointment After Insert** (execution order 640):
1. `AAA_ERS_Update_Spotting_Number_on_SA` → facility reference
2. `AAA_ERS_Update_Work_Order_Manager` → sync WO fields
3. `AAA_ERS_Send_SMS_on_Insert` → SMS to member (if SMS_Opt_In, not Drop-Off)

**AAA Master Service Appointment After Update** (15 subflows, sequential):
1. `AAA_ERS_Send_Notification_To_Driver_when_SA_On_Location_Tow_Drop_off`
2. `AAA_ERS_Share_Asset_Data_with_Driver`
3. `AAA_ERS_Subflow_Create_or_Update_Resource_Absence` → blocks driver availability
4. `Update_WOLI_WO_SA_Notify_Driver_when_SA_is_Cancelled` → cascade cancel
5. `AAA_ERS_Update_WOLI_WO_when_SA_status_changes` → SA→WOLI→WO status sync
6. `AAA_ERS_Create_WO_WOLI_SA_on_Unable_to_Complete` → auto-retry call creation
7. `AAA_ERS_Dispatch_Tow_Work_Together` → tow pick-up/drop-off coordination
8. `AAA_ERS_Send_Notification_To_Driver_when_SA_Dispatched`
9. `AAA_ERS_Update_Work_Order_Manager`
10. `AAA_ERS_Send_Immediate_SMS`
11. `AAA_ERS_Cancel_Tow_Drop_Off_SA` → cascade tow cancellation
12. `ERS_Give_Customer_Access_to_Facility`
13. `AAA_ERS_Service_Appointment_Location_Work_Type_Updated`
14. `AAA_ERS_Update_TowDrop_off_Territory`
15. `AAA_ERS_Delete_Old_ServiceTerritory_Share_Record`

### Master Flow Chain (WO Lifecycle)

**Master Work Order Flow — After Insert** (RecordType = ERS_Work_Order):
1. Generate Call Key (ERS_Call_Key__c)
2. CDX Authorization Check (if Type = 'Authorization')
3. Entitlement Consumption:
   - Standard: consume if Non_Count_Call = false AND Status ≠ New
   - Feedback: consume if Non_Count_Call = false
   - Back Office: consume if Status = Closed AND Non_Count_Call = false
   - Unable-To-Complete Dupes: consume if Status transitions from New
4. Dispatch Decision:
   - Non-Tow: Status = Submitted AND Tow_Call = false AND lat/long present
   - Tow: Status = Submitted AND Tow_Call = true AND lat/long AND tow destination lat/long present
   - Routes to `Subflow_Work_Order_ERS_Scenario_Manager` (Scenario_Type = "Dispatch")
5. Resolution & Clear (on Resolution_Code + Clear_Code populated)
6. Messaging user creation, Case sync, internal notifications

**Master Work Order Flow — After Update**: Same logic + delta detection for field changes.

---

## KEY AUTOMATION PATTERNS

### 1. Status Sync Cascade
```
SA status change → Flow updates WOLI status → Flow updates WO status
Completed → WOLI "Completed" → WO lifecycle check
Canceled → WOLI "Cannot Complete" or "Canceled" → depends on tow pair
Unable to Complete → auto-create NEW WO/WOLI/SA (retry call)
```

### 2. Tow Dual-SA Coordination
- Tow calls create TWO SAs: Pick-Up + Drop-Off
- Linked via `FSL__Time_Dependency__c` (Dependency = "Immediately Follow", Same_Resource = true)
- Drop-Off auto-cancels if Pick-Up canceled
- Drop-Off WOLI only completes if Pick-Up SA completed
- Both dispatched to same driver via Time Dependency constraint

### 3. Dispatch Routing
```
WO created (by Mulesoft/Replicant/manual)
  → Apex trigger fires: geocode address, spot territory, set PTA, set Auto_Assign
  → If ERS_Auto_Assign__c = true: FSL__Auto_Schedule__c also set true
  → Mulesoft ERS_SA_AutoSchedule picks up (~78% of dispatches)
  → OR human dispatcher manually assigns via AssignedResource
```

### 4. Resource Absence Management (Flow-driven)
- SA activations → Flow creates ResourceAbsence (blocks driver availability)
- Time window: SA.EarliestStartTime → SA.DueDate
- FSL scheduler respects this for real-time availability

### 5. AR Restriction (Flow: AAA_ERS_Restrict_Assigned_Resource_Update)
- Cannot change driver (ServiceResourceId) if SA status in:
  Dispatched, Accepted, En Route, On Location, Completed, Unable to Complete
- Must unschedule SA first, then reassign

### 6. Cost Rollup Chain (Apex triggers)
```
WOLI change → ERS_WorkOrderPricingEngine + ERS_SalesTaxEngine
  → ERS_Work_Order_Cost__c records created/updated
  → ERS_WorkOrderCostTrigger → rollUpCostByType() + rollUpTaxes()
  → Parent WO financial fields updated
```
Uses Future methods for async processing (avoids stack depth issues on bulk).

### 7. Driver Login = Asset Assignment
```
Asset (ERS Truck) has ERS_Driver__c lookup to ServiceResource
  → TS_AssetTrigger AFTER UPDATE detects driver change
  → Flow: AAA_ERS_Update_Number_of_Seats_on_SR
  → Copies Asset.ERS_Number_of_Seats__c to ServiceResource.ERS_Number_of_Seats__c
```

### 8. Territory Spotting (Apex: ERS_workOrderGeoQueuable)
```
WO address provided → Google Geocoding API → Lat/Long
  → ERS_Utilities.getSpottedTerritory(lat, lng) → finds matching ServiceTerritory
  → SA.ServiceTerritoryId assigned
  → If address changes → re-spot → reassign territory
```

---

## FLOW INVENTORY BY DOMAIN (377 total)

### ERS Dispatch & SA Management (~60 flows)
- Master SA After Insert/Update (orchestrators)
- Tow coordination (dispatch together, cancel drop-off, update territory)
- Status change handlers (WOLI/WO rollup, retry creation)
- Resource absence management
- Driver notifications (dispatched, on-location, worktype change)
- SA location/worktype update handlers
- Territory sharing (create/delete share records)
- AR restriction validation

### SMS & Messaging (~15 flows)
- Send SMS on insert, on dispatch, on status change
- Create/update contact messaging users
- Open territory SA notifications to drivers

### Work Order Management (~40 flows)
- Master WO After Insert/Update (orchestrators)
- Scenario Manager (dispatch, resolution, clear)
- Entitlement consumption (standard, feedback, back office, dupes)
- CDX authorization processing
- Call key generation
- Tow facility manager
- Long tow calculation
- Internal notification manager (RAP codes R001/R002/R003)
- Towbook event publishing (platform events)

### Financial/Back Office (~30 flows)
- Payment run processing
- Facility contract calculations
- Invoice line items
- Reimbursement approval
- Reciprocal cost flows
- Tax rate management
- WO adjustment handling

### Authorization & Entitlements (~15 flows)
- Authorization manager (master)
- Call count tracking
- Membership status/eligibility
- Vehicle coverage
- Additional entitlements evaluation

### CRM (Case/Lead/Task/Account) (~50 flows)
- Master Case flows (before/after insert/update)
- Master Lead flows
- Lead-to-Case conversion
- Status tracking
- SLA management
- Account type derivation (from Asset, Insurance, Opportunity)
- Contact management

### Travel & Insurance (~20 flows)
- Travel support manager
- Cruise check-in notifications
- Traveler opportunity management

### Platform Events & Integration (~10 flows)
- ERS_WorkOrder_Platform_Event_Trigger (listener)
- Platform_Event_Work_Order_Scenario_Manager
- Share off-platform records to Towbook user
- SA re-trigger Towbook event

### Scheduled Flows (~5 flows)
- 30-day flag removal
- Flag manager
- RV services entitlement consumption

### Screen Flows (~20 flows)
- Inbound new guest appointment
- Outbound modify appointment
- Process outbound leads
- Edit SA location

### Administrative/Utility (~30 flows)
- Assign SR user to public group
- Create resource preference (excluded)
- Asset household ID sync
- Lead field sync
- Survey result relationship resolution

---

## MULESOFT INTEGRATION POINTS

Mulesoft does NOT write to Apex classes. It interacts via:
1. **Direct DML** — Creates WO/WOLI/SA/AR records, which fire triggers
2. **ERS_SA_AutoSchedule** — Custom auto-dispatch logic (bypasses FSL scheduler)
3. **ERS_Dispatch_Method__c** — Set to 'Field Services' or 'Towbook' on SA (read by Apex, never written by Apex)
4. **Platform Events** — WO scenario manager events consumed by Flows
5. **REST API** — Towbook appointment controller (`ERS_Towbook_AppointmentController`) for external garage updates

**What Mulesoft controls:**
- Which driver gets which call (~78% of dispatches)
- Whether dispatch goes to Towbook or Field Services
- PTA override for Towbook calls
- SA creation timing and sequencing

**What Mulesoft does NOT control:**
- Status transitions (handled by FSL app + triggers)
- Cost calculations (Apex triggers)
- Territory spotting (Apex queueable + Google Maps)
- SMS/messaging (Flows)
- Resource absence blocking (Flows)

---

## CRITICAL FIELD DEPENDENCY MAP

```
WO.Latitude/Longitude ──→ SA.Latitude/Longitude ──→ ERS_Utilities.getSpottedTerritory()
                                                        ↓
                                                  SA.ServiceTerritoryId
                                                        ↓
                    ┌───────────────────────────────────────┐
                    │ Territory settings determine:          │
                    │ • ERS_Auto_Assign__c (auto-dispatch)   │
                    │ • ERS_PTA__c (promised time)           │
                    │ • Which drivers are eligible (STM)     │
                    └───────────────────────────────────────┘

Asset.ERS_Driver__c ──→ ServiceResource (driver login)
                            ↓
                    SR.ERS_Number_of_Seats__c (from Asset)
                    SR.LastKnownLatitude/Longitude (from FSL app)
                            ↓
                    STM.Latitude/Longitude (synced by FSL app)

AssignedResource ──→ Links SR to SA
                        ↓
                  SA.ERS_Assigned_Resource__c updated
                  SA.ServiceTerritoryId updated (from driver's facility)
                  Tow Drop-Off auto-pinned to same driver

SA.Status transitions ──→ WOLI.Status ──→ WO.Status
                              ↓
                    ResourceAbsence created/updated (Flow)
                    SMS sent to member (Flow)
                    Driver notified (Flow)
                    Cost calculations triggered (if Completed)
```
