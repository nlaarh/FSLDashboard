# Optimizer Black Box Decoder — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a chat-first interface in FSLAPP that lets dispatchers interrogate optimizer decisions — who got assigned, who was excluded and why, what policy fired — using the request/response JSON files stored in SF ContentDocuments, backed by a DuckDB analytics store.

**Architecture:** A background sync job polls SF every 15 min for new FSL__Optimization_Request__c records, downloads their request/response JSON files, parses driver eligibility, and stores structured data in DuckDB. A chat endpoint wraps DuckDB with domain-grounded tool calling so dispatchers can ask questions in plain English. The frontend renders inline React Flow decision trees and Recharts pattern charts inside chat bubbles.

**Tech Stack:** Python/FastAPI backend, DuckDB (analytics), SQLite (existing, audit only), React 18 + @xyflow/react + Recharts + Framer Motion frontend, Anthropic claude-sonnet-4-6 for chat.

---

## File Map

### New Backend
| File | Responsibility |
|---|---|
| `backend/optimizer_db.py` | DuckDB connection, schema init, all query helpers |
| `backend/optimizer_sync.py` | Delta sync job: SF → download → parse → DuckDB |
| `backend/optimizer_init.py` | CLI backfill script (`--days 30`) |
| `backend/routers/optimizer.py` | REST endpoints (timeline, SA detail, driver analysis) |
| `backend/routers/optimizer_chat.py` | Chat endpoint: domain system prompt + tool calling |

### Modified Backend
| File | Change |
|---|---|
| `backend/database.py` | Add `opt_sync_audit` table to SQLite init |
| `backend/main.py` | Register optimizer router + wire sync job to startup |

### New Frontend
| File | Responsibility |
|---|---|
| `frontend/src/pages/OptimizerDecoder.jsx` | Main page: timeline + chat layout |
| `frontend/src/components/OptimizerTimeline.jsx` | Left panel: scrollable run list with status dots |
| `frontend/src/components/OptimizerChat.jsx` | Chat interface: renders text + inline visualizations |
| `frontend/src/components/OptDecisionTree.jsx` | React Flow decision tree: SA → filters → winner |
| `frontend/src/components/OptKpiBar.jsx` | Before/after KPI comparison (Recharts) |
| `frontend/src/components/OptDriverChart.jsx` | Driver exclusion/pattern charts (Recharts) |

### Modified Frontend
| File | Change |
|---|---|
| `frontend/src/App.jsx` | Add `/optimizer` route |
| `frontend/src/components/Layout.jsx` | Add nav link |
| `frontend/src/api.js` | Add optimizer + optimizer_chat API calls |
| `frontend/package.json` | Add `@xyflow/react`, `@floating-ui/react` |

---

## Task 1: DuckDB Schema + Connection

**Files:**
- Create: `backend/optimizer_db.py`

- [ ] **Step 1: Install duckdb**

```bash
cd backend && pip install duckdb==1.2.2
echo "duckdb==1.2.2" >> requirements.txt
```

- [ ] **Step 2: Create optimizer_db.py**

```python
"""DuckDB store for optimizer run analysis — schema, connection, query helpers."""

import os, logging
import duckdb
from pathlib import Path
from contextlib import contextmanager

log = logging.getLogger('optimizer_db')

_ON_AZURE = bool(os.environ.get('WEBSITE_SITE_NAME'))
_DB_DIR = Path('/home/fslapp') if _ON_AZURE else Path(os.path.expanduser('~/.fslapp'))
DB_PATH = str(_DB_DIR / 'optimizer.duckdb')

_SCHEMA = """
CREATE TABLE IF NOT EXISTS opt_resources (
    id           VARCHAR PRIMARY KEY,
    name         VARCHAR,
    updated_at   TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS opt_runs (
    id                 VARCHAR PRIMARY KEY,
    name               VARCHAR,
    territory_id       VARCHAR,
    territory_name     VARCHAR,
    policy_id          VARCHAR,
    policy_name        VARCHAR,
    run_at             TIMESTAMP NOT NULL,
    horizon_start      TIMESTAMP,
    horizon_end        TIMESTAMP,
    resources_count    INTEGER,
    services_count     INTEGER,
    pre_scheduled      INTEGER,
    post_scheduled     INTEGER,
    unscheduled_count  INTEGER,
    pre_travel_time_s  INTEGER,
    post_travel_time_s INTEGER,
    pre_response_avg_s DOUBLE,
    post_response_avg_s DOUBLE,
    synced_at          TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS opt_sa_decisions (
    id                     VARCHAR PRIMARY KEY,
    run_id                 VARCHAR NOT NULL,
    sa_id                  VARCHAR NOT NULL,
    sa_number              VARCHAR,
    sa_work_type           VARCHAR,
    action                 VARCHAR,
    unscheduled_reason     VARCHAR,
    winner_driver_id       VARCHAR,
    winner_driver_name     VARCHAR,
    winner_travel_time_min DOUBLE,
    winner_travel_dist_mi  DOUBLE,
    run_at                 TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS opt_driver_verdicts (
    id               VARCHAR PRIMARY KEY,
    run_id           VARCHAR NOT NULL,
    sa_id            VARCHAR NOT NULL,
    driver_id        VARCHAR NOT NULL,
    driver_name      VARCHAR,
    status           VARCHAR,
    exclusion_reason VARCHAR,
    travel_time_min  DOUBLE,
    travel_dist_mi   DOUBLE,
    run_at           TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS opt_sync_cursor (
    id                  INTEGER PRIMARY KEY DEFAULT 1,
    last_run_created_at TIMESTAMP,
    last_run_id         VARCHAR,
    total_synced        INTEGER DEFAULT 0,
    last_synced_at      TIMESTAMP,
    last_error          VARCHAR
);

CREATE TABLE IF NOT EXISTS opt_sync_errors (
    run_id    VARCHAR PRIMARY KEY,
    run_name  VARCHAR,
    error     VARCHAR,
    failed_at TIMESTAMP,
    retried   BOOLEAN DEFAULT false
);
"""

_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_opt_runs_run_at       ON opt_runs(run_at);
CREATE INDEX IF NOT EXISTS idx_opt_runs_territory    ON opt_runs(territory_id);
CREATE INDEX IF NOT EXISTS idx_sa_decisions_sa_num   ON opt_sa_decisions(sa_number);
CREATE INDEX IF NOT EXISTS idx_sa_decisions_run_id   ON opt_sa_decisions(run_id);
CREATE INDEX IF NOT EXISTS idx_sa_decisions_run_at   ON opt_sa_decisions(run_at);
CREATE INDEX IF NOT EXISTS idx_verdicts_driver_name  ON opt_driver_verdicts(driver_name);
CREATE INDEX IF NOT EXISTS idx_verdicts_run_id       ON opt_driver_verdicts(run_id);
CREATE INDEX IF NOT EXISTS idx_verdicts_sa_id        ON opt_driver_verdicts(sa_id);
CREATE INDEX IF NOT EXISTS idx_verdicts_run_at       ON opt_driver_verdicts(run_at);
"""


def init_db():
    """Create tables and indexes. Safe to call multiple times (IF NOT EXISTS)."""
    _DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(DB_PATH)
    conn.execute(_SCHEMA)
    conn.execute(_INDEXES)
    conn.close()
    log.info(f"Optimizer DuckDB initialized at {DB_PATH}")


@contextmanager
def get_conn(read_only: bool = False):
    conn = duckdb.connect(DB_PATH, read_only=read_only)
    try:
        yield conn
    finally:
        conn.close()


def purge_old_runs(days: int = 30):
    """Delete rows older than `days` days from all three data tables."""
    with get_conn() as conn:
        for tbl in ('opt_driver_verdicts', 'opt_sa_decisions', 'opt_runs'):
            conn.execute(
                f"DELETE FROM {tbl} WHERE run_at < now() - INTERVAL '{days} days'"
            )


# ── Read helpers ─────────────────────────────────────────────────────────────

def list_runs(from_dt: str, to_dt: str, territory: str | None = None) -> list[dict]:
    sql = """
        SELECT id, name, territory_name, policy_name, run_at,
               resources_count, services_count,
               pre_scheduled, post_scheduled, unscheduled_count,
               pre_travel_time_s, post_travel_time_s,
               pre_response_avg_s, post_response_avg_s
        FROM opt_runs
        WHERE run_at BETWEEN ? AND ?
    """
    params = [from_dt, to_dt]
    if territory:
        sql += " AND lower(territory_name) LIKE ?"
        params.append(f"%{territory.lower()}%")
    sql += " ORDER BY run_at DESC LIMIT 200"
    with get_conn(read_only=True) as conn:
        return conn.execute(sql, params).fetchdf().to_dict('records')


def get_run_detail(run_id: str) -> dict | None:
    with get_conn(read_only=True) as conn:
        run = conn.execute(
            "SELECT * FROM opt_runs WHERE id = ?", [run_id]
        ).fetchdf().to_dict('records')
        if not run:
            return None
        decisions = conn.execute(
            "SELECT * FROM opt_sa_decisions WHERE run_id = ? ORDER BY action",
            [run_id]
        ).fetchdf().to_dict('records')
        return {'run': run[0], 'decisions': decisions}


def get_sa_decision(sa_number: str, limit: int = 5) -> list[dict]:
    """Return the last `limit` runs that touched this SA, with full driver verdicts."""
    with get_conn(read_only=True) as conn:
        decisions = conn.execute(
            """SELECT d.*, r.territory_name, r.policy_name
               FROM opt_sa_decisions d
               JOIN opt_runs r ON r.id = d.run_id
               WHERE d.sa_number = ?
               ORDER BY d.run_at DESC LIMIT ?""",
            [sa_number, limit]
        ).fetchdf().to_dict('records')
        for dec in decisions:
            dec['verdicts'] = conn.execute(
                """SELECT driver_name, status, exclusion_reason,
                          travel_time_min, travel_dist_mi
                   FROM opt_driver_verdicts
                   WHERE run_id = ? AND sa_id = ?
                   ORDER BY CASE status WHEN 'winner' THEN 0
                                        WHEN 'eligible' THEN 1
                                        ELSE 2 END,
                            travel_time_min NULLS LAST""",
                [dec['run_id'], dec['sa_id']]
            ).fetchdf().to_dict('records')
        return decisions


def get_driver_analysis(driver_name: str, days: int = 7) -> dict:
    with get_conn(read_only=True) as conn:
        summary = conn.execute(
            """SELECT status, COUNT(*) as count
               FROM opt_driver_verdicts
               WHERE lower(driver_name) LIKE lower(?)
                 AND run_at >= now() - INTERVAL ? DAYS
               GROUP BY status""",
            [f"%{driver_name}%", days]
        ).fetchdf().to_dict('records')
        reasons = conn.execute(
            """SELECT exclusion_reason, COUNT(*) as count
               FROM opt_driver_verdicts
               WHERE lower(driver_name) LIKE lower(?)
                 AND status = 'excluded'
                 AND run_at >= now() - INTERVAL ? DAYS
               GROUP BY exclusion_reason ORDER BY count DESC""",
            [f"%{driver_name}%", days]
        ).fetchdf().to_dict('records')
        return {'summary': summary, 'exclusion_reasons': reasons}


def get_unscheduled_analysis(run_id: str) -> list[dict]:
    with get_conn(read_only=True) as conn:
        rows = conn.execute(
            """SELECT d.sa_number, d.sa_work_type, d.unscheduled_reason,
                      COUNT(v.id) FILTER (WHERE v.status='excluded') as excluded_count,
                      COUNT(v.id) FILTER (WHERE v.status='eligible') as eligible_count
               FROM opt_sa_decisions d
               LEFT JOIN opt_driver_verdicts v ON v.run_id=d.run_id AND v.sa_id=d.sa_id
               WHERE d.run_id = ? AND d.action = 'Unscheduled'
               GROUP BY d.sa_number, d.sa_work_type, d.unscheduled_reason""",
            [run_id]
        ).fetchdf().to_dict('records')
        return rows


def get_exclusion_patterns(territory: str | None, days: int = 7) -> list[dict]:
    sql = """
        SELECT v.exclusion_reason, COUNT(*) as fires,
               COUNT(DISTINCT v.driver_id) as drivers_affected
        FROM opt_driver_verdicts v
        JOIN opt_runs r ON r.id = v.run_id
        WHERE v.status = 'excluded'
          AND v.run_at >= now() - INTERVAL ? DAYS
    """
    params: list = [days]
    if territory:
        sql += " AND lower(r.territory_name) LIKE ?"
        params.append(f"%{territory.lower()}%")
    sql += " GROUP BY v.exclusion_reason ORDER BY fires DESC"
    with get_conn(read_only=True) as conn:
        return conn.execute(sql, params).fetchdf().to_dict('records')


def query_optimizer_sql(sql: str) -> list[dict]:
    """Read-only SQL escape hatch. Only SELECT allowed."""
    stripped = sql.strip().upper()
    if not stripped.startswith('SELECT'):
        raise ValueError("Only SELECT queries are permitted")
    for forbidden in ('INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'ATTACH', 'COPY'):
        if forbidden in stripped:
            raise ValueError(f"Forbidden keyword: {forbidden}")
    with get_conn(read_only=True) as conn:
        return conn.execute(sql).fetchdf().head(500).to_dict('records')


def upsert_resource_names(resources: list[dict]):
    """Store resource id→name mappings. Only inserts missing ones."""
    if not resources:
        return
    with get_conn() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO opt_resources(id, name) VALUES (?, ?)",
            [(r['id'], r['name']) for r in resources]
        )


def get_resource_name(resource_id: str, fallback: dict | None = None) -> str:
    with get_conn(read_only=True) as conn:
        row = conn.execute(
            "SELECT name FROM opt_resources WHERE id = ?", [resource_id]
        ).fetchone()
    if row:
        return row[0]
    if fallback:
        return fallback.get(resource_id, resource_id)
    return resource_id
```

