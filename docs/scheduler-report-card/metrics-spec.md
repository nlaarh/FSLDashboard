# Scheduler Report Card: Metric and Verdict Spec

Owner: Henry (metrics, verdicts, thresholds) · Plugs into Dan's `architecture.md` §5.3, §6, §7, §11.3
Status: DRAFT for user approval · 2026-10-03 · METRICS_VERSION `m1` · rules `r1` / engine `e1`
Every number here comes from a read-only SOQL pull. The scripts and raw outputs are in
`docs/scheduler-report-card/validation/`.

---

## 0. The answer first

1. **076DO cannot be the pilot for grading the scheduler.** On 2026-09-01 it moved from On-Platform FSL to
   Towbook. Since then, every 076DO assignment goes to the placeholder `Towbook-076DO`, and all 108
   On-Platform members are inactive. On 9/24, all 374 of 374 SAs are Towbook. No 076DO day in the last 30
   days has an FSL driver decision to grade.
2. **Primary validation day: 100 - WESTERN NEW YORK FLEET (`0HhPb00000007qGKAQ`), Monday 2026-09-28.**
   It had 90 member calls, all Fleet. The optimizer was active that day: 257 In-Day runs on the territory,
   202 RSO runs on its drivers and 358 `Optimization_Log__c` rows.
3. **That day, the scheduler's picks were sound on distance and load:**
   - A qualified driver who was closer *and* less loaded was available in **0 of 80** gradable decisions.
   - A closer idle driver was available in **3 of 80**.
   - Where it went wrong was elsewhere: slow or churning assignments, dispatcher pull-backs, calls
     inherited from Towbook garages, and real capacity shortfalls.
   - PTA met: **65/82 = 79%**. Median response: **40 min**.
4. **076DO on 2026-08-31 (its last On-Platform Monday) shows the stacking problem clearly:**
   - A qualified driver who was closer *and* idle was available in **65 of 195** decisions (33%).
   - A closer *and* less-loaded driver was available in **34 of 195** (17%).
   - 26 SAs are STACKED and 15 are FAR_PICK. PTA met: **124/185 = 67%**.
5. **Three rules in the current project guidance are wrong. The data shows it:**
   - (a) `AssignedResource.CreatedBy` is **not** the final decision maker. The AR row is updated in place,
     so CreatedBy is whoever created it, and the last driver change was made by someone else in 25 of 82
     SAs. The final decision maker is the actor on the last `ERS_Assigned_Resource__c` history row.
   - (b) `Platform Integration User` is the **FSL optimizer** (In-Day/RSO), not an external integration.
     All 48 of its assignment events on 9/28 fall within 1 minute before to 3 minutes after an optimization
     request.
   - (c) Skills on `ServiceResourceSkill` alone do not gate dispatch. "Qualified" = WOLI
     `SkillRequirement` ⊆ (driver skills ∪ capabilities of the truck the driver is logged into). That rule
     explains 100% of FSL-engine and integration picks on both days (20/20, 39/39, 45/45, 70/70).
6. **`simulate_day` understates closest-driver performance by half:** 22% vs 44% on 9/28. Off-shift drivers
   with old GPS are treated as candidates, and its skill gate reads an empty table. Details in §9.

---

## 1. Scope, pilot and validation days

| Day | Garage | Role | Why |
|---|---|---|---|
| **2026-09-28 (Mon)** | 100 - WESTERN NEW YORK FLEET | **Primary.** All FSL metrics, closest driver, optimizer cross-check | 90 member calls (4th busiest of the last 30 days; the busier 9/5, 9/8 and 10/3 are a Saturday, 20+ days old and today). 257 In-Day runs plus 202 RSO runs, and policy `Copy of Highest Priority` ran 451 of 459 times. A Monday 5 days ago, inside any plausible optimizer retention window |
| 2026-08-31 (Mon) | 076DO - TRANSIT AUTO DETAIL | Secondary. On-Platform Contractor example | Busiest late-August day (208 member calls, 309 AR) and its last full On-Platform day. SF history only |
| 2026-09-24 (Thu) | 076DO | Towbook workload-only example | Busiest 076DO day since 9/8 (229 member calls). No scheduler grade |

Daily WNY Fleet member-call counts for the last 30 days range from 62 to 112 (median about 83). Pilot
alternative: 800 - CENTRAL REGION ERS FLEET SERVICES, which has the most In-Day runs (9,303 in 30 days).

**ERS only.** `RecordType.Name = 'ERS Service Appointment'`. Tow Drop-Off is excluded from every count and
time (`'drop' in WorkType.Name.lower()`). WNY Fleet had 0 drop-offs on 9/28 because Fleet does light service.

---

## 2. Source-of-truth rules (verified in this session)

| # | Rule | Evidence |
|---|---|---|
| S1 | **The day window is the Eastern calendar day.** Use `ZoneInfo('America/New_York')`; 9/28 = `04:00Z..04:00Z` | `simulate_day` uses UTC midnight. Wrong (§9) |
| S2 | **Channel comes from `AssignedResource.ServiceResource.ERS_Driver_Type__c`.** If there is no AR (canceled calls), use the last assigned driver from history. Never use `ERS_Dispatch_Method__c`: it is the formula `TEXT(AAA_ERS_Account_Facility__r.Dispatch_Method__c)`, the facility's *current* method | 076DO's August calls now read "Towbook" |
| S3 | **The AR row is updated in place, not replaced.** `AR.CreatedBy`/`CreatedDate` = whoever created the row. The last driver change can be made by someone else | 9/28: AR.CreatedBy ≠ last assignment actor in 25/82 (11 Integration→FSL, 9 Integration→Human). Example SA-1073613: AR created 12:16 UTC by Mulesoft, final driver set 12:35 by Platform Integration User. AR.CreatedDate ≠ final assignment time in 81/82 |
| S4 | **Final decision = the last `ServiceAppointmentHistory` row with `Field='ERS_Assigned_Resource__c'` whose NewValue is a name (not an Id).** Its CreatedBy is the decision maker; its CreatedDate is the decision time | Every change writes two rows (name + Id); keep the name rows. A "clear" row (NewValue null) is an unassign |
| S5 | **The history field name is `ServiceTerritory`, not `ServiceTerritoryId`.** A real garage bounce = a row with OldValue non-null and NewValue ≠ OldValue | 9/28: 83 creation rows (null → 100), 7 real moves into 100 |
| S6 | **Arrival:** Fleet/On-Platform = `ActualStartTime`. Towbook = first SAHistory `Status` NewValue `'On Location'` | 9/28: AST vs history On Location median diff 0.0 min, max 12 min (n=80). 076DO 9/24 Towbook: AST present on only 73/208, median "response" 273 min, \|AST − On Location\| median 240 min, 89% off by > 30 min |
| S7 | **PTA deadline = `ERS_PTA_Due__c`.** Formula: `ERS_Spotting_Datetime__c + ERS_PTA__c/1440`. PTA in minutes; skip PTA ≤ 0 or ≥ 999 | 0 disagreements against `CreatedDate + ERS_PTA__c` on both days (spotting = created for all 90 on 9/28). `ERS_PTA__c` is written twice at creation (90 → 60 or 75); use the stored value |
| S8 | **On-shift = truck login (`AssetHistory` `Field='ERS_Driver__c'`) minus `ResourceAbsence`.** `Shift` is effectively empty | Shift: 72 rows org-wide in 30 days; 0 for WNY Fleet on 9/28; 1 for 076DO on 8/31. Absences on 9/28: Break 9, Shift Mod - Early Out 5, Out-Short-Term 2, Call out 1, PTO 1 |
| S9 | **Qualified = WOLI `SkillRequirement.Skill` ⊆ `ServiceResourceSkill` ∪ `Asset.ERS_Truck_Capabilities__c` of the truck logged in at that moment.** Requirements live on the **WOLI** (`SA.ParentRecordId`), not on WorkType | WorkType SkillRequirement = 0 rows. Strict SR-skills-only: FSL engine meets 1/20, contractors 0/45. Combined rule: FSL 20/20 and 45/45, Integration 39/39 and 70/70, Human 28/31 and 41/45 |
| S9-T | **Truck timing for S9.** Use the truck the driver is logged into at the decision time. If they are not logged in yet, use the first truck they log into within `qualified_login_forward_min` (30) after the decision **and** before their En Route on that SA. If neither exists, qualification = `unknown` | 9/28: 4 human picks were made 1.4 to 16 min before the driver's truck login (Jacob Schaich ×2, Kenneth Kirkendoll ×2). In all 4, the truck they then logged into covers the job (Tire, Battery Service, Lockout), and each driver logged in before going En Route. Skills on the SR alone never cover these jobs, so without this rule every pre-login pick reads as a skill mismatch |
| S10 | **Roster = `ServiceTerritoryMember` effective on that day.** For historical days, do **not** filter `ServiceResource.IsActive = true` | All 108 076DO contractors are inactive today but were active on 8/31 |
| S11 | **GPS = `ServiceResourceHistory` LastKnownLatitude/Longitude.** Use the newest fix ≤ decision + 5 min, and only if it is ≤ 30 min old | Coverage of on-shift minutes with a fresh fix: 98% (954/975) on 9/28, 98% (2,636/2,689) for 076DO contractors on 8/31. **Contractors do have GPS** |
| S12 | **Membership User profile ≠ dispatcher.** Kenneth Kirkendoll is a Fleet driver whose User profile is Membership User, and he wrote 30 status rows on 9/28. On the Towbook day, 34 different Membership Users touched 076DO assignments | Any "status changed by Membership User → manual" rule mislabels driver actions. Rule: if the actor's name matches the SA's driver ServiceResource, the actor is a DRIVER |

