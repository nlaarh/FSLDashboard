# SA History Report — Design & Implementation

**Endpoint**: `GET /api/sa/{number}/report`
**Frontend**: `SAReportModal.jsx` opened via `SAReportContext` / `SALink`
**Backend**: `routers/sa_report.py`

---

## Purpose

Full-screen modal showing the complete lifecycle of any SA number: timeline from Received → Completed, per-assignment driver snapshots (map + table), and a rule-based plain-English narrative.  Accessible from any SA number anywhere in the app via `<SALink number="SA-XXXXXX" />`.

---

## SF Round Trips (3 total, 4 if cascade fallback needed)

| Trip | Queries (parallel) | Purpose |
|------|-------------------|---------|
| 1 | SA lookup | Get SA fields, territory, dispatch method |
| 2 | SAHistory + AssignedResource + TerritoryMembers | Timeline events, assign events, Fleet member roster |
| 2b | SAHistory(ServiceTerritoryId) + TerritoryMembers | **Only if SA cascaded from Fleet → Towbook** — find original Fleet territory |
| 3 | ServiceResourceSkill + GPS lat + GPS lon + **AssetHistory(ERS_Driver__c)** | Skills, GPS positions, **truck login/logout events** |

Result cached 2 minutes: `cache.cached_query('sa_report_{number}', _fetch, ttl=120)`

---

## Driver Eligibility — Three Gates (Fleet only)

A driver appears in a dispatch snapshot only if they pass **all three** at the assignment time T:

### Gate 1: On Truck (AssetHistory)
- Source: `AssetHistory WHERE Field = 'ERS_Driver__c'`
- **Login** = `OldValue=null, NewValue=SR_Id (0Hn prefix)`
- **Logout** = `OldValue=SR_Id, NewValue=null`
- 8,132 records total in the org; self-authored by the driver via FSL Track app
- Logic: find most recent event for the driver with `CreatedDate ≤ T`. If login → on truck. If logout or no record → exclude.
- **Bypass**: the step's assigned driver (name match) always passes this gate, in case their shift started > 24h before the lookback window.
- SOQL limitation: `NewValue`/`OldValue` **cannot be used in WHERE clause** on `AssetHistory`. Must fetch all records for the time window and filter in Python.
- Lookback: 24 hours before first assignment time → ensures any shift start is captured.

### Gate 2: Has Matching Skills (ServiceResourceSkill)
- Required skills derived from `WorkType.Name` using `_SKILL_MAP` in `misc.py`
- If no required skills → all skilled members pass (empty set = any)

### Gate 3: Has GPS Position (ServiceResourceHistory)
- `LastKnownLatitude` + `LastKnownLongitude` must exist near time T
- Used for map position only — NOT used to determine "on shift"
- GPS window: `min(all_step_times) - 15min` → `max(all_step_times) + 5min` (covers all steps)

### Why not GPS-only?
- `MobileLastSyncTime` is NOT tracked in `ServiceResourceHistory` (0 records)
- `IsActive` in `ServiceResourceHistory` has only 155 records — permanent hire/terminate only
- No shift login/logout audit trail exists in SF except `AssetHistory.ERS_Driver__c`
- GPS pings can persist after a driver goes off shift (phone left on) — unreliable alone

---

## Towbook Steps

Towbook assignment steps (driver name starts with 'Towbook' or step has no Fleet GPS data) are handled differently:
- **No** truck login check, skill check, or GPS lookup
- Frontend shows purple "Towbook contractor — off-platform dispatch. Driver location is not tracked on the FSL map."
- No map rendered for Towbook steps

---

## Cascade SA Handling

When an SA starts in a Fleet territory but cascades to a Towbook garage:
- `ServiceTerritoryId` on the SA points to the Towbook garage at query time
- Detection: territory members all start with 'towbook' → empty `members` list
- Fallback: query `ServiceAppointmentHistory WHERE Field='ServiceTerritoryId'` → find original Fleet territory → refetch members for that territory
- This enables showing the Fleet dispatch snapshot even though the SA ultimately went to Towbook

---

## Shared Utilities (dispatch_utils.py)

| Function | Purpose |
|----------|---------|
| `build_truck_login_hist(rows)` | Parse AssetHistory rows → `{sr_id: [(ts, 'login'/'logout'), ...]}` |
| `is_on_truck(driver_id, ts, hist)` | Check if driver was logged into truck at time T |
| `gps_at_time(driver_id, ts, lat_hist, lon_hist)` | Get driver GPS position at time T |
| `parse_assign_events(rows, sa_id_set)` | Parse SAHistory ERS_Assigned_Resource__c rows |
| `build_assign_steps(events, members, ...)` | Build per-assignment snapshots with all three gates |

---

## Frontend Components

| Component | Purpose |
|-----------|---------|
| `SAReportContext.jsx` | React context with `open(number)` / `close()` — mounts modal globally at App level |
| `SALink.jsx` | Thin button wrapper — any SA number becomes clickable |
| `SAReportModal.jsx` | Full-screen modal: Narrative → Timeline → Dispatch Snapshots → SA footer |
| `mapIcons.js` | Shared Leaflet icon factories used by both MapView and SAReportModal |

**Driver map markers** use `Tooltip` (hover) showing: name, distance from member, role badge (ASSIGNED / CLOSEST / ELIGIBLE / NO MATCHING SKILLS).

---

## Known SF Constraints

- `AssetHistory.NewValue` / `OldValue` cannot be filtered in SOQL WHERE — fetch all and filter in Python
- `ERS_Dispatch_Method__c` (formula) cannot GROUP BY
- Towbook `ActualStartTime` is a midnight bulk-update — never use for Towbook response time
