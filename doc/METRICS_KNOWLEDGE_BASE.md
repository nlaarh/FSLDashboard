# FSL App — Metrics Knowledge Base

All metrics, formulas, Salesforce fields, and fallback behavior documented per page.

---

## Salesforce Fields Reference

| Field | Object | Type | Description |
|-------|--------|------|-------------|
| `CreatedDate` | ServiceAppointment | DateTime (standard) | When the call was created. **Start of clock** for all time-based metrics. |
| `ActualStartTime` | ServiceAppointment | DateTime (standard) | **Fleet**: real driver arrival time. **Towbook**: FAKE — written at completion as a future estimate. Do NOT use for Towbook ATA. |
| `ActualEndTime` | ServiceAppointment | DateTime (standard) | When the job was marked completed. |
| `SchedStartTime` | ServiceAppointment | DateTime (standard) | When the scheduler assigned a driver. Used for dispatch speed. Works for both Fleet and Towbook. |
| `ERS_PTA__c` | ServiceAppointment | Number (custom) | Promised Time of Arrival in minutes. The time quoted to the member at dispatch. |
| `ERS_Dispatch_Method__c` | ServiceAppointment | Formula (custom) | `'Field Services'` = Fleet (internal). `'Towbook'` = Contractor (external). Determines which ATA calculation to use. |
| `Status` | ServiceAppointment | Picklist (standard) | Lifecycle: Dispatched, Assigned, Completed, Canceled, Cancel Call - Service Not En Route, Cancel Call - Service En Route, Unable to Complete, No-Show. |
| `WorkType.Name` | WorkType (via SA) | Text (standard) | Call type: Tow, Flat Bed, Wheel Lift, Winch Out, Battery, Jumpstart, Tire, Lockout, Fuel Delivery, etc. |
| `ERS_Cancellation_Reason__c` | ServiceAppointment | Picklist (custom) | Why a call was canceled. `'Member Could Not Wait%'` = CNW metric. |
| `ERS_Facility_Decline_Reason__c` | ServiceAppointment | Picklist (custom) | Why a garage declined work. Non-null = decline counted. |
| `Off_Platform_Driver__c` | ServiceAppointment | Lookup→Contact (custom) | Towbook driver contact. Used for contractor leaderboard (driver name + ID). |
| `ERS_Service_Appointment_PTA__c` | ERS_Service_Appointment_PTA__c | Number (custom object) | PTA setting per territory + work type. What Mulesoft quotes to members. |
| `ServiceAppointmentHistory` | History table | — | Tracks all field changes. `Field='Status'`, `NewValue='On Location'` → real Towbook driver arrival. The `CreatedDate` of that history row = actual arrival timestamp. |

---

## How ATA (Actual Time of Arrival) is Calculated

### Fleet Garages (`ERS_Dispatch_Method__c = 'Field Services'`)

```
ATA = ActualStartTime − CreatedDate  (in minutes)
```

`ActualStartTime` is the real arrival time recorded by the FSL mobile app.

### Towbook Garages (`ERS_Dispatch_Method__c = 'Towbook'`)

```
ATA = ServiceAppointmentHistory.CreatedDate (where Status → 'On Location') − ServiceAppointment.CreatedDate  (in minutes)
```

**Why not ActualStartTime?** Towbook writes `ActualStartTime` at the moment of completion as a **future estimate**, not real arrival. The real arrival is the `On Location` status change recorded in `ServiceAppointmentHistory` by the "Integrations Towbook" system user.

**How it's fetched:** `get_towbook_on_location(sa_ids)` in `sf_client.py` batch-queries:
```sql
SELECT ServiceAppointmentId, NewValue, CreatedDate
FROM ServiceAppointmentHistory
WHERE ServiceAppointmentId IN (:sa_ids)
  AND Field = 'Status'
ORDER BY ServiceAppointmentId, CreatedDate ASC
```
Returns the first `On Location` CreatedDate per SA.

### Validity Filter (both types)

```
If ATA ≤ 0 or ATA ≥ 1440 → discard (bad data)
```

---

## Page: Garages List (`/garages` — ops.py `get_ops_territories`)

**Time window:** Today only (midnight ET to now).

