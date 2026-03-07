# FSLAPP Redesign — Two-Space Architecture

## Problem
- Response time calculation was wrong: used `CreatedDate → ActualStartTime` for all SAs
- Towbook SAs update `ActualStartTime` in bulk at midnight — NOT real arrival time
- Mixed daily operations data with historical analytics on same pages
- All garages showed 300+ min "response time" (actually Towbook sync lag)

## Root Cause (verified March 5, 2026)
| Dispatch Method | % of SAs | `ActualStartTime` behavior |
|---|---|---|
| Field Services (internal) | ~26% | Real-time, reliable. ATA = 17-46 min typically |
| Towbook (off-platform) | ~74% | Bulk midnight sync. Shows 300+ min. UNRELIABLE. |

## Correct Metrics
- **PTA** (Promised Time of Arrival) = `ERS_PTA__c` (minutes). Available on all ERS SAs.
- **PTA Due** = `ERS_PTA_Due__c` (datetime). The actual clock time promised to member.
- **ATA** (Actual Time of Arrival):
  - Field Services only: `ActualStartTime - CreatedDate` (reliable, real-time)
  - Towbook: NOT calculable from ActualStartTime. Use PTA as the promise.
- **On-site Time** = `ActualStartTime → ActualEndTime` (reliable for both, once stamped)
- **Dispatch Method** = `ERS_Dispatch_Method__c` ('Field Services' or 'Towbook')

## Two-Space Architecture

### Space 1: Daily Operations (`/` and `/ops/garage/:id`)
**Who**: Dispatchers, shift supervisors
**When**: During the workday, checking every few minutes
**Data**: TODAY only (12:00 AM ET → now), live SOQL, cached 2-5 min

#### Dashboard (`/`)
- Territory grid: open calls, completed today, completion %, avg PTA
- Alert strip for territories with long-waiting members
- Click territory → Day View

#### Garage Day View (`/ops/garage/:id`)
- Today's SA list with columns: SA#, WorkType, Status, PTA, ATA (if Field Services), Driver, Created, Wait Time
- KPIs: total today, completed, open, avg PTA, avg ATA (Field Services only)
- Per-SA detail: PTA promised vs ATA actual (for FS), on-site time

### Space 2: Analytics (`/analytics` and `/analytics/garage/:id`)
**Who**: Supervisors, managers
**When**: Weekly/monthly review
**Data**: Historical periods, pre-computed nightly, instant load

#### Analytics Dashboard (`/analytics`)
- All territories comparison table
- Sortable by: volume, PTA avg, satisfaction, completion %
- Period selector: week, month, custom range

#### Garage Analytics (`/analytics/garage/:id`)
- Scorecard (8-dimension scoring)
- Performance trends (daily/weekly/monthly charts)
- Satisfaction analysis
- Resource/fleet breakdown
- PTA distribution (buckets: <30, 30-45, 45-60, 60-90, 90+)

### Navigation
```
/                          → Daily Ops Dashboard
/ops/garage/:id            → Garage Day View
/analytics                 → Analytics Dashboard
/analytics/garage/:id      → Garage Analytics (scorecard + performance)
/command-center            → Map Command Center (stays as-is)
```

## Backend Endpoints

### Daily Ops (live SOQL)
- `GET /api/ops/territories` — All territories with today's KPIs
- `GET /api/ops/territory/:id` — Single territory today detail + SA list
- `GET /api/command-center` — Map view (existing, fixed metrics)

### Analytics (can be live or pre-computed)
- `GET /api/analytics/territories?weeks=4` — All territories summary
- `GET /api/analytics/territory/:id/scorecard?weeks=4` — Scoring
- `GET /api/analytics/territory/:id/performance?start=&end=` — Trends
- `GET /api/analytics/territory/:id/score?weeks=4` — Grade

## Implementation Order
1. Fix metrics (PTA/ATA) in existing endpoints
2. Create daily ops endpoints
3. Create analytics endpoints
4. Update frontend routing + pages
5. Remove old mixed endpoints
