"""Call Story: "type a call, see what happened and why" (call-story-architecture 7).

  GET  /api/call-story?q=<input>[&sa=<SA#>][&rules=r1|r2][&raw=1]
  POST /api/call-story/narrative  {"sa_id": "..."}   (needs the story loaded first)

Gates: flag `call_story` (404 when off), permission `scheduler.report_card` (403, never contractors), territory
access on the member-facing leg. Salesforce: sequential, capped (call_story_pull), at most 2 pulls at once, one pull
per work order, 10 stories per user per minute. Closed calls are cached 24 h in the file store, open calls 2 min.
"""

import logging
import threading
import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

import cache
import report_card_store as store
from call_story_compose import compose
from call_story_config import cs1
from call_story_events import redact_row
from call_story_norms import Norms
from call_story_pull import Ambiguous, NotFound, NotSupported, classify, pull_story
from permissions import require_feature
from report_card_build import CallCapReached
from report_card_verdicts import RULES_VERSIONS
from routers.garages import _check_territory_access

router = APIRouter()
log = logging.getLogger('call_story')
_PULLS = threading.Semaphore(2)
_WO_LOCKS = defaultdict(threading.Lock)
_RATE = defaultdict(deque)
MAP_CLOSED_TTL_S = 7 * 86400


def _gate(request: Request):
    import feature_flags
    if not feature_flags.is_on('call_story'):
        raise HTTPException(status_code=404, detail='Not found')
    require_feature(('scheduler.report_card', 'scheduler.replay'), request)   # Replay users read the same day and story data


def _user(request: Request) -> str:
    from routers.auth import _verify_cookie
    cookie = request.cookies.get('fslapp_auth')
    payload = _verify_cookie(cookie) if cookie else None
    return payload.split(':')[0] if payload else (request.client.host if request.client else 'anon')


def _rate_limit(user: str, cfg: dict):
    q, now = _RATE[user], time.time()
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= cfg['rate_limit_per_min']:
        raise HTTPException(status_code=429, detail='Too many stories in a minute; try again shortly')
    q.append(now)


def _raw_for(q: str, cfg: dict, user: str | None = None) -> tuple:
    """(raw bundle, cache state). Resolution is cached so a repeat input costs 0 Salesforce calls.
    `user` is rate limited only when a real Salesforce pull is needed: cache hits are free, so opening several
    calls in a row (each is 2-3 requests) is never blocked."""
    kind, value = classify(q, cfg)
    with _WO_LOCKS[f'{kind}:{value}']:               # concurrent clicks on one call share a single pull
        wo_id = cache.get(f'cs_resolve:{kind}:{value}')
        if wo_id:
            hit = cache.get(f'cs_raw:{wo_id}') or _stored(wo_id, cfg)
            if hit:
                return hit, 'hit'
        if user:
            _rate_limit(user, cfg)
        with _PULLS:
            raw = pull_story(q, cfg)
        wo_id = raw['resolution']['wo']['id']
        ttl = cfg['cache_ttl_sec']['closed' if raw['closed'] else 'open']
        cache.put(f'cs_resolve:{kind}:{value}', wo_id, ttl=86400)
        cache.put(f'cs_raw:{wo_id}', raw, ttl=ttl)
        if raw['closed']:
            store.save_story_raw(wo_id, raw)
        return raw, 'miss'


def _stored(wo_id: str, cfg: dict):
    age = store.story_raw_age_s(wo_id)
    if age is not None and age < cfg['cache_ttl_sec']['closed']:
        raw = store.load_story_raw(wo_id)
        cache.put(f'cs_raw:{wo_id}', raw, ttl=cfg['cache_ttl_sec']['closed'])
        return raw
    return None


def _norms(date: str, cfg: dict) -> Norms:
    key = f'cs_norms:{date}'
    hit = cache.get(key)
    if hit is None:
        hit = Norms.for_call(date, cfg)
        cache.put(key, hit, ttl=600)
    return hit


@router.get('/api/call-story')
def get_story(request: Request, q: str, sa: str | None = None, rules: str | None = None, raw: int = 0):
    _gate(request)
    cfg = cs1()
    if rules and rules not in RULES_VERSIONS:
        raise HTTPException(status_code=422, detail=f'rules must be one of {RULES_VERSIONS}')
    try:
        classify(q, cfg)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    t0 = time.time()
    try:
        bundle, state = _raw_for(q, cfg, _user(request))
    except NotFound:
        return JSONResponse(status_code=404, content={'status': 'not_found'})
    except Ambiguous as e:
        return JSONResponse(status_code=409, content={'status': 'ambiguous', 'candidates': e.candidates})
    except NotSupported as e:
        raise HTTPException(status_code=422, detail=str(e))
    except (CallCapReached, RuntimeError) as e:
        log.warning('call story pull failed for %s: %s', q, e)
        raise HTTPException(status_code=503, detail='Salesforce is unavailable or busy; try again shortly')
    member = next((s for s in bundle['sas'] if 'drop' not in ((s.get('WorkType') or {}).get('Name') or '').lower()), None)
    if member is not None:
        _check_territory_access(request, member.get('ServiceTerritoryId'))
    story = compose(bundle, cfg, sa, store.load_snapshot, lambda d: _norms(d, cfg), rules)
    story.setdefault('meta', {}).update({
        'fetched_at': bundle.get('fetched_at'), 'cache': state, 'sf_calls': 0 if state == 'hit' else bundle.get('sf_calls'),
        'partial': bool(bundle.get('partial')), 'engine_version': 'e1'})
    if raw:
        story['raw_history'] = [redact_row(h) for h in bundle['history']]
    sel = next((leg for leg in story['resolution'].get('legs', []) if leg['selected']), None)
    if sel:
        cache.put(f"cs_story:{sel['sa_id']}", story, ttl=3600)
    log.info('call story %s: sf_calls=%s cache=%s snapshot_used=%s ms=%d', q, story['meta']['sf_calls'], state,
             bool(story['meta'].get('snapshot_used')), int((time.time() - t0) * 1000))
    return story


