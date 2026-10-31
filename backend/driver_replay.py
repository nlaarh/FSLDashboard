"""Driver Replay: one driver's day from the saved garage-day snapshot, as stops and drives a supervisor can follow.

A stop = the truck stayed within STOP_RADIUS_M for at least MIN_STOP_S (MIN_CALL_STOP_S at one of the driver's own calls:
a jump start or lockout can take less than 5 minutes). Salesforce only records a position when it changes,
so a parked truck often leaves one ping and then nothing until it moves again: when the next ping is close, the stop is
taken to last until shortly before it (the drive time at city speed), not just until the last ping.
Each stop is named, first match wins: a call the driver held at that time, parked outside the shift, the garage, the driver's
home base, a place from the New York place list (geo/ny_places.json, OpenStreetMap; "Near ..." when the truck stood a little
away from the place's point), else "Unlisted stop". Back-to-back stops with the same name are one stop.
The track is re-timed so a parked truck stays put and then drives (a straight line between two pings 40 minutes apart would
crawl across the map). No Salesforce and no outside service: the snapshot already holds the GPS, the place list is a file.
"""

import json
import math
import os
import threading

R_M = 6371000
STOP_RADIUS_M = 150
MIN_STOP_S = 300
MIN_CALL_STOP_S = 120
CITY_MPS = 11            # about 25 mph: how long the drive from the stop to the next ping took
LEAVE_MAX_M = 3000       # a next ping further than this after a long silence is a GPS gap, not the end of a stop
GAP_S = 20 * 60          # silence longer than this with a far next ping = no signal (same as the player's GPS_GAP_S)
CALL_RADIUS_M = 300
GARAGE_RADIUS_M = 300
PLACE_RADIUS_M = {'bigstore': 220, 'grocery': 180}   # big parking lots: the store's point can be far from where the truck parks
PLACE_RADIUS_DEFAULT_M = 110
PLACE_SURE_M = {'bigstore': 150, 'grocery': 120}      # closer than this = "at" the place; further (up to the radius) = "near" it
PLACE_SURE_DEFAULT_M = 50
MERGE_GAP_S = 180        # same-name stops this close in time are one stop (the cluster drifted past STOP_RADIUS_M)
PLACES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'geo', 'ny_places.json')
CELL = 0.01              # place index cell, degrees (about 1.1 km north-south)

KIND_LABEL = {
    'coffee': 'Coffee', 'food': 'Food', 'gas': 'Gas station', 'store': 'Store', 'bigstore': 'Store', 'grocery': 'Grocery',
    'pharmacy': 'Pharmacy', 'bank': 'Bank', 'post': 'Post office', 'bar': 'Bar or pub', 'auto': 'Auto parts',
}


def metres(a_lat, a_lon, b_lat, b_lon) -> float:
    h = (math.sin(math.radians(b_lat - a_lat) / 2) ** 2
         + math.cos(math.radians(a_lat)) * math.cos(math.radians(b_lat)) * math.sin(math.radians(b_lon - a_lon) / 2) ** 2)
    return 2 * R_M * math.asin(math.sqrt(h))


def _d(p, q) -> float:
    return metres(p[1], p[2], q[1], q[2])


def find_stops(track: list, radius_m: float = STOP_RADIUS_M, min_s: int = MIN_STOP_S) -> list:
    """[{'t0', 't1', 'lat', 'lon', 'first', 'last'}] from [[t, lat, lon]...] sorted by time. first/last = ping indexes."""
    stops, i, n = [], 0, len(track)
    while i < n:
        j = i
        while j + 1 < n and _d(track[i], track[j + 1]) <= radius_m:
            j += 1
        end = track[j][0]
        if j + 1 < n:
            nxt = track[j + 1]
            far = _d(track[j], nxt)
            if far <= LEAVE_MAX_M:
                end = max(end, int(nxt[0] - far / CITY_MPS))
        if end - track[i][0] >= min_s:
            pts = track[i:j + 1]
            stops.append({'t0': track[i][0], 't1': end, 'first': i, 'last': j,
                          'lat': round(sum(p[1] for p in pts) / len(pts), 5), 'lon': round(sum(p[2] for p in pts) / len(pts), 5)})
            i = j + 1
        else:
            i += 1
    return stops


