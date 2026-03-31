# FSL Scheduling & Optimization — Complete Reference

Source: Salesforce Field Service Guide (Spring '26, 966 pages)
PDF: https://resources.docs.salesforce.com/latest/latest/en-us/sfdc/pdf/support_field_service.pdf

---

## Schedule Automation vs Optimization

**Schedule automation** = generating a schedule without manual intervention.
**Schedule optimization** = refining the schedule by evaluating thousands of options to find the OPTIMAL one.

### Automation Methods (no optimization needed)
1. **Auto Schedule checkbox** on SA record + Scheduling Policy Used field
2. **ScheduleService Apex class** — `GetSlots()` for available times, `Schedule()` to book. Can use different policies for slot retrieval (no objectives = fast) vs scheduling (with objectives = graded).
3. **Optimization processes** — also automate, but do full evaluation

### Optimization Types

| Type | Scope | Runtime | When to Use |
|------|-------|---------|-------------|
| **Global Optimization** | All resources in 1+ territories over multi-day horizon | Up to 2 hours | Overnight batch. Run after midnight in territory timezone. Best schedule quality. |
| **In-Day Optimization** | All resources in 1+ territories, short horizon | Up to 5 min (ESO) / 10 min (Legacy) | Throughout the day, reactively. Responds to cancellations, reschedules, onsite delays. |
| **Resource Schedule Optimization (RSO)** | Single resource, typically 1 day | Fast | Last-minute changes: cancelled jobs, late runs, overlaps, emergencies. From dispatcher console or programmatically. |
| **Scheduling Recipes** | Auto-trigger RSO on criteria | Immediate | Auto-resolve overlaps, fill gaps on cancellation. NOT supported in ESO — use Fix Overlaps Flow instead. |
| **Fix Overlaps Flow (Beta, ESO)** | Flow-triggered RSO | Immediate | Replaces Scheduling Recipes in ESO. Configurable in Flow. |
| **Fix Overlaps** | Resolve overlaps only | Fast | When you want to fix overlap without disrupting rest of schedule. Doesn't schedule new work or optimize by objectives. |

### Global Optimization Best Practices
- Choose LOWEST horizon with most schedule activity (e.g., 3 days)
- Run as background process after midnight
- Schedule nightly — progressively optimizes upcoming days
- Use OAAS API for programmatic control with future dates

### In-Day Optimization Best Practices
- Horizon: max 2 days (today + tomorrow)
- Run at set intervals throughout day via scheduled job
- Focuses on today's disruptions (cancellations, delays, reschedules)
- Global optimization yields BETTER metrics; in-day is faster

### Resource Schedule Optimization
- Choose lowest horizon (typically 1 day)
- Use global/in-day for longer periods
- Can be triggered programmatically or from dispatcher console

---

## Scheduling Policies

### Definition
A scheduling policy = **Work Rules** (hard filters) + **Service Objectives** (weighted scoring)

### 4 Standard Policies

| Policy | Description | Use Case |
|--------|------------|----------|
| **Customer First** | Balances customer service with travel minimization. Grades: 1) preferred employee, 2) ASAP, 3) minimize travel | Default for most scenarios |
| **High Intensity** | Employee productivity > customer preferences | Storm/disaster scenarios, high volume |
| **Soft Boundaries** | Same as Customer First but allows cross-territory resource sharing | When local capacity is insufficient |
| **Emergency** | Used with Emergency Chatter action | Emergency dispatch |

### Policy Fields

| Field | Description |
|-------|-------------|
| **Scheduling Policy Name** | Name (add "In-Day" prefix for in-day policies) |
| **In-Day Optimization** | Checkbox. If selected: runs up to 5 min (ESO) / 10 min (Legacy) instead of hours |
| **Fix Overlaps** | Checkbox. If selected: overlaps addressed during optimization. In ESO, overlaps ALWAYS resolved (field irrelevant) |
| **Commit Mode** | "Always Commit" or "Rollback" — what happens when a dispatcher makes changes during ongoing optimization |
| **Description** | Policy description |

