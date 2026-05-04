# Optimizer Black Box Decoder — Design & Status

## What This Feature Is

A 3-panel UI inside FSLAPP that lets dispatchers understand WHY the FSL optimizer made specific assignment decisions for each run. Replaces the "black box" with a transparent decision tree showing winners, eligible drivers, and excluded drivers with reasons.

---

## Architecture

### Data Flow

```
Salesforce FSL
  FSL__Optimization_Request__c  (one per run, every 15 min)
  ContentDocument: Request_<id>.json  (optimizer input — SAs, Resources, Skills, Absences)
  ContentDocument: Response_<id>.json (optimizer output — assignments, KPIs, unscheduled reasons)
         │
         ▼
optimizer_sync.py  (background thread, runs every 15 min)
         │
         ▼
DuckDB  (~/.fslapp/optimizer.duckdb)
  opt_runs            — one row per optimizer run (KPIs, territory, policy)
  opt_sa_decisions    — one row per SA per run (action, winner, travel)
  opt_driver_verdicts — one row per driver per SA per run (winner/eligible/excluded + reason)
  opt_resources       — driver name cache
  opt_sync_errors     — failed runs for retry
         │
         ▼
FastAPI REST endpoints  (routers/optimizer.py, routers/optimizer_chat.py)
         │
         ▼
React UI  (src/pages/OptimizerDecoder.jsx)
  Left panel:   OptimizerTimeline.jsx    — run list, grouped by date+territory
  Center panel: OptimizerRunDetail.jsx   — SA decisions table, inline decision tree
  Right panel:  OptimizerChat.jsx        — AI chat (Claude) with tool access to DuckDB
```

### UI Route
`/optimizer` — added to Layout.jsx nav as "Optimizer" (BrainCircuit icon)

---

## Files Created / Modified

### Backend
| File | Status | Purpose |
|------|--------|---------|
| `backend/optimizer_db.py` | Created | DuckDB schema, connection pool, query functions |
| `backend/optimizer_sync.py` | Created | Background sync job — pulls SF ContentDocuments, parses JSON, writes to DuckDB |
| `backend/optimizer_init.py` | Created | CLI backfill script: `python optimizer_init.py --days 30` |
| `backend/routers/optimizer.py` | Created | REST endpoints: runs list, run detail, SA decisions, driver analysis, patterns |
| `backend/routers/optimizer_chat.py` | Created | AI chat endpoint — Claude with 7 DuckDB tools, viz output |
| `backend/main.py` | Modified | Registered optimizer routers, started sync thread on startup |
| `backend/database.py` | Modified | Added `optimizer_sync_audit` table for admin UI |

### Frontend
| File | Status | Purpose |
|------|--------|---------|
| `frontend/src/pages/OptimizerDecoder.jsx` | Created | 3-panel layout page |
| `frontend/src/components/OptimizerTimeline.jsx` | Created | Left panel — run timeline |
| `frontend/src/components/OptimizerRunDetail.jsx` | Created | Center panel — SA decisions table |
| `frontend/src/components/OptimizerChat.jsx` | Created | Right panel — AI chat |
| `frontend/src/components/OptDecisionTree.jsx` | Created | Inline decision tree card |
| `frontend/src/components/OptKpiBar.jsx` | Created | KPI before/after bar chart |
| `frontend/src/components/OptExclusionChart.jsx` | Created | Exclusion pattern horizontal chart |
| `frontend/src/api.js` | Modified | Added optimizer API functions |
| `frontend/src/App.jsx` | Modified | Added `/optimizer` route |
| `frontend/src/components/Layout.jsx` | Modified | Added Optimizer nav link |
| `frontend/src/index.css` | Modified | Added `optFadeUp` + `optBounce` animations |

---

## Salesforce Data Source

### Objects Used
- `FSL__Optimization_Request__c` — one record per optimizer run (prefix `a1u`)
- `FSL__Territory_Optimization_Request__c` — junction: which territory ran (prefix `a27`)
- `ContentDocumentLink` — links JSON files to OR records
- `ContentVersion` — the actual Request/Response JSON file bodies

### File Naming Convention
Files are stored as ContentDocuments linked to `FSL__Optimization_Request__c` via `ContentDocumentLink`:
- `Request_<OR_Id>.json` — optimizer input (Resources, Services, Skills, Absences, TimeHorizon)
- `Response_<OR_Id>.json` — optimizer output (objectChanges, assignedResourcesToUpsert, territoryKpis)

### Content of Request JSON (top-level keys)
```json
{
  "CalendarDays": [...],
  "Resources": [...],
  "Services": [...],
  "WorkOrderLineItems": [...],
  "Territories": [...],
  "SchedulingPolicy": [...],
  "NonAvailabilities": [...],
  "TimeHorizon": {}
}
```

### Content of Response JSON (top-level keys)
```json
{
  "objectChanges": {},
  "assignedResourcesToUpsert": [...],
  "territoryKpis": {
    "territory_pre_opt_kpis": [...],
    "territory_post_opt_kpis": [...]
  },
  "unscheduledServiceAppointments": [...]
}
```

