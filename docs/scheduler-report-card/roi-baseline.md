# Scheduler Report Card: ROI baseline (what avoidable dispatch failures cost, measured)

Owner: Henry · 2026-10-04 · Rules r1 / engine e1 (`report_card_verdicts.py`), builder `rc-build-1.0` · Read-only Salesforce,
sequential · Scripts: `validation/roi/` · Status: **baseline for the business case. No dollars yet** (unit costs in section 8
come from the business, not Salesforce).

Sample: 20 garage-days built with Ruby's snapshot builder and scored with the shipping verdict rules.
- **100 WNY Fleet:** 8 weekdays + 2 weekend days in Sep 2026. 821 scored calls (Fleet).
- **076DO:** 8 weekdays + 2 weekend days in Aug 2026, before the 9/1 Towbook cutover. 1,587 scored calls (On-Platform Contractor).

Monthly totals = weekday average × weekdays + weekend average × weekend days: Sep = 21 + 9 (Labor Day counted as a weekend
day), Aug = 21 + 10.

---

## 1. The answer first

1. **The cost of avoidable dispatch failures depends on the channel. Lead the pitch with On-Platform Contractor garages.**
   - **076DO (contractors):** of the PTA misses owned by either the scheduler or staffing, **68% were the scheduler**
     (184 vs 86 calls) and **71% of those late minutes** (6,623 vs 2,692 min).
   - **WNY Fleet:** the reverse. **74% were staffing** (65 vs 23 calls) and **76% of the late minutes**. On Fleet, the
     scheduler mostly picks well (strict avoidable miles are about 5 per day). The value there is showing *when* the
     garage is short-staffed.
   - **Replicated on two more garages** (section 11, Sep 2026). **421 Action Towing**, the largest active On-Platform
     garage: **88% scheduler** (92% of late minutes; at least 57% if every ungraded late call were staffing). **800 Central
     Fleet:** 38% scheduler, 62% staffing. The channel pattern holds in all four garages.
2. **Per month at 076DO** (4,757 calls):
   - about **4,100 avoidable straight-line miles** (3,800 conservative),
   - **519 PTA misses** owned by the scheduler, about **18,200 member-minutes** past the promise,
   - **94 member cancellations** while a free qualified driver within 15 mi sat idle for 10+ min, or after a failed pick,
   - **720 idle qualified driver-hours** while a nearby call waited (an upper bound for contractors).
3. **Per month at WNY Fleet** (2,481 calls):
   - **175 avoidable miles**, 74 scheduler-owned misses (about 1,600 late minutes),
   - **44 member cancellations** in scheduler-owned delay,
   - **208 idle qualified driver-hours** while a call waited (8% of on-shift time).
4. **Two dispatch-process failures are bigger than bad picks, and the product exposes both:**
   - **Pull-backs and re-dispatch (BOUNCED)** are 24% (WNY) and 35% (076DO) of all late minutes. At 076DO the garage's
     own portal dispatcher made most of them.
   - **Inbound cascades** (the call started at another garage) are 25% of 076DO late minutes.
5. **PTA re-basing barely affects FSL-platform PTA numbers.** Only 3 of 2,158 graded calls (0.14%) were "met" only because
   the PTA was re-based. All 20 re-bases in the sample were written by `Integrations Towbook` on calls that first sat at a
   Towbook garage.
6. **Members notice.**
   - Calls the scheduler got wrong scored **70.5% "Totally satisfied" vs 84.9% for GOOD calls** at 076DO (n = 44 vs 126,
     p = 0.03).
   - A missed PTA costs **12 to 20 points** in both garages (pooled within garage: z = −4.2, p < 0.0001).
   - This is an association, from SMS-opted-in respondents only.

---

## 2. What was measured (definitions)

| # | Measure | Definition (source of truth) |
|---|---|---|
| 1 | Avoidable extra miles | Calls with code STACKED or FAR_PICK: picked driver's miles to the call minus the closest **free** (0 open jobs), on-shift, qualified roster driver's miles, both at the decision time (`ServiceResourceHistory` GPS ≤ 30 min old). **Straight-line (haversine), one-way approach miles, not road miles.** *Conservative* drops 8 picks of more than 15 mi whose En Route → On Location time implies more than 70 mph, meaning the driver did not start from that GPS point (mostly STACKED: they left from their previous job). *Broad* = every graded call with any closer free qualified driver > 0.5 mi (upper bound). |
| 2 | PTA-miss minutes by owner | `arrival − ERS_PTA_Due__c` on calls with `pta_met = false`. Arrival = `ActualStartTime` (real on the FSL platform). Owner from the r1 code: **scheduler** = LATE_DESPITE_CAPACITY, STACKED, FAR_PICK · **capacity/staffing** = CAPACITY_SHORT · **bounced** = BOUNCED · **inbound** = INBOUND_CASCADE · **driver** = LATE_EXECUTION. |
| 3 | Member cancels while waiting | End status Cancel Call (Not En Route / En Route) or Canceled, no On Location, and `ERS_Cancellation_Reason__c` ∈ {Member Could Not Wait, Member Found Own Service, Member got themselves going, Passerby Assisted, IVR Cancellation}. "Facility initiated" is excluded. **Scheduler-owned delay:** a failure code, or a free, on-shift, qualified driver (not the pick) within 15 mi with a fresh fix sat idle ≥ 10 consecutive min between created + 10 min and En Route or cancel. **Parked unassigned:** cancelled while `Spotted`, or ≥ 10 min in `Spotted`, or arrived from a `*SPOT*` territory. |
| 4 | Churn and pull-backs | Picks = `ERS_Assigned_Resource__c` name rows (spec S4). OPTIMIZER_CHURN = ≥ 3 picks before Dispatched. Pull-back = Status → Spotted after Dispatched/Accepted/En Route, with the actor class (B4) of whoever wrote it. |
| 5 | Idle qualified driver-hours | Spec H2 numerator: on-shift minutes (truck login minus absence) with 0 open jobs while ≥ 1 in-garage call waited (from created + 10 min until En Route), the driver was qualified for it and within 15 mi. Also the member view: call-hours waited while such a driver was idle nearby. |
| 6 | PTA met, original promise | r1 = `ERS_PTA_Due__c` (final). Original = spotting time + the last `ERS_PTA__c` history value written ≤ 5 s after creation (call-story cs1 / r2). |
| 7 | Satisfaction | `Survey_Result__c.ERS_Overall_Satisfaction__c` = "Totally satisfied" (case-insensitive), linked SA → WOLI (`ParentRecordId`) → `WorkOrderId` → `Survey_Result__c.ERS_Work_Order__c`. 464 surveys on 2,408 calls (19%), all with an overall score. |

---

## 3. Headline: month totals (extrapolated from the 10 sampled days)