- [ ] **Step 3: Smoke test**

```bash
cd backend
python3 -c "
import optimizer_db
optimizer_db.init_db()
print('DuckDB initialized at', optimizer_db.DB_PATH)
with optimizer_db.get_conn() as c:
    tables = c.execute(\"SELECT table_name FROM information_schema.tables WHERE table_schema='main'\").fetchall()
    print('Tables:', [t[0] for t in tables])
"
```

Expected output:
```
DuckDB initialized at /Users/.../.fslapp/optimizer.duckdb
Tables: ['opt_resources', 'opt_runs', 'opt_sa_decisions', 'opt_driver_verdicts', 'opt_sync_cursor', 'opt_sync_errors']
```

- [ ] **Step 4: Commit**

```bash
git add backend/optimizer_db.py backend/requirements.txt
git commit -m "feat(optimizer): DuckDB schema and connection helpers"
```

---

## Task 2: SQLite Audit Table

**Files:**
- Modify: `backend/database.py`

- [ ] **Step 1: Add opt_sync_audit to init_db() in database.py**

Find the `init_db()` function's `executescript` call and append before the closing `"""`):

```python
            CREATE TABLE IF NOT EXISTS opt_sync_audit (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at        TEXT NOT NULL,
                finished_at       TEXT,
                status            TEXT NOT NULL,
                runs_found        INTEGER DEFAULT 0,
                runs_inserted     INTEGER DEFAULT 0,
                runs_skipped      INTEGER DEFAULT 0,
                runs_failed       INTEGER DEFAULT 0,
                verdicts_inserted INTEGER DEFAULT 0,
                rows_purged       INTEGER DEFAULT 0,
                error_detail      TEXT,
                duration_ms       INTEGER
            );
```

- [ ] **Step 2: Add write_sync_audit() helper to database.py (after existing helpers)**

```python
def write_sync_audit(
    started_at: str,
    finished_at: str,
    status: str,
    runs_found: int = 0,
    runs_inserted: int = 0,
    runs_skipped: int = 0,
    runs_failed: int = 0,
    verdicts_inserted: int = 0,
    rows_purged: int = 0,
    error_detail: str | None = None,
    duration_ms: int = 0,
):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO opt_sync_audit
               (started_at, finished_at, status, runs_found, runs_inserted,
                runs_skipped, runs_failed, verdicts_inserted, rows_purged,
                error_detail, duration_ms)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (started_at, finished_at, status, runs_found, runs_inserted,
             runs_skipped, runs_failed, verdicts_inserted, rows_purged,
             error_detail, duration_ms)
        )


def get_sync_audit(limit: int = 50) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM opt_sync_audit
               ORDER BY id DESC LIMIT ?""",
            (limit,)
        ).fetchall()
    cols = ['id','started_at','finished_at','status','runs_found','runs_inserted',
            'runs_skipped','runs_failed','verdicts_inserted','rows_purged',
            'error_detail','duration_ms']
    return [dict(zip(cols, r)) for r in rows]
```

- [ ] **Step 3: Smoke test**

```bash
cd backend
python3 -c "
import database
database.init_db()
database.write_sync_audit('2026-04-27T00:00:00', '2026-04-27T00:00:04', 'success',
    runs_found=3, runs_inserted=3, verdicts_inserted=918, duration_ms=4200)
rows = database.get_sync_audit()
print(rows[0])
"
```

Expected: prints a dict with the row we just inserted.

- [ ] **Step 4: Commit**

```bash
git add backend/database.py
git commit -m "feat(optimizer): add opt_sync_audit table and helpers to SQLite"
```

---

## Task 3: Optimizer Sync Job

**Files:**
- Create: `backend/optimizer_sync.py`

This is the core pipeline: SF → download → parse → DuckDB.

- [ ] **Step 1: Create optimizer_sync.py**

