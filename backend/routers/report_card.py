"""Scheduler Report Card, slice 1: build a past garage-day once, then serve the day view.

  GET  /api/report-card/garages?date=YYYY-MM-DD        only the garages that had ERS work orders that day (for the pickers)
  GET  /api/report-card/{territory_id}/{date}          day view (404 not built, 202 building, 409 failed)
  POST /api/report-card/{territory_id}/{date}/build    start a build (202), or 200 if already built
  GET  /api/report-card/{territory_id}/{date}/status   build status
  GET  /api/report-card/{territory_id}/{date}/findings AI findings from the fact sheet (template without a key)
  GET  /api/report-card/{territory_id}/{date}/replay   driver tracks and call holds for the Day replay tab
  GET  /api/report-card/{territory_id}/{date}/call-flags   RAP / out of territory / coverage / member-text flags per call
  GET  /api/case-trail/{wo_id}   the work order's cases, each with who touched it and what they did (on demand)

Gates (architecture.md section 9): feature flag `scheduler_report_card` (404 when off, default off),
permission `scheduler.report_card` (403; contractors never have it), territory access check.
Storage is the interim JSON file store (report_card_store); no Postgres tables in this slice.
"""

import logging
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

import cache
import report_card_store as store
from permissions import require_feature
from report_card_metrics import METRICS_VERSION, driver_day, garage_summary
from report_card_verdicts import (DEFAULT_RULES, ENGINE_VERSION, RULES_VERSIONS,
                                  rules_for, score_snapshot, supports)
from routers.garages import _check_territory_access
from utils import _ET

router = APIRouter()
log = logging.getLogger('report_card')

MAX_LOOKBACK_DAYS = 540
_ID = re.compile(r'^[A-Za-z0-9]{15}$|^[A-Za-z0-9]{18}$')
_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_BUILD_SEM = threading.Semaphore(1)   # one build per process, ever (section 5.1)

VERDICT_CATALOG = [
    ('GOOD', 'Sound decision, PTA met', 'good'),
    ('GOOD_NO_ARRIVAL', 'Sound decision, canceled before arrival', 'good'),
    ('LATE_EXECUTION', 'Quick pick to a free driver, PTA still missed', 'context'),
    ('CAPACITY_SHORT', 'PTA missed, no qualified driver free nearby', 'context'),
    ('INBOUND_CASCADE', 'Arrived from another garage', 'context'),
    ('BOUNCED', 'Driver pulled back or changed after dispatch', 'failure'),
    ('STACKED', 'Busy driver picked while a closer qualified driver was idle', 'failure'),
    ('FAR_PICK', 'Picked far beyond the closest free qualified driver', 'failure'),
    ('LATE_DESPITE_CAPACITY', 'PTA missed although a qualified driver was free nearby', 'failure'),
    ('NOT_GRADED_INSUFFICIENT_DATA', 'Not graded: no fresh GPS for the picked driver', 'not_graded'),
    ('NOT_GRADED_CANCELED_PRE_ASSIGN', 'Not graded: no driver ever assigned', 'not_graded'),
    ('NOT_GRADED_TOWBOOK', 'Not graded: Towbook call', 'not_graded'),
]
CAVEATS = [
    'Availability is observed, not counterfactual.',
    'Skills and truck capabilities are current values; Salesforce keeps no history of them.',
    'Distances are straight-line miles, not road distance.',
    'Open jobs in other territories are not visible.',
    'On-Platform contractor idle time is an upper bound (non-AAA work is invisible).',
]


def _gate(request: Request, territory_id: str, service_date: str):
    import feature_flags
    if not feature_flags.is_on('scheduler_report_card'):
        raise HTTPException(status_code=404, detail='Not found')
    require_feature('scheduler.report_card', request)
    if not _ID.match(territory_id or ''):
        raise HTTPException(status_code=422, detail='Invalid territory id')
    _check_territory_access(request, territory_id)
    if not _DATE.match(service_date or ''):
        raise HTTPException(status_code=422, detail='Date must be YYYY-MM-DD')
    d = date.fromisoformat(service_date)
    today = datetime.now(_ET).date()
    if d >= today:
        raise HTTPException(status_code=422, detail='Past days only: pick yesterday or earlier')
    if d < today - timedelta(days=MAX_LOOKBACK_DAYS):
        raise HTTPException(status_code=422, detail=f'Older than {MAX_LOOKBACK_DAYS} days: Salesforce history is gone')


