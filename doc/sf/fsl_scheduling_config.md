# FSL Scheduling Configuration — Full Documentation (Complete)
**Organization:** AAAWCNY (aaawcny.lightning.force.com)
**Captured:** March 15, 2026

---

## STEP 1: AUTOMATED SCHEDULING (Left Sidebar)

**Section title:** Automated Scheduling
**Tab:** SCHEDULING RECIPES (only one tab)

**Important note:** This section does NOT contain a "scheduling policy" dropdown or an enable/disable toggle. It is solely for configuring **Scheduling Recipes** (automated responses to schedule events). There is no policy ID, no global enable/disable setting, and no territory scope setting here.

**Description text on page:**
> "Stay two steps ahead of common scheduling challenges by activating 'recipes' of schedule optimization settings. Choose what happens to your schedule after appointment cancellations, time changes, and overlaps. Don't worry–we'll tell you if a recipe conflicts with your existing optimization settings. Cover all scenarios by creating multiple recipes for each category and putting them in priority order. If an event meets the criteria of more than one recipe, the higher-priority recipe is used."

### Recipe Categories and Configured Recipes

| Category | Description | Recipe Name | Status |
|---|---|---|---|
| Canceled Appointment | Choose what to do with the available time in the schedule when an appointment is canceled. | (Example) Customer Cancels | Inactive |
| Shortened Appointment | Choose what to do with the available time in the schedule when an appointment ends early. | (Example) Appointment Ends Early | Inactive |
| Late-End Overlap | Choose how to address a schedule overlap caused by an appointment running long. | (Example) Appointment Ends Late | Inactive |
| Emergency Overlap | Choose how to address a schedule overlap caused by emergency scheduling. | (Example) Emergency Appointment | Inactive |

**Summary:** All 4 recipes are example/placeholder records and all are **Inactive**. No custom recipes have been created. No scheduling policy is configured here.

---

## STEP 2: SCHEDULING > SCHEDULING POLICIES TAB

**Section title:** Scheduling
**Active tab:** SCHEDULING POLICIES

**Tabs available:** GENERAL LOGIC | **SCHEDULING POLICIES** | DYNAMIC GANTT | ROUTING | BUNDLING | WORK CAPACITY

**Description text on page:**
> "A Scheduling Policy is based on scheduling rules and weighted business objectives. When the optimization engine builds and maintains the schedule, its decisions are guided by your scheduling policies."

**Note:** The tab shows only the description and Save/Restore Defaults buttons. No policies are listed inline here. The policy records live in the top-nav "Scheduling Policies" object.

### Full List of Scheduling Policies (All — 5 records, sorted by name)

| # | Policy Name |
|---|---|
| 1 | Closest Driver |
| 2 | Copy of Highest Priority |
| 3 | DF TEST- Closest Driver |
| 4 | Emergency |
| 5 | Highest priority |

**No policy is marked as a global default in the UI.** In Salesforce FSL, the policy is set per Service Territory and per Optimization Job.

---

## STEP 3: SCHEDULING > GENERAL LOGIC TAB

**Section title:** Scheduling | **Active tab:** GENERAL LOGIC

### Top-Level Fields

| Setting | Value |
|---|---|
| Multiday service appointment field | Is MultiDay |
| Set the hour that starts a new day based on the Availability rule(s) | Unchecked (OFF) |
| Maximum days to get candidates or to book an appointment | 10 |
| Delay auto-scheduling until appointments are geocoded | Checked (ON) |
| Activate Approval confirmation on resource absences | Unchecked (OFF) |
| Avoid aerial calculation upon callout DML exception | Checked (ON) |
| Respect secondary STM operating hours | Checked (ON) |

### Sliding and Reshuffling

| Setting | Value |
|---|---|
| Sliding Only (radio) | NOT selected |
| Enable complex work sliding by territory | Checked (ON) |
| **Sliding and reshuffling** (radio) | **SELECTED** |
| Keep Scheduled Criteria (Beta)* | None |
| None (radio) | NOT selected |

**Pin Criteria — 13 statuses selected (pinned/unmovable for scheduling):**
Completed, Received, Dispatched, Accepted, En Route, Rejected, On Location, Unable to Complete, Canceled, Declined, Cancel Call - Service Not En Route, Cancel Call - Service En Route, Acknowledged

### Enhanced Scheduling Flags

| Setting | Value |
|---|---|
| Use enhanced scheduling and optimization for all service territories | Checked (ON) |
| Use the Visiting Hours object's time zone when an appointment has visiting hours | Checked (ON) |
| Use enhanced scheduling and optimization when there isn't an associated service territory | Checked (ON) |
| Enable the Fix Schedule Overlaps flow (Beta) | Unchecked (OFF) |
| Fix Schedule Overlaps flow (Beta) API name | AAA_ERS_Fix_Schedule_SA_Overlaps |
| Generate activity reports and retrieve optimization request files | Checked (ON) |

### Scheduling Priority

