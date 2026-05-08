# SQLite → PostgreSQL Migration — Implementation Plan (v2.0.0)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace SQLite (`fslapp.db`) as the primary data store with the existing Azure PostgreSQL database (`fslapp-pg`), eliminating the corruption risk that took the app down.

**Architecture:** `database.py` gains a `USE_POSTGRES=true` feature flag that delegates every public function to a new `database_pg.py`. Zero changes to callers (users.py, routers, main.py). Cache table stays in SQLite (high-frequency, ephemeral). All other tables move to the `core` Postgres schema. Tested locally first, then deployed with env var flip.

**Tech Stack:** FastAPI · psycopg 3 · psycopg-pool · Azure PostgreSQL Flexible Server · Entra ID token auth (existing `pg_pool.py`) · pytest

---

## Table → Schema Mapping

| SQLite table | Postgres schema.table | Notes |
|---|---|---|
| `users` | `core.users` | Primary auth store |
| `settings` | `core.settings` | API keys, preferences |
| `bonus_tiers` | `core.bonus_tiers` | Configurable contractor bonus rules |
| `accounting_rates` | `core.accounting_rates` | Audit thresholds, included miles |
| `woa_reviews` | `core.woa_reviews` | WOA review decisions |
| `watchlist_manual` | `core.watchlist_manual` | SA watchlist |
| `activity_log` | `core.activity_log` | Request audit trail |
| `opt_sync_audit` | `core.opt_sync_audit` | Optimizer blob sync audit |
| `cache` | **SQLite only** | Stays in SQLite — high-frequency, ephemeral |

## File Map

| File | Action | Responsibility |
|---|---|---|
| `infra/postgres/init-schema.sql` | Modify | Add `core.activity_log` + `core.opt_sync_audit` tables |
| `backend/database_pg.py` | **Create** | Full Postgres implementation of every `database.py` public function |
| `backend/database.py` | Modify | Add `USE_POSTGRES` flag; delegate to `database_pg` when enabled |
| `backend/migrations/sqlite_to_core.py` | Modify | Add `activity_log` + `opt_sync_audit` to migration |
| `backend/main.py` | Modify | Bump version to 2.0.0 |
| `frontend/package.json` | Modify | Bump version to 2.0.0 |
| `tests/test_database_pg.py` | **Create** | Integration tests against live Postgres (local) |

---

## Task 1: Extend Postgres Core Schema

Add `activity_log` and `opt_sync_audit` to `infra/postgres/init-schema.sql` (in the Phase 2 core section, before the grants block).

**File:** `infra/postgres/init-schema.sql`

- [ ] **Step 1.1: Add the two missing tables**

In `init-schema.sql`, after the `watchlist_manual` table and before the `GRANT` lines, add:

