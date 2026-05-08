# Optimizer Black Box Decoder — Design Spec
**Date:** 2026-04-27  
**Status:** Approved  
**Feature:** Optimizer Decoder — dispatcher tool for understanding FSL optimization decisions

---

## 1. Problem

The FSL optimizer runs every 15 minutes across 3 territories simultaneously. It makes hundreds of driver assignment decisions per run that dispatchers cannot currently explain. When the optimizer gives a call to one driver and skips another, there is no way to understand why — the decision is a black box. Dispatchers need a way to get inside that box, understand what happened, tune policies and objectives, and identify systemic patterns.

---

## 2. Solution Overview

A chat-first interface in FSLAPP where dispatchers type plain English questions and get answers grounded in the actual optimizer request/response data — with dynamic, clickable visualizations rendered inline in chat responses. The system reverse-engineers optimizer decisions by parsing the full request (54 resources, 376 SAs, 14 work rules, 2 objectives) and response (assignments, unscheduled reasons, pre/post KPIs) files stored in SF ContentDocuments.

---

## 3. Architecture

### 3.1 Data Pipeline

```
Salesforce (FSL__Optimization_Request__c + ContentDocuments)
    ↓ every 15 min (delta sync)
optimizer_sync.py
    ↓ parse request + response JSON
DuckDB (optimizer.duckdb)
    ↓ queried by
Backend API + AI tool layer
    ↓ served to
OptimizerDecoder page (chat + timeline + visualizations)
```

### 3.2 Environment Split

| Environment | DB Path | Days of data | Init method |
|---|---|---|---|
| Local dev | `~/.fslapp/optimizer.duckdb` | 30 days | `optimizer_init.py --days 30` (one-time, ~40 min) |
| Azure prod | `/home/fslapp/optimizer.duckdb` | 30 days | Same script run on Azure, triggered once post-deploy |

Same code path for both — controlled by:
```python
_ON_AZURE = bool(os.environ.get('WEBSITE_SITE_NAME'))
DB_PATH = '/home/fslapp/optimizer.duckdb' if _ON_AZURE else \
          os.path.expanduser('~/.fslapp/optimizer.duckdb')
```

No file transfer between environments. Azure initializes itself on first deploy via the backfill job. Progress visible in Admin sync audit table during the ~40-min backfill window.

---

## 4. DuckDB Schema

### 4.1 `opt_runs` — one row per optimization run
```sql
CREATE TABLE opt_runs (
    id                    VARCHAR PRIMARY KEY,  -- SF OptimizationRequest Id
    name                  VARCHAR,              -- OR-2026-04-127674
    territory_id          VARCHAR,
    territory_name        VARCHAR,
    policy_id             VARCHAR,
    policy_name           VARCHAR,
    run_at                TIMESTAMP NOT NULL,   -- CreatedDate (indexed)
    horizon_start         TIMESTAMP,
    horizon_end           TIMESTAMP,
    resources_count       INTEGER,              -- drivers in scope
    services_count        INTEGER,              -- SAs in scope
    pre_scheduled         INTEGER,
    post_scheduled        INTEGER,
    unscheduled_count     INTEGER,
    pre_travel_time_s     INTEGER,
    post_travel_time_s    INTEGER,
    pre_response_avg_s    DOUBLE,
    post_response_avg_s   DOUBLE,
    synced_at             TIMESTAMP DEFAULT now()
);
CREATE INDEX idx_opt_runs_run_at ON opt_runs(run_at);
CREATE INDEX idx_opt_runs_territory ON opt_runs(territory_id);
```

### 4.2 `opt_sa_decisions` — one row per SA that changed per run
```sql
CREATE TABLE opt_sa_decisions (
    id                    VARCHAR PRIMARY KEY,  -- run_id + sa_id
    run_id                VARCHAR NOT NULL,
    sa_id                 VARCHAR NOT NULL,
    sa_number             VARCHAR,              -- SA-04799070 (indexed)
    sa_work_type          VARCHAR,
    action                VARCHAR,              -- Scheduled | Rescheduled | Unscheduled
    unscheduled_reason    VARCHAR,
    winner_driver_id      VARCHAR,
    winner_driver_name    VARCHAR,
    winner_travel_time_min DOUBLE,
    winner_travel_dist_mi DOUBLE,
    run_at                TIMESTAMP NOT NULL    -- denormalized for range queries
);
CREATE INDEX idx_sa_decisions_sa_number ON opt_sa_decisions(sa_number);
CREATE INDEX idx_sa_decisions_run_id ON opt_sa_decisions(run_id);
CREATE INDEX idx_sa_decisions_run_at ON opt_sa_decisions(run_at);
```