### Applying Policies
- **Scheduled optimization jobs**: Field Service Settings > Optimization > Scheduled Jobs
- **Dispatcher console default**: Field Service Settings > Dispatcher Console UI
- **Book Appointment / Candidates**: Field Service Settings > Global Actions > Appointment Booking
- **Auto-schedule on SA**: Set `Scheduling Policy Used` field + select `Auto Schedule` checkbox
- **Dispatcher console appointment list**: Policy field, can be changed per-optimization

---

## Work Rules (Hard Constraints) — Complete Reference

Work rules reject candidates that violate any rule. **Mandatory rules for ALL policies:**
1. Service Resource Availability
2. Earliest Start Permitted (Match Time)
3. Due Date (Match Time)

### All Work Rule Types

| Rule Type | What It Does | ESO Notes |
|-----------|-------------|-----------|
| **Match Skills** | Resource must have required skills from WO/WOLI | Supported |
| **Match Boolean** | Resource boolean field must be true | Supported |
| **Match Fields** | Resource field must match SA/WO field | Supported |
| **Match Territory** | Resource must be in SA's primary/relocated territory only | Scheduling outside working hours can cause violation |
| **Match Time** | Arrival window constraints (Earliest Start, Due Date) | Check Rules doesn't distinguish which time rule violated |
| **Working Territories** | Resource in primary AND secondary territories | Scheduling outside working hours can cause violation |
| **Extended Match** | Expand candidates to neighboring territories | Time-phased Extended Match can affect global optimization performance |
| **Count Rule** | Limit appointments per resource per time period | Supports complex work; shifts spanning midnight NOT supported |
| **Maximum Travel from Home** | Limit distance from STM home address | Supported (but useless for AAA — 0 STM addresses) |
| **Service Resource Availability** | Resource available during SA window (operating hours, absences, schedule) | MANDATORY. Must include Travel From/To Home (can't be empty). Supports flexible breaks (up to 3). |
| **Excluded Resources** | Block specific resources from specific SAs | Supported |
| **Required Resources** | Require specific resource for SA | Supported |
| **Visiting Hours** | Customer availability windows | Supported |
| **Designated Work** | Reserve time slots for specific work types | Shifts and time slots supported |
| **Overtime** | Control overtime scheduling | Only after shift end, not during shift |
| **Service Crew Resources Availability** | Crew availability | Supported |

### ESO-Specific Work Rule Behavior
- ESO tries to FIX rule violations by rescheduling/unscheduling (Legacy leaves them pinned)
- To keep rule-violating appointments on Gantt in ESO, pin them first
- Service Resource Availability: Travel From Home / Travel To Home fields CANNOT be empty in ESO
- Two shifts/time slots < 1 min apart are treated as unified

---

## Service Objectives (Soft Constraints) — Complete Reference

Each assignment scored 0-100 per objective. Weight determines influence on final score.

### All Objective Types with ESO Notes

| Objective | Purpose | ESO Relevance Group Support |
|-----------|---------|---------------------------|
| **Schedule ASAP** | Earliest possible time | SA-based relevance groups only (not resource-based) |
| **Minimize Travel** | Reduce total travel time | STM-based relevance groups only. "Exclude Home Base Travel" NOT supported in ESO |
| **Minimize Overtime** | Reduce overtime duration | STM-based relevance groups only |
| **Minimize Gaps** | Reduce idle time | — |
| **Preferred Resource** | Prefer resources marked as preferred | — |
| **Resource Priority** | Prioritize resources by priority value | — |
| **Same Site** | Group appointments at same location (ESO only) | — |
| **Skill Level** | Prefer higher-proficiency resources | — |
| **Skill Preference** | Prefer higher-priority skill type (ESO only) | — |
| **Service Appointment Priority** | Non-configurable, considers SA priority | — |
| **Custom Objects** | Custom objective logic | — |

### Scoring Mechanics
- **Legacy engine**: Rewards (higher = better). Maximize total reward.
- **ESO engine**: Penalties (lower = better). Minimize total penalty.
- Objective scale: best-case (e.g., 0 travel) to worst-case (e.g., 2+ hours travel)
- Grade = position on scale × weight
- Sum of all weighted grades = schedule score

### Weight Allocation Method (500-point system)
1. Budget 500 total points (Legacy: keep sum ≤ 500)
2. Distribute ALL points across selected objectives
3. Each objective's weight = its share of importance
4. Individual weight should be < combined weights of objectives that should override it together
5. Test via simulation, change ONE weight at a time

---

## Enhanced Scheduling and Optimization (ESO)

### Key Differences from Legacy
- Uses **penalties** (not rewards) for scoring
- **Always resolves overlaps** (Fix Overlaps checkbox irrelevant)
- Tries to **fix rule violations** by rescheduling (Legacy pins them)
- Uses **Platform Integration User** (no separate activation needed)
- Supports: Same Site, Skill Preference, Dynamic Scaling, Travel Modes, Sliding/Reshuffling, Flexible Breaks, Count Rule
- Runtime: Global = up to 2 hours, In-Day = up to 5 minutes
- **Point-to-point predictive routing** regardless of routing settings

### ESO-Only Features
- **Sliding and Reshuffling**: Move SAs between time slots (sliding) or between resources (reshuffling)
  - Sliding only: same resource, same shift, maintains order
  - Sliding + reshuffling: any resource, any day. Lower priority SAs can be dropped.
  - Pin Criteria: SA statuses that prevent movement
  - Keep Scheduled Criteria: SAs that can move but not drop
- **Travel Modes**: Car, Light Truck, Heavy Truck, Bicycle, Walking. Per-territory or per-STM. Toll roads, hazmat.
- **Flexible Breaks**: Up to 3 breaks per resource per day
- **Count Rule**: Limit appointments per resource per period
- **Fix Overlaps Flow**: Replaces Scheduling Recipes
- **Dynamic Scaling (Beta)**: Auto-scale optimization compute
- **Appointment Insights (Beta)**: Recommendations for schedule improvement

### Enabling ESO
1. Setup > Field Service Settings > Enable "Field Service Enhanced Scheduling and Optimization"
2. Also enables Field Service Integration automatically
3. New orgs (Summer '23+) have ESO enabled by default
4. Existing orgs: enable per-territory or all territories
5. Backward compatible — existing config preserved

### ESO Considerations
- If using Queueable Apex: MUST add `Database.AllowsCallouts` annotation
- DML before callout causes exception — ensure DML is in separate transaction
- "Exclude Home Base Travel" NOT supported on Minimize Travel objective
- Multiday work: not supported in Appointment Booking
- Scheduling Recipes NOT supported — use Fix Overlaps Flow

---

## Scheduling Services Matrix (ESO)

### Scheduling Services
| Service | Available in ESO |
|---------|-----------------|
| Appointment Booking | Yes (Objective Calculation explanation missing) |
| Bulk Schedule | Yes |
| Drag & Drop | Yes |
| Emergency Wizard | Yes |
| Get Candidates | Yes (Objective Calculation explanation missing) |
| Keep Scheduled | Yes |
| Reshuffle | Yes (scheduling and appointment booking) |
| Schedule | Yes |
| Schedule over lower priority | Yes |

### Dynamic Gantt Services
| Service | Available in ESO |
|---------|-----------------|
| Fill-in Schedule | Yes |
| Fix Overlaps | Yes |
| Group Nearby | Yes |

### Optimization Services
| Service | Available in ESO |
|---------|-----------------|
| Global Optimization | Yes |
| In-Day Optimization | Yes |
| Resource Schedule Optimization (RSO) | Yes |
| Scheduling Recipes | NOT available (use Fix Overlaps Flow) |

### Transparency Services
| Service | Available in ESO |
|---------|-----------------|
| Activity Reports (Beta) | Yes |
| Appointment Insights (Beta) | Yes |
| Optimization Hub | Yes |
| Optimization Request Files (Beta) | Yes |

---

## Optimization Conflicts

Prevent conflicts when multiple optimization requests hit same dataset:
- Two users optimizing same territory + horizon simultaneously
- Dispatcher reschedules while optimization running
- Auto-schedule triggers during optimization

**Commit Mode on Scheduling Policy:**
- **Always Commit**: Dispatcher changes win, optimization adjusts
- **Rollback**: Optimization results rolled back if conflicts detected

---

## Limits & Limitations (Key Numbers)

| Limit | Value |
|-------|-------|
| Max service resources per user | 1 |
| Max territories in hierarchy | 10,000 |
| Max work orders in hierarchy | 10,000 |
| Max WOLIs in hierarchy | 10,000 |
| Max appointments scheduled at once (Group Nearby) | 50 |
| Max runtime for Group Nearby | 60 seconds |
| Max coordinates in map polygon | 3,200 |
| Max polygons in org (recommended) | 30,000 |
| Max report markers on Gantt map | 500 |
| Max rows on Gantt | 500 |
| Max SAs in appointment list | 3,000 |
| Max SA sharing records in bulk status update | 50,000 |
| Max STM per resource (recommended) | 100 |
| Max skills in Gantt filter | 2,000 |
| Max skills per resource (ESO) | 250 |
| Max values per extended match rule (ESO) | 250 |
| Max operating hours in lookup | 2,000 |
| Max SAs in Long-Term Gantt view | 1,000 |

---

## Performance Best Practices

### Reduce Optimization Complexity
1. Minimize optimization horizon (lowest date range with most activity)
2. Widen appointment slot windows (2-hour vs 30-min)
3. Use work rules (Max Travel from Home, Extended Match) to reduce candidates
4. Use gradeless booking when slot grades not needed (skip objectives for speed)
5. Different policies for GetSlots (no objectives) vs Schedule (with objectives)

### Avoid Apex CPU Timeouts
- See: Guidelines for Avoiding Apex CPU Timeouts in Field Service
- Minimize trigger logic on SA/WO/AR objects during optimization
- Use async processing where possible
- ESO: trigger CPU time reduced to 10 seconds (vs. 60 seconds standard)

### Scheduling Recipes (Legacy only — NOT supported in ESO)
- Auto-trigger RSO on: cancellations, time changes, overlaps

| Scenario | Trigger | Behavior |
|----------|---------|----------|
| **Canceled Appointment** | Status=Canceled, on day of service | Fill gap from next 100 SAs |
| **Shortened Appointment** | Status=Completed/CannotComplete/Canceled, gap >= 15min | Fill gap from next 100 SAs |
| **Late-End Overlap** | Scheduled End extended, overlap >= 10min | Reschedule from next 100 SAs |
| **Emergency Overlap** | Emergency=True, overlap >= 10min | Reschedule around emergency |

- Max 75 active recipes per category, 1,000 per org
- ESO replacement: Fix Schedule Overlaps Flow (Beta) — triggered on late-end overlaps, uses RSO

---

## Work Rule Detailed Configurations

### Database vs Apex Rules
**Database rules** (applied at SOQL level, no performance impact): Max Travel From Home, Working Territories, Match Territory, Extended Match. In ESO also: Match Boolean, Match Fields, Required Resource, Excluded Resource.

**Apex rules** (iterate over resources, higher performance impact): All others.

**Best practice:** Include at least 1 database rule. Filter candidates to ~20 per SA.

### Service Resource Availability (MANDATORY — Detailed Config)
| Setting | Description | ESO Notes |
|---------|-------------|-----------|
| Fixed Gap | Enforce minimum break between SAs (ignores travel time for scheduling) | — |
| Minimum Gap (minutes) | Gap duration (only if Fixed Gap selected) | — |
| Break Start | Single break time per day | — |
| Break Duration | Break length | — |
| Overtime | Allow scheduling in Extended-type time slots | — |
| Travel From Home (min) | Travel buffer before shift | ESO: if empty, all travel within work day. **Enter 500 if transitioning from standard** |
| Travel To Home (min) | Travel buffer after shift | Same as above |

**Flexible Breaks (ESO only):** Up to 3 breaks per rule. Each has: Duration, Earliest Start (min from day start), Latest End (min from day start).

### Extended Match — Key Config
- Max 5 Extended Match rules per policy
- Time-phased: up to 80 records per SR during period
- Non-time-phased: up to 200 records
- Can't use relevance groups
- More than 2 with complex scenarios affects performance
- ESO: if SA matching field empty, all resources valid; if SR field empty, resource not valid

### Match Skills — Key Config
- Match Skill Level: SR skill level must meet or exceed requirement
- Skill Type Logic: All Skills Match (AND, default) or At Least One (OR, ESO only)
- Time-phased: validates skills current at assignment time
- If SA has no required skills: all SRs valid
- If SR has no skills: not valid for any SA with skill requirements

### Count Rule — Key Config
- Time Resolution: Daily only
- Count Type: assignments, durations, or custom field value
- Max 10 count rules on custom field values per policy
- Multiday work not supported
- Shifts spanning midnight not supported in ESO

---

## Optimization Limits (Exact Numbers)

| Limit | Standard | ESO |
|-------|----------|-----|
| Max optimization requests/hour/org | 3,600 | 3,600 |
| Max skills per SR | 100 | 250 |
| Max SAs per resource per day | 200 | 200 |
| Max SAs optimized per rolling 24 hours | 50,000 (optimization only) | 50,000 or 500/FSL license (all scheduling actions) |
| Max SAs per request | 5,000 | 5,000 |
| Max territories per request | 100 | 100 |
| Max SRs per request | 500 | 500 |
| Max days per request | 21 | 30 |
| Max objects per request | 45,000 | N/A |
| RSO max keep-scheduled SAs | 50 | 50 |
| Max JSON file size per request | 6M chars | 6M chars |

### Optimization Run Time (Standard only)
- Low/Medium/High setting in FS Settings
- Ratio 1:2:3 (High = 3x Low)
- Never exceeds 2 hours
- **Session timeout warning:** If optimization runs longer than org session timeout, it gets stuck. Increase timeout to ≥ 2 hours.

---

## Relevance Groups

Apply work rules or service objectives to subsets of SRs or SAs based on Boolean fields.
- Must be mutually exclusive
- Primary and relocation STMs supported; secondary NOT supported
- Extended Match rules cannot use relevance groups
- Overlapping Service Resource Availability rules = error

---

## Appointment Priorities

- Priority field: one or more fields on SA, WO, WOLI (configurable in FS Settings)
- Scale: 1-10 (1=Critical) or 1-100
- SA priority checked first; if empty, derived from parent WO/WOLI
- "Schedule over lower priority appointment" checkbox on SA enables priority-based replacement
- Pinned lower-priority SAs won't be bumped

---

## ESO Transition Checklist

1. Enable Field Service Enhanced Scheduling and Optimization in Setup
2. Check Service Resource Availability rules: **empty Travel To/From Home = unlimited travel in standard but different in ESO** — enter 500 min if keeping behavior
3. Update Field Service Integration permission set for custom fields
4. Separate optimization jobs for Enhanced vs non-Enhanced territories
5. If using Queueable Apex: add `Database.AllowsCallouts` annotation
6. Ensure no DML before callout in same transaction
7. Test Match Skills OR logic if using it (new in ESO)
8. Verify trigger CPU time stays under 10 seconds (reduced from 60s)
9. Note: resource efficiency rounded UP (standard rounds down)
10. Note: cannot schedule SA exactly at break start time
