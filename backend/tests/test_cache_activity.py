"""Salesforce load: refresh a dashboard only while somebody is looking at it."""

import threading
import time

import cache
from refresher import ACTIVE_WINDOW_S, REAL_CACHE_KEY, STARTUP_WARM_KEYS, refresh_due


def _fresh():
    cache._store.clear(); cache._last_read.clear(); cache.set_system_thread(False)


def test_a_users_read_counts_as_someone_looking():
    _fresh()
    assert not cache.recently_read('dash', 900)
    cache.cached_query('dash', lambda: {'x': 1}, ttl=60)            # a user opens the screen
    assert cache.recently_read('dash', 900)


def test_the_refreshers_own_reads_never_count():
    _fresh()
    cache.set_system_thread(True)                                    # what the refresher thread does at start
    cache.cached_query('dash', lambda: {'x': 1}, ttl=60)
    cache.get('dash'); cache.get_stale('dash')
    assert not cache.recently_read('dash', 900)
    cache.set_system_thread(False)


def test_another_threads_system_flag_does_not_hide_a_real_user():
    _fresh()
    t = threading.Thread(target=lambda: cache.set_system_thread(True)); t.start(); t.join()   # flag is per thread
    cache.get('dash')
    assert cache.recently_read('dash', 900)


def test_a_screen_nobody_has_read_for_a_while_stops_counting():
    _fresh()
    cache._last_read['dash'] = time.time() - (ACTIVE_WINDOW_S + 60)
    assert not cache.recently_read('dash', ACTIVE_WINDOW_S)


def test_refresh_only_when_the_interval_passed_and_someone_is_looking():
    assert refresh_due(elapsed=301, interval=300, read_recently=True) is True
    assert refresh_due(elapsed=299, interval=300, read_recently=True) is False       # not due yet
    assert refresh_due(elapsed=900, interval=300, read_recently=False) is False      # due, but nobody is looking: 0 calls
    assert refresh_due(elapsed=0, interval=300, read_recently=False, warm_once=True) is True   # the one-time warm-up after a restart


def test_command_center_refresh_watches_the_key_the_endpoint_really_uses():
    assert REAL_CACHE_KEY['command_center_24'] == 'command_center_24h' and REAL_CACHE_KEY['command_center_4'] == 'command_center_4h'
    assert 'command_center_24' in STARTUP_WARM_KEYS


def test_dashboards_are_up_to_five_minutes_old_not_thirty_seconds():
    import inspect
    from routers import command_center
    src = inspect.getsource(command_center.command_center)
    assert 'DASHBOARD_TTL' in src and 'stale_ttl=900' in src and 'ttl = 120' not in src
    assert cache.DASHBOARD_TTL == 300


def test_the_real_refresher_loop_spends_nothing_on_a_screen_nobody_reads(monkeypatch):
    """Drive _refresh_loop with a fake clock: one dashboard a user keeps reading, one nobody reads, for 2 simulated hours."""
    import refresher

    class Clock:
        now = 1_000_000.0
        def time(self): return self.now
        def sleep(self, s): self.now += s
    clock, ran = Clock(), []

    class Stop(BaseException): pass

    def fake_sleep(s):
        clock.sleep(s)
        cache._last_read['watched'] = clock.now                    # a user has the 'watched' screen open all the time
        if clock.now - 1_000_000.0 > 2 * 3600:
            raise Stop()

    fake_time = type('T', (), {'time': staticmethod(clock.time), 'sleep': staticmethod(fake_sleep), 'strftime': staticmethod(__import__('time').strftime)})
    _fresh(); cache._last_read['watched'] = clock.now
    monkeypatch.setattr(refresher, 'time', fake_time)
    monkeypatch.setattr(cache, 'time', fake_time)                       # the same clock for 'read recently'
    monkeypatch.setattr(refresher, '_get_schedule', lambda: [(300, 'watched', lambda: {'k': 1}, False), (300, 'ignored', lambda: {'k': 2}, False)])
    monkeypatch.setattr(refresher, '_try_become_leader', lambda: True)
    monkeypatch.setattr(refresher, '_renew_leadership', lambda: None)
    monkeypatch.setattr(refresher, '_run_nightly_jobs', lambda: None)
    monkeypatch.setattr(refresher, '_warm_watchlist', lambda: None)
    monkeypatch.setattr(refresher, '_refresh_one', lambda key, fn, interval, persist: ran.append(key) or True)
    try:
        refresher._refresh_loop()
    except Stop:
        pass
    assert ran.count('watched') >= 20 and 'ignored' not in ran         # ~24 refreshes in 2 h for the watched one, none for the other
