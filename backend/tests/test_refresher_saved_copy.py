"""After a deploy the landing-page screens are warmed one at a time, and the last saved copy answers first."""

import cache
import refresher
from refresher import STARTUP_WARM_KEYS


def test_landing_page_screens_are_warmed_after_a_deploy():
    for key in ('command_center_4', 'ops_brief', 'scheduler_insights_today', 'gps_health', 'map_drivers', 'ops_territories'):
        assert key in STARTUP_WARM_KEYS


def test_every_warm_key_is_on_the_refresh_schedule():
    assert set(STARTUP_WARM_KEYS) <= {entry[1] for entry in refresher._get_schedule()}


def test_saved_copy_answers_before_the_first_refresh(monkeypatch):
    saved = {'command_center_4h': {'n': 4}, 'ops_brief': {'n': 1}}
    monkeypatch.setattr(cache, 'disk_get_stale', lambda k: saved.get(k.removeprefix('saved:')))
    for k in ('command_center_4h', 'ops_brief', 'gps_health'):
        cache._store.pop(k, None)
    refresher._restore_saved_copies(('command_center_4', 'ops_brief', 'gps_health'))
    assert cache.get('command_center_4h') == {'n': 4}        # restored under the key the endpoint really reads
    assert cache.get('ops_brief') == {'n': 1}
    assert cache.get('gps_health') is None                   # nothing saved: nothing invented


def test_saved_copy_never_replaces_data_already_in_memory(monkeypatch):
    monkeypatch.setattr(cache, 'disk_get_stale', lambda k: {'old': True})
    cache.put('ops_brief', {'new': True}, 300)
    refresher._restore_saved_copies(('ops_brief',))
    assert cache.get('ops_brief') == {'new': True}


def test_refresh_saves_a_copy_under_the_saved_key(monkeypatch):
    written = {}
    monkeypatch.setattr(cache, 'disk_put', lambda k, d, ttl=0: written.update({k: (d, ttl)}))
    assert refresher._refresh_one('command_center_4', lambda: {'n': 4}, 300, False)
    assert written['saved:command_center_4h'][0]['n'] == 4
    assert written['saved:command_center_4h'][1] == 86400