def gaps(track: list, stops: list) -> list:
    """[[t0, t1]] silences longer than GAP_S that are not a stop (the truck reappears far away)."""
    inside = {k for s in stops for k in range(s['first'], s['last'] + 1)}
    out = []
    for k, (a, b) in enumerate(zip(track, track[1:])):
        if b[0] - a[0] > GAP_S and not (k in inside and _d(a, b) <= LEAVE_MAX_M):
            out.append([a[0], b[0]])
    return out


def retime(track: list, stops: list) -> list:
    """The track with the truck parked at each stop until it leaves: a keyframe at the stop's end, at the stop's last ping."""
    out = [list(p) for p in track]
    for s in reversed(stops):
        last = track[s['last']]
        if s['t1'] > last[0]:
            out.insert(s['last'] + 1, [s['t1'], last[1], last[2]])
    return out


class Places:
    """The New York place list, indexed by grid cell. Loaded once, on first use."""
    _lock = threading.Lock()
    _grid = None

    @classmethod
    def grid(cls) -> dict:
        with cls._lock:
            if cls._grid is None:
                try:
                    with open(PLACES_FILE) as f:
                        rows = json.load(f)['places']
                except (OSError, ValueError, KeyError):
                    rows = []
                g = {}
                for lat, lon, name, kind in rows:
                    g.setdefault((int(lat // CELL), int(lon // CELL)), []).append((lat, lon, name, kind))
                cls._grid = g
            return cls._grid

    @classmethod
    def nearest(cls, lat: float, lon: float):
        """{'name', 'kind', 'm'} of the closest place within its kind's radius, or None."""
        g, best = cls.grid(), None
        ci, cj = int(lat // CELL), int(lon // CELL)
        for i in range(ci - 1, ci + 2):
            for j in range(cj - 1, cj + 2):
                for plat, plon, name, kind in g.get((i, j), ()):
                    m = metres(lat, lon, plat, plon)
                    if m <= PLACE_RADIUS_M.get(kind, PLACE_RADIUS_DEFAULT_M) and (best is None or m < best['m']):
                        best = {'name': name, 'kind': kind, 'm': round(m)}
        return best


def label(stop: dict, driver_id: str, calls: list, garage: dict, home: dict, shifts: list = ()) -> dict:
    """What the stop was: {'kind', 'label', 'call'?}. calls = replay calls (lat, lon, number, holds); shifts = [[t0, t1]].
    Only a call this driver held during the stop counts: standing next to another driver's call is not "at a call"."""
    lat, lon, t0, t1 = stop['lat'], stop['lon'], stop['t0'], stop['t1']
    best = None
    for c in calls:
        if c.get('lat') is None:
            continue
        m = metres(lat, lon, c['lat'], c['lon'])
        if m <= CALL_RADIUS_M and any(h[0] == driver_id and h[1] < t1 and h[2] > t0 for h in c.get('holds') or []):
            if best is None or m < best[0]:
                best = (m, c)
    if best:
        return {'kind': 'call', 'label': f"At call {best[1]['number']}", 'call': best[1]['number']}
    if shifts and not any(a < t1 and b > t0 for a, b in shifts):
        return {'kind': 'off', 'label': 'Parked, off shift'}
    if garage.get('lat') is not None and metres(lat, lon, garage['lat'], garage['lon']) <= GARAGE_RADIUS_M:
        return {'kind': 'garage', 'label': 'At the garage'}
    if home.get('lat') is not None and metres(lat, lon, home['lat'], home['lon']) <= GARAGE_RADIUS_M:
        return {'kind': 'home', 'label': 'At home base'}
    p = Places.nearest(lat, lon)
    if p:
        name = p['name'] or KIND_LABEL.get(p['kind'], 'Place')
        near = p['m'] > PLACE_SURE_M.get(p['kind'], PLACE_SURE_DEFAULT_M)
        return {'kind': p['kind'], 'label': f'Near {name}' if near else name, 'place_kind': KIND_LABEL.get(p['kind']), 'place_m': p['m']}
    return {'kind': 'unknown', 'label': 'Unlisted stop'}


def merge(stops: list) -> list:
    """Back-to-back stops with the same name become one (first ping of the first to the end of the last)."""
    out = []
    for s in stops:
        prev = out[-1] if out else None
        if prev and prev['label'] == s['label'] and s['t0'] - prev['t1'] <= MERGE_GAP_S:
            prev.update(t1=max(prev['t1'], s['t1']), last=s['last'])
        else:
            out.append(dict(s))
    return out


def summary(track: list, stops: list, gap_list: list) -> dict:
    """Seconds driving, stopped by kind, and without signal, between the first and last ping."""
    if len(track) < 2:
        return {'driving_s': 0, 'stopped_s': {}, 'no_signal_s': 0, 'miles': 0}
    total = track[-1][0] - track[0][0]
    by = {}
    for s in stops:
        by[s['kind']] = by.get(s['kind'], 0) + (s['t1'] - s['t0'])
    stopped = sum(by.values())
    silent = sum(b - a for a, b in gap_list)
    in_stop = [(s['first'], s['last']) for s in stops]
    miles = 0.0
    for k, (a, b) in enumerate(zip(track, track[1:])):
        if not any(f <= k < l for f, l in in_stop) and b[0] - a[0] <= GAP_S:
            miles += _d(a, b) / 1609.344
    return {'driving_s': max(0, total - stopped - silent), 'stopped_s': by, 'no_signal_s': silent, 'miles': round(miles, 1)}


def shift(d: dict, d0: int, d1: int) -> list:
    """[[t0, t1]] the driver was logged in (or had a truck) during the day d0..d1, clipped to it, epoch seconds.
    The snapshot also holds logins from the day before; those are not this day's shift."""
    from report_card_replay import _s
    spans = [[_s(x['start']), _s(x['end'])] for x in (d.get('logins') or d.get('trucks') or []) if x.get('start')]
    return sorted([max(a, d0), min(b, d1)] for a, b in spans if a and b and b > a and a < d1 and b > d0)


def driver_day(snap: dict, replay: dict, driver_id: str) -> dict | None:
    """Everything the Driver Replay tab draws for one driver, or None when the driver is not in the day.
    replay = report_card_replay.replay_view(snap) (its calls carry the holds)."""
    d = next((x for x in snap['drivers'] if x['id'] == driver_id), None)
    if d is None:
        return None
    d0, d1 = replay['day_start'], replay['day_end']
    track = sorted(([int(t), round(la, 5), round(lo, 5)] for t, la, lo in d.get('gps') or [] if d0 <= t <= d1), key=lambda p: p[0])
    done = sum(1 for sa in snap['sas'] if sa['in_day'] and not sa.get('is_drop_off') and sa.get('final_driver_id') == driver_id)
    base = {'id': d['id'], 'name': d['name'], 'shift': shift(d, d0, d1), 'calls_done': done}
    if len(track) < 2:
        return {**base, 'mode': 'none', 'track': [], 'stops': [], 'gaps': [], 'summary': summary([], [], [])}
    terr = replay['territory']
    stops = find_stops(track, min_s=MIN_CALL_STOP_S)
    for s in stops:
        s.update(label(s, driver_id, replay['calls'], {'lat': terr.get('lat'), 'lon': terr.get('lon')}, d.get('home_base') or {}, base['shift']))
    stops = merge([s for s in stops if s['kind'] == 'call' or s['t1'] - s['t0'] >= MIN_STOP_S])
    gap_list = gaps(track, stops)
    return {**base, 'mode': 'gps', 'track': retime(track, stops),
            'stops': [{k: v for k, v in s.items() if k not in ('first', 'last')} for s in stops],
            'gaps': gap_list, 'summary': summary(track, stops, gap_list)}