```sql
CREATE TABLE IF NOT EXISTS activity_log (
  id          SERIAL PRIMARY KEY,
  timestamp   TIMESTAMPTZ DEFAULT now(),
  username    TEXT,
  action      TEXT NOT NULL,
  endpoint    TEXT,
  method      TEXT DEFAULT 'GET',
  status_code INTEGER,
  duration_ms DOUBLE PRECISION,
  ip          TEXT,
  user_agent  TEXT,
  detail      TEXT
);
CREATE INDEX IF NOT EXISTS idx_al_timestamp ON activity_log USING BRIN (timestamp);
CREATE INDEX IF NOT EXISTS idx_al_username  ON activity_log (username) WHERE username IS NOT NULL;

CREATE TABLE IF NOT EXISTS opt_sync_audit (
  id                SERIAL PRIMARY KEY,
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

- [ ] **Step 1.2: Apply schema to production Postgres**

```bash
TOKEN=$(az account get-access-token --resource https://ossrdbms-aad.database.windows.net --query accessToken -o tsv)
PGPASSWORD="$TOKEN" psql \
  "host=fslapp-pg.postgres.database.azure.com dbname=fslapp user=nlaaroubi@nyaaa.com sslmode=require" \
  -f infra/postgres/init-schema.sql 2>&1 | tail -20
```

Expected: No errors. `activity_log` and `opt_sync_audit` appear in `core` tables list.

- [ ] **Step 1.3: Commit**

```bash
git add infra/postgres/init-schema.sql
git commit -m "feat(pg): add core.activity_log + core.opt_sync_audit tables"
```

---

## Task 2: Extend Migration Script and Run It

**File:** `backend/migrations/sqlite_to_core.py`

- [ ] **Step 2.1: Add activity_log and opt_sync_audit to _TABLES list**

```python
_TABLES = ['users', 'settings', 'bonus_tiers', 'accounting_rates',
           'woa_reviews', 'watchlist_manual', 'activity_log', 'opt_sync_audit']
```

- [ ] **Step 2.2: Run the migration against production**

```bash
cd FSLAPP/backend
AZ_OPT_CONNECTION_STRING="<value from Azure Portal>" \
AZ_OPT_CONTAINER="optimizer-files" \
python -m migrations.sqlite_to_core
```

Expected output:
```
INFO sqlite_to_core: Downloading backup: db-backups/fslapp_YYYYMMDD_HHMMSS.json
INFO sqlite_to_core: users: N rows attempted
INFO sqlite_to_core: settings: N rows attempted
INFO sqlite_to_core: bonus_tiers: N rows attempted
INFO sqlite_to_core: accounting_rates: N rows attempted
INFO sqlite_to_core: woa_reviews: N rows attempted
INFO sqlite_to_core: watchlist_manual: N rows attempted
INFO sqlite_to_core: activity_log: N rows attempted
INFO sqlite_to_core: opt_sync_audit: N rows attempted
INFO sqlite_to_core: === Migration complete ===
```

- [ ] **Step 2.3: Verify in Postgres**

```bash
TOKEN=$(az account get-access-token --resource https://ossrdbms-aad.database.windows.net --query accessToken -o tsv)
PGPASSWORD="$TOKEN" psql \
  "host=fslapp-pg.postgres.database.azure.com dbname=fslapp user=nlaaroubi@nyaaa.com sslmode=require" \
  -c "SET search_path=core; SELECT 'users' t, count(*) FROM users UNION ALL SELECT 'settings', count(*) FROM settings UNION ALL SELECT 'bonus_tiers', count(*) FROM bonus_tiers;"
```

Expected: all counts match the SQLite values.

- [ ] **Step 2.4: Commit**

```bash
git add backend/migrations/sqlite_to_core.py
git commit -m "feat(migration): include activity_log + opt_sync_audit in sqlite_to_core"
```

---

## Task 3: Create `database_pg.py`

This is the core of the migration. It mirrors every public function in `database.py` but uses `pg_pool` for connections and targets the `core` Postgres schema. The `get_db()` context manager returns a raw `psycopg` connection (not wrapped) so `users.py` raw SQL continues to work.

**File:** `backend/database_pg.py` *(create new)*

- [ ] **Step 3.1: Write the file**

```python
"""PostgreSQL implementation of the database module.

Drop-in replacement for database.py — identical public API, Postgres backend.
Activated when USE_POSTGRES=true env var is set.

Tables live in the `core` schema on fslapp-pg.postgres.database.azure.com.
Cache table is NOT moved to Postgres — it stays in SQLite (ephemeral/high-freq).
"""

import json
import logging
import os
import time
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

import pg_pool

log = logging.getLogger('database_pg')


@contextmanager
def get_db():
    """Context manager that yields a raw psycopg connection in core schema.

    Mirrors database.get_db() so callers (users.py, etc.) work unchanged.
    Uses the writer pool so DML is allowed.
    """
    with pg_pool.writer() as conn:
        # Ensure search_path = core for every call
        with conn.cursor() as cur:
            cur.execute("SET search_path = core, public")
        yield conn


def init_db():
    """No-op in Postgres mode — schema managed by init-schema.sql."""
    log.info("Postgres mode: init_db() skipped (schema managed externally)")


def migrate_settings_json():
    """No-op in Postgres mode."""
    pass


# ── Settings ──────────────────────────────────────────────────────────────────

def get_setting(key: str, default=None):
    with get_db() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = %s", (key,)
        ).fetchone()
        if row:
            try:
                return json.loads(row[0])
            except (json.JSONDecodeError, TypeError):
                return row[0]
    return default


def put_setting(key: str, value):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO settings (key, value, updated_at)
               VALUES (%s, %s, now())
               ON CONFLICT (key) DO UPDATE
               SET value = EXCLUDED.value, updated_at = now()""",
            (key, json.dumps(value)),
        )
        conn.commit()


def get_all_settings() -> dict:
    with get_db() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    result = {}
    for key, val in rows:
        try:
            result[key] = json.loads(val)
        except (json.JSONDecodeError, TypeError):
            result[key] = val
    return result


def delete_setting(key: str):
    with get_db() as conn:
        conn.execute("DELETE FROM settings WHERE key = %s", (key,))
        conn.commit()


# ── Cache — stays in SQLite; these are passthroughs so imports don't break ────

def cache_get(key: str):
    import database as _sqlite
    return _sqlite._sqlite_cache_get(key)


def cache_get_stale(key: str):
    import database as _sqlite
    return _sqlite._sqlite_cache_get_stale(key)


def cache_put(key: str, data, ttl: int = 300):
    import database as _sqlite
    return _sqlite._sqlite_cache_put(key, data, ttl)


def cache_get_meta(key: str) -> dict:
    import database as _sqlite
    return _sqlite._sqlite_cache_get_meta(key)


def cache_delete(key: str):
    import database as _sqlite
    return _sqlite._sqlite_cache_delete(key)


def cache_delete_prefix(prefix: str) -> int:
    import database as _sqlite
    return _sqlite._sqlite_cache_delete_prefix(prefix)


def cache_cleanup():
    import database as _sqlite
    return _sqlite._sqlite_cache_cleanup()


def cache_stats() -> dict:
    import database as _sqlite
    return _sqlite._sqlite_cache_stats()


# ── Bonus Tiers ───────────────────────────────────────────────────────────────

def get_bonus_tiers() -> list:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, min_pct, bonus_per_sa, label, sort_order "
            "FROM bonus_tiers ORDER BY min_pct DESC"
        ).fetchall()
    return [{'id': r[0], 'min_pct': r[1], 'bonus_per_sa': r[2],
             'label': r[3], 'sort_order': r[4]} for r in rows]


def set_bonus_tiers(tiers: list):
    with get_db() as conn:
        conn.execute("DELETE FROM bonus_tiers")
        for i, t in enumerate(tiers):
            conn.execute(
                "INSERT INTO bonus_tiers (min_pct, bonus_per_sa, label, sort_order) "
                "VALUES (%s, %s, %s, %s)",
                (t['min_pct'], t['bonus_per_sa'],
                 t.get('label', f"≥{t['min_pct']}%"), i),
            )
        conn.commit()


def bonus_for_pct(pct) -> tuple:
    if pct is None:
        return 0, 'N/A'
    tiers = get_bonus_tiers()
    for t in tiers:
        if pct >= t['min_pct']:
            return t['bonus_per_sa'], t['label']
    lowest = tiers[-1]['min_pct'] if tiers else 92
    return 0, f'<{lowest}%'


# ── Accounting Rates ──────────────────────────────────────────────────────────

def get_accounting_rates() -> list:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT code, label, value, unit, notes, category, updated_at "
            "FROM accounting_rates ORDER BY category, code"
        ).fetchall()
    cols = ['code', 'label', 'value', 'unit', 'notes', 'category', 'updated_at']
    return [dict(zip(cols, r)) for r in rows]


def get_accounting_rates_dict() -> dict:
    with get_db() as conn:
        rows = conn.execute("SELECT code, value FROM accounting_rates").fetchall()
    return {r[0]: r[1] for r in rows}


def set_accounting_rate(code: str, value: float) -> dict:
    with get_db() as conn:
        conn.execute(
            "UPDATE accounting_rates SET value = %s, updated_at = now() WHERE code = %s",
            (value, code),
        )
        row = conn.execute(
            "SELECT code, label, value, unit, notes, category, updated_at "
            "FROM accounting_rates WHERE code = %s", (code,)
        ).fetchone()
        conn.commit()
    if not row:
        raise ValueError(f"Unknown accounting rate code: {code}")
    cols = ['code', 'label', 'value', 'unit', 'notes', 'category', 'updated_at']
    return dict(zip(cols, row))


# ── Watchlist ─────────────────────────────────────────────────────────────────

def watchlist_add(sa_number: str, sa_id: str = '', added_by: str = ''):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO watchlist_manual (sa_number, sa_id, added_by) "
            "VALUES (%s, %s, %s) ON CONFLICT (sa_number) DO UPDATE "
            "SET sa_id = EXCLUDED.sa_id, added_by = EXCLUDED.added_by",
            (sa_number, sa_id, added_by),
        )
        conn.commit()


def watchlist_remove(sa_number: str):
    with get_db() as conn:
        conn.execute("DELETE FROM watchlist_manual WHERE sa_number = %s", (sa_number,))
        conn.commit()


def watchlist_list() -> list:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT sa_number, sa_id, added_by, added_at "
            "FROM watchlist_manual ORDER BY added_at DESC"
        ).fetchall()
    cols = ['sa_number', 'sa_id', 'added_by', 'added_at']
    return [dict(zip(cols, r)) for r in rows]


def watchlist_has(sa_number: str) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM watchlist_manual WHERE sa_number = %s", (sa_number,)
        ).fetchone()
    return row is not None


# ── Activity Log ──────────────────────────────────────────────────────────────

def log_activity(user: str = None, action: str = '', endpoint: str = None,
                 method: str = 'GET', status_code: int = None, duration_ms: float = None,
                 ip: str = None, user_agent: str = None, detail: str = None):
    try:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO activity_log
                   (username, action, endpoint, method, status_code,
                    duration_ms, ip, user_agent, detail)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (user, action, endpoint, method, status_code,
                 duration_ms, ip, user_agent, detail),
            )
            conn.commit()
    except Exception:
        pass  # never crash the request for logging


def get_activity_log(limit: int = 100, user: str = None, action: str = None) -> list:
    parts = ["SELECT id, timestamp, username, action, endpoint, method, "
             "status_code, duration_ms, ip, user_agent, detail "
             "FROM activity_log WHERE 1=1"]
    params: list = []
    if user:
        parts.append("AND username = %s"); params.append(user)
    if action:
        parts.append("AND action ILIKE %s"); params.append(f"%{action}%")
    parts.append("ORDER BY timestamp DESC LIMIT %s"); params.append(limit)
    with get_db() as conn:
        rows = conn.execute(" ".join(parts), params).fetchall()
    cols = ['id','timestamp','user','action','endpoint','method',
            'status_code','duration_ms','ip','user_agent','detail']
    return [dict(zip(cols, r)) for r in rows]


def get_activity_stats() -> dict:
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0]
        today = conn.execute(
            "SELECT COUNT(*) FROM activity_log WHERE timestamp >= now() - INTERVAL '1 day'"
        ).fetchone()[0]
        users = conn.execute(
            "SELECT COUNT(DISTINCT username) FROM activity_log WHERE username IS NOT NULL"
        ).fetchone()[0]
        slow = conn.execute(
            "SELECT COUNT(*) FROM activity_log WHERE duration_ms > 5000"
        ).fetchone()[0]
    return {'total_entries': total, 'last_24h': today, 'unique_users': users, 'slow_queries': slow}


# ── WOA Reviews ───────────────────────────────────────────────────────────────

def get_woa_review(woa_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT woa_id, status, note, reviewer, reviewed_at "
            "FROM woa_reviews WHERE woa_id = %s", (woa_id,)
        ).fetchone()
    if not row:
        return None
    return dict(zip(['woa_id','status','note','reviewer','reviewed_at'], row))


def set_woa_review(woa_id: str, status: str, note: str = '', reviewer: str = '') -> dict:
    with get_db() as conn:
        conn.execute(
            """INSERT INTO woa_reviews (woa_id, status, note, reviewer, reviewed_at)
               VALUES (%s,%s,%s,%s, now())
               ON CONFLICT (woa_id) DO UPDATE
               SET status=EXCLUDED.status, note=EXCLUDED.note,
                   reviewer=EXCLUDED.reviewer, reviewed_at=now()""",
            (woa_id, status, note or '', reviewer or ''),
        )
        conn.commit()
    return {'woa_id': woa_id, 'status': status, 'note': note, 'reviewer': reviewer}


def get_woa_reviews_batch(woa_ids: list) -> dict:
    if not woa_ids:
        return {}
    placeholders = ','.join(['%s'] * len(woa_ids))
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT woa_id, status, note, reviewer, reviewed_at "
            f"FROM woa_reviews WHERE woa_id IN ({placeholders})", woa_ids
        ).fetchall()
    cols = ['woa_id','status','note','reviewer','reviewed_at']
    return {r[0]: dict(zip(cols, r)) for r in rows}


# ── Optimizer Sync Audit ──────────────────────────────────────────────────────

def write_sync_audit(started_at, finished_at, status, runs_found=0,
                     runs_inserted=0, runs_skipped=0, runs_failed=0,
                     verdicts_inserted=0, rows_purged=0,
                     error_detail=None, duration_ms=0):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO opt_sync_audit
               (started_at, finished_at, status, runs_found, runs_inserted,
                runs_skipped, runs_failed, verdicts_inserted, rows_purged,
                error_detail, duration_ms)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (started_at, finished_at, status, runs_found, runs_inserted,
             runs_skipped, runs_failed, verdicts_inserted, rows_purged,
             error_detail, duration_ms),
        )
        conn.commit()


def get_sync_audit(limit: int = 50) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, started_at, finished_at, status, runs_found,
                      runs_inserted, runs_skipped, runs_failed,
                      verdicts_inserted, rows_purged, error_detail, duration_ms
               FROM opt_sync_audit ORDER BY id DESC LIMIT %s""",
            (limit,)
        ).fetchall()
    cols = ['id','started_at','finished_at','status','runs_found','runs_inserted',
            'runs_skipped','runs_failed','verdicts_inserted','rows_purged',
            'error_detail','duration_ms']
    return [dict(zip(cols, r)) for r in rows]
