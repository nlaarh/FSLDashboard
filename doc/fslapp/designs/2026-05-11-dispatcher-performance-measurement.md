# Dispatcher Performance Measurement

**Status:** Active — current implementation in `backend/routers/dispatch_score.py`
**Purpose:** Help managers identify which dispatchers need coaching to ultimately keep SAs from going into trouble — late, unaccepted, stalled, or requiring reassignment.

---

## How We Currently Measure Performance

Each dispatcher receives a composite score of **0–100** built from four dimensions over a rolling 90-day window. Scores reset monthly so each month is its own snapshot.

| Dimension          | Weight | What it tracks                                                         |
|--------------------|--------|------------------------------------------------------------------------|
| Completion Quality | 40 pts | % of assigned calls completed, weighted by call difficulty             |
| Speed              | 25 pts | Median minutes from SA creation → driver assignment                    |
| Reliability        | 20 pts | % of dispatches taking over 30 minutes to assign                       |
| Volume             | 15 pts | Total calls dispatched in the 90-day window                            |

**Score formula:** `Completion Quality + Speed + Reliability + Volume`

### Tier thresholds

| Tier          | Score    |
|---------------|----------|
| Elite         | 85–100   |
| Proficient    | 70–84    |
| Developing    | 50–69    |
| Needs Support | < 50     |

### Call difficulty weights (Completion Quality)

Harder call types count more so a dispatcher handling tough calls is not unfairly compared to one handling easy ones.

| Call Type    | Weight |
|--------------|--------|
| Tow Drop-Off | 0.8×   |
| Battery      | 1.0×   |
| Lockout      | 1.0×   |
| Tire         | 1.1×   |
| Tow Pick-Up  | 1.2×   |
| Locksmith    | 1.3×   |
| Winch Out    | 2.0×   |

### Response time cap

Calls that waited over **120 minutes** are capped before scoring. This protects dispatchers (primarily Alger and Gancasz) who inherit a backlog queue from the overnight shift — those inherited SAs should not count against them.

### Data source

SF object: `AssignedResource`. Query window: `LAST_N_DAYS:90`. Filter: ERS Service Appointments only. Response time = `AssignedResource.CreatedDate` − `ServiceAppointment.CreatedDate`.

---

## What This Model Measures Well

- **Driver selection outcome**: Completion Quality captures whether the dispatcher's chosen driver actually completed the call, adjusted for how hard the call was.
- **Queue monitoring habit**: Speed and Reliability together measure whether the dispatcher is staying on top of the queue — slow medians and high late-assignment rates both point to queue monitoring gaps.
- **Statistical weight**: Volume ensures that a dispatcher with 3 calls at 100% doesn't score Elite — it anchors confidence in the other three dimensions.

---

## Known Gaps (Active Investigation)

The current model is **retrospective and blunt**. It tells you how a dispatcher performed over 90 days, but it does not tell you:

1. **Reassignment rate** — how often did an initial driver assignment fail and require a reassignment? This is the most direct signal of poor driver selection and is completely invisible in the current model. Multiple `AssignedResource` records per SA = reassignment. The data exists in SF; we are not using it.

2. **PTA violation rate** — how often did dispatches assigned by this dispatcher end up violating the member's Promised Time to Arrive? A dispatcher can have an acceptable median response time but still cause PTA violations if they're selecting slow drivers or wrong territories.

3. **No distinction between SA failure causes** — "Not Completed" could mean the member cancelled, the driver couldn't locate the member, the driver had a breakdown, or the dispatcher made a bad call. The current model treats all non-completions equally.

4. **No real-time signal** — the scorecard is a monthly snapshot. It cannot surface an SA that is going wrong right now. The Operational Watchlist (FSLPulse) handles this for dispatchers; there is currently no manager-level operational view showing which dispatcher's queue has SAs at risk.

5. **Supervisor/part-time distortion** — Mary Trichilo (supervisor, 35 dispatches/90 days) is scored on the same scale as full-time dispatchers with 400+ dispatches. Volume partially compensates for this but does not fully remove the comparison distortion.

---

## What We Learned from the Data (May 2026 Analysis)

### How dispatchers are actually organized

Dispatchers are organized by **channel** and **shift** — not by geography.

**Channel split:**

| Dispatcher | Channel | Primary Call Types | Shift (ET) |
|---|---|---|---|
| Jeremy Harrington | Fleet | Battery, Tire, Lockout | 9am–2pm |
| Jon Carroll | Fleet | Battery, Tire, Lockout | 9am–2pm |
| Catherine Alger | Towbook | Tow Pick-Up, Tow Drop-Off | 9am–2pm |
| Kristen Hartman | Towbook | Tow Drop-Off (dominant), Tow Pick-Up | 2pm–8pm |
| Deborah Kalenda | Towbook | Tow Pick-Up, Winch Out | 9am–2pm |
| Shawn Gancasz | Mixed | Battery, Tow Pick-Up | 2pm–8pm |
| Mary Trichilo | Supervisor/Specialist | Winch Out (60% of her calls) | Scattered 9am–3pm |
| Chris Macneil | Overnight | Tow Pick-Up | 6am–8am |

