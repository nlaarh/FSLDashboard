"""Watchlist call map: GET /api/watchlist/call-map/{sa_id}: one open call, its garage, driver, nearby qualified drivers, cases and story.

Same gate as the Watchlist (any signed-in user) except contractors, who must never see other drivers. Member TEXT CONTENT only for roles with
`scheduler.replay`; everyone else gets counts. Driver and garage phones are visible to all Watchlist users.
Cost of an open: the call story (1 composite, shared with Replay through the same cache), the member's calls/texts (2 composites, same cache
as Replay's extras), and ONE composite of 5 SELECTs (watchlist_call_map.pull). The whole answer is cached 60 s per call, one rebuild at a time.
"""

import logging
import re
import time

from fastapi import APIRouter, HTTPException, Request

import cache
import feature_flags
import report_card_store as store
import sf_client
import watchlist_call_map as wcm
from call_story_compose import compose
from call_story_config import cs1
from call_story_pull import Ambiguous, NotFound, NotSupported
from permissions import can_access
from report_card_build import CallCapReached, CompositeError
from routers import call_story as cs
from routers.auth import get_request_username
from wo_replay import build_replay
from wo_replay_map import _towbook

router = APIRouter()
log = logging.getLogger('watchlist.callmap')
TTL_S = 60
_ID = re.compile(r'^08p[A-Za-z0-9]{12}([A-Za-z0-9]{3})?$')


def _role(request: Request) -> str:
    import users as _users
    username = get_request_username(request)
    if not username:
        raise HTTPException(status_code=401, detail='Not authenticated')
    return (_users.get_user(username) or {}).get('role') or ''


def _story_bits(sa_id: str, sa_number: str | None, notes: list) -> dict:
    """Steps, history, towbook flag and the member's calls/texts. Never raises: a story that cannot be read becomes a note."""
    cfg = cs1()
    bits = {'steps': [], 'history': [], 'extras': None, 'promise': None, 'towbook': False}
    try:
        raw, _state = cs._raw_for(sa_id, cfg)
    except (NotFound, Ambiguous, NotSupported, CallCapReached, RuntimeError) as e:
        log.warning('call map story unavailable for %s: %s', sa_id, type(e).__name__)
        notes.append('The call story could not be read right now.')
        return bits
    story = compose(raw, cfg, sa_number, store.load_snapshot, lambda d: cs._norms(d, cfg), None)
    if not isinstance(story, dict) or story.get('status') == 'no_service_appointment':
        return bits
    bits.update(steps=build_replay(story)['steps'], history=raw.get('history') or [], towbook=bool(_towbook(raw)),
                promise=(story.get('pta') or {}).get('due_initial'))
    if feature_flags.is_on('replay_member_contact') and feature_flags.is_on('call_story'):
        bits['extras'] = _extras(raw, bits['promise'], notes)
    return bits


def _extras(raw: dict, promise, notes: list):
    from replay_extras_pull import pull_extras
    wo_id = raw['wo']['Id']
    hit = cache.get(f'cs_extras:{wo_id}')
    if hit:
        return hit
    try:
        with cs._PULLS:
            out, private = pull_extras(raw, promise)
    except (CallCapReached, CompositeError, RuntimeError) as e:
        log.warning('call map extras failed for %s: %s', wo_id, e)
        notes.append('The member\'s calls and texts could not be read right now.')
        return None
    ttl = cs1()['cache_ttl_sec']['closed' if raw.get('closed') else 'open']
    cache.put(f'cs_extras:{wo_id}', out, ttl=ttl)
    cache.put(f'cs_extras_conv:{wo_id}', private, ttl=ttl)     # lets the text-thread endpoint (replay permission) open a conversation
    return out


def _build(sa_id: str, sa_number, geo: bool, lat, lon) -> dict:
    t0, before = time.time(), sf_client.get_stats()['total_calls']
    notes: list = []
    bits = _story_bits(sa_id, sa_number, notes)
    sf = wcm.pull(sa_id, geo, bits['towbook'], lat, lon)
    out = wcm.assemble(sf, bits, wcm.now_utc())
    out['steps'] = bits['steps']
    out['extras'] = ({k: bits['extras'].get(k) for k in ('calls', 'inbound_texts')} if bits['extras'] else None)
    out['notes'] = notes + (['Towbook garage: no driver GPS, so no drivers are shown.'] if bits['towbook'] else [])
    out['sf_calls'] = sf_client.get_stats()['total_calls'] - before
    log.info('call map %s: sf_calls=%s ms=%d', sa_id, out['sf_calls'], int((time.time() - t0) * 1000))
    return out


@router.get('/api/watchlist/call-map/{sa_id}')
def get_call_map(request: Request, sa_id: str, sa_number: str | None = None, geo: int = 0, lat: float | None = None, lon: float | None = None):
    role = _role(request)
    if role == 'contractor':
        raise HTTPException(status_code=403, detail='Access restricted')
    if not _ID.match(sa_id):
        raise HTTPException(status_code=400, detail='Invalid sa_id')
    if sa_number is not None and not re.match(r'^SA-\d{6,7}$', sa_number):
        sa_number = None
    try:
        out = cache.cached_query(f'call_map:{sa_id}', lambda: _build(sa_id, sa_number, bool(geo), lat, lon), ttl=TTL_S)
    except LookupError:
        raise HTTPException(status_code=404, detail='That service appointment was not found')
    except (CallCapReached, CompositeError, RuntimeError) as e:
        log.warning('call map failed for %s: %s', sa_id, e)
        raise HTTPException(status_code=503, detail='Salesforce is unavailable or busy; try again shortly')
    can_read = can_access(role, 'scheduler.replay')
    out = {**out, 'can_read_texts': can_read, 'now': wcm.now_utc().isoformat(timespec='seconds')}
    if not can_read:
        out['steps'] = wcm.strip_text_content(out['steps'])
    return out
