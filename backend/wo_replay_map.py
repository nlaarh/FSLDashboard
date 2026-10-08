"""Work Order Replay map data: where the member was, where the garage is, and where each driver who held the call was.

Read-only and sequential, bound to this one call. Most calls need no Salesforce read at all:
  driver ids     paired from the story's own history (an id row and a name row share a timestamp)
  garage         the member leg's ServiceTerritory coordinates, already in the story
  GPS pings      first from the day's built Report Card snapshot; only drivers still without a track go to
                 ServiceResourceHistory (Salesforce's slowest object), in one query, each with their own time window
Fallbacks that cost a query: ServiceResource names the history could not pair, ServiceTerritory when the story has no coordinates.
A failed or empty GPS read is reported as a note, never guessed: a driver with fewer than 2 pings has no track.
Towbook garages do not report driver location to Salesforce: for those legs the map has no driver, only the member, the
garage and (when Salesforce has them) the off-platform driver and truck names.
Member location is rounded to 4 decimals (about 11 m). Never returns a phone number or street address.
"""

import re
from datetime import timedelta

from report_card_build import Puller, _in, _iso
from report_card_timeline import Timelines
from utils import parse_dt, to_eastern

MAX_CALLS = 4
WINDOW_BEFORE_MIN = 30     # pings from before the first pick, so the driver is already on the map when picked
WINDOW_AFTER_MIN = 5
MIN_PINGS = 2
MAX_SNAPSHOT_TERRITORIES = 3
_SUFFIX = re.compile(r'\s+\d{2,3}[A-Z]{0,2}$')
_SKIP = re.compile(r'^(Towbook-|\d{3}-\s*(ST|WNY|.*SPOT))', re.I)
_ID = re.compile(r'^[a-zA-Z0-9]{15}$|^[a-zA-Z0-9]{18}$')


def _short(name: str) -> str:
    return _SUFFIX.sub('', name or '').strip()


def _member_sa(sas: list):
    return next((s for s in sas if 'drop' not in ((s.get('WorkType') or {}).get('Name') or '').lower()), sas[0] if sas else None)


def _towbook(raw: dict):
    """{'driver': 'Towbook Driver', 'truck'} when any leg was worked through Towbook; else None. The driver's name is deliberately not returned."""
    placeholder = any(str(h.get('NewValue') or '').startswith('Towbook-') for h in raw.get('history') or [])
    off = [s for s in raw.get('sas') or [] if s.get('Off_Platform_Driver__r') or s.get('Off_Platform_Truck_Id__c')]
    if not placeholder and not off:
        return None
    s = off[-1] if off else {}
    return {'driver': 'Towbook Driver', 'truck': s.get('Off_Platform_Truck_Id__c')}      # Towbook does not tell us who drives: never a name


def driver_names(raw: dict) -> list:
    """Every driver the call was assigned to, as Salesforce names them (with the garage suffix)."""
    names = {h['NewValue'] for h in raw.get('history') or []
             if h.get('Field') == 'ERS_Assigned_Resource__c' and h.get('NewValue') and not _ID.match(h['NewValue'])}
    names |= {(a.get('ServiceResource') or {}).get('Name') for a in raw.get('assigned') or []}
    return sorted(n for n in names if n and not _SKIP.match(n))


def locate(raw: dict) -> dict:
    """{'member': {lat, lon} | None, 'garage': {name, lat, lon} | None} from the story's own rows: no Salesforce read.
    The garage is None when the story has no coordinates for it (an older cached pull)."""
    sa = _member_sa(raw.get('sas') or [])
    member = None if not sa or sa.get('Latitude') is None else {'lat': round(sa['Latitude'], 4), 'lon': round(sa['Longitude'], 4)}
    t = (sa or {}).get('ServiceTerritory') or {}
    garage = None if t.get('Latitude') is None else {'name': t.get('Name'), 'lat': round(t['Latitude'], 5), 'lon': round(t['Longitude'], 5)}
    return {'member': member, 'garage': garage}


def _paired_ids(raw: dict) -> dict:
    """{driver name: ServiceResource id}. Salesforce writes each driver change as an id row and a name row with the
    same timestamp on the same SA, so the pair gives the id without a ServiceResource query."""
    rows = {}
    for h in raw.get('history') or []:
        if h.get('Field') == 'ERS_Assigned_Resource__c' and h.get('NewValue'):
            rows.setdefault((h.get('ServiceAppointmentId'), h.get('CreatedDate')), []).append(h['NewValue'])
    out = {}
    for vals in rows.values():
        ids, names = [v for v in vals if _ID.match(v)], [v for v in vals if not _ID.match(v)]
        if len(ids) == 1 and len(names) == 1:
            out[names[0]] = ids[0]
    return out


def _windows(raw: dict, names: list, sa: dict | None) -> dict:
    """{driver name: (start, end)}: from 30 min before their first assignment to their last un-assignment, or to the
    member leg's On Location (else the last history row), plus 5 min. A driver known only from AssignedResource gets the whole call."""
    hist = raw.get('history') or []
    times = [parse_dt(h['CreatedDate']) for h in hist] or ([parse_dt(sa['CreatedDate'])] if sa else [])
    on_loc = next((parse_dt(h['CreatedDate']) for h in hist if h.get('Field') == 'Status' and h.get('ServiceAppointmentId') == (sa or {}).get('Id')
                   and (h.get('NewValue') or '').lower() == 'on location'), None)
    before, after = timedelta(minutes=WINDOW_BEFORE_MIN), timedelta(minutes=WINDOW_AFTER_MIN)
    swaps = [h for h in hist if h.get('Field') == 'ERS_Assigned_Resource__c']
    out = {}
    for n in names:
        given = [parse_dt(h['CreatedDate']) for h in swaps if h.get('NewValue') == n]
        taken = [parse_dt(h['CreatedDate']) for h in swaps if h.get('OldValue') == n]
        if not given:
            out[n] = (min(times) - before, max(times) + after)
            continue
        end = max(taken) if taken and max(taken) > max(given) else max(max(given), on_loc or max(times))
        out[n] = (min(given) - before, end + after)
    return out


