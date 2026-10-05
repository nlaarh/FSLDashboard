# Call Story: Data Spec ("type a call, see what happened and why")

Owner: Henry (sources, rules, thresholds) · For: Dan (design), Ruby (build), Tamy (golden tests)
Status: DRAFT for user approval · 2026-10-03 · rules `cs1` · extends `GET /api/sa/{sa_number}/report`
All numbers come from read-only SOQL, pulled sequentially. Scripts: `docs/scheduler-report-card/validation/call_story/`.
No app code here. Nothing in this spec reads production Postgres.

---

## 0. The answer first

1. **One box takes any of four inputs:** SA number, WO number, the call key `084-YYYYMMDD-<WO#>`, or the D3/RAP
   source call ID. Each resolves to one WorkOrder and its member-facing SA. `Tow_Call__c` is **not** a call number.
   It is a true/false tow flag. Section 2 explains.
2. **The story is built from data we already trust:**
   - `ServiceAppointmentHistory`, with OldValue *and* NewValue (the current SA report never fetches OldValue).
   - The priority matrix.
   - The SMS log.
   - The SF optimizer trail.
   - The report-card verdict engine.
   A normal call needs about 7 light sequential queries.
3. **"Grid" in this org = the spotting zone** (e.g. `WM003`). All 228 map polygons in `/api/map/grids` are exactly
   these 228 zones. `SA.ERS_Parent_Territory__c` holds the call's grid, and the priority matrix ranks the garages
   for each grid. "Stuck in the grid" most likely means **the call ran out of garages and was parked in a
   `000-<region> SPOT` bucket**. On 9/28, 76 calls did this (median 6 min, p90 27 min, max 61 min). Nearly every
   call still parked there at the end gets canceled by the member. Two other readings are possible (§6), so please
   confirm with the user.
4. **We can prove an SMS was *sent*, not that it was *delivered*.**
   - `SMS_Send_Log__c` (since 2026-09-01) logs every attempt with an outcome: Sent, Failed or Skipped-*.
   - Each "Sent" row matches a `MessagingSession` (Origin `TriggeredOutbound`) 1:1.
   - Carrier delivery status lives in `ConversationEntry.MessageStatus`, and this API user gets 0 rows back.
   - Before 9/1 we can still count texts from `MessagingSession`, but we cannot tell which message each one was.
5. **The flows explain why some members get no update for over an hour.** The "we're still working on it" texts
   fire 30, 50 and 80 min after the SA enters Assigned/Dispatched. They are **cancelled whenever the status leaves
   those two values**. A call that cascades through declines or rejections keeps restarting the timer. The Towbook
   golden call got no update text for 82 minutes for this reason.
6. **"Stuck" = time in a stage above the garage's own p90 for that stage, channel and hour block.** Dispatched →
   Accepted is split by whether the driver was busy (WNY week: free p90 40 min, busy p90 58 min).
7. **Every "why" is a deterministic cause code** (§8), built on the report-card verdicts (STACKED, CAPACITY_SHORT,
   BOUNCED, etc.). The AI only turns the fact list into sentences.
8. **Four golden calls are written out step by step** (§10), with Ids: GOOD, BOUNCED, CAPACITY_SHORT and a Towbook
   cascade that ended up in SPOT.
9. **New data traps found** (§11):
   - `SA.ERS_Work_Order__c` is a reliable direct SA→WO link (400/400).
   - `ERS_Reason_for_changing_Facility__c` = "AAA Reassignment" on 76% of SAs, so it is useless.
   - Decline and rejection reasons keep only the last value.
   - `ERS_PTA__c` can be re-based at acceptance (90 → 120).
   - On Towbook calls the "last assigned-resource row" rule picks the wrong actor.
   - The existing SA report has five bugs that matter for this feature.

---

## 1. What the Call Story is

**In plain English:** for one member's call, list every step in time order: who did it, how long each stage
took against what is normal for that garage, where it got stuck, which texts the member got, and the reason for
each delay. Then give a one-paragraph verdict.

It extends the SA report and reuses its parts:
- `parse_assign_events`, the GPS, truck and candidate snapshots (`build_assign_steps`) and the photos and notes.
- It also reuses the report card's `report_card_verdicts.sa_features()` / code functions, so the story and the
  report card always agree on a call's verdict.

**Scope:** ERS only (`RecordType.Name = 'ERS Service Appointment'`). Tow Drop-Off is shown as the second leg of a
tow, but it is **never** used for response time, PTA or stuck detection.

---

## 2. Accepted inputs and resolution

Detect the input type with the rules below, in order. Every path ends at one `WorkOrder` Id plus the
**member-facing SA** (the first non-Drop-Off SA on the WO).

| # | Input looks like | Example | Query | Notes |
|---|---|---|---|---|
| 1 | `SA-\d+` or 7 digits | `SA-1074304` | `ServiceAppointment WHERE AppointmentNumber = 'SA-…'` → `ERS_Work_Order__c` | AppointmentNumber is idLookup (indexed) |
| 2 | `WO-\d+` or 8 digits with a leading 0 | `05173612` | `WorkOrder WHERE WorkOrderNumber = '05173612'` | Stored without the `WO-` prefix (search.py does the same) |
| 3 | `\d{3}-\d{8}-\d{8}` | `084-20260928-05173612` | `WorkOrder WHERE ERS_Call_Key__c = '…'` | External Id. Format = club-date-WO#. Present on all 4 golden WOs |
| 4 | other 8-digit number with no WO match | `05211381` | `WorkOrder WHERE ERS_Source_Call_ID__c = '…'` | External Id. Populated only for `Source__c` RAP (400/wk) and Call Mover (118/wk). The source club's call number |
| 5 | 15/18-char Id with prefix `08p` / `0WO` / `1WL` | | direct | Convenience for links |

**Ambiguity:** an 8-digit number is tried as a WO number first, then as a source call ID. If both match, show both
and let the user pick. `Membership_ID__c` and name search stay in `/api/search` and are not story inputs.

**WO → SAs: one query.** `ServiceAppointment WHERE ERS_Work_Order__c = :woId`.
- `SA.ERS_Work_Order__c` is populated on 10,287/10,287 ERS SAs (week of 9/21).
- It equals `ParentRecordId → WorkOrderLineItem.WorkOrderId` on 400/400 SAs checked (9/28).
- `ParentRecordId` is still the WOLI. Keep the WOLI hop only for line-item status and skill requirements.
- Never semi-join `ParentRecordId` against WO Ids. It silently returns 0.

**Legs:**
- The member-facing leg is the first SA whose `WorkType.Name` does not contain "drop".
- For a tow, the Drop-Off leg is `SA.ERS_Tow_Pick_Up_Drop_off__c`, and it is shown collapsed.
- If a WO has more than one non-drop SA (re-created or duplicate calls), show each one as its own story, in order,
  and flag `MULTI_SA`.

**Tow flag:** `WorkOrder.Tow_Call__c` (reliable, agrees with work type 99.7%).

---

## 3. Query plan (sequential, light; about 7 calls for a normal call)

| # | Query | Why |
|---|---|---|
| Q1 | Resolve the input (§2) plus WO fields: `WorkOrderNumber, CreatedDate, ERS_Submitted_Date_Time__c, Source__c, ERS_Channel_Type__c, Priority_Code__c, Tow_Call__c, SMS_Opt_In__c, Mobile_Phone__c(not displayed), Trouble_Code__c, Resolution_Code__c, Clear_Code__c, Status_Reason__c, ERS_Call_Key__c` | Header, SMS eligibility |
| Q2 | SAs on the WO: `Id, AppointmentNumber, Status, CreatedDate, WorkType.Name, ServiceTerritory.Name, ERS_Parent_Territory__c, ERS_Parent_Territory__r.Name, AAA_ERS_Account_Facility__r.Name, ERS_PTA__c, ERS_PTA_Due__c, ERS_Spotting_Datetime__c, ERS_Spotting_Number__c, ActualStartTime, ActualEndTime, ERS_Facility_Decline_Reason__c, ERS_Rejection_Reason__c, ERS_Rejected_Datetime__c, ERS_Cancellation_Reason__c, FSL__InJeopardyReason__c, Off_Platform_Driver__r.Name, Off_Platform_Truck_Id__c, ERS_Tow_Pick_Up_Drop_off__c, ParentRecordId, Latitude, Longitude` | All legs |
| Q3 | `ServiceAppointmentHistory WHERE ServiceAppointmentId IN (legs)`. **All fields**, with `Field, OldValue, NewValue, CreatedDate, CreatedBy.Name, CreatedBy.Profile.Name`, `ORDER BY CreatedDate, Id` | The story itself. About 50–110 rows per SA |
| Q4 | `AssignedResource` for the legs, plus `ServiceResource.ERS_Driver_Type__c` | Channel (S2 in metrics-spec) |
| Q5 | `SMS_Send_Log__c WHERE Work_Order__c = :wo` (if the call is on or after 2026-09-01). Otherwise `MessagingSession` by end user (§7.5) | Texts |
| Q6 | `ERS_Territory_Priority_Matrix__c WHERE ERS_Parent_Service_Territory__c = :grid` with `ERS_Spotted_Territory__r.Name, ERS_Priority__c, ERS_Worktype__c, ERS_Operating_Hours__r.Name` | Explains which garage was tried and why |
| Q7 | Only if FSL_ENGINE events exist: `FSL__Optimization_Request__c` and `Optimization_Log__c` in [first FSL event − 2 min, last + 1 min], territory or resource match | Optimizer run and trigger per reshuffle |
| Q8 | Only if a stuck segment involves a busy driver: that driver's other SAs that day (AR + Status history), plus `ResourceAbsence` and the `AssetHistory` login rows for that driver | Names the job blocking the call |
| Q9 | `Survey_Result__c WHERE ERS_Work_Order__c = :wo` | Satisfaction, if answered |
| — | Verdict and candidates: reuse the report-card snapshot for that garage-day if one exists. Otherwise run the SA report's candidate step (GPS, logins, skills) for this one SA | Avoids re-pulling GPS |

