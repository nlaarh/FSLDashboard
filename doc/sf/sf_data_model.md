# AAA WCNY Salesforce Org — Complete Data Model Reference

**Org**: aaawcny.my.salesforce.com
**API User**: apiintegration@nyaaa.com (Mulesoft profile)
**API Version**: v59.0
**Explored**: 2026-02-27 | **FLS Updated**: 2026-03-02

## API User Field-Level Security (FLS) — UPDATED March 2026
Admin granted FLS access on most objects. Current state:
- **ServiceAppointment**: 191 fields, **126 custom fields** visible (ERS__/FSL__ UNLOCKED)
- **WorkOrder**: 175+ fields, **175 custom fields** visible (all ERS__ fields UNLOCKED)
- **Survey_Result__c**: 37 fields, **26 custom fields** visible (satisfaction scores, NPS, comments)
- **Qualtrics_Data__c**: 98 fields, **89 custom fields** visible (full call detail)
- **ServiceResource**: 16 custom fields visible (UNLOCKED Mar 2) — includes ERS_Driver_Type__c, ERS_Tech_ID__c, FSL__Efficiency__c, FSL__Travel_Speed__c, Schedule_Type__c, ERS_Number_of_Seats__c
- **Account**: 288 fields, **199 custom fields** ALL visible
- **Contact**: 121 fields, **73 custom fields** ALL visible
- **Asset**: 94 fields, **33 custom fields** ALL visible

---