| Measure / month | 100 WNY Fleet (Sep 2026) | 076DO On-Platform (Aug 2026) |
|---|---|---|
| Scored calls | 2,481 | 4,757 |
| **Avoidable extra miles, strict (straight-line)** | **175** | **4,106** (conservative 3,793) |
| Extra miles, broad upper bound | 550 | 7,020 |
| PTA misses, all | 399 | 1,509 |
| scheduler-owned | **74** | **519** |
| capacity / staffing (CAPACITY_SHORT) | 193 | 261 |
| bounced (pull-back / re-dispatch) | 76 | 430 |
| inbound cascade | 24 | 213 |
| driver (LATE_EXECUTION) | 27 | 49 |
| Late member-minutes past PTA, all | 9,338 | 75,616 |
| scheduler-owned | **1,631** | **18,163** |
| capacity / staffing | 4,468 | 7,987 |
| bounced | 2,239 | 25,889 |
| inbound cascade | 780 | 21,199 |
| Member cancels before arrival | 189 | 313 |
| … in scheduler-owned delay | **44** | **94** |
| … already past PTA when they cancelled | 12 | 31 |
| … parked unassigned | 3 | 39 |
| Picks per call | 1.83 | 2.27 |
| Calls with optimizer churn (≥ 3 picks before dispatch) | 307 (12%) | 895 (19%) |
| Pull-backs | 459 | 1,703 |
| **Idle qualified driver-hours while a nearby call waited** | **208 h** (8% of 2,558 on-shift h) | **719 h** (13% of 5,471 h, upper bound) |
| Call-hours waited while an idle qualified driver was ≤ 15 mi away | 220 h | 1,367 h |
| PTA met, r1 (final PTA), sample | 605/739 = 81.9% | 912/1,419 = 64.3% |
| PTA met, original promise (r2), sample | 604/739 = 81.7% | 910/1,419 = 64.1% |
| "Met" only because the PTA was re-based, sample | 1 | 2 |

---

## 4. The key sales message: who owns the misses

**Late minutes, sample totals (10 days each):**

| Garage | Scheduler | Capacity (staffing) | Bounced | Inbound cascade | Driver | Total | Scheduler ÷ (scheduler + capacity) |
|---|---|---|---|---|---|---|---|
| 100 WNY Fleet | 493 (15%) | 1,562 (49%) | 783 (24%) | 297 (9%) | 57 (2%) | 3,210 | **24%** |
| 076DO On-Platform | 6,623 (26%) | 2,692 (11%) | 9,012 (35%) | 6,233 (25%) | 399 (2%) | 25,393 | **71%** |

**Miss counts, same split:**
- WNY: scheduler 23, capacity 65, bounced 26, inbound 9, driver 9 → **26% scheduler / 74% staffing**.
- 076DO: scheduler 184, capacity 86, bounced 144, inbound 63, driver 17 → **68% / 32%**.

**How to say it honestly:**
- *At On-Platform Contractor garages, about 2 of every 3 late arrivals that a decision could have prevented were the
  dispatch decision, not a staffing gap. At Fleet garages, 3 of 4 were staffing.*
- The product shows each garage which of the two it has. That is the value in both cases.
- **"Scheduler" means the dispatch decision, whoever made it.** At 076DO the scheduler-owned misses were final-picked by:
  | Picked by | Misses | Late minutes |
  |---|---|---|
  | Garage portal dispatcher | 63 | 2,701 |
  | FSL engine | 62 | 2,116 |
  | AAA dispatcher | 30 | 1,015 |
  | Mulesoft/IT integration | 29 | 791 |
- At WNY the same split is FSL 9, AAA dispatcher 6, integration 6, driver 2.
- **Correction (2026-10-04, metrics-spec B4a):** "Mulesoft/IT integration" is not all outside the scheduler.
  - Mulesoft and Replicant driver picks are **FSL auto-schedule**: `FSL__Auto_Schedule__c` set by `ERS_SA_AutoSchedule`,
    then the managed FSL batch runs a scheduling policy as that user. They belong with the FSL engine.
  - Only IT System User's picks without an auto-schedule stamp are decided outside Salesforce code: 42 of 204 graded
    calls on 076DO 8/31.
  - So "FSL" here is FSL engine + auto-schedule. Both are policy-driven.
- Do not sell this as "the FSL optimizer is broken". Sell it as "every decision maker is graded on the same rules".
- Per-decider rates are not causal (the FSL engine re-picks calls that are already in trouble), so do not rank them.

**Pull-backs:**
- Who made them:
  - WNY: AAA dispatchers 102, drivers 51, FSL 4.
  - 076DO: garage portal dispatcher 235, AAA dispatchers 234, integration 65, FSL 19, Towbook sync 8.
- Late minutes on BOUNCED calls, by who made the first pull-back:
  - 076DO: garage dispatcher 5,362, AAA dispatcher 3,091.
  - WNY: AAA dispatcher 593, driver 145.
- At WNY, 59 of 131 pull-back events came ≤ 2 min after dispatch (quick corrections). At 076DO the median was 8 min, and
  129 of 355 came after 15 min or more (consistent with driver non-response).

---

## 5. Satisfaction link (sample supports it, within garage)

| Group | 100 WNY Fleet | 076DO On-Platform |
|---|---|---|
| GOOD calls | 125/132 = **94.7%** | 107/126 = **84.9%** |
| Scheduler failure (STACKED / FAR_PICK / LATE_DESPITE_CAPACITY) | 6/7 (n too small) | 31/44 = **70.5%** (−14.5 pts, z = −2.1, p = 0.03) |
| BOUNCED | 20/24 = 83.3% (−11.4 pts, p = 0.05) | 26/38 = 68.4% (−16.5 pts, p = 0.02) |
| CAPACITY_SHORT | 15/18 = 83.3% | 15/21 = 71.4% |
| PTA met | 142/152 = 93.4% | 147/175 = 84.0% |
| PTA missed | 34/42 = **81.0%** (−12.5 pts, p = 0.01) | 46/72 = **63.9%** (−20.1 pts, p = 0.0005) |

- Pooled within garage (Cochran–Mantel–Haenszel):
  - PTA missed vs met: **z = −4.23, p < 0.0001**.
  - Scheduler failure vs GOOD: **z = −2.29, p = 0.02**.
- I compare within each garage because 076DO scores lower overall and holds most of the failures. The raw pooled gap
  (72.5% vs 89.9%) mixes the two garages.
- Only SMS-opted-in members are surveyed. About 19% of sampled calls have a survey.
- This shows association, not cause.
- Use it as "**misses cost 12 to 20 satisfaction points**". Turning that into renewals needs the member-value inputs in
  section 8.

---

## 6. Per-day tables, daily averages and month extrapolation