```

- [ ] **Step 3.2: Commit**

```bash
git add backend/database_pg.py
git commit -m "feat(pg): add database_pg.py — Postgres implementation of database module"
```

---

## Task 4: Rename SQLite Cache Functions and Add `USE_POSTGRES` Flag to `database.py`

The cache functions need to be exposed as `_sqlite_cache_*` so `database_pg.py` can call through to them.

**File:** `backend/database.py`

- [ ] **Step 4.1: Add `_sqlite_` aliases for cache functions at bottom of file**

After all existing cache functions, add:

```python
# Aliases so database_pg.py can call SQLite cache directly
_sqlite_cache_get        = cache_get
_sqlite_cache_get_stale  = cache_get_stale
_sqlite_cache_put        = cache_put
_sqlite_cache_get_meta   = cache_get_meta
_sqlite_cache_delete     = cache_delete
_sqlite_cache_delete_prefix = cache_delete_prefix
_sqlite_cache_cleanup    = cache_cleanup
_sqlite_cache_stats      = cache_stats
```

- [ ] **Step 4.2: Add `USE_POSTGRES` delegation block at very bottom of `database.py`**

```python
# ── Postgres delegation ───────────────────────────────────────────────────────
# When USE_POSTGRES=true, replace all public functions with Postgres versions.
# Cache functions are excluded — they stay in SQLite regardless.
if os.environ.get('USE_POSTGRES', '').lower() in ('1', 'true', 'yes'):
    import database_pg as _pg
    init_db              = _pg.init_db
    migrate_settings_json = _pg.migrate_settings_json
    get_db               = _pg.get_db
    get_setting          = _pg.get_setting
    put_setting          = _pg.put_setting
    get_all_settings     = _pg.get_all_settings
    delete_setting       = _pg.delete_setting
    get_bonus_tiers      = _pg.get_bonus_tiers
    set_bonus_tiers      = _pg.set_bonus_tiers
    bonus_for_pct        = _pg.bonus_for_pct
    get_accounting_rates = _pg.get_accounting_rates
    get_accounting_rates_dict = _pg.get_accounting_rates_dict
    set_accounting_rate  = _pg.set_accounting_rate
    watchlist_add        = _pg.watchlist_add
    watchlist_remove     = _pg.watchlist_remove
    watchlist_list       = _pg.watchlist_list
    watchlist_has        = _pg.watchlist_has
    log_activity         = _pg.log_activity
    get_activity_log     = _pg.get_activity_log
    get_activity_stats   = _pg.get_activity_stats
    get_woa_review       = _pg.get_woa_review
    set_woa_review       = _pg.set_woa_review
    get_woa_reviews_batch = _pg.get_woa_reviews_batch
    write_sync_audit     = _pg.write_sync_audit
    get_sync_audit       = _pg.get_sync_audit
    import logging as _log
    _log.getLogger('database').info("USE_POSTGRES=true — delegating to database_pg")