@router.get('/api/call-story/replay')
def get_replay_steps(request: Request, q: str):
    """The same story, as animation steps for the Work Order Replay (wo_replay.py). Same gates and Salesforce load."""
    from wo_replay import build_replay
    from wo_replay_map import locate
    require_feature('scheduler.replay', request)         # Replay: administrators, executives and ERS managers only
    t0 = time.time()
    story = get_story(request, q)
    if not isinstance(story, dict):
        return story
    bundle = cache.get(f"cs_raw:{story['resolution']['wo']['id']}") or _stored(story['resolution']['wo']['id'], cs1())
    out = build_replay(story, where=locate(bundle) if bundle else None)
    out['meta'] = {'sf_calls': story['meta'].get('sf_calls'), 'cache': story['meta'].get('cache'), 'ms': int((time.time() - t0) * 1000)}
    return out


@router.get('/api/call-story/replay-map')
def get_replay_map(request: Request, q: str):
    """Locations for the replay (wo_replay_map.py), loaded after the animation because the GPS read can be slow.
    Same gates as the story; the story's raw pull is reused from cache. A day snapshot supplies most GPS tracks, so
    the usual cost is 0 Salesforce calls. A closed call's map is kept 7 days, in memory and on disk."""
    from wo_replay_map import pull_map
    require_feature('scheduler.replay', request)         # Replay: administrators, executives and ERS managers only
    t0 = time.time()
    story = get_story(request, q)
    if not isinstance(story, dict):
        return story
    wo_id = story['resolution']['wo']['id']
    key = f'cs_map:{wo_id}'
    hit = cache.get(key) or cache.disk_get(key)          # only closed calls are ever written to disk
    if hit:
        return hit
    bundle = cache.get(f'cs_raw:{wo_id}') or _stored(wo_id, cs1())
    if not bundle:
        raise HTTPException(status_code=409, detail='Load the replay first')
    try:
        out = pull_map(bundle, snapshot_for=store.load_snapshot)
    except (CallCapReached, RuntimeError) as e:
        log.warning('replay map pull failed for %s: %s', q, e)
        raise HTTPException(status_code=503, detail='Salesforce is unavailable or busy; try again shortly')
    if bundle.get('closed'):
        cache.put(key, out, ttl=MAP_CLOSED_TTL_S)
        cache.disk_put(key, out, ttl=MAP_CLOSED_TTL_S)
    else:
        cache.put(key, out, ttl=cs1()['cache_ttl_sec']['open'])
    log.info('replay map %s: sf_calls=%s ms=%d', q, out['sf_calls'], int((time.time() - t0) * 1000))
    return out


@router.get('/api/call-story/peers')
def get_replay_peers(request: Request, q: str):
    """The other qualified, on-shift drivers of the garage when the call was given to the driver (wo_replay_peers.py).
    Read from the day snapshot only: 0 Salesforce calls. Same gates as the map; loaded after the animation."""
    from wo_replay_peers import pull_peers
    require_feature('scheduler.replay', request)
    story = get_story(request, q)
    if not isinstance(story, dict):
        return story
    wo_id = story['resolution']['wo']['id']
    key = f'cs_peers:{wo_id}'
    hit = cache.get(key)
    if hit:
        return hit
    bundle = cache.get(f'cs_raw:{wo_id}') or _stored(wo_id, cs1())
    if not bundle:
        raise HTTPException(status_code=409, detail='Load the replay first')
    out = pull_peers(bundle, store.load_snapshot)
    cache.put(key, out, ttl=MAP_CLOSED_TTL_S if bundle.get('closed') and out['available'] else 600)
    return out


@router.post('/api/call-story/narrative')
def post_narrative(request: Request, body: dict):
    _gate(request)
    story = cache.get(f"cs_story:{body.get('sa_id')}")
    if story is None:
        return JSONResponse(status_code=409, content={'status': 'load_story_first'})
    from call_story_narrative import narrate
    from utils import load_ai_settings
    return narrate(story, load_ai_settings())