---

## 3. Channel mapping (`architecture.md` §5.3)

| `ServiceResource.ERS_Driver_Type__c` (as captured at build) | channel | graded? |
|---|---|---|
| `Fleet Driver` | `fleet` | yes |
| `On-Platform Contractor Driver` | `on_platform_contractor` | yes (see contractor caveat C3) |
| `Off-Platform Contractor Driver` (Towbook placeholder `Towbook-<code>`) | `towbook` | no. Workload view only |
| null / no AR and no driver in history | `unknown` | no |

FSL Platform = `fleet` + `on_platform_contractor`. Day mode is `towbook` if all graded-eligible SAs are
`towbook`, `fsl` if none are, otherwise `mixed`. On a Towbook day, the person who did the work is
`SA.Off_Platform_Driver__c` (Contact) / `Off_Platform_Truck_Id__c`. It is populated on 227/229 calls on 9/24.

---

## 4. Building blocks (shared by all metrics and verdicts)

**B1 Scored SA set:** ERS record type, created in the ET window, not Tow Drop-Off, and not inbound-only
context. Carryover SAs (created before the window, still open) count toward open jobs only.

**B2 Milestones** (first occurrence in SAHistory `Status`):
`t_disp` = Dispatched, `t_acc` = Accepted, `t_er` = En Route, `t_ol` = On Location,
`t_end` = first of {Completed, Unable to Complete, Cancel Call - Service Not En Route,
Cancel Call - Service En Route, Canceled, No-Show}.

**B3 Assignment events:** name rows of `ERS_Assigned_Resource__c` in time order, each with
(ts, driver, actor, actor profile).
- `t_first` = the first event.
- `t_asg` = the last event that set the final driver (the decision time).
- `n_pre` = events before `t_disp`.
- `pullback` = a Status change to `Spotted` after the SA had been Dispatched, Accepted or En Route.

**B4 Actor class** (config list in r1, evaluated in this order):

| Class | Rule | Seen on these days |
|---|---|---|
| `FSL_ENGINE` | name in {`Platform Integration User`, `FSL System User`} | Platform Integration User (no profile, UserType CloudIntegrationUser); FSL System User (System Administrator) |
| `INTEGRATION` | name in {`Mulesoft Integration`, `Replicant Integration User`, `IT System User`} (all profile `AAACRM Mulesoft Integration User`) | all three |
| `TOWBOOK_SYNC` | profile `Towbook Integrations` (`Integrations Towbook`) | Towbook status writes |
| `DRIVER` | actor name matches a ServiceResource on the roster, or profile `Fleet Driver` | Fleet drivers updating status |
| `GARAGE_DISPATCHER` | profile `Partner Community User` and not a roster driver | Todd Kryszak (75 assignment rows on 8/31), Anna Guarino (5) |
| `HUMAN` (AAA dispatcher) | profile `Membership User` and not one of the above | 9/28: Paige White, Lynn Pilarski, Gabriela Butler. 8/31: Paige White, Lynn Pilarski, Tyler LaFave, Joana Smith, Krystle Knight, Katie Tamez, Geela Israel |
| `OTHER` | anything else | logged for review |

**B4a: integration accounts are not all "outside the scheduler"** (verified 2026-10-04, read-only; evidence in
`validation/roi/integ*.py`).

| Account (profile `AAACRM Mulesoft Integration User`) | What its driver picks actually are | Evidence |
|---|---|---|
| Mulesoft Integration, Replicant Integration User | **FSL auto-schedule.** The call-intake trigger enqueues `ERS_SA_AutoSchedule`, which only sets `FSL__Auto_Schedule__c = true` and stamps `Auto_Schedule_Requested__c`. The FSL managed batch `FSL.BatchScheduleServiceAppointments` then schedules the call with an FSL policy, **running as the user who set the flag**, so the assignment history shows the integration account | Prod class body identical to local (last modified 2026-05-11). Last 2 days: **179/179** Mulesoft and **68/68** Replicant driver picks fall inside an FSL `BatchScheduleServiceAppointments` run they launched (placebo, shifted −10 min: 2–3%). Every one is request-stamped. Pick − request: median 7–8 s, matching the org's own `Auto_Schedule_Elapsed_Seconds__c` (median 7 s, logged as "FSL Assignment detected"). 9/28: 70/70; 8/31: 33/33 |
| IT System User | **Mixed.** 109 of 286 driver picks (2 days) fall inside FSL auto-schedule batch runs. **167 do not**: no batch running, no request stamp, no SF optimizer run nearby (Aug: 30% within 60 s of a run, the same as humans). They follow a pull-back or a territory move 10–45 s earlier, mostly at On-Platform contractor garages (076DO in Aug, 201, 4635D, 4652D, 4682 now) | No Apex in the org's metadata picks an on-platform driver: the only direct `AssignedResource` insert is the Towbook placeholder (`spotOffPlatformWork`), and the geo-queueable insert is commented out. So the decision is made **outside Salesforce code**, most likely the MuleSoft service itself. **Confirm with the integration team.** Pick quality on 076DO first picks: closest-free 21% (n 733), mean 0.94 open jobs on the pick vs 0.20 for the least-loaded candidate. FSL auto-schedule first picks on the same garage: 68% (n 111) and 0.77 vs 0.56 |
| Mulesoft / IT / Replicant **Towbook placeholder** picks (`Towbook-<code>`, SPOT) | Routing to a Towbook garage, not a driver choice | Already NOT_GRADED_TOWBOOK |

`FSL__Scheduling_Policy_Used__c` is **never** populated in this org (0 of 45,725 ERS SAs in Aug 2026, including
optimizer picks). An empty policy field therefore proves nothing and must not be cited as evidence of a bypass.

**Rule change (proposed r2 / builder `rc-build-1.1`):**
- Pull `Auto_Schedule_Requested__c` with the SA.
- An integration-account pick made 0–60 s after `Auto_Schedule_Requested__c` gets class **`FSL_AUTO_SCHEDULE`**: the FSL
  scheduler, a policy run. It is **not** BYPASSED_OPTIMIZER.
- An IT System User pick inside a known batch window stays INTEGRATION until it can be tied to a job. AsyncApexJob
  keeps only about 7 days, so for past days use the stamp rule.

**Effect on the headline days (r1 → proposed):**
- **076DO 8/31:** BYPASSED_OPTIMIZER 162 → **134**. The 162 = 47 garage-portal dispatcher + 45 AAA dispatcher + 42 IT System
  User (no stamp) + 28 Mulesoft/Replicant auto-schedule.
- **WNY 9/28:** 70 → **31** (all 39 integration finals were FSL auto-schedule).
- "Integration picks that bypassed FSL" on 8/31 is **42 of 204 graded calls (21%)**, not 162.

**B5 Open jobs** for a driver at time t = the number of scored or carryover SAs whose final driver is that
driver and where `t_asg ≤ t < t_end`. Canceled SAs count until their cancel time.

**B6 Candidate set at decision time t:**
- active territory member that day (S10),
- on truck and not absent (S8),
- qualified (S9),
- fresh GPS (S11),
- with `miles` = haversine(GPS, SA) and `open_jobs` from B5.

Store the candidate set at **every** assignment event, not only the first; that is at most 7 per SA. Dan's
snapshot stores candidates only at the first assignment. Verdicts use the decision-time set.

**B7 Waiting call at t:** created ≤ t < `t_er` (or `t_end` if earlier) and waited ≥ 10 min.

**Gantt segments per driver** (from B2/B3, per SA of that driver):

| Segment | From → To | Colour role |
|---|---|---|
| Queued | `t_asg` → `t_disp` | assigned, not yet sent |
| Dispatched | `t_disp` → `t_acc` (or `t_er`) | waiting for driver accept |
| En route | `t_er` → `t_ol` | travel |
| On scene | `t_ol` → `t_end` | work |
| Idle | on-shift time with zero open jobs | gap |
| Off shift / absence | outside login windows / `ResourceAbsence` (labelled with its Type) | grey |

Overlapping bars on one driver = stacking. Assignments made before truck login are real: 9/28 had 8 such
SAs (FSL assigns ahead of login), so draw them, flagged.

---

## 5. Metric registry (`architecture.md` §6)

All families: scope `garage` and `driver` unless noted. Channels: `fleet` + `on_platform_contractor`,
unless marked T (Towbook-applicable). Bands are r1 proposals and tunable (§7.6).