```

- [ ] **Step 4.3: Commit**

```bash
git add backend/database.py
git commit -m "feat(pg): add USE_POSTGRES flag to database.py — delegates to database_pg"
```

---

## Task 5: Integration Tests

**File:** `tests/test_database_pg.py` *(create new)*

These tests run against a real Postgres connection (same production DB). Run locally with `USE_POSTGRES=true`.

- [ ] **Step 5.1: Write the test file**

```python
"""Integration tests for database_pg.py.

Run with:
    USE_POSTGRES=true pytest tests/test_database_pg.py -v

Requires az login and AZ_OPT_CONNECTION_STRING in env.
"""

import os
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get('USE_POSTGRES', '').lower() not in ('1', 'true', 'yes'),
    reason="Set USE_POSTGRES=true to run Postgres integration tests"
)

import database  # picks up Postgres delegation when USE_POSTGRES=true


# ── Settings ──────────────────────────────────────────────────────────────────

def test_put_and_get_setting():
    database.put_setting('_test_key', {'hello': 'world'})
    result = database.get_setting('_test_key')
    assert result == {'hello': 'world'}
    database.delete_setting('_test_key')
    assert database.get_setting('_test_key') is None


def test_get_all_settings_returns_dict():
    database.put_setting('_test_a', 'val_a')
    all_s = database.get_all_settings()
    assert isinstance(all_s, dict)
    assert all_s.get('_test_a') == 'val_a'
    database.delete_setting('_test_a')