Cache: completed or canceled calls never change, so cache them for 24 h. Calls still open: 2 min.
`sf_query_all` silently stops if a page errors. Q3 can return more than 2,000 rows only for pathological SAs, so
compare it to `SELECT COUNT()` when the row count is ≥ 1,000.

---

## 4. Ordered event timeline

### 4.1 Event catalogue

Times are shown in ET. The order is by `CreatedDate`, then `Id`. Each SF save writes several rows in the same
second. Group rows with the same `CreatedDate` and the same actor into one **event**, and show the field changes
inside it.

| Event | Source (object.field) | Detection rule | Shown as |
|---|---|---|---|
| E00 Call taken | `WorkOrder.CreatedDate`, `ERS_Submitted_Date_Time__c` | always | "Call taken 14:55; SA created 2.6 min later". The member's clock starts at **SA CreatedDate / `ERS_Spotting_Datetime__c`**, because that is the PTA basis |
| E01 SA created | SAHistory `Field='created'` + CreatedBy | first row | Actor: Mulesoft (auto) or a person. Call takers have the Membership User profile, see §11 T6 |
| E02 Grid and first garage | `SA.ERS_Parent_Territory__r.Name` (grid); first `ServiceTerritory` name row (OldValue null); `ERS_Spotting_Number__c` | first rows | "Grid WM032 → 100 WNY FLEET, matrix rank 3". **`ERS_Spotting_Number__c` = the matrix `ERS_Priority__c` rank** (matched on all 4 golden calls and every cascade hop) |
| E03 Rank skipped | Q6 matrix + OperatingHours | the first garage's rank > the lowest eligible rank for the work type | "Rank 2 (063 BISON, Mon–Fri 8a–5p) was closed at 07:34". Inference: OperatingHours TimeSlots need one extra query, see Q-open 6 |
| E04 Assigned / reassigned | `ERS_Assigned_Resource__c` **name rows** (skip Id rows; NewValue null = unassign) | each row | driver, actor class (metrics-spec B4), "pick n of N" |
| E05 Optimizer run | Q7 | FSL_ENGINE event with a Completed request at 0–90 s before it (the validated window is −1/+3 min) | "In-Day run 11:45:02 (policy Copy of Highest Priority, trigger Idle Territory Optimization) moved it Marquan → Arthur" |
| E06 Dispatched | `Status` → Dispatched | each | the actor (IT System User = auto release, Membership User = dispatcher) |
| E07 Accepted / Declined / Rejected | `Status` → Accepted / Declined / Rejected | each | Declined = Towbook garage (actor `Integrations Towbook`). Rejected = an FSL driver. Reason: see E08 |
| E08 Decline/reject reason | `ERS_Facility_Decline_Reason__c`, `ERS_Rejection_Reason__c` + `ERS_Rejected_Datetime__c` | **These fields are not history-tracked and keep only the last value.** Attach the rejection reason only to the Rejected event within 60 s of `ERS_Rejected_Datetime__c`. Attach the facility decline reason only if there was exactly one Declined event | Otherwise: "reason not recorded for this hop" |
| E09 Garage change (real bounce) | `ServiceTerritory` name rows with **OldValue non-null and NewValue ≠ OldValue** (also `AAA_ERS_Account_Facility__c`) | each | "Moved 076DO → 630 BACHS by Towbook (decline cascade)" or "by Paige White". Target kind: GARAGE / SPOT / GRID (§6) |
| E10 Pull-back | `Status` → Spotted after Dispatched/Accepted/En Route | each | "Paige White pulled it back from Marquan Gates" |
| E11 En Route / On Location | `Status` → En Route / On Location | first | Arrival: §9. Towbook = this history row, never `ActualStartTime` |
| E12 PTA promised / changed | `ERS_PTA__c` history | **initial PTA = the last row written within 5 s of creation** (the first row is always a 90 placeholder: 90 → 60/75 in the same second). **Final PTA** = current value | If initial ≠ final, show both deadlines (§11 T4) |
| E13 Jeopardy | `FSL__InJeopardy__c`, `FSL__InJeopardyReason__c` | → true | "Flagged PTA Overdue at 12:45" |
| E14 Address change | `Street`, `Latitude`, `Longitude` rows after creation | each | "Address corrected by Domingo Santiago" |
| E15 Note | `ServiceNote` row | each | "Towbook added a note". The history keeps no text, so show the current `SA.ServiceNote` |
| E16 SMS | §7 | each | Interleaved with the events |
| E17 End | first terminal Status: Completed, Unable to Complete, Cancel Call - Service (Not) En Route, Canceled, No-Show | first | Plus `ERS_Cancellation_Reason__c` and WO `Resolution_Code__c` / `Clear_Code__c`. For a cancel, also say where the call was at that moment (garage / SPOT / grid; with or without a driver) |
| E18 Survey | `Survey_Result__c.ERS_Overall_Satisfaction__c` | if present | Case-insensitive "Totally satisfied" |

Noise to hide (keep it in a raw view): SchedStart/End churn, SLR geolocation, StateCode/CountryCode,
ActualDuration, the `FSL__Auto_Schedule__c` true→false flip and the `ERS_For_Spotting__c` flip.

### 4.2 Final decision maker and channel per hop

- **FSL platform:** the final decision = the last `ERS_Assigned_Resource__c` name row (metrics-spec S4).
- **Towbook: this rule breaks.**
  - In SA-1067245 the last name row is "000-ST Spot", set by a dispatcher. It was cleared at 11:57 and never set
    again, and the AR row was deleted.
  - For a Towbook leg, the final decision = the `Status → Accepted` row by `Integrations Towbook`.
  - The person who did the work = `Off_Platform_Driver__c`.
- **Channel per hop:** a call can cross channels (the Towbook golden call went 076DO Towbook → 630 Towbook → 642
  On-Platform driver → SPOT → 076DO Towbook).
  - Each assignment event gets a channel from the driver's `ERS_Driver_Type__c`. `Towbook-<code>` placeholders =
    Towbook. `000-* Spot` placeholders = SPOT.
  - The call's channel = the channel of the leg that arrived. Never use `ERS_Dispatch_Method__c`: it is a formula
    on the facility's current method.

---

## 5. "Stuck" detection

### 5.1 Segments (one row per contiguous stretch, so repeats are counted separately)

| Segment | From → to | Who owns the wait |
|---|---|---|
| S1 Waiting for a garage/driver | SA created or pull-back → first Assigned | system / dispatcher |
| S2 Assigned, not released | Assigned → Dispatched | optimizer / auto-release / dispatcher |
| S3 Dispatched, not accepted | Dispatched → Accepted (or En Route) | driver / garage |
| S4 Accepted, not rolling | Accepted → En Route | driver / Towbook garage queue |
| S5 Driving | En Route → On Location | driver / distance |
| S6 On scene | On Location → terminal | driver / job |
| S7 Rejected or declined, nobody acting | Rejected/Declined → next Spotted/Assigned | **dispatcher** (no automatic cascade after an FSL driver rejects) |
| S8 Parked in SPOT | territory = `000-* SPOT` → next garage | dispatcher |
| S9 In a grid zone | territory = grid → next garage | system |

### 5.2 Baselines (what is "normal")

- **Key:** garage × channel × segment × 4-hour ET block (00, 04, …, 20) × weekday/weekend, using the last 56 days.
  - Below n = 30, fall back to garage × channel × segment.
  - Below that, use channel-wide.
  - **Below that, for S7, S8 and S9 only:** the segment pooled over all channels and garages. Approved 2026-10-04 (O5).
    These are dispatcher-owned waits, so the channel does not change who owns them. Other segments never pool across
    channels.
  - Never rank or flag on n < 30 without saying so.
  - First data, from the 20 ROI-sample snapshots (`roi-baseline.md`; `validation/roi/s789.py`):
    - S7 pooled: n = 76, p50 0.0, p75 2.0, p90 7.3, p95 14.7 (WNY Fleet n 14, 076DO On-Platform n 60).
    - S8: n = 20 (< 30), so floors only.
    - So golden 10.4's 48.1 min S7 is CRITICAL at level 4.
- **S3 is split by driver state at dispatch:** BUSY (en route or on scene on another SA) vs FREE. Use B5 open jobs
  from metrics-spec.
- **S6 is keyed by work type** (battery and tire differ).
- Precompute the baselines nightly in the report-card backfill (architecture §12). Never compute them at story time.

