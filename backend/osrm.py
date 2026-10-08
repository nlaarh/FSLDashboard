"""Street routing through the public OSRM demo server (the contractor map and the Work Order Replay use it).

No key, no signup, no bill, no SLA: every failure is soft. route() returns None and the caller draws a straight line.
Swapping in a paid router (Google Directions, Mapbox) means changing route() and nothing else.
"""

import hashlib
import logging

import requests

import cache

log = logging.getLogger('osrm')

OSRM_URL = 'https://router.project-osrm.org/route/v1/driving'
OSRM_TIMEOUT = 8
CACHE_TTL_S = 7 * 86400
METERS_PER_MILE = 1609.344


def _key(points: list) -> str:
    return 'osrm:' + hashlib.sha1(';'.join(f'{la:.5f},{lo:.5f}' for la, lo in points).encode()).hexdigest()


def route(points: list, timeout: float = OSRM_TIMEOUT, cached: bool = True) -> dict | None:
    """Street path through (lat, lon) waypoints, in order, or None if unroutable.

    Returns {'coords': [[lat, lon]...], 'miles', 'minutes', 'snapped': [[lat, lon] per waypoint]}.
    OSRM takes lon,lat and returns lon,lat; Leaflet wants lat,lon. The flip happens in this file only.
    A found route is kept on disk for 7 days (the same points always give the same road); a failure is never kept.
    """
    if len(points) < 2 or any(p is None or p[0] is None or p[1] is None for p in points):
        return None
    key = _key(points)
    if cached and (hit := cache.disk_get(key)):
        return hit
    try:
        r = requests.get(f"{OSRM_URL}/{';'.join(f'{lo},{la}' for la, lo in points)}",
                         params={'overview': 'full', 'geometries': 'geojson'}, timeout=timeout)
        d = r.json()
        if d.get('code') != 'Ok' or not d.get('routes'):
            log.info('osrm: no route (%s)', d.get('code'))
            return None
        rt = d['routes'][0]
        out = {
            'coords': [[c[1], c[0]] for c in rt['geometry']['coordinates']],
            'miles': round(rt['distance'] / METERS_PER_MILE, 1),
            'minutes': round(rt['duration'] / 60),
            'snapped': [[w['location'][1], w['location'][0]] for w in d['waypoints']],
        }
    except Exception as exc:
        log.info('osrm: route failed: %s', exc)
        return None
    if cached:
        cache.disk_put(key, out, ttl=CACHE_TTL_S)
    return out