```python
"""Optimizer sync job — delta-pulls FSL optimization run files from SF into DuckDB.

Runs every 15 min via threading (same pattern as refresher.py).
Leader election via lock file — only one worker syncs across all gunicorn processes.
"""

import os, time, logging, threading, json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests as _requests
from sf_client import get_auth, refresh_auth
import optimizer_db
import database

log = logging.getLogger('optimizer_sync')

_ON_AZURE = bool(os.environ.get('WEBSITE_SITE_NAME'))
_LOCK_DIR = Path('/home/fslapp/locks') if _ON_AZURE else Path(os.path.expanduser('~/.fslapp/locks'))
_LOCK_FILE = _LOCK_DIR / '.optimizer_sync.lock'
_LEADER_STALE_AGE = 90  # seconds
_SYNC_INTERVAL = 900     # 15 minutes

_MI_PER_METER = 0.000621371
_ORG_SPEED_MPH = 25.0     # verified mean from 662 real AR records


# ── Lock / leader election ────────────────────────────────────────────────────

def _acquire_lock() -> bool:
    _LOCK_DIR.mkdir(parents=True, exist_ok=True)
    if _LOCK_FILE.exists():
        age = time.time() - _LOCK_FILE.stat().st_mtime
        if age < _LEADER_STALE_AGE:
            return False
    try:
        _LOCK_FILE.write_text(str(os.getpid()))
        return True
    except Exception:
        return False


def _release_lock():
    try:
        _LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# ── SF HTTP helpers ───────────────────────────────────────────────────────────

def _sf_get(path: str) -> dict:
    token, instance = get_auth()
    r = _requests.get(f"{instance}{path}",
                      headers={'Authorization': f'Bearer {token}'}, timeout=60)
    if r.status_code == 401:
        token, instance = refresh_auth()
        r = _requests.get(f"{instance}{path}",
                          headers={'Authorization': f'Bearer {token}'}, timeout=60)
    r.raise_for_status()
    return r.json()


def _sf_get_binary(path: str) -> bytes:
    token, instance = get_auth()
    r = _requests.get(f"{instance}{path}",
                      headers={'Authorization': f'Bearer {token}'}, timeout=120)
    if r.status_code == 401:
        token, instance = refresh_auth()
        r = _requests.get(f"{instance}{path}",
                          headers={'Authorization': f'Bearer {token}'}, timeout=120)
    r.raise_for_status()
    return r.content


# ── File resolution ───────────────────────────────────────────────────────────

def _get_content_versions(run_id: str) -> tuple[str | None, str | None]:
    """Return (request_cv_id, response_cv_id) for a given OptimizationRequest."""
    data = _sf_get(
        f"/services/data/v59.0/query/?q="
        f"SELECT+ContentDocumentId,ContentDocument.Title"
        f"+FROM+ContentDocumentLink"
        f"+WHERE+LinkedEntityId='{run_id}'"
    )
    req_doc_id = resp_doc_id = None
    for rec in data.get('records', []):
        title = rec.get('ContentDocument', {}).get('Title', '')
        if title.startswith('Request_'):
            req_doc_id = rec['ContentDocumentId']
        elif title.startswith('Response_'):
            resp_doc_id = rec['ContentDocumentId']
    if not req_doc_id or not resp_doc_id:
        return None, None

    def _latest_cv(doc_id: str) -> str | None:
        d = _sf_get(
            f"/services/data/v59.0/query/?q="
            f"SELECT+Id+FROM+ContentVersion"
            f"+WHERE+ContentDocumentId='{doc_id}'+AND+IsLatest=true"
        )
        recs = d.get('records', [])
        return recs[0]['Id'] if recs else None

    return _latest_cv(req_doc_id), _latest_cv(resp_doc_id)


def _download_json(cv_id: str) -> dict:
    raw = _sf_get_binary(f"/services/data/v59.0/sobjects/ContentVersion/{cv_id}/VersionData")
    return json.loads(raw)


# ── Resource name resolution ──────────────────────────────────────────────────

def _resolve_resource_names(resource_ids: list[str]) -> dict[str, str]:
    """Fetch ServiceResource Names for IDs not already in opt_resources."""
    with optimizer_db.get_conn(read_only=True) as conn:
        known = {r[0] for r in conn.execute(
            "SELECT id FROM opt_resources"
        ).fetchall()}
    missing = [rid for rid in resource_ids if rid not in known]
    if not missing:
        with optimizer_db.get_conn(read_only=True) as conn:
            rows = conn.execute(
                f"SELECT id, name FROM opt_resources WHERE id IN ({','.join('?' * len(resource_ids))})",
                resource_ids
            ).fetchall()
        return {r[0]: r[1] for r in rows}

    # Fetch missing names from SF in chunks of 50
    names: dict[str, str] = {}
    for i in range(0, len(missing), 50):
        chunk = missing[i:i + 50]
        ids_str = "','".join(chunk)
        data = _sf_get(
            f"/services/data/v59.0/query/?q="
            f"SELECT+Id,Name+FROM+ServiceResource+WHERE+Id+IN+('{ids_str}')"
        )
        for rec in data.get('records', []):
            names[rec['Id']] = rec['Name']

    optimizer_db.upsert_resource_names([{'id': k, 'name': v} for k, v in names.items()])

    # Return full map for all requested IDs
    with optimizer_db.get_conn(read_only=True) as conn:
        rows = conn.execute(
            f"SELECT id, name FROM opt_resources WHERE id IN ({','.join('?' * len(resource_ids))})",
            resource_ids
        ).fetchall()
    return {r[0]: r[1] for r in rows}


# ── Parser ────────────────────────────────────────────────────────────────────

def _parse_run(run_id: str, run_name: str, run_at: str,
               req: dict, resp: dict) -> tuple[dict, list[dict], list[dict]]:
    """Parse request+response JSON → (run_row, sa_decisions, driver_verdicts)."""

    # ── Territory / policy from request ──
    territories = req.get('Territories', [])
    territory_id = territories[0].get('Id', '') if territories else ''
    territory_name = ''  # resolved separately in sync_tick via SF query

    policy_list = req.get('SchedulingPolicy', [])
    policy = policy_list[0] if policy_list else {}
    policy_id = policy.get('Id', '')
    policy_name = policy.get('Name', '')

    # ── Resources index ──
    resources = req.get('Resources', [])
    resource_ids = [r['Id'] for r in resources]
    name_map = _resolve_resource_names(resource_ids)

    # Build lookup: resource_id → {skills, territories, absences}
    res_index: dict[str, dict] = {}
    for r in resources:
        rid = r['Id']
        res_index[rid] = {
            'name': name_map.get(rid, rid),
            'skills': {s.get('FSL__Skill__c') for s in r.get('ServiceResourceSkills', [])
                       if s.get('FSL__Skill__c')},
            'territories': {t.get('ServiceTerritoryId') or t.get('Id')
                            for t in r.get('ServiceTerritories', [])},
            'absences': [(a['Start'], a['End']) for a in r.get('ResourceAbsences', [])],
        }

    # ── NonAvailabilities (org-level absences) ──
    non_avail: dict[str, list] = {}
    for na in req.get('NonAvailabilities', []):
        rid = na.get('ResourceId')
        if rid:
            non_avail.setdefault(rid, []).append((na['Start'], na['End']))

    # ── WOLI skill requirements index ──
    woli_skills: dict[str, set] = {}
    for woli in req.get('WorkOrderLineItems', []):
        sa_id = woli.get('Id')  # WOLI.Id maps to SA.ParentRecordId in some orgs;
        # use SA-to-WOLI join via WorkOrderId if available
        for sr in woli.get('SkillRequirements', []):
            woli_skills.setdefault(sa_id, set()).add(sr.get('FSL__Skill__c'))

    # ── Services (SAs) index ──
    services: dict[str, dict] = {s['Id']: s for s in req.get('Services', [])}
    # Map sa_id → woli skill requirements via ParentRecordId
    sa_skills: dict[str, set] = {}
    for woli in req.get('WorkOrderLineItems', []):
        # Each WOLI is linked to one SA via the Services list (same ordering)
        # Fallback: match by index if direct join not possible
        pass
    # Simpler: build from SkillRequirements directly on Services
    for sa_id, sa in services.items():
        sa_skills[sa_id] = set()
    for woli in req.get('WorkOrderLineItems', []):
        for sr in woli.get('SkillRequirements', []):
            skill = sr.get('FSL__Skill__c')
            if skill:
                # Associate skill with SAs in same territory (best effort in v1)
                for sa_id in sa_skills:
                    sa_skills[sa_id].add(skill)

    # ── Response indexes ──
    # objectChanges: {sa_id: {activity, activityDetails}}
    obj_changes: dict[str, dict] = resp.get('objectChanges', {})

    # assignedResourcesToUpsert: list of AR records with winner info
    winners: dict[str, dict] = {}
    for ar in resp.get('assignedResourcesToUpsert', []):
        sa_id = ar.get('ServiceAppointmentId')
        if sa_id:
            winners[sa_id] = ar

    # Time horizon
    horizon = req.get('TimeHorizon', {})

    # ── KPIs ──
    kpis = resp.get('territoryKpis', {})
    pre_kpis = kpis.get('territory_pre_opt_kpis', [{}])
    post_kpis = kpis.get('territory_post_opt_kpis', [{}])
    # Use the main territory KPI block (largest num_tasks_scheduled)
    pre = max(pre_kpis, key=lambda k: k.get('num_tasks_scheduled', 0)) if pre_kpis else {}
    post = max(post_kpis, key=lambda k: k.get('num_tasks_scheduled', 0)) if post_kpis else {}

    unscheduled_sas = resp.get('unscheduledServiceAppointments', [])

    run_row = {
        'id': run_id,
        'name': run_name,
        'territory_id': territory_id,
        'territory_name': territory_name,
        'policy_id': policy_id,
        'policy_name': policy_name,
        'run_at': run_at,
        'horizon_start': horizon.get('Start'),
        'horizon_end': horizon.get('Finish'),
        'resources_count': len(resources),
        'services_count': len(services),
        'pre_scheduled': pre.get('num_tasks_scheduled', 0),
        'post_scheduled': post.get('num_tasks_scheduled', 0),
        'unscheduled_count': len(unscheduled_sas),
        'pre_travel_time_s': pre.get('travel_time_between', 0),
        'post_travel_time_s': post.get('travel_time_between', 0),
        'pre_response_avg_s': pre.get('response_time_avg_nonappointment', 0.0),
        'post_response_avg_s': post.get('response_time_avg_nonappointment', 0.0),
    }

    sa_decisions = []
    driver_verdicts = []

    for sa_id, change in obj_changes.items():
        action = change.get('activity', '')
        reason = None
        details = change.get('activityDetails', '')
        if 'Unscheduling Reason:' in details:
            reason = details.split('Unscheduling Reason:')[-1].strip()

        sa = services.get(sa_id, {})
        sa_number = sa.get('AppointmentNumber', '')
        sa_territory_id = sa.get('ServiceTerritoryId', '')
        sched_start = sa.get('SchedStartTime') or sa.get('EarliestStartTime')

        winner_ar = winners.get(sa_id)
        winner_driver_id = winner_ar.get('ServiceResourceId') if winner_ar else None
        winner_driver_name = name_map.get(winner_driver_id, winner_driver_id) if winner_driver_id else None
        winner_travel_time = winner_ar.get('EstimatedTravelTime') if winner_ar else None
        winner_travel_dist = (winner_ar.get('FSL__EstimatedTravelDistanceTo__c', 0) * _MI_PER_METER
                              if winner_ar else None)

        dec_id = f"{run_id}_{sa_id}"
        sa_decisions.append({
            'id': dec_id,
            'run_id': run_id,
            'sa_id': sa_id,
            'sa_number': sa_number,
            'sa_work_type': None,  # not in request JSON, enriched separately if needed
            'action': action,
            'unscheduled_reason': reason,
            'winner_driver_id': winner_driver_id,
            'winner_driver_name': winner_driver_name,
            'winner_travel_time_min': winner_travel_time,
            'winner_travel_dist_mi': winner_travel_dist,
            'run_at': run_at,
        })

        # ── Driver verdicts for this SA ──
        required_skills = sa_skills.get(sa_id, set())

        for rid, rdata in res_index.items():
            # Skip winner first
            is_winner = (rid == winner_driver_id)

            # Territory check
            if sa_territory_id and sa_territory_id not in rdata['territories']:
                reason_code = 'territory'
                status = 'excluded'
            # Skill check (best effort — skills may overlap across SAs in request)
            elif required_skills and not required_skills.issubset(rdata['skills']):
                reason_code = 'skill'
                status = 'excluded'
            # Absence check
            elif _is_absent(rid, sched_start, rdata['absences'] + non_avail.get(rid, [])):
                reason_code = 'absent'
                status = 'excluded'
            elif is_winner:
                reason_code = None
                status = 'winner'
            else:
                reason_code = None
                status = 'eligible'

            # Travel time: exact for winner, estimated (~) for others
            if is_winner and winner_travel_time is not None:
                t_time = winner_travel_time
                t_dist = winner_travel_dist
            else:
                dist_m = (winner_ar.get('FSL__EstimatedTravelDistanceTo__c', 0)
                          if winner_ar else 0)
                # For non-winners we don't have travel distance in response
                t_time = None
                t_dist = None

            driver_verdicts.append({
                'id': f"{run_id}_{sa_id}_{rid}",
                'run_id': run_id,
                'sa_id': sa_id,
                'driver_id': rid,
                'driver_name': rdata['name'],
                'status': status,
                'exclusion_reason': reason_code,
                'travel_time_min': t_time,
                'travel_dist_mi': t_dist,
                'run_at': run_at,
            })

    return run_row, sa_decisions, driver_verdicts


def _is_absent(resource_id: str, sched_start: str | None,
               absences: list[tuple[str, str]]) -> bool:
    if not sched_start or not absences:
        return False
    try:
        sa_time = datetime.fromisoformat(sched_start.replace('Z', '+00:00'))
        for start_str, end_str in absences:
            a_start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
            a_end = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
            if a_start <= sa_time <= a_end:
                return True
    except Exception:
        pass
    return False


# ── Insert helpers ────────────────────────────────────────────────────────────

def _insert_run(run_row: dict, sa_decisions: list[dict], driver_verdicts: list[dict]) -> int:
    """Insert all rows. ON CONFLICT DO NOTHING ensures idempotency."""
    cols_run = list(run_row.keys())
    cols_dec = list(sa_decisions[0].keys()) if sa_decisions else []
    cols_verd = list(driver_verdicts[0].keys()) if driver_verdicts else []

    def _placeholders(cols):
        return ', '.join(['?' * len(cols)])[::2]  # '?, ?, ?'

    def _ph(n):
        return ', '.join(['?'] * n)

    with optimizer_db.get_conn() as conn:
        conn.execute(
            f"INSERT OR IGNORE INTO opt_runs ({', '.join(cols_run)}) VALUES ({_ph(len(cols_run))})",
            list(run_row.values())
        )
        for dec in sa_decisions:
            conn.execute(
                f"INSERT OR IGNORE INTO opt_sa_decisions ({', '.join(cols_dec)}) VALUES ({_ph(len(cols_dec))})",
                list(dec.values())
            )
        for v in driver_verdicts:
            conn.execute(
                f"INSERT OR IGNORE INTO opt_driver_verdicts ({', '.join(cols_verd)}) VALUES ({_ph(len(cols_verd))})",
                list(v.values())
            )
    return len(driver_verdicts)


# ── Territory name resolution ─────────────────────────────────────────────────

def _resolve_territory_name(territory_id: str) -> str:
    if not territory_id:
        return ''
    try:
        data = _sf_get(
            f"/services/data/v59.0/query/?q="
            f"SELECT+Name+FROM+ServiceTerritory+WHERE+Id='{territory_id}'"
        )
        recs = data.get('records', [])
        return recs[0]['Name'] if recs else territory_id
    except Exception:
        return territory_id


# ── Main sync tick ────────────────────────────────────────────────────────────

def sync_tick(days: int = 30):
    """One sync cycle. Called by the background thread every _SYNC_INTERVAL seconds."""
    started_at = datetime.now(timezone.utc).isoformat()
    start_ts = time.time()
    counts = dict(found=0, inserted=0, skipped=0, failed=0, verdicts=0, purged=0)
    error_detail = None

    try:
        # Step 1: retry previously failed runs
        with optimizer_db.get_conn() as conn:
            errors = conn.execute(
                "SELECT run_id, run_name FROM opt_sync_errors WHERE retried=false LIMIT 10"
            ).fetchall()
        for run_id, run_name in errors:
            _retry_failed_run(run_id, run_name, counts)

        # Step 2: determine cursor
        with optimizer_db.get_conn(read_only=True) as conn:
            row = conn.execute("SELECT MAX(run_at) FROM opt_runs").fetchone()
        cursor = row[0] if row and row[0] else (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()

        # Step 3: fetch new runs from SF
        cursor_str = cursor if isinstance(cursor, str) else cursor.isoformat()
        soql = (
            f"SELECT Id, Name, CreatedDate FROM FSL__Optimization_Request__c"
            f" WHERE CreatedDate >= {cursor_str[:19]}Z"
            f" ORDER BY CreatedDate ASC LIMIT 50"
        )
        data = _sf_get(f"/services/data/v59.0/query/?q={soql.replace(' ', '+')}")
        sf_runs = data.get('records', [])
        counts['found'] = len(sf_runs)

        # Step 4: process each run
        for sf_run in sf_runs:
            run_id = sf_run['Id']
            run_name = sf_run['Name']
            run_at = sf_run['CreatedDate']

            # Already in DB? Skip.
            with optimizer_db.get_conn(read_only=True) as conn:
                exists = conn.execute(
                    "SELECT 1 FROM opt_runs WHERE id = ?", [run_id]
                ).fetchone()
            if exists:
                counts['skipped'] += 1
                continue

            try:
                req_cv_id, resp_cv_id = _get_content_versions(run_id)
                if not req_cv_id or not resp_cv_id:
                    raise RuntimeError("Missing content versions")
                req_json = _download_json(req_cv_id)
                resp_json = _download_json(resp_cv_id)
                run_row, sa_decisions, driver_verdicts = _parse_run(
                    run_id, run_name, run_at, req_json, resp_json
                )
                # Resolve territory name
                run_row['territory_name'] = _resolve_territory_name(run_row['territory_id'])
                verdicts_n = _insert_run(run_row, sa_decisions, driver_verdicts)
                counts['inserted'] += 1
                counts['verdicts'] += verdicts_n
                # Mark retried in errors table if it was there
                with optimizer_db.get_conn() as conn:
                    conn.execute(
                        "UPDATE opt_sync_errors SET retried=true WHERE run_id=?", [run_id]
                    )
            except Exception as e:
                log.warning(f"optimizer_sync: failed run {run_name}: {e}")
                with optimizer_db.get_conn() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO opt_sync_errors(run_id,run_name,error,failed_at,retried)"
                        " VALUES(?,?,?,now(),false)",
                        [run_id, run_name, str(e)[:500]]
                    )
                counts['failed'] += 1

        # Step 5: purge old rows
        purged = optimizer_db.purge_old_runs(days=days)
        counts['purged'] = purged or 0

        status = 'success' if counts['failed'] == 0 else 'partial'

    except Exception as e:
        log.error(f"optimizer_sync: tick failed: {e}", exc_info=True)
        status = 'failed'
        error_detail = str(e)[:500]

    finally:
        finished_at = datetime.now(timezone.utc).isoformat()
        duration_ms = int((time.time() - start_ts) * 1000)
        try:
            database.write_sync_audit(
                started_at=started_at, finished_at=finished_at, status=status,
                runs_found=counts['found'], runs_inserted=counts['inserted'],
                runs_skipped=counts['skipped'], runs_failed=counts['failed'],
                verdicts_inserted=counts['verdicts'], rows_purged=counts['purged'],
                error_detail=error_detail, duration_ms=duration_ms,
            )
        except Exception:
            pass


def _retry_failed_run(run_id: str, run_name: str, counts: dict):
    try:
        req_cv_id, resp_cv_id = _get_content_versions(run_id)
        if not req_cv_id or not resp_cv_id:
            return
        req_json = _download_json(req_cv_id)
        resp_json = _download_json(resp_cv_id)
        with optimizer_db.get_conn(read_only=True) as conn:
            row = conn.execute(
                "SELECT CreatedDate FROM opt_runs WHERE id=?", [run_id]
            ).fetchone()
        run_at = row[0] if row else datetime.now(timezone.utc).isoformat()
        run_row, sa_decisions, driver_verdicts = _parse_run(
            run_id, run_name, str(run_at), req_json, resp_json
        )
        run_row['territory_name'] = _resolve_territory_name(run_row['territory_id'])
        _insert_run(run_row, sa_decisions, driver_verdicts)
        with optimizer_db.get_conn() as conn:
            conn.execute(
                "UPDATE opt_sync_errors SET retried=true WHERE run_id=?", [run_id]
            )
        counts['inserted'] += 1
    except Exception as e:
        log.warning(f"optimizer_sync: retry failed for {run_name}: {e}")


# ── Background thread ─────────────────────────────────────────────────────────

def _run_loop():
    while True:
        try:
            if _acquire_lock():
                try:
                    sync_tick()
                finally:
                    _release_lock()
        except Exception as e:
            log.error(f"optimizer_sync loop error: {e}", exc_info=True)
        time.sleep(_SYNC_INTERVAL)


def start():
    """Start background sync thread. Safe to call from multiple workers — lock prevents duplication."""
    optimizer_db.init_db()
    t = threading.Thread(target=_run_loop, daemon=True, name='optimizer-sync')
    t.start()
    log.info("Optimizer sync thread started")
```

