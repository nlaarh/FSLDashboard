"""Day replay payload: where each driver was and which calls each one held, from the saved snapshot.

Zero Salesforce reads. Times are epoch seconds so the page can scrub without parsing dates.
Driver positions come in two honest kinds:
  gps        the builder's downsampled GPS pings; the page draws a straight line between pings
  estimated  fewer than two pings all day: parked at home base (else the garage), a straight-line drive
             from En Route to arrival, then on scene until the call clears (Studio-style projection)
Member locations are rounded to 4 decimals (about 11 m); this payload is behind the report-card gates.
"""

from datetime import datetime

MIN_GPS_POINTS = 2


def _s(iso: str | None) -> int | None:
    return int(datetime.fromisoformat(iso.replace('Z', '+00:00')).timestamp()) if iso else None


def call_end(sa: dict, day_end: int) -> int:
    m = sa['milestones']
    return _s(m.get('t_end') or m.get('actual_end')) or day_end


def holds(sa: dict, end: int) -> list:
    """[[driver_id, from_s, to_s]]: each pick holds the call until the next pick or the call ends.
    A pick to someone off the roster (SPOT placeholder, another garage) breaks the chain without a span."""
    picks = [(_s(e['ts']), e.get('driver_id')) for e in sa['events'] if e['field'] == 'assigned']
    out = []
    for i, (t, d) in enumerate(picks):
        until = picks[i + 1][0] if i + 1 < len(picks) else end
        if d and until > t:
            out.append([d, t, until])
    return out


def estimated_track(origin: tuple, calls: list) -> list:
    """Keyframes [[t, lat, lon]] from the calls this driver actually ran, in arrival order, never going back in time."""
    pts, here = [], origin
    runs = sorted((c for c in calls if c.get('lat') is not None and _arrival(c)), key=_arrival)
    for c in runs:
        last = pts[-1][0] if pts else 0
        arrive = max(_arrival(c), last)
        leave = min(max(_s(c['milestones'].get('t_er')) or arrive, last), arrive)
        dest = (round(c['lat'], 5), round(c['lon'], 5))
        if leave < arrive:
            pts.append([leave, *here])
        pts.append([arrive, *dest])
        end = _s(c['milestones'].get('t_end') or c['milestones'].get('actual_end'))
        if end and end > arrive:
            pts.append([end, *dest])
        here = dest
    return pts


def parked(track: list, origin: tuple, d0: int, d1: int) -> list:
    """An estimated driver is on the map all day: at the home base (else the garage) before the first call, and where the last call
    left him after it. The day view hides him while he is off shift. With no track at all he simply stays at the origin."""
    if not track:
        return [[d0, *origin], [d1, *origin]]
    head = [[d0, *origin]] if track[0][0] > d0 else []
    tail = [[d1, track[-1][1], track[-1][2]]] if track[-1][0] < d1 else []
    return head + track + tail


def vehicle(d: dict) -> dict:
    """The truck the driver last logged into, as plain text for the truck drawing: its name and what it can do (Flat Bed, Wheel Lift Truck...).
    Taken from the snapshot, so there is no new Salesforce read."""
    last = max(d.get('trucks') or [], key=lambda x: x['start'], default=None)
    return {'truck': last and last.get('truck'), 'skills': sorted(set((last or {}).get('truck_caps') or []) | set(d.get('skills') or []))}


def _arrival(sa: dict) -> int | None:
    m = sa['milestones']
    return _s(m.get('arrival') or m.get('t_ol'))