### 4.3 `opt_driver_verdicts` — one row per driver per changed SA per run
```sql
CREATE TABLE opt_driver_verdicts (
    id                    VARCHAR PRIMARY KEY,  -- run_id + sa_id + driver_id
    run_id                VARCHAR NOT NULL,
    sa_id                 VARCHAR NOT NULL,
    driver_id             VARCHAR NOT NULL,
    driver_name           VARCHAR,
    status                VARCHAR,              -- winner | eligible | excluded
    exclusion_reason      VARCHAR,              -- skill | absent | territory | capacity | null
    travel_time_min       DOUBLE,
    travel_dist_mi        DOUBLE,
    run_at                TIMESTAMP NOT NULL    -- denormalized
);
CREATE INDEX idx_verdicts_driver_name ON opt_driver_verdicts(driver_name);
CREATE INDEX idx_verdicts_run_id ON opt_driver_verdicts(run_id);
CREATE INDEX idx_verdicts_sa_id ON opt_driver_verdicts(sa_id);
CREATE INDEX idx_verdicts_run_at ON opt_driver_verdicts(run_at);
```

### 4.4 `opt_sync_cursor` — sync state (single row)
```sql
CREATE TABLE opt_sync_cursor (
    id                    INTEGER PRIMARY KEY DEFAULT 1,
    last_run_created_at   TIMESTAMP,
    last_run_id           VARCHAR,
    total_synced          INTEGER DEFAULT 0,
    last_synced_at        TIMESTAMP,
    last_error            VARCHAR
);
```

### 4.5 `opt_sync_errors` — failed runs for retry
```sql
CREATE TABLE opt_sync_errors (
    run_id                VARCHAR PRIMARY KEY,
    run_name              VARCHAR,
    error                 VARCHAR,
    failed_at             TIMESTAMP,
    retried               BOOLEAN DEFAULT false
);
```

### 4.6 Purge policy
Auto-purge on every sync tick:
```sql
DELETE FROM opt_driver_verdicts WHERE run_at < now() - INTERVAL 30 DAYS;
DELETE FROM opt_sa_decisions    WHERE run_at < now() - INTERVAL 30 DAYS;
DELETE FROM opt_runs            WHERE run_at < now() - INTERVAL 30 DAYS;
```

---

## 5. Admin Audit Table (SQLite)

Lives in existing `fslapp.db` alongside `activity_log`. Admin page gets a new "Optimizer Sync" section.

```sql
CREATE TABLE opt_sync_audit (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at        TEXT NOT NULL,
    finished_at       TEXT,
    status            TEXT NOT NULL,    -- running | success | partial | failed
    runs_found        INTEGER DEFAULT 0,
    runs_inserted     INTEGER DEFAULT 0,
    runs_skipped      INTEGER DEFAULT 0,    -- already in DB (delta dedup)
    runs_failed       INTEGER DEFAULT 0,
    verdicts_inserted INTEGER DEFAULT 0,
    rows_purged       INTEGER DEFAULT 0,
    error_detail      TEXT,
    duration_ms       INTEGER
);
```

Admin panel display (last 50 syncs):
```
Time                Status     Found  Stored  Skipped  Failed  Verdicts   Duration
Apr 28 01:45:12    ✅ success    3      3        0        0      918        4.2s
Apr 28 01:30:08    ✅ success    3      3        0        0      924        3.8s
Apr 28 01:15:44    ⚠️ partial    3      2        0        1      612        5.1s  [details]
```
Click partial/failed row → modal with `error_detail`.

---

## 6. Delta Sync Logic

Every tick (every 15 min), aligned to optimizer schedule:

```
1. Check opt_sync_errors WHERE retried=false → retry those first
2. cursor = MAX(run_at) FROM opt_runs  (null if DB empty)
3. Query SF: WHERE CreatedDate >= cursor ORDER BY CreatedDate ASC LIMIT 50
4. For each run:
   a. Already in opt_runs by Id? → skip (idempotent)
   b. Download request JSON (1.1MB) from ContentDocumentLink
   c. Download response JSON (30KB) from ContentDocumentLink
   d. Parse → extract resources, work rules, SA decisions, driver verdicts
   e. INSERT INTO opt_runs, opt_sa_decisions, opt_driver_verdicts ON CONFLICT DO NOTHING
   f. Update opt_sync_cursor
   g. On failure: log to opt_sync_errors, continue to next run
5. Purge rows > 30 days
6. Write row to opt_sync_audit (SQLite)
```