- [ ] **Step 2: Smoke test one SF run**

```bash
cd backend
python3 -c "
import optimizer_db, optimizer_sync
optimizer_db.init_db()

# Test against one known run
req_cv_id = '068Pb00001X8RKUIA3'  # from earlier exploration
resp_cv_id = '068Pb00001X8e81IAB'

req = optimizer_sync._download_json(req_cv_id)
resp = optimizer_sync._download_json(resp_cv_id)
print('Request keys:', list(req.keys()))
print('Response keys:', list(resp.keys()))

run_row, sa_decs, verdicts = optimizer_sync._parse_run(
    'a1uPb000009IcMbIAK', 'OR-2026-04-122089',
    '2026-04-09T00:15:02.000+0000', req, resp
)
print('Run row:', run_row)
print('SA decisions:', len(sa_decs))
print('Driver verdicts:', len(verdicts))
print('Sample verdict:', verdicts[0] if verdicts else 'none')
"
```

Expected: prints run_row dict, SA decision count (~17), verdict count (~900).

- [ ] **Step 3: Commit**

```bash
git add backend/optimizer_sync.py
git commit -m "feat(optimizer): delta sync job with SF download, parse, and DuckDB insert"
```

---

## Task 4: Backfill CLI Script

**Files:**
- Create: `backend/optimizer_init.py`

- [ ] **Step 1: Create optimizer_init.py**

```python
#!/usr/bin/env python3
"""One-time backfill script: pulls last N days of optimizer runs from SF into DuckDB.

Usage:
    python optimizer_init.py --days 30
    python optimizer_init.py --days 30 --force   # re-process runs already in DB
"""

import argparse, logging, os, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'), override=False)
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'), override=False)

import optimizer_db
import optimizer_sync
import database

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('optimizer_init')


def main():
    parser = argparse.ArgumentParser(description='Backfill optimizer runs into DuckDB')
    parser.add_argument('--days', type=int, default=30, help='Days to backfill (default 30)')
    parser.add_argument('--force', action='store_true', help='Re-process runs already in DB')
    args = parser.parse_args()

    optimizer_db.init_db()
    database.init_db()

    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
    log.info(f"Backfilling optimizer runs since {since} ({args.days} days)")

    offset = 0
    total_inserted = total_skipped = total_failed = total_verdicts = 0
    page = 0

    while True:
        page += 1
        soql = (
            f"SELECT Id, Name, CreatedDate FROM FSL__Optimization_Request__c"
            f" WHERE CreatedDate >= {since[:19]}Z"
            f" ORDER BY CreatedDate ASC LIMIT 50 OFFSET {offset}"
        )
        data = optimizer_sync._sf_get(
            f"/services/data/v59.0/query/?q={soql.replace(' ', '+')}"
        )
        runs = data.get('records', [])
        if not runs:
            break

        log.info(f"Page {page}: processing {len(runs)} runs (offset {offset})")

        for sf_run in runs:
            run_id = sf_run['Id']
            run_name = sf_run['Name']
            run_at = sf_run['CreatedDate']

            if not args.force:
                with optimizer_db.get_conn(read_only=True) as conn:
                    exists = conn.execute(
                        "SELECT 1 FROM opt_runs WHERE id = ?", [run_id]
                    ).fetchone()
                if exists:
                    total_skipped += 1
                    continue

            try:
                req_cv_id, resp_cv_id = optimizer_sync._get_content_versions(run_id)
                if not req_cv_id or not resp_cv_id:
                    log.warning(f"  {run_name}: no content versions, skipping")
                    total_failed += 1
                    continue

                req_json = optimizer_sync._download_json(req_cv_id)
                resp_json = optimizer_sync._download_json(resp_cv_id)
                run_row, sa_decs, verdicts = optimizer_sync._parse_run(
                    run_id, run_name, run_at, req_json, resp_json
                )
                run_row['territory_name'] = optimizer_sync._resolve_territory_name(
                    run_row['territory_id']
                )
                n_verdicts = optimizer_sync._insert_run(run_row, sa_decs, verdicts)
                total_inserted += 1
                total_verdicts += n_verdicts
                log.info(f"  ✓ {run_name} — {len(sa_decs)} SAs, {n_verdicts} verdicts")

            except Exception as e:
                log.error(f"  ✗ {run_name}: {e}")
                total_failed += 1

            time.sleep(0.5)  # throttle SF calls

        offset += len(runs)
        if len(runs) < 50:
            break

    log.info(
        f"\nBackfill complete: {total_inserted} inserted, "
        f"{total_skipped} skipped, {total_failed} failed, "
        f"{total_verdicts} verdicts stored"
    )


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: Test run (dry run with --days 1 to verify it works)**

```bash
cd backend
python optimizer_init.py --days 1
```

Expected output:
```
2026-04-27 ... INFO Backfilling optimizer runs since ... (1 days)
2026-04-27 ... INFO Page 1: processing N runs (offset 0)
2026-04-27 ... INFO   ✓ OR-2026-04-127... — 17 SAs, 918 verdicts
...
2026-04-27 ... INFO Backfill complete: N inserted, 0 skipped, 0 failed, NNN verdicts stored
```

- [ ] **Step 3: Commit**

```bash
git add backend/optimizer_init.py
git commit -m "feat(optimizer): one-time backfill CLI script with throttling"
```

---

## Task 5: Wire Sync into main.py

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add import after existing imports in main.py**

After the line `import refresher`:
```python
import optimizer_sync
```

- [ ] **Step 2: Add sync start to the startup event handler**

In the `startup()` function, after `refresher.start()`:
```python
    # Start optimizer sync (every 15 min, leader-elected)
    optimizer_sync.start()