Column notes:
- "Extra mi strict (cons.)" = strict avoidable miles (conservative in brackets).
- Misses and late minutes are split by owner.
- "Member cancels (sched-delay)" = member cancels (of which in scheduler-owned delay).
- Idle columns are in hours.

#### 100 WNY Fleet: per day (Sep 2026)

| Date | Day | Calls | Extra mi strict (cons.) | Extra mi broad | PTA met | Misses: sched / capacity / bounced / inbound / driver | Late min: sched / capacity / bounced | Member cancels (sched-delay) | Picks/call | Pull-backs | Idle q. driver-h | Call-h waited w/ idle q. driver |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-09-01 | Tue | 73 | 0 (0) | 4 | 57/68 (84%) | 0 / 8 / 1 / 2 / 0 | 0 / 239 / 3 | 2 (1) | 1.78 | 14 | 3.7 | 3.1 |
| 2026-09-09 | Wed | 73 | 14 (14) | 29 | 55/67 (82%) | 4 / 5 / 2 / 1 / 0 | 92 / 111 / 83 | 6 (2) | 2.10 | 12 | 5.1 | 5.4 |
| 2026-09-11 | Fri | 78 | 1 (1) | 11 | 59/70 (84%) | 1 / 4 / 4 / 0 / 2 | 0 / 115 / 70 | 4 (2) | 1.82 | 24 | 8.6 | 6.7 |
| 2026-09-14 | Mon | 91 | 12 (12) | 16 | 66/81 (81%) | 3 / 8 / 1 / 2 / 0 | 21 / 171 / 10 | 9 (2) | 1.89 | 24 | 4.4 | 3.9 |
| 2026-09-17 | Thu | 66 | 6 (6) | 21 | 54/59 (92%) | 2 / 0 / 1 / 1 / 1 | 5 / 0 / 8 | 6 (0) | 1.56 | 8 | 7.1 | 4.1 |
| 2026-09-22 | Tue | 93 | 6 (6) | 31 | 69/85 (81%) | 3 / 3 / 7 / 2 / 1 | 41 / 22 / 248 | 4 (1) | 1.83 | 20 | 8.7 | 9.5 |
| 2026-09-25 | Fri | 83 | 0 (0) | 14 | 53/75 (71%) | 1 / 15 / 4 / 0 / 1 | 32 / 422 / 181 | 4 (1) | 1.86 | 14 | 8.9 | 8.6 |
| 2026-09-28 | Mon | 90 | 0 (0) | 6 | 65/82 (79%) | 2 / 10 / 2 / 1 / 2 | 123 / 287 / 80 | 6 (1) | 1.92 | 16 | 6.8 | 6.5 |
| 2026-09-12 | Sat (wkd) | 79 | 16 (16) | 39 | 55/72 (76%) | 5 / 7 / 3 / 0 / 2 | 163 / 150 / 80 | 6 (3) | 1.59 | 10 | 11.7 | 15.7 |
| 2026-09-20 | Sun (wkd) | 95 | 0 (0) | 6 | 72/80 (90%) | 2 / 5 / 1 / 0 / 0 | 17 / 45 / 19 | 12 (1) | 1.88 | 15 | 3.4 | 5.4 |

#### 100 WNY Fleet: daily averages and month extrapolation (Sep 2026: 21 weekdays + 9 weekend/holiday days)

| Measure | Weekday avg | Weekend avg | Month total (extrapolated) | Sample total (10 days) |
|---|---|---|---|---|
| Scored calls | 81 | 87 | 2481 | 821 |
| Avoidable extra miles, strict (STACKED + FAR_PICK) | 5 | 8 | 175 | 55 |
| Avoidable extra miles, conservative (strict minus 0 implausible-speed picks) | 5 | 8 | 175 | 55 |
| Extra miles, broad upper bound (any closer free qualified driver > 0.5 mi) | 16 | 23 | 550 | 177 |
| PTA misses, all | 14 | 12 | 399 | 134 |
| PTA misses, scheduler-owned (LATE_DESPITE_CAPACITY / STACKED / FAR_PICK) | 2 | 4 | 74 | 23 |
| PTA misses, capacity-owned (CAPACITY_SHORT) | 7 | 6 | 193 | 65 |
| PTA misses, BOUNCED (pull-back / re-dispatch) | 3 | 2 | 76 | 26 |
| PTA misses, INBOUND_CASCADE (clock started in another garage) | 1 | 0 | 24 | 9 |
| PTA misses, driver-owned (LATE_EXECUTION) | 1 | 1 | 27 | 9 |
| Late minutes past PTA, all | 340 | 243 | 9338 | 3210 |
| Late minutes, scheduler-owned | 39 | 90 | 1631 | 493 |
| Late minutes, capacity-owned | 171 | 98 | 4468 | 1562 |
| Late minutes, BOUNCED | 86 | 49 | 2239 | 783 |
| Late minutes, INBOUND_CASCADE | 37 | 0 | 780 | 297 |
| Late minutes, driver-owned | 5 | 7 | 176 | 57 |
| Member cancels before arrival | 5 | 9 | 189 | 59 |
|   of which past the PTA when cancelled | 0 | 0 | 12 | 4 |
|   of which in scheduler-owned delay (failure code, or idle qualified driver <= 15 mi for >= 10 min) | 1 | 2 | 44 | 14 |
|   of which BOUNCED | 1 | 0 | 20 | 7 |
|   of which parked unassigned (Spotted >= 10 min, or cancelled while Spotted, or came from a SPOT territory) | 0 | 0 | 3 | 1 |
| Assignment picks (all) | 150 | 152 | 4515 | 1502 |
| Calls with OPTIMIZER_CHURN (>= 3 picks before dispatch) | 10 | 10 | 307 | 102 |
| Pull-backs (Dispatched/Accepted/En Route -> Spotted) | 16 | 12 | 459 | 157 |
| Calls with >= 1 pull-back | 13 | 10 | 360 | 122 |
| Idle qualified driver-hours while a call within 15 mi waited (H2 numerator) | 6.7 | 7.6 | 208.1 | 68.4 |
| Call-hours waited while an idle qualified driver was within 15 mi | 6.0 | 10.6 | 220.5 | 68.9 |
| Driver on-shift hours (roster, truck login) | 82 | 93 | 2558 | 842 |
| PTA met (final PTA, r1) | 60 | 64 | 1826 | 605 |
| PTA graded calls | 73 | 76 | 2225 | 739 |
| PTA met against the ORIGINAL promise | 60 | 64 | 1824 | 604 |
| Met only because PTA was re-based | 0 | 0 | 3 | 1 |
| Calls with a later ERS_PTA__c edit | 1 | 0 | 18 | 7 |

#### 076DO (On-Platform): per day (Aug 2026)