**Indicative baselines** (to sanity-check the build, not to configure it):

WNY 100 Fleet, 9/21–9/28 (n = 684 SAs, minutes):

| Segment | n | p50 | p75 | p90 | p95 |
|---|---|---|---|---|---|
| S1 created → first Assigned | 684 | 0.2 | 0.3 | 2.4 | 4.2 |
| S2 Assigned → Dispatched | 671 | 2.0 | 12.5 | 33.7 | 45.1 |
| S3 Dispatched → Accepted, driver FREE | 482 | 3.9 | 15.1 | 40.1 | 53.0 |
| S3 Dispatched → Accepted, driver BUSY | 152 | 22.5 | 40.2 | 58.2 | 77.9 |
| S4 Accepted → En Route | 629 | 0.5 | 3.0 | 6.6 | 12.3 |
| S5 En Route → On Location | 597 | 18.1 | 26.4 | 36.0 | 44.0 |
| S6 On Location → Completed | 515 | 19.9 | 34.3 | 51.5 | 63.7 |
| S7 time in Rejected | 13 | 3.5 | 5.2 | 6.5 | 12.1 |
| created → On Location | 597 | 45.1 | 66.3 | 91.6 | 112.8 |

S3 p90 by hour block (all drivers): 04h 38 · 08h 43 · 12h 43 · 16h 51 · 20h 47.

076DO Towbook, 9/24 (n = 229 non-drop SAs):

| Segment | p50 | p90 |
|---|---|---|
| Time in Dispatched | 8.1 | 86.6 |
| Accepted → En Route | 34.5 | 137.2 |
| En Route → On Location | 20.9 | 45.2 |
| created → On Location | 72.1 | 171.1 |

Towbook garages accept first and queue the job internally, so S4 is their real queue. S4 must have its own
Towbook baseline. Never compare it with Fleet.

### 5.3 Rules (`cs1`, thresholds are config)

A segment is:
- **SLOW** if minutes > baseline p75.
- **STUCK** if minutes > max(baseline p90, floor).
- **CRITICAL** if minutes > max(p95, floor), **or** the original PTA deadline (`due_initial`, §4.4 of the
  architecture) passed during the segment **and** the segment is at least SLOW **and** it is a pre-arrival segment
  (S1–S5, S7–S9).
  - Why the two guards: without them, a normal 2-minute S4 that happens to straddle the deadline would read CRITICAL
    and blame the wrong stage.
  - S6 (on scene) is after arrival, so the PTA cannot pass "during" it in any meaningful way.
  - (O3, 2026-10-04; golden 10.3 corrected to CRITICAL.)

Floors (minutes) stop tiny baselines from flagging noise: S1 5, S2 15, S3 15, S4 10, S5 45, S6 60, S7 10, S8 10,
S9 5.

S7, S8 and S9 are always at least SLOW, because a call in those states has no owner.

---

## 6. "Stuck in the grid": what "grid" means here

**Evidence:**
- 228 `ServiceTerritory` rows with `AAA_ERS_Type__c = 'Closed'` are named `WM001…`, `WR…`, `CM…`, `CR…`, `RM…`,
  `RR…` (2 letters + 3 digits).
- `FSL__Polygon__c` has 228 rows, and **all 228 point to these territories**. So "grids" in `/api/map/grids` are
  exactly these zones.
- `SA.ERS_Parent_Territory__c` holds the call's zone (WM032, WM014, WM025, WM003 on the golden calls).
- `ERS_Territory_Priority_Matrix__c` (`ERS_Parent_Service_Territory__c` = zone → `ERS_Spotted_Territory__c` =
  garage, `ERS_Priority__c` = rank, `ERS_Worktype__c`, `ERS_Operating_Hours__c`) ranks the garages per zone. Every
  zone's last resort is its region's `000- <region> SPOT` facility at rank 10. For example: WM003 → 076DO (2), 630
  BACHS (3), 642 AUTO WRENCH (4), 000- WNY M SPOT (10), 202 ELLMAN'S (11, tows).
- FSLAPP code already treats `XX###` names as "grid zones" (`dispatch_shared._is_real_garage`). The Watchlist
  already flags a facility starting with `000` as "Call Not Assigned".

**Candidates for "stuck in the grid":**

| # | Meaning | Detection | 9/28 org-wide (4,538 territory-history rows, 1,800 SAs) | End-state, week of 9/21 |
|---|---|---|---|---|
| **G1 (recommended)** | Cascade exhausted: the call is parked in a SPOT bucket with no real garage | `ServiceTerritory` / `AAA_ERS_Account_Facility__c` NewValue starts with `000-` or contains `SPOT`, or the assigned resource is a `000-* Spot` placeholder | **76 SAs (95 entries)**. Moved in by Integrations Towbook 41, IT System User 36, dispatchers about 18. Time there: p50 6.0, p90 27.2, max 61.3 min. 90 of 95 left for a garage | **49 SAs ended in SPOT; 48 were "Cancel Call - Service Not En Route"** |
| G2 | The SA's territory is a raw grid zone (no facility resolved) | `ServiceTerritory` NewValue matches `^(WM\|WR\|CM\|CR\|RM\|RR)\d{3}$` | 12 SAs (15 entries), p50 1.1, max 9.7 min | 20 ended in a grid zone (14 canceled, 6 completed) |
| G3 | The zone has no matrix rows ("SPOT - UNASSIGNED GRIDS" facility) | territory = `SPOT - UNASSIGNED GRIDS` | 0 on 9/28 | — |
| G4 | Mis-gridded: the SA's GPS point is outside the polygon of its `ERS_Parent_Territory__c` | point-in-polygon against `FSL__Polygon__c.FSL__KML__c` | not measured | — |

**What the story shows:**
- G1 and G2 become segments S8 and S9 (always flagged).
- G4 is a data-quality note ("this address plots in WM031 but was spotted to WM032").
- The story always shows the call's grid and the matrix ladder (which ranks were tried, skipped or never reached).

**Ask the user:** when dispatchers say "stuck in the grid", do they mean the `000 SPOT` queue (G1), a call with no
garage at all (G2), or something they see on the Dispatcher Console Gantt? The Gantt is not in the data.

---

## 7. SMS

### 7.1 Sources

| What | Object.field | Coverage |
|---|---|---|
| Attempt log (what, when, outcome) | `SMS_Send_Log__c`: `Work_Order__c`, `Service_Appointment__c`, `Message_Definition__c`, `Source_Flow__c`, `Outcome__c`, `Error_Message__c`, `Checkpoint_Minutes__c`, `Sent_At__c`, `Messaging_End_User__c`, `MEU_Resolution__c` | 2026-09-01 20:08 UTC onward. 133,104 rows |
| Hand-off to the SMS channel | `MessagingSession` (`Origin='TriggeredOutbound'`, `ChannelName='ERS SMS Messaging Channel'`, `MessagingEndUserId`, `CreatedDate`) | 2024-12-13 onward. 131,861 in Aug 2026 |
| Carrier delivery / read | `ConversationEntry.MessageStatus`, `MessageDeliverTime`, `MessageReadTime` | **0 rows readable by the API user** for sessions known to exist |
| Delivery errors | `MessagingDeliveryError` | 0 rows since 9/1 (either none happened or it is not visible; unconfirmed) |
| Consent | `WorkOrder.SMS_Opt_In__c`; `MessagingEndUser.MessagingConsentStatus` (OptedOut / ImplicitlyOptedIn / ExplicitlyOptedIn / DoublyOptedIn) | current values only |

### 7.2 Sent vs delivered vs failed (what we can honestly say)

| Status shown | Rule |
|---|---|
| **Sent to SMS channel** | `Outcome__c = 'Sent'`. A matching `MessagingSession` exists within ±10 s (8/8 on SA-1074304; week of 9/21: 35,468 Sent rows vs 36,367 sessions) |
| **Not sent: <reason>** | `Outcome__c` = Skipped-No-MEU / No-Consent / No-Phone / No-Link / No-AR / No-Channel / Not-Eligible, or Failed with `Error_Message__c`. All time: Sent 132,076; Skipped-No-MEU 992; Skipped-Not-Eligible 32; Failed **0** |
| **Delivered** | **Not available.** Say so on screen: "delivery to the phone is not visible to FleetPulse". Zero Failed in 133k rows is too clean: "Sent" means the flow handed the text off without error, not that a phone received it |

### 7.3 Message catalogue (week of 9/21, Sent)

