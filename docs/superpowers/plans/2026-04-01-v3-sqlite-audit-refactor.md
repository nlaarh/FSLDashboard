# v3.0 — SQLite Migration, Code Audit & Refactor

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace JSON file cache + settings with SQLite, enforce 600-line file limit, eliminate code duplication, and make the app clean, lean, and fast.

**Architecture:** SQLite at `/home/fslapp/fslapp.db` (Azure) or `~/.fslapp/fslapp.db` (local) replaces both `~/.fslapp/settings.json` and `~/.fslapp/cache/v*/` JSON files. Two tables: `settings` (key-value config) and `cache` (persistent cache with TTL). All existing `cache.py` consumers updated to use SQLite backend. Backend files split to ≤600 lines. Shared utilities extracted for batch SOQL, settings loading, and satisfaction calculation.

**Tech Stack:** Python 3.10+, SQLite3 (stdlib), FastAPI, React 18, Vite

---

## Phase 1: SQLite Foundation

### Task 1: Create SQLite database module

**Files:**
- Create: `backend/database.py`
- Modify: `backend/main.py` (init DB on startup)

**Schema:**
```sql
-- Settings: key-value config (replaces settings.json)
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,        -- JSON-encoded value
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Cache: persistent cache (replaces disk JSON files)
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    data TEXT NOT NULL,         -- JSON-encoded response
    expires_at REAL NOT NULL,   -- Unix timestamp
    created_at TEXT DEFAULT (datetime('now'))
);

-- Bonus tiers: configurable contractor bonus rules
CREATE TABLE IF NOT EXISTS bonus_tiers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    min_pct REAL NOT NULL,      -- e.g. 92.0
    bonus_per_sa REAL NOT NULL, -- e.g. 1.00
    label TEXT,                 -- e.g. '≥92%'
    sort_order INTEGER DEFAULT 0
);
```

- [ ] Step 1: Create `backend/database.py` with init, get/put settings, get/put cache, bonus tier CRUD
- [ ] Step 2: Add default bonus tiers on first init (98/$4, 96/$3, 94/$2, 92/$1)
- [ ] Step 3: Add DB init call to `backend/main.py` startup
- [ ] Step 4: Verify DB file created at correct path (Azure vs local)
- [ ] Step 5: Commit

### Task 2: Migrate cache.py to SQLite backend

**Files:**
- Modify: `backend/cache.py`
- Remove: `~/.fslapp/cache/v*/` directory logic

**Key changes:**
- `put()` / `get()` → L1 stays in-memory dict (fast), L2 writes to SQLite `cache` table
- `disk_put()` / `disk_get()` → replaced by SQLite reads/writes
- `cached_query_persistent()` → writes to both L1 + SQLite
- Cleanup: `DELETE FROM cache WHERE expires_at < ?` on startup
- Keep `CACHE_VERSION` concept — prefix all keys with version

- [ ] Step 1: Update `cache.py` L2 layer to use `database.py` instead of JSON files
- [ ] Step 2: Remove disk JSON file functions (disk_put, disk_get, disk_invalidate, disk_get_stale)
- [ ] Step 3: Update `cached_query_persistent()` to write to SQLite
- [ ] Step 4: Add startup cleanup (expired rows)
- [ ] Step 5: Update `stats()` to query SQLite counts
- [ ] Step 6: Verify all 88 endpoints still work with new cache backend
- [ ] Step 7: Commit

### Task 3: Migrate settings.json to SQLite

**Files:**
- Modify: `backend/routers/admin.py` (read/write from SQLite)
- Modify: `backend/routers/chatbot.py` (read settings from SQLite)
- Modify: `backend/routers/garages_scorecard.py` (read AI settings from SQLite)
- Remove: `_load_settings()` duplicates in admin.py and chatbot.py
- Create: `backend/settings_service.py` (shared settings access)

- [ ] Step 1: Create `backend/settings_service.py` with `get_setting(key)`, `put_setting(key, value)`, `get_ai_config()`
- [ ] Step 2: Migrate Admin page read/write to use `settings_service.py`
- [ ] Step 3: Migrate chatbot.py to use `settings_service.py`
- [ ] Step 4: Migrate garages_scorecard.py `_load_ai_settings()` to use `settings_service.py`
- [ ] Step 5: Add migration: on first startup, read `settings.json` if exists → insert into SQLite → rename to `.json.bak`
- [ ] Step 6: Commit

### Task 4: Make bonus tiers configurable in Admin

**Files:**
- Modify: `backend/routers/admin.py` (add bonus tier endpoints)
- Modify: `backend/routers/garages_scorecard.py` (read tiers from DB)
- Modify: `frontend/src/pages/Admin.jsx` (add bonus tier UI section)
- Modify: `frontend/src/components/GaragePerformance.jsx` (read tiers from scorecard response)