def towbook_vehicles(calls: list, terr: dict, day_end: int) -> tuple:
    """Towbook reports no driver location to Salesforce, so a Towbook garage has no drivers to draw. Each Towbook call with an
    En Route time becomes one ESTIMATED vehicle: garage -> customer between En Route and arrival, then on scene until the call
    clears. Towbook does not tell us who drives, so they are numbered (Towbook Driver 1, 2, ...) in the order they leave the garage,
    never named. Returns (vehicles shaped like drivers, {call id: hold span}). Marked mode 'estimated' and towbook True."""
    vehicles, spans = [], {}
    if terr.get('lat') is None or terr.get('lon') is None:      # a garage with no coordinates cannot be drawn: no estimated vehicles, no crash
        return vehicles, spans
    runs = []
    for sa in calls:
        if sa.get('channel') != 'towbook' or sa.get('lat') is None:
            continue
        t_er, arr = _s(sa['milestones'].get('t_er')), _arrival(sa)
        if not t_er or not arr or arr < t_er:
            continue
        runs.append((t_er, arr, sa))
    for n, (t_er, arr, sa) in enumerate(sorted(runs, key=lambda r: (r[0], r[2]['number'])), 1):
        end = max(call_end(sa, day_end), arr)
        g, c = (round(terr['lat'], 5), round(terr['lon'], 5)), (round(sa['lat'], 5), round(sa['lon'], 5))
        vid = f"tb:{sa['number']}"
        vehicles.append({'id': vid, 'name': f'Towbook Driver {n}', 'mode': 'estimated', 'gps_points': 0,
                         'towbook': True, 'track': [[t_er, *g], [arr, *c], [end, *c]]})
        spans[sa['id']] = [vid, t_er, end]
    return vehicles, spans


def replay_view(snap: dict) -> dict:
    win = snap['window']
    d0, d1 = _s(win['day_start_utc']), _s(win['day_end_utc'])
    terr = snap['territory']
    in_day = [sa for sa in snap['sas'] if sa['in_day']]
    ran = {}
    for sa in in_day:
        if sa['final_driver_id']:
            ran.setdefault(sa['final_driver_id'], []).append(sa)

    calls = []
    for sa in in_day:
        end = call_end(sa, d1)
        calls.append({
            'id': sa['id'], 'number': sa['number'],
            'lat': None if sa['lat'] is None else round(sa['lat'], 4),
            'lon': None if sa['lon'] is None else round(sa['lon'], 4),
            'created': _s(sa['created']), 'arrival': _arrival(sa), 'end': end,
            'promise_due': _s(sa.get('pta_initial_due') or sa.get('pta_due')),
            'holds': holds(sa, end),
        })
    held = {h[0] for c in calls for h in c['holds']}

    drivers = []
    for d in snap['drivers']:
        gps = [[int(t), round(la, 5), round(lo, 5)] for t, la, lo in d['gps'] if d0 <= t <= d1]
        if len(gps) >= MIN_GPS_POINTS:
            mode, track = 'gps', gps
        else:
            home = d['home_base']
            origin = (home['lat'], home['lon']) if home.get('lat') is not None else (terr['lat'], terr['lon'])
            track = estimated_track(origin, ran.get(d['id'], []))
            mode = 'estimated' if track else 'none'
        if mode == 'none' and d['id'] not in held and not d['logins']:
            continue
        if mode != 'gps':
            mode, track = 'estimated', parked(track, origin, d0, d1)
        drivers.append({'id': d['id'], 'name': d['name'], 'mode': mode, 'gps_points': len(gps), 'track': track, **vehicle(d)})

    tb, tb_spans = towbook_vehicles(in_day, terr, d1)
    for c in calls:
        if c['id'] in tb_spans:
            c['holds'].append(tb_spans[c['id']])
    drivers += tb

    return {
        'territory': {k: terr[k] for k in ('id', 'name', 'lat', 'lon')},
        'service_date': snap['service_date'], 'built_at': snap['built_at'],
        'day_start': d0, 'day_end': d1,
        'drivers': drivers, 'calls': calls,
        'basis': {'towbook': 'Towbook shows no driver location. Its vehicles are drawn from the En Route and On Location times, garage to customer: estimated.',
                  'gps': 'Builder-downsampled GPS pings; straight line between pings.',
                  'estimated': 'No GPS: straight line from the last known place, En Route to arrival.',
                  'member_location': 'Rounded to about 11 m.'},
    }