Harrington and Carroll are the only directly comparable pair — same channel, same call types, same shift, same territory structure. All Towbook dispatchers are comparable to each other but not to Fleet dispatchers.

**Trichilo is not a general dispatcher.** 21 of her 35 dispatches in 90 days are Winch Outs — she's a supervisor intervening on the hardest specialist calls. Her 0.0m response time median means she assigns before the SA enters the general queue.

### Failure mode analysis (verified against 2,018 SAs, last 90 days)

**Mode B — Reassignment rate: 0 detected.**
Zero human-to-human reassignments across all 2,018 records. When an SA gets reassigned, it goes through auto-assign or a non-dispatcher account. This failure mode is invisible in the current model and likely not caused by dispatcher behavior directly.

**Mode A — Slow initial dispatch:**
Gancasz is the only outlier at 24.5m median response time (everyone else is 6–16m). His afternoon/evening shift has fewer available drivers and more complex call mix — partly structural, partly behavioral.

**Mode C — Driver stall after dispatch: THE dominant failure mode.**

| Dispatcher | Channel | Median stall | P90 stall |
|---|---|---|---|
| Jon Carroll | Fleet | 24m | 52m |
| Chris Macneil | Overnight | 21m | 83m |
| Mary Trichilo | Supervisor | 26m | 107m |
| Jeremy Harrington | Fleet | 36m | 97m |
| Shawn Gancasz | Mixed | 45m | 99m |
| Catherine Alger | Towbook | 48m | 146m |
| Deborah Kalenda | Towbook | 48m | 119m |
| **Kristen Hartman** | **Towbook** | **77m** | **155m** |

*Stall = time from first driver assignment to SA reaching "On Location" status.*

**28.2% of all SAs (569/2,018) had a stall of over 60 minutes.** This is the real member experience problem — members waiting over an hour after a driver was supposedly assigned.

**Fleet vs Towbook structural gap:**
- Fleet (Harrington + Carroll): Median stall = 28m, P90 = 76m
- Towbook (Alger + Hartman + Kalenda): Median stall = 58m, P90 = 144m

Part of this gap is structural: Towbook contractors travel longer distances, tow trucks are slower, and Tow Drop-Offs have two legs (pickup + delivery). But part is behavioral — Hartman's 77m median is an outlier even within Towbook and is partly explained by Tow Drop-Offs being her dominant call type (179/297 = 60%).

**Within-Fleet comparison (Harrington vs Carroll — same job):**
Carroll median stall = 24m vs Harrington = 36m. Same channel, same call types, same shift. Carroll's assignments arrive 50% faster. This is the most actionable finding — it points to driver selection quality within Fleet (Carroll may be selecting geographically closer or more available drivers consistently).

### What the current scorecard misses

The scorecard measures **speed to assign** (dispatcher response time). It does not measure **speed to arrive** (what the member actually experiences). These are different:

- Speed to assign: SA created → dispatcher assigns driver (what we score today)
- Speed to arrive: Driver assigned → driver arrives On Location (what the member waits for)

A dispatcher who assigns instantly but selects a driver 90 minutes away scores well on Speed but creates a terrible member experience. This is the real gap.

---

## Direction Being Evaluated

Data analysis changes the priorities significantly:

**Drop: Reassignment Rate** — zero human-to-human reassignments detected. Not a real signal with current data.

**Priority 1: Add Driver Arrival dimension to scorecard**
The scorecard currently measures only speed to assign. It needs to also measure the **dispatch-to-arrival gap** (AR creation → On Location). This is the metric that represents actual member experience. Fleet and Towbook must be benchmarked separately because the structural gap (28m vs 58m median) is real and not dispatcher-caused.

**Priority 2: Separate Fleet vs Towbook scoring**
Comparing Harrington (Fleet, Battery calls, 36m stall) to Hartman (Towbook, Tow Drop-Off calls, 77m stall) on the same scale is not valid. The scorecard needs a channel label and peer-group benchmarking.

**Priority 3: Flag Trichilo as supervisor view**
Remove from general dispatcher comparison. Show in a separate "Supervisor Interventions" panel.

**Priority 4: Manager operational view (deferred)**
A real-time panel showing SAs currently stalled (Dispatched >30m with no On Location), tagged to the dispatcher who made the assignment. This closes the gap between retrospective scoring and real-time intervention. Deferred until Priority 1–3 are implemented.