- [ ] Step 1: Add `GET /api/admin/bonus-tiers` and `PUT /api/admin/bonus-tiers` endpoints
- [ ] Step 2: Update `_bonus_for_pct()` in garages_scorecard.py to read tiers from DB
- [ ] Step 3: Include `bonus_tiers` in scorecard response so frontend knows current config
- [ ] Step 4: Add Bonus Tiers section to Admin page (table editor)
- [ ] Step 5: Commit

### Task 5: Add refresh/recalculate to all cached views

**Files:**
- Modify: `backend/cache.py` (add `invalidate_by_prefix()` using SQLite DELETE)
- Modify: `backend/routers/admin.py` (cache management endpoints)
- Modify: Frontend components with refresh button (already on GarageDashboard, add to others)

- [ ] Step 1: Add `DELETE FROM cache WHERE key LIKE ?` to cache.py
- [ ] Step 2: Ensure refresh icon on GarageDashboard sends `?bust=timestamp` to bypass L1
- [ ] Step 3: Add refresh capability to SatisfactionView, TrendsView, CommandCenter
- [ ] Step 4: Admin page: show cache table stats, "Clear All" and "Clear by prefix" buttons
- [ ] Step 5: Commit

---

## Phase 2: Backend Code Audit & Refactor (≤600 lines per file)

### Task 6: Extract shared SOQL batch utility

**Files:**
- Create: `backend/sf_batch.py`
- Modify: `backend/routers/dispatch_drill.py` (replace inline batching)
- Modify: `backend/routers/dispatch_satisfaction.py` (replace inline batching)
- Modify: `backend/routers/garages_scorecard.py` (replace inline batching)
- Modify: `backend/routers/tracking.py` (replace inline batching)

```python
# backend/sf_batch.py
def batch_query(template: str, ids: list, chunk_size: int = 200) -> list:
    """Run SOQL IN-clause query in parallel chunks. Returns combined results."""
```

- [ ] Step 1: Create `sf_batch.py` with `batch_query()` and `batch_query_parallel()`
- [ ] Step 2: Replace 6 inline batch patterns across 5 files
- [ ] Step 3: Verify all affected endpoints return same data
- [ ] Step 4: Commit

### Task 7: Split dispatch_satisfaction.py (1,336 → 3 files)

**Files:**
- Keep: `backend/routers/dispatch_satisfaction.py` (~400 lines: overview endpoint + monthly generation)
- Create: `backend/routers/satisfaction_garage.py` (~400 lines: garage detail + day analysis)
- Create: `backend/routers/satisfaction_utils.py` (~200 lines: shared insights, executive briefing, zone mapping)

- [ ] Step 1: Extract `_satisfaction_insights()`, `_build_executive_insight()`, `_build_zone_satisfaction()`, `_is_real_garage()` → `satisfaction_utils.py`
- [ ] Step 2: Extract `api_satisfaction_garage()`, `api_satisfaction_day()`, `SatisfactionDayAnalysis` → `satisfaction_garage.py`
- [ ] Step 3: Register new router in `main.py`
- [ ] Step 4: Verify all 5 satisfaction endpoints work
- [ ] Step 5: Commit

### Task 8: Split chatbot.py (1,099 → 3 files)

**Files:**
- Keep: `backend/routers/chatbot.py` (~350 lines: main chat endpoint, router)
- Create: `backend/routers/chatbot_context.py` (~350 lines: context classification, data fetching)
- Create: `backend/routers/chatbot_providers.py` (~200 lines: OpenAI, Anthropic, Google API calls)

- [ ] Step 1: Extract `_call_openai()`, `_call_anthropic()`, `_call_google()` → `chatbot_providers.py`
- [ ] Step 2: Extract context classification and data preparation → `chatbot_context.py`
- [ ] Step 3: Update imports in chatbot.py
- [ ] Step 4: Verify chat endpoint works with all providers
- [ ] Step 5: Commit

### Task 9: Split dispatch.py (1,034 → 2 files)

**Files:**
- Keep: `backend/dispatch.py` (~500 lines: queue, cascade, core dispatch logic)
- Create: `backend/dispatch_decomposition.py` (~500 lines: response decomposition, driver leaderboard)

- [ ] Step 1: Extract `get_response_decomposition()` and supporting functions → `dispatch_decomposition.py`
- [ ] Step 2: Update imports in garages.py (calls decomposition)
- [ ] Step 3: Verify decomposition endpoints work
- [ ] Step 4: Commit

### Task 10: Split remaining backend files over 600 lines