def _snapshot_tracks(raw: dict, sa: dict | None, who: dict, wins: dict, snapshot_for) -> dict:
    """{name: track} from the built Report Card snapshots of the garages that held the call (up to 3): no Salesforce read.
    A snapshot counts only when it was built at or after the driver's window end, so a provisional day is never used."""
    if not sa or not sa.get('CreatedDate') or snapshot_for is None:
        return {}
    tids = [sa.get('ServiceTerritoryId')] + [h['NewValue'] for h in raw.get('history') or []
                                             if h.get('Field') == 'ServiceTerritory' and _ID.match(h.get('NewValue') or '')]
    day = to_eastern(sa['CreatedDate']).date().isoformat()
    found = {}
    for tid in list(dict.fromkeys(t for t in tids if t))[:MAX_SNAPSHOT_TERRITORIES]:
        snap = snapshot_for(tid, day)
        by_id = {d['id']: d for d in (snap or {}).get('drivers') or []}
        for name, rid in who.items():
            t0, t1 = wins[name]
            if name in found or rid not in by_id or parse_dt(snap['built_at']) < t1:
                continue
            pts = [[int(t), round(la, 5), round(lo, 5)] for t, la, lo in by_id[rid].get('gps') or [] if t0.timestamp() <= t <= t1.timestamp()]
            if len(pts) >= MIN_PINGS:
                found[name] = pts
    return found


def pull_map(raw: dict, puller: Puller | None = None, snapshot_for=None) -> dict:
    p = puller or Puller(max_calls=MAX_CALLS)
    notes = []
    sas = raw.get('sas') or []
    sa = _member_sa(sas)
    where = locate(raw)
    wo, garage = where['member'], where['garage']
    if wo is None:
        notes.append('The work order has no location in Salesforce.')

    towbook = _towbook(raw)
    if towbook:
        notes.append('This call went through a Towbook garage. Towbook does not report driver location to Salesforce, so no driver is drawn for that part.')
    names = driver_names(raw)
    ids = {(a.get('ServiceResource') or {}).get('Name'): a.get('ServiceResourceId') for a in raw.get('assigned') or []}
    for n, i in _paired_ids(raw).items():
        ids.setdefault(n, i)
    missing = [n for n in names if n not in ids]
    if missing:
        for r in p.all(f"SELECT Id, Name FROM ServiceResource WHERE Name IN ({_in(missing)})"):
            ids.setdefault(r['Name'], r['Id'])

    final_tid = (sa or {}).get('ServiceTerritoryId')          # the garage that finally had the member leg
    if garage is None and final_tid:                          # a pull saved before the story carried territory coordinates
        rows = [t for t in p.all(f"SELECT Id, Name, Latitude, Longitude FROM ServiceTerritory WHERE Id IN ({_in(sorted({s['ServiceTerritoryId'] for s in sas if s.get('ServiceTerritoryId')}))})")
                if t.get('Latitude') is not None]
        t = next((t for t in rows if t['Id'] == final_tid), rows[0] if rows else None)
        garage = t and {'name': t['Name'], 'lat': round(t['Latitude'], 5), 'lon': round(t['Longitude'], 5)}

    who = {n: i for n, i in ids.items() if n and i and n in names}
    wins = _windows(raw, list(who), sa) if who else {}
    tracks = _snapshot_tracks(raw, sa, who, wins, snapshot_for)
    todo, pings = {n: i for n, i in who.items() if n not in tracks}, {}
    if todo:
        cond = " OR ".join(f"(ServiceResourceId = '{i}' AND CreatedDate >= {_iso(wins[n][0])} AND CreatedDate <= {_iso(wins[n][1])})" for n, i in todo.items())
        t0, t1 = min(wins[n][0] for n in todo), max(wins[n][1] for n in todo)
        try:
            rows = p.all(f"""SELECT ServiceResourceId, Field, NewValue, CreatedDate FROM ServiceResourceHistory
                WHERE Field IN ('LastKnownLatitude','LastKnownLongitude') AND ({cond})""")
        except RuntimeError as e:
            rows = []
            notes.append(f'Driver GPS could not be read from Salesforce ({e}).')
        tl = Timelines({'gps': rows}, t0, t1)
        for name, rid in todo.items():
            a, b = wins[name]
            track = [[t, round(la, 5), round(lo, 5)] for t, la, lo in tl.gps_track(rid, min_gap_s=60, min_move_mi=0.05)
                     if a.timestamp() <= t <= b.timestamp()]
            pings[name] = len(track)
            if len(track) >= MIN_PINGS:
                tracks[name] = track
    drivers = []
    for name in who:
        track = tracks.get(name) or []
        drivers.append({'name': _short(name), 'track': track, 'pings': pings.get(name, len(track)),
                        'source': 'snapshot' if name not in todo else 'salesforce'})
        if not track:
            notes.append(f'No GPS pings for {_short(name)} while this call was open.')
    window = [int(min(w[0] for w in wins.values()).timestamp()), int(max(w[1] for w in wins.values()).timestamp())] if wins else None
    return {'wo': wo, 'garage': garage, 'towbook': towbook, 'drivers': drivers, 'notes': notes, 'window': window, 'sf_calls': p.calls}