## TABLE OF CONTENTS
1. [Roadside / ERS Domain](#1-roadside--ers-domain)
2. [Membership Domain](#2-membership-domain)
3. [Travel Domain](#3-travel-domain)
4. [Insurance / Financial Services Domain](#4-insurance--financial-services-domain)
5. [Vehicles Domain](#5-vehicles-domain)
6. [Support / Cases Domain](#6-support--cases-domain)
7. [Billing / Payments Domain](#7-billing--payments-domain)
8. [Surveys / Feedback Domain](#8-surveys--feedback-domain)
9. [Scheduling Infrastructure](#9-scheduling-infrastructure)
10. [Integration / Admin Objects](#10-integration--admin-objects)
11. [Account Record Types](#11-account-record-types)
12. [Relationship Map](#12-relationship-map)

---

## 1. ROADSIDE / ERS DOMAIN

### ServiceAppointment (SA) — The Core Roadside Record
Each roadside call creates SAs. Tow calls create 2 SAs (Tow Pick-Up + Tow Drop-Off).

**Accessible Fields:**
| Field | Type | Notes |
|-------|------|-------|
| Id | id | Primary key |
| AppointmentNumber | string | e.g. "SA-680182" |
| Status | picklist | See status table below |
| StatusCategory | picklist | Mapped category |
| CreatedDate | datetime | When call came in (UTC) |
| SchedStartTime / SchedEndTime | datetime | Scheduled window |
| ActualStartTime / ActualEndTime | datetime | When driver arrived/finished |
| EarliestStartTime | datetime | Earliest allowed start |
| DueDate | datetime | Latest allowed end |
| ArrivalWindowStartTime/EndTime | datetime | Customer-facing window |
| Street, City, State, PostalCode | string | Service location |
| Latitude, Longitude | double | Service location coords |
| Duration, DurationType | double/picklist | Estimated duration |
| WorkTypeId | reference → WorkType | Service type (Tow, Battery, etc.) |
| ServiceTerritoryId | reference → ServiceTerritory | Territory |
| ParentRecordId | reference | Links to WorkOrderLineItem (76%), Account (24%), or WorkOrder |
| ParentRecordType | string | "WorkOrderLineItem", "Account", "Lead", "WorkOrder" |
| AccountId | reference → Account | Member account (662K+ populated) |
| ContactId | reference → Contact | Only 157 populated |
| Subject | string | e.g. "Smith - ERS SA - 2026-02-09 - Tow Pick-Up" (500K populated) |
| Comments | textarea | Only 16 populated |
| AdditionalInformation | textarea | Only 1 populated |
| Description | textarea | Can't be filtered in WHERE clause |

**BLOCKED custom fields** (need admin FLS grant):
- All ERS__ fields (e.g., ERS_SA_GarageName__c, ERS_SA_DriverName__c, etc.)
- All FSL__ fields (e.g., FSL__Scheduling_Policy_Used__c, etc.)

**SA Status → StatusCategory Mapping:**
| Status | Category | Count |
|--------|----------|-------|
| Completed | Completed | 543,940 |
| Cancel Call - Service Not En Route | Canceled | 69,730 |
| Unable to Complete | CannotComplete | 35,928 |
| Cancel Call - Service En Route | CannotComplete | 7,128 |
| No-Show | Canceled | 5,755 |
| Cleared | CannotComplete | ~3K |
| Checked In | InProgress | ~2K |
| On Location | InProgress | active |
| En Route | InProgress | active |
| Dispatched | Dispatched | active |
| Accepted | Dispatched | active |
| Assigned | Scheduled | active |
| Scheduled | Scheduled | active |
| None | None | old records |

### ServiceAppointmentHistory — Status Change Tracking
Tracks all field changes on SA. Very useful for timeline analysis.
| Field | Type |
|-------|------|
| ServiceAppointmentId | reference → SA |
| Field | string | Which field changed (e.g., "Status") |
| OldValue / NewValue | string | Previous/new values |
| CreatedDate | datetime | When change occurred |

### AssignedResource (AR) — Links SA to Driver
| Field | Type | Notes |
|-------|------|-------|
| Id | id | |
| ServiceAppointmentId | reference → SA | Which job |
| ServiceResourceId | reference → SR | Which driver/garage |
| CreatedDate | datetime | When dispatched |
| CreatedById | reference → User | Who dispatched |
| IsRequiredResource | boolean | Always false in this org |
| EstimatedTravelTime | double | Minutes (in describe, but query fails) |
| ActualTravelTime | double | Minutes (in describe, but query fails) |
| ServiceCrewId | reference → ServiceCrew | Not used |
| Role | picklist | Not used |
| EventId | reference → Event | Calendar event |

### ServiceResource (SR) — Drivers & Garages
| Field | Type | Notes |
|-------|------|-------|
| Id | id | |
| Name | string | "John Smith" or "Towbook-053" |
| IsActive | boolean | 513 active T, 161 active A |
| ResourceType | picklist | "T" (Technician) or "A" (Agent) |
| RelatedRecordId | reference → User | SF User for this resource |
| AccountId | reference → Account | For Towbook resources: maps to garage Account |
| Description | textarea | Sometimes has schedule notes |
| LastKnownLatitude/Longitude | double | GPS position |
| LastKnownLocationDate | datetime | When GPS last updated |
| LocationId | reference → Location | 0/705 populated |
| IsCapacityBased | boolean | |
| IsOptimizationCapable | boolean | |
| ServiceCrewId | reference → ServiceCrew | Not used |
| IsPrimary | boolean | |

**Resource counts:** 513 active Technicians, 161 active Agents, 505+52 inactive

**Towbook mapping:** SR.Name = "Towbook-XXX" → SR.Account.Name = "053 - MICHAEL BELLRENG"

### WorkOrder (WO) — Parent of Service Appointments
| Field | Type | Notes |
|-------|------|-------|
| WorkOrderNumber | string | e.g. "04651607" |
| Status, StatusCategory | picklist | |
| Subject | string | e.g. "Smith - ERS WO - 2026-02-27" |
| CreatedDate, StartDate, EndDate | datetime | |
| Street, City, State, PostalCode | string | |
| Latitude, Longitude | double | |
| AccountId → Account | reference | Member account |
| ContactId → Contact | reference | |
| CaseId → Case | reference | Support case |
| ServiceTerritoryId → ServiceTerritory | reference | |
| WorkTypeId → WorkType | reference | |
| Duration, DurationType, DurationInMinutes | | |
| **Moved_to_D3__c** | boolean | Custom: moved to D3 system |
| **Current_Wait__c** | double | Custom: current wait time |

### WorkOrderLineItem (WOLI) — SA Parent Link
76% of SAs have ParentRecordType = "WorkOrderLineItem"
| Field | Type |
|-------|------|
| WorkOrderId | reference → WorkOrder |
| Product2Id | reference → Product2 |
| WorkTypeId | reference → WorkType |
| ServiceTerritoryId | reference → ServiceTerritory |

### WorkType — Service Type Definitions
| Name | Used For |
|------|----------|
| Tow Pick-Up | Tow service (pick up vehicle) |
| Tow Drop-Off | Tow service (drop off vehicle) |
| Battery | Battery test/replace |
| Tire | Flat tire service |
| Lockout | Locked keys |
| Winch Out | Vehicle stuck |
| Fuel/Miscellaneous | Out of gas / misc |
| Locksmith | Key cutting |
| Existing Trip Service | Additional service on existing call |
| *(plus non-roadside types)* | Insurance, Travel, etc. |

### ResourceAbsence — Driver Time Off
| Field | Type | Notes |
|-------|------|-------|
| ResourceId | reference → SR | |
| Start / End | datetime | Absence window |
| Type | picklist | Break (5570), Real-Time Location (459), Out-Short-Term (331), Last assigned Service Location (266), Call out (258), etc. |
| Description | textarea | |
| AbsenceNumber | string | e.g. "RA-16761" |

### Shift — Driver Schedules
| Field | Type | Notes |
|-------|------|-------|
| ServiceResourceId | reference → SR | |
| StartTime / EndTime | datetime | |
| Status | picklist | Confirmed (1212), Tentative (4) |
| Label | string | e.g. "Shift update-Early Start" |
| TimeSlotType | picklist | Normal (1069), Extended (147) |
| StatusCategory | picklist | |

### ERS Custom Objects (ALL have 0 custom fields visible to API user)
| Object | Purpose | Records |
|--------|---------|---------|
| ERS_Service_Appointment_PTA__c | Territory Facility PTA (links SAs to garages/territories) | Has data |
| ERS_Territory_Priority_Matrix__c | Priority matrix for territory dispatching | Has data |
| ERS_Zip_Code__c | Zip code → City mapping | Has data (1 custom: City__c → ERS_City__c) |
| ERS_City__c | City definitions | Has data |
| ERS_County__c | County definitions | Has data |
| ERS_Work_Priority__c | Priority levels: Person/Animal Locked in Car, Medical Concern, Extreme Weather, etc. | 10 records |
| ERS_Battery_Test_Result__c | Battery test results | Has data |
| ERS_Checklist__c | Driver checklists (links to Asset via Truck__c) | Has data |
| ERS_Facility_Contract_Calculator__c | Calculates contracted rates | Has data |
| ERS_Facility_Invoice__c | Invoices to garages (ERS_Facility__c → Account) | Has data |
| ERS_Facility_Products__c | Products supplied by facilities | Has data |
| ERS_Facility_Adjustment__c | Adjustments to facility payments | Has data |
| ERS_Work_Order_Adjustment__c | WO adjustments (Work_Order__c → WorkOrder) | Has data |
| ERS_Work_Order_Cost__c | Cost tracking (Work_Order__c → WO, GL_Account__c, Quantity, Unit_Price) | Has data |
| ERS_Work_Order_Line_Item_History__c | WO line item history | Has data |
| ERS_Reciprocal__c | Cross-club service reciprocals | Has data |
| ERS_Service_Request_Batch__c | Batch processing (Close_Date__c, Facility__c → Account) | Has data |

---

## 2. MEMBERSHIP DOMAIN

### Account (Person Account) — The Member Record
**Record Types:** Person Account (1,243,281), Facility (1,465), Business Account (1,333), Child Account (81)

**Key AAA-specific custom fields on Account:**
| Field | Type | Notes |
|-------|------|-------|
| Account_Member_ID__c | string | Member # |
| Account_Member_Since__c | date | Member since date |
| Member_Status__c | picklist | A, S, X, B, C, L, etc. |
| Coverage__c | picklist | B, PLUS, PMRV, PLRV, PREMIER, PLRV-A, etc. |
| Region__c / Billing_Region__c / Mailing_Region__c | picklist | Central, Rochester, Western, Out of Service Region |
| LTV__c | picklist | Lifetime Value: A, B, C, D, E, A*N, etc. |
| MPI__c | double | Member Product Index |
| Tenure__c | string | Membership tenure |
| ERS_Calls_Available_CP__c | double | ERS calls available current period |
| ERS_Calls_Made_CP__c | double | ERS calls made current period |
| ERS_Calls__c | string | ERS calls (text) |
| Insuance_Customer_ID__c | string | Insurance customer # (note: typo in field name) |
| Insurance_Agent_of_Record__c | reference → User | |
| EPIC_GUID__c | string | EPIC system GUID |
| Golden_Record_Id__c | string | MDM golden record |
| Facility_Number__c | string | For Facility accounts |
| Member_Type__pc | picklist | EMP, FAC, 10, HNR, IND, MIL, etc. (Person Account) |
| Phone__c / Mobile_Phone__c | string | |
| Risk_Score__pc | picklist | 1RS through 10RS |
| Parent_Account__pc | reference → Account | |
| Possible_Duplicate_Account__c | boolean | |

**Opt-out fields** (both Direct Mail and Email for each business line):
- Membership, Insurance, Travel, Financial Services, Driver Training, Life Insurance, Medicare

**FinServ__ fields on Account** (Financial Services Cloud):
- Full banking/investment profile: CreditScore, NetWorth, AUM, TotalInsurance, etc.
- Demographics: Age, Gender, MaritalStatus, HomeOwnership, Occupation, etc.
- Contact preferences, KYC status, etc.

### Asset — Memberships & Vehicles
**33 custom fields.** Used for membership cards AND vehicle records.
| Field | Type | Notes |
|-------|------|-------|
| Membership_ID__c | string | Membership card # |
| Household_Membership_ID__c | string | Household level |
| Coverage__c | picklist | B, PLUS, PREMIER, PMRV, PLRV, etc. |
| Member_Since_Date__c | date | |
| Expiry_Date__c | date | |
| Start_Date__c | date | |
| Role__c | picklist | Primary, Associate, Vehicle |
| Type__c | picklist | Household, Business, Fleet, Flatbed, Wheel Lift, Light Service, etc. |
| Payment_Frequency__c | picklist | A (annual), M (monthly) |
| Payment_Method__c | picklist | Many payment codes |
| ERS_Calls_Available_Current_Period__c | double | |
| ERS_Calls_Made_Current_Period__c | double | |
| Solo__c | boolean | Solo membership |
| RV__c | boolean | RV coverage |
| eBill__c | boolean | Electronic billing |
| Balance_Owing__c | currency | |
| Suspend_Cancel_Date__c | date | |
| Suspend_Cancel_Reason__c | picklist | Many codes |
| Expiration_Action__c | picklist | SUE, CUE |
| Status | standard | A (active), S (suspended), L (lapsed), etc. |
| Fleet_Vehicle__c | reference → Asset | For fleet vehicle linkage |
| Donor__c / Donor_Contact__c / Donor_Type__c | | Gift membership tracking |

### Program__c — Membership Programs
133 records. Standard fields only visible (Name, Id).

### Entitlement_Master__c — Entitlement Definitions
Standard fields only visible.

### Contracted_Service__c — Contracted Services
Custom: Facility_Contract__c (→ Facility_Contract__c), Effective_Start_Date__c

### Contracted_Rate__c — Rate Definitions
Standard fields only visible.

---

## 3. TRAVEL DOMAIN

### Travel_Portfolio__c — 168,348 records
| Field | Type |
|-------|------|
| Account__c | reference → Account |
| Emergency_Contact__c | reference → Contact |
| Preferred_Advisor__c | reference → User |
| Seat_Preference__c | picklist: Window, Aisle, Middle |
| Solo_Club__c | boolean |
| Special_Requests_Notes__c | textarea |
| Travel_Rewards_Available__c | currency |
| My_Customer__c | boolean |

### Related_Traveler__c
| Field | Type |
|-------|------|
| Travel_Portfolio__c | reference → Travel_Portfolio__c |
| Contact__c | reference → Contact |
| Account__c | reference → Account |
| Roles__c | multipicklist: Preferred Companion, Emergency Contact |

### Frequent_Traveler_Number__c
| Field | Type |
|-------|------|
| Travel_Portfolio__c | reference → Travel_Portfolio__c |
| Card_Name__c | picklist: AAdvantage, Air Canada Aeroplan, Delta SkyMiles, Hilton Honors, Marriott Bonvoy, etc. |

---

## 4. INSURANCE / FINANCIAL SERVICES DOMAIN

Built on Salesforce Financial Services Cloud (FinServ__ namespace).

### FinServ__FinancialAccount__c — 121 fields (108 custom)
Full banking/insurance account with: Balance, APY, InterestRate, LoanAmount, Premium, CreditLimit, Status, Type (Brokerage, Checking, CD, Credit Card, Insurance, Mortgage, etc.)

### FinServ__FinancialAccountRole__c
Links accounts to contacts/accounts with roles (Accountant, Beneficiary, Co-Signer, etc.)

### FinServ__FinancialAccountTransaction__c — 24 custom fields
Full transaction tracking: Amount, TransactionDate, PostDate, TransactionType (Credit/Debit), RunningBalance, etc.

### Other FinServ Objects
| Object | Purpose |
|--------|---------|
| FinServ__FinancialGoal__c | Retirement, Home Purchase, Education goals |
| FinServ__FinancialHolding__c | Investment holdings (shares, market value, P&L) |
| FinServ__Card__c | Credit/debit cards |
| FinServ__BillingStatement__c | Monthly statements |
| FinServ__AssetsAndLiabilities__c | Net worth tracking |
| FinServ__Revenue__c | Revenue by account |
| FinServ__Securities__c | Stock/bond definitions |
| FinServ__LifeEvent__c | Life events (New Baby, New Job, Retirement) |
| FinServ__Education__c | Education history |
| FinServ__Employment__c | Employment history |
| FinServ__IdentificationDocument__c | ID documents |
| FinServ__AccountAccountRelation__c | Account-to-account relationships |
| FinServ__ContactContactRelation__c | Contact-to-contact relationships |
| FinServ__Alert__c | Account alerts |
| FinServ__ChargesAndFees__c | Fee schedules |
| FinServ__PolicyPaymentMethod__c | Insurance payment methods |

---

## 5. VEHICLES DOMAIN

### Vehicle_Make_Model__c — 73,400 records
| Field | Type |
|-------|------|
| Make__c | picklist: Acura, Ford, Toyota, etc. |
| Model__c | string |
| Year__c | picklist: 2026, 2025, 2024... |
| Vehicle_Type__c | picklist: Car, Truck, Van, Motorcycle, etc. |
| Fuel_Type__c | picklist: GAS, DIESEL, HYBRID, ELECTRIC |
| Driveline__c | picklist: AWD, 4WD, FWD, RWD |

### Vehicle_Group__c
Groups vehicles by type code (PS, 2M, 3M, R1, R2, etc.)

### Covered_Vehicle__c — 3,612 records
Links Vehicle_Group__c to Entitlement_Master__c (what coverage covers what vehicles)

### Vehicle_Service__c
Links Vehicle_Group__c to WorkTypeGroup (what services apply to what vehicle types)

---

## 6. SUPPORT / CASES DOMAIN

### Case — 741K+ records
| Field | Notes |
|-------|-------|
| Status | Closed (735K), New (5K), Waiting on Customer (1.2K), etc. |
| RecordType.Name | **ERS KMI Alerts** (404K), **ERS** (171K), **Travel Support** (102K), etc. |
| AccountId / ContactId | Member linkage |
| CaseId | standard |
| FinServ__FinancialAccount__c | Financial account reference |
| FinServ__Household__c | Household account |

### Stage_Duration_Tracking__c — Case Stage Timing
| Field | Type |
|-------|------|
| Name | string: "CASE: {CaseId} {StageName}" |
| Stage_Name__c | string: "New", "Closed", etc. |
| DateTime_Stage_Entered__c | datetime |
| DateTime_Difference__c | string |
| Total_Minutes__c | double |

---

## 7. BILLING / PAYMENTS DOMAIN

| Object | Purpose | Key Fields |
|--------|---------|------------|
| Credit_Card__c | Member credit cards | Account_Holder__c → Account |
| Reimbursement_Request__c | Member reimbursements | Account__c, Amount_Due__c, GL_Allocation__c, Related_Case__c |
| Refund_Cancellation__c | Refunds | Has RecordTypeId |
| ERS_Facility_Invoice__c | Garage invoices | ERS_Facility__c → Account |
| ERS_Facility_Invoice_Line_Item__c | Invoice line items | ERS_Source__c (Work Order, WO Adjustment, Facility Adjustment) |
| ERS_Payment_Run__c | Payment batches | ERS_Start_Date__c, ERS_End_Date__c |
| ERS_Pay_Group__c | Pay groups | Standard fields only |
| Facility_Contract__c | Contract types | 19 records: "80-Fleet Reciprocals", A1, A2, A3, A4, etc. |
| Facility_Contract_Assignment__c | Contract → Account mapping | Account__c, Facility_Contract__c |
| ERS_Work_Order_Cost__c | WO cost tracking | Work_Order__c, GL_Account__c, Quantity, Unit_Price__c |

---

## 8. SURVEYS / FEEDBACK DOMAIN

### Survey_Result__c
| Field | Type |
|-------|------|
| Off_Platform_Driver__c | reference → Contact |
| Survey_Driver__c | string |

### Feedback_Resolution__c
| Field | Picklist Values |
|-------|----------------|
| Club_Area__c | AAA Mobile App, AAA.com, Auto-Travel, Automotive, Insurance, Membership, etc. |
| Category__c | AAA Service, Call Quality, Driver Programs, Insurance, etc. |
| Sub_Category__c | Many detailed sub-categories |

### Qualtrics_Data__c
Standard fields only visible.

---

## 9. SCHEDULING INFRASTRUCTURE

### ServiceTerritory — 405+ territories
| Field | Notes |
|-------|-------|
| Name | e.g. "100 - WESTERN NEW YORK FLEET" |
| IsActive | boolean |
| ParentTerritoryId | Hierarchy (top-level: AAA+, Amherst Office, Camillus Office, etc.) |
| TopLevelTerritoryId | Root of hierarchy |
| OperatingHoursId → OperatingHours | |
| Address, City, State, PostalCode, Lat, Lng | Territory center |

**Top-level territories:** 000-SPOT, 002-Towbook Test ST, AAA+, Amherst Office, Camillus Office, etc.
**Child territory counts:** Up to 62 children under one parent.

### ServiceTerritoryMember — Driver → Territory Assignment
| Field | Notes |
|-------|-------|
| ServiceResourceId → SR | |
| ServiceTerritoryId → ST | |
| TerritoryType | Primary, Secondary, Relocation |
| OperatingHoursId | |
| Address, City, State, PostalCode, Lat, Lng | 78 have Lat/Long (9.4%), 748 blank. FSL app auto-syncs GPS for active drivers. |
| EffectiveStartDate / EffectiveEndDate | |

### OperatingHours — 114 records
Examples: "Business Hours" (M-F 9-5:30), "Operating Hours" (M-Sa), "Base Calendar", "Gold Appointments Calendar"

### TimeSlot — Defines operating hour slots
DayOfWeek + StartTime + EndTime per OperatingHoursId

### FSL Scheduling Policy Objects
| Object | Key Fields |
|--------|------------|
| FSL__Scheduling_Policy__c | Id, Name (0 custom fields visible) |
| FSL__Service_Goal__c | Id, Name (0 custom fields visible) |
| FSL__Work_Rule__c | Id, Name (0 custom fields visible) |
| FSL__Scheduling_Policy_Goal__c | FSL__Scheduling_Policy__c, FSL__Service_Goal__c, FSL__Weight__c |
| FSL__Scheduling_Policy_Work_Rule__c | FSL__Scheduling_Policy__c, FSL__Work_Rule__c |
| FSL__Work_Rule_Entry__c | FSL__Work_Rule__c, RecordTypeId |

### Scheduling Policies in Org
1. "Highest priority" — ASAP 9000 / Minimize Travel 1000
2. "Closest Driver" — Minimize Travel 100
3. "DF TEST- Closest Driver" — Minimize Travel 100 (test)
4. "Emergency" — ASAP 700 / Travel 300
5. "Highest Priority" (variant)
6. "Customer First" (no goals)

### Skills System
| Object | Notes |
|--------|-------|
| Skill | 55 skills defined (Insurance types, Travel types, etc.) |
| SkillRequirement | Links skills to WorkTypes |
| ServiceResourceSkill | Links skills to ServiceResources |

### Optimization Objects
| Object | Purpose |
|--------|---------|
| FSL__Optimization_Request__c | Scheduling optimization requests |
| FSL__Optimization_Data__c | Optimization data |
| FSL__Territory_Optimization_Request__c | Per-territory optimization requests |
| FSL__Criteria__c | Filter criteria |
| FSL__SchedulingRecipe__c | Scheduling recipes |
| FSL__FSL_Operation__c | FSL operations log |
| FSL__SLR_Cache__c | SLR (Service Level Routing) cache |

---

## 10. INTEGRATION / ADMIN OBJECTS

| Object | Purpose | Key Fields |
|--------|---------|------------|
| Integration_Log__c | API call logs | Source (AXIS/SF/Epic/MDM), MuleSoft_Application_Name, Payload, URL |
| Transaction_Errors__c | Error tracking | Error_Message, Error_Origin (SF/Mulesoft), Payload, Reprocess_Status |
| D3_URLs__c | D3 system URLs | Prod_D3_URL, Test_D3_URL |
| Code_Translation__c | Code lookups | Code_Key, Type (Insurance Policy, Trouble, Dispatch, Clear) |
| Code_Relationship__c | Code mappings | Code → Related_Code, Relationship Type |
| Geographic_Location__c | 11,483 locations | Name: Central, Rochester, Western, plus travel destinations |
| Account_Group__c / Account_Group_Relationship__c | Account grouping | |
| Account_Type_Dirty_Flag__c | Batch processing flags | Account__c, Run_Type_Update_Tonight |
| Account_Flow_Lock__c | Flow concurrency control | Account__c, isLocked, Lock_Counter |
| MulesoftClientInfo__c / MulesoftCredentials__c | Integration credentials | |
| Time_of_Day_Code__c | Time period definitions | Start_Time, End_Time |

### DocuSign Integration (dfsle__ namespace)
Full DocuSign envelope tracking: Envelope__c, EnvelopeStatus__c, RecipientStatus__c, Document__c, etc.

---

## 11. ACCOUNT RECORD TYPES

| Record Type | Count | Purpose |
|-------------|-------|---------|
| Person Account | 1,243,281 | AAA members (individuals) |
| Facility | 1,465 | Garages, tow companies, service providers |
| Business Account | 1,333 | Business members |
| Child Account | 81 | Sub-accounts |

---

## 12. RELATIONSHIP MAP

```
Member (Account/Person Account)
  ├── Asset (Membership cards + vehicles)
  │     ├── Membership_ID__c, Coverage__c, Expiry_Date__c
  │     └── ERS_Calls_Available/Made
  ├── Travel_Portfolio__c
  │     ├── Related_Traveler__c → Contact
  │     └── Frequent_Traveler_Number__c
  ├── FinServ__FinancialAccount__c (Insurance/Banking)
  │     ├── FinServ__FinancialAccountRole__c
  │     ├── FinServ__FinancialAccountTransaction__c
  │     ├── FinServ__Card__c
  │     └── FinServ__BillingStatement__c
  ├── Case (Support tickets)
  │     └── Stage_Duration_Tracking__c
  ├── WorkOrder (Roadside service)
  │     ├── WorkOrderLineItem → WorkType
  │     └── ServiceAppointment
  │           ├── AssignedResource → ServiceResource (driver/garage)
  │           └── ServiceAppointmentHistory (status changes)
  └── Credit_Card__c / Reimbursement_Request__c

ServiceResource (Driver/Garage)
  ├── ServiceTerritoryMember → ServiceTerritory
  ├── ServiceResourceSkill → Skill
  ├── Shift (schedule)
  ├── ResourceAbsence (time off/breaks)
  ├── Account (for Towbook: garage identity)
  └── AssignedResource → ServiceAppointment

Facility Account
  ├── Facility_Contract_Assignment__c → Facility_Contract__c
  ├── ERS_Facility_Invoice__c → ERS_Facility_Invoice_Line_Item__c
  ├── ERS_Facility_Contract_Calculator__c
  ├── ERS_Facility_Adjustment__c
  └── ERS_Service_Appointment_PTA__c
```

---

## OBJECTS THAT DO NOT EXIST IN THIS ORG
- ResourceCapacity (use ServiceResourceCapacity instead — 0 records)
- FSL__Contractor__c
- FSL__Estimated_Travel_Time__c
- AppointmentScheduleLog / AppointmentScheduleAggr (0 records)
- ServiceResourceCapacity (0 records)

## KEY DATA VOLUMES
| Object | Record Count |
|--------|-------------|
| Account (Person) | 1,243,281 |
| ServiceAppointment | ~700K+ |
| Case | ~741K |
| Asset | Many |
| Travel_Portfolio__c | 168,348 |
| Vehicle_Make_Model__c | 73,400 |
| Geographic_Location__c | 11,483 |
| Covered_Vehicle__c | 3,612 |
| Shift | 1,216 |
| OperatingHours | 114 |
| Skill | 55 |
| Facility_Contract__c | 19 |
| ERS_Work_Priority__c | 10 |
