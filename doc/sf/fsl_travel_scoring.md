# FSL Travel Time Calculation & Driver Scoring

**Verified Mar 15, 2026 — via API queries, Apex code, Tooling API, and FSL documentation**

---

## 1. Travel Distance: Aerial (Haversine) — No Roads

This org does NOT use Street Level Routing (SLR). Verified: 0 TravelMode records, `isGeoCodeSyncEnabled = false`.

FSL calculates straight-line distance using the Haversine formula:

```
distance = 2 × R × arctan2(√a, √(1-a))
where a = sin²(Δlat/2) + cos(lat1) × cos(lat2) × sin²(Δlon/2)
R = 3,959 miles (Earth radius)
```

**Travel Time = distance ÷ speed**

- `FSL__Travel_Speed__c` on ServiceResource: **blank for all resources in this org**
- When blank, FSL uses a default speed (~30 mph)
- Our FSLAPP backend uses 25 mph (Buffalo metro verified average)

---

## 2. Driver Location Sources

| Scenario | Location Source | Field |
|----------|----------------|-------|
| **First job of the day** | Home base / garage | `ServiceTerritoryMember.Latitude/Longitude` |
| **Between jobs (during shift)** | Previous SA's end location | `ServiceAppointment.Latitude/Longitude` |
| **Real-time GPS** | FSL mobile app (updates every ~5 min) | `ServiceResource.LastKnownLatitude/Longitude` |

### GPS → STM Auto-Sync (Discovered Mar 15, 2026)

**CORRECTION:** The FSL mobile app **automatically syncs** `ServiceResource.LastKnownLatitude/Longitude` → `ServiceTerritoryMember.Latitude/Longitude` every time it updates GPS. Verified by matching timestamps: STM.LastModifiedDate = SR.LastKnownLocationDate exactly, and LastModifiedBy = the driver's own user record.

This means **GPS IS effectively used for scheduling** — it flows through STM. The scheduler reads STM, and the mobile app keeps STM updated with real GPS.

### Remaining Problem: Drivers Without Active App

Before the Thursday Mar 12 STM sync fix, only 17 of 712 STM records had coordinates org-wide. After the fix, WNY Fleet has 14 of 38 (37%) with coords. Drivers whose app is not actively running still have no STM coords → FSL falls back to the ServiceTerritory address (garage).

See `scheduler_policy_analysis.md` for the full data analysis.

---

## 3. Scheduling Policy: Most Likely "Closest Driver"

### Auto-Scheduler Policy (reverse-engineered from data, Mar 15, 2026)

The auto-scheduler's policy is stored in a protected managed package field (`FSL__Automator_Config__c.FSL__Scheduling_Policy_Id__c`) that cannot be read via any API. Analysis of 349 WNY Fleet SAs (Mar 10-14) shows the scheduler favors **distance over availability** — when closest ≠ soonest, closest wins 69% vs soonest 31%. Best-fit weights: **ASAP 0 / Travel 100**, matching the **"Closest Driver" policy**. See `scheduler_policy_analysis.md` for full analysis.

### Overlap Flow Policy (via flows + Tooling API)

The auto-scheduler uses **"Highest priority"** (Id: `a22Pb000001KlCuIAK`):
- Last modified: May 5, 2025 by Ankit Chawla (FSL implementor)
- Evidence: Both `Resource_Absence_Fix_Overlap` and `AAA_ERS_Fix_Schedule_SA_Overlaps` flows hardcode this policy name

| Objective | Weight | % of Score |
|-----------|--------|------------|
| **ASAP** | 9,000 | 90% |
| **Minimize Travel** | 1,000 | 10% |

### All 5 Policies in This Org

| Policy | ASAP | Travel | Ratio | Used By |
|--------|------|--------|-------|---------|
| **Highest priority** | 9,000 | 1,000 | 9:1 | Auto-scheduler + overlap flows + 5 territory optimizers |
| Copy of Highest Priority | 1,000 | 10 | 100:1 | WNY Fleet optimizer only (created Mar 13, 2026) |
| Emergency | 700 | 300 | 2.3:1 | Not assigned |
| Closest Driver | — | 100 | Travel only | Not assigned |
| DF TEST- Closest Driver | — | 100 | Travel only | Not assigned |

### Where the Policy Config Is Stored

The auto-scheduler's default policy is stored in `FSL__Automator_Config__c.FSL__Scheduling_Policy_Id__c` — a **fully protected managed package object**. Not accessible via standard API, Tooling API, Metadata API, or Execute Anonymous. Only readable through the FSL Admin UI: **Field Service Settings → Automated Scheduling**.

---

## 4. The Complete Scoring Formula

```
Total Score = (ASAP_Grade × 9,000) + (Travel_Grade × 1,000) + Priority_Points
```

### ASAP Grade (0-100, linear interpolation)

Measures: "When can this driver START the job?"

```
ASAP_Grade = (Candidate_Start - Latest_Start) / (Earliest_Start - Latest_Start) × 100
```

- Considers driver availability (current job end time) + travel time to reach the SA
- Grade 100 = earliest possible start among all candidates
- Grade 0 = latest possible start
- An idle driver 15 miles away might score higher than a busy driver 3 miles away

### Minimize Travel Grade (0-100, linear interpolation)

Measures: "How far is this driver from the job?"

```
Travel_Grade = (Longest_Distance - Candidate_Distance) / (Longest_Distance - Shortest_Distance) × 100
```

- Grade 100 = closest driver
- Grade 0 = farthest driver
- Uses aerial distance only (no roads)

### Priority Points (added on top)