| Label in the story | `Message_Definition__c` (flow) | Fires when | n/week |
|---|---|---|---|
| Call received | `Message_1_Sent_upon_initial_call_placement` (Send_SMS_on_SA_Insert) | SA insert | 5,575 |
| Garage + PTA | `Facility_Assigned_WO_Id_PTA_SMS` (SA_Insert / Send_Immediate_SMS) | insert, or Towbook acceptance | 4,622 |
| Still working on it (30/50/80 min) | `Message_3_When_Call_is_not_accepted_by_a_driver` (`AAA_ERS_Sent_SMS_when_call_is_not_accepted_by_a_driver`, `…_50mins`, `…_80mins`) | see §7.4 | 2,277 |
| Driver accepted, update (30/60/90 min) | `Message_4_Sent_when_call_is_accepted_by_a_driver` | Accepted for 30/60/90 min | 906 |
| Driver en route | `Message_1_Sent_upon_when_driver_is_enroute`, `Message_2a…w_o_link`, `Message_6…battery…enroute`, `Message_9…Tire_Call` | En Route | 6,705 |
| Driver on location | `Message_5_Sent_when_system_or_driver_marks_On_Location` | On Location | 5,016 |
| Tow drop-off leg | `Message_9_…Tow_Drop_off`, `Message 9a…w/o tracking link` | drop-off En Route | 2,375 |
| Call completed | `Message_7_…member_is_084`, `Message_8_…completes` | Completed | 1,653 |
| Survey | `Survey_IC_SMS` | Completed | 2,728 |
| Opt-in confirmation | `Opt_in_Confirmation` | opt-in | 3,063 |
| **Not to the member: exclude** | `ERS_Send_SMS_Notification_to_Dispatchers_Contacts` (new SA spotting) | dispatcher contacts | 548 |

### 7.4 Why a text did NOT go out (deterministic)

Check these in order:
1. `WorkOrder.SMS_Opt_In__c = false` → "Member not opted in to texts. No texts and no survey." (SA-1073520, a RAP
   call.) Never present this as a member choice in correlations, because only opted-in members are ever surveyed.
2. A log row with `Skipped-*` / `Failed` → show the reason verbatim.
3. **Timer cancelled.**
   - The "still working on it" flows are record-triggered on SA update, entry `Status = Assigned OR Dispatched`,
     "only when the record changes to meet the criteria". They have a scheduled path at +30/+50/+80 min from that
     moment.
   - **The path's own status re-check does nothing.** Decision `Check_SA_Status` uses
     `(1 OR 2 OR 3 OR 4 OR 5) AND 6 AND 7 AND 8`, where 1–5 are `Status ≠ Accepted / En Route / On Location /
     Completed / Unable to Complete`. An OR of "not equal" checks is always true.
   - The real guard is the platform: a scheduled path is dropped when the record stops meeting the entry criteria.
     The outcome is the same as the old wording; only the mechanism is different.
   - Flow owner: change the OR to AND as a safety net.
   - So the clock starts when the SA first enters Assigned/Dispatched. It keeps running through reassignments, and it
     resets whenever the status leaves {Assigned, Dispatched} (Declined, Rejected, Spotted).
   - Verified on SA-1074304: Assigned 11:44:23, texts at 12:14:52 (+30) and 12:34:50 (+50).
   - Verified on SA-1067245: the status left Assigned/Dispatched after 0.6, 0.6, 6.0 and 25.9 min of each run,
     so no timer ever completed.
   - Rule: if the call was un-accepted for ≥ 30 min and no Message_3 was sent, the story says "No 'still working'
     text: the timer restarted N times because the call kept being declined, rejected or re-spotted."
   - *Source:* local metadata `FSL/force-app/main/default/flows/AAA_ERS_Sent_SMS_*` (file dated 2026-08-13).
   - **Verified against production 2026-10-04** (O7; Tooling API, read-only; `validation/roi/flows_prod.py`).
   - Active versions:
     - 30 min v4 (2026-09-09),
     - 50 min v4 (2026-09-09),
     - 80 min v5 (2026-09-15),
     all by Kathleen Osuch.
   - **Same as the 8/13 metadata** on everything this rule depends on:
     - object, after-save on Update,
     - entry filter `Status = Assigned OR Dispatched`,
     - "only when changed to meet criteria",
     - scheduled paths +30/+50/+80 min from the trigger event,
     - every decision.
   - Production differs in two ways:
     - **Logging actions were added** (`ERS_SMS_Service` → `SMS_Send_Log__c`: Sent / Skipped-No-MEU / Skipped-No-Channel).
     - The 80-minute flow's phone check is **fixed in production**: local has `ERS_Work_Order__c EqualTo False`, which
       could never pass; production has `IsNull False`. Before v5 (2026-09-15) the 80-minute text may never have sent.
       That is not verifiable, because logging arrived in the same version.
   - The always-true re-check above is in production too.
4. No row and no reason → "No text logged for this step."

### 7.5 Calls before 2026-09-01

There is no SMS log for these calls.
- Find the member's `MessagingEndUser` via `MessagingPlatformKey` = `WorkOrder.Mobile_Phone__c` (normalised;
  Ruby: verify the key format on 5 samples).
- List `MessagingSession` rows (TriggeredOutbound) between WO creation and closed + 1 h.
- Label each one "Text sent (type unknown)".
- Optional: infer the type when a session is within 5 s of a status change (e.g. On Location). Mark it "inferred".
- Banner: "Detailed text log starts 1 Sep 2026."
- Never invent message types or delivery.

---

## 8. "Why": deterministic causes (the AI only narrates)

Each cause has a trigger (data rule), the evidence to cite, and where available a verdict code from metrics-spec
§7 and a lever from §12. A story shows every cause that fired, in time order. The **headline cause** is the
report-card primary verdict for the call. For Towbook, use the first CRITICAL segment instead.

| Code | Trigger (data) | Evidence to cite | Verdict / lever |
|---|---|---|---|
| C01 RANK_SKIPPED | first garage rank > the lowest eligible rank for the work type | skipped garage + operating hours | context |
| C02 TOWBOOK_DECLINE | Status → Declined by Integrations Towbook | garage, seconds from offer to decline (≤ 60 s = "declined within a minute, consistent with an automatic rule"), reason if attributable (E08), next rank tried | L08 |
| C03 DRIVER_REJECT | Status → Rejected by the assigned driver | `ERS_Rejection_Reason__c` (E08) | context |
| C04 ORPHANED_AFTER_REJECT | S7 ≥ SLOW | minutes with no owner, who finally acted | **L08**; Watchlist "Call Not Assigned - Rejected" |
| C05 PARKED_IN_SPOT | S8 present | SPOT name, minutes, who parked and who rescued it; flag when it is a different region's SPOT than the matrix's | L08 / L13 |
| C06 IN_GRID | S9 present | grid name, minutes | data / matrix review |
| C07 OPTIMIZER_CHURN | ≥ 3 picks before dispatch | each pick with its run (E05) and trigger reason | flag OPTIMIZER_CHURN → L05 |
| C08 SLOW_RELEASE | S2 > 10 min (r1) or STUCK | who finally released | flag SLOW_RELEASE → L05 |
| C09 QUEUED_BEHIND_JOB | S3 with the driver BUSY and ≥ SLOW | the blocking SA number, its on-scene minutes vs the S6 norm for its work type | CAPACITY_SHORT / STACKED / LATE_DESPITE_CAPACITY context |
| C10 NO_ACCEPT_FREE_DRIVER | S3 with the driver FREE, logged in, not absent, and ≥ SLOW | login window, absence check | L09; FSL does not record why a driver did not accept |
| C11 PULLBACK | E10 | actor; the C10/C09 that preceded it; minutes lost (first dispatch → re-dispatch) | **BOUNCED** → L06 |
| C12 INBOUND_CASCADE | an E09 move into the final garage from another garage | minutes spent before the move | **INBOUND_CASCADE** → L08 |
| C13 DECISION_QUALITY | report-card verdict at the final decision | pick miles / open jobs vs the closest free qualified driver | **STACKED / FAR_PICK / LATE_DESPITE_CAPACITY / LATE_EXECUTION / CAPACITY_SHORT / GOOD** → L01–L04, L07, L09, L12 |
| C14 LONG_DRIVE | S5 ≥ STUCK | miles (straight line) if GPS exists | L09 / FAR_PICK |
| C15 LONG_ON_SCENE | S6 ≥ STUCK for the work type | — | L09 |
| C16 PTA_REBASELINED | initial PTA ≠ final PTA | both deadlines, the actor of the change, met/missed under each | context (§11 T4) |
| C17 MEMBER_NOT_UPDATED | ≥ 30 min un-accepted with no update text, or no text at all | §7.4 reason | flow owner |
| C18 CANCELED_WHILE_STUCK | terminal = cancel while S7/S8/S9 was open, or with no driver | cancel reason, where the call was | L08 |
| C19 DISPATCHER_SPOT_REGION | a dispatcher used a SPOT that is not in the zone's matrix | matrix SPOT vs the one used | coaching |

**Policy diagnosis:** when C07, C08 or C13 fires with actor FSL_ENGINE or INTEGRATION, attach the matching
metrics-spec §10A.2 row as "consistent with …" (for example, Minimize Travel weight 10 vs ASAP 60,000/120,000 for
FAR_PICK by FSL). Never write "caused by".

**AI rules:**
- The narrator receives only: the event list, the segments with baselines, the fired causes and evidence, the
  verdict and the SMS rows.
- It may not add a cause, number or name that is not in that input.
- Every sentence keeps the event Ids it came from, so the UI can highlight them.
- If no cause fired: "No delay found; the call ran within this garage's normal times."
- Show the deterministic bullet list first. The AI paragraph is optional and below it.

---

## 9. Channel handling

