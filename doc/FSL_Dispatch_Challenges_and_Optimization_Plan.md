# AAA WCNY — FSL Dispatch Challenges & Optimization Plan

## Executive Summary

AAA Western & Central New York dispatches ~1,000 roadside calls per day through two channels: Fleet (company trucks) and Towbook (contractor garages). The current system achieves 83% member satisfaction and 79% auto-dispatch rate, but several structural issues create inefficiencies that cost time, money, and member satisfaction. This document identifies the key challenges and proposes a phased improvement plan.

---

## Current Challenges

### 1. Closest Driver Not Always Assigned

**Problem:** The FSL Enhanced Scheduler was designed for field service businesses where technicians start from home. AAA drivers are already on the road — the scheduler's "home base" travel calculation doesn't apply.

**Root Cause:**
- Zero home addresses populated on 501 ServiceTerritoryMember records
- Scheduler falls back to STM address (blank) → travel calculation is meaningless
- Resource Absence workaround provides approximate location, but it's the LAST job location, not current position

**Impact:** Drivers 3 miles away get skipped in favor of drivers 15 miles away because the scheduler doesn't know where anyone actually is.

**Current Mitigation:** Resource Absence records storing "last assigned service location" gave the scheduler something to work with → auto-assignment improved from 0% → 83%. But it's still using stale position data.

**Data Available:** 4.25 million ServiceResourceHistory GPS records — we know where every FSL driver was at every moment. The scheduler just doesn't use this data.

---

### 2. Driver Workload Imbalance

**Problem:** Some drivers get overloaded with calls while others sit idle. The scheduler optimizes for speed (closest driver) without considering how many calls a driver already has.

**Root Cause:**
- No capacity planning enabled in FSL — the scheduler doesn't check how many active calls a driver has
- No "max concurrent jobs" work rule configured
- High-performing drivers who complete calls quickly get immediately assigned the next one, creating burnout
- Newer or slower drivers don't get enough volume to build experience

**Impact:**
- Top drivers averaging 8-10 calls/day while others do 2-3
- Fatigue leads to longer response times later in the shift
- Member satisfaction drops on the 7th+ call because the driver is rushing

---

### 3. Towbook Visibility Gap

**Problem:** Off-platform contractors (Towbook) handle ~60% of calls but provide zero GPS data to Salesforce.

**Root Cause:**
- Towbook integration sends status updates (Accepted, En Route, Completed) but NOT driver coordinates
- 72 Towbook drivers: 0% have GPS in Salesforce
- `ActualStartTime` on Towbook SAs is fake — bulk-updated at midnight, not real arrival time
- Real arrival must be reconstructed from ServiceAppointmentHistory "On Location" status change

**Impact:**
- Cannot calculate accurate ATA for Towbook calls
- Cannot include Towbook in closest-driver analysis
- Cannot monitor Towbook driver positions in real-time
- 27% PTA miss rate partially driven by inability to track Towbook response times accurately

---

### 4. Garage Capacity Blind Spot

**Problem:** Garages get overloaded because the dispatch system doesn't consider current load.

**Root Cause:**
- FSL Capacity-Based Resources feature is not enabled
- No "max calls per day" or "max concurrent calls" per garage
- Priority matrix sends calls to the same garage regardless of how busy it is
- Transit Auto Detail (44% satisfaction) is overwhelmed — high volume + slow response

**Impact:**
- Top 3 underperforming garages account for most dissatisfied surveys
- Members wait 170+ minutes at overwhelmed garages while nearby garages have capacity
- Dispatchers manually intervene to redirect calls (22% manual dispatch rate) — reactive, not preventive

---

### 5. Static Priority Matrix

**Problem:** The territory priority matrix is a fixed lookup table that doesn't adapt to real-time conditions.

**Root Cause:**
- 180 PTA settings — each garage has a fixed promise (60-120 min) regardless of current demand
- Priority cascade (P2 → P3 → P5 → P10) is the same at 8 AM and 8 PM
- No dynamic adjustment for: time of day, day of week, weather, current queue depth, driver availability
- Matrix was configured once and rarely updated

**Impact:**
- Morning rush sends all calls to the same P2 garages even when they're full
- Evening calls cascade to P10 (spot) because closer garages already maxed out
- PTA promises are unrealistic for current capacity — 27% miss rate
- Seasonal patterns (winter = more calls) aren't reflected in the matrix

---

## Phased Optimization Plan

### Phase 1: Measure & Visibility (Weeks 1-4) ✅ MOSTLY COMPLETE

**Goal:** Understand what's happening before trying to fix it.

| Deliverable | Status | Impact |
|-------------|--------|--------|
| Satisfaction Score Analysis with call-date attribution | ✅ Done | VP can see daily trends, worst garages, root causes |
| SA History Report with reassignment impact | ✅ Done | Audit any call — who was assigned, was closest picked, PTA vs arrival |
| Dispatch channel breakdown (Fleet/On-Platform/Towbook) | ✅ Done | See which channel has the most reassignment time lost |
| Closest driver analysis per SA | ✅ Done | For each call, was the closest driver picked? |
| GPS health monitoring | ✅ Done | Track which drivers have active GPS |
| Executive insights (VP-level) | ✅ Done | Auto-generated analysis: what happened, why, what to do |