# ── Bonus Tiers ───────────────────────────────────────────────────────────────

def test_bonus_tiers_roundtrip():
    original = database.get_bonus_tiers()
    test_tiers = [
        {'min_pct': 99, 'bonus_per_sa': 5.0, 'label': '≥99%'},
        {'min_pct': 95, 'bonus_per_sa': 2.0, 'label': '≥95%'},
    ]
    database.set_bonus_tiers(test_tiers)
    result = database.get_bonus_tiers()
    assert len(result) == 2
    assert result[0]['min_pct'] == 99
    # Restore original
    database.set_bonus_tiers(original)


def test_bonus_for_pct():
    tiers = database.get_bonus_tiers()
    if not tiers:
        pytest.skip("No bonus tiers configured")
    top = tiers[0]
    bonus, label = database.bonus_for_pct(top['min_pct'])
    assert bonus == top['bonus_per_sa']


# ── Watchlist ─────────────────────────────────────────────────────────────────

def test_watchlist_crud():
    database.watchlist_add('TEST-0001', 'sa_id_test', 'pytest')
    assert database.watchlist_has('TEST-0001') is True
    items = database.watchlist_list()
    assert any(i['sa_number'] == 'TEST-0001' for i in items)
    database.watchlist_remove('TEST-0001')
    assert database.watchlist_has('TEST-0001') is False


