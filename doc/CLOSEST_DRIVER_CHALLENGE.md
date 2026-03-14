# Closest Driver Assignment — Challenges & Solutions

## The Problem

AAA WCNY's roadside drivers are always on the road. When a member calls for help, the goal is simple: **send the nearest available driver**. But the FSL Enhanced Scheduler wasn't built for this model — it was built for technicians who start from home each morning.

## Why the Scheduler Doesn't Assign the Closest Driver

### 1. Home Base Calculation (By Design, Not a Bug)

The FSL Enhanced Scheduler calculates travel from the driver's **home base** (ServiceTerritoryMember address), not their real-time GPS. The "Closest Driver" scheduling policy includes work rules:

- Maximum Travel From Home is 10 Mins
- Maximum Travel From Home is 20 Mins
- Maximum Travel From Home is 30 Mins
- Maximum Travel From Home is 40 Mins
- Maximum Travel From Home is 50 Mins
- Maximum Travel From Home is 60 Mins

**The Scheduler does NOT use `LastKnownLatitude/Longitude` (GPS) for assignment decisions.** GPS tracking feeds the mobile app and dispatcher map — not the scheduling engine.

### Example: How This Fails

```
📍 Flat tire at Exit 42, I-90 (near Syracuse)

Driver A (Mike):  🚛 Currently 3 miles away (just finished a job)
                  🏠 Home: Watertown (75 miles north)

Driver B (Lisa):  🚛 Currently 35 miles away (in Utica)
                  🏠 Home: Syracuse (5 miles away)
```

**What happens:** The Scheduler checks "Maximum Travel From Home":
- Mike: 75 miles from home → **EXCLUDED** (exceeds 60-min rule)
- Lisa: 5 miles from home → **ASSIGNED**

**Result:** Lisa drives 35 miles. Mike was 3 miles away doing nothing. Customer waits 40 extra minutes. AAA pays for 32 extra miles of fuel.

### 2. No Home Addresses Populated

Even if the home base calculation was useful, **zero out of 501** ServiceTerritoryMember records have a street address. Only 65 have geocoded lat/lon. The Scheduler has almost nothing to calculate with.

### 3. GPS Coverage Gap

**By driver type (business hours, March 13 2026):**

| Driver Type | Total | Had GPS | % |
|-------------|-------|---------|---|
| Fleet Driver | 89 | 25 | 28% |
| On-Platform Contractor | 232 | 47 | 20% |
| Off-Platform Contractor (Towbook) | 72 | 0 | 0% |

- **Towbook drivers will never have GPS** — Towbook integration sends status updates and timestamps but NOT driver GPS coordinates
- During business hours, ~83% of FSL app drivers who worked had usable GPS
- The 124 ServiceResources with no driver type are office/dispatch staff, not field drivers

## Data Sources Available

### Real-Time: `ServiceResource.LastKnownLatitude/Longitude`
- Updated every ~5 minutes by the FSL mobile app
- Only stores the MOST RECENT position (overwrites on update)
- Useless for historical analysis

### Historical: `ServiceResourceHistory`
- **4.25 million records** tracking every GPS change
- Full movement trail for every FSL app driver
- Can reconstruct where a driver was at any specific timestamp
- Enables "closest driver at time of assignment" analysis
- Towbook drivers have zero entries

### SA History: `ServiceAppointmentHistory`
- Tracks SA field changes, NOT driver GPS
- `Latitude/Longitude` entries = job location geocoding, not driver position
- Useful for: who assigned, who dispatched, status timestamps

## Current Workaround: Resource Absences

Resource Absences mark drivers as unavailable, removing them from the Scheduler's candidate pool:

| Absence Type | Count | Purpose |
|-------------|-------|---------|
| Real-Time Location | 435 | Marks drivers without active GPS |
| Last assigned Service Location | 233 | Updates location reference |
| Break | 4,344 | Standard break tracking |
| Call out | 102 | Driver called out |
| PTO / Vacation | 81 | Planned time off |

**UAT results (March 13):** After configuring Resource Absences, auto-assignment went from **0% to 83%**.

This doesn't fix the home base calculation — it removes the worst candidates so the Scheduler works with a smaller, cleaner pool.

## AAA's Dispatch Philosophy: The 25-Minute Rule