### AVG PTA

```
AVG PTA = sum(ERS_PTA__c) ÷ count(SAs with ERS_PTA__c)
```

- **Population:** ALL today's SAs (any status) where `0 < ERS_PTA__c < 999`
- **Default if missing:** `null` → shown as `—`

### AVG ATA

```
AVG ATA = sum(ATA) ÷ count(completed SAs with valid ATA)
```

- **Population:** Only **completed** SAs with a calculable ATA
- **ATA per SA:** Fleet: `ActualStartTime − CreatedDate`. Towbook: `OnLocation − CreatedDate`
- **Default if missing:** Falls back to AVG PTA with label `"est. (PTA)"`. If no PTA either → `—`

### SLA % (under 45 min)

```
ATA Under 45% = count(ATA ≤ 45) ÷ count(completed SAs with ATA) × 100
```

- **Default if missing:** `null` → `—`

### Completion Rate (DONE %)

```
DONE % = count(Status = 'Completed') ÷ count(all SAs) × 100
```

- Excludes Tow Drop-Off work type
- **Default if missing:** `0%`

### 1ST CALL % / 2ND+ CALL %

```
1ST CALL % = count(primary completed) ÷ count(primary total) × 100
2ND+ CALL % = count(secondary completed) ÷ count(secondary total) × 100
```

- Primary = rank 1 in Territory Priority Matrix. Secondary = rank 2+.
- **Default if missing:** `—`

### Response Time (resp_time)

```
If AVG ATA exists → resp_time = AVG ATA, resp_source = 'ata'
Else if AVG PTA exists → resp_time = AVG PTA, resp_source = 'pta'
Else → null
```

### MAX WAIT

```
MAX WAIT = max(now − CreatedDate) for open SAs (Dispatched/Assigned)
```

- Only open calls. Completed/canceled calls don't contribute.
- **Default if missing:** `—`

---

## Page: Garage Dashboard (`/garage/:id` — main.py `_compute_performance` + `get_scorecard`)

**Time window:** Weekly (7 days) or Monthly (28 days), selectable.

### Median Response Time

```
1. Collect ATA for all completed SAs in window
2. Sort ascending
3. Median = value at position [count ÷ 2]
```

- **Default if missing:** `null` → `—`

### SLA Hit Rate (45-Min SLA)

```
SLA Hit Rate = count(ATA ≤ 45) ÷ count(all valid ATAs)
```

- **Default if missing:** `null` → `—`

### ETA Accuracy (Promise vs Actual)

```
For each completed SA where ERS_PTA__c exists AND ATA exists:
  on_time = (ATA ≤ ERS_PTA__c)

ETA Accuracy = count(on_time) ÷ count(evaluated) × 100
Avg Overshoot = sum(ATA − ERS_PTA__c for late calls) ÷ count(late calls)
```

- Fleet ATA = `ActualStartTime − CreatedDate`
- Towbook ATA = `OnLocation − CreatedDate`
- Only SAs where `0 < ATA < 480` minutes are evaluated
- **Default if missing:** `null` → `—`

### Completion Rate

```
Completion Rate = count(Status = 'Completed') ÷ count(all SAs) × 100
```

- Aggregate SOQL `GROUP BY Status`
- Excludes Tow Drop-Off work type
- **Default if missing:** `0%`

### Satisfaction Rate

```
Satisfaction = count(ERS_Overall_Satisfaction__c = 'Totally Satisfied') ÷ count(all surveys) × 100
```

- Surveys linked via `ERS_Work_Order_Number__c` matching `WorkOrder.WorkOrderNumber`
- Max 500 work orders queried
- **Default if missing:** `null` → `—`

### Response Time Breakdown (buckets)

```
Bucket 1: ATA ≤ 30 min
Bucket 2: 30 < ATA ≤ 45 min
Bucket 3: 45 < ATA ≤ 60 min
Bucket 4: 60 < ATA ≤ 90 min
Bucket 5: ATA > 90 min (labeled "2+ hours")
```

### Where Time is Spent

```
Member Wait = CreatedDate → driver arrival (= ATA)
On-Site Service = driver arrival → ActualEndTime
Total = Member Wait + On-Site Service
```