# ── WOA Reviews ───────────────────────────────────────────────────────────────

def test_woa_review_crud():
    database.set_woa_review('WOA-TEST-001', 'approved', 'looks good', 'pytest')
    result = database.get_woa_review('WOA-TEST-001')
    assert result is not None
    assert result['status'] == 'approved'
    batch = database.get_woa_reviews_batch(['WOA-TEST-001', 'WOA-NONEXISTENT'])
    assert 'WOA-TEST-001' in batch
    assert 'WOA-NONEXISTENT' not in batch


# ── Activity Log ──────────────────────────────────────────────────────────────

def test_log_activity_and_stats():
    database.log_activity(user='pytest', action='test_action', endpoint='/test',
                          method='GET', status_code=200, duration_ms=42.0)
    stats = database.get_activity_stats()
    assert stats['total_entries'] > 0
    logs = database.get_activity_log(limit=5, user='pytest')
    assert any(l['action'] == 'test_action' for l in logs)


# ── Accounting Rates ──────────────────────────────────────────────────────────

def test_accounting_rates_readable():
    rates = database.get_accounting_rates()
    assert len(rates) > 0
    rate_dict = database.get_accounting_rates_dict()
    assert 'er_rate_per_mile' in rate_dict
```

- [ ] **Step 5.2: Run the tests**

```bash
cd FSLAPP/backend
USE_POSTGRES=true pytest tests/test_database_pg.py -v
```

Expected: all tests pass. Fix any failures before proceeding.

- [ ] **Step 5.3: Commit**

```bash
git add tests/test_database_pg.py
git commit -m "test(pg): integration tests for database_pg.py"
```

---

## Task 6: Local Smoke Test — Full App with Postgres

- [ ] **Step 6.1: Start the backend with Postgres enabled**

```bash
cd FSLAPP/backend
USE_POSTGRES=true uvicorn main:app --port 8000 --reload
```

Watch startup logs. Expected:
```
INFO database: USE_POSTGRES=true — delegating to database_pg
INFO database_pg: Postgres mode: init_db() skipped
INFO uvicorn: Application startup complete.
```

No errors.

- [ ] **Step 6.2: Verify login works**

```bash
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"nlaaroubi@nyaaa.com","password":"Hh%9hXrL"}' | python3 -m json.tool
```

Expected: JSON with `token` field, no errors.

- [ ] **Step 6.3: Verify settings endpoint**

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"nlaaroubi@nyaaa.com","password":"Hh%9hXrL"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/admin/settings | python3 -m json.tool
```