def _is_admin(request: Request) -> bool:
    try:
        require_feature('scheduler.report_card_admin', request)
        return True
    except HTTPException:
        return False


def _not_ready(territory_id: str, service_date: str):
    s = store.get_status(territory_id, service_date)
    if s and s.get('status') == 'building':
        return JSONResponse(status_code=202, content=s)
    if s and s.get('status') == 'failed':
        return JSONResponse(status_code=409, content=s)
    return JSONResponse(status_code=404, content={'status': 'not_built'})


def _rules(version: str, snap: dict):
    """Rules for this request, or a 409 telling the page to rebuild (r2 needs builder 1.1). Never falls back."""
    if version not in RULES_VERSIONS:
        raise HTTPException(status_code=422, detail=f'rules must be one of {RULES_VERSIONS}')
    rules = rules_for(version)
    if not supports(snap, rules):
        return None, JSONResponse(status_code=409, content={
            'status': 'rules_unavailable', 'rules': version, 'builder_version': snap.get('builder_version'),
            'available': [v for v in RULES_VERSIONS if supports(snap, rules_for(v))],
            'error': f'Rules {version} need data this day was built without (original PTA, auto-schedule stamp). '
                     'Rebuild the day.'})
    return rules, None


@router.get('/api/report-card/garages')
def garages_with_work(request: Request, date: str):
    """Garages that had at least one ERS work order that Eastern day, busiest first: [{id, name, count}].
    Two small read-only aggregate queries per day, cached an hour (a past day does not change)."""
    import feature_flags
    from sf_client import sf_query_all, sanitize_soql
    if not feature_flags.is_on('scheduler_report_card'):
        raise HTTPException(status_code=404, detail='Not found')
    require_feature('scheduler.report_card', request)
    if not _DATE.match(date or ''):
        raise HTTPException(status_code=422, detail='Date must be YYYY-MM-DD')
    d, today = date_from_iso(date), datetime.now(_ET).date()
    if d >= today:
        raise HTTPException(status_code=422, detail='Past days only: pick yesterday or earlier')
    if d < today - timedelta(days=MAX_LOOKBACK_DAYS):
        raise HTTPException(status_code=422, detail=f'Older than {MAX_LOOKBACK_DAYS} days: Salesforce history is gone')
    key = f'report_card_day_garages:{date}'
    hit = cache.get(key)
    if hit is not None:
        return hit
    start = datetime(d.year, d.month, d.day, tzinfo=_ET).astimezone(timezone.utc)
    stop = start + timedelta(days=1)
    iso = lambda t: t.strftime('%Y-%m-%dT%H:%M:%SZ')
    rows = sf_query_all(f"""SELECT ServiceTerritoryId, COUNT(Id) cnt FROM ServiceAppointment
        WHERE CreatedDate >= {iso(start)} AND CreatedDate < {iso(stop)} AND ServiceTerritoryId != null
        AND RecordType.Name = 'ERS Service Appointment' AND WorkType.Name != 'Tow Drop-Off'
        GROUP BY ServiceTerritoryId ORDER BY COUNT(Id) DESC""")
    ids = [r['ServiceTerritoryId'] for r in rows if _ID.match(r.get('ServiceTerritoryId') or '')]
    names = {}
    if ids:
        names = {t['Id']: t['Name'] for t in sf_query_all(
            "SELECT Id, Name FROM ServiceTerritory WHERE Id IN (" + ','.join(f"'{sanitize_soql(i)}'" for i in ids) + ')')}
    out = [{'id': r['ServiceTerritoryId'], 'name': names.get(r['ServiceTerritoryId'], r['ServiceTerritoryId']), 'count': r['cnt']}
           for r in rows if r.get('ServiceTerritoryId') in names]
    cache.put(key, out, ttl=3600)
    return out


def date_from_iso(s: str) -> date:
    return date.fromisoformat(s)


@router.get('/api/report-card/{territory_id}/{service_date}')
def get_day(territory_id: str, service_date: str, request: Request, rules: str = DEFAULT_RULES):
    _gate(request, territory_id, service_date)
    snap = store.load_snapshot(territory_id, service_date)
    if snap is None:
        return _not_ready(territory_id, service_date)
    ruleset, refusal = _rules(rules, snap)
    if refusal:
        return refusal
    key = f"report_card_day:{territory_id}:{service_date}:{snap['built_at']}:{METRICS_VERSION}:{rules}"
    view = cache.get(key)
    if view is None:
        view = day_view(snap, ruleset)
        cache.put(key, view, ttl=600)
    return view