| id | family | label / meaning | formula (source in §2/§4) | unit | needs | bands (good / watch / bad) | 9/28 WNY value |
|---|---|---|---|---|---|---|---|
| M01 T | load | Calls per driver (assigned, completed) | count SAs by final driver (Towbook: `Off_Platform_Driver__c`) | count | — | — | median 7.5, max 10 |
| M02 | load | Load spread | max ÷ median calls among drivers on shift ≥ 1 h | ratio | logins | ≤ 1.5 / ≤ 2.0 / > 2.0 | 1.33 (12 drivers) |
| M03 | load | Jobs per on-shift hour (driver; garage min/median/max) | assigned SAs ÷ on-shift hours (S8) | ratio | logins | spread max/min ≤ 2 / ≤ 3 / > 3 | 0.61 to 1.73, median 1.15 (2.8×) |
| M04 | load | Utilisation | minutes on shift with ≥ 1 open job ÷ on-shift minutes | pct | logins | — (shown) | 62% to 100% |
| M05 | load | Idle while members waited | Σ over minutes of idle on-shift drivers while ≥ 1 call waited (B7); variant "within 15 mi" (GPS) | hours, plus % of on-shift hours | logins, gps | ≤ 5% / ≤ 10% / > 10% | 8.6 h; 7.8 h within 15 mi = 9.6% of 81.2 on-shift h |
| M06 | stacking | Max concurrent open jobs | max over t of B5 per driver | count | — | ≤ 2 / 3 / ≥ 4 | max 3 (Mike Klotz, Marquan Gates); all 12 drivers reached 2 |
| M07 | stacking | Stacked driver-minutes | Σ minutes with B5 ≥ 2 | minutes | — | — | 1,426 |
| M08 | stacking | Queue wait | `t_er − t_asg`, median / p90 | minutes | — | p90 ≤ 30 / ≤ 60 / > 60 | median 14, p90 55 |
| M09 | source | Decision source mix | share of SAs by actor class of the **final** decision (B3/B4); also **first pick** and `AR.CreatedBy` (audit) | pct | — | — | final: Integration 39, Human 31, FSL 20. First: Integration 75, FSL 8, Human 7 |
| M10 | source | Optimizer touch and churn | % of SAs with ≥ 1 FSL_ENGINE pick; % with `n_pre` ≥ 3 | pct | — | churn ≤ 5% / ≤ 15% / > 15% | touched 31/90; churn 15/90 = 17% |
| M11 | source | Human override rate | final actor HUMAN after a non-human pick | pct | — | — | 25 of 31 human finals replaced an earlier system pick |
| M12 T | outcome | Response time | arrival (S6) − CreatedDate; median / p90; by channel and by final source | minutes | — | — | median 40, mean 50 (n=82) |
| M13 T | outcome | PTA met | arrival ≤ `ERS_PTA_Due__c`; by final source (n shown, no ranking under 30) | pct | — | ≥ 85 / ≥ 75 / < 75 (target TBC by user) | 65/82 = 79% |
| M14 | outcome | Speed to decide | `t_first − created` median; `t_disp − t_asg` median | minutes | — | — | 0.2 / 0.7 |
| M15 | bounce | Garage bounces in / out | in: S5 move into this garage; out: S5 move from this garage (§11 Q2) | count | region history (out) | — | in 7 (5 from 053 Towbook, 1 from 063, 1 from LS); out 0 |
| M16 | bounce | Driver bounces | SAs with a pullback or a driver change after `t_disp` | count, pct | — | ≤ 5% / ≤ 10% / > 10% | 13 pullbacks; 12 post-dispatch reassignments |
| M17 | closest | Closest qualified picked | at `t_asg`, picked driver = min-miles candidate (B6) | pct | gps | within-2-mi ≥ 80 / ≥ 65 / < 65 | 38/87 = 44%; within 2 mi 59/87 = 68% |
| M18 | closest | Extra miles | Σ and median (picked − closest qualified) | miles | gps | — | Σ 129.2; median 2.2 when not closest |
| M19 | closest | Closest **free** qualified picked | among SAs where a 0-open-job candidate existed | pct | gps | ≥ 80 / ≥ 65 / < 65 | 36/43 = 84% |
| M20 | closest | **Qualified-available-not-picked** (headline) | SAs where a candidate was > 0.5 mi closer **and** (a) idle, (b) had fewer open jobs than the pick | pct | gps | (a) ≤ 5% / ≤ 15% / > 15% | (a) 3/80, (b) 0/80 |
| M21 | quality | Data coverage | % of on-shift minutes with fresh GPS; % of SAs gradable | pct | gps | ≥ 90 / ≥ 75 / < 75 | 98%; 87/90 gradable |
| T01 T | towbook | Calls per Off-Platform driver; demonstrated capacity | distinct `Off_Platform_Driver__c`; jobs/day vs historical p95 (memory: towbook-demonstrated-capacity) | count | — | — | 9/24: 25 drivers, top 15, median 8 |

Notes:
- **M09.** Report `AR.CreatedBy` only as an audit column labelled "record creator". Dan's §6 text
  "`assignment.source` from AssignedResource.CreatedBy" must change to the final assignment actor (S3/S4).
- **M12/M13 by source** are confounded. The optimizer touches calls that are already in trouble: FSL-final
  13/19 (68%) vs Integration-final 31/35 (89%), and FSL n < 30, so do not rank. Show n, and never present
  these as "the optimizer performs worse".
- **M17.** "Closest" is straight-line distance. AR's own `FSL__EstimatedTravelDistanceTo__c` is 1.42× the
  straight line (IQR 1.22 to 1.67, n=78), which is consistent with road distance. Show the miles basis on
  screen.

---

## 5A. Driver-day health (`h1`, replaces the interim worst-of {M06, M08 p90, M13})

**What it answers:** does this driver's day need someone's attention, and whose: the **scheduler's** (how work was
spread) or the **driver's** (how the work was executed)? A driver should never look bad because the scheduler
queued work behind them.

**Why the interim rule is wrong:**
- **M08 p90** on 5 to 10 calls is effectively the single worst call. Queue wait is mostly the scheduler queueing
  behind a busy driver, which is not the driver's health.
- **Per-driver M13** ranks groups of 4 to 9 calls, against our n ≥ 30 rule. One miss turns 7/7 into 86% = watch.
- On 9/28 the interim rule produced 1 healthy / 7 watch / 4 unhealthy, driven by queue-wait p90, on a day when the
  picks were sound.

**Two lenses. The badge = the worse lens, labelled with its owner(s).**

| id | Lens (owner) | Input | Definition | good / watch / bad | min data |
|---|---|---|---|---|---|
| H1 | Workload (scheduler) | **Avoidable stacking** | on-shift minutes with ≥ 2 open jobs (B5) while another roster member was on shift, idle (0 open jobs), qualified (S9/S9-T) and had a GPS fix ≤ 30 min old within `reach_mi` (15) of one of this driver's queued SAs (t_asg ≤ t < t_er), ÷ on-shift minutes | ≤ 0.05 / ≤ 0.20 / > 0.20 | on shift ≥ 120 min |
| H2 | Workload (scheduler) | **Idle while work waited** | on-shift minutes with 0 open jobs while ≥ 1 **in-garage** call waited (B7, with the wait starting at max(created + 10 min, move-in time)), the driver was qualified for it and was within 15 mi, ÷ on-shift minutes (per-driver M05) | ≤ 0.10 / ≤ 0.25 / > 0.25 | on shift ≥ 120 min |
| H3 | Workload (scheduler) | Peak load | M06 max concurrent open jobs | ≤ 3 / — / ≥ 4 | — |
| H4 | Execution (driver) | **Driver-attributable late arrivals** | count of the driver's SAs with code `LATE_EXECUTION` (a sound, quick pick to a free driver, and PTA still missed) | 0 / 1 / ≥ 2 | — |
| H5 | Execution (driver) | **Non-response pull-backs** | pull-backs (Dispatched → Spotted) from this driver where they had 0 open jobs at dispatch **and** had not accepted for ≥ the garage's free-driver Dispatched→Accepted p75 (indicative 15 min). Shorter pull-backs (≈ 1 min) are dispatcher corrections and are ignored | 0 / 1 / ≥ 2 | — |
| H6 | Execution (driver) | Slow to accept when free | median Dispatched→Accepted (or En Route) over the driver's SAs picked with 0 open jobs | ≤ garage free p75 / ≤ p90 / > p90 (56-day baseline; indicative WNY 15.1 / 40.1 min) | n ≥ 3 |
| — | context, not banded | PTA met n/N, misses split by owner | system (CAPACITY_SHORT, LATE_DESPITE_CAPACITY, STACKED, FAR_PICK) · bounce (BOUNCED and missed) · driver (LATE_EXECUTION); queue wait **median** | shown only | — |
| — | context, not banded | Long on scene | jobs with On Location → end > work-type p90 | shown only until the 56-day work-type baselines exist | — |

**Labels:**
- `healthy`: both lenses good.
- `watch` / `unhealthy`: the worse lens decides. Also return `health_owner` ∈ {`scheduler`, `driver`, `both`} and
  the reasons (input id, value, band).
- UI wording: "Scheduler: Jacob was stacked 29% of his shift while a qualified driver nearby was idle", not
  "Jacob unhealthy".