**Files to split:**
- `dispatch_drill.py` (958) → extract detail endpoints into `dispatch_drill_detail.py`
- `garages_scorecard.py` (957) → extract export/email into `garages_export.py`
- `insights.py` (912) → extract health checks into `insights_health.py`
- `garages.py` (867) → extract score/decomposition routes into separate file
- `dispatch_trends.py` (867) → extract per-month into `dispatch_trends_monthly.py`
- `misc.py` (818) → extract diagnostics into `misc_diagnostics.py`
- `sa_report.py` (808) → extract timeline building into `sa_report_timeline.py`
- `db.py` (777) → extract analytics into `db_analytics.py`
- `command_center.py` (674) → extract helper functions

- [ ] Step 1-9: Split each file, register new routers in main.py
- [ ] Step 10: Verify all 88 endpoints work after splits
- [ ] Step 11: Commit

---

## Phase 3: Frontend Code Audit & Refactor (≤600 lines per file)

### Task 11: Split Help.jsx (2,472 → 4 files)

**Files:**
- Keep: `frontend/src/pages/Help.jsx` (~300 lines: navigation, layout)
- Create: `frontend/src/components/HelpFAQ.jsx` (~500 lines: FAQ content)
- Create: `frontend/src/components/HelpGuides.jsx` (~500 lines: feature guides)
- Create: `frontend/src/components/HelpChatbot.jsx` (~400 lines: chatbot integration)

- [ ] Step 1-4: Extract components, update imports
- [ ] Step 5: Verify Help page renders correctly
- [ ] Step 6: Commit

### Task 12: Split DispatchInsights.jsx (1,172 → 3 files)

- Keep: `DispatchInsights.jsx` (~400 lines: main layout, tabs)
- Create: `DispatchInsightCards.jsx` (~400 lines: metric cards, trend summaries)
- Create: `DispatchDrillDowns.jsx` (~400 lines: drill-down detail views)

- [ ] Step 1-3: Extract, update imports
- [ ] Step 4: Commit

### Task 13: Split CommandCenter.jsx (1,109 → 3 files)

- Keep: `CommandCenter.jsx` (~400 lines: layout, tab switching)
- Create: `CommandCenterCards.jsx` (~350 lines: territory cards, metrics)
- Create: `useCommandCenterData.js` (~300 lines: shared data hook)

- [ ] Step 1-3: Extract, update imports
- [ ] Step 4: Commit

### Task 14: Split remaining frontend files over 600 lines

**Files to split (8 files):**
- `SatisfactionView.jsx` (947) → extract day/garage detail into separate components
- `GarageDashboard.jsx` (928) → extract Operations tab into `GarageOperations.jsx`
- `MapView.jsx` (922) → extract layer controls, legend into components
- `Admin.jsx` (894) → extract each admin section into separate components
- `Performance.jsx` (854) → extract chart components
- `DataDictionary.jsx` (777) → extract table into separate component
- `PtaAdvisor.jsx` (757) → extract detail views
- `SAReportModal.jsx` (682) → extract timeline into component

- [ ] Step 1-8: Split each file
- [ ] Step 9: Build frontend, verify all pages render
- [ ] Step 10: Commit

---

## Phase 4: Deduplication & Cleanup

### Task 15: Extract shared utilities

- [ ] Step 1: Move `_totally_satisfied_pct()` from garages_scorecard.py → `backend/utils.py`
- [ ] Step 2: Create `backend/settings_service.py` (consolidate 3 copies of settings loading)
- [ ] Step 3: Move HTML report template to shared `backend/report_html.py` (used by scorecard email + export)
- [ ] Step 4: Remove dead imports, unused variables across all files
- [ ] Step 5: Commit

### Task 16: Final validation

- [ ] Step 1: Run Python syntax check on ALL backend files
- [ ] Step 2: Build frontend (vite build) — verify zero errors
- [ ] Step 3: Start server, hit every major endpoint with curl
- [ ] Step 4: Line count audit — verify every file ≤ 600 lines
- [ ] Step 5: Tag as `v3.0`
- [ ] Step 6: Commit (do NOT push — wait for user approval)

---

## File Count Summary

**Before:**
- Backend: 12 files over 600 lines (3 over 1000)
- Frontend: 13 files over 600 lines (3 over 900)
- Duplicate patterns: 6 batch SOQL, 3 settings loaders, scattered cache patterns

**After:**
- Backend: 0 files over 600 lines (~15 new focused files)
- Frontend: 0 files over 600 lines (~12 new focused components)
- Shared utilities: sf_batch.py, settings_service.py, report_html.py, database.py
- SQLite: single DB file for settings + cache + bonus config
- Cache: unified L1 (memory) + L2 (SQLite) with version-prefixed keys