**Delta guarantee:** cursor = `MAX(run_at)` means only runs not yet in DB are fetched. `ON CONFLICT DO NOTHING` ensures no duplicates even if cursor overlaps. Re-running sync N times produces identical state.

---

## 7. Driver Eligibility Reconstruction

The optimizer does not expose candidate ranking. We reconstruct eligibility from the request JSON:

| Exclusion reason | Source in request JSON |
|---|---|
| `territory` | Driver's `ServiceTerritories` doesn't include SA's `ServiceTerritoryId` |
| `skill` | `WorkOrderLineItems[sa].SkillRequirements` not met by `Resources[driver].ServiceResourceSkills` |
| `absent` | Driver Id appears in `NonAvailabilities` during SA's time window |
| `capacity` | Driver's existing `Services[].ServiceResources` fills their shift window |

Winner = driver in `assignedResourcesToUpsert` for this SA in response JSON.
Eligible = passed all 4 checks, not the winner.
Excluded = failed at least one check.

Travel time for winner = `EstimatedTravelTime` from response `assignedResourcesToUpsert` (exact — from SF optimizer).  
Travel time for eligible non-winners = estimated from `FSL__EstimatedTravelDistanceTo__c` ÷ org travel speed (25 mph mean). Displayed with "~" prefix in UI to indicate it is inferred, not optimizer-computed.

---

## 8. AI System — The Brain

### 8.1 Domain Grounding (system prompt)

The AI is pre-loaded with FSL dispatch knowledge:
- Fleet vs Towbook channels (optimizer only touches Fleet — `ERS_Dispatch_Method__c = 'Field Services'`)
- The 14 work rules and what each means
- The 2 objectives and their weights (travel-heavy "Closest Driver" policy — reverse-engineered from 349 real SAs)
- What "Unscheduled — Failed to reschedule a rule violating task" means in plain English
- The 5 scheduling policies in this org and when each applies
- FSL__Pinned__c, TimeDependencies, ERS_Dynamic_Priority__c semantics
- The 15-min optimizer cadence, 3 territories optimized simultaneously
- Why Towbook SAs are never in the optimizer scope
- How travel time becomes the primary tiebreaker in the Closest Driver policy

### 8.2 Tool Layer

Pre-built tools (cover 90% of questions):

| Tool | Parameters | Returns |
|---|---|---|
| `list_runs` | `from_dt, to_dt, territory` | Run timeline for time window |
| `get_run_detail` | `run_id` | Full run: KPIs, all SA decisions |
| `get_sa_decision` | `sa_number` | Decision tree: winner, eligible, excluded drivers |
| `get_driver_analysis` | `driver_name, days` | Runs in scope, assigned vs excluded, patterns |
| `get_unscheduled_analysis` | `run_id` | All failed SAs + reasons for a run |
| `get_exclusion_patterns` | `territory, days` | Aggregate exclusion reasons over time |

Read-only SQL escape hatch (novel pattern questions):
```python
def query_optimizer(sql: str) -> list[dict]:
    # Validates: SELECT only, no DDL/DML, no ATTACH
    # Executes against DuckDB read-only connection
    # Returns up to 500 rows
```

### 8.3 Rich Response Format

AI responses include structured visualization hints the frontend renders inline:

```json
{
  "text": "076DO was in scope but at capacity — 3 active SAs filled their shift window...",
  "visualization": {
    "type": "decision_tree",   
    "data": { "sa": {...}, "winner": {...}, "eligible": [...], "excluded": [...] }
  }
}
```

Visualization types:
| Question type | Rendered component |
|---|---|
| "Why didn't X get SA Y?" | `OptDecisionTree` — React Flow funnel |
| "Show me this run's outcome" | `OptKpiBar` — before/after KPI bars |
| "Which drivers excluded most?" | `OptDriverChart` — horizontal bar (Recharts) |
| "Show 076DO's pattern this week" | `OptDriverTimeline` — line chart (Recharts) |
| "What patterns do you see?" | `OptPatternCards` — 3 finding cards with supporting charts |

---

