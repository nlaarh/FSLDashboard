"""Work Order Replay map data: where the member was, where the garage is, and where each driver who held the call was.

Read-only and sequential, at most MAX_CALLS Salesforce queries, all bounded to this one call:
  1 ServiceResource    driver names from the history -> ids (history stores names, not ids)
  2 ServiceTerritory   garage coordinates
  3 ServiceResourceHistory   GPS pings for those few drivers inside the call's window (Salesforce's slowest object)
A failed or empty GPS read is reported as a note, never guessed: a driver with fewer than 2 pings has no track.
Towbook garages do not report driver location to Salesforce: for those legs the map has no driver, only the member, the
garage and (when Salesforce has them) the off-platform driver and truck names.
Member location is rounded to 4 decimals (about 11 m). Never returns a phone number or street address.
"""

import re
from datetime import timedelta

from report_card_build import Puller, _in, _iso
from report_card_timeline import Timelines
from utils import parse_dt

MAX_CALLS = 4
WINDOW_BEFORE_MIN = 30     # pings from before the first pick, so the driver is already on the map when picked
WINDOW_AFTER_MIN = 5
MIN_PINGS = 2
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


def pull_map(raw: dict, puller: Puller | None = None) -> dict:
    p = puller or Puller(max_calls=MAX_CALLS)
    notes = []
    sas = raw.get('sas') or []
    sa = _member_sa(sas)
    wo = None if not sa or sa.get('Latitude') is None else {'lat': round(sa['Latitude'], 4), 'lon': round(sa['Longitude'], 4)}
    if wo is None:
        notes.append('The work order has no location in Salesforce.')

    towbook = _towbook(raw)
    if towbook:
        notes.append('This call went through a Towbook garage. Towbook does not report driver location to Salesforce, so no driver is drawn for that part.')
    ids = {(a.get('ServiceResource') or {}).get('Name'): a.get('ServiceResourceId') for a in raw.get('assigned') or []}
    missing = [n for n in driver_names(raw) if n not in ids]
    if missing:
        for r in p.all(f"SELECT Id, Name FROM ServiceResource WHERE Name IN ({_in(missing)})"):
            ids.setdefault(r['Name'], r['Id'])

    terr_ids = sorted({s.get('ServiceTerritoryId') for s in sas if s.get('ServiceTerritoryId')})
    final_tid = (sa or {}).get('ServiceTerritoryId')          # the garage that finally had the member leg
    garage = None
    if terr_ids:
        rows = [t for t in p.all(f"SELECT Id, Name, Latitude, Longitude FROM ServiceTerritory WHERE Id IN ({_in(terr_ids)})")
                if t.get('Latitude') is not None]
        t = next((t for t in rows if t['Id'] == final_tid), rows[0] if rows else None)
        garage = t and {'name': t['Name'], 'lat': round(t['Latitude'], 5), 'lon': round(t['Longitude'], 5)}

    times = [parse_dt(h['CreatedDate']) for h in raw.get('history') or []] or [parse_dt(sa['CreatedDate'])] if sa else []
    drivers, who = [], {n: i for n, i in ids.items() if n and i and n in driver_names(raw)}
    if who and times:
        t0, t1 = min(times) - timedelta(minutes=WINDOW_BEFORE_MIN), max(times) + timedelta(minutes=WINDOW_AFTER_MIN)
        try:
            rows = p.all(f"""SELECT ServiceResourceId, Field, NewValue, CreatedDate FROM ServiceResourceHistory
                WHERE Field IN ('LastKnownLatitude','LastKnownLongitude') AND ServiceResourceId IN ({_in(who.values())})
                AND CreatedDate >= {_iso(t0)} AND CreatedDate <= {_iso(t1)}""")
        except RuntimeError as e:
            rows = []
            notes.append(f'Driver GPS could not be read from Salesforce ({e}).')
        tl = Timelines({'gps': rows}, t0, t1)
        for name, rid in who.items():
            track = [pt for pt in tl.gps_track(rid, min_gap_s=60, min_move_mi=0.05) if t0.timestamp() <= pt[0] <= t1.timestamp()]
            track = [[t, round(la, 5), round(lo, 5)] for t, la, lo in track]
            drivers.append({'name': _short(name), 'track': track if len(track) >= MIN_PINGS else [], 'pings': len(track)})
            if len(track) < MIN_PINGS:
                notes.append(f'No GPS pings for {_short(name)} while this call was open.')
    return {'wo': wo, 'garage': garage, 'towbook': towbook, 'drivers': drivers, 'notes': notes, 'window': [int(t0.timestamp()), int(t1.timestamp())] if who and times else None,
            'sf_calls': p.calls}