**Balance cost vs customer service:**

| Scenario | Action | Why |
|----------|--------|-----|
| Closest driver within ~25 min of faster driver | Send closest | Saves fuel, mileage, truck wear. Acceptable wait. |
| Closest driver 25+ min slower than faster driver | Send faster | Customer can't wait. Service quality > cost. |

## Potential Solutions

### Option A: Fix GPS Coverage First (Quick Win)
- Get all Fleet Drivers on the FSL mobile app (41 out of 89 have no GPS)
- Enforce app login at shift start
- Monitor GPS Health metric in Command Center
- **Impact:** More drivers visible = better Scheduler decisions even with home base limitation

### Option B: Populate ServiceTerritoryMember Addresses
- Set each driver's STM address to their **garage/shop location** (not actual home)
- This gives the Scheduler a better starting point than nothing
- **Limitation:** Still not real-time position, but better than blank

### Option C: Build Custom Assignment Logic (Bypass Scheduler)
- Use `ServiceResourceHistory` to get driver positions at time of assignment
- Build our own "closest driver" calculation using Haversine distance from actual GPS
- Apply the 25-minute threshold rule
- Surface recommendations to dispatchers via the FSLAPP Dispatch Insights panel
- **Advantage:** Uses real GPS, applies AAA's actual business logic
- **Challenge:** Doesn't replace the Scheduler — adds a recommendation layer

### Option D: Use Appointment Booking with "Closest" Objective
- Configure the FSL "Book Appointment" action with Minimize Travel objective
- This may use a different location source than the batch Scheduler
- **Needs investigation:** Does Book Appointment use GPS or home base?

### Option E: Flow-Based Auto-Assignment
- Build a Salesforce Flow that triggers on SA creation
- Query `ServiceResource.LastKnownLatitude/Longitude` for all available drivers in territory
- Calculate distance to SA location
- Apply 25-minute threshold logic
- Assign the optimal driver
- **Advantage:** Full control, uses real GPS, applies business rules
- **Challenge:** Requires Salesforce Flow development, needs to handle edge cases

## Fleet vs Towbook: Who Owns What

| | Fleet Drivers | Towbook Drivers |
|--|---------------|-----------------|
| **Who assigns** | FSL Scheduler + AAA dispatchers | Towbook facility dispatchers |
| **Our control** | Full — we can fix GPS, STM addresses, Scheduler config | None — Towbook handles their own assignment |
| **GPS source** | FSL mobile app (real-time) | None (we use last job location as estimate) |
| **Our focus** | Fix assignment quality | Track & measure their performance |

**Key insight:** Towbook assignment is Towbook's problem. Our operational focus should be on the 89 Fleet drivers where we control the outcome. We track Towbook closest-driver % for visibility and contract conversations.

## Measurement

The FSLAPP Command Center Dispatch Insights panel tracks:
- System vs Dispatcher assignment rates (Fleet only)
- Closest driver % — **3-way split:**
  - **System** (green) — FSL Scheduler auto-assigned Fleet SAs
  - **Dispatcher** (amber) — manually assigned Fleet SAs
  - **Towbook** (purple) — Towbook facility-assigned SAs (uses last-job-location GPS estimate)
- GPS Health metric — stacked bar showing fresh/recent/stale/no-GPS
- Response time comparison (System vs Dispatcher)
- 45-min SLA hit rates

### Garage Over-Capacity Detection

The system detects when a garage has more open calls than available drivers:

- **Available drivers** = active ServiceTerritoryMembers with fresh GPS (< 4 hours old = logged into FSL app and working)
- **Capacity ratio** = Open calls ÷ Available drivers

| Ratio | Status | Badge | Meaning |
|-------|--------|-------|---------|
| < 1 | Normal | None | More drivers than calls |
| 1–2 | Busy | Yellow "Busy" | Every driver has a call |
| 2+ or 0 drivers | Over Capacity | Red "Over Cap" (pulsing) | Calls stacking, consider cascade |

Shown in:
- **Garage Operations table** — badge next to garage name + driver count under Open column
- **Command Center** — badge on territory cards + "Over Cap" / "Busy" counts in top bar

**Future:** Use `ServiceResourceHistory` to calculate true "closest at time of assignment" for accurate measurement.