- Fleet: arrival = ActualStartTime
- Towbook: arrival = On Location timestamp

### Contractor Leaderboard (Towbook garages)

```
Keyed by: Off_Platform_Driver__c (driver contact)
Per driver:
  Calls = count(completed SAs)
  Avg Response = sum(ATA) ÷ count(SAs with ATA)
  Median = median of ATAs
  On-Site = avg(ActualEndTime − arrival)
  Declines = count(ERS_Facility_Decline_Reason__c != null)
```

- Drivers without `Off_Platform_Driver__c` are skipped and counted as `missing_driver_info`
- **Default if missing driver:** Row omitted, count shown as note

### Facility Declines

```
Decline Rate = count(ERS_Facility_Decline_Reason__c != null) ÷ total SAs
```

- Breakdown by reason is shown
- **Default if missing:** `0`

### Cancellations

```
CNW Rate = count(ERS_Cancellation_Reason__c LIKE 'Member Could Not Wait%') ÷ total SAs
```

- Breakdown by reason is shown
- **Default if missing:** `0`

---

## Page: Scorer (`/api/score/:id` — scorer.py `compute_score`)

**Time window:** 4 weeks (28 days) by default.

### 8 Dimensions with Weights

| Dimension | Weight | Target | Higher Better | Formula |
|-----------|--------|--------|---------------|---------|
| SLA Hit Rate | 30% | 100% | Yes | `count(ATA ≤ 45) ÷ count(valid ATAs)` |
| Completion Rate | 15% | 95% | Yes | `count(Completed) ÷ count(all SAs)` |
| Satisfaction | 15% | 82% | Yes | `count(Totally Satisfied) ÷ count(surveys)` |
| Median Response | 10% | 45 min | No | `median(all ATAs)` |
| PTA Accuracy | 10% | 90% | Yes | `count(ATA ≤ ERS_PTA__c) ÷ count(evaluated)` |
| Could Not Wait | 10% | 3% | No | `count(CNW cancellations) ÷ count(all SAs)` |
| Dispatch Speed | 5% | 5 min | No | `median(SchedStartTime − CreatedDate)` |
| Decline Rate | 5% | 2% | No | `count(declines) ÷ count(all SAs)` |

### Dimension Score

```
If higher_better:
  score = min(100, actual ÷ target × 100)

If lower_better:
  If actual ≤ target → score = 100
  Else → score = max(0, 100 × (1 − (actual − target) ÷ target))
```

### Composite Score

```
composite = sum(score × weight for each dimension with data) ÷ sum(weight for each dimension with data)
```

- Dimensions with `null` actual value are excluded from both numerator and denominator.

### Grade

```
A = composite ≥ 90
B = composite ≥ 80
C = composite ≥ 70
D = composite ≥ 60
F = composite < 60
? = no composite (all null)
```

---

## Page: PTA Advisor (`/pta` — main.py `pta_advisor`)

**Time window:** Today only. Refreshes every 15 min (configurable).

**Purpose:** Projects what the wait time would be RIGHT NOW for a new call, compared to the PTA setting in Salesforce.

### Does NOT use historical ATA

PTA Advisor is a **forward-looking projection**, not historical analysis. It does not calculate or use ATA from completed calls. It uses:
- Live queue depth (open SAs)
- Driver availability (idle/busy)
- Cycle times per work type
- Current PTA settings

### Projected PTA per Call Type

**Fleet garages (has logged-in drivers):**

```
If idle driver available for this call type:
  projected = PTA setting (per-type or scaled default)

If only busy drivers:
  Heap-based FIFO simulation:
    1. Put each busy driver's remaining_min on a min-heap
    2. For each queued SA: pop min, add cycle_time, push back
    3. Pop final min = next_free_time
    4. projected = next_free_time + dispatch_travel_buffer

If no capable drivers:
  projected = null (labeled "No Drivers")
```

**Contractor garages (Towbook, no Fleet drivers):**

```
If open SAs exist matching this call type:
  projected = avg(ERS_PTA__c) for open SAs of this type

Else if PTA setting exists:
  projected = setting × type_scale (tow=1.0, winch=0.75, battery=0.65, light=0.7)

Else:
  projected = default (tow=90, winch=60, battery=45, light=45)
```