@router.get('/api/report-card/{territory_id}/{service_date}/status')
def get_status(territory_id: str, service_date: str, request: Request):
    _gate(request, territory_id, service_date)
    s = store.get_status(territory_id, service_date)
    if s is None:
        ready = store.load_snapshot(territory_id, service_date) is not None
        return {'status': 'ready' if ready else 'not_built'}
    return s


@router.post('/api/report-card/{territory_id}/{service_date}/build')
def build_day(territory_id: str, service_date: str, request: Request, force: bool = False):
    _gate(request, territory_id, service_date)
    s = store.get_status(territory_id, service_date)
    if s and s.get('status') == 'building':
        return JSONResponse(status_code=202, content=s)
    snap = store.load_snapshot(territory_id, service_date)
    if snap is not None and not force:
        return {'status': 'ready', 'built_at': snap['built_at']}
    if snap is not None and not snap.get('provisional') and not _is_admin(request):
        raise HTTPException(status_code=403, detail='Only an admin can rebuild a final report')
    started = datetime.now(timezone.utc).isoformat(timespec='seconds')
    store.set_status(territory_id, service_date, status='building', started_at=started, started_ts=time.time())
    threading.Thread(target=_run_build, args=(territory_id, service_date, started), daemon=True).start()
    return JSONResponse(status_code=202, content={'status': 'building', 'started_at': started})


@router.get('/api/report-card/{territory_id}/{service_date}/findings')
def get_findings(territory_id: str, service_date: str, request: Request, rules: str = DEFAULT_RULES):
    """Architecture 11: fact sheet -> AI (validated, cached by hash) or template. No SF, no Postgres writes."""
    from report_card_ai import day_findings
    from report_card_facts import build_fact_sheet
    _gate(request, territory_id, service_date)
    snap = store.load_snapshot(territory_id, service_date)
    if snap is None:
        return _not_ready(territory_id, service_date)
    ruleset, refusal = _rules(rules, snap)
    if refusal:
        return refusal
    verdicts = score_snapshot(snap, ruleset)
    rows = driver_day(snap, verdicts, ruleset)
    sheet, driver_map = build_fact_sheet(snap, verdicts, rows, garage_summary(snap, verdicts, rows, ruleset), ruleset)
    return day_findings(sheet, driver_map)


@router.get('/api/report-card/{territory_id}/{service_date}/replay')
def get_replay(territory_id: str, service_date: str, request: Request):
    """Positions and call holds from the saved snapshot. No SF, no Postgres."""
    from report_card_replay import replay_view
    _gate(request, territory_id, service_date)
    require_feature('scheduler.replay', request)         # Replay is for administrators and executives only
    snap = store.load_snapshot(territory_id, service_date)
    if snap is None:
        return _not_ready(territory_id, service_date)
    key = f"report_card_replay:{territory_id}:{service_date}:{snap['built_at']}"
    view = cache.get(key)
    if view is None:
        view = replay_view(snap)
        cache.put(key, view, ttl=600)
    return view


@router.get('/api/report-card/{territory_id}/{service_date}/call-flags')
def get_call_flags(territory_id: str, service_date: str, request: Request):
    """Icons and filters for the Replay work-order list. Three read-only SELECTs, cached against the snapshot."""
    from report_card_build import Puller
    from report_card_flags import pull_flags
    _gate(request, territory_id, service_date)
    require_feature('scheduler.replay', request)
    snap = store.load_snapshot(territory_id, service_date)
    if snap is None:
        return _not_ready(territory_id, service_date)
    key = f"report_card_flags:{territory_id}:{service_date}:{snap['built_at']}"
    flags = cache.get(key)
    if flags is None:
        flags = pull_flags([s for s in snap['sas'] if not s['is_drop_off']], Puller(max_calls=8))
        # surveys arrive for a few days after a call: cache short while the day is recent, long once it can't change
        old = (datetime.now(_ET).date() - date.fromisoformat(service_date)).days > 3
        cache.put(key, flags, ttl=86400 if old else 3600)
    return {'flags': flags}


_WO_ID = re.compile(r'^0WO[A-Za-z0-9]{12,15}$')


