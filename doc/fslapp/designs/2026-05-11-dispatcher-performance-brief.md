# Dispatcher Performance — What We Measure, What We Found, and What We Need to Fix

**Audience:** Leadership  
**Date:** May 2026  
**Purpose:** Explain how we assess dispatcher performance, what the data revealed about how dispatchers are organized, and why the current measurement approach needs to evolve.

---

## Why This Matters

Every service call that goes wrong — a member waiting 90 minutes after being told a driver is on the way, a call that gets passed from driver to driver, a tow that never arrives — flows through a dispatcher decision. Dispatchers decide which driver gets assigned, how quickly, and whether to intervene when something is going sideways.

We built a Dispatcher Scorecard to help managers identify who needs coaching and support. But before we could trust the numbers, we needed to understand how dispatchers are actually organized and whether we were measuring the right things.

---

## How Dispatchers Are Actually Organized

We analyzed 90 days of Salesforce data (2,018 service calls, May 2026) and found that **dispatchers are not organized by geography — they are organized by channel and shift.**

### Two channels, fundamentally different jobs

**Fleet dispatchers** handle calls assigned to AAA's own drivers. The drivers have set schedules, known availability, and are pre-positioned in territories. The dispatcher selects from a roster of drivers they know.

**Towbook dispatchers** handle calls assigned to independent contractors — towing companies, locksmiths, specialty service providers. Contractor availability changes constantly. Response times are longer because contractors are not pre-positioned and often travel farther.

| Dispatcher | Channel | What They Dispatch | Shift |
|---|---|---|---|
| Jeremy Harrington | Fleet | Battery, Tire, Lockout | 9am – 2pm |
| Jon Carroll | Fleet | Battery, Tire, Lockout | 9am – 2pm |
| Catherine Alger | Towbook | Tow Pick-Up, Tow Drop-Off | 9am – 2pm |
| Kristen Hartman | Towbook | Tow Drop-Off (dominant), Tow Pick-Up | 2pm – 8pm |
| Deborah Kalenda | Towbook | Tow Pick-Up, Winch Out | 9am – 2pm |
| Shawn Gancasz | Mixed | Battery, Tow Pick-Up | 2pm – 8pm |
| Mary Trichilo | Supervisor | Winch Out specialist interventions | Scattered |

**Mary Trichilo is a special case.** 60% of her 35 dispatches in 90 days are Winch Outs — the most complex call type requiring specialized equipment. She is not running a general dispatch queue. She is a supervisor directly intervening on the hardest calls before they escalate. She should not be measured on the same scale as general dispatchers.

---

## What We Are Currently Measuring

The Dispatcher Scorecard gives each dispatcher a score from 0 to 100 built from four areas:

| Area | Weight | What It Measures |
|---|---|---|
| Completion Quality | 40 pts | Did the drivers assigned by this dispatcher actually complete the call? Harder call types count more so dispatchers handling complex work are not unfairly penalized. |
| Speed | 25 pts | How quickly did the dispatcher assign a driver after the call came in? |
| Reliability | 20 pts | What percentage of assignments took over 30 minutes? |
| Volume | 15 pts | How many calls did this dispatcher handle in 90 days? |

These four areas are reasonable — but the analysis revealed that we are measuring the **wrong end of the process**.

---

## What the Data Revealed

### Finding 1 — We are measuring speed to assign, not speed to arrive

Speed and Reliability measure how fast a dispatcher assigns a driver. That is the dispatcher's action. But what the member experiences is how long they wait after being told a driver is coming.

**28% of service calls — 569 out of 2,018 — had the driver take over 60 minutes to arrive after being assigned.** That is the real gap, and we are not measuring it.

The time from driver assignment to driver arrival (what we call "stall time") looks like this across the team:

| Dispatcher | Channel | Typical stall | Worst 10% |
|---|---|---|---|
| Jon Carroll | Fleet | 24 minutes | 52 minutes |
| Jeremy Harrington | Fleet | 36 minutes | 97 minutes |
| Catherine Alger | Towbook | 48 minutes | 146 minutes |
| Deborah Kalenda | Towbook | 48 minutes | 119 minutes |
| Kristen Hartman | Towbook | 77 minutes | 155 minutes |

A dispatcher who assigns a driver instantly but selects one who is 90 minutes away scores well on our current scorecard. The member still waits 90 minutes.

### Finding 2 — Fleet and Towbook cannot be compared on the same scale

The data confirms what we suspected: dispatching Fleet drivers and dispatching Towbook contractors are structurally different jobs with different expectations.

- **Fleet** typical stall: 28 minutes
- **Towbook** typical stall: 58 minutes

This gap is not because Towbook dispatchers are slower. It is because tow trucks travel farther, move slower, and Tow Drop-Off calls have two legs (pick up the car, then deliver it). Putting a Fleet dispatcher and a Towbook dispatcher on the same leaderboard is not a fair comparison — and it could lead to the wrong coaching conversations.

### Finding 3 — The most actionable comparison is Carroll vs. Harrington

Jon Carroll and Jeremy Harrington do identical jobs: Fleet channel, same call types (Battery, Tire, Lockout), same shift (9am–2pm), same territory structure. They are the only true apples-to-apples pair on the team.

Carroll's drivers arrive on location in **24 minutes** (median). Harrington's take **36 minutes** — 50% longer. Same job, same conditions, 50% difference in how fast members get help. This is likely a driver selection pattern — Carroll may be consistently choosing geographically closer or more available drivers. This is an exact coaching conversation waiting to happen, but only visible because we looked at the right metric.

### Finding 3 — Reassignment between dispatchers is not happening

We looked for cases where Dispatcher A made an assignment that then got overridden and reassigned by Dispatcher B. This would indicate a bad initial driver selection. The result: zero cases in 2,018 records. When SAs get reassigned, it goes through an automated system — not a traceable dispatcher action. This failure mode does not appear in the data the way we expected.

---

## What Needs to Change

### 1 — Add "driver arrival" to the scorecard

The scorecard needs a fifth dimension: how long did it take the driver to arrive after being assigned? This is the metric that reflects member experience. It also measures the quality of the dispatcher's driver selection — a driver assigned from the right territory, at the right availability level, arrives faster.

### 2 — Score Fleet and Towbook separately

Fleet dispatchers should be compared against Fleet peers. Towbook dispatchers against Towbook peers. Mixing them produces misleading rankings and wrong coaching priorities.

### 3 — Create a supervisor view for Trichilo

Mary Trichilo's work is valuable and important — she is handling the calls that would otherwise escalate. But her performance cannot be measured the same way as a general dispatcher queue. She needs a separate view that recognizes specialist intervention work.

### 4 — Build a real-time "at-risk SA" panel (next phase)

The scorecard tells managers who needs coaching over the past 90 days. It does not help today, right now, when a driver has been assigned for 45 minutes and has not moved. The next phase is a live panel showing SAs currently stalled — dispatcher assigned, driver not on location — so managers can intervene before the call becomes a crisis.

---

## Summary

| Question | Answer |
|---|---|
| How are dispatchers organized? | By channel (Fleet vs Towbook) and shift — not by geography |
| What are we measuring today? | Speed to assign a driver and completion rate |
| What should we be measuring? | Also speed to arrive — the member's actual wait time |
| What is the biggest failure mode? | 28% of SAs have the driver take over 60 minutes to arrive after assignment |
| Who is the most actionable comparison? | Carroll vs Harrington — same job, Carroll's drivers arrive 50% faster |
| What is the immediate fix? | Add driver arrival time to the scorecard, split Fleet/Towbook, remove Trichilo from general ranking |