| Priority Level | Points Added |
|----------------|-------------|
| 1 (Critical) | 25,500 |
| 2 | 20,500 |
| 3 | 15,500 |
| 4 | 12,000 |
| **5 (Normal ERS)** | **10,000** |
| 6 | 7,000 |
| 7 | 5,000 |
| 8 | 3,000 |
| 9 | 2,000 |
| 10 or null | 1,000 |

87% of ERS SAs are Priority Group 5 (10,000 points).

---

## 5. Worked Examples

### Example A: Both Drivers Idle → Closest Always Wins

| | Driver A (Close) | Driver B (Far) |
|---|---|---|
| Distance | 5 miles | 15 miles |
| Status | Idle | Idle |
| Travel time | 10 min | 30 min |
| Can start | 2:10 PM | 2:30 PM |

**Grades:**
- ASAP: A=100, B=0
- Travel: A=100, B=0

**Scores:**
- A: (100 × 9,000) + (100 × 1,000) + 10,000 = **1,010,000** ← wins
- B: (0 × 9,000) + (0 × 1,000) + 10,000 = **10,000**

**When both idle, closest ALWAYS wins** because ASAP and Travel align.

### Example B: Closer Driver Is Busy → Farther Driver Wins

| | Driver A (Close, busy) | Driver B (Far, idle) |
|---|---|---|
| Distance | 3 miles | 12 miles |
| Status | Finishes at 3:00 PM | Idle now |
| Travel time | 6 min | 29 min |
| Can start | 3:06 PM | 2:29 PM |

**Grades (spread = 37 min):**
- ASAP: A=0, B=100
- Travel: A=100, B=0

**Scores:**
- A: (0 × 9,000) + (100 × 1,000) + 10,000 = **110,000**
- B: (100 × 9,000) + (0 × 1,000) + 10,000 = **910,000** ← wins

**Driver B wins despite being 4x farther** because ASAP (9,000) crushes Travel (1,000).

### Example C: Close Call — Slightly Busier, Much Closer

| | Driver A (Very close, slightly busy) | Driver B (Far, idle) |
|---|---|---|
| Distance | 2 miles | 20 miles |
| Status | Finishes at 2:10 PM | Idle now |
| Travel time | 4 min | 40 min |
| Can start | 2:14 PM | 2:40 PM |

**Grades (spread = 26 min):**
- ASAP: A=100 (starts earlier!), B=0
- Travel: A=100, B=0

**Both grades favor Driver A** — the closer driver who finishes soon enough to still arrive first.

**Key insight:** When a close driver's current job ends soon, their combined availability + short travel can still beat a far idle driver's long travel. The crossover point depends on the specific time gap.

---

## 6. Candidate Pool Generation (Before Scoring)

Before scoring, FSL filters candidates through Work Rules:

```
1. SA needs scheduling (FSL__Auto_Schedule__c = true)
2. Find SA's territory → get all ServiceTerritoryMembers
3. Apply Work Rules to filter:
   - Match Required Skills (Tow, Battery, Tire, etc.)
   - Territory membership (Primary/Secondary)
   - Resource availability (operating hours, absences, existing appointments)
   - Maximum Travel From Home (requires STM address — broken for 98.5% of drivers)
4. Surviving candidates: max 20 per SA
5. Score each candidate using formula above
6. Assign highest scorer
```

---

## 7. What FSL CANNOT Do (This Org)

| Capability | Status | Why |
|------------|--------|-----|
| **Road-based routing** | NOT available | SLR not enabled, 0 TravelModes |
| **Real-time traffic** | NEVER available | FSL doesn't support this at all |
| **Time-of-day speed variation** | NOT available | Requires SLR |
| **Live GPS for scheduling** | NOT used | Scheduler reads STM coords, not SR.LastKnownLat/Long |
| **Per-resource travel speed** | NOT configured | FSL__Travel_Speed__c blank on all SRs |
| **Efficiency factor** | NOT configured | FSL__Efficiency__c null on all SRs |

---

## 8. Why "Closest Driver" Wins Only 26% of the Time

This was Mulesoft's dispatch logic, not FSL's. But the same principle applies:

1. **ASAP dominates scoring (90%)** — availability matters more than proximity
2. **STM coordinates missing (98.5%)** — FSL thinks everyone is at the garage, so travel grades are meaningless for first-job-of-day
3. **Skill filtering** — if only 2 of 10 nearby drivers have the required skill (e.g., Flat Bed), the pool is small
4. **Cascading effect** — the Priority Matrix sends calls to specific garages in priority order, not to the nearest driver globally

---

## 9. How to Enable "Farther But Faster" (Street Level Routing)

If SLR were enabled:
- FSL would use HERE Maps road network data
- A driver 15 miles away on a highway (15 min drive) could beat a driver 5 miles away through city streets (25 min drive)
- Uses historical average speeds per road segment — still no live traffic
- Requires: TravelMode records, SLR license, geocoding enabled
- **This org does not have SLR and there are no plans to enable it**

---

## References

- `force-app/main/default/flows/AAA_ERS_Fix_Schedule_SA_Overlaps.flow-meta.xml` — Hardcodes "Highest Priority" policy
- `force-app/main/default/flows/Resource_Absence_Fix_Overlap.flow-meta.xml` — Same
- `apidev/FSLAPP/backend/simulator.py:22-30` — Haversine formula
- `apidev/FSLAPP/backend/dispatch.py:15` — TRAVEL_SPEED_MPH = 25
- FSL Scoring: https://help.salesforce.com/s/articleView?id=sf.pfs_optimization_theory_service_objectives.htm
- FSL ASAP: https://help.salesforce.com/s/articleView?id=service.pfs_optimization_theory_service_objectives_asap.htm
- FSL Travel: https://help.salesforce.com/s/articleView?id=service.pfs_optimization_theory_service_objectives_min_travel.htm