Expected: settings JSON. No errors.

- [ ] **Step 6.4: Verify watchlist endpoint**

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/watchlist | python3 -m json.tool
```

Expected: list (may be empty). No errors.

- [ ] **Step 6.5: Open browser and manually test**

Navigate to http://localhost:5173 (frontend dev server).

- Log in as `nlaaroubi@nyaaa.com`
- Navigate to Admin → Users: verify all 7 users are listed
- Navigate to Admin → Settings: verify API keys and config are present
- Navigate to Admin → Bonus Tiers: verify tiers load
- Navigate to SA Watchlist: verify it loads

If all pass: proceed to deploy. If any fail: fix before deploying.

---

## Task 7: Version Bump to 2.0.0

- [ ] **Step 7.1: Bump backend version**

In `backend/main.py`, line 29:
```python
app = FastAPI(title="FSL App", version="2.0.0")
```

- [ ] **Step 7.2: Bump frontend version**

In `frontend/package.json`:
```json
"version": "2.0.0",
```

- [ ] **Step 7.3: Commit**

```bash
git add backend/main.py frontend/package.json
git commit -m "chore: bump version to 2.0.0 — SQLite → Postgres migration"
```

---

## Task 8: Deploy to Azure

- [ ] **Step 8.1: Set USE_POSTGRES=true on Azure App Service**

```bash
az webapp config appsettings set \
  -g rg-nlaaroubi-sbx-eus2-001 \
  -n fslapp-nyaaa \
  --settings USE_POSTGRES=true