| | Fleet | On-Platform Contractor | Towbook (off-platform) |
|---|---|---|---|
| Who picks the driver | Mulesoft / FSL optimizer / dispatcher. Visible per event | same; plus garage dispatchers (Partner Community User, e.g. Todd Kryszak) | the garage, inside Towbook. SF sees only `Towbook-<code>` |
| Arrival | `ActualStartTime` (matches history On Location: median 0.0 min) | same | **SAHistory first `Status → On Location`**. `ActualStartTime` is fake (bulk midnight sync) or empty (empty on SA-1067245) |
| Accept | driver, Status Accepted | driver | `Integrations Towbook` writes Accepted; PTA may be re-based then |
| S3 / S4 meaning | waiting for the driver | waiting for the driver; "idle" is an upper bound (they may be doing non-AAA work) | S3 = garage acknowledging; S4 = garage queue |
| Candidate / verdict | full | full | NOT_GRADED_TOWBOOK; still show the cascade, stuck and SMS |
| Driver name | AR / history | AR / history | `Off_Platform_Driver__c`, `Off_Platform_Truck_Id__c` |
| Actor classes | metrics-spec B4. Add: actor name = the SA's driver → DRIVER, even with a Membership User profile | same | `Towbook Integrations` profile → TOWBOOK_SYNC |

---

## 10. Golden examples (expected story output; Tamy's acceptance tests)

All times are ET. "min" = minutes from SA creation unless stated otherwise. Baselines are the indicative ones in §5.2.

### 10.1 GOOD: SA-1073520 · WNY 100 Fleet · Mon 2026-09-28

Ids: SA `08pPb000009e5a5IAA` · WO `05172864` (`0WOPb00000KQNezOAH`) · call key `084-20260928-05172864` · source call
`05211381` (RAP) · WOLI `1WLPb00000921pFOAQ` · Tire · grid WM032.

1. 07:34:24. RAP call received; SA created by Mulesoft. Grid WM032 → **100 WNY FLEET, matrix rank 3**. Rank 2 (063
   BISON AUTOMOTIVE, Mon–Fri 8a–5p) was closed at that hour (C01, inferred from operating hours). PTA 60 min (due
   08:34).
2. 07:34:31. Assigned to **Arthur Yates Jr.** by Mulesoft Integration, 7 s after creation. He was the closest
   qualified driver, 8.3 mi, no open jobs.
3. 07:35:01. Released (Dispatched) by IT System User, 0.5 min (S2 normal).
4. 07:37:26. Driver accepted in 2.4 min. 07:38:17 En Route.
5. 08:08:18. On Location. Drive 30.0 min (S5 p75 26 / p90 36: SLOW, not stuck). Arrival at 33.9 min vs PTA 60:
   **met, 26 min early**.
6. 08:17:14. Completed (8.9 min on scene). Resolution G102.
7. Texts: **none. `SMS_Opt_In__c = false`**, so the member was never texted or surveyed (C17 reason 1).
8. Verdict **GOOD**; flag BYPASSED_OPTIMIZER. No stuck segments.

### 10.2 BOUNCED: SA-1074927 · WNY 100 Fleet · 2026-09-28

Ids: SA `08pPb000009eonJIAQ` · WO `05174140` (`0WOPb00000KRA4bOAH`) · key `084-20260928-05174140` · Battery ·
grid WM014 → 100 (rank 2) · priority @H · PTA 75 (due 16:13).

1. 14:55:46. Call taken (WO). 14:58:20: SA created by **Katie Kelsey** (call taker, Membership User profile; not a
   dispatcher), 2.6 min later.
2. 14:58:21. Texts: Call received + Garage/PTA. Both Sent.
3. 15:00:49. FSL optimizer (Platform Integration User) assigned **Jacob Schaich**. Run: RSO for Jacob at 15:00:14
   (Past-Start SA Nudge logged 15:00:13).
4. 15:01:53. FSL In-Day run (15:00:54) moved it to **Marquan Gates**. 15:02:12: released by IT System User.
5. 15:02:12 → 15:17:52. **Dispatched, not accepted: 15.7 min.** Marquan was logged in (truck 100 92B3, 11:33–16:33),
   had no absence and no other open job (his last job, SA-1074610, completed 14:51). For a free driver that is
   about the 75th percentile: slow, not extreme (C10).
6. 15:17:52. **Paige White pulled it back** from Marquan (Dispatched → Spotted) (C11, **BOUNCED**).
7. 15:18:42. Paige assigned **Antonio Hatch Jr.** (2.8 mi, 1 open job; Jacob was 2.7 mi). Re-dispatched 15:18:53.
   **16.7 min lost** between the first dispatch and the re-dispatch.
8. 15:27:29. Accepted (8.6 min). 15:27:41 En Route. Texts: en route ×2.
9. 15:37:45. On Location (drive 10.1 min). Arrival at 39.4 min vs PTA 75: **met**. Text: on location.
10. 16:34:12. Completed. On scene 56.5 min, battery. That is **SLOW**, not stuck: it is above the battery S6 p75 (40.8)
    and just above p90 (56.3), but under the 60-min S6 floor. **C15 does not fire.** (O2, corrected 2026-10-04: the
    earlier text used the all-work-type p90 51.5 and ignored the floor. S6 is keyed by work type, §5.2.) Survey text sent
    16:34:17; no response.
11. Verdict **BOUNCED** (3 picks; flags BYPASSED_OPTIMIZER, HUMAN_FINAL). Lever L06 (pull-back review). FSL does not
    record why Marquan did not accept.

### 10.3 CAPACITY_SHORT / late: SA-1074304 · WNY 100 Fleet · 2026-09-28

Ids: SA `08pPb000009eT1JIAU` · WO `05173612` (`0WOPb00000KQpubOAD`) · key `084-20260928-05173612` · Battery · grid
WM025 → 100 (rank 2) · Source DRR · PTA 60 (due 12:44).

1. 11:43:09. Call taken. 11:44:12: SA created by Mulesoft. 11:44:13: texts Call received + Garage/PTA.
2. 11:44:23. Mulesoft assigned **Marquan Gates**.
3. 11:45:15. FSL In-Day run (11:45:02, trigger Idle Territory Optimization) moved it to **Arthur Yates Jr.**
4. 11:50:43. FSL In-Day run (11:50:18–19; Past-Start SA Nudge) moved it to **Isaiah Carter-Faires**. 3 picks in
   6 min (C07, OPTIMIZER_CHURN).
5. 11:52:55. **Lynn Pilarski** released it to Isaiah, who had been on scene at **SA-1074246** since 11:49.
6. 11:52:55 → 13:01:39. **Dispatched, not accepted: 68.7 min. CRITICAL.**
   - It is above the busy-driver p90 (58.2), and **the original PTA 12:44:11 passed during the segment** (§5.3).
   - O3, corrected 2026-10-04: the earlier text said STUCK, which ignored `critical_if_pta_passed`.
   - Cause C09: Isaiah was on scene at SA-1074246 (battery) for **72 min**. Against the battery S6 norm (p90 56.3,
     p95 73.5) that is STUCK.
   - He accepted this call the minute he finished.
7. 12:14:52 and 12:34:50. Texts "still working on it" (Message_3), sent at Assigned + 30 and + 50 min.
8. 12:44:11. PTA passed. 12:45:49: FSL flagged In Jeopardy, PTA Overdue.
9. 13:01:43. En Route. 13:18:38: On Location (drive 16.9 min). Arrival at 94.4 min vs PTA 60: **34 min late**.
10. 13:25:24. Completed. Texts: en route ×2, on location, completed.
11. Verdict **CAPACITY_SHORT**. At the decision, the closest qualified driver (Marquan, 2.3 mi) was busy, no free
    qualified driver was nearby, and no qualified driver went idle ≥ 10 min while the call waited (no
    MISSED_REBALANCE). Lever L07 (capacity in this hour block). Secondary: long on-scene time on the previous job
    (L09).

### 10.4 Towbook cascade + SPOT: SA-1067245 · 076DO · Thu 2026-09-24

Ids: SA `08pPb000009bEurIAE` (Tow Pick-Up) · Drop-Off SA-1067246 `08pPb000009bEusIAE` · WO `05164342`
(`0WOPb00000KLEKbOAP`) · key `084-20260924-05164342` · `Tow_Call__c = true` · grid WM003 · Source DRR.

1. 10:33:58. Call taken. 10:35:49: SA created by Mulesoft. Grid WM003 → **076DO (rank 2)**, offered to
   Towbook-076DO. PTA 90 (due 12:05). 10:35:53: text "Call received".
2. 10:36:22. **076DO declined via Towbook in 33 s** (C02) → cascaded to rank 3 **630 BACHS TOWING** (offered
   10:36:30).
3. 10:37:06. **630 declined in 36 s** (C02) → cascaded to rank 4 **642 AUTO WRENCH CONNECTION**.
4. 10:37:21. Assigned to **Anthony Tabb Jr** (642, On-Platform contractor driver) by IT System User. 10:41:01:
   Dispatched.
5. 10:43:20. **Driver rejected: "Out of Area"** (C03; reason from `ERS_Rejection_Reason__c`, rejected-datetime
   10:43:18).
6. 10:43:20 → 11:31:24. **Rejected, nobody acting: 48.1 min. CRITICAL** (S7 norm p90 6.5). The call was not
   cascaded to the next rank automatically (C04). 11:04: Towbook added a note.