| Setting | Value |
|---|---|
| Work Order Priority Field | None |
| Work Order Line Item Priority Field | None |
| Service Appointment Priority Field | Dynamic Priority |
| Use 1-100 priority scale | Checked (ON) |

### Crews

| Setting | Value |
|---|---|
| Enable resource crew skill grouping | Unchecked (OFF) |
| Assign Service Appointments to individuals and crews | Unchecked (OFF) |

### Complex Work

| Setting | Value |
|---|---|
| FSL Operation — Object Sharing | Private (green checkmark) |
| Enable complex work | Checked (ON) |
| Use all-or-none scheduling for related appointments | Checked (ON) |

### Limit Apex Operations

| Setting | Value |
|---|---|
| Set Apex operation timeout limits | Unchecked (OFF) |
| Timeout Limit for Get Candidates (Percent) | 95 |
| Timeout Limit for Appointment Booking (Percent) | 95 |
| Timeout Limit for Scheduling (Percent) | 90 |

---

## STEP 4: OPTIMIZATION (Left Sidebar)

### Tab: ACTIVATION

| Setting | Value |
|---|---|
| Turn on Enhanced Scheduling and Optimization | **ENABLED** (green toggle) |
| Standard Optimization — User profile | Not authorized |
| Optimization Insights | ON (blue toggle) |

### Tab: LOGIC — General Logic

| Setting | Value |
|---|---|
| Enable optimization overlaps prevention | Checked (ON) |
| Mark optimization requests failed when failing due to org customizations | Checked (ON) |
| Enable sharing for Optimization request | Unchecked (OFF) |
| Global optimization run time per service appointment | High |
| Enable Dynamic Scaling | Unchecked (OFF) |

### Tab: LOGIC — Safeguarded Service Appointments

**Global Optimization — Pin Criteria (11 statuses):**
Completed, Received, En Route, Rejected, On Location, Unable to Complete, Canceled, Declined, Cancel Call - Service Not En Route, Cancel Call - Service En Route, Acknowledged
Keep Scheduled Criteria (Beta)*: None

**In-Day Optimization — Pin Criteria (11 statuses — same as above):**
Keep Scheduled Criteria (Beta)*: None

**Resource Schedule Optimization — Pin Criteria (11 statuses — same as above)**

---

### Tab: SCHEDULED JOBS — Overview

| Job Name | Status | Type |
|---|---|---|
| **Closest Drv. Optimization** | **Active** | Enhanced |
| Day Optimization | Inactive | Enhanced |
| Optimization | Inactive | Standard (legacy) |
| PRD Launch Smoke Test Optimization | Inactive | Enhanced |

---

### JOB 1: Closest Drv. Optimization — ACTIVE

**Status:** Active (toggle ON) | **Type:** Enhanced

#### General Tab
| Setting | Value |
|---|---|
| Time Periods — From Day | 1 |
| Time Periods — To Day | 1 |
| Scheduling Policy | **Copy of Highest Priority** |
| Appointment Optimization Criteria | Auto Assign? |
| Keep Scheduled Criteria (Beta) | Use the default selection |
| Notification Recipient | dfisher@nyaaa.com |

#### Territory Tab — Groups
| Group # | Selected Service Territories | Scheduling Policy |
|---|---|---|
| 1 | 100 - western new york fleet | Copy of Highest Priority |

#### Schedule Tab
| Setting | Value |
|---|---|
| Job Frequency | Recurring |
| Recurrence type | Weekly |
| Repeat on Days | Sun, Mon, Tue, Wed, Thu, Fri, Sat (all 7 days) |
| Repeat in Months | All 12 months |
| Time setting | **Recurring — Every 15 Minutes** |
| Run between | Unchecked (OFF) — values shown: 0:00 to 20:00 but not enabled |

---

### JOB 2: Day Optimization — INACTIVE

**Status:** Inactive | **Type:** Enhanced

#### General Tab
| Setting | Value |
|---|---|
| Time Periods — From Day | 0 |
| Time Periods — To Day | 1 |
| Scheduling Policy | **Highest priority** |

#### Territory Tab — Groups
| Group # | Selected Service Territories | Scheduling Policy |
|---|---|---|
| 1 | 4652d - val u auto llc, 800 - central region ers fleet services | Highest priority |
| 2 | 063 - bison automotive | Highest priority |
| 3 | 421 - action towing of rochester inc | Highest priority |
| 4 | 4602 - lamphere trucking & general repai, 831 - phinney's chevrolet & olds, inc. | Highest priority |

#### Schedule Tab
| Setting | Value |
|---|---|
| Job Frequency | Recurring |
| Recurrence type | Weekly |
| Repeat on Days | Sun, Mon, Tue, Wed, Thu, Fri, Sat (all 7 days) |
| Repeat in Months | All 12 months |
| Time setting | **Recurring — Every 15 Minutes** |
| Run between | Unchecked (OFF) — values shown: 0:00 to 20:00 but not enabled |

---

### JOB 3: Optimization — INACTIVE (Legacy)