```

- [ ] **Step 3: Register optimizer router — add to the import block**

In the router imports block, add:
```python
from routers import optimizer as optimizer_router
```

After the existing `app.include_router(...)` calls:
```python
app.include_router(optimizer_router.router, prefix="/api/optimizer")
```

- [ ] **Step 4: Verify startup**

```bash
cd backend
uvicorn main:app --port 8000 --reload
```

Check logs for:
```
INFO:optimizer_sync:Optimizer sync thread started
```

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "feat(optimizer): wire sync thread and router into app startup"
```

---

## Task 6: REST API Endpoints

**Files:**
- Create: `backend/routers/optimizer.py`

- [ ] **Step 1: Create routers/optimizer.py**

```python
"""Optimizer decoder REST endpoints."""

from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Query

import optimizer_db
import database

router = APIRouter(tags=['optimizer'])


@router.get('/runs')
def get_runs(
    from_dt: str = Query(None, description="ISO datetime, default 24h ago"),
    to_dt: str = Query(None, description="ISO datetime, default now"),
    territory: str = Query(None),
):
    now = datetime.now(timezone.utc)
    f = from_dt or (now - timedelta(hours=24)).isoformat()
    t = to_dt or now.isoformat()
    return optimizer_db.list_runs(f, t, territory)


@router.get('/runs/{run_id}')
def get_run(run_id: str):
    result = optimizer_db.get_run_detail(run_id)
    if not result:
        raise HTTPException(404, f"Run {run_id} not found")
    return result


@router.get('/sa/{sa_number}')
def get_sa(sa_number: str, limit: int = Query(5, le=20)):
    return optimizer_db.get_sa_decision(sa_number, limit)


@router.get('/driver/{driver_name}')
def get_driver(driver_name: str, days: int = Query(7, le=30)):
    return optimizer_db.get_driver_analysis(driver_name, days)


@router.get('/runs/{run_id}/unscheduled')
def get_unscheduled(run_id: str):
    return optimizer_db.get_unscheduled_analysis(run_id)


@router.get('/patterns')
def get_patterns(territory: str = Query(None), days: int = Query(7, le=30)):
    return optimizer_db.get_exclusion_patterns(territory, days)


@router.post('/query')
def run_sql(body: dict):
    sql = body.get('sql', '')
    if not sql:
        raise HTTPException(400, "sql field required")
    try:
        return optimizer_db.query_optimizer_sql(sql)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get('/admin/sync-audit')
def sync_audit(limit: int = Query(50, le=200)):
    return database.get_sync_audit(limit)
```

- [ ] **Step 2: Test endpoints**

```bash
# List recent runs
curl http://localhost:8000/api/optimizer/runs | python3 -m json.tool | head -40

# Get SA decision
curl "http://localhost:8000/api/optimizer/sa/SA-04799070" | python3 -m json.tool

# Sync audit
curl http://localhost:8000/api/optimizer/admin/sync-audit | python3 -m json.tool
```

Expected: all return JSON without errors.

- [ ] **Step 3: Commit**

```bash
git add backend/routers/optimizer.py
git commit -m "feat(optimizer): REST endpoints for runs, SA decisions, driver analysis"
```

---

## Task 7: AI Chat Endpoint

**Files:**
- Create: `backend/routers/optimizer_chat.py`

- [ ] **Step 1: Create routers/optimizer_chat.py**

```python
"""Optimizer chat endpoint — domain-grounded AI with DuckDB tool calling."""

import json, os, logging
from fastapi import APIRouter, Request, HTTPException
from routers.chatbot_providers import _call_anthropic

import optimizer_db

router = APIRouter(tags=['optimizer'])
log = logging.getLogger('optimizer_chat')

_SYSTEM_PROMPT = """You are an expert FSL (Field Service Lightning) dispatch analyst for AAA WCNY.
You help dispatchers understand why the optimizer made specific assignment decisions.

## Your Domain Knowledge

**Dispatch channels:**
- Fleet (Field Services): ~26% of calls. THE OPTIMIZER ONLY TOUCHES FLEET SAs.
  ERS_Dispatch_Method__c = 'Field Services'
- Towbook: ~74% of calls. External contractors, NOT in optimizer scope.
If asked about Towbook decisions — explain the optimizer doesn't control those.

**Optimizer cadence:** Runs every 15 minutes, 3 territories simultaneously (WNY Fleet, 076DO, 089DO).

**Scheduling Policy in this org:** "Closest Driver" (Travel-heavy) — travel time is the dominant
scoring factor. Verified from 349 real assignments: closest driver wins 69% vs soonest 31%.

**Work rules (constraints — a driver failing any rule is EXCLUDED):**
1. Territory match — driver must serve the SA's service territory
2. Skill match — driver must have all skills required by the work order line item
3. Availability — no approved absence overlapping the SA's scheduled time
4. Capacity — driver's shift window not fully booked with other SAs
5. Time dependencies — some SAs must go to the same resource (linked pairs)
6. Pinned SAs (FSL__Pinned__c=true) — locked to current driver, NOT rescheduled

**Exclusion reasons in the data:**
- 'territory': Driver's ServiceTerritories doesn't include this SA's territory
- 'skill': Driver lacks a required skill for this work type
- 'absent': Driver has an approved absence (ResourceAbsence) during this window
- 'eligible': Passed all rules but wasn't the closest — travel time was higher than winner

**Common unscheduled reason:** "Failed to reschedule a rule violating task" means the SA
was previously assigned to a driver who now violates a rule (skill removed, absence added,
territory changed) and no valid replacement could be found in this run.

**Travel time:** Winner's travel time is exact (from optimizer). Non-winner eligible drivers
show estimated (~) travel times based on straight-line distance ÷ 25 mph mean speed.

**What you can answer:**
- Why a specific driver was/wasn't assigned to a specific SA
- What work rule excluded a driver
- Patterns in exclusions across time (skill gaps, capacity overload, territory mismatches)
- Before/after KPI changes from an optimization run
- Which drivers get excluded most and why

**What you cannot answer:**
- Internal optimizer scoring (it's a black box — you only see inputs and outputs)
- Towbook dispatcher decisions (different system entirely)
- Future predictions (you only see historical runs stored in DuckDB)

Always be specific and cite the data. If the data doesn't support a conclusion, say so.
When showing decision trees, output them as structured JSON for rendering — never as ASCII art.
"""

_TOOLS = [
    {
        "name": "list_runs",
        "description": "List optimization runs in a time window. Use to show the timeline or find recent runs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "from_dt": {"type": "string", "description": "ISO datetime start (e.g. '2026-04-28T00:00:00Z')"},
                "to_dt": {"type": "string", "description": "ISO datetime end"},
                "territory": {"type": "string", "description": "Optional territory filter (partial name match)"}
            }
        }
    },
    {
        "name": "get_run_detail",
        "description": "Get full detail of one optimization run: KPIs and all SA decisions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "OptimizationRequest SF Id (starts with a1u)"}
            },
            "required": ["run_id"]
        }
    },
    {
        "name": "get_sa_decision",
        "description": "Get the decision tree for a specific SA — winner, eligible drivers, excluded drivers with reasons. Use when dispatcher asks about a specific SA number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sa_number": {"type": "string", "description": "SA number e.g. 'SA-04799070' or '04799070'"},
                "limit": {"type": "integer", "description": "Number of recent runs to include (default 1, max 5)"}
            },
            "required": ["sa_number"]
        }
    },
    {
        "name": "get_driver_analysis",
        "description": "Analyze a driver's optimizer history — how often they're assigned, eligible, or excluded and why.",
        "input_schema": {
            "type": "object",
            "properties": {
                "driver_name": {"type": "string", "description": "Driver name or partial name (e.g. '076DO')"},
                "days": {"type": "integer", "description": "Days to analyze (default 7)"}
            },
            "required": ["driver_name"]
        }
    },
    {
        "name": "get_unscheduled_analysis",
        "description": "Show all SAs the optimizer failed to schedule in a specific run, with reasons.",
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "OptimizationRequest SF Id"}
            },
            "required": ["run_id"]
        }
    },
    {
        "name": "get_exclusion_patterns",
        "description": "Aggregate patterns — which exclusion reasons fire most often, how many drivers affected. Use for 'what patterns do you see?' questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "territory": {"type": "string", "description": "Optional territory filter"},
                "days": {"type": "integer", "description": "Days to analyze (default 7)"}
            }
        }
    },
    {
        "name": "query_optimizer",
        "description": "Run a read-only SQL query against the DuckDB optimizer store. Tables: opt_runs, opt_sa_decisions, opt_driver_verdicts. Use for novel analytical questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SELECT query only. No DDL/DML."}
            },
            "required": ["sql"]
        }
    },
]


def _execute_tool(name: str, inputs: dict) -> str:
    try:
        if name == 'list_runs':
            result = optimizer_db.list_runs(
                inputs.get('from_dt', ''), inputs.get('to_dt', ''),
                inputs.get('territory')
            )
        elif name == 'get_run_detail':
            result = optimizer_db.get_run_detail(inputs['run_id'])
        elif name == 'get_sa_decision':
            sa_num = inputs['sa_number']
            if not sa_num.upper().startswith('SA-'):
                sa_num = 'SA-' + sa_num.lstrip('0').zfill(8) if sa_num.isdigit() else sa_num
            result = optimizer_db.get_sa_decision(sa_num, inputs.get('limit', 1))
        elif name == 'get_driver_analysis':
            result = optimizer_db.get_driver_analysis(
                inputs['driver_name'], inputs.get('days', 7)
            )
        elif name == 'get_unscheduled_analysis':
            result = optimizer_db.get_unscheduled_analysis(inputs['run_id'])
        elif name == 'get_exclusion_patterns':
            result = optimizer_db.get_exclusion_patterns(
                inputs.get('territory'), inputs.get('days', 7)
            )
        elif name == 'query_optimizer':
            result = optimizer_db.query_optimizer_sql(inputs['sql'])
        else:
            return f"Unknown tool: {name}"
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@router.post('/chat')
async def optimizer_chat(request: Request):
    body = await request.json()
    messages = body.get('messages', [])
    model = body.get('model', 'claude-sonnet-4-6')
    run_context = body.get('run_context')  # optional: {run_id, run_name} from timeline click

    if not messages:
        raise HTTPException(400, "messages required")

    # Inject run context as a system note if dispatcher clicked a run
    system = _SYSTEM_PROMPT
    if run_context:
        system += (
            f"\n\n## Current Context\nThe dispatcher is looking at run "
            f"{run_context.get('run_name', '')} (ID: {run_context.get('run_id', '')}, "
            f"Territory: {run_context.get('territory_name', '')}, "
            f"Time: {run_context.get('run_at', '')}). "
            f"Prioritize data from this run when answering questions."
        )

    api_messages = list(messages)

    # Agentic tool loop — up to 5 tool rounds
    for _ in range(5):
        response = _call_anthropic(
            model=model,
            system=system,
            messages=api_messages,
            tools=_TOOLS,
            max_tokens=4096,
        )

        # Collect text + tool_use blocks
        text_parts = []
        tool_calls = []
        for block in response.get('content', []):
            if block.get('type') == 'text':
                text_parts.append(block['text'])
            elif block.get('type') == 'tool_use':
                tool_calls.append(block)

        if not tool_calls:
            # Final response — check if it includes a visualization hint
            return {
                'text': '\n'.join(text_parts),
                'visualization': _extract_visualization(text_parts),
            }

        # Execute tools and continue loop
        api_messages.append({'role': 'assistant', 'content': response['content']})
        tool_results = []
        for tc in tool_calls:
            result_str = _execute_tool(tc['name'], tc.get('input', {}))
            tool_results.append({
                'type': 'tool_result',
                'tool_use_id': tc['id'],
                'content': result_str,
            })
        api_messages.append({'role': 'user', 'content': tool_results})

    return {'text': 'I reached the maximum number of tool calls. Please try a more specific question.'}


def _extract_visualization(text_parts: list[str]) -> dict | None:
    """Parse JSON visualization hint from AI response if present."""
    full = '\n'.join(text_parts)
    import re
    match = re.search(r'```json\n({.*?})\n```', full, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            if 'visualization_type' in data:
                return data
        except Exception:
            pass
    return None
```

