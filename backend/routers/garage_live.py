"""Garage Live: GET /api/garage-live/{garage_id}: one garage's open tickets, drivers and a ranked "Needs attention" list.

Salesforce cost per refresh, whatever the number of viewers: ZERO from this endpoint's own reads. Tickets and flags come from the shared
Watchlist snapshot (refreshed once for everybody), drivers / trucks / territory members from ref_data (2 min and 10 min copies). The only
extra reads are skills for the "closer driver" suggestion: the required skills of a waiting call (read once per call, kept 6 h) and the skills
of the garage's free drivers (once per driver, kept 1 h), both shared, both skipped when no call waits or no driver is free.
The finished answer is kept 20 s per garage, so every viewer of a garage shares one build.
Same gate as the Command Center; a contractor only gets their own garages and never sees other garages' calls in a driver's queue.
"""

import logging
import re
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response

import cache
import garage_live
import osrm
import ref_data
import users as _users
from routers import watchlist
from routers.auth import get_request_username
from routers.garages import _check_territory_access
from report_card_snapshot import miles
from sf_client import sanitize_soql, sf_query_all

router = APIRouter()
log = logging.getLogger('garage_live')
TTL_S = 20
TTL_WOLI_SKILLS = 6 * 3600
TTL_DRIVER_SKILLS = 3600
_ID = re.compile(r'^[A-Za-z0-9]{15,18}$')
CHUNK = 150
ROAD_MAX_MILES = 15              # a truck that moved further than this is a jump, not a drive: no road is asked for
ROAD_SLOTS = threading.BoundedSemaphore(4)   # at most this many road lookups at once, however many screens are open


def _cached_skills(prefix: str, ids: list, ttl: int, fetch) -> dict:
    """{id: set(skills)} for `ids`: each id is read once per ttl (an id with no skills is remembered as empty), the missing ones in chunked SELECTs."""
    out, missing = {}, []
    for i in ids:
        hit = cache.get(f'{prefix}:{i}')
        if hit is None:
            missing.append(i)
        else:
            out[i] = set(hit)
    for n in range(0, len(missing), CHUNK):
        part = missing[n:n + CHUNK]
        got = {i: set() for i in part}
        for row in fetch(part):
            got.setdefault(row['_id'], set()).add(row['_skill'])
        for i, skills in got.items():
            cache.put(f'{prefix}:{i}', sorted(skills), ttl)
            out[i] = skills
    return out


def _in(ids):
    return ','.join(f"'{sanitize_soql(i)}'" for i in ids)


def _woli_rows(ids):
    return [{'_id': r['RelatedRecordId'], '_skill': (r.get('Skill') or {}).get('MasterLabel')} for r in sf_query_all(
        f"SELECT RelatedRecordId, Skill.MasterLabel FROM SkillRequirement WHERE RelatedRecordId IN ({_in(ids)})") if (r.get('Skill') or {}).get('MasterLabel')]


def _driver_rows(ids):
    return [{'_id': r['ServiceResourceId'], '_skill': (r.get('Skill') or {}).get('MasterLabel')} for r in sf_query_all(
        f"SELECT ServiceResourceId, Skill.MasterLabel FROM ServiceResourceSkill WHERE ServiceResourceId IN ({_in(ids)}) "
        f"AND (EffectiveEndDate = null OR EffectiveEndDate >= TODAY)") if (r.get('Skill') or {}).get('MasterLabel')]


def skills_provider(woli_ids: list, driver_ids: list):
    try:
        return (_cached_skills('glive:woli', woli_ids, TTL_WOLI_SKILLS, _woli_rows),
                _cached_skills('glive:drv', driver_ids, TTL_DRIVER_SKILLS, _driver_rows))
    except Exception as e:
        log.warning('garage live: skills unavailable (%s)', e)
        return None


def _info(garage_id: str) -> dict:
    g = next((g for g in cache.get_stale('garages_list') or [] if g.get('id') == garage_id), None)
    return {'name': g.get('name'), 'lat': g.get('lat'), 'lon': g.get('lon')} if g else {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _build(garage_id: str):
    snap, result = watchlist.shared_state()
    now = _now()
    return garage_live.build(garage_id, snap, result, ref_data.drivers(require_gps=False), ref_data.trucks(), ref_data.members(), now,
                             skills_provider, _info(garage_id))


def _role(request: Request) -> str:
    username = get_request_username(request)
    if not username:
        raise HTTPException(status_code=401, detail='Not authenticated')
    return (_users.get_user(username) or {}).get('role') or ''


def _redact_for_contractor(body: dict, garage_id: str) -> dict:
    """A contractor sees their own garage only: another garage's call (in a shared driver's queue or current job) loses its number and type,
    and the attention lines about it are left out."""
    hide = {'sa_id': None, 'number': 'Another garage', 'work_type': ''}
    own = {t['sa_id'] for t in body['tickets']}
    drivers = []
    for d in body['drivers']:
        queue = [q if q['territory_id'] == garage_id else {**q, **hide} for q in d['queue']]
        job = d['job'] if not d['job'] or d['job']['territory_id'] == garage_id else {**d['job'], **hide}
        drivers.append({**d, 'queue': queue, 'job': job})
    return {**body, 'drivers': drivers, 'attention': [i for i in body['attention'] if not i['sa_id'] or i['sa_id'] in own]}


@router.get('/api/garage-live/{garage_id}')
def get_garage_live(request: Request, garage_id: str):
    role = _role(request)
    if not _ID.match(garage_id):
        raise HTTPException(status_code=400, detail='Invalid garage id')
    _check_territory_access(request, garage_id)
    try:
        body = cache.cached_query(f'garage_live:{garage_id}', lambda: _build(garage_id), ttl=TTL_S)
    except RuntimeError as e:
        log.warning('garage live %s failed: %s', garage_id, e)
        raise HTTPException(status_code=503, detail='Salesforce is unavailable or busy; try again shortly')
    if body is None:
        raise HTTPException(status_code=404, detail='That garage was not found')
    if role == 'contractor':
        body = _redact_for_contractor(body, garage_id)
    return {**body, 'can_replay': role != 'contractor', 'contractor': role == 'contractor', 'now': _now().isoformat(timespec='seconds')}


@router.get('/api/garage-live-road')
def get_road(a: str, b: str):
    """The street route between a truck's old and new position (lat,lon each), for the truck to drive along between two refreshes.
    The same OSRM lookup and 7-day cache the Replay maps use (osrm.route). No Salesforce. 204 = no road (the screen draws a straight line)."""
    try:
        (la1, lo1), (la2, lo2) = [tuple(float(x) for x in v.split(',')) for v in (a, b)]
    except ValueError:
        raise HTTPException(status_code=400, detail='Invalid position')
    if not all(-90 <= x <= 90 for x in (la1, la2)) or not all(-180 <= x <= 180 for x in (lo1, lo2)):
        raise HTTPException(status_code=400, detail='Invalid position')
    if miles(la1, lo1, la2, lo2) > ROAD_MAX_MILES:
        raise HTTPException(status_code=400, detail='Too far for a road lookup')
    if not ROAD_SLOTS.acquire(timeout=2):
        raise HTTPException(status_code=503, detail='Road lookups are busy')
    try:
        res = osrm.route([(la1, lo1), (la2, lo2)], timeout=4)
    finally:
        ROAD_SLOTS.release()
    if not res:
        return Response(status_code=204)
    return {'coords': [[round(c[0], 5), round(c[1], 5)] for c in res['coords']], 'miles': res['miles']}
