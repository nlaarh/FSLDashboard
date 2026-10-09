"""After a restart only the hot screens are refreshed straight away; the rest wait their interval."""

from refresher import STARTUP_WARM_KEYS, initial_refresh_times

KEYS = ['queue_live', 'command_center_24', 'garages_list', 'ops_brief', 'map_grids', 'pta_advisor']   # map_grids, pta_advisor: not warmed


def test_only_the_hot_keys_are_due_immediately():
    t = initial_refresh_times(KEYS, now=1000.0, refresh_all=False)
    assert {k for k, v in t.items() if v == 0.0} == set(STARTUP_WARM_KEYS) & set(KEYS)
    assert all(v == 1000.0 for k, v in t.items() if k not in STARTUP_WARM_KEYS)


def test_emergency_flag_still_refreshes_everything():
    assert set(initial_refresh_times(KEYS, now=1000.0, refresh_all=True).values()) == {0.0}


def test_a_hot_key_missing_from_the_schedule_is_ignored():
    assert initial_refresh_times(['map_grids'], now=5.0, refresh_all=False) == {'map_grids': 5.0}