| Date | Day | Calls | Extra mi strict (cons.) | Extra mi broad | PTA met | Misses: sched / capacity / bounced / inbound / driver | Late min: sched / capacity / bounced | Member cancels (sched-delay) | Picks/call | Pull-backs | Idle q. driver-h | Call-h waited w/ idle q. driver |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-08-03 | Mon | 202 | 163 (137) | 397 | 134/180 (74%) | 14 / 6 / 19 / 6 / 0 | 480 / 63 / 1038 | 10 (4) | 2.62 | 83 | 23.3 | 78.6 |
| 2026-08-05 | Wed | 163 | 173 (173) | 213 | 77/147 (52%) | 30 / 17 / 13 / 5 / 3 | 1193 / 621 / 706 | 12 (3) | 2.31 | 45 | 16.6 | 56.9 |
| 2026-08-07 | Fri | 127 | 92 (92) | 145 | 79/115 (69%) | 12 / 10 / 11 / 1 / 2 | 182 / 264 / 586 | 6 (1) | 2.14 | 54 | 21.0 | 38.2 |
| 2026-08-11 | Tue | 172 | 50 (42) | 102 | 75/153 (49%) | 26 / 15 / 23 / 7 / 3 | 1166 / 719 / 1893 | 11 (3) | 2.28 | 65 | 25.3 | 59.6 |
| 2026-08-13 | Thu | 133 | 76 (76) | 118 | 62/117 (53%) | 26 / 4 / 14 / 5 / 3 | 1341 / 115 / 1285 | 10 (4) | 2.58 | 40 | 14.7 | 56.0 |
| 2026-08-19 | Wed | 163 | 261 (217) | 367 | 106/148 (72%) | 18 / 1 / 18 / 3 / 1 | 406 / 15 / 1361 | 4 (1) | 2.22 | 68 | 35.9 | 34.6 |
| 2026-08-25 | Tue | 170 | 187 (168) | 244 | 108/152 (71%) | 12 / 10 / 11 / 10 / 1 | 350 / 317 / 613 | 14 (3) | 2.13 | 51 | 32.6 | 41.3 |
| 2026-08-31 | Mon | 208 | 276 (255) | 418 | 124/185 (67%) | 31 / 8 / 13 / 6 / 2 | 1179 / 192 / 591 | 18 (9) | 1.99 | 58 | 29.6 | 75.6 |
| 2026-08-08 | Sat (wkd) | 123 | 73 (73) | 197 | 63/108 (58%) | 12 / 7 / 14 / 9 / 2 | 255 / 173 / 617 | 9 (2) | 1.93 | 36 | 22.8 | 23.8 |
| 2026-08-23 | Sun (wkd) | 126 | 77 (77) | 155 | 84/114 (74%) | 3 / 8 / 8 / 11 / 0 | 72 / 214 / 323 | 9 (2) | 2.47 | 61 | 16.6 | 18.1 |

#### 076DO (On-Platform): daily averages and month extrapolation (Aug 2026: 21 weekdays + 10 weekend/holiday days)

| Measure | Weekday avg | Weekend avg | Month total (extrapolated) | Sample total (10 days) |
|---|---|---|---|---|
| Scored calls | 167 | 124 | 4757 | 1587 |
| Avoidable extra miles, strict (STACKED + FAR_PICK) | 160 | 75 | 4106 | 1428 |
| Avoidable extra miles, conservative (strict minus 8 implausible-speed picks) | 145 | 75 | 3793 | 1309 |
| Extra miles, broad upper bound (any closer free qualified driver > 0.5 mi) | 250 | 176 | 7020 | 2356 |
| PTA misses, all | 54 | 38 | 1509 | 507 |
| PTA misses, scheduler-owned (LATE_DESPITE_CAPACITY / STACKED / FAR_PICK) | 21 | 8 | 519 | 184 |
| PTA misses, capacity-owned (CAPACITY_SHORT) | 9 | 8 | 261 | 86 |
| PTA misses, BOUNCED (pull-back / re-dispatch) | 15 | 11 | 430 | 144 |
| PTA misses, INBOUND_CASCADE (clock started in another garage) | 5 | 10 | 213 | 63 |
| PTA misses, driver-owned (LATE_EXECUTION) | 2 | 1 | 49 | 17 |
| Late minutes past PTA, all | 2703 | 1886 | 75616 | 25393 |
| Late minutes, scheduler-owned | 787 | 164 | 18163 | 6623 |
| Late minutes, capacity-owned | 288 | 193 | 7987 | 2692 |
| Late minutes, BOUNCED | 1009 | 470 | 25889 | 9012 |
| Late minutes, INBOUND_CASCADE | 524 | 1019 | 21199 | 6233 |
| Late minutes, driver-owned | 43 | 26 | 1170 | 399 |
| Member cancels before arrival | 11 | 9 | 313 | 103 |
|   of which past the PTA when cancelled | 1 | 1 | 31 | 10 |
|   of which in scheduler-owned delay (failure code, or idle qualified driver <= 15 mi for >= 10 min) | 4 | 2 | 94 | 32 |
|   of which BOUNCED | 1 | 2 | 49 | 15 |
|   of which parked unassigned (Spotted >= 10 min, or cancelled while Spotted, or came from a SPOT territory) | 2 | 0 | 39 | 14 |
| Assignment picks (all) | 381 | 274 | 10754 | 3600 |
| Calls with OPTIMIZER_CHURN (>= 3 picks before dispatch) | 33 | 20 | 895 | 304 |
| Pull-backs (Dispatched/Accepted/En Route -> Spotted) | 58 | 48 | 1703 | 561 |
| Calls with >= 1 pull-back | 33 | 30 | 993 | 324 |
| Idle qualified driver-hours while a call within 15 mi waited (H2 numerator) | 24.9 | 19.7 | 719.4 | 238.4 |
| Call-hours waited while an idle qualified driver was within 15 mi | 55.1 | 20.9 | 1366.6 | 482.7 |
| Driver on-shift hours (roster, truck login) | 193 | 141 | 5471 | 1828 |
| PTA met (final PTA, r1) | 96 | 74 | 2743 | 912 |
| PTA graded calls | 150 | 111 | 4252 | 1419 |
| PTA met against the ORIGINAL promise | 96 | 73 | 2736 | 910 |
| Met only because PTA was re-based | 0 | 0 | 8 | 2 |
| Calls with a later ERS_PTA__c edit | 1 | 1 | 39 | 13 |


---

## 7. Evidence: example calls (typical, not extreme)

Every row can be opened in the report card Day view (`?garage=<id>&date=<date>&sa=<number>`).

