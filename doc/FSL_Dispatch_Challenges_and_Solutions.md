# AAA WCNY — Dispatch Challenges, Solutions & Optimization Roadmap

---

## Challenge 1: Closest Driver Not Always Assigned

### What's Wrong
The FSL Scheduler doesn't know where drivers actually are. It was designed for plumbers who start from home — AAA drivers are already on the road. The scheduler uses "home base" addresses for travel calculation, but zero out of 501 driver records have a home address populated. The Resource Absence workaround provides the LAST job location — not the CURRENT location.

**Result:** A driver 3 miles from the member gets skipped. A driver 15 miles away gets assigned because the scheduler thinks he's closer (based on stale data).

### Solution
**Use real-time GPS for dispatch decisions.**

| Option | How | Pros | Cons |
|--------|-----|------|------|
| **A. Populate STM addresses with garage locations** | Data entry — set each driver's home address to their garage | Scheduler has a baseline; simple; no code | Still not real-time; driver may be 30 miles from garage |
| **B. GPS-fed Resource Absences** | Flow that updates absence location every 5 min from LastKnownLatitude | Scheduler uses fresh position; works within existing FSL framework | Extra SF API calls; absence records grow; 5 min delay |
| **C. Post-dispatch override (FSLAPP)** | Let scheduler assign, then FSLAPP checks GPS and suggests a closer driver to the dispatcher | No SF config change; human in the loop; builds trust | Manual; not scalable; adds dispatcher workload |
| **D. Custom Apex dispatch** | After-trigger checks real GPS, overrides scheduler if a closer driver exists within threshold | Fully automated; uses real GPS; customizable threshold | Requires Apex development; conflicts with scheduler |

**Recommendation:** Start with **A** (1 day, immediate improvement) + **B** (1 week, sustained improvement). Evaluate **D** after Phase 3 data analysis proves the value.

**Would this resolve it?** Option A alone would improve ~40% of cases. Option B would improve ~80%. The remaining 20% are cases where no driver has GPS (off-shift, app not running).

---

## Challenge 2: Towbook Garages — No Visibility, No Control

### What's Wrong
Towbook garages handle ~60% of all calls but operate as a black box:
- **No GPS** — Towbook integration sends status updates but NEVER driver coordinates. 72 Towbook drivers: 0% have GPS in Salesforce.
- **Fake timestamps** — `ActualStartTime` on Towbook SAs is bulk-updated at midnight, not when the driver actually arrived.
- **No dispatch control** — AAA sends the call to Towbook; Towbook's facility dispatcher picks the driver. AAA doesn't know who, where, or how fast.
- **No capacity visibility** — Can't tell if a Towbook garage is overloaded until members start complaining.

### Solution: Move Towbook Garages to On-Platform

**What "On-Platform" means:** The contractor's drivers use the FSL mobile app instead of Towbook. They appear in the same system as Fleet drivers — GPS tracked, scheduler-assigned, real-time status.

| Capability | Towbook (Off-Platform) | On-Platform Contractor | Improvement |
|-----------|----------------------|----------------------|-------------|
| Driver GPS | ❌ None | ✅ Every 5 min | Can track, can assign closest |
| Real ATA | ❌ Fake midnight update | ✅ Real On Location timestamp | Accurate satisfaction metrics |
| Dispatch control | ❌ Towbook picks driver | ✅ FSL Scheduler assigns | Optimal driver selection |
| Capacity monitoring | ❌ Blind | ✅ Real-time queue depth | Prevent overload |
| Closest driver analysis | ❌ Impossible | ✅ Full GPS history | Include in optimization |
| PTA accuracy | ❌ Can't measure | ✅ Precise tracking | Realistic promises |
| Cost optimization | ❌ Can't compare | ✅ Distance-based cost model | Include in tradeoff analysis |
| Driver workload balance | ❌ Unknown | ✅ Visible per driver | Prevent burnout |

**Migration path:**
1. Identify top 10 highest-volume Towbook garages (they handle ~40% of Towbook calls)
2. Provision FSL mobile app licenses for their drivers
3. Create ServiceResource records, assign skills, set territory membership
4. Switch dispatch from Towbook cascade to FSL Scheduler
5. Monitor for 2 weeks, then migrate next batch

**Would this resolve it?** Moving the top 10 Towbook garages to On-Platform would bring ~40% of currently invisible calls under full visibility and control. Full migration would cover all 60%.

---

## Challenge 3: Driver Workload Imbalance

### What's Wrong
The scheduler optimizes for speed — send the closest driver. Fast drivers who complete calls quickly get immediately assigned the next one. Result: some drivers do 8-10 calls/day, others do 2-3.

- No capacity limit per driver
- No "max concurrent jobs" work rule
- Top drivers burn out → slower response on call #7+
- New drivers don't get experience

### Solution
**Enable FSL Capacity Planning + Count Work Rules.**

| Action | How | Effect |
|--------|-----|--------|
| **Enable Capacity-Based Resources** | SF Admin → Field Service Settings → Enable | Scheduler checks driver capacity before assigning |
| **Set daily capacity per driver** | ServiceResource.DailyCapacity = 6 (configurable) | No driver gets more than 6 calls/day |
| **Add Count Work Rule** | "Max 2 concurrent active calls per driver" | Prevents stacking calls on one person |
| **Add "Resource Priority" Service Objective** | Weight idle drivers higher than busy ones | Scheduler prefers drivers with fewer active calls |