**Remaining:**
- [ ] Driver workload dashboard — calls per driver per day, distribution chart
- [ ] Garage capacity monitor — current queue depth vs historical average
- [ ] Towbook ATA accuracy report — compare ActualStartTime vs real On Location

---

### Phase 2: Quick Wins — Configuration (Weeks 5-8)

**Goal:** Improve dispatch without writing code, using FSL configuration and Salesforce admin.

| Action | Effort | Expected Impact |
|--------|--------|----------------|
| **Enable Capacity-Based Resources** — set max concurrent jobs per driver | SF Admin (1 day) | Prevents driver overload, distributes work evenly |
| **Add "Count" Work Rule** — max 6 calls per driver per day | SF Admin (1 day) | Forces scheduler to spread work across drivers |
| **Update PTA Settings** — differentiate by work type (Battery=45m, Tow=90m) | SF Admin (2 days) | Realistic promises → fewer PTA misses → better satisfaction |
| **Review Priority Matrix** — remove underperforming garages from P2 | Business decision + SF Admin | Stop sending calls to garages that can't handle them |
| **Populate STM Addresses** — enter garage addresses for all 128 territories | Data entry (3 days) | Scheduler has better fallback for travel calculation |

---

### Phase 3: Smart Dispatch — Data-Driven (Weeks 9-16)

**Goal:** Use 12 months of historical data to optimize dispatch decisions.

| Action | Effort | Expected Impact |
|--------|--------|----------------|
| **Train satisfaction model** — logistic regression on 50K surveys: ATA → satisfaction probability | Data science (1 week) | Know exactly when wait time kills satisfaction |
| **Train cost model** — distance + driver type → cost per call | Data science (1 week) | Know the cost of each dispatch decision |
| **Historical simulation** — test different Δmax thresholds on 12 months of data | Data science (1 week) | Find the optimal tradeoff: how many extra minutes of wait save how much cost |
| **Pareto frontier** — plot satisfaction vs cost for different policies | Analysis (2 days) | Give leadership a clear tradeoff curve to make an informed decision |
| **Dispatcher decision support** — show cost comparison in FSLAPP when a call is dispatched | Dev (2 weeks) | "Driver A: 12 min, $45. Driver B: 18 min, $28. Save $17, +6 min wait" |

---

### Phase 4: Automation — Scheduler Tuning (Weeks 17-20)

**Goal:** Implement the optimal policy in the FSL Scheduler.

| Action | Effort | Expected Impact |
|--------|--------|----------------|
| **Reweight Service Objectives** — reduce ASAP weight, increase Minimize Travel | SF Admin (1 day) | Scheduler considers cost, not just speed |
| **Dynamic PTA** — adjust promises based on current queue depth | Apex development (2 weeks) | Realistic promises = fewer misses = better satisfaction |
| **Towbook GPS integration** — request coordinates from Towbook API | Integration (2-4 weeks) | Enable closest-driver analysis for 60% of calls |
| **Weather-aware dispatch** — adjust PTA and capacity for snow/ice days | Dev (1 week) | Prevent PTA violations on high-demand days |

---

### Phase 5: Continuous Optimization (Ongoing)

| Action | Frequency | Purpose |
|--------|-----------|---------|
| Retrain satisfaction/cost models | Quarterly | Keep models current with changing patterns |
| Review PTA settings vs actual performance | Monthly | Calibrate promises to reality |
| Audit top 10 worst SAs per week | Weekly | Identify systematic dispatch failures |
| Monitor Pareto frontier position | Weekly | Are we staying at the optimal tradeoff? |
| Review dispatcher manual override rate | Weekly | High rate = scheduler not working well |

---

## Expected Outcomes

| Metric | Current | After Phase 2 | After Phase 4 |
|--------|---------|--------------|--------------|
| Member Satisfaction | 83% | 85% | 87%+ |
| PTA Miss Rate | 27% | 18% | 12% |
| Auto-Dispatch Rate | 79% | 85% | 90% |
| Avg Response Time | 62 min | 55 min | 48 min |
| Cost per Call | Baseline | -8% | -15% |
| Manual Dispatch Rate | 22% | 15% | 8% |
| Reassignment Rate | 15% | 10% | 7% |

---

## Key Dependencies

1. **Business decision:** What is the acceptable extra wait time (Δmax) to save cost? The data model will provide options, but leadership must choose.
2. **Towbook cooperation:** GPS data from Towbook would unlock optimization for 60% of calls. Without it, Towbook dispatch remains a black box.
3. **SF Admin access:** Phases 2 and 4 require changes to FSL Scheduling Policy, Service Objectives, and Work Rules.
4. **Data quality:** STM addresses need to be populated. PTA settings need review. Capacity settings need configuration.