| Measure | Call | What happened |
|---|---|---|
| FAR_PICK (076DO) | SA-979159 `08pPb000008tCaDIAU` · 8/08 | AAA dispatcher picked a driver 13.4 mi away with 0 open jobs. A free qualified driver was 5.0 mi away. 22 min late (PTA 60). Flags: OPTIMIZER_CHURN, HUMAN_FINAL. |
| FAR_PICK, largest (076DO) | SA-1010160 `08pPb0000098WGrIAM` · 8/25 | FSL engine picked a driver 75.5 mi away (drive 87.6 min, so the distance was real). A free qualified driver was 1.6 mi away. |
| STACKED (076DO) | SA-968582 `08pPb000008nD4NIAU` · 8/03 | AAA dispatcher queued it on a driver 6.8 mi away with 1 open job. Two idle qualified drivers were closer (3.3 and 4.9 mi). 32 min late. Flag MISSED_REBALANCE. |
| STACKED (WNY) | SA-1048928 `08pPb000009RhmrIAC` · 9/14 | AAA dispatcher picked a driver 7.1 mi away with 1 open job. An idle qualified driver was 2.3 mi away. 11 min late (PTA 45). |
| LATE_DESPITE_CAPACITY (WNY) | SA-1075605 `08pPb000009fCODIA2` · 9/28 | FSL pick 3.8 mi away, driver busy. A qualified driver went idle nearby for ≥ 10 min and the call was not moved. 37 min late. |
| LATE_DESPITE_CAPACITY (076DO) | SA-984302 `08pPb000008vWmXIAU` · 8/11 | FSL pick 2.4 mi away, busy. A free driver 3.0 mi away was available before the assignment. 35 min late. |
| CAPACITY_SHORT (WNY, staffing) | SA-1074304 `08pPb000009eT1JIAU` · 9/28 | Call-story golden 10.3. The closest qualified driver was busy and nobody nearby was free. 34 min late. |
| Member cancel in scheduler-owned delay (WNY) | SA-1042570 `08pPb000009OtcTIAS` · 9/11 | Queued on a driver with 2 open jobs. A free qualified driver within 15 mi sat idle for 26 min before the call went En Route. The member cancelled after 73.5 min, with the driver already en route ("Member Could Not Wait"). |
| Member cancel in scheduler-owned delay (076DO) | SA-969905 `08pPb000008oEKvIAM` · 8/03 | 43.8 min in total unassigned (Spotted). The final pick had 1 open job. A free qualified driver within 15 mi sat idle for 66 min before En Route. The member cancelled after 144 min, with the driver en route ("Member Could Not Wait"). |
| Optimizer churn (076DO) | SA-969465 `08pPb000008nzP7IAI` · 8/03 | **19 picks before dispatch**. Final pick 15.9 mi away with 1 open job while a qualified driver 7.7 mi away was idle. 221 min late. |
| PTA met only because re-based (WNY) | SA-1075021 `08pPb000009esNtIAI` · 9/28 | PTA 60 → 120 written by `Integrations Towbook` 15 s after creation. Arrived at 69 min: met against 120, missed against the original 60. |

---

## 8. Unit costs the business case needs (NOT in Salesforce: please supply)

I did not invent any of these. Each one turns a measured quantity above into dollars.

| # | Input | Turns this into $ | Notes / who likely owns it |
|---|---|---|---|
| U1 | **Fleet cost per mile** (fuel + maintenance + depreciation) | Avoidable miles (Fleet) | Fleet ops / finance. Also a **road-to-straight-line factor**, or approval for a routing API, because all miles here are straight-line |
| U2 | **On-Platform contractor pay structure** (per call? per mile? per tow? any standby pay?) | Contractor miles and idle hours: are they AAA's cost or the contractor's? | Contractor management. If contractors are paid per call, avoidable contractor miles cost the contractor, not AAA. The value is then speed and satisfaction |
| U3 | **Fleet driver fully loaded hourly cost** | Idle qualified driver-hours (208 h/month at WNY) | HR / finance |
| U4 | **AAA dispatcher hourly cost + minutes per manual intervention** (pull-back, re-pick) | Pull-backs (459/month WNY, 1,703 at 076DO) and churn | Dispatch ops |
| U5 | **Value of a retained member** (annual dues × expected tenure, or CLV) **and the renewal-rate gap between "Totally satisfied" and the rest** | The 12–20 point satisfaction gap on missed PTAs, and member cancels | Membership / marketing. Actual renewal is in the membership system, not FSL. `Survey_Result__c.ERS_Renew__c` is only *stated* intent |
| U6 | **Cost of a member cancel** (reimbursement for "Member Found Own Service", repeat call, complaint handling) | Member cancels in scheduler-owned delay (44 / 94 per month) | Member services / claims |
| U7 | **Towbook per-call cost** by service type | What-if comparisons (on-platform vs Towbook for the same garage) | Contractor management / finance |
| U8 | **Business PTA target** (85% is a placeholder in r1) and any garage SLA credits or penalties | Bands, and the value of a late minute | Ops leadership |
| U9 | Product price / operating cost | The ROI ratio itself | Product owner |

---

## 9. Caveats and limits (read before quoting)

1. **Straight-line miles.**
   - Haversine distance, one way, at the decision time. Road miles are longer, and the factor was not measured.
   - For STACKED picks the busy driver actually starts from their current job, so the decision-time distance can over- or
     under-state the real detour. The *conservative* column removes the 8 picks where the drive time proves the GPS point
     was not the start.
2. **Late minutes are an upper bound on avoidable lateness.**
   - A better pick would not have saved every minute past the PTA. The counterfactual arrival is not modelled.
   - Waits that stayed inside the PTA are not counted at all.
3. **Small samples, extrapolated.**
   - 10 days per garage, and weekend averages come from 2 days each, so treat month totals as ±30% indicative. WNY Fleet
     has only 23 scheduler-owned misses in the sample, so per-day values are noisy.
   - Labor Day was not sampled. August and September are different seasons.
   - Do not rank days or decision makers on n < 30.
4. **076DO moved to Towbook on 9/1.** Its numbers describe what On-Platform contractor dispatch cost in August. They are a
   reference for any On-Platform garage, not 076DO's current spend.
5. **Contractor idle is an upper bound** (spec C3). A logged-in contractor with no AAA job may be doing non-AAA work.
6. **Cancel attribution is a signal, not proof.** "An idle qualified driver nearby for ≥ 10 min" does not prove the member
   would have stayed.
7. **Calls that left the garage are not in the pull.** The pull is by current `ServiceTerritoryId`, so calls moved out of the
   garage (for example to SPOT) and cancelled there are missed. "Parked unassigned" cancels are therefore undercounted.
8. **Truck capabilities have no history** (current values are used for qualification).
9. **PTA is graded only where an arrival exists.** Cancels are outside PTA met.
10. **Satisfaction** covers SMS-opted-in respondents only. It is an association, and respondent bias is possible.
11. **r1 thresholds are placeholders** (FAR_PICK > 5 mi, MISSED_REBALANCE ≥ 10 min idle, reach 15 mi). Changing them moves
    the scheduler/capacity split. A sensitivity run is cheap because it re-scores the snapshots with 0 Salesforce calls.
