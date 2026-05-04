"""Optimizer decoder REST endpoints."""

import io
import os
import zipfile
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

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
def get_sa(
    sa_number: str,
    limit: int = Query(5, le=20),
    run_id: str = Query(None, description="If provided, return only this specific run's decision"),
):
    return optimizer_db.get_sa_decision(sa_number, limit, run_id=run_id)


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


# ── Azure Blob file browser ──────────────────────────────────────────────────

def _blob_container():
    """Return Azure Blob ContainerClient. Raises if env not configured."""
    from azure.storage.blob import BlobServiceClient
    conn = os.environ.get('AZ_OPT_CONNECTION_STRING')
    if not conn:
        raise HTTPException(503, "Azure Blob not configured (AZ_OPT_CONNECTION_STRING missing)")
    container_name = os.environ.get('AZ_OPT_CONTAINER', 'optimizer-files')
    return BlobServiceClient.from_connection_string(conn).get_container_client(container_name)


@router.get('/api/optimizer/files/latest-date')
def latest_date():
    """Return the most recent date that has blobs in Azure storage."""
    container = _blob_container()
    seen = set()
    for b in container.list_blobs():
        parts = b.name.split('/')
        if len(parts) >= 1 and parts[0]:
            seen.add(parts[0])
    if not seen:
        raise HTTPException(404, "No optimizer runs found in Azure Blob")
    return {'date': sorted(seen)[-1]}


@router.get('/api/optimizer/files')
def list_files(date: str = Query(None, description="YYYY-MM-DD; default = today")):
    """List runs available in Azure Blob, enriched with batch grouping from DuckDB.

    Returns: {count, date_filter, runs:[{run_id, run_name, batch_id, chunk_num,
                                         fsl_status, run_at, blobs[], total_size}]}
    """
    container = _blob_container()
    prefix = f"{date}/" if date else ""
    runs: dict[str, dict] = {}
    for b in container.list_blobs(name_starts_with=prefix):
        parts = b.name.split('/')
        if len(parts) != 3:
            continue
        date_str, run_id, fname = parts
        slot = runs.setdefault(run_id, {
            'run_id': run_id, 'date': date_str, 'blobs': [], 'total_size': 0,
            'run_name': None, 'batch_id': None, 'chunk_num': None,
            'fsl_status': None, 'run_at': None,
        })
        slot['blobs'].append({
            'name': fname,
            'size': b.size,
            'last_modified': b.last_modified.isoformat() if b.last_modified else None,
        })
        slot['total_size'] += b.size or 0

    # Enrich with batch info from metadata.json blob — parallelized for speed.
    # Sequential 60ms × 300 runs = 18s. Parallel 16 = ~1-2s.
    import json as _json
    from concurrent.futures import ThreadPoolExecutor

    def _fetch_meta(item):
        rid, slot = item
        try:
            blob_name = f"{slot['date']}/{rid}/metadata.json"
            content = container.get_blob_client(blob_name).download_blob().readall()
            meta = _json.loads(content)
            return rid, {
                'run_name':   meta.get('run_name'),
                'batch_id':   meta.get('batch_id'),
                'chunk_num':  meta.get('chunk_num'),
                'fsl_status': meta.get('fsl_status'),
                'run_at':     meta.get('run_at'),
            }
        except Exception:
            return rid, None

    with ThreadPoolExecutor(max_workers=16) as pool:
        for rid, meta in pool.map(_fetch_meta, runs.items()):
            if meta:
                runs[rid].update(meta)

    out = sorted(runs.values(),
                 key=lambda r: (r['run_at'] or max((b['last_modified'] or '') for b in r['blobs'])),
                 reverse=True)
    return {'count': len(out), 'date_filter': date, 'runs': out}


@router.get('/api/optimizer/files/{run_id}/download')
def download_run_zip(run_id: str):
    """Download all blobs for a run as a single ZIP file."""
    container = _blob_container()
    # Find the run's date prefix by listing blobs with the run_id substring
    matched = [b for b in container.list_blobs() if f"/{run_id}/" in b.name]
    if not matched:
        raise HTTPException(404, f"No blobs found for run {run_id}")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for b in matched:
            data = container.get_blob_client(b.name).download_blob().readall()
            # Strip the date+run_id prefix; keep just the filename inside the zip
            arcname = b.name.split('/')[-1]
            zf.writestr(arcname, data)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type='application/zip',
        headers={'Content-Disposition': f'attachment; filename="optimizer-{run_id}.zip"'},
    )