**Would this resolve it?** Yes — capacity-based scheduling is the standard FSL solution for workload balancing. Combined with the count work rule, it ensures even distribution. The 6-call daily cap is adjustable based on work type (tow drivers may do fewer, battery drivers more).

---

## Challenge 4: Garage Capacity Overload

### What's Wrong
The priority matrix sends calls to the same garage regardless of how busy it is. Transit Auto Detail (44% satisfaction) gets call after call because it's P3 in the cascade for many zones — even when it already has a 2-hour backlog.

- No max queue depth per garage
- No dynamic cascade that skips overloaded garages
- Dispatchers manually redirect (22% manual rate) — reactive, not preventive

### Solution
**Dynamic cascade + capacity monitoring.**

| Action | How | Effect |
|--------|-----|--------|
| **Add capacity field to garages** | Custom field `ERS_Max_Concurrent__c` on ServiceTerritory | Define max calls per garage (e.g., Transit Auto = 5) |
| **Apex trigger on SA assignment** | Before assigning to a garage, check current open count vs max | Auto-skip overloaded garages, cascade to next in matrix |
| **FSLAPP Capacity Alerts** | ✅ Already built — shows "OVER CAP" on Command Center | Dispatchers see overload in real-time |
| **Dynamic PTA** | When a garage is at 80% capacity, increase PTA by 30 min | Realistic promises during high demand |

**Would this resolve it?** The Apex trigger would prevent the root cause — calls never get sent to a full garage. Combined with the capacity alerts already in FSLAPP, dispatchers have both automated protection and real-time visibility.

---

## Challenge 5: Static Priority Matrix

### What's Wrong
The territory priority matrix is a fixed table — 180 records, configured once, rarely updated. It doesn't adapt to:
- Time of day (morning rush vs evening)
- Day of week (weekday vs weekend)
- Weather (snow day = 3x call volume)
- Current queue depth
- Driver availability
- Seasonal patterns

PTA settings are also static: most garages promise 88 minutes regardless of work type. Battery calls take 38 minutes, tow calls take 115 minutes — one PTA doesn't fit both.

### Solution
**Differentiated PTA + data-driven matrix review.**

| Action | How | Effect |
|--------|-----|--------|
| **Work-type-specific PTA** | Update ERS_Service_Appointment_PTA__c: Battery=45m, Tow=90m, Tire=60m, Lockout=45m | Promises match reality → fewer PTA misses |
| **Quarterly matrix review** | Use FSLAPP satisfaction data to identify underperforming P2/P3 garages | Demote bad garages, promote good ones |
| **Time-of-day PTA adjustment** | Apex trigger: if CreatedDate hour > 18 (evening), add 30 min to PTA | Evening calls get realistic promises |
| **Weather-aware PTA** | Integration with weather API: if snow/ice, add 45 min to PTA | Storm days don't generate mass PTA violations |
| **Dynamic cascade (Phase 4)** | ML model scores garages based on current capacity + historical performance | Calls route to the best available garage, not just the closest |

**Would this resolve it?** Work-type PTA alone would reduce PTA misses from 27% to ~15%. Adding time-of-day and weather adjustments would get to ~10%. Dynamic cascade is the long-term fix that adapts in real-time.

---

## Solution Summary: What Fixes What

| Solution | Closest Driver | Towbook Blind Spot | Workload Balance | Garage Overload | Static Matrix | Satisfaction Impact |
|----------|:---:|:---:|:---:|:---:|:---:|:---:|
| Populate STM addresses | ✅ | | | | | +1% |
| GPS-fed Resource Absences | ✅ | | | | | +2% |
| Move Towbook to On-Platform | ✅ | ✅ | ✅ | ✅ | | +3-5% |
| Enable Capacity Planning | | | ✅ | ✅ | | +2% |
| Count Work Rule (max 6/day) | | | ✅ | | | +1% |
| Work-type PTA | | | | | ✅ | +2% |
| Garage capacity trigger | | | | ✅ | ✅ | +2% |
| Quarterly matrix review | | | | ✅ | ✅ | +1% |
| Cost optimization model | ✅ | | | | ✅ | neutral (saves $) |

**Biggest single impact:** Moving Towbook garages to On-Platform. It solves GPS visibility, dispatch control, capacity monitoring, and workload balance in one move — for 60% of calls.

---

## Phased Roadmap

### Phase 1: Measure (✅ Done)
FSLAPP dashboards, satisfaction analysis, SA History Reports, dispatch insights

### Phase 2: Quick Config Wins (Weeks 1-2)
- Populate STM addresses
- Work-type specific PTA (Battery=45m, Tow=90m)
- Enable Capacity-Based Resources
- Add Count Work Rule (max 6 concurrent)
- Review and update priority matrix for top 10 worst garages

### Phase 3: Towbook Migration (Weeks 3-8)
- Pilot: Move top 5 Towbook garages to On-Platform
- Provision FSL app licenses, create resources, set skills
- Monitor 2 weeks, compare satisfaction before/after
- If successful: migrate next 10 garages

### Phase 4: Data-Driven Optimization (Weeks 9-16)
- Train satisfaction model (ATA → satisfaction probability)
- Train cost model (distance + driver type → cost)
- Historical simulation (find optimal Δmax threshold)
- Dispatcher decision support tool in FSLAPP
- Dynamic PTA based on capacity and weather

### Phase 5: Automation (Weeks 17-20)
- Reweight Service Objectives (reduce ASAP, add cost awareness)
- Dynamic cascade (Apex trigger skips full garages)
- Weather-aware PTA adjustment
- Continuous model retraining (quarterly)