12. **Salesforce load for this work:** about 420 sequential read-only calls for sections 1–10, plus about 330 for
    section 11 (20 builds + PTA history + surveys for the new calls only) and about 25 for the integration-account check.
    Breakdown of the first 420:
    - 18 new garage-day builds (about 330), plus one 076DO build that timed out on `ServiceResourceHistory` at 45 s,
    - PTA history (30), surveys (39), flow and describe checks (8).

    No parallel calls, no DML, no Postgres. Snapshots are in `~/.fslapp/report_card/`, append-only.

---

## 10. Recommended actions

| # | Action | Owner |
|---|---|---|
| 1 | Supply U1–U9, or point me to the source. I will turn section 3 into a dollar table with low / base / high ranges. | User / finance |
| 2 | **Position the product by channel:** for On-Platform Contractor garages lead with "decision quality" (68–71% of preventable misses); for Fleet garages lead with "staffing vs decision" visibility and pull-back review. | User (product owner) |
| 3 | ~~Repeat on one more Fleet and one active On-Platform garage~~ **Done** (section 11): the channel split holds (Fleet 26–38% scheduler, On-Platform 68–88%). | Henry |
| 3b | Do **not** use "route integration picks through the FSL scheduler" as the headline lever. Mulesoft/Replicant picks already are FSL auto-schedule. Only IT System User's unstamped picks (42 of 204 on 8/31) are outside Salesforce code. Confirm with the integration team what decides those. | Ruby (wording), integration team |
| 3c | At On-Platform garages, add an alert or auto-assign when a call sits unassigned while a qualified driver is free (421: garage dispatchers picked at a median of 54 min). | Contractor management / dispatch ops |
| 4 | LATE_DESPITE_CAPACITY is the biggest scheduler bucket at 076DO (116 of 184 misses, 4,013 min). Lever L03: territory-wide rebalance when a qualified driver goes idle. | FSL admin (Apex RSO) |
| 5 | BOUNCED is the biggest late-minute bucket at 076DO (35%), mostly from the garage portal dispatcher. Lever L06: pull-back review. | Dispatch ops / contractor management |
| 6 | Inbound cascades are 25% of 076DO late minutes. Lever L08: priority-matrix review and auto-cascade. | Dispatch ops |
| 7 | Run a threshold sensitivity (r1 ± 50%) on these 20 snapshots (0 SF calls), so the split comes with a range. | Henry |

---

## 11. Extension: two more garages (Sep 2026, same 10 dates as WNY)

**Why these two:** they were the busiest by channel in the week of 9/14–9/20 (one AssignedResource aggregate query).
- **800 Central Region ERS Fleet Services** (`0HhPb00000007rKKAQ`), Fleet: 448 assignments that week.
- **421 Action Towing of Rochester** (`0HhPb00000007qUKAQ`), the largest **currently active** On-Platform Contractor
  garage: 656 assignments that week.

Both were built with builder `rc-build-1.1` and scored with r1, so they compare directly with sections 3–6.

### 11.1 Headline (month = Sep 2026, extrapolated)

| Measure / month | 100 WNY Fleet | 800 Central Fleet | 076DO On-Platform (Aug) | 421 Action On-Platform |
|---|---|---|---|---|
| Scored calls | 2,481 | 1,994 | 4,757 | 1,987 |
| Avoidable extra miles, strict (straight-line) | 175 | 311 | 4,106 | 634 |
| PTA met, sample | 81.9% | 88.6% (545/615) | 64.3% | 70.4% (438/622) |
| Scheduler-owned misses | 74 | 40 | 519 | 240 |
| Capacity-owned misses | 193 | 68 | 261 | 33 |
| **Scheduler share of (scheduler + capacity) misses** | **26%** | **38%** | **68%** | **88%** (≥ 57%, see 11.3) |
| Scheduler share of late minutes | 24% | 35% | 71% | 92% |
| Scheduler-owned late member-minutes | 1,631 | 938 | 18,163 | 7,671 |
| Bounced late member-minutes | 2,239 | 1,970 | 25,889 | 2,540 |
| Member cancels in scheduler-owned delay | 44 | 26 | 94 | 24 |
| Member cancels parked unassigned | 3 | 5 | 39 | **74** |
| Idle qualified driver-hours while a nearby call waited | 208 h (8%) | 164 h (7%) | 719 h (13%) † | 797 h (19%) † |
| Picks per call | 1.83 | 1.59 | 2.27 | 1.11 |
| Pull-backs | 459 | 371 | 1,703 | 184 |
| "Met" only because the PTA was re-based (sample) | 1 | 0 | 2 | 0 |

† Contractor idle is an upper bound (C3).

### 11.2 What the extension changes in the story

1. **The channel split is not a one-garage artifact.**
   - Fleet garages: 26% and 38% scheduler-owned. Staffing is the bigger lever.
   - On-Platform garages: 68% and 88%. The dispatch decision is the bigger lever.
2. **At 421 the dispatch decision is late, not wrong, and it is made at the garage's own desk.**
   - Picks per call are only 1.11, and only 7 calls had ≥ 3 picks before dispatch.
   - 75 of 87 scheduler-owned misses are LATE_DESPITE_CAPACITY (2,573 late min). Only 2 carry MISSED_REBALANCE. The rest
     fired because a free qualified driver within reach existed **before** the assignment was made.
   - **68 of the 75 were final-picked by 421's own garage-portal dispatchers** (two people made 65). The pick came a median
     **54 min after the call was created** (p75 85), usually to a driver with no open job (64 of 75).
   - So the lever is an auto-assign or alert when a call sits unassigned at a contractor garage while a qualified driver is
     free (L08 / L03). Tuning the FSL policy or the integration would not fix it.
   - 421 is a tow company: its contractors may be doing non-AAA work while "idle" (C3). Treat 797 h as a ceiling, not a
     cost, and the "late despite capacity" share as an upper bound for the same reason.
3. **421 loses members while calls sit unassigned.** 26 of its 40 sampled member cancels happened while the call sat in
   `Spotted` ≥ 10 min, or was cancelled while Spotted (74 a month).
   - These are calls nobody owned yet, the call story's NO_OWNER and PARKED_IN_SPOT.
   - The other three garages have 1–14.
4. **Fleet 800 looks like WNY 100:** few bad picks (about 10 strict extra miles a day) and BOUNCED is the largest late bucket
   (37%). Pull-backs at 800 are mostly drivers handing back their own call (81 of 127).

### 11.3 Caveat specific to 421: GPS gaps
- **138 of 699 scored calls (20%) are NOT_GRADED_INSUFFICIENT_DATA.** In every one, the final driver had no GPS fix within
  30 min of the pick (checked case by case, `validation/roi/ng.py`).
