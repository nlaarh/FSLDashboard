"""Optimizer decoder REST endpoints."""

from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request

import optimizer_db
import database
from routers.admin import _check_pin

router = APIRouter(tags=['optimizer'])


def _test_data_status() -> dict:
    """Detect whether DuckDB currently holds seed/test data vs. live SF data.

    Test data has run names starting with 'Seed-' (from optimizer_seed.py).
    Returns a banner dict to attach to every response.
    """
    try:
        with optimizer_db.get_conn(read_only=True) as conn:
            total = conn.execute("SELECT COUNT(*) FROM opt_runs").fetchone()[0]
            test = conn.execute(
                "SELECT COUNT(*) FROM opt_runs WHERE name LIKE 'Seed-%'"
            ).fetchone()[0]
        if total == 0:
            return {'is_test_data': False, 'notice': 'No optimizer data loaded yet.'}
        if test == total:
            return {
                'is_test_data': True,
                'notice': '⚠️ TEST DATA — NOT LIVE SALESFORCE DATA. '
                          'Synthetic seed (288 runs over 3 days, territory 076DO) for compile/UI verification only. '
                          'Run optimizer_sync to load real data.',
            }
        if test > 0:
            return {
                'is_test_data': True,
                'notice': f'⚠️ MIXED — {test}/{total} runs are TEST seed data. Real data also present.',
            }
        return {'is_test_data': False, 'notice': 'Live Salesforce data.'}
    except Exception:
        return {'is_test_data': False, 'notice': 'Unable to determine data status.'}


@router.get('/api/optimizer/status')
def get_status():
    """Test-data banner status. Frontend polls this to show 'PREVIEW / TEST DATA' alert."""
    return _test_data_status()


@router.get('/api/optimizer/runs')
def get_runs(
    from_dt: str = Query(None, description="ISO datetime, default 24h ago"),
    to_dt: str = Query(None, description="ISO datetime, default now"),
    territory: str = Query(None),
):
    now = datetime.now(timezone.utc)
    f = from_dt or (now - timedelta(hours=24)).isoformat()
    t = to_dt or now.isoformat()
    return optimizer_db.list_runs(f, t, territory)


@router.get('/api/optimizer/runs/{run_id}')
def get_run(run_id: str):
    result = optimizer_db.get_run_detail(run_id)
    if not result:
        raise HTTPException(404, f"Run {run_id} not found")
    return result


@router.get('/api/optimizer/sa/{sa_number}')
def get_sa(sa_number: str, limit: int = Query(5, le=20)):
    return optimizer_db.get_sa_decision(sa_number, limit)


@router.get('/api/optimizer/driver/{driver_name}')
def get_driver(driver_name: str, days: int = Query(7, le=30)):
    return optimizer_db.get_driver_analysis(driver_name, days)


@router.get('/api/optimizer/runs/{run_id}/unscheduled')
def get_unscheduled(run_id: str):
    return optimizer_db.get_unscheduled_analysis(run_id)


@router.get('/api/optimizer/patterns')
def get_patterns(territory: str = Query(None), days: int = Query(7, le=30)):
    return optimizer_db.get_exclusion_patterns(territory, days)


@router.post('/api/optimizer/query')
def run_sql(body: dict, request: Request):
    _check_pin(request)
    sql = body.get('sql', '')
    if not sql:
        raise HTTPException(400, "sql field required")
    try:
        return optimizer_db.query_optimizer_sql(sql)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get('/api/optimizer/admin/sync-audit')
def sync_audit(limit: int = Query(50, le=200)):
    return database.get_sync_audit(limit)


@router.get('/api/optimizer/stats')
def get_stats():
    """Current DuckDB counts and date range — useful for monitoring backfill progress."""
    with optimizer_db.get_conn(read_only=True) as conn:
        runs = conn.execute("SELECT COUNT(*) FROM opt_runs").fetchone()[0]
        dates = conn.execute("SELECT MIN(run_at), MAX(run_at) FROM opt_runs").fetchone()
        decisions = conn.execute("SELECT COUNT(*) FROM opt_sa_decisions").fetchone()[0]
        verdicts = conn.execute("SELECT COUNT(*) FROM opt_driver_verdicts").fetchone()[0]
        errors = conn.execute(
            "SELECT COUNT(*) FROM opt_sync_errors WHERE retried=false"
        ).fetchone()[0]
    return {
        'runs': runs,
        'sa_decisions': decisions,
        'driver_verdicts': verdicts,
        'pending_errors': errors,
        'oldest_run': str(dates[0]) if dates and dates[0] else None,
        'newest_run': str(dates[1]) if dates and dates[1] else None,
    }


@router.post('/api/optimizer/backfill')
async def start_backfill(request: Request, background_tasks: BackgroundTasks):
    """Backfill optimizer runs for the last N days.

    Processes up to max_runs new runs per call (default 500).
    Returns immediately; backfill runs in background.
    Poll /api/optimizer/stats to track progress.
    Call again if the previous response had remaining > 0.
    """
    body = await request.json()
    days = min(int(body.get('days', 30)), 90)
    max_runs = min(int(body.get('max_runs', 500)), 2000)

    import optimizer_sync
    background_tasks.add_task(optimizer_sync.backfill, days=days, max_runs=max_runs)
    return {
        'status': 'started',
        'days': days,
        'max_runs': max_runs,
        'message': f'Backfill started for last {days} days (up to {max_runs} runs). '
                   f'Poll /api/optimizer/stats to track progress.',
    }
