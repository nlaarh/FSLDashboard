# AAA WCNY — Dispatch Optimization Roadmap

**Prepared for:** VP of Road Service
**Date:** March 25, 2026

---

## Bottom Line

We dispatch ~1,000 roadside calls per day. Member satisfaction is 83% (just above the 82% target), but we're leaving time and money on the table due to five structural issues. A phased approach addresses each one — starting with configuration changes that take days, not months.

---

## The Five Issues

| # | Issue | Impact Today |
|---|-------|-------------|
| 1 | **Closest driver not assigned** — scheduler doesn't know where drivers are | Drivers 15 mi away assigned; 3 mi driver skipped |
| 2 | **Towbook is a black box** — no GPS, no dispatch control, fake timestamps | Can't track or optimize 60% of calls |
| 3 | **Driver overload** — no capacity limits, top drivers get 8+ calls/day | Burnout, slower response on late calls |
| 4 | **Garage overload** — calls keep going to full garages | 170+ min waits at overwhelmed garages |
| 5 | **Static promises** — same PTA whether it's a battery or tow, morning or night | 27% of promises broken |

---

## The Roadmap

### Phase 1: Visibility ✅ Complete
*We built the tools to see the problems.*

- Satisfaction Score Analysis — by call date, by garage, actionable VP insights
- SA History Report — full assignment chain, closest driver analysis, reassignment impact
- Dispatch channel breakdown — Fleet vs On-Platform vs Towbook
- GPS health monitoring, capacity alerts, dispatcher drill-downs

**What this solved:** We can now measure every problem. Before this, we were guessing.

---

### Phase 2: Quick Configuration Wins (2 weeks)
*Fix the obvious things with SF admin changes — no code.*

| Action | Solves | Expected Result |
|--------|--------|----------------|
| Set driver daily capacity to 6 calls max | Driver overload | Even workload distribution |
| Add max 2 concurrent calls work rule | Driver overload | No stacking calls on one person |
| Set PTA by work type: Battery=45m, Tow=90m, Tire=60m | Broken promises | PTA miss drops from 27% → ~15% |
| Populate driver home addresses (garage location) | Closest driver | Scheduler has a baseline for travel calc |
| Demote 3 worst-performing P2 garages in priority matrix | Garage overload | Calls stop flooding underperforming garages |

**Satisfaction impact:** 83% → ~86%

---

### Phase 3: Move Towbook to On-Platform (6 weeks)
*The single biggest improvement — bring 60% of calls under full visibility and control.*

Start with top 10 highest-volume Towbook garages (handles ~40% of Towbook calls). Give their drivers the FSL mobile app.

| Before (Towbook) | After (On-Platform) |
|------------------|-------------------|
| No GPS | GPS every 5 min |
| Fake arrival times | Real On Location timestamp |
| Towbook picks the driver | FSL Scheduler assigns optimal driver |
| Can't see queue depth | Real-time capacity monitoring |
| Excluded from closest-driver analysis | Fully included |
| Can't balance workload | Visible per driver |

**Satisfaction impact:** 86% → ~89%

---

### Phase 4: Data-Driven Optimization (8 weeks)
*Use 12 months of history to find the optimal dispatch strategy.*

- Train a model: for every extra minute of wait, how much does satisfaction drop?
- Train a cost model: distance + driver type → cost per call
- Simulate different policies: "accept 10 min extra wait to save 8 miles" — what's the tradeoff?
- Give dispatchers a cost comparison tool: "Driver A: 12 min, $45. Driver B: 18 min, $28."
- Build dynamic PTA that adjusts for time of day, weather, and current queue depth

**Satisfaction impact:** 89% → ~91%. **Cost impact:** -12% per call.

---

### Phase 5: Full Automation (4 weeks)
*Scheduler makes optimal decisions without human intervention.*

- Reweight scheduler objectives: balance speed vs cost
- Auto-skip overloaded garages in the cascade
- Weather-aware PTA (snow day = +45 min automatically)
- Continuous model retraining quarterly

**Target state:** 90%+ satisfaction, <10% PTA miss, <8% manual dispatch, 15% lower cost per call.

---

## What Each Phase Delivers

| Metric | Today | Phase 2 | Phase 3 | Phase 4 | Phase 5 |
|--------|-------|---------|---------|---------|---------|
| Satisfaction | 83% | 86% | 89% | 91% | 91%+ |
| PTA Miss Rate | 27% | 15% | 12% | 10% | <10% |
| Auto-Dispatch | 79% | 85% | 90% | 92% | 92%+ |
| Manual Dispatch | 22% | 15% | 10% | 8% | <8% |
| Avg Response | 62 min | 55 min | 50 min | 48 min | 45 min |
| Cost per Call | Baseline | -3% | -8% | -12% | -15% |

---

## Key Decision Needed

**Phase 3 (Towbook → On-Platform) requires a business decision:** Are we willing to provision FSL mobile app licenses for contractor drivers? This is the single highest-impact change — it unlocks GPS, dispatch control, and capacity monitoring for 60% of our calls.

---

*Appendix with full technical details: see FSL_Dispatch_Challenges_and_Solutions.md*