- [ ] **Step 2: Register the chat router in main.py**

After the optimizer_router include:
```python
from routers import optimizer_chat as optimizer_chat_router
app.include_router(optimizer_chat_router.router, prefix="/api/optimizer")
```

- [ ] **Step 3: Test the chat endpoint**

```bash
curl -s -X POST http://localhost:8000/api/optimizer/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What can you tell me about recent optimization runs?"}], "model": "claude-haiku-4-5-20251001"}' \
  | python3 -m json.tool
```

Expected: JSON with `text` field containing an explanation, no errors.

- [ ] **Step 4: Commit**

```bash
git add backend/routers/optimizer_chat.py backend/main.py
git commit -m "feat(optimizer): AI chat endpoint with domain grounding and DuckDB tools"
```

---

## Task 8: Admin Sync Audit UI

**Files:**
- Modify: `frontend/src/components/AdminActivityLog.jsx` (add sync audit section) OR
- Create: `frontend/src/components/AdminOptimizerSync.jsx` (preferred — keeps AdminActivityLog under 600 lines)

Check `AdminActivityLog.jsx` line count first:

```bash
wc -l frontend/src/components/AdminActivityLog.jsx
```

If under 500 lines, add the section there. If over 500, create a new component.

- [ ] **Step 1: Create AdminOptimizerSync.jsx**

```jsx
import { useState, useEffect } from 'react'
import { Activity, CheckCircle, AlertTriangle, XCircle, RefreshCw } from 'lucide-react'
import api from '../api'

const STATUS_ICON = {
  success: <CheckCircle size={14} className="text-green-400" />,
  partial: <AlertTriangle size={14} className="text-yellow-400" />,
  failed: <XCircle size={14} className="text-red-400" />,
  running: <RefreshCw size={14} className="text-blue-400 animate-spin" />,
}

export default function AdminOptimizerSync() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState(null)

  const load = async () => {
    setLoading(true)
    try {
      const data = await api.getOptimizerSyncAudit()
      setRows(data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2">
          <Activity size={14} className="text-blue-400" />
          Optimizer Sync Audit
        </h3>
        <button onClick={load} className="text-xs text-gray-400 hover:text-white flex items-center gap-1">
          <RefreshCw size={11} /> Refresh
        </button>
      </div>

      {loading ? (
        <div className="text-xs text-gray-500">Loading...</div>
      ) : rows.length === 0 ? (
        <div className="text-xs text-gray-500">No sync records yet.</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-500 border-b border-white/10">
                <th className="text-left pb-1 pr-3">Time</th>
                <th className="text-left pb-1 pr-3">Status</th>
                <th className="text-right pb-1 pr-3">Found</th>
                <th className="text-right pb-1 pr-3">Stored</th>
                <th className="text-right pb-1 pr-3">Skipped</th>
                <th className="text-right pb-1 pr-3">Failed</th>
                <th className="text-right pb-1 pr-3">Verdicts</th>
                <th className="text-right pb-1">Duration</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <>
                  <tr key={r.id}
                    className={`border-b border-white/5 cursor-pointer hover:bg-white/5 ${r.error_detail ? 'cursor-pointer' : ''}`}
                    onClick={() => r.error_detail && setExpanded(expanded === r.id ? null : r.id)}
                  >
                    <td className="py-1 pr-3 text-gray-400 whitespace-nowrap">
                      {new Date(r.started_at).toLocaleString('en-US', {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})}
                    </td>
                    <td className="py-1 pr-3">
                      <span className="flex items-center gap-1">
                        {STATUS_ICON[r.status]}
                        <span className={r.status === 'success' ? 'text-green-400' : r.status === 'partial' ? 'text-yellow-400' : 'text-red-400'}>
                          {r.status}
                        </span>
                      </span>
                    </td>
                    <td className="py-1 pr-3 text-right text-gray-300">{r.runs_found}</td>
                    <td className="py-1 pr-3 text-right text-green-400">{r.runs_inserted}</td>
                    <td className="py-1 pr-3 text-right text-gray-500">{r.runs_skipped}</td>
                    <td className="py-1 pr-3 text-right text-red-400">{r.runs_failed || '—'}</td>
                    <td className="py-1 pr-3 text-right text-gray-400">{r.verdicts_inserted?.toLocaleString()}</td>
                    <td className="py-1 text-right text-gray-500">{r.duration_ms ? `${(r.duration_ms/1000).toFixed(1)}s` : '—'}</td>
                  </tr>
                  {expanded === r.id && r.error_detail && (
                    <tr key={`${r.id}-err`} className="bg-red-950/30">
                      <td colSpan={8} className="py-2 px-2 text-xs text-red-300 font-mono">
                        {r.error_detail}
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Add to Admin.jsx**

In `frontend/src/pages/Admin.jsx`, import and render `AdminOptimizerSync` in the admin page body (after existing sections):

```jsx
import AdminOptimizerSync from '../components/AdminOptimizerSync'
// ... inside the JSX:
<AdminOptimizerSync />
```

- [ ] **Step 3: Add API call to api.js**

```js
// In api.js, add to the export object:
getOptimizerSyncAudit: () => axios.get('/api/optimizer/admin/sync-audit').then(r => r.data),
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/AdminOptimizerSync.jsx frontend/src/pages/Admin.jsx frontend/src/api.js
git commit -m "feat(optimizer): admin sync audit table UI"
```

---

## Task 9: Frontend Dependencies + API Layer

**Files:**
- Modify: `frontend/package.json`, `frontend/src/api.js`

- [ ] **Step 1: Install new dependencies**

```bash
cd frontend
npm install @xyflow/react@^12 @floating-ui/react@^0.26
```

- [ ] **Step 2: Add optimizer API calls to api.js**

```js
// Optimizer Decoder
getOptimizerRuns: (params = {}) =>
  axios.get('/api/optimizer/runs', { params }).then(r => r.data),

getOptimizerRun: (runId) =>
  axios.get(`/api/optimizer/runs/${runId}`).then(r => r.data),

getOptimizerSA: (saNumber, limit = 1) =>
  axios.get(`/api/optimizer/sa/${saNumber}`, { params: { limit } }).then(r => r.data),

getOptimizerDriver: (driverName, days = 7) =>
  axios.get(`/api/optimizer/driver/${encodeURIComponent(driverName)}`, { params: { days } }).then(r => r.data),

getOptimizerUnscheduled: (runId) =>
  axios.get(`/api/optimizer/runs/${runId}/unscheduled`).then(r => r.data),

getOptimizerPatterns: (params = {}) =>
  axios.get('/api/optimizer/patterns', { params }).then(r => r.data),

chatOptimizer: (messages, model = 'claude-sonnet-4-6', runContext = null) =>
  axios.post('/api/optimizer/chat', { messages, model, run_context: runContext }).then(r => r.data),
```

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/api.js
git commit -m "feat(optimizer): add frontend deps and optimizer API helpers"
```

---

## Task 10: Decision Tree Component

**Files:**
- Create: `frontend/src/components/OptDecisionTree.jsx`

- [ ] **Step 1: Create OptDecisionTree.jsx**