7. 11:31:45. Dispatcher **Domingo Santiago** moved it to **000- ST SPOT**, the SPOT queue. 11:32:10: "dispatched" to
   the SPOT placeholder. WM003's matrix SPOT is 000- WNY M SPOT, so a different region's bucket was used (C05,
   C19).
8. 11:57:51. Domingo moved it back to **076DO** (26 min in SPOT). 11:58:07: **076DO accepted via Towbook and changed
   PTA 90 → 120** (C16). 11:58:08: first Garage/PTA text, **82 min after the call** (C17: no "still working" text,
   because the timer reset 4 times).
9. 12:13:36. En Route (Towbook accept → en route 15.5 min).
10. 12:20:44. **On Location (from SAHistory; `ActualStartTime` is empty)**. Arrival at 105 min.
    - Against the **original PTA 90**: missed by 15 min.
    - Against the **re-based PTA 120** (`ERS_PTA_Due__c` 12:35): met.
    - Show both.
11. 12:32:36. Pick-up completed. Driver **Adam Lucas**, truck 076DO-287862. The drop-off leg finished about 15:04
    (completed text 15:04:43).
12. Verdict **NOT_GRADED_TOWBOOK**. Headline cause = C04. Levers: L08 (auto-cascade or alert on driver rejection;
    priority-matrix review), plus the SMS timer gap for the flow owner.
13. Trap check: the last `ERS_Assigned_Resource__c` name row = "000-ST Spot" by Domingo. Under §4.2 the final
    decision must be Towbook's acceptance, not that row.

---

## 11. Data traps and existing-code issues (found in this work)

| # | Trap | Evidence | Rule |
|---|---|---|---|
| T1 | `SA.ERS_Work_Order__c` is a reliable direct WO link | 10,287/10,287 populated; 400/400 = WOLI.WorkOrderId | use it for WO → SAs |
| T2 | `ERS_Reason_for_changing_Facility__c` is a default value | "AAA Reassignment" on 7,853/10,287 (76%), including never-moved calls | never show it |
| T3 | Decline/rejection reasons keep only the last value and are not history-tracked | single values on SA-1067245 after 3 hops | E08 attribution rule |
| T4 | PTA can be re-based at Towbook acceptance (90 → 120), and `ERS_PTA_Due__c` follows the new value | SA-1067245 | show the initial and final promise; Q-open 3 |
| T5 | On Towbook calls the last assigned-resource name row can be a dispatcher's SPOT placeholder | SA-1067245 | §4.2 |
| T6 | SA creators include call takers with the Membership User profile | Katie Kelsey on SA-1074927 | actor class for `created` = CALL_TAKER, unless they also make an assignment |
| T7 | `ERS_Spotting_Number__c` = matrix rank | all golden hops | use it for the matrix ladder |
| T8 | Optimizer runs carry no SA Id (`Optimization_Log__c.Service_Appointment_Id__c` was empty on all 358 WNY rows on 9/28) | Q7 | attribute by time window and resource |
| T9 | 0 SMS failures in 133k rows | §7.2 | "Sent" ≠ delivered |

**Existing SA report (`routers/sa_report.py`, `sa_report_timeline.py`): fix before reuse (Ruby):**
1. The history query selects `NewValue` but **not `OldValue`**. The Towbook cascade code reads `OldValue`, which is
   always None, so it picks the first differing territory Id rather than the real origin. Real bounces cannot be
   shown.
2. The history field list misses `created`, `AAA_ERS_Account_Facility__c`, `ERS_Spotting_Number__c`,
   `FSL__InJeopardy*`, `Street`/`Latitude` and `ServiceNote`.
3. `_STATUS_LABEL` maps **Accepted → "En Route"**. That merges S3 with S4 and hides Towbook's real queue (S4 p50 34.5
   min on 076DO).
4. `_build_sa_summary.response_min` uses `ActualStartTime` for every channel, so the Towbook response time and the
   narrative's PTA verdict are wrong or empty.