### Recommendation

```
If projected is null → 'no_coverage'
If no PTA setting → 'no_setting'
If projected > setting × 1.2 → 'increase' (PTA too optimistic)
If projected < setting × 0.6 → 'decrease' (PTA could be lowered)
Else → 'ok'
```

### Cycle Times

| Type | Cycle Time | Dispatch Buffer |
|------|-----------|-----------------|
| Tow | 115 min | 30 min |
| Winch | 40 min | 25 min |
| Battery | 38 min | 25 min |
| Light | 33 min | 25 min |

### Driver Skill Hierarchy

```
Tow driver → can serve: Tow, Winch, Light, Battery
Light driver → can serve: Winch, Light, Battery
Battery driver → can serve: Battery only
```

### `has_arrived` Field (Driver Queue Display)

```
has_arrived = ActualStartTime is not null
```

This is correct even for Towbook because PTA Advisor only looks at **active SAs** (Dispatched/Assigned). Towbook only writes the fake ActualStartTime at completion, not during active dispatch.

---

## Page: Dispatch Analysis (`/garage/:id` Dashboard tab — dispatch.py)

**Time window:** Weekly or Monthly, matching garage dashboard.

### Response Time Decomposition

```
For each completed SA:
  Member Wait (queue) = CreatedDate → SchedStartTime
  Dispatch-to-Arrival = SchedStartTime → driver arrival
  On-Site Service = driver arrival → ActualEndTime

  Fleet: driver arrival = ActualStartTime
  Towbook: driver arrival = On Location from history
```

### Leaderboard (Towbook Garages)

```
Keyed by: Off_Platform_Driver__c
Per driver:
  Calls = count(completed SAs)
  Avg Response = avg(ATA) where ATA = OnLocation − CreatedDate
  Median = median(ATA values)
  On-Site = avg(ActualEndTime − OnLocation)
  Declines = count(SAs with ERS_Facility_Decline_Reason__c)
```

- Drivers without `Off_Platform_Driver__c` are skipped
- `response_metric` = `'ATA (actual)'` for both Fleet and Towbook

---

## Default / Fallback Behavior Summary

| Metric | When data is missing | Display |
|--------|---------------------|---------|
| AVG PTA | No SAs with valid ERS_PTA__c | `—` |
| AVG ATA | No completed SAs with valid arrival time | Falls back to AVG PTA, labeled `"est. (PTA)"` |
| AVG ATA | No completed SAs AND no PTA | `—` |
| SLA Hit Rate | No valid ATAs | `—` |
| Median Response | No valid ATAs | `—` |
| ETA Accuracy | No SAs with both PTA and ATA | `—` |
| PTA Accuracy (scorer) | No SAs with both PTA and ATA | `N/A` (excluded from composite) |
| Satisfaction | No surveys found | `—` or `N/A` (excluded from composite) |
| Completion Rate | No SAs at all | `0%` |
| CNW Rate | No CNW cancellations | `0` |
| Decline Rate | No declines | `0` |
| Dispatch Speed | No valid SchedStartTime | `N/A` (excluded from composite) |
| Projected PTA (Advisor) | No capable drivers (Fleet) | `null` → "No Drivers" |
| Projected PTA (Advisor) | No open SAs (Towbook) | Falls back to PTA setting, then default |

---

## Key Implementation Files

| File | What it computes |
|------|-----------------|
| `backend/ops.py` | Garages list (today): AVG PTA, AVG ATA, completion, wait times |
| `backend/main.py` → `_compute_performance()` | Garage dashboard: response times, ETA accuracy, satisfaction, leaderboard |
| `backend/main.py` → `get_scorecard()` | Scorecard: 8-dimension composite score |
| `backend/main.py` → `pta_advisor()` | PTA Advisor: projected wait times |
| `backend/scorer.py` → `compute_score()` | Scorer: 8-dimension weighted composite (0-100 + grade) |
| `backend/dispatch.py` | Dispatch analysis: decomposition, leaderboard |
| `backend/sf_client.py` → `get_towbook_on_location()` | Shared utility: batch-fetch real Towbook arrival from history |

---

*Last updated: 2026-03-13*
