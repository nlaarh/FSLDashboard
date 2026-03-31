# Auto-Scheduler Policy — Reverse-Engineered from Assignment Data

**Analysis date:** March 15, 2026
**Dataset:** 349 completed SAs, WNY Fleet, March 10-14, 2026

---

## Why This Analysis Exists

The auto-scheduler's policy is stored in `FSL__Automator_Config__c.FSL__Scheduling_Policy_Id__c` — a protected managed package field that cannot be read via REST API, Tooling API, Metadata API, or Execute Anonymous. The FSL Admin UI's "Automated Scheduling" section shows only inactive Scheduling Recipes — no policy dropdown exists.

Only 1 of 667K SAs has `FSL__Scheduling_Policy_Used__c` populated (the "Emergency" policy on SA-74126, Dec 2024). The scheduler does not log which policy it uses.

**Approach:** Compare actual driver assignments against all available candidates to infer whether the engine weights Travel (distance) or ASAP (availability) more heavily.

---

## Method

1. Queried all AssignedResource records for completed Field Services SAs on WNY Fleet territory (Mar 10-14)
2. For each SA, used `ERS_Dispatched_Geolocation` as actual driver position and `ServiceAppointment.Latitude/Longitude` as member position
3. Reconstructed realistic candidate pools: only drivers active within 4 hours and with known positions
4. Compared the assigned driver's distance rank and start-time rank against all candidates
5. Tested weight combinations (ASAP 0-100 / Travel 100-0) to find best prediction accuracy

---

## Results

### Assigned Driver Rankings (330 analyzable SAs, avg 8.2 candidates)

| Metric | Rank 1 | Top 3 |
|--------|--------|-------|
| **Distance** (closest) | 34% | 69% |
| **Start time** (soonest) | 28% | 63% |

Distance ranking is stronger → system favors proximity.

### Head-to-Head: When Closest ≠ Soonest (80 conflict cases)

| Winner | Count | % of Conflicts |
|--------|-------|----------------|
| **Closest driver picked** (Travel won) | 33 | 41% |
| **Soonest driver picked** (ASAP won) | 15 | 19% |
| **Neither** (skills/other factor) | 32 | 40% |

Excluding "neither": **Travel wins 69% / ASAP wins 31%** → 2.2:1 ratio favoring distance

### Weight Estimation

| ASAP Weight | Travel Weight | Prediction Accuracy |
|-------------|---------------|-------------------|
| 0 | 100 | **34%** (best) |
| 20 | 80 | 32% |
| 40 | 60 | 32% |
| 60 | 40 | 30% |
| 80 | 20 | 29% |
| 100 | 0 | 28% |

Low accuracy is expected — we can't model skills (the #1 filter before scoring).

### Best Match: "Closest Driver" Policy

The auto-scheduler behavior most closely matches the **"Closest Driver"** policy (Travel only, no ASAP weight). This policy exists in the org but is not visibly assigned to any optimization job.

---

## GPS → STM Sync Discovery

### The FSL mobile app automatically syncs GPS to STM

| Driver | STM LastModified | SR GPS LastKnownDate | Modified By |
|--------|-----------------|---------------------|-------------|
| Arthur Yates Jr. | 2026-03-15 19:00:25 | 2026-03-15 19:00:25 | Arthur Yates Jr. |
| Christopher Mcarthur | 2026-03-14 20:40:47 | 2026-03-14 20:40:47 | Christopher Mcarthur |
| Marcus Gibson | 2026-03-15 19:01:18 | 2026-03-15 19:01:18 | Marcus Gibson |

**Timestamps are identical.** The FSL mobile app writes `ServiceResource.LastKnownLatitude/Longitude` AND updates `ServiceTerritoryMember.Latitude/Longitude` in the same transaction.

### Implications
- **GPS IS effectively used for scheduling** — it flows SR → STM automatically
- 14 of 38 WNY Fleet drivers (37%) have STM coords from active app usage
- 24 of 38 (63%) have no coords → FSL falls back to garage address
- **Thursday Mar 12 fix** deployed additional STM sync logic to cover drivers whose app isn't actively sending

---

## Why Assignment Quality Varies

| Scenario | What Happens | Result |
|----------|-------------|--------|
| Driver's app is active | GPS → STM synced | FSL knows real position → closest driver picked correctly |
| Driver's app not running | No GPS update | STM is blank or stale → FSL uses garage address → distance scoring broken |
| Only 2-3 drivers have required skill | Pool is tiny | Distance ranking barely matters — whoever qualifies gets it |
| Driver between jobs | FSL uses previous SA end location | Usually accurate (driver is near where they just finished) |
| First job of day, no STM coords | FSL uses garage address | All drivers "at garage" → Travel grades equal → ASAP breaks tie |

---

## Known Policies in This Org

| Policy | ASAP | Travel | Assigned To | Matches Behavior? |
|--------|------|--------|-------------|------------------|
| **Closest Driver** | 0 | 100 | Nothing visible | **YES — best match** |
| Emergency | 700 | 300 | Nothing | Partial |
| Highest priority | 9,000 | 1,000 | Overlap flows (hardcoded) | No — would show 85%+ soonest |
| Copy of Highest Priority | 1,000 | 10 | Active optimizer (WNY Fleet) | No — would show 95%+ soonest |
| DF TEST- Closest Driver | 0 | 100 | Nothing | Same as Closest Driver |

---

## References
- Analysis scripts: `/tmp/analyze_v3.py`
- Raw data: `/tmp/fleet_data.json` (349 records from sf_bulk_query)
- STM query: ServiceTerritoryMember WHERE ServiceTerritoryId = '0HhPb00000007qGKAQ'
- SR GPS query: ServiceResource WHERE Name IN (...)
- Related docs: `fsl_travel_scoring.md`, `fsl_scheduling_config.md`