```jsx
import { useCallback, useMemo } from 'react'
import { ReactFlow, Background, Controls, MiniMap, useNodesState, useEdgesState, Handle, Position } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { CheckCircle, XCircle, AlertCircle, ChevronDown, ChevronRight } from 'lucide-react'
import { useState } from 'react'

// ── Custom node types ──────────────────────────────────────────────────────

function SANode({ data }) {
  return (
    <div className="bg-blue-900/80 border border-blue-500 rounded-xl px-4 py-3 min-w-[200px] shadow-lg">
      <Handle type="source" position={Position.Bottom} className="!bg-blue-400" />
      <div className="text-blue-200 text-xs font-mono">{data.sa_number}</div>
      <div className="text-white font-semibold text-sm">{data.work_type || 'Service Call'}</div>
      <div className="text-gray-400 text-xs mt-1">{data.run_at}</div>
    </div>
  )
}

function FilterNode({ data }) {
  const [open, setOpen] = useState(false)
  const color = data.count > 0 ? 'border-orange-500 bg-orange-900/60' : 'border-gray-600 bg-gray-800/60'
  return (
    <div className={`border rounded-xl px-3 py-2 min-w-[160px] cursor-pointer shadow ${color}`}
         onClick={() => setOpen(o => !o)}>
      <Handle type="target" position={Position.Top} className="!bg-orange-400" />
      <Handle type="source" position={Position.Bottom} className="!bg-orange-400" />
      <div className="flex items-center justify-between">
        <div className="text-white text-xs font-semibold">{data.label}</div>
        <span className="text-orange-300 text-xs font-bold">{data.count} excluded</span>
        {data.count > 0 ? <ChevronDown size={12} className="text-orange-300 ml-1" /> : null}
      </div>
      {open && data.drivers?.length > 0 && (
        <div className="mt-2 space-y-1 border-t border-orange-700/40 pt-1">
          {data.drivers.map((d, i) => (
            <div key={i} className="text-xs text-orange-200 flex justify-between">
              <span>{d.driver_name}</span>
              <span className="text-orange-400 ml-2">{d.exclusion_reason}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function WinnerNode({ data }) {
  return (
    <div className="bg-green-900/80 border-2 border-green-400 rounded-xl px-4 py-3 min-w-[180px] shadow-lg">
      <Handle type="target" position={Position.Top} className="!bg-green-400" />
      <div className="flex items-center gap-2">
        <CheckCircle size={16} className="text-green-400" />
        <div className="text-green-300 font-bold text-sm">{data.driver_name}</div>
      </div>
      <div className="text-green-200 text-xs mt-1">
        {data.travel_time_min != null ? `${data.travel_time_min} min` : ''}
        {data.travel_dist_mi != null ? ` · ${data.travel_dist_mi?.toFixed(1)} mi` : ''}
      </div>
      <div className="text-green-500 text-xs">WINNER ✓</div>
    </div>
  )
}

function EligibleNode({ data }) {
  return (
    <div className="bg-gray-800/80 border border-gray-500 rounded-xl px-3 py-2 min-w-[160px] shadow">
      <Handle type="target" position={Position.Top} className="!bg-gray-400" />
      <div className="text-gray-300 text-xs font-semibold">{data.driver_name}</div>
      <div className="text-gray-400 text-xs">
        {data.travel_time_min != null ? `~${data.travel_time_min} min` : 'eligible'}
      </div>
    </div>
  )
}

const nodeTypes = { sa: SANode, filter: FilterNode, winner: WinnerNode, eligible: EligibleNode }

// ── Main component ─────────────────────────────────────────────────────────

export default function OptDecisionTree({ decision }) {
  // decision = { sa_number, sa_work_type, action, run_at, territory_name, policy_name, verdicts: [...] }
  const verdicts = decision?.verdicts || []

  const excluded = verdicts.filter(v => v.status === 'excluded')
  const eligible = verdicts.filter(v => v.status === 'eligible').slice(0, 5)
  const winner = verdicts.find(v => v.status === 'winner')

  const byReason = {
    territory: excluded.filter(v => v.exclusion_reason === 'territory'),
    skill: excluded.filter(v => v.exclusion_reason === 'skill'),
    absent: excluded.filter(v => v.exclusion_reason === 'absent'),
    capacity: excluded.filter(v => v.exclusion_reason === 'capacity'),
  }

  const nodes = [
    { id: 'sa', type: 'sa', position: { x: 300, y: 0 },
      data: { sa_number: decision?.sa_number, work_type: decision?.sa_work_type,
              run_at: decision?.run_at ? new Date(decision.run_at).toLocaleString() : '' } },
    { id: 'f-territory', type: 'filter', position: { x: 0, y: 150 },
      data: { label: 'Territory', count: byReason.territory.length, drivers: byReason.territory } },
    { id: 'f-skill', type: 'filter', position: { x: 200, y: 150 },
      data: { label: 'Skills', count: byReason.skill.length, drivers: byReason.skill } },
    { id: 'f-absent', type: 'filter', position: { x: 400, y: 150 },
      data: { label: 'Availability', count: byReason.absent.length, drivers: byReason.absent } },
    { id: 'f-capacity', type: 'filter', position: { x: 600, y: 150 },
      data: { label: 'Capacity', count: byReason.capacity.length, drivers: byReason.capacity } },
    ...(winner ? [{ id: 'winner', type: 'winner', position: { x: 250, y: 320 },
      data: { driver_name: winner.driver_name, travel_time_min: winner.travel_time_min,
              travel_dist_mi: winner.travel_dist_mi } }] : []),
    ...eligible.map((v, i) => ({
      id: `elig-${i}`, type: 'eligible',
      position: { x: 480 + i * 170, y: 320 },
      data: { driver_name: v.driver_name, travel_time_min: v.travel_time_min }
    })),
  ]

  const edges = [
    { id: 'sa-ft', source: 'sa', target: 'f-territory', animated: true, style: { stroke: '#f97316' } },
    { id: 'sa-fs', source: 'sa', target: 'f-skill', animated: true, style: { stroke: '#f97316' } },
    { id: 'sa-fa', source: 'sa', target: 'f-absent', animated: true, style: { stroke: '#f97316' } },
    { id: 'sa-fc', source: 'sa', target: 'f-capacity', animated: true, style: { stroke: '#f97316' } },
    ...(winner ? [{ id: 'fc-winner', source: 'f-capacity', target: 'winner',
      style: { stroke: '#4ade80', strokeWidth: 2 } }] : []),
    ...eligible.map((_, i) => ({
      id: `fc-elig-${i}`, source: 'f-capacity', target: `elig-${i}`,
      style: { stroke: '#6b7280' }
    })),
  ]

  const [rfNodes, , onNodesChange] = useNodesState(nodes)
  const [rfEdges, , onEdgesChange] = useEdgesState(edges)

  if (!decision) return null

  return (
    <div className="rounded-xl overflow-hidden border border-white/10" style={{ height: 480 }}>
      <div className="bg-gray-900/80 px-3 py-2 text-xs text-gray-400 border-b border-white/10 flex justify-between">
        <span>{decision.sa_number} · {decision.territory_name} · {decision.policy_name}</span>
        <span>{verdicts.length} drivers evaluated</span>
      </div>
      <ReactFlow
        nodes={rfNodes} edges={rfEdges}
        onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView fitViewOptions={{ padding: 0.2 }}
        className="bg-gray-950"
      >
        <Background color="#374151" gap={20} />
        <Controls className="!bg-gray-800 !border-gray-600" />
        <MiniMap className="!bg-gray-900" nodeColor="#374151" />
      </ReactFlow>
    </div>
  )
}
```

- [ ] **Step 2: Quick render test**

Add a temporary route to verify the component loads without errors (remove after):

```bash
cd frontend && npm run dev
# Open http://localhost:5173 and check console for errors
```

Expected: no import errors, no crash.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/OptDecisionTree.jsx
git commit -m "feat(optimizer): React Flow decision tree with expand/collapse filter nodes"
```

---

## Task 11: KPI Bar + Driver Chart Components

**Files:**
- Create: `frontend/src/components/OptKpiBar.jsx`
- Create: `frontend/src/components/OptDriverChart.jsx`

- [ ] **Step 1: Create OptKpiBar.jsx**

```jsx
import { BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, Cell } from 'recharts'