5. `is_towbook` / `garage_type` come from the `ERS_Dispatch_Method__c` formula (the facility's current method),
   which relabels history (076DO's August calls).

Also: `is_human` = Membership User profile catches call takers and drivers (metrics-spec S12), and `sf_parallel` is
used where the guidance says sequential (Dan to decide).

---

## 12. Config (`cs1`)

```jsonc
{
  "rules_version": "cs1",
  "inputs": { "sa": "^(SA-)?\\d{7}$", "wo": "^(WO-)?0\\d{7}$", "call_key": "^\\d{3}-\\d{8}-\\d{8}$",
              "source_call_id_field": "ERS_Source_Call_ID__c" },
  "event_group_window_sec": 0,
  "pta": { "initial_window_sec": 5, "skip_le": 0, "skip_ge": 999 },
  "optimizer_attribution": { "before_sec": 90, "after_sec": 0, "log_match_sec": 10 },
  "decline_auto_sec": 60,
  "reason_attach_sec": 60,
  "baseline": { "lookback_days": 56, "hour_block": 4, "split_weekend": true, "min_n": 30,
                "fallback": ["garage_channel_segment", "channel_segment"],
                "pooled_all_channels_segments": ["S7", "S8", "S9"],   // level 4, O5 approved 2026-10-04
                "s3_split_by_driver_state": true, "s6_by_work_type": true },
  "severity": { "slow": "p75", "stuck": "p90", "critical": "p95",
                "critical_if_pta_passed": { "enabled": true, "pta_basis": "initial", "min_severity": "SLOW",
                                            "segments": ["S1","S2","S3","S4","S5","S7","S8","S9"] } },
  "floors_min": { "S1": 5, "S2": 15, "S3": 15, "S4": 10, "S5": 45, "S6": 60, "S7": 10, "S8": 10, "S9": 5 },
  "always_flag": ["S7", "S8", "S9"],
  "grid": { "zone_regex": "^(WM|WR|CM|CR|RM|RR)\\d{3}$", "spot_prefixes": ["000-"], "spot_contains": ["SPOT"] },
  "sms": { "log_start_utc": "2026-09-01T20:08:44Z", "session_match_sec": 10,
           "exclude_definitions": ["ERS_Send_SMS_Notification_to_Dispatchers_Contacts"],
           "not_accepted_checkpoints_min": [30, 50, 80], "not_accepted_entry_statuses": ["Assigned", "Dispatched"] },
  "cache_ttl_sec": { "closed": 86400, "open": 120 }
}
```

---

## 13. Response shape (proposal for Dan)

`GET /api/call-story?q=<input>` returns:
- `resolution` {input_type, wo, legs[]}
- `header` {member-safe fields only, grid, matrix_ladder[], channel_path[]}
- `pta` {initial, final, due_initial, due_final, met_initial, met_final}
- `events[]` {id, ts, kind, actor, actor_class, fields[], channel}
- `segments[]` {kind, from, to, minutes, baseline{p50,p75,p90,p95,n,key}, severity}
- `sms[]` {ts, label, outcome, reason}
- `causes[]` {code, event_ids[], evidence{}, verdict_code?, lever?}
- `verdict` {primary, flags[]} (from report_card_verdicts)
- `data_notes[]`
- `narrative?`

Phone numbers are never returned.

---

## 14. Open questions for the user

1. **"Stuck in the grid":** is it the `000 SPOT` queue (G1, recommended), a call sitting in a raw grid zone (G2), or
   something on the Dispatcher Console screen?
2. **Should the story also check whether the address plots inside its grid polygon** (G4, mis-gridded calls)? It
   costs one polygon test per call.
3. **PTA promise:** is the member's promise the PTA at creation (90 on SA-1067245) or the PTA after the garage
   accepted (120)? Today `ERS_PTA_Due__c` uses the latest value, so re-based calls count as "met".
4. **SMS delivery:** can the integration user get read access to `ConversationEntry` (or the Conversation API)?
   Without it we can only say "sent to the SMS channel".
5. **SMS flow gap:** does ops know that the "still working on it" texts never fire on calls that bounce through
   declines or rejections? This is a flow-design finding for the flow owner. The local flow file is dated 8/13, so
   confirm production matches.
6. Operating hours for C01: OK to read `TimeSlot` for matrix garages? That is one small query per story, or cache
   it daily.
7. Who may see the story: all supervisors, or garage-scoped for contractor users (as `/api/search` does)?

## 15. Limits and Salesforce load used

- Measured:
  - 4 golden calls in full.
  - 1 week of WNY Fleet status history (684 SAs, 10,006 rows).
  - 1 day of 076DO (229 SAs).
  - 1 day of org-wide territory history (4,538 rows).
  - Small aggregates on SMS, reasons and territories.
  - About 45 sequential SELECTs, all COUNT-checked. No DML. No Postgres.
- Baselines in §5.2 are indicative (one garage-week). The build must compute them from 56 days per garage.
- The "busy" state for the S3 split is approximated as en route or on scene on another SA. Breaks and absences are
  not removed in the indicative numbers.
- Operating-hours reasoning (C01) and the SMS flow logic (§7.4) come from metadata, not history. They are marked as
  inferred until confirmed.
- FSL does not record why a driver did not accept, or why a Towbook garage declined beyond the last reason. The
  story says so instead of guessing.

---

## 16. Work order replay: Salesforce sources (Henry, 2026-10-04)

The replay is the call story drawn on a map, step by step. It adds four things the story did not define: intake channel,
role of every person who touched the call, how the garage accepted, and member messages. Everything below is read-only,
verified on WNY 100 Fleet 9/28 (90 calls), 076DO 8/31 (208, On-Platform) and 076DO 9/24 (229, Towbook). Scripts:
`validation/roi/intake.py, touch.py, accept.py, sms_gold*.py, gold.py`. Extra cost per replay: **2 queries** (WorkOrder
intake fields, `SMS_Send_Log__c`), plus 1 optional (send-request confirmation, 16.4).

### 16.1 Intake channel (how the call came in)

**Source of truth:** `WorkOrder.Source__c` + `WorkOrder.Secondary_Source__c` + `WorkOrder.CreatedBy` (Name, Profile,
UserRole). `ERS_Channel_Type__c` is a secondary hint only (blank on 54/90 and 95/208). `Source_System_ID__c` was never
populated; `ERS_Source_Call_ID__c` is set only on RAP / Call Mover calls (the partner's call number). There is no standard
`Origin` on WorkOrder. `ServiceAppointment.CreatedBy` is almost always Mulesoft/Replicant and says nothing about channel.

| Replay label | Rule (evaluated in order) | WNY 100, 9/28 | 076DO, 8/31 |
|---|---|---|---|
| **Voice AI (Replicant)** | `Source__c = 'IVR'` and CreatedBy = Replicant Integration User (`Secondary_Source__c` = DRRWeb 2.0 IVR SELF SERVICE) | 41 (46%) | 35 (17%) |
| **Voice AI, completed by agent** | `Source__c = 'Intake'`, CreatedBy = Replicant, Secondary = IVR SELF SERVICE (submitted 3–10 min after WO creation) | 3 | 6 |
| **Call-center agent** | `Source__c = 'Intake'` and CreatedBy profile = Membership User. Show the agent's name and role (Contact Center Level 5 = representative, Level 3–4 = lead/supervisor, Automotive = dispatch staff) | 10 (11%) | 44 (21%) |
| **Member web** | `Source__c = 'DRR'`, Secondary = `DRRWeb 2.0` (also BQ, SEO, BLUESKYDRR) | 21 | 62 |
| **Member mobile app** | `Source__c = 'DRR'`, Secondary ∈ IOSMOBILE, ANDROIDMOBILE, ACEAPP*, DRRCARPLAY IOS | 6 | 26 |
| **Web link from IVR / text** | `Source__c = 'DRR'`, Secondary ∈ `DRRWeb 2.0 IVR`, `DRRWeb 2.0 800SMS` (member was sent to the web form from the phone line or a text) | 2 | 5 |
| **Agent on web form** | `Source__c = 'DRR'`, Secondary = `DRRWeb 2.0 AGENT` | 0 | 0 |
| **Partner: RAP** (roadside assistance partner, e.g. OEM program) | `Source__c = 'RAP'`; show `ERS_Source_Call_ID__c` | 7 | 15 |
| **Partner: Call Mover** (call moved in from another club/system) | `Source__c = 'Call Mover'`; `ERS_Channel_Type__c` IVR / CALL_CENTER tells how it reached the partner | 0 | 5 |
| **System-created copy** | `Source__c = 'Intake'`, CreatedBy = IT System User, `Subject = 'This is a duplicated call'` | 0 | 10 |
| Other | Reciprocal, Reimbursement, Service Ticket, Authorize, Walk-in (`Walk_In_Call__c`), anything else: show the raw value | 0 | 0 |

Notes:
- The DRR/IVR/RAP/Call Mover rows are created by **Mulesoft Integration** (the intake integration); IVR voice-AI rows by
  **Replicant**. The account is the pipe, not the channel: always label from `Source__c`.
- "System-created copy": 10 of 208 calls on 076DO 8/31, Closed, Root = itself, no parent. They were assigned and mostly
  served, so they are **real work, not junk**, and are scored. What creates them is not yet known (open item R1).
- Time of intake = `ERS_Submitted_Date_Time__c` when set (member pressed submit), else WO `CreatedDate`. SA creation follows
  within ~2 s for web/app/IVR.

### 16.2 Every touch, with role

**Sources** (already in the day snapshot or the story pull, 0 extra calls): `ServiceAppointmentHistory` (Status,
`ERS_Assigned_Resource__c`, `ServiceTerritory`, **plus `ERS_PTA__c`, `ERS_Cancellation_Reason__c`,
`ERS_Rejection_Reason__c`**), `WorkOrder.CreatedBy` (intake). Actor role needs `User.Profile.Name`, `User.UserRole.Name`,
`User.Title` and permission-set-group membership. One `User` query for the distinct actors of the call (cache 24 h).

**Role rules** (in order; validated on 197 distinct actors across 5 garage-days):

| Replay role | Rule | Seen as |
|---|---|---|
| FSL optimizer | Name = Platform Integration User | in-day / RSO re-picks |
| FSL auto-schedule | integration-account pick 0–60 s after `SA.Auto_Schedule_Requested__c` (metrics-spec B4a) | first pick at insert |
| FSL system user | Name = FSL System User (System Administrator) | 150 auto-releases (Dispatched) in 5 days |
| Integration (outside FSL) | Mulesoft / Replicant / IT System User, not the two rows above. IT System User's Dispatched = the drip-feed auto-release batch (`ERS_SADripFeedBatch`) | intake, Towbook routing, auto-release |
| Towbook | Profile = Towbook Integrations (`Integrations Towbook`) | Towbook accept/decline/status |
| Driver | the actor is the SA's assigned driver (name matches the ServiceResource), or profile Fleet Driver | accept, en route, on location |
| **Garage portal dispatcher** | Profile = Partner Community User **and** acts on a call assigned to another driver (assign, dispatch, pull back) | Todd Kryszak (076DO), Rob Chisholm |
| **AAA dispatch supervisor / manager** | Profile = Membership User **and** in `ERS_Manager_Permission_Set_Group` | all such users have UserRole Automotive Level 2–3 and titles Supervisor, Dispatch / ERS Fleet Supervisor / Senior Dispatcher / Manager, Dispatch Operations / Dispatch Training Specialist |
| **AAA dispatcher** | Membership User, UserRole Automotive Level 4, in `ERS_Dispatch_Permission_Set_Group`, not in the Manager group | Paige White, Lynn Pilarski, Domingo Santiago (Title "Dispatcher") |
| Call-center lead / supervisor | Membership User, UserRole Contact Center Level 3–4 (Lead Membership Representative, Member Service Supervisor) | |
| Call-center agent | Membership User, UserRole Contact Center Level 5 (Membership / Member Service Representative). Some hold the Dispatch group and do occasional dispatch: label "agent (dispatching)" | |
| Other | anything else: show name + profile | |

**What distinguishes a supervisor from a dispatcher:** membership in **`ERS_Manager_Permission_Set_Group`**, which
coincides 1:1 with UserRole **Automotive Level 2–3** in the sample. Do **not** use `Omni_Channel_Supervisor` (ordinary
dispatchers have it) or `ERS_Contractor_Driver_Dispatcher_PSG` for garage dispatchers (contractor drivers such as Anthony
Tabb Jr have it too). Profile alone is not enough (spec S12: a Fleet driver can have the Membership User profile).

**Touch types to draw:** create (WO, SA), route (territory change), assign / re-assign, unassign, release (Dispatched),
pull back (Dispatched/Accepted/En Route → Spotted), accept, reject (+ `ERS_Rejection_Reason__c`), decline (Towbook),
en route, on location, complete / unable to complete, cancel (+ `ERS_Cancellation_Reason__c`), PTA change (old → new,
actor). Every step carries `{ts, actor, role, action, from, to}`; the map moves only on assign / route / en route / on
location.

### 16.3 Garage acceptance

| How the garage took the call | Data signature | 9/28 WNY | 8/31 076DO | 9/24 076DO |
|---|---|---|---|---|
| **Driver accepted in the FSL app** (Fleet, On-Platform) | first `Status → Accepted` by the assigned driver | 80 | 191 | 1 |
| **Towbook garage accepted** | `Status → Accepted` by Integrations Towbook (usually with a PTA change by Towbook in the same second) | 5 | 1 | 228 |
| **Towbook garage declined** | `Status → Declined` by Integrations Towbook, then a territory move (cascade). ≤ 60 s from offer = "declined within a minute, likely automatic" (C02) | 0 | 5 | 5 |
| Driver rejected | `Status → Rejected` by the driver (+ reason) | 1 | 0 | 1 |
| Released by the garage's portal dispatcher | first `Dispatched` by a Partner Community user who is not the driver | — | 61 | — |
| Released by AAA dispatcher | first `Dispatched` by Membership User | 42 | 70 | 5 |
| Auto-released | first `Dispatched` by IT System User (drip-feed batch) or FSL System User | 44 | 72 | 4 |

Display: one "Garage took it" step = the first Accepted, labelled with its signature. For Towbook calls also show the
Towbook driver/truck from `Off_Platform_Driver__c` / `Off_Platform_Truck_Id__c` (not the `Towbook-<code>` placeholder).
Caveat: on 076DO 8/31 Todd Kryszak's releases read as DRIVER under plain B4 because he is on the roster; use the
decision-mode rule (garage-portal user acting on another driver's call = garage dispatcher) for releases too.

### 16.4 Member communication

**Texts (from 2026-09-01):** `SMS_Send_Log__c` WHERE `Work_Order__c = <WO>` (1 query). Fields to show: `Sent_At__c`,
`Message_Label__c` (definition + checkpoint, e.g. "…not accepted by a driver [30 min]"), `Outcome__c` (Sent / Failed /
Skipped-No-MEU / No-Consent / No-Phone / No-Link / No-AR / No-Channel / Not-Eligible), `Error_Message__c`, `Source_Flow__c`,
`Service_Appointment__c` (the drop-off leg's texts point at the drop-off SA). **Never show `Recipient_Phone__c`.**

Type mapping for the replay: §7.3 catalogue (Call received, Garage + PTA, Still working 30/50/80, Driver accepted update,
En route [battery / tire / with or without tracking link], On location, Tow drop-off leg, Completed, Survey, Opt-in).

**Platform confirmation (optional, 1 query per text, server-side only):** `ConvMessageSendRequest` (2.4 M rows) is the
platform's own send request: `RequestStatus`, `FailedMessageErrorReasons`, `MessageDefinitionParameters`. It has no WO
or SA link and clears the member Id after completion; the only key is the phone in `SuccessMeuPlatformKeys`. Matching
`WorkOrder.Mobile_Phone__c` (last 10 digits) inside the backend within ±10 s **matched 8 of 8** texts on SA-1074304, all
`Completed`. Rules: compare in memory, never return or log the phone; show only "platform: completed / failed (reason)".
Two texts sent in the same second both match (definition is an Id, `1md…`), so attach the status to the pair. Still not
"delivered to the handset": `ConversationEntry` is not readable (§7.1).

**Message text:** not available from SOQL. `MessagingTemplate` has 0 rows and the Messaging Component definitions
(`ConversationMessageDefinition`) are not queryable via Tooling SOQL or present in the local metadata. The send request
exposes only the **parameter names** (e.g. `WO_Id`, `PTA`, `Facility_Name`, `facilityName`, `trackingURL`), never needed
for display. Option (open item R2): one read-only Metadata API retrieve of the ~15 definitions into a static file, then show
the template text with placeholders filled only from safe values (facility name, PTA minutes). Never render the tracking
URL (it is a member token) or any phone number.

**Calls and email:** `VoiceCall` (Genesys, ~18 k/week) exists, but 98% have no `RelatedRecordId` (500-row sample:
inbound 346, outbound 82, transfer 66, none linked to a WO) and none link to the golden WOs. `Task` and `EmailMessage` on
the golden WOs: 0. So outbound calls / IVR / email **cannot be tied to a call today**; the replay says "calls and emails
are not linked to work orders in Salesforce". Linking by caller phone + time is possible but not proposed (PII, low value).

### 16.5 Golden replays (Ruby's tests; times ET)

**G-A: SA-1074304** · `08pPb000009eT1JIAU` · WO 05173612 `0WOPb00000KQpubOAD` · 100 WNY Fleet · Battery · Mon 2026-09-28

| # | Time | Step | Actor (role) |
|---|---|---|---|
| 1 | 11:43:09 | Call received. **Intake: web link from IVR** (`Source__c` DRR, Secondary "DRRWeb 2.0 IVR", channel EDS); submitted 11:44:10 | Mulesoft Integration (integration, intake pipe) |
| 2 | 11:44:12 | SA created, Spotted in 100 WNY Fleet. PTA set 90 → 60 in the same second: **promise 60 min, due 12:44:11** | Mulesoft Integration |
| 3 | 11:44:13 | Texts: "Call received" + "Garage + PTA" (Sent; platform Completed) | Send_SMS_on_SA_Insert |
| 4 | 11:44:23 | Assigned to Marquan Gates (11 s after creation) | Mulesoft Integration (**FSL auto-schedule**, stamp → pick 11 s) |
| 5 | 11:45:15 | Re-assigned to Arthur Yates Jr. | Platform Integration User (FSL optimizer) |
| 6 | 11:50:43 | Re-assigned to Isaiah Carter-Faires (3rd pick in 6.5 min: optimizer churn) | FSL optimizer |
| 7 | 11:52:55 | Released (Dispatched) to Isaiah, who was on scene at SA-1074246 | Lynn Pilarski (**AAA dispatcher**, Automotive Level 4) |
| 8 | 12:14:51 | Text "Still working on it [30 min]" (Sent) | AAA_ERS_Sent_SMS_when_call_is_not_accepted_by_a_driver |
| 9 | 12:34:50 | Text "Still working on it [50 min]" (Sent) | …_Not_Accepted_50mins |
| 10 | 12:44:11 | **PTA passed** (original = final, no re-base) | — |
| 11 | 13:01:39 | **Accepted in the FSL app** (garage acceptance = driver accepted); 68.7 min after dispatch | Isaiah Carter-Faires (driver) |
| 12 | 13:01:43 | En Route. Texts: battery en route (13:01:44) + driver en route with tracking (13:01:45) | driver |
| 13 | 13:18:38 | On Location: **34 min late**. Text "On location" 13:18:39 | driver |
| 14 | 13:25:24 | Completed. Text "Completed" 13:25:27 | driver |

Verdict CAPACITY_SHORT (unchanged). Touch count: 2 systems for intake, FSL ×3 picks, 1 dispatcher, 1 driver, 8 texts.

**G-B (Towbook): SA-1067245** · `08pPb000009bEurIAE` · WO 05164342 `0WOPb00000KLEKbOAP` · 076DO (Towbook) · Tow Pick-Up ·
Thu 2026-09-24

| # | Time | Step | Actor (role) |
|---|---|---|---|
| 1 | 10:33:58 | Call received. **Intake: member web** (DRR / "DRRWeb 2.0", EDS); submitted 10:35:48 | Mulesoft Integration |
| 2 | 10:35:49 | SA created and offered to **Towbook-076DO** (placeholder assignment, Spotted → Assigned). PTA **90, due 12:05:49** | Mulesoft Integration (Towbook routing) |
| 3 | 10:35:53 | Text "Call received" (Sent) | Send_SMS_on_SA_Insert |
| 4 | 10:36:22 | **076DO declined via Towbook in 33 s**; moved to 630 Bachs Towing | Integrations Towbook (Towbook) |
| 5 | 10:36:30 | Offered to Towbook-630 | IT System User (integration, Towbook routing) |
| 6 | 10:37:06 | **630 declined via Towbook in 36 s**; moved to 642 Auto Wrench Connection | Towbook |
| 7 | 10:37:21 | Assigned to Anthony Tabb Jr (642, On-Platform driver) | IT System User (**integration, no auto-schedule stamp**) |
| 8 | 10:41:01 | Released (Dispatched) | IT System User (auto-release) |
| 9 | 10:43:20 | **Driver rejected** ("Out of Area", `ERS_Rejection_Reason__c`) | Anthony Tabb Jr (driver) |
| 10 | 10:43:20 → 11:31:24 | **48 min with no owner** (S7, CRITICAL) | — |
| 11 | 11:31:24–11:31:57 | Pulled to Spotted, moved to **000- ST SPOT**, "assigned" to the SPOT placeholder | Domingo Santiago (**AAA dispatcher**) |
| 12 | 11:32:10 | Released to the SPOT placeholder | IT System User |
| 13 | 11:57:51 | Moved back to 076DO (26 min in SPOT) | Domingo Santiago |
| 14 | 11:58:07 | **076DO accepted via Towbook** and **re-based PTA 90 → 120** (due 12:35:49) | Towbook |
| 15 | 11:58:08 | Text "Garage + PTA", the first ETA text, **82 min after the call** | Send_Immediate_SMS |
| 16 | 12:05:49 | **Original PTA passed** | — |
| 17 | 12:13:36 | En Route (Towbook). Text "Driver en route" 12:13:37 | Towbook |
| 18 | 12:20:44 | **On Location** (SAHistory; `ActualStartTime` empty). 105 min: **15 min late vs original**, met vs re-based | Towbook |
| 19 | 12:32:36 | Pick-up completed. Text "Tow drop-off leg, no tracking link" 12:32:37 (on drop-off SA-1067246) | Towbook |
| 20 | 15:04:43 | Text "Completed" (drop-off leg) | Send_Immediate_SMS |

No "still working" text: the timer reset each time the status left Assigned/Dispatched (§7.4). Verdict
NOT_GRADED_TOWBOOK; headline cause C04.

### 16.6 Open items
- **R1:** what creates the "This is a duplicated call" work orders (IT System User, `Source__c` Intake)? They carry real
  service. Ask the intake/integration team before labelling them more specifically.
- **R2:** approve a one-time read-only Metadata API retrieve of the Messaging Component definitions so the replay can show
  template text (placeholders only).
- **R3:** confirm the role mapping with a dispatch manager: is "Senior Dispatcher" / "Dispatch Training Specialist" (in the
  Manager group) to be shown as supervisor?
