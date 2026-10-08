"""Replay extras: member calls, member texts and the driver's other jobs (replay-v2 design 4).

  GET /api/call-story/extras?q=       calls, inbound texts, driver load, insights   (2 Salesforce calls, cached)
  GET /api/call-story/text-thread?q=  the message bodies of the member's text chat  (1 call, only when clicked)

Gates: flags `call_story` and `replay_member_contact` (404 when off), permission `scheduler.replay` and the territory
check (all through get_story). Anyone with Replay permission sees message text; every view of a thread is logged.
Phones never leave the pull; conversation ids and message bodies stay in the server's memory cache only."""

import logging
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

import cache
import feature_flags
from call_story_config import cs1
from permissions import require_feature
from replay_extras_pull import pull_extras
from replay_thread import fetch_thread
from report_card_build import CallCapReached, CompositeError
from routers import call_story as cs

router = APIRouter()
log = logging.getLogger('replay_extras')
THREAD_TTL_S = 3600


def _story(request: Request, q: str):
    """(story, raw bundle) or a JSONResponse for not_found / ambiguous, after every gate."""
    if not feature_flags.is_on('replay_member_contact'):
        raise HTTPException(status_code=404, detail='Not found')
    require_feature('scheduler.replay', request)
    story = cs.get_story(request, q)
    if not isinstance(story, dict):
        return story, None
    wo_id = story['resolution']['wo']['id']
    return story, cache.get(f'cs_raw:{wo_id}') or cs._stored(wo_id, cs1())


@router.get('/api/call-story/extras')
def get_extras(request: Request, q: str):
    t0 = time.time()
    story, raw = _story(request, q)
    if raw is None and not isinstance(story, dict):
        return story
    if raw is None:
        raise HTTPException(status_code=409, detail='Load the replay first')
    wo_id = raw['wo']['Id']
    key = f'cs_extras:{wo_id}'
    hit = cache.get(key)
    if hit:
        return {**hit, 'sf_calls': 0, 'cache': 'hit'}
    cfg = cs1()
    with cs._WO_LOCKS[f'extras:{wo_id}']:
        hit = cache.get(key)
        if hit:
            return {**hit, 'sf_calls': 0, 'cache': 'hit'}
        cs._rate_limit(cs._user(request), cfg)
        try:
            with cs._PULLS:
                out, private = pull_extras(raw, (story.get('pta') or {}).get('due_initial'))
        except (CallCapReached, CompositeError, RuntimeError) as e:
            log.warning('replay extras pull failed for %s: %s', q, e)
            raise HTTPException(status_code=503, detail='Salesforce is unavailable or busy; try again shortly')
        ttl = cfg['cache_ttl_sec']['closed' if raw.get('closed') else 'open']
        cache.put(key, out, ttl=ttl)
        cache.put(f'cs_extras_conv:{wo_id}', private, ttl=ttl)
    log.info('replay extras %s: sf_calls=%s ms=%d', q, out['sf_calls'], int((time.time() - t0) * 1000))
    return {**out, 'cache': 'miss'}


@router.get('/api/call-story/text-thread')
def get_text_thread(request: Request, q: str):
    story, raw = _story(request, q)
    if raw is None and not isinstance(story, dict):
        return story
    if raw is None:
        raise HTTPException(status_code=409, detail='Load the replay first')
    wo_id = raw['wo']['Id']
    private = cache.get(f'cs_extras_conv:{wo_id}')
    if not private:
        return JSONResponse(status_code=409, content={'status': 'load_extras_first'})
    log.info('text thread viewed user=%s wo=%s', cs._user(request), raw['wo'].get('WorkOrderNumber') or wo_id)
    key = f'cs_thread:{wo_id}'                                          # message bodies: memory only, never disk
    hit = cache.get(key)
    if hit:
        return {**hit, 'sf_calls': 0}
    if not private['conversations']:
        return {'entries': [], 'sf_calls': 0}
    try:
        with cs._PULLS:
            entries, calls = fetch_thread(private['conversations'], *private['window'])
    except RuntimeError as e:
        log.warning('text thread read failed for %s: %s', q, e)
        raise HTTPException(status_code=503, detail='Salesforce is unavailable or busy; try again shortly')
    out = {'entries': entries}
    cache.put(key, out, ttl=THREAD_TTL_S)
    return {**out, 'sf_calls': calls}