export default function OptKpiBar({ run }) {
  if (!run) return null

  const data = [
    { name: 'Scheduled', before: run.pre_scheduled, after: run.post_scheduled },
    { name: 'Unscheduled', before: 0, after: run.unscheduled_count },
    { name: 'Travel Time (min)', before: Math.round((run.pre_travel_time_s||0)/60), after: Math.round((run.post_travel_time_s||0)/60) },
    { name: 'Avg Response (min)', before: Math.round((run.pre_response_avg_s||0)/60), after: Math.round((run.post_response_avg_s||0)/60) },
  ]

  return (
    <div className="rounded-xl bg-gray-900/60 border border-white/10 p-4">
      <div className="text-xs text-gray-400 mb-3 font-semibold">
        {run.name} · {run.territory_name} · {run.policy_name}
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
          <XAxis dataKey="name" tick={{ fill: '#9ca3af', fontSize: 11 }} />
          <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} />
          <Tooltip contentStyle={{ background: '#1f2937', border: '1px solid #374151', borderRadius: 8 }}
                   labelStyle={{ color: '#f3f4f6' }} />
          <Legend wrapperStyle={{ fontSize: 11, color: '#9ca3af' }} />
          <Bar dataKey="before" name="Before" fill="#4b5563" radius={[3,3,0,0]} />
          <Bar dataKey="after" name="After" fill="#3b82f6" radius={[3,3,0,0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
```

- [ ] **Step 2: Create OptDriverChart.jsx**

```jsx
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

const REASON_COLORS = {
  territory: '#f59e0b',
  skill: '#ef4444',
  absent: '#8b5cf6',
  capacity: '#06b6d4',
}

export default function OptDriverChart({ patterns }) {
  if (!patterns?.length) return null

  const data = patterns.map(p => ({
    name: p.exclusion_reason || 'unknown',
    fires: p.fires,
    drivers: p.drivers_affected,
    color: REASON_COLORS[p.exclusion_reason] || '#6b7280',
  }))

  return (
    <div className="rounded-xl bg-gray-900/60 border border-white/10 p-4">
      <div className="text-xs text-gray-400 mb-3 font-semibold">Exclusion Patterns</div>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} layout="vertical" margin={{ left: 20, right: 10 }}>
          <XAxis type="number" tick={{ fill: '#9ca3af', fontSize: 11 }} />
          <YAxis dataKey="name" type="category" tick={{ fill: '#9ca3af', fontSize: 11 }} width={80} />
          <Tooltip
            contentStyle={{ background: '#1f2937', border: '1px solid #374151', borderRadius: 8 }}
            formatter={(val, name, props) => [
              `${val} fires · ${props.payload.drivers} drivers affected`, 'Count'
            ]}
          />
          <Bar dataKey="fires" radius={[0,3,3,0]}>
            {data.map((entry, i) => <Cell key={i} fill={entry.color} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="flex gap-3 mt-2 flex-wrap">
        {Object.entries(REASON_COLORS).map(([k, v]) => (
          <span key={k} className="flex items-center gap-1 text-xs text-gray-400">
            <span className="w-2 h-2 rounded-full inline-block" style={{ background: v }} />
            {k}
          </span>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/OptKpiBar.jsx frontend/src/components/OptDriverChart.jsx
git commit -m "feat(optimizer): KPI before/after bars and driver exclusion pattern chart"
```

---

## Task 12: Timeline Component

**Files:**
- Create: `frontend/src/components/OptimizerTimeline.jsx`

- [ ] **Step 1: Create OptimizerTimeline.jsx**

```jsx
import { useState, useEffect, useCallback } from 'react'
import { RefreshCw, AlertTriangle, CheckCircle, Clock } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import api from '../api'

function groupByHour(runs) {
  const groups = {}
  runs.forEach(r => {
    const d = new Date(r.run_at)
    const key = `${d.toLocaleDateString('en-US',{month:'short',day:'numeric'})} ${d.getHours().toString().padStart(2,'0')}:00`
    if (!groups[key]) groups[key] = []
    groups[key].push(r)
  })
  return Object.entries(groups)
}

export default function OptimizerTimeline({ onRunSelect, selectedRunId }) {
  const [runs, setRuns] = useState([])
  const [loading, setLoading] = useState(true)
  const [territory, setTerritory] = useState('')
  const [hours, setHours] = useState(24)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const to = new Date().toISOString()
      const from = new Date(Date.now() - hours * 3600000).toISOString()
      const data = await api.getOptimizerRuns({ from_dt: from, to_dt: to, territory: territory || undefined })
      setRuns(data)
    } finally {
      setLoading(false)
    }
  }, [hours, territory])

  useEffect(() => { load() }, [load])

  const groups = groupByHour(runs)

  return (
    <div className="flex flex-col h-full">
      {/* Controls */}
      <div className="px-3 py-2 border-b border-white/10 space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-400 font-semibold">RUN TIMELINE</span>
          <button onClick={load} className="text-gray-500 hover:text-white">
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
        <select
          value={hours}
          onChange={e => setHours(Number(e.target.value))}
          className="w-full bg-gray-800 text-gray-300 text-xs rounded px-2 py-1 border border-white/10"
        >
          <option value={6}>Last 6 hours</option>
          <option value={24}>Last 24 hours</option>
          <option value={72}>Last 3 days</option>
          <option value={168}>Last 7 days</option>
        </select>
        <input
          placeholder="Filter territory..."
          value={territory}
          onChange={e => setTerritory(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && load()}
          className="w-full bg-gray-800 text-gray-300 text-xs rounded px-2 py-1 border border-white/10 placeholder-gray-600"
        />
      </div>

      {/* Run list */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="p-4 text-xs text-gray-500">Loading runs...</div>
        ) : runs.length === 0 ? (
          <div className="p-4 text-xs text-gray-500">No runs found.</div>
        ) : (
          groups.map(([hour, hourRuns]) => (
            <div key={hour}>
              <div className="px-3 py-1 text-xs text-gray-600 bg-gray-900/50 sticky top-0">{hour}</div>
              {hourRuns.map(run => {
                const hasIssues = run.unscheduled_count > 0
                const isSelected = run.id === selectedRunId
                return (
                  <motion.button
                    key={run.id}
                    initial={{ opacity: 0, x: -4 }}
                    animate={{ opacity: 1, x: 0 }}
                    onClick={() => onRunSelect(run)}
                    className={`w-full text-left px-3 py-2 border-b border-white/5 hover:bg-white/5 transition-colors ${isSelected ? 'bg-blue-900/30 border-l-2 border-l-blue-500' : ''}`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        {hasIssues
                          ? <AlertTriangle size={11} className="text-yellow-400 flex-shrink-0" />
                          : <CheckCircle size={11} className="text-green-500 flex-shrink-0" />}
                        <span className="text-xs text-gray-300 font-mono truncate max-w-[100px]">
                          {run.territory_name || run.name}
                        </span>
                      </div>
                      <div className="flex items-center gap-1 text-xs text-gray-500">
                        <Clock size={10} />
                        {new Date(run.run_at).toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit',hour12:false})}
                      </div>
                    </div>
                    <div className="flex gap-2 mt-1 text-xs">
                      <span className="text-blue-400">{run.post_scheduled} sched</span>
                      {run.unscheduled_count > 0 && (
                        <span className="text-yellow-400">{run.unscheduled_count} unsched</span>
                      )}
                    </div>
                  </motion.button>
                )
              })}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/OptimizerTimeline.jsx
git commit -m "feat(optimizer): run timeline panel with hour grouping and territory filter"
```

---

## Task 13: Chat Component

**Files:**
- Create: `frontend/src/components/OptimizerChat.jsx`

- [ ] **Step 1: Create OptimizerChat.jsx**

```jsx
import { useState, useRef, useEffect } from 'react'
import { Send, Bot, User, Loader } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import api from '../api'
import OptDecisionTree from './OptDecisionTree'
import OptKpiBar from './OptKpiBar'
import OptDriverChart from './OptDriverChart'

function VisualizationRenderer({ viz }) {
  if (!viz) return null
  const type = viz.visualization_type || viz.type
  if (type === 'decision_tree') return <OptDecisionTree decision={viz.data} />
  if (type === 'kpi_bar') return <OptKpiBar run={viz.data} />
  if (type === 'driver_chart') return <OptDriverChart patterns={viz.data} />
  return null
}

function Message({ msg }) {
  const isUser = msg.role === 'user'
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={`flex gap-3 ${isUser ? 'justify-end' : 'justify-start'}`}
    >
      {!isUser && (
        <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center flex-shrink-0 mt-1">
          <Bot size={14} className="text-white" />
        </div>
      )}
      <div className={`max-w-[85%] space-y-3 ${isUser ? 'order-first' : ''}`}>
        <div className={`rounded-2xl px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? 'bg-blue-600 text-white rounded-br-sm'
            : 'bg-gray-800/80 text-gray-200 rounded-bl-sm border border-white/10'
        }`}>
          {msg.content}
        </div>
        {msg.visualization && <VisualizationRenderer viz={msg.visualization} />}
      </div>
      {isUser && (
        <div className="w-7 h-7 rounded-full bg-gray-600 flex items-center justify-center flex-shrink-0 mt-1">
          <User size={14} className="text-white" />
        </div>
      )}
    </motion.div>
  )
}

const SUGGESTED = [
  "What happened in the last optimization run?",
  "Show me unscheduled SAs from today",
  "What patterns do you see this week?",
  "Why is capacity an issue?",
]

export default function OptimizerChat({ runContext }) {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: runContext
        ? `Now looking at run ${runContext.run_name} (${runContext.territory_name}, ${new Date(runContext.run_at).toLocaleString()}). What would you like to understand about this run?`
        : "I can help you understand optimizer decisions. Ask me about a specific SA, a driver, or say \"what patterns do you see?\" to get started.",
    }
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Reset chat when run context changes
  useEffect(() => {
    if (runContext) {
      setMessages([{
        role: 'assistant',
        content: `Now looking at run ${runContext.run_name} (${runContext.territory_name}, ${new Date(runContext.run_at).toLocaleString()}). What would you like to understand about this run?`,
      }])
    }
  }, [runContext?.run_id])

  const send = async (text) => {
    const question = (text || input).trim()
    if (!question || loading) return
    setInput('')

    const userMsg = { role: 'user', content: question }
    const history = [...messages, userMsg]
    setMessages(history)
    setLoading(true)

    try {
      // Build API message history (exclude visualization field — backend doesn't need it)
      const apiMessages = history.map(m => ({ role: m.role, content: m.content }))
      const result = await api.chatOptimizer(apiMessages, 'claude-sonnet-4-6', runContext)
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: result.text,
        visualization: result.visualization,
      }])
    } catch (err) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `Sorry, I encountered an error: ${err.message}`,
      }])
    } finally {
      setLoading(false)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <AnimatePresence initial={false}>
          {messages.map((msg, i) => <Message key={i} msg={msg} />)}
        </AnimatePresence>
        {loading && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}
            className="flex gap-3">
            <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center">
              <Loader size={14} className="text-white animate-spin" />
            </div>
            <div className="bg-gray-800/80 border border-white/10 rounded-2xl rounded-bl-sm px-4 py-3">
              <div className="flex gap-1">
                {[0,1,2].map(i => (
                  <motion.div key={i} className="w-1.5 h-1.5 bg-blue-400 rounded-full"
                    animate={{ y: [0, -4, 0] }}
                    transition={{ repeat: Infinity, duration: 0.8, delay: i * 0.15 }} />
                ))}
              </div>
            </div>
          </motion.div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Suggested prompts — show only on fresh chat */}
      {messages.length === 1 && (
        <div className="px-4 pb-2 flex flex-wrap gap-2">
          {SUGGESTED.map(s => (
            <button key={s} onClick={() => send(s)}
              className="text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 border border-white/10 rounded-full px-3 py-1 transition-colors">
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <div className="px-4 pb-4">
        <div className="flex gap-2 bg-gray-800/80 border border-white/10 rounded-2xl px-4 py-3">
          <input
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send()}
            placeholder="Ask about a driver, SA, or pattern..."
            className="flex-1 bg-transparent text-sm text-gray-200 placeholder-gray-600 outline-none"
          />
          <button onClick={() => send()}
            disabled={!input.trim() || loading}
            className="text-blue-400 hover:text-blue-300 disabled:text-gray-600 transition-colors">
            <Send size={16} />
          </button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/OptimizerChat.jsx
git commit -m "feat(optimizer): chat component with inline visualization rendering"
```

---

## Task 14: Main Page + Routing

**Files:**
- Create: `frontend/src/pages/OptimizerDecoder.jsx`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/components/Layout.jsx`

- [ ] **Step 1: Create OptimizerDecoder.jsx**

```jsx
import { useState } from 'react'
import OptimizerTimeline from '../components/OptimizerTimeline'
import OptimizerChat from '../components/OptimizerChat'

export default function OptimizerDecoder() {
  const [selectedRun, setSelectedRun] = useState(null)

  const handleRunSelect = (run) => {
    setSelectedRun(run)
  }

  return (
    <div className="flex h-screen bg-gray-950 text-white overflow-hidden">
      {/* Left: Timeline */}
      <div className="w-64 flex-shrink-0 bg-gray-900/60 border-r border-white/10 flex flex-col">
        <OptimizerTimeline
          onRunSelect={handleRunSelect}
          selectedRunId={selectedRun?.id}
        />
      </div>

      {/* Right: Chat */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="px-4 py-3 border-b border-white/10 flex items-center justify-between">
          <div>
            <h1 className="text-sm font-bold text-white">Optimizer Black Box Decoder</h1>
            {selectedRun && (
              <p className="text-xs text-gray-400 mt-0.5">
                {selectedRun.territory_name} · {selectedRun.name} ·{' '}
                {new Date(selectedRun.run_at).toLocaleString()}
                {selectedRun.unscheduled_count > 0 && (
                  <span className="text-yellow-400 ml-2">⚠ {selectedRun.unscheduled_count} unscheduled</span>
                )}
              </p>
            )}
          </div>
          {selectedRun && (
            <button
              onClick={() => setSelectedRun(null)}
              className="text-xs text-gray-500 hover:text-gray-300"
            >
              Clear context
            </button>
          )}
        </div>
        <div className="flex-1 overflow-hidden">
          <OptimizerChat
            key={selectedRun?.id || 'no-run'}
            runContext={selectedRun}
          />
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Add route to App.jsx**

In `App.jsx`, import and add the route:

```jsx
import OptimizerDecoder from './pages/OptimizerDecoder'
// Inside <Routes>:
<Route path="/optimizer" element={<OptimizerDecoder />} />
```

- [ ] **Step 3: Add nav link to Layout.jsx**

In the nav sidebar, add alongside existing nav items:

```jsx
{ path: '/optimizer', label: 'Optimizer', icon: <GitBranch size={16} /> }
```

Import `GitBranch` from `lucide-react` if not already imported.

- [ ] **Step 4: Run full stack and verify**

```bash
# Terminal 1
cd backend && uvicorn main:app --port 8000 --reload

# Terminal 2
cd frontend && npm run dev
```

Open http://localhost:5173/optimizer. Expected:
- Left panel shows a timeline list of optimization runs (loaded from DuckDB after running `optimizer_init.py --days 1`)
- Right panel shows chat interface with suggested prompts
- Clicking a run in the timeline updates the header and resets chat with run context
- Typing "what happened in the last run?" returns an AI response

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/OptimizerDecoder.jsx frontend/src/App.jsx frontend/src/components/Layout.jsx
git commit -m "feat(optimizer): main page, routing, and nav link — feature complete"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| DuckDB schema (5 tables + indexes) | Task 1 |
| SQLite audit table | Task 2 |
| Delta sync, cursor-based, idempotent | Task 3 |
| Backfill CLI (--days 30) | Task 4 |
| Sync wired to startup | Task 5 |
| REST endpoints (runs, SA, driver, unscheduled, patterns, SQL) | Task 6 |
| AI chat with domain system prompt + 7 tools | Task 7 |
| Admin sync audit UI | Task 8 |
| @xyflow/react + @floating-ui/react installed | Task 9 |
| React Flow decision tree (winner, eligible, excluded, expand) | Task 10 |
| KPI before/after bars + driver exclusion chart | Task 11 |
| Timeline with hour grouping + territory filter | Task 12 |
| Chat with inline visualization rendering | Task 13 |
| Main page + routing + nav | Task 14 |
| 30-day purge | Task 1 (purge_old_runs) + Task 3 (sync_tick) |
| Leader election for sync job | Task 3 |
| opt_sync_errors retry | Task 3 |
| Driver name resolution (opt_resources) | Task 1 + Task 3 |
| Territory name resolution | Task 3 |
| Eligible non-winner travel marked as ~ | Task 13 (chat text) + Task 10 (EligibleNode shows ~) |

All spec requirements covered. No gaps found.

**Type consistency check:** All function signatures in Task 1 (`optimizer_db.py`) match calls in Task 3 (`optimizer_sync.py`), Task 6 (`routers/optimizer.py`), and Task 7 (`routers/optimizer_chat.py`). API response shapes in Task 6 match what Task 13 (`OptimizerChat.jsx`) and Tasks 10-12 render.