- Their misses (54) fall in the "other" bucket. The 88% scheduler share excludes them. If all 54 were staffing, the share
  would still be **57%**.
- Contractor app GPS coverage at 421 is itself a finding for contractor management: the scheduler cannot pick
  "closest" for a driver it cannot see.

### 11.4 Satisfaction across all four garages
- PTA missed vs met: **71.7% vs 88.4% "Totally satisfied"** (n = 159 vs 542). Within-garage CMH **z = −4.52, p < 0.0001**.
- Scheduler failure vs GOOD: **72.2% vs 89.8%** (n = 79 vs 421). CMH **z = −3.14, p = 0.002**.
- 732 surveys on 3,783 calls (19%), SMS-opted-in only. This is an association.

### 11.5 Per-day tables

#### 800 Central Fleet: per day (Sep 2026)

| Date | Day | Calls | Extra mi strict (cons.) | Extra mi broad | PTA met | Misses: sched / capacity / bounced / inbound / driver | Late min: sched / capacity / bounced | Member cancels (sched-delay) | Picks/call | Pull-backs | Idle q. driver-h | Call-h waited w/ idle q. driver |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-09-01 | Tue | 74 | 0 (0) | 11 | 55/64 (86%) | 1 / 5 / 2 / 1 / 0 | 2 / 91 / 15 | 8 (1) | 1.55 | 9 | 7.2 | 3.7 |
| 2026-09-09 | Wed | 75 | 8 (8) | 31 | 54/64 (84%) | 3 / 3 / 2 / 1 / 1 | 62 / 37 / 69 | 7 (1) | 1.61 | 12 | 3.4 | 3.6 |
| 2026-09-11 | Fri | 66 | 12 (12) | 28 | 46/59 (78%) | 3 / 6 / 2 / 1 / 1 | 31 / 202 / 157 | 5 (0) | 1.73 | 14 | 3.2 | 3.8 |
| 2026-09-14 | Mon | 72 | 11 (11) | 41 | 65/70 (93%) | 1 / 2 / 1 / 1 / 0 | 8 / 19 / 43 | 2 (1) | 1.50 | 12 | 6.3 | 3.7 |
| 2026-09-17 | Thu | 63 | 4 (4) | 23 | 51/57 (89%) | 1 / 2 / 2 / 0 / 1 | 30 / 82 / 42 | 5 (1) | 1.51 | 12 | 5.3 | 5.0 |
| 2026-09-22 | Tue | 73 | 6 (6) | 35 | 59/63 (94%) | 1 / 0 / 3 / 0 / 0 | 14 / 0 / 61 | 5 (4) | 1.75 | 24 | 6.4 | 5.0 |
| 2026-09-25 | Fri | 60 | 14 (14) | 37 | 50/55 (91%) | 0 / 1 / 4 / 0 / 0 | 0 / 16 / 86 | 4 (1) | 1.32 | 10 | 8.9 | 6.3 |
| 2026-09-28 | Mon | 76 | 11 (11) | 44 | 66/71 (93%) | 2 / 0 / 2 / 1 / 0 | 33 / 0 / 50 | 3 (1) | 1.36 | 14 | 6.7 | 4.4 |
| 2026-09-12 | Sat (wkd) | 61 | 11 (11) | 24 | 56/57 (98%) | 0 / 0 / 1 / 0 / 0 | 0 / 0 / 2 | 3 (0) | 1.51 | 12 | 6.0 | 3.9 |
| 2026-09-20 | Sun (wkd) | 56 | 20 (20) | 30 | 43/55 (78%) | 2 / 4 / 5 / 0 / 1 | 103 / 87 / 131 | 1 (0) | 1.93 | 8 | 2.9 | 5.5 |

#### 800 Central Fleet: daily averages and month extrapolation (Sep 2026: 21 weekdays + 9 weekend/holiday days)

| Measure | Weekday avg | Weekend avg | Month total (extrapolated) | Sample total (10 days) |
|---|---|---|---|---|
| Scored calls | 70 | 58 | 1994 | 676 |
| Avoidable extra miles, strict (STACKED + FAR_PICK) | 8 | 15 | 311 | 97 |
| Avoidable extra miles, conservative (strict minus 0 implausible-speed picks) | 8 | 15 | 311 | 97 |
| Extra miles, broad upper bound (any closer free qualified driver > 0.5 mi) | 31 | 27 | 898 | 303 |
| PTA misses, all | 7 | 6 | 208 | 70 |
| PTA misses, scheduler-owned (LATE_DESPITE_CAPACITY / STACKED / FAR_PICK) | 2 | 1 | 40 | 14 |
| PTA misses, capacity-owned (CAPACITY_SHORT) | 2 | 2 | 68 | 23 |
| PTA misses, BOUNCED (pull-back / re-dispatch) | 2 | 3 | 74 | 24 |
| PTA misses, INBOUND_CASCADE (clock started in another garage) | 1 | 0 | 13 | 5 |
| PTA misses, driver-owned (LATE_EXECUTION) | 0 | 0 | 12 | 4 |
| Late minutes past PTA, all | 182 | 166 | 5313 | 1787 |
| Late minutes, scheduler-owned | 23 | 52 | 938 | 284 |
| Late minutes, capacity-owned | 56 | 44 | 1568 | 535 |
| Late minutes, BOUNCED | 65 | 67 | 1970 | 655 |
| Late minutes, INBOUND_CASCADE | 34 | 0 | 723 | 275 |
| Late minutes, driver-owned | 4 | 4 | 114 | 37 |
| Member cancels before arrival | 5 | 2 | 120 | 43 |
|   of which past the PTA when cancelled | 0 | 0 | 5 | 2 |
|   of which in scheduler-owned delay (failure code, or idle qualified driver <= 15 mi for >= 10 min) | 1 | 0 | 26 | 10 |
|   of which BOUNCED | 1 | 0 | 13 | 5 |
|   of which parked unassigned (Spotted >= 10 min, or cancelled while Spotted, or came from a SPOT territory) | 0 | 0 | 5 | 2 |
| Assignment picks (all) | 108 | 100 | 3165 | 1063 |
| Calls with OPTIMIZER_CHURN (>= 3 picks before dispatch) | 4 | 6 | 143 | 46 |
| Pull-backs (Dispatched/Accepted/En Route -> Spotted) | 13 | 10 | 371 | 127 |
| Calls with >= 1 pull-back | 11 | 8 | 298 | 102 |
| Idle qualified driver-hours while a call within 15 mi waited (H2 numerator) | 5.9 | 4.4 | 164.3 | 56.3 |
| Call-hours waited while an idle qualified driver was within 15 mi | 4.4 | 4.7 | 135.4 | 44.9 |
| Driver on-shift hours (roster, truck login) | 84 | 70 | 2390 | 810 |
| PTA met (final PTA, r1) | 56 | 50 | 1616 | 545 |
| PTA graded calls | 63 | 56 | 1824 | 615 |
| PTA met against the ORIGINAL promise | 56 | 50 | 1616 | 545 |
| Met only because PTA was re-based | 0 | 0 | 0 | 0 |
| Calls with a later ERS_PTA__c edit | 0 | 0 | 7 | 2 |