- H1 and H2 are two sides of one rebalance gap. Show the top partner where possible ("…while Marquan Gates sat
  idle").

**What H5/H6 cannot see:** why a driver did not accept. FSL does not record it, and the driver may be on an
unlogged break.
Contractor caveat C3 applies to H2 (idle is an upper bound for `on_platform_contractor`).

**9/28 WNY 100 result under h1.** Computed offline from the slice-1 snapshot. Scripts are in
`validation/driver_health/`.

| Driver | On-shift min | H1 avoidable stacked | H2 idle while waited | H4 | H5 | H6 median (n) | PTA met (misses: sys/bounce/drv) | h1 | interim |
|---|---|---|---|---|---|---|---|---|---|
| Antonio Hatch Jr. | 423 | 0.16 W | 0.00 | 0 | 0 | 0.7 (2) | 6/9 (3/0/0) | **watch** (scheduler) | unhealthy |
| Marcus Gibson | 347 | 0.03 | 0.03 | 0 | 0 | 3.6 (6) | 8/9 (0/1/0) | **healthy** | healthy |
| Mike Klotz | 456 | 0.00 | 0.08 | 0 | 0 | 0.0 (6) | 7/9 (1/0/0) | **healthy** | watch |
| Arthur Yates Jr. | 429 | 0.10 W | 0.00 | 1 W | 0 | 4.5 (4) | 7/9 (1/0/1) | **watch** (both) | watch |
| Frankie Giordano | 444 | 0.03 | 0.21 W | 0 | 0 | 0.7 (4) | 7/8 (0/1/0) | **watch** (scheduler) | watch |
| Benjamin Hailand-Vanlieu | 450 | 0.00 | 0.16 W | 0 | 0 | 5.2 (4) | 6/7 (1/0/0) | **watch** (scheduler) | unhealthy |
| Isaiah Carter-Faires | 455 | 0.02 | 0.03 | 0 | 0 | 13.5 (3) | 5/7 (2/0/0) | **healthy** | unhealthy |
| Kenneth Kirkendoll | 308 | 0.02 | 0.14 W | 0 | 0 | 18.2 (3) W | 6/6 | **watch** (both) | watch |
| Jacob Schaich | 439 | **0.29 B** | 0.01 | 0 | 1 W (82.9 min) | 26.0 (2) | 2/5 (3/0/0) | **unhealthy** (scheduler; driver watch) | unhealthy |
| Jarron Wiggins | 434 | 0.00 | 0.08 | 1 W | 0 | 12.4 (4) | 4/5 (0/0/1) | **watch** (driver) | watch |
| Marquan Gates | 300 | 0.00 | **0.29 B** | 0 | 1 W (15.7 min) | 0.6 (1) | 4/4 | **unhealthy** (scheduler; driver watch) | watch |
| Ernest Patterson | 392 | 0.02 | 0.02 | 0 | 0 | 3.7 (2) | 3/4 (1/0/0) | **healthy** | watch |

- Misses not in the split are INBOUND_CASCADE calls (the clock started in another garage). Example: Mike Klotz's
  second miss.
- **h1: 4 healthy / 6 watch / 2 unhealthy** (interim: 1 / 7 / 4).
- Both "unhealthy" drivers are scheduler-owned: Jacob was stacked while qualified colleagues nearby were idle, and
  Marquan was idle while work he could do waited.
- Isaiah moves from unhealthy to healthy. His 69-min queue on SA-1074304 was a capacity problem (CAPACITY_SHORT),
  not his.
- Cross-check: H2 summed over the 12 drivers, before the qualified/in-garage filters = 469 min = 7.8 h. That matches
  M05 within 15 mi in §5.
- The band edges were chosen on one garage-day. Re-check them after 30+ garage-days (`min_support`), like the other
  r1 thresholds.

**Config.** Ruby replaces `RULES_R1['driver_health']` in `backend/report_card_verdicts.py`:

```jsonc
"driver_health": {
  "version": "h1",
  "min_on_shift_min": 120,
  "reach_mi": 15, "gps_max_age_min": 30,
  "workload": {
    "H1_avoidable_stacked_share": {"good": [0, 0.05], "watch": [0.05, 0.20]},
    "H2_idle_while_waited_share": {"good": [0, 0.10], "watch": [0.10, 0.25]},
    "H3_max_open": {"bad_at": 4}
  },
  "execution": {
    "H4_late_execution_count": {"watch_at": 1, "bad_at": 2},
    "H5_nonresponse_pullbacks": {"watch_at": 1, "bad_at": 2, "min_wait": "free_accept_p75", "min_wait_fallback_min": 15},
    "H6_accept_when_free_median": {"good": "free_accept_p75", "watch": "free_accept_p90", "min_n": 3,
                                    "fallback_min": {"p75": 15.1, "p90": 40.1}}
  },
  "context_only": ["pta_split_by_owner", "queue_wait_median", "long_on_scene"]
},
"candidate": { "...": "...", "qualified_login_forward_min": 30 }
```

## 5B. Member impact (ranks findings; decision 2026-10-04)

**What it measures:** how long members waited past the time we promised them, on the calls a finding is about.

**Per call:**
- `impact_min = max(0, end − due_initial)`, rounded to whole minutes.
  - `due_initial` = the original promise (r2, §7.7): spotting time + the `ERS_PTA__c` written ≤ 5 s after creation.
  - `end` = arrival: `ActualStartTime` for Fleet / On-Platform, the first SAHistory `On Location` for Towbook.
- **Refinement 1, member cancels:** a member cancel (reasons in `roi-baseline.md` §2) whose cancel time is after
  `due_initial` counts with `end = cancel time`. These members waited past the promise and then gave up. Leaving them out
  hides the worst outcomes (14 of 162 member cancels in the ROI sample). Facility cancels and calls with no arrival and no
  member cancel count 0.
- Tow Drop-Off never counts. PTA ≤ 0 or ≥ 999 counts 0 ("not graded").

**Per finding:**
- `impact_minutes = Σ impact_min` over the finding's calls, with `late_calls` = the count with `impact_min > 0`.
- Show the median beside it.
- **Refinement 2, overlap:** a call can sit in several findings. It counts in full in each one, for ranking only.
  - Never add findings' impact together.
  - The day's total is the distinct-call sum (the existing `impact` fact).
  - Say so under the panel: "a call can appear in more than one finding".
- **Refinement 3, one-call dominance:** if one call is more than 50% of a finding's minutes, show "mostly one call (SA-…)".
  - Example: SA-974049 on 076DO 8/05 was 603 min late on its own, an inbound cascade.
  - Ranking still uses the sum. That is the member's real wait, and capping it would hide the worst cases.
- **Order:** impact_minutes desc, then severity, then count. A finding with 0 impact sorts by severity.

**Status of the build:**
- `report_card_facts.py` today uses `ERS_PTA_Due__c` (final) and arrivals only.
- Switch to `due_initial` when builder `rc-build-1.1` stores the initial PTA, and add the cancel rule.
- Until then, label it "minutes past PTA (current)".
- On the ROI sample the two bases differ by 1–2 calls per garage-month (r2 §7.7), so ranking will not change in practice.

---

## 6. Validation evidence (so the app can be checked later)

### 6.1 Primary: WNY Fleet 100, 2026-09-28 (90 SAs; all `fleet`)

Counts: SA `COUNT()` = 90 = pulled. AR 82; the 8 canceled SAs lost their AR, and their driver was recovered
from history. Status: Completed 68, Unable to Complete 14, Cancel Not En Route 5, Cancel En Route 3.
Work types: Battery 54, Tire 23, Lockout 11, Fuel 1, Locksmith 1. `FSL__Scheduling_Policy_Used__c` is null
on all 90, and `AR.FSL__UpdatedByOptimization__c` is false on all 82, so neither is usable to detect the
optimizer.

Driver-day table (on shift ≥ 1 h; times ET):

| Driver | Login window | On-shift h | Assigned | Completed | Jobs/h | Util | Max open |
|---|---|---|---|---|---|---|---|
| Antonio Hatch Jr. | 13:49–21:23 | 7.0 | 10 | 9 | 1.42 | 100% | 2 |
| Marcus Gibson | 08:17–15:31 | 5.8 | 10 | 5 | 1.73 | 88% | 2 |
| Mike Klotz | 15:05–23:11 | 7.6 | 10 | 7 | 1.32 | 62% | 3 |
| Arthur Yates Jr. | 07:09–14:48 | 7.2 | 9 | 8 | 1.26 | 86% | 2 |
| Frankie Giordano | 14:56–22:56 | 7.4 | 9 | 5 | 1.22 | 66% | 2 |
| Benjamin Hailand-Vanlieu | 15:01–23:01 | 7.5 | 8 | 7 | 1.07 | 75% | 2 |
| Isaiah Carter-Faires | 07:40–15:45 | 7.6 | 7 | 7 | 0.92 | 86% | 2 |
| Kenneth Kirkendoll | 17:27–22:35 | 5.1 | 7 | 6 | 1.36 | 74% | 2 |
| Jacob Schaich | 14:41–22:53 | 7.3 | 6 | 5 | 0.82 | 98% | 2 |
| Jarron Wiggins | 07:49–15:34 | 7.2 | 5 | 3 | 0.69 | 80% | 2 |
| Marquan Gates | 11:33–16:33 | 5.0 | 5 | 2 | 1.00 | 66% | 3 |
| Ernest Patterson | 08:28–15:30 | 6.5 | 4 | 4 | 0.61 | 90% | 2 |

Example SA timelines to check in the app:
- **SA-1074747** (`08pPb000009eiefIAA`). Created 14:05 ET by Mulesoft (Marcus Gibson). Platform Integration
  User reshuffled it 5 times (Marquan Gates → Jarron Wiggins → Antonio Hatch → Jarron Wiggins → Marquan
  Gates). Paige White finally assigned Jacob Schaich at 14:38. Dispatched 14:39, En Route 15:42, On Location
  15:54. Response 109 min vs PTA 75. Picks = 7, `OPTIMIZER_CHURN`. Not a bounce: it was never dispatched
  before the final pick.
- **SA-1074927** (`08pPb000009eonJIAQ`). FSL picked Jacob Schaich, then Marquan Gates, and it was dispatched
  15:02. Paige White pulled it back 15:17 (Dispatched → Spotted) and assigned Antonio Hatch Jr. Real driver
  bounce.
- **SA-1074934** (`08pPb000009eoybIAA`). Created in 053 - MICHAEL BELLRENG (Towbook-053), Towbook accepted
  it, and 45 min later Paige White moved it to 100 and assigned Mike Klotz. Inbound cascade.

### 6.2 Secondary: 076DO, 2026-08-31 (On-Platform contractors; 208 member SAs)

PTA met 124/185 = 67%; median response 62 min.

- **Final source:** Integration 70, Garage dispatcher 46 (Todd Kryszak), Human 45, FSL 45.
- **Distance:** closest qualified picked 55/204 = 27%; extra miles Σ 978.
- **Qualified-available-not-picked:** closer and idle 65/195; closer and less loaded 34/195.
- **Load:** idle-while-waiting 42.5 h (37.6 h within 15 mi). 26 drivers on shift ≥ 1 h; load spread 1.5;
  jobs/h 0.59 to 1.43.
- **Examples:**
  - SA-1020203: assigned to William Bundschuh, 4.1 mi, 1 open job; John Szpara was idle at 1.1 mi.
  - SA-1020257: Todd Kryszak picked Daniel Brusie at 35.3 mi; the closest qualified driver was at 1.8 mi.

**Contractor caveat C3:** a contractor who is logged in with no AAA job may be doing non-AAA work, which is
invisible to SF. So "idle" for `on_platform_contractor` is an upper bound. Label it that way.

### 6.3 Towbook example: 076DO, 2026-09-24 (229 member SAs)

- **Arrival:** On Location from history n=208, median 72 min. PTA met 88/208 = 42%. Do not use
  `ActualStartTime` (S6).
- **Drivers:** 25 Off-Platform drivers, top Owen Potycz 15, median 8.
- **Inbound moves:** 22, of which **13 came from 100 - WNY FLEET** (Fleet bounced work out to Towbook that day).
- **Who touched assignments:** IT System User 167, Mulesoft 114, Replicant 46, Platform Integration User 21,
  plus 34 Membership Users (1 to 8 rows each).
- **View:** workload view only, no scheduler grade.

---

## 7. Decision audit (`architecture.md` §7)

### 7.1 Codes, precedence, failure set

Each SA gets one primary code, taken from the first match in the order below, plus all matching flags.
Codes come from the **final decision** at `t_asg`. Precedence:

| # | Code | Counts as scheduler failure? | Plain meaning |
|---|---|---|---|
| 1 | `NOT_GRADED_TOWBOOK` | — | Towbook channel |
| 2 | `NOT_GRADED_CANCELED_PRE_ASSIGN` | — | no driver ever assigned |
| 3 | `INBOUND_CASCADE` | no (context) | the call arrived from another garage; its clock started elsewhere |
| 4 | `BOUNCED` | **yes** | the driver was pulled back or changed after dispatch |
| 5 | `NOT_GRADED_INSUFFICIENT_DATA` | — | no fresh GPS for the picked driver |
| 6 | `STACKED` | **yes** | picked a driver who already had work while a closer qualified driver sat idle |
| 7 | `FAR_PICK` | **yes** | picked a driver far beyond the closest free qualified driver |
| 8 | `LATE_DESPITE_CAPACITY` | **yes** | PTA missed although a qualified driver was free nearby before assignment or while the call sat queued |
| 9 | `LATE_EXECUTION` | no (driver side) | a sound, quick pick to a free driver, and PTA still missed |
| 10 | `CAPACITY_SHORT` | no (capacity) | PTA missed and no qualified driver was free nearby |
| 11 | `GOOD_NO_ARRIVAL` | no | sound decision; the call was canceled before arrival |
| 12 | `GOOD` | no | sound decision, PTA met (or no PTA) |

Flags (non-exclusive; pattern dimensions, never primary):

| Flag | Meaning |
|---|---|
| `BYPASSED_OPTIMIZER` | final actor is INTEGRATION, HUMAN or GARAGE_DISPATCHER |
| `HUMAN_FINAL` | final actor is HUMAN |
| `OPTIMIZER_CHURN` | `n_pre` ≥ 3 |
| `SLOW_RELEASE` | `t_disp − t_asg` > 10 min |
| `MISSED_REBALANCE` | queued on a busy driver while a qualified closer-or-equal driver was idle ≥ 10 consecutive min before `t_er` |
| `SKILL_MISMATCH` | the pick fails S9 using S9-T truck timing. Not raised when qualification is `unknown` (driver never logged in before En Route); `ASSIGNED_OFF_SHIFT` covers that case |
| `ASSIGNED_OFF_SHIFT` | `t_asg` is outside the driver's login window |

Why `BYPASSED_OPTIMIZER` is a flag and not a primary code: it says *who* decided, not *how well*. As a
primary code it would hide 70 of 90 decisions on 9/28 from the quality grade. The pattern view answers
"do bypassed decisions fail more?" with it as a dimension.

### 7.2 Per-code logic (inputs = §7.3 features)

- **INBOUND_CASCADE:** `terr_moves_in ≥ 1`. The pre-move time is shown as evidence.
- **BOUNCED:** `pullbacks ≥ 1 OR reassign_after_dispatch ≥ 1`. Evidence: the actor of the pullback.
- **STACKED:** `pick_open_jobs ≥ params.min_open_on_pick (1)` AND ≥ `params.min_idle_alternatives (1)`
  candidates with `open_jobs = 0` AND `miles < pick_miles − params.closer_by_mi (0)`.
- **FAR_PICK:** a free candidate exists and is not the pick AND
  `pick_miles − closest_free_miles > params.extra_mi (5.0)`.
- **LATE_DESPITE_CAPACITY:** `pta_met = false` AND (`MISSED_REBALANCE` OR at some 2-minute sample in
  [created, `t_asg`] a free qualified candidate existed with `miles ≤ pick_miles + params.extra_mi`).
- **LATE_EXECUTION:** `pta_met = false` AND `pick_open_jobs = 0` AND
  `t_asg − created ≤ params.quick_assign_min (10)`.
- **CAPACITY_SHORT:** `pta_met = false`, otherwise.
- **GOOD_NO_ARRIVAL:** no arrival and none of the above. **GOOD:** none of the above.

### 7.3 Features to add to Dan's §7.3 list

| Feature | Source |
|---|---|
| `final_actor`, `final_actor_class`, `first_actor_class`, `ar_creator` | B3/B4 (replaces `assign_source` = AR.CreatedBy) |
| `decision_ts` | `t_asg` |
| `n_pre_dispatch_picks`, `pullbacks`, `reassign_after_dispatch` | B2/B3 |
| `terr_moves_in`, `terr_moves_out` | S5 |
| `pick_miles`, `pick_open_jobs`, `closest_q_miles`, `closest_free_q_miles` | B6 at `t_asg` |
| `idle_q_closer_count`, `less_loaded_q_closer_count` | B6 |
| `pick_qualified`, `assigned_off_shift` | S9, S8 |
| `queue_wait_min`, `release_min`, `decide_min` | B2/B3 |
| `on_shift_drivers`, `open_sas_at_decision`, `demand_level` | demand = open scored SAs ÷ on-shift drivers at `t_asg`; bands [0, 0.5, 1, 2] |
| `distance_band` | on `pick_miles`; bands [0, 3, 7, 15, 30] |

Pattern dimensions to aggregate over many days:
- hour_et, dow
- call_class / work_type / primary skill
- final_actor_class and final_actor
- first_actor_class
- driver
- distance_band
- zone (postal code)
- demand_level
- channel
- pairs: hour × final_actor_class, demand_level × hour, call_class × final_actor_class, driver × hour

### 7.4 Verdict distribution on the primary day (WNY 100, 2026-09-28, n = 90)

| Code | n | Example SAs (decision ET · final actor → driver · pick mi / open · closest qualified · response vs PTA) |
|---|---|---|
| GOOD | 54 | SA-1073520 `08pPb000009e5a5IAA`: 07:34 Mulesoft → Arthur Yates, 8.3 mi / 0, is closest, 34 vs 60 · SA-1073522 `08pPb000009e5gXIAQ`: 07:35 Mulesoft → Arthur Yates, 6.5 / 1, is closest, 58 vs 60 · SA-1073550 `08pPb000009e67xIAA`: 07:47 Replicant → Isaiah Carter-Faires, 3.9 / 0, closest Arthur 1.1 mi but busy, 40 vs 60 |
| CAPACITY_SHORT | 10 | SA-1073632 `08pPb000009e7gjIAA`: 08:18 Replicant → Isaiah Carter-Faires, 3.2 / 1, is closest, 64 vs 60 · SA-1074304 `08pPb000009eT1JIAU`: 11:50 FSL → Isaiah Carter-Faires, 3.6 / 1, 94 vs 60 · SA-1074449 `08pPb000009eXT7IAM`: 12:20 Replicant → Arthur Yates, 1.9 / 1, 66 vs 60 |
| BOUNCED | 7 | SA-1074741 `08pPb000009eiGTIAY` (Lynn Pilarski pullback, 6 picks, 83 vs 75) · SA-1074927 `08pPb000009eonJIAQ` (Paige White pullback) · SA-1075074 `08pPb000009euMTIAY` (3 pullbacks, canceled en route) |
| INBOUND_CASCADE | 7 | SA-1074934 `08pPb000009eoybIAA`, SA-1075021 `08pPb000009esNtIAI`, SA-1075125 `08pPb000009ewUjIAI` (all from 053 Towbook) |
| GOOD_NO_ARRIVAL | 6 | SA-1074161 `08pPb000009eLOkIAM`, SA-1074252 `08pPb000009eQoDIAU`, SA-1075312 `08pPb000009f3b3IAA` |
| LATE_DESPITE_CAPACITY | 2 | SA-1074458 `08pPb000009eXw9IAE`: FSL → Ernest Patterson, 7.3 / 1, 146 vs 60, `MISSED_REBALANCE` · SA-1075605 `08pPb000009fCODIA2`: FSL → Jacob Schaich, 3.8 / 1, closest Antonio 1.7, 112 vs 75 |
| LATE_EXECUTION | 2 | SA-1074531 `08pPb000009eaafIAA` (6.4 mi, free, 65 vs 60) · SA-1074664 `08pPb000009efAXIAY` (6.5 mi, free, 65 vs 60) |
| NOT_GRADED_INSUFFICIENT_DATA | 2 | SA-1075259 `08pPb000009f0y9IAA`, SA-1075278 `08pPb000009f1nlIAA` (Kenneth Kirkendoll: no fresh GPS) |
| STACKED / FAR_PICK | 0 / 0 | none on this day. Examples from 076DO 8/31: STACKED SA-1020203 `08pPb000009DZsPIAW`, SA-1020212 `08pPb000009Da25IAC`, SA-1020277 `08pPb000009Db7pIAC`; FAR_PICK SA-1020257 `08pPb000009Daq5IAC`, SA-1020265 `08pPb000009Day9IAC`, SA-1020570 `08pPb000009DhpxIAC` |

- **Flags (9/28):** BYPASSED_OPTIMIZER 70, HUMAN_FINAL 31, OPTIMIZER_CHURN 15, SLOW_RELEASE 12,
  SKILL_MISMATCH **1** after the S9-T correction (2026-10-03): SA-1075493, a Locksmith call given to a driver with no locksmith skill or capability. The earlier count of 3 was wrong: it included Kenneth Kirkendoll's SA-1075259 and SA-1075278, which were assigned 16 min before his 21:27:40Z login, and it missed Jacob Schaich's SA-1074747 and SA-1074862, assigned 3.0 and 1.4 min before his 18:41:38Z login. Ruby's 5 is the correct reading of the old rule. Under S9-T, all four are qualified by the truck they logged into before En Route. MISSED_REBALANCE 2.
- **Scheduler failure rate 9/28:** (7 + 2) / 81 graded = 11%. **076DO 8/31:** (35 + 26 + 15 + 17) / 195 = 48%.
- **Hour pattern 9/28:** PTA met 1/4 at 19:00 ET (CAPACITY_SHORT 3 of 5, 4.5 drivers on shift), and 3/6 at
  12:00.

### 7.5 What the verdicts cannot see (state on screen)

- Availability is *observed*, not counterfactual (Dan's §7.1 caveat).
- Contractor non-AAA work (C3).
- Skills and truck capabilities are current values; SF keeps no history of them.
- Distances are straight-line.
- Open jobs in other territories: verified 0 for 9/28 (all 82 AR of garage-100 drivers were in 100), but not
  guaranteed on other days.

### 7.6 r1 thresholds JSON

```jsonc
{
  "rules_version": "r1", "engine_version": "e1",
  "precedence": ["NOT_GRADED_TOWBOOK","NOT_GRADED_CANCELED_PRE_ASSIGN","INBOUND_CASCADE","BOUNCED",
                 "NOT_GRADED_INSUFFICIENT_DATA","STACKED","FAR_PICK","LATE_DESPITE_CAPACITY",
                 "LATE_EXECUTION","CAPACITY_SHORT","GOOD_NO_ARRIVAL","GOOD"],
  "failure_codes": ["BOUNCED","STACKED","FAR_PICK","LATE_DESPITE_CAPACITY"],
  "context_codes": ["INBOUND_CASCADE","CAPACITY_SHORT","LATE_EXECUTION"],
  "actors": {
    "fsl_engine": ["Platform Integration User","FSL System User"],
    "integration": ["Mulesoft Integration","Replicant Integration User","IT System User"],
    "towbook_sync_profiles": ["Towbook Integrations"],
    "garage_dispatcher_profiles": ["Partner Community User"],
    "human_profiles": ["Membership User"]
  },
  "candidate": { "gps_max_age_min": 30, "gps_forward_slack_min": 5,
                 "qualified_rule": "woli_skills_subset_of_sr_skills_plus_truck_caps" },
  "params": {
    "STACKED":   { "min_open_on_pick": 1, "min_idle_alternatives": 1, "closer_by_mi": 0.0 },
    "FAR_PICK":  { "extra_mi": 5.0 },
    "LATE_DESPITE_CAPACITY": { "pta_grace_min": 0, "sample_step_min": 2 },
    "MISSED_REBALANCE": { "min_idle_run_min": 10 },
    "LATE_EXECUTION": { "quick_assign_min": 10 },
    "OPTIMIZER_CHURN": { "min_pre_dispatch_picks": 3 },
    "SLOW_RELEASE": { "release_min": 10 },
    "M05": { "wait_min": 10, "reach_mi": 15 },
    "M20": { "closer_by_mi": 0.5 }
  },
  "bands": { "distance_mi": [0,3,7,15,30], "demand_open_per_driver": [0,0.5,1.0,2.0], "hour_blocks": "hourly" },
  "metric_bands": {
    "M02": {"good":[0,1.5],"watch":[1.5,2.0]}, "M05": {"good":[0,0.05],"watch":[0.05,0.10]},
    "M06": {"good":[0,2],"watch":[2,3]},       "M08": {"good":[0,30],"watch":[30,60]},
    "M10": {"good":[0,0.05],"watch":[0.05,0.15]}, "M13": {"good":[0.85,1],"watch":[0.75,0.85]},
    "M16": {"good":[0,0.05],"watch":[0.05,0.10]}, "M17": {"good":[0.80,1],"watch":[0.65,0.80]},
    "M19": {"good":[0.80,1],"watch":[0.65,0.80]}, "M20": {"good":[0,0.05],"watch":[0.05,0.15]},
    "M21": {"good":[0.90,1],"watch":[0.75,0.90]}
  },
  "min_support": 20
}
```

How sensitive the results are to the thresholds: on 9/28, FAR_PICK at `extra_mi` 5 → 0 SAs and at 2 → about 1 SA.
Other thresholds have not been sensitivity-tested yet. Re-check them after 30+ garage-days.

### 7.7 r2: grade PTA against the original promise (decision O1, 2026-10-04)

The product owner decided (call-story D2) that the member's promise is the **original** PTA. For consistency the report
card adds **r2**. **r1 stays, unchanged, for comparison.** Every verdict row already records its rules version.

**The only change from r1** is the PTA deadline used by `pta_met` (and so M13, LATE_DESPITE_CAPACITY, LATE_EXECUTION
and CAPACITY_SHORT):
- `due_initial = ERS_Spotting_Datetime__c + initial_pta`.
- `initial_pta` = the last `ERS_PTA__c` history value written **≤ 5 s after `CreatedDate`**. It is the same rule as
  call-story cs1 §4.4, so the story and the card agree.
  - Same-second rows are chained Old → New (the 90 → 60 pair at creation).
  - With no history row, use the stored `ERS_PTA__c`.
  - Skip ≤ 0 and ≥ 999.
- The spotting basis is recovered without a new pull: `ERS_PTA_Due__c − ERS_PTA__c` = `ERS_Spotting_Datetime__c`.
- Everything else (thresholds, precedence, flags, actors) is r1.

```jsonc
// r2 = r1 + this block (rules_version "r2")
{ "rules_version": "r2", "pta_basis": "initial", "pta_initial_window_sec": 5 }
```

**Build impact:**
- The snapshot needs the `ERS_PTA__c` history rows. Add `'ERS_PTA__c'` to the Q2 `Field IN (...)` list in
  `report_card_build.py`, a builder bump (`rc-build-1.1`).
- Store `initial_pta` per SA in the snapshot (`pta_initial_min`, `pta_initial_src`).
- Existing snapshots need a rebuild before they can be scored with r2. Until then r2 = "not available" for that day,
  never silently r1.

**Why 5 s and not "within a couple of minutes":**
- On 9/28 five WNY Fleet calls had PTA 60 → 120 written by `Integrations Towbook` **15–52 s after creation**.
- In each case the call was offered to a Towbook garage first.
- A 2-minute window would have treated those re-bases as the promise.

**Effect, measured on the 20 ROI-sample garage-days** (`roi-baseline.md`; script `validation/roi/r2.py`; 0 extra SF
calls, using pulled history):

| Scope | PTA met r1 (final) | PTA met r2 (original) | Verdict codes that change |
|---|---|---|---|
| **WNY 100, 2026-09-28** | **65/82 = 79.3%** | **64/82 = 78.0%** | **0** |
| WNY 100, 10 days (Sep) | 605/739 | 604/739 | 0 of 821 |
| 076DO, 10 days (Aug) | 912/1,419 | 910/1,419 | 0 of 1,587 |

- The 9/28 flip is SA-1075021 `08pPb000009esNtIAI`:
  - PTA 60 → 120 by Integrations Towbook at +15 s.
  - Arrived at 69 min: met under r1, missed under r2.
- **No code changes**, because every PTA re-base in the sample (20 of 2,408 calls) was written by `Integrations Towbook`
  on an **INBOUND_CASCADE** call. INBOUND_CASCADE comes before the PTA-based codes in precedence.
- So on the FSL platform r2 moves M13 by ≤ 0.2 points and no verdicts. It matters for Towbook-touched calls, which is
  where the call story uses it.
- Recommendation:
  - Make r2 the default once the builder bump ships, so the card and the story never disagree.
  - Keep r1 selectable for audit.

---

## 8. Headline metric: "a qualified driver was available but not picked"

**Definition.** At the final decision time, there is a driver who is:
- an active territory member that day,
- logged into a truck,
- not in a `ResourceAbsence`,
- qualified under S9,
- with a GPS fix ≤ 30 min old,
- more than 0.5 mi closer than the pick,
- and either idle (0 open jobs) or less loaded (fewer open jobs than the pick).

"Not already on a higher-priority job" is covered by the open-jobs count. Open jobs are treated as committed
regardless of priority, because `ERS_Dynamic_Priority__c` is not part of this check (flagged in §12).

| Day | Graded decisions | Closer + idle | Closer + less loaded | Same test at first-pick time |
|---|---|---|---|---|
| WNY 100, 9/28 | 80 | 3 (4%) | 0 | 3 idle / 5 less loaded of 77 |
| 076DO, 8/31 | 195 | 65 (33%) | 34 (17%) | 63 / 43 of 187 |

How the skill rule changes the 076DO result (closer + idle): strict SR-skills 0, SR-skills-overlap 6,
**SR skills + truck caps 65**, no skill gate 93. The truck-capability rule is the only one that matches
how dispatch actually behaves (S9).

---

## 9. Validation of existing code

**`simulate_day` (`backend/simulator.py`). Do not reuse as-is for grading:**
1. **No on-shift gate and no GPS age limit.** `gps_at_time` accepts any old fix, so off-shift drivers become
   "closest". On 9/28, 36 of 88 SAs had a closest candidate with GPS older than 60 min. Closest picked:
   22% vs 44% with the gates. On 8/31: 8% vs 27%.
2. **The skill gate reads WorkType `SkillRequirement`, which has 0 rows.** Requirements are on the WOLI. The
   gate is a no-op.
3. **It compares the final AR driver against the closest driver at the *first* assignment time.**
4. **It uses a UTC-midnight day window and the `ERS_Dispatch_Method__c` channel** (S1, S2).
5. **It runs 4 queries in parallel (`sf_parallel`)** against the sequential guidance.

**`dispatch_utils`:**
- `build_assign_steps` / `is_on_truck` already implement the truck gate. Reuse them with
  `truck_login_hist`.
- `parse_assign_events` is correct (name rows, ordering).
- `classify_dispatch` calls a single human assignment "auto". Keep it out of the report card; use B4 actor
  classes.
- `_SYSTEM_USERS` lumps the FSL engine in with integrations.

**`optimizer_parser` / `opt_driver_verdicts`:**
- These are **FSLAPP reconstructions**, not FSL output. Non-winner distance = home haversine ÷ 25 mph, and
  "skill" exclusion uses a strict subset of `Resources` skills.
- Only `action`, `unscheduled_reason` and the winner's travel estimate are optimizer output. There are no
  candidate scores.
- Calibrate on top-1 winner only (Dan's §18.4 is right).
- Check whether the request JSON skills include truck capabilities. If not, its "excluded: skill" labels will
  be wrong for most drivers (S9).

---

## 10. Scheduling policy and optimizer data (for the shadow twin)

- **Territory flags:**
  - 100 WNY Fleet: `RSO_Automation_Active__c = true`, `ERS_Auto_Schedule__c = true`.
  - 076DO today: both false.
- **Policies that ran for WNY 100 on 9/28** (`FSL__Optimization_Request__c.FSL__Scheduling_Policy__c`):

| Policy (Id) | Runs | Goals (`FSL__Scheduling_Policy_Goal__c` weight) | Work rules |
|---|---|---|---|
| Copy of Highest Priority (`a22Pb0000088ISzIAM`) | 257 In-Day + 194 RSO | ASAP High Priority 120000, ASAP 60000, Minimize Travel 10 | Active Resources; Passenger Transport Tows by Truck Passenger Space; Due Date; Earliest Start Permitted; Excluded Resources; Fleet Driver Resource Availability- No Break; Match Skills; Match Territory; Off Platform Contractors Resource Availability; Off Schedule Platform Contractors Resource Availability; On Schedule Platform Contractors Resource Availability; PTA Window Work Rule; Required Service Resource; Scheduled End; Scheduled Start |
| RSO Login (`a22Pb00000AjQNBIA3`) | 3 RSO | ASAP High Priority 60000, ASAP 45000, Minimize Travel 10 | as above, minus Fleet No-Break and PTA Window, plus Resource Availability and Maximum Travel From Home is 50 Mins |
| Highest priority (`a22Pb000001KlCuIAK`) | 5 RSO | ASAP 9000, Minimize Travel 1000 | adds Working Territories and Maximum Travel From Home 10 to 60 min |

- **What the weights mean.** Travel is weighted about 1/6,000 to 1/12,000 of ASAP in the active policy, so
  the optimizer picks *soonest available*, not *closest*. That fits FSL-final closest-picked at 7/20 (35%)
  on 9/28 and 10/45 (22%) for 076DO on 8/31.
- **Workload balance.** There is no workload-balance goal type in this org. `FSL__Service_Goal__c` types:
  ASAP, ASAP High Priority, Minimize Travel, Minimize Overtime, Preferred Service Resource, Resource Priority,
  Same Site, Skill Level, Skill Preferences. A balance objective is `fsl_native=false` here.
- **The optimizer trail in SF persists independently of Postgres:**
  - `FSL__Optimization_Request__c`: 291,834 rows since 2024-12-13.
  - `FSL__Territory_Optimization_Request__c`: links a run to its territory.
  - `Optimization_Log__c`: trigger reason, config, resource, territory. 9/28 WNY 100: Idle Territory
    Optimization 161, Past-Start SA Nudge 69, Idle Resource Preemptive RSO 62, SA_Completed 47,
    ERS_Number_of_Seats Increased 13, cancels 6.
  - Snapshot these (about 3 light queries per garage-day) so attribution of FSL_ENGINE decisions never
    depends on Postgres retention.
- **Postgres `opt_*` coverage: not checked by me.** The user's standing rule forbids pointing tools at a
  production database without explicit approval, and Kathy owns that check (§18.5). With the default
  3-day retention, 9/28 is probably already purged. The SF trail above covers the cross-check.

## 10A. Policy diagnosis (why findings happen, pointed at configuration)

### 10A.1 What applies to the pilot garage (100 WNY Fleet), read-only, 2026-10-03

| Item | Value | Source |
|---|---|---|
| Territory automation | `RSO_Automation_Active__c = true`, `ERS_Auto_Schedule__c = true` | ServiceTerritory |
| Policy actually run (9/28) | **Copy of Highest Priority** `a22Pb0000088ISzIAM`: 451 of 459 runs (257 In-Day, 194 RSO). RSO Login 3, Highest priority 5 | `FSL__Optimization_Request__c.FSL__Scheduling_Policy__c` via `FSL__Territory_Optimization_Request__c` + `FSL__Service_Resource__c` |
| In-Day run filter | `FSL__Filter_By_Boolean__c = ERS_Auto_Assign__c`. Only SAs with that flag are optimizable | OR sample |
| Objectives (weight) | ASAP High Priority **120000**, ASAP **60000**, Minimize Travel **10**. No Resource Priority, Skill Level, Preferred Resource or Minimize Overtime goal | `FSL__Scheduling_Policy_Goal__c` |
| Work rules (type) | Match Skills (Match Skills) · Match Territory (Match Territory) · Active Resources (Match Boolean) · Passenger Transport Tows by Truck Passenger Space (Match Fields) · Excluded Resources · Required Service Resource · 4× Service Resource Availability (Fleet No-Break; Off-Platform; Off-Schedule and On-Schedule Platform Contractors) · 5× Match Time (Earliest Start, Due Date, Scheduled Start/End, PTA Window) | `FSL__Scheduling_Policy_Work_Rule__c` → `FSL__Work_Rule__r.RecordType.Name`. Rule parameter fields are not visible to the API user (only Id/Name/RecordType come back), so rule settings such as the availability travel buffer and the skill-level check cannot be read |
| No max-travel rule in the main policy | "Maximum Travel From Home" exists only in RSO Login (50 min) and Highest priority (10 to 60 min) | same |
| Territory membership | All 20 WNY drivers have exactly one membership, type **P** (no Secondary/Relocation) | ServiceTerritoryMember |
| Resource tuning | `FSL__Efficiency__c`, `FSL__Priority__c`, `FSL__Travel_Speed__c` are **null for all 20**; `AAA_ERS_MaxTravelDuration__c = Unlimited` | ServiceResource |
| Org-wide goal types available | ASAP, Minimize Travel, Minimize Overtime, Preferred Service Resource, Resource Priority, Same Site, Skill Level, Skill Preferences. **No balance or workload goal** | `FSL__Service_Goal__c` |

076DO on 8/31 ran the same `Copy of Highest Priority` family through RSO (memory note
ers-rso-mechanism-and-stacking). Since 9/1 it has no FSL policy at all: Towbook, flags false.

### 10A.2 Finding → likely config cause → config lever

Each row is a *hypothesis the AI may state*, only when its trigger and the cited config fact are both in
the fact sheet. Wording: "consistent with", never "caused by".

| Finding (trigger) | Likely configuration cause (fact to cite) | Lever (§12 id) |
|---|---|---|
| STACKED or MISSED_REBALANCE high, actor FSL_ENGINE | No workload or balance objective exists in the org's goal types; RSO (`ResourceDayOptimization`) works on one resource at a time and never pulls work off a busy driver | L03 territory-wide rebalance; custom objective = not FSL-native |
| STACKED high, actor INTEGRATION | The selection happens outside FSL (Mulesoft/IT System User write the AR directly); no policy is evaluated (`FSL__Scheduling_Policy_Used__c` null on 90/90) | L01, L02 |
| FAR_PICK, or closest-picked low, actor FSL_ENGINE | Minimize Travel weight 10 vs ASAP 60000/120000: travel is about 1/6,000 of the score, so FSL picks "soonest", not "closest". Seen: FSL-final closest 7/20 on 9/28, 10/45 on 8/31 | L04 raise the Minimize Travel weight |
| FAR_PICK with very long distances (e.g. 35 mi) | No Maximum Travel From Home rule in the main policy; `AAA_ERS_MaxTravelDuration__c = Unlimited` | add a max-travel work rule (new lever L12) |
| OPTIMIZER_CHURN, SLOW_RELEASE | In-Day runs every few minutes on unpinned, undispatched SAs (257 territory runs plus 202 RSO runs that day; triggers: Idle Territory Optimization 161, Past-Start SA Nudge 69, Idle Resource Preemptive RSO 62) | L05 pin or commit after the first pick |
| SKILL_MISMATCH (human picks) / "excluded: skill" noise | Match Skills checks `ServiceResourceSkill`, but the real capability lives on `Asset.ERS_Truck_Capabilities__c` (S9). Integration picks match only when truck caps are added | L10 sync truck capabilities into skills, or align the rule |
| Calls never optimized (FSL touch low) | In-Day only takes SAs where `ERS_Auto_Assign__c = true` (filter boolean) | L02, or review the filter |
| Load imbalance between equal-shift drivers | `FSL__Priority__c` and `FSL__Efficiency__c` are null (no preference by design). So imbalance comes from ASAP timing plus RSO re-triggers on idle drivers, not from resource settings | L03 |
| Same driver keeps winning after each job | RSO triggers `SA_Completed` and `Idle Resource Preemptive RSO` refill the driver who just freed up | L03 |
| Off-shift assignments (ASSIGNED_OFF_SHIFT) | Availability work rules use FSL operating hours or absences, not truck login (Shift object empty) | L11 / availability rule review |
| Cross-territory gaps | All members are type P with no secondary territories, so FSL cannot borrow neighbouring drivers; rescues are manual (INBOUND_CASCADE by Paige White) | add Secondary memberships (new lever L13) |

Two new whitelist entries:
- **L12** "Add a Maximum Travel From Home work rule to the active policy" (FSL admin, native).
- **L13** "Add Secondary territory memberships for neighbouring garages" (FSL admin, native).

### 10A.3 Engine (ESO vs legacy) and what-if feasibility

- **Engine: not verifiable through the API.** FSL's settings are protected managed-package settings. No
  `FSL__*` custom-setting object is visible, and work-rule parameter fields are hidden.
- **Indirect signs point to Enhanced Scheduling and Optimization:**
  - `FSL__Optimization_Data__c` has 0 rows since 9/28 and `FSL__Optimization_Data__c` on requests is null.
    The legacy engine stores run data there.
  - AR travel distance is 1.42× straight line, consistent with street-level routing.
  - The persona file says ESO is on for WNY Fleet.
  - Confirm in Setup → Field Service Settings → Scheduling → "Enhanced Scheduling and Optimization".
- **New finding: optimization runs no longer carry Request/Response files.** 0 `ContentDocumentLink`s on 60
  WNY runs from 9/28, and 0 on the 40 most recent completed runs (to 2026-10-04 02:55 UTC).
  `optimizer_sync` reads exactly those files. So the `opt_*` tables are probably not being filled at all,
  whatever the retention setting. Kathy should confirm `max(run_at)`. The file-logging option in FSL
  settings may have been turned off.
- **Org:** production. `Organization.IsSandbox = false`, Unlimited Edition, instance USA326.
  `SandboxInfo` is not queryable from this user. UAT and test orgs exist (FleetPulse Canvas sign-in accepts
  test, UAT and prod; release notes 2026-09-28 `.invalid` sandbox emails), but I cannot list them from here.
- **Rollback-based what-if** (call FSL Get Candidates or Schedule, then roll back) is **never acceptable in
  production**: SELECT-only rule, and FSL callouts are not reliably rolled back. It is only conceivable in a
  sandbox. Even then the sandbox lacks production's live GPS, logins and open-job state for past days.
  Recommendation: keep the offline twin (Dan §18) as the what-if path. Use a sandbox only to calibrate
  policy scoring on synthetic cases, and only with the user's explicit approval.

---

## 11. Answers to Dan's open questions

| Q | Answer |
|---|---|
| Is Shift populated for Fleet? | **No.** Use AssetHistory truck login + ResourceAbsence (S8). Keep Q5 as optional, off by default |
| Include calls bounced OUT of the garage? | **Yes, as M15-out (counted and listed, not graded in this garage).** 9/24: 13 SAs moved 100 → 076DO; 9/28: 0 out of 100 (checked 1,130 territory-history rows under parent WNY M). Method: one region-level SAHistory pull per day (`Field='ServiceTerritory'`, CreatedDate in window, parent region), filtering OldValue in Python, shared by all garages in that region during backfill |
| Is the integration-account list correct? | Names correct, grouping **wrong**: Platform Integration User and FSL System User are the FSL engine (B4). Add TOWBOOK_SYNC, DRIVER and GARAGE_DISPATCHER classes. Dan's r1 `BYPASSED_OPTIMIZER.system_accounts` would flag the optimizer's own picks |
| Which pilot Fleet garage? | **100 - WESTERN NEW YORK FLEET**, validated on 2026-09-28. Alternative: 800 Central |
| Optimizer retention / which days have opt rows? | Not queried (see §10). The verdicts do not need Postgres |
| ESO or legacy engine? | Not readable via the API; signs point to ESO (§10A.3). Run files are missing, so the opt_* sync is likely starved |
| FSL Street Level Routing setting? | Setting not read. Indirect evidence: AR estimated distance ÷ straight line = 1.42 median, which suggests road routing. Kathy or the user can confirm in FSL Settings > Routing |
| Is a balance objective FSL-native? | Not in this org (§10) |
| Driver names in AI input / supervisor access? | User decision. My recommendation: anonymise drivers in AI input, show real names in the UI to permitted roles |

---

## 12. Recommendation lever whitelist (`architecture.md` §11.3)

| lever_id | Lever | Triggered by | Owner | FSL-native? |
|---|---|---|---|---|
| L01 | Add an open-jobs penalty or cap to the integration's (Mulesoft/IT System User) driver selection | STACKED, FAR_PICK where actor = INTEGRATION | Mulesoft / integration team | no (external) |
| L02 | Route integration picks through FSL Schedule with a policy instead of a direct write | BYPASSED_OPTIMIZER share | Dispatch systems + Kathy | yes |
| L03 | Add a territory-wide rebalance pass for queued SAs when a qualified driver goes idle (RSO is single-resource) | MISSED_REBALANCE, LATE_DESPITE_CAPACITY | FSL admin (Apex RSO) | partly (custom Apex) |
| L04 | Rebalance the `Copy of Highest Priority` weights (raise Minimize Travel vs ASAP) | FAR_PICK with actor = FSL_ENGINE | FSL admin | yes |
| L05 | Limit In-Day reshuffles of not-yet-dispatched SAs (commit after first pick or near PTA) | OPTIMIZER_CHURN, SLOW_RELEASE | FSL admin | yes (pinning / commit mode) |
| L06 | Dispatcher pull-back review and coaching | BOUNCED with HUMAN actor | Dispatch supervisor | n/a |
| L07 | Add capacity or shift coverage in the hour blocks where CAPACITY_SHORT concentrates | CAPACITY_SHORT | Ops / workforce | n/a |
| L08 | Faster rescue from Towbook garages / priority-matrix review | INBOUND_CASCADE | Ops + priority matrix owner | n/a |
| L09 | Driver execution coaching (accept → en route, travel) | LATE_EXECUTION | Fleet supervisor | n/a |
| L10 | Fix skill / truck-capability data or the assignment rule humans use | SKILL_MISMATCH | Fleet admin | n/a |
| L12 | Add a Maximum Travel From Home work rule to the active policy | FAR_PICK long distances | FSL admin | yes |
| L13 | Add Secondary territory memberships for neighbouring garages | INBOUND_CASCADE, CAPACITY_SHORT | FSL admin | yes |
| L11 | Truck-login / GPS hygiene | NOT_GRADED_INSUFFICIENT_DATA, M21 | Fleet admin | n/a |

---

## 13. Assumptions that need user verification

1. **Pilot switch:** grade 100 - WNY FLEET instead of 076DO, and keep 076DO as the On-Platform example and the
   Towbook workload view.
2. **Platform Integration User = FSL optimizer.** The timing evidence is strong (48/48). Confirm with the FSL
   admin that no other process uses this account.
3. **Final decision = the last assignment-history actor** (not AR.CreatedBy). This overrides the project rule
   "Who dispatched = AssignedResource.CreatedBy" for this product. The rule is still valid for "who created
   the assignment record".
4. **Qualified = WOLI skills ⊆ SR skills ∪ current truck capabilities.** Truck capabilities have no history in
   SF.
5. **Pullback = driver bounce.** An optimizer reshuffle before dispatch is not a bounce; it is
   OPTIMIZER_CHURN.
6. **The PTA deadline uses `ERS_PTA_Due__c`** (spotting time + current PTA). For re-spotted calls this may move
   the deadline later.
7. **The PTA target for bands is 85%.** It is a placeholder; I need the business target.
8. **Contractor idle = upper bound** (C3).
9. **The Membership User profile includes non-dispatchers** (a driver, many touches on Towbook days). Should
   the HUMAN class be limited to a dispatcher roster?
10. **Open jobs ignore priority.** `ERS_Dynamic_Priority__c` could refine "available" later.

## 14. Limits and SF load used

- Two garage-days were pulled in full and one Towbook day partly. All queries were sequential: about 60 SOQL
  calls in total, the heaviest being 17k GPS rows. No DML.
- The `ServiceResourceHistory` `COUNT()` took 26 to 39 s on the first attempt and failed once; the retry
  succeeded. Dan's build plan should expect GPS to be the slow step.
- I did not query Postgres.