@router.get('/api/case-trail/{wo_id}')
def get_case_trail(wo_id: str, request: Request):
    """Cases on one work order with every touch (owner/status changes, comments, emails, tasks). Replay permission."""
    import feature_flags
    from report_card_build import Puller
    import case_trail
    if not feature_flags.is_on('scheduler_report_card'):
        raise HTTPException(status_code=404, detail='Not found')
    require_feature('scheduler.replay', request)         # Replay is for administrators and executives only
    if not _WO_ID.match(wo_id or ''):
        raise HTTPException(status_code=422, detail='Invalid work order id')
    key = f'case_trail:{wo_id}'
    out = cache.get(key)
    if out is None:
        cases = case_trail.pull(wo_id, Puller(max_calls=8))
        out = {'wo_id': wo_id, 'cases': cases}
        # open cases keep changing; a closed set is stable for longer
        cache.put(key, out, ttl=3600 if cases and all(c['closed'] for c in cases) else 120)
    return out


def _run_build(territory_id: str, service_date: str, started: str):
    from report_card_build import pull_garage_day
    from report_card_snapshot import build_snapshot
    with _BUILD_SEM:
        t0, raw = time.time(), None
        try:
            raw = pull_garage_day(territory_id, service_date)
            size = store.save_snapshot(territory_id, service_date, build_snapshot(raw))
            store.set_status(territory_id, service_date, status='ready', started_at=started,
                             finished_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                             sf_calls=raw['sf_calls'], payload_bytes=size, build_ms=int((time.time() - t0) * 1000))
        except Exception as e:  # recorded for the page; the previous snapshot stays current
            log.exception('report card build failed %s %s', territory_id, service_date)
            store.set_status(territory_id, service_date, status='failed', started_at=started,
                             error=str(e)[:1000], sf_calls=(raw or {}).get('sf_calls'))


def day_view(snap: dict, rules: dict) -> dict:
    """Snapshot -> page payload. GPS, candidate sets and capacity samples stay server-side."""
    verdicts = score_snapshot(snap, rules)
    drivers = driver_day(snap, verdicts, rules)
    by_id = {d['id']: d for d in snap['drivers']}
    for row in drivers:
        d = by_id[row['id']]
        row.update(logins=d['logins'], absences=d['absences'], skills=d['skills'],
                   trucks=[{k: t[k] for k in ('start', 'end', 'truck', 'truck_caps')} for t in d['trucks']])
    names = {d['id']: d['name'] for d in snap['drivers']}
    sas = []
    for sa in snap['sas']:
        if not sa['in_day']:
            continue
        v = verdicts.get(sa['id'])
        ev = (v or {}).get('evidence', {})
        sas.append({
            **{k: sa[k] for k in ('id', 'number', 'work_type', 'call_class', 'is_drop_off', 'status', 'created',
                                  'pta_min', 'pta_due', 'channel', 'final_driver_id', 'required_skills',
                                  'milestones', 'territory_moves', 'city')},
            'driver_name': names.get(sa['final_driver_id']),
            'decision': {**{k: sa['decision'][k] for k in ('n_picks', 'n_pre_dispatch_picks', 'pullbacks',
                                                            'reassign_after_dispatch', 'ar_creator')},
                         'final_actor': ev.get('final_actor'), 'final_actor_class': ev.get('final_actor_class'),
                         'first_actor': (sa['decision']['first'] or {}).get('actor'),
                         'first_actor_class': ev.get('first_actor_class')},
            'verdict': {**{k: v[k] for k in ('code', 'flags', 'is_failure', 'graded')},
                        'evidence': {**ev, 'closest_driver': names.get(ev.get('closest_driver_id')),
                                     'closest_free_driver': names.get(ev.get('closest_free_driver_id')),
                                     'idle_closer': [[names.get(i), mi] for i, mi in ev.get('idle_closer') or []]}}
            if v else None,
        })
    return {
        'snapshot': {'built_at': snap['built_at'], 'provisional': snap['provisional'],
                     'schema_version': snap['schema_version'], 'builder_version': snap['builder_version'],
                     'metrics_version': METRICS_VERSION, 'rules_version': rules['rules_version'],
                     'engine_version': ENGINE_VERSION, 'day_mode': snap['channel_summary']['mode'],
                     'channel_summary': snap['channel_summary'], 'completeness': snap['completeness'],
                     'storage': 'interim_file'},
        'territory': snap['territory'], 'service_date': snap['service_date'], 'window': snap['window'],
        'summary': garage_summary(snap, verdicts, drivers, rules),
        'config': snap['config'], 'travel_basis': snap['travel_basis'],
        'verdict_catalog': [{'code': c, 'label': lbl, 'group': g} for c, lbl, g in VERDICT_CATALOG],
        'caveats': CAVEATS,
        'drivers': drivers,
        'sas': sas,
    }