#### 421 Action Towing (On-Platform): per day (Sep 2026)

| Date | Day | Calls | Extra mi strict (cons.) | Extra mi broad | PTA met | Misses: sched / capacity / bounced / inbound / driver | Late min: sched / capacity / bounced | Member cancels (sched-delay) | Picks/call | Pull-backs | Idle q. driver-h | Call-h waited w/ idle q. driver |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-09-01 | Tue | 74 | 21 (21) | 59 | 49/63 (78%) | 5 / 2 / 1 / 2 / 0 | 88 / 86 / 5 | 6 (2) | 1.04 | 5 | 31.4 | 18.4 |
| 2026-09-09 | Wed | 60 | 2 (2) | 26 | 40/55 (73%) | 6 / 0 / 3 / 1 / 1 | 77 / 0 / 191 | 1 (0) | 1.20 | 10 | 38.4 | 23.8 |
| 2026-09-11 | Fri | 61 | 20 (20) | 56 | 40/58 (69%) | 8 / 1 / 4 / 0 / 0 | 219 / 8 / 189 | 3 (0) | 1.18 | 6 | 19.9 | 16.0 |
| 2026-09-14 | Mon | 112 | 35 (35) | 60 | 60/93 (65%) | 13 / 3 / 1 / 3 / 0 | 530 / 27 / 82 | 12 (1) | 1.05 | 9 | 35.4 | 53.7 |
| 2026-09-17 | Thu | 82 | 25 (25) | 64 | 43/77 (56%) | 22 / 0 / 4 / 1 / 0 | 941 / 0 / 273 | 2 (1) | 1.13 | 8 | 28.9 | 51.7 |
| 2026-09-22 | Tue | 69 | 11 (11) | 31 | 45/61 (74%) | 10 / 2 / 0 / 0 / 0 | 243 / 42 / 0 | 4 (2) | 1.07 | 6 | 35.4 | 20.7 |
| 2026-09-25 | Fri | 79 | 12 (12) | 51 | 53/70 (76%) | 7 / 2 / 3 / 0 / 0 | 123 / 84 / 100 | 4 (1) | 1.10 | 11 | 32.1 | 20.2 |
| 2026-09-28 | Mon | 81 | 54 (54) | 83 | 51/74 (69%) | 10 / 1 / 3 / 0 / 1 | 375 / 7 / 68 | 3 (2) | 1.09 | 5 | 36.4 | 29.9 |
| 2026-09-12 | Sat (wkd) | 43 | 18 (18) | 37 | 26/36 (72%) | 4 / 1 / 3 / 0 / 0 | 100 / 1 / 35 | 3 (0) | 1.28 | 5 | 15.2 | 7.8 |
| 2026-09-20 | Sun (wkd) | 38 | 17 (17) | 25 | 31/35 (89%) | 2 / 0 / 0 / 0 / 0 | 91 / 0 / 0 | 2 (0) | 1.05 | 1 | 11.6 | 8.1 |

#### 421 Action Towing (On-Platform): daily averages and month extrapolation (Sep 2026: 21 weekdays + 9 weekend/holiday days)

| Measure | Weekday avg | Weekend avg | Month total (extrapolated) | Sample total (10 days) |
|---|---|---|---|---|
| Scored calls | 77 | 40 | 1987 | 699 |
| Avoidable extra miles, strict (STACKED + FAR_PICK) | 23 | 18 | 634 | 216 |
| Avoidable extra miles, conservative (strict minus 0 implausible-speed picks) | 23 | 18 | 634 | 216 |
| Extra miles, broad upper bound (any closer free qualified driver > 0.5 mi) | 54 | 31 | 1411 | 493 |
| PTA misses, all | 21 | 7 | 509 | 184 |
| PTA misses, scheduler-owned (LATE_DESPITE_CAPACITY / STACKED / FAR_PICK) | 10 | 3 | 240 | 87 |
| PTA misses, capacity-owned (CAPACITY_SHORT) | 1 | 0 | 33 | 12 |
| PTA misses, BOUNCED (pull-back / re-dispatch) | 2 | 2 | 63 | 22 |
| PTA misses, INBOUND_CASCADE (clock started in another garage) | 1 | 0 | 18 | 7 |
| PTA misses, driver-owned (LATE_EXECUTION) | 0 | 0 | 5 | 2 |
| Late minutes past PTA, all | 818 | 156 | 18589 | 6859 |
| Late minutes, scheduler-owned | 324 | 95 | 7671 | 2786 |
| Late minutes, capacity-owned | 32 | 1 | 671 | 255 |
| Late minutes, BOUNCED | 113 | 18 | 2540 | 943 |
| Late minutes, INBOUND_CASCADE | 145 | 0 | 3037 | 1157 |
| Late minutes, driver-owned | 3 | 0 | 53 | 20 |
| Member cancels before arrival | 4 | 2 | 114 | 40 |
|   of which past the PTA when cancelled | 0 | 0 | 15 | 5 |
|   of which in scheduler-owned delay (failure code, or idle qualified driver <= 15 mi for >= 10 min) | 1 | 0 | 24 | 9 |
|   of which BOUNCED | 0 | 0 | 10 | 3 |
|   of which parked unassigned (Spotted >= 10 min, or cancelled while Spotted, or came from a SPOT territory) | 3 | 2 | 74 | 26 |
| Assignment picks (all) | 85 | 48 | 2215 | 776 |
| Calls with OPTIMIZER_CHURN (>= 3 picks before dispatch) | 0 | 2 | 26 | 7 |
| Pull-backs (Dispatched/Accepted/En Route -> Spotted) | 8 | 3 | 184 | 66 |
| Calls with >= 1 pull-back | 6 | 3 | 156 | 55 |
| Idle qualified driver-hours while a call within 15 mi waited (H2 numerator) | 32.2 | 13.4 | 797.4 | 284.6 |
| Call-hours waited while an idle qualified driver was within 15 mi | 29.3 | 8.0 | 687.0 | 250.3 |
| Driver on-shift hours (roster, truck login) | 148 | 118 | 4160 | 1417 |
| PTA met (final PTA, r1) | 48 | 28 | 1257 | 438 |
| PTA graded calls | 69 | 36 | 1766 | 622 |
| PTA met against the ORIGINAL promise | 48 | 28 | 1257 | 438 |
| Met only because PTA was re-based | 0 | 0 | 0 | 0 |
| Calls with a later ERS_PTA__c edit | 0 | 0 | 3 | 1 |