---

## ⚠️ BLOCKED — Required Before Data Will Flow

### Problem
The sync job runs every 15 min and finds OR records in SF, but cannot read the `ContentDocument` / `ContentVersion` files because the API integration user is **missing the `QueryAllFiles` permission**.

Every SOQL query against `ContentVersion`, `ContentDocument`, or `ContentDocumentLink` returns 0 rows for this user — even though the files exist. This is because Salesforce has a separate permission (`PermissionsQueryAllFiles`) that controls file visibility, independent of `ViewAllData`.

### Verified Facts
- API user: `apiintegration@nyaaa.com` (Id: `005Pb00000xVltVIAS`)
- Profile: `Read Only`
- `PermissionsViewAllData` = **true** ✅
- `PermissionsQueryAllFiles` = **false** ❌ ← THE BLOCKER

The sync error log currently shows: `"Missing content versions — files not attached to run"` for every OR — this is the symptom.

### Fix Required (SF Admin action)

**One permission change in Salesforce Setup:**

> **Setup → Permission Sets → [the permission set assigned to `apiintegration@nyaaa.com`] → System Permissions → ☑ Query All Files**

**Objects this unlocks (read-only):**
| Object | Why Needed |
|--------|-----------|
| `ContentVersion` | Read file body (VersionData) and metadata |
| `ContentDocument` | Find files by title pattern |
| `ContentDocumentLink` | Find which files are linked to which OR record |

No other permission changes needed. The user already has ViewAllData for all other objects.

### After the Fix
Once "Query All Files" is enabled, the next sync tick (within 15 min of server start) will:
1. Find OR records since the last cursor
2. Resolve `Request_*.json` and `Response_*.json` for each OR via ContentDocumentLink
3. Download and parse the JSON bodies
4. Write runs, SA decisions, and driver verdicts to DuckDB
5. The timeline in the UI will populate

To backfill historical data (past 30 days):
```bash
cd apidev/FSLAPP/backend
python optimizer_init.py --days 30
```

---

## DuckDB Schema (Quick Reference)

```sql
opt_runs (
  id TEXT PRIMARY KEY,          -- SF OptimizationRequest Id
  name TEXT,                    -- e.g. "WNY Fleet 14:15"
  territory_id TEXT,
  territory_name TEXT,
  policy_id TEXT, policy_name TEXT,
  run_at TIMESTAMP,
  horizon_start TIMESTAMP, horizon_end TIMESTAMP,
  resources_count INTEGER, services_count INTEGER,
  pre_scheduled INTEGER, post_scheduled INTEGER,
  unscheduled_count INTEGER,
  pre_travel_time_s INTEGER, post_travel_time_s INTEGER,
  pre_response_avg_s REAL, post_response_avg_s REAL
)

opt_sa_decisions (
  id TEXT PRIMARY KEY,          -- "{run_id}_{sa_id}"
  run_id TEXT, sa_id TEXT,
  sa_number TEXT,               -- e.g. "SA-04799070"
  sa_work_type TEXT,
  action TEXT,                  -- "Scheduled" | "Unscheduled"
  unscheduled_reason TEXT,
  winner_driver_id TEXT, winner_driver_name TEXT,
  winner_travel_time_min REAL, winner_travel_dist_mi REAL,
  run_at TIMESTAMP
)

opt_driver_verdicts (
  id TEXT PRIMARY KEY,          -- "{run_id}_{sa_id}_{driver_id}"
  run_id TEXT, sa_id TEXT,
  driver_id TEXT, driver_name TEXT,
  status TEXT,                  -- "winner" | "eligible" | "excluded"
  exclusion_reason TEXT,        -- "territory" | "skill" | "absent" | "capacity"
  travel_time_min REAL, travel_dist_mi REAL,
  run_at TIMESTAMP
)
```

---

## AI Chat (optimizer_chat.py)

- Model: reads from Admin → Settings → primary_model (no user-facing selector)
- Tools available to Claude: `list_runs`, `get_run_detail`, `get_sa_decision`, `get_driver_analysis`, `get_unscheduled_analysis`, `get_exclusion_patterns`, `query_optimizer` (raw SQL)
- Visualization types: `decision_tree`, `kpi_comparison`, `exclusion_chart` (embedded in response as ```json fence)
- Max tool rounds: 5

---

## Known Issues / Next Session TODOs

1. **[BLOCKED] Enable `QueryAllFiles` on SF API user** — nothing works until this is done
2. After permission is granted, restart backend and run backfill: `python optimizer_init.py --days 30`
3. Verify timeline populates and click through to confirm SA decisions + decision trees render
4. Test "Ask AI" button flow: click run → click Ask AI → confirm AI gets context and responds
5. The `opt_sa_decisions.sa_work_type` field is currently NULL (not parsed from request JSON) — low priority