## 9. UI Layout

```
┌─────────────────────────────────────────────────────────────┐
│  OPTIMIZER DECODER          [Territory ▾] [Date range ▾] [🔄]│
├───────────────┬─────────────────────────────────────────────┤
│               │                                             │
│  RUN TIMELINE │   CHAT                                      │
│               │                                             │
│  Apr 28       │   AI: I can see 87 optimization runs        │
│  ● 01:45 WNY  │   in the last 24h. 4 runs had unscheduled  │
│  ● 01:45 076  │   SAs. What would you like to investigate?  │
│  ● 01:45 089  │                                             │
│  ● 01:30 WNY  │   ┌─────────────────────────────────────┐  │
│  ● 01:30 076  │   │  [DECISION TREE — SA-04799070]      │  │
│  ● 01:30 089  │   │  54 drivers → 8 eligible → winner   │  │
│  ...          │   └─────────────────────────────────────┘  │
│               │                                             │
│  ⚠️ = partial  │   You: Why wasn't 076DO picked?            │
│  ✅ = success  │                                             │
│               │   _______________________________ [Send ↵]  │
└───────────────┴─────────────────────────────────────────────┘
```

### Three entry points (all via chat)

Dispatcher types naturally — AI routes to the right tool:
- **SA-first:** "What happened to SA-04799070?" → `get_sa_decision`
- **Driver-first:** "Show me 076DO in today's runs" → `get_driver_analysis`
- **Unscheduled-first:** "Which SAs failed in the 1:45am run?" → `get_unscheduled_analysis`

Clicking a run in the timeline injects context: "Now looking at run OR-2026-04-127674 (Apr 28 01:45, WNY Fleet)."

---

## 10. Decision Tree Visualization (React Flow)

The core visual. Rendered inline in chat when AI calls a decision-related tool.

**Node hierarchy:**
```
[SA card — number, work type, location]
         │
[All N drivers in scope]
         │
    ┌────┴────────────────────┐
    │                         │
[EXCLUDED]              [ELIGIBLE — sorted by travel time]
    │                         │
┌───┴──────────┐         ┌────┴────────────────┐
│ Territory(N) │         │ Driver A — 8min ✅  │
│ Skill(N)     │         │ Driver B — 12min    │
│ Absent(N)    │         │ Driver C — 15min    │
│ Capacity(N)  │         └─────────────────────┘
└──────────────┘
```

- **Click excluded category** → expands to show individual driver names + specific reason
- **Hover any node** → tooltip (driver details, travel distance, rule that fired)
- **Click eligible driver** → tooltip shows "Would have been assigned if winner unavailable"
- Framer Motion handles expand/collapse transitions
- `@floating-ui/react` for viewport-safe tooltips

---

## 11. New Files

### Backend
| File | Purpose |
|---|---|
| `optimizer_db.py` | DuckDB init, schema, connection, query helpers |
| `optimizer_sync.py` | Delta sync job: SF → parse → DuckDB. Runs on scheduler. |
| `optimizer_init.py` | CLI script: one-time backfill. Args: `--days 30` |
| `routers/optimizer.py` | REST endpoints: runs, SA decisions, driver analysis |
| `routers/optimizer_chat.py` | Chat endpoint: domain system prompt + tool calling |

### Frontend
| File | Purpose |
|---|---|
| `pages/OptimizerDecoder.jsx` | Main page — layout, timeline + chat |
| `components/OptimizerTimeline.jsx` | Left panel: scrollable run list |
| `components/OptimizerChat.jsx` | Chat interface with inline visualization rendering |
| `components/OptDecisionTree.jsx` | React Flow decision tree — SA → filters → winner |
| `components/OptKpiBar.jsx` | Before/after KPI comparison bars (Recharts) |
| `components/OptDriverChart.jsx` | Driver exclusion/pattern charts (Recharts) |

### New dependencies
```bash
npm install @xyflow/react          # decision tree visualization
npm install @floating-ui/react     # viewport-safe tooltips
pip install duckdb                 # backend DuckDB driver
```

---

## 12. Out of Scope (v1)

- Towbook runs (optimizer only touches Fleet — Towbook is out-of-domain by definition)
- Editing or suggesting policy changes from the UI (read-only analysis only)
- Real-time websocket updates (15-min sync cadence is sufficient)
- MotherDuck or shared remote DuckDB (revisit if team grows)
- Exporting decision trees as PDF/image