```

Expected: settings JSON returned with `USE_POSTGRES: true`.

- [ ] **Step 8.2: Build frontend and push**

```bash
cd FSLAPP/frontend && npm run build
cd FSLAPP && rm -rf backend/static && cp -r frontend/dist backend/static
git add backend/ frontend/package.json
git push origin main
```

- [ ] **Step 8.3: Wait for deploy and verify health**

```bash
until gh run list --repo nlaarh/FSLDashboard --limit 1 | grep -qv "in_progress"; do sleep 5; done
curl -s -o /dev/null -w "%{http_code}" https://fslapp-nyaaa.azurewebsites.net/api/health
```

Expected: `200`

- [ ] **Step 8.4: Test all 7 user logins in production**

```bash
BASE="https://fslapp-nyaaa.azurewebsites.net"
for creds in "tingraham@nyaaa.com:p@DsnF*6" "dfisher@nyaaa.com:5NjR8#8z" \
             "nlaaroubi@nyaaa.com:Hh%9hXrL" "shorn@nyaaa.com:nUC@eS3x" \
             "jnixon@nyaaa.com:Q3HFf&YC" "ksmeal@nyaaa.com:D9dUaK0YFpZqrgga" \
             "dbrown@nyaaa.com:e80XFSnoVtRGWekM"; do
  u="${creds%%:*}"; p="${creds##*:}"
  code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/auth/login" \
    -H "Content-Type: application/json" -d "{\"username\":\"$u\",\"password\":\"$p\"}")
  echo "$u: $code"
done
```

Expected: all `200`.

- [ ] **Step 8.5: Check startup logs for Postgres confirmation**

```bash
az webapp log download --name fslapp-nyaaa -g rg-nlaaroubi-sbx-eus2-001 --log-file /tmp/v2_logs.zip
unzip -o /tmp/v2_logs.zip -d /tmp/v2_logs/
grep -i "USE_POSTGRES\|database_pg\|Postgres mode" /tmp/v2_logs/LogFiles/$(ls /tmp/v2_logs/LogFiles/ | grep default_docker | sort -r | head -1)
```

Expected:
```
INFO database: USE_POSTGRES=true — delegating to database_pg
INFO database_pg: Postgres mode: init_db() skipped
```

---

## Rollback Plan

If production breaks after deploy:

```bash
# Disable Postgres, fall back to SQLite immediately
az webapp config appsettings set \
  -g rg-nlaaroubi-sbx-eus2-001 \
  -n fslapp-nyaaa \
  --settings USE_POSTGRES=false

# Azure restarts app automatically — SQLite takes over
# Verify:
curl -s -o /dev/null -w "%{http_code}" https://fslapp-nyaaa.azurewebsites.net/api/health
```

SQLite `fslapp.db` is still on `/home/fslapp/` — nothing was deleted. Data in Postgres is preserved and can be re-migrated when issue is resolved.

---

## Post-Migration Cleanup (Do After 1 Week Stable)

Once Postgres has been running stably for 1 week:

- [ ] Remove SQLite corruption-recovery code from `database.py` (`_recover_db`, `_clear_wal_files`, corruption check in `init_db`)
- [ ] Remove `db_backup.py` Azure Blob backup (Postgres has built-in Azure backup)
- [ ] Archive `~/.fslapp/fslapp.db` (don't delete — keep as archive)
- [ ] Remove `cache` table from SQLite schema and migrate to in-memory or Redis (future)
