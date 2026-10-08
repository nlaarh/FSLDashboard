"""osrm.route: lon/lat flip, disk cache, soft failures; contractor_dispatch._osrm_leg keeps its old shape."""

import pytest

import osrm


class Resp:
    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


OK = {'code': 'Ok', 'routes': [{'geometry': {'coordinates': [[-78.0, 42.0], [-78.1, 42.1], [-78.2, 42.2]]}, 'distance': 16093.44, 'duration': 600}],
      'waypoints': [{'location': [-78.0, 42.0]}, {'location': [-78.2, 42.2]}]}


@pytest.fixture
def net(monkeypatch):
    seen, disk = {'urls': [], 'puts': []}, {}
    monkeypatch.setattr(osrm.requests, 'get', lambda url, params=None, timeout=None: seen['urls'].append((url, params, timeout)) or Resp(seen.get('body', OK)))
    monkeypatch.setattr(osrm.cache, 'disk_get', lambda k: disk.get(k))
    monkeypatch.setattr(osrm.cache, 'disk_put', lambda k, v, ttl=0: seen['puts'].append((k, ttl)) or disk.__setitem__(k, v))
    return seen


def test_route_flips_lon_lat_once_and_reports_miles_minutes_and_snapped_waypoints(net):
    r = osrm.route([(42.0, -78.0), (42.2, -78.2)])
    assert net['urls'][0][0].endswith('/-78.0,42.0;-78.2,42.2')                      # OSRM wants lon,lat
    assert r == {'coords': [[42.0, -78.0], [42.1, -78.1], [42.2, -78.2]], 'miles': 10.0, 'minutes': 10,
                 'snapped': [[42.0, -78.0], [42.2, -78.2]]}                          # Leaflet wants lat,lon


def test_a_found_route_is_cached_for_a_week_and_reused(net):
    osrm.route([(42.0, -78.0), (42.2, -78.2)])
    osrm.route([(42.000001, -78.000001), (42.2, -78.2)])                             # same road at 5 decimals
    assert len(net['urls']) == 1 and net['puts'][0][1] == 7 * 86400 and net['puts'][0][0].startswith('osrm:')


def test_uncached_route_never_touches_the_disk(net):
    osrm.route([(42.0, -78.0), (42.2, -78.2)], cached=False)
    osrm.route([(42.0, -78.0), (42.2, -78.2)], cached=False)
    assert len(net['urls']) == 2 and net['puts'] == []


def test_no_route_and_network_errors_give_none_and_are_not_cached(net, monkeypatch):
    net['body'] = {'code': 'NoRoute', 'routes': []}
    assert osrm.route([(42.0, -78.0), (42.2, -78.2)]) is None
    monkeypatch.setattr(osrm.requests, 'get', lambda *a, **k: (_ for _ in ()).throw(TimeoutError('slow')))
    assert osrm.route([(42.0, -78.0), (43.0, -78.2)]) is None and net['puts'] == []


def test_bad_points_are_refused_without_a_request(net):
    assert osrm.route([(42.0, -78.0)]) is None and osrm.route([(None, -78.0), (42.0, -78.0)]) is None
    assert net['urls'] == []


def test_timeout_is_passed_through(net):
    osrm.route([(42.0, -78.0), (42.2, -78.2)], timeout=2.5)
    assert net['urls'][0][2] == 2.5


def test_contractor_leg_keeps_its_shape_and_is_not_cached(net):
    from routers.contractor_dispatch import _osrm_leg
    assert _osrm_leg((42.0, -78.0), (42.2, -78.2)) == {'coords': [[42.0, -78.0], [42.1, -78.1], [42.2, -78.2]], 'miles': 10.0, 'minutes': 10}
    assert net['puts'] == [] and _osrm_leg(None, (1, 2)) is None and _osrm_leg((None, 1), (1, 2)) is None