**Status:** Inactive | **Type:** Standard (legacy — no General/Territory/Schedule tabs, uses flat layout)

#### All Settings (Single View)
| Setting | Value |
|---|---|
| Effective Territories | None selected (checkboxes available: 000- CNY M / NC SPOT, 000- ROC M SPOT, 000- ST SPOT, 000- WNY M SPOT, 002- Towbook Test ST, 053 - MICHAEL BELLRENG, 057 - KNOLL'S MOBIL NORTH LLC, 063 - BISON AUTOMOTIVE, etc.) |
| Optimize in stages | OFF |
| Time Horizon in days | 7 |
| Appointment Optimization Criteria | Include all types |
| Scheduling Policy | **(blank — not set)** |
| Email recipient user name | (blank) |
| Frequency | Recurring |
| Month | All 12 months |
| Day type | Day of week |
| Days | Sun, Mon, Tue, Wed, Thu, Fri, Sat (all 7) |
| Time | Specific Hour |
| Hour | 0 |
| Minute | 0 |
| Timezone | America/New_York |

---

### JOB 4: PRD Launch Smoke Test Optimization — INACTIVE

**Status:** Inactive | **Type:** Enhanced

#### General Tab
| Setting | Value |
|---|---|
| Time Periods — From Day | 0 |
| Time Periods — To Day | 1 |
| Scheduling Policy | **Highest priority** |
| Appointment Optimization Criteria | Auto Assign? |
| Keep Scheduled Criteria (Beta) | Use the default selection |
| Notification Recipient | (blank) |

#### Territory Tab — Groups
| Group # | Selected Service Territories | Scheduling Policy |
|---|---|---|
| 1 | test ers facility | Highest priority |

#### Schedule Tab
| Setting | Value |
|---|---|
| Job Frequency | Recurring |
| Recurrence type | Weekly |
| Repeat on Days | Sun, Mon, Tue, Wed, Thu, Fri, Sat (all 7 days) |
| Repeat in Months | All 12 months |
| Time setting | **Recurring — Every 15 Minutes** |
| Run between | Unchecked (OFF) — values shown: 0:00 to 20:00 but not enabled |

### Tab: ADVANCED PARAMETERS
Two collapsed sections (contents not expanded):
- Service Optimization - Additional properties
- Resource Optimization - Additional properties

---

## STEP 5: DISPATCH (Left Sidebar)

### Tab: DRIP FEED

| Setting | Value |
|---|---|
| Enable drip feed dispatching | Unchecked (OFF) |
| Service Appointments to Dispatch | 2 |

### Tab: SCHEDULED JOBS

| Setting | Value |
|---|---|
| Mention assigned user when the Service Appointment is dispatched | Checked (ON) |
| Dispatch Chatter Post Destination | Service Appointment Feed |

#### Auto Dispatch Job

| Setting | Value |
|---|---|
| Active toggle | **OFF** (Inactive) |
| Frequency | Recurring |
| Months | All 12 months |
| Day type | Day of week |
| Days | Sun, Mon, Tue, Wed, Thu, Fri, Sat (all 7) |
| Time type | Specific Hour |
| Hour | 0 |
| Minute | 0 |

**Effective Territories listed (none checked/selected):**
000- CNY M / NC SPOT, 000- ROC M SPOT, 000- ST SPOT, 000- WNY M SPOT, 002- Towbook Test ST, 053 - MICHAEL BELLRENG, 057 - KNOLL'S MOBIL NORTH LLC, 063 - BISON AUTOMOTIVE, and more...

---

## KEY FINDINGS SUMMARY

| Question | Answer |
|---|---|
| Scheduling policy for Automated Scheduling | N/A — no policy set here; section only manages Recipes (all 4 Inactive) |
| Global default scheduling policy | No single global default exists in FSL Settings |
| Total scheduling policies in org | 5: Closest Driver, Copy of Highest Priority, DF TEST- Closest Driver, Emergency, Highest priority |
| Only **Active** optimization job | **Closest Drv. Optimization** |
| Policy on active job | **Copy of Highest Priority** (ASAP 1,000 / Travel 10 = 100:1 ratio) |
| Territory on active job | **100 - western new york fleet** |
| Active job schedule | **Every 15 minutes**, all 7 days, all 12 months, 24/7 (Run Between not enabled) |
| Day Optimization (Inactive) policy | **Highest priority** (ASAP 9,000 / Travel 1,000 = 9:1 ratio) |
| Day Optimization territories (4 groups) | val u auto, central region ERS fleet, bison automotive, action towing rochester, lamphere trucking, phinney's chevrolet |
| Day Optimization schedule | Every 15 min, all days/months (would run 24/7 if active) |
| Optimization (legacy, Inactive) | Standard type, no policy set, 7-day horizon, no territories selected, midnight daily |
| PRD Smoke Test (Inactive) | **Highest priority** → test ers facility, every 15 min |
| Enhanced S&O | **Enabled globally** for all territories |
| Auto Dispatch job | **Inactive**; configured midnight daily |