@router.get('/api/optimizer/files/by-date/{date}/download')
def download_date_zip(date: str):
    """Download all runs for a given date (YYYY-MM-DD) as one ZIP."""
    container = _blob_container()
    prefix = f"{date}/"
    matched = list(container.list_blobs(name_starts_with=prefix))
    if not matched:
        raise HTTPException(404, f"No blobs found for date {date}")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for b in matched:
            data = container.get_blob_client(b.name).download_blob().readall()
            # Keep run_id/filename structure inside the zip for clarity
            arcname = '/'.join(b.name.split('/')[1:])  # drop date prefix
            zf.writestr(arcname, data)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type='application/zip',
        headers={'Content-Disposition': f'attachment; filename="optimizer-{date}.zip"'},
    )


# ── Run Health Check — anomaly detection + workload distribution ─────────────

@router.get('/api/optimizer/runs/{run_id}/health')
def run_health(run_id: str):
    """Auto-detect anomalies + return workload distribution for visualization."""
    with optimizer_db.get_conn() as conn:
        run = conn.execute("SELECT * FROM opt_runs WHERE id = ?", [run_id]).fetchone()
        if not run:
            raise HTTPException(404, f"Run {run_id} not found")
        cols = [d[0] for d in conn.description]
        run = dict(zip(cols, run))

        # Workload by driver — pull from opt_sa_decisions.winner_* so we count ALL
        # winners including 'Unchanged' SAs (which don't have verdict rows).
        driver_rows = conn.execute("""
            SELECT d.winner_driver_name, d.winner_driver_id,
                   MIN(COALESCE(v.driver_territory, '')) AS territory,
                   COUNT(*) AS sa_count
            FROM opt_sa_decisions d
            LEFT JOIN opt_driver_verdicts v
              ON v.run_id = d.run_id AND v.driver_id = d.winner_driver_id
              AND v.status = 'winner'
            WHERE d.run_id = ? AND d.winner_driver_id IS NOT NULL
            GROUP BY d.winner_driver_name, d.winner_driver_id
            ORDER BY sa_count DESC
        """, [run_id]).fetchall()
        workload = [{'driver_name': r[0], 'driver_id': r[1], 'driver_territory': r[2],
                     'sa_count': r[3]} for r in driver_rows]

        # All considered drivers (winners + eligible) regardless of SA count
        all_drivers = conn.execute("""
            SELECT driver_name, driver_id, driver_territory,
                   COUNT(*) FILTER (WHERE status = 'winner')   AS won,
                   COUNT(*) FILTER (WHERE status = 'eligible') AS eligible_only,
                   COUNT(*) FILTER (WHERE status = 'excluded') AS excluded_count
            FROM opt_driver_verdicts
            WHERE run_id = ?
            GROUP BY driver_name, driver_id, driver_territory
        """, [run_id]).fetchall()
        all_d = [{'driver_name': r[0], 'driver_id': r[1], 'driver_territory': r[2],
                  'won': r[3], 'eligible_only': r[4], 'excluded_count': r[5]}
                 for r in all_drivers]

        # SA decision tallies
        decision_rows = conn.execute("""
            SELECT action, COUNT(*) AS c
            FROM opt_sa_decisions WHERE run_id = ? GROUP BY action
        """, [run_id]).fetchall()
        action_counts = {r[0]: r[1] for r in decision_rows}

    # Compute median + outliers
    counts = sorted([w['sa_count'] for w in workload])
    median = counts[len(counts)//2] if counts else 0
    max_sa = counts[-1] if counts else 0
    outlier_threshold = max(median * 2.5, 5)
    outliers = [w for w in workload if w['sa_count'] >= outlier_threshold]
    idle = [d for d in all_d if d['won'] == 0 and d['eligible_only'] > 0]   # had eligibility, lost out
    truly_idle = [d for d in all_d if d['won'] == 0 and d['eligible_only'] == 0 and d['excluded_count'] > 0]

    # Build anomaly list
    alerts = []
    for o in outliers:
        alerts.append({
            'severity': 'warn',
            'type': 'overload',
            'message': f"{o['driver_name']} got {o['sa_count']} SAs ({o['sa_count']/median:.1f}× median)",
            'driver_name': o['driver_name'],
        })
    if len(idle) > 0:
        alerts.append({
            'severity': 'warn' if len(idle) >= 3 else 'info',
            'type': 'idle',
            'message': f"{len(idle)} driver{'s' if len(idle)>1 else ''} were eligible but got 0 SAs",
            'count': len(idle),
        })
    unsch = action_counts.get('Unscheduled', 0)
    if unsch > 0:
        alerts.append({
            'severity': 'warn',
            'type': 'unscheduled',
            'message': f"{unsch} SAs failed to schedule",
            'count': unsch,
        })
    # If we have no decisions for this run AT ALL, the run hasn't been ingested yet —
    # don't fake "balanced", tell the user to wait.
    total_decisions = sum(action_counts.values())
    if total_decisions == 0 and not workload:
        alerts.insert(0, {
            'severity': 'info',
            'type': 'pending',
            'message': 'This run is still being parsed. Refresh in a few seconds.',
        })
    elif not alerts:
        alerts.append({'severity': 'ok', 'type': 'healthy',
                       'message': 'Run looks balanced — no obvious anomalies'})

    # Headline = first warn/error alert, else first alert (which may be pending or healthy)
    headline = next((a for a in alerts if a['severity'] in ('warn', 'error')), alerts[0])

    return {
        'run': run,
        'headline': headline,
        'alerts': alerts,
        'workload': workload,
        'distribution': {'median': median, 'max': max_sa,
                          'outlier_threshold': outlier_threshold,
                          'driver_count': len(all_d),
                          'with_work': len(workload),
                          'idle_eligible': len(idle),
                          'idle_excluded': len(truly_idle)},
        'action_counts': action_counts,
    }


@router.get('/api/optimizer/runs/{run_id}/driver/{driver_id}/day')
def driver_day(run_id: str, driver_id: str):
    """Return a driver's full day for one run: every SA they were considered for + the winners they got."""
    with optimizer_db.get_conn() as conn:
        # SAs this driver won in this run
        won = conn.execute("""
            SELECT d.sa_number, d.sa_id, d.priority, d.duration_min,
                   d.sa_status, d.action, d.required_skills,
                   d.sched_start, d.sched_end, d.earliest_start, d.due_date,
                   d.winner_travel_time_min, d.winner_travel_dist_mi,
                   d.sa_lat, d.sa_lon
            FROM opt_sa_decisions d
            WHERE d.run_id = ?
              AND d.winner_driver_id = ?
            ORDER BY d.sched_start NULLS LAST
        """, [run_id, driver_id]).fetchall()
        cols = [c[0] for c in conn.description]
        won = [dict(zip(cols, r)) for r in won]

        # SAs they were eligible for but didn't win
        lost = conn.execute("""
            SELECT d.sa_number, d.sa_id, d.priority, d.sched_start,
                   v.travel_time_min, v.travel_dist_mi,
                   d.winner_driver_name AS winner
            FROM opt_driver_verdicts v
            JOIN opt_sa_decisions d ON d.run_id = v.run_id AND d.sa_id = v.sa_id
            WHERE v.run_id = ?
              AND v.driver_id = ?
              AND v.status = 'eligible'
            ORDER BY d.sched_start NULLS LAST
            LIMIT 50
        """, [run_id, driver_id]).fetchall()
        cols = [c[0] for c in conn.description]
        lost = [dict(zip(cols, r)) for r in lost]

        # SAs they were excluded from (top 20 with reason)
        excl = conn.execute("""
            SELECT v.sa_id, d.sa_number, v.exclusion_reason
            FROM opt_driver_verdicts v
            JOIN opt_sa_decisions d ON d.run_id = v.run_id AND d.sa_id = v.sa_id
            WHERE v.run_id = ? AND v.driver_id = ? AND v.status = 'excluded'
            LIMIT 20
        """, [run_id, driver_id]).fetchall()
        cols = [c[0] for c in conn.description]
        excl = [dict(zip(cols, r)) for r in excl]

    return {'won': won, 'lost': lost, 'excluded': excl,
             'won_count': len(won), 'lost_count': len(lost), 'excluded_count': len(excl)}


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
