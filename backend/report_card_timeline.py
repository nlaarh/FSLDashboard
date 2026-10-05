"""Scheduler Report Card: driver timelines from raw Salesforce rows. Pure, no I/O.

On shift = truck login (AssetHistory ERS_Driver__c) minus ResourceAbsence (spec S8).
GPS = ServiceResourceHistory, newest fix <= t + slack and no older than max age (spec S11).
The login/interval rules mirror Henry's validated script (validation/analyze.py), which
also handles driver swaps and logouts whose login happened before the lookback window.
dispatch_utils.build_truck_login_hist only knows pure login/logout rows, so it is not used.
"""

from bisect import bisect_right
from collections import defaultdict
from datetime import timedelta

from utils import parse_dt, haversine

PRE_WINDOW_LOGIN_HOURS = 10   # logout with no login in the pull: treat as logged in since this


class Timelines:
    """Lookups over one garage-day: logins, truck capabilities, absences, skills, GPS."""

    def __init__(self, raw: dict, day_start, day_end):
        self.day_start, self.day_end = day_start, day_end
        open_end = day_end + timedelta(hours=2)
        ah = sorted(raw.get('asset_history') or [], key=lambda a: a['CreatedDate'])
        self.logins = _login_intervals(ah, day_start - timedelta(hours=PRE_WINDOW_LOGIN_HOURS), open_end)
        self.trucks = _truck_intervals(ah, open_end)
        self.caps = {a['Id']: {c.strip() for c in (a.get('ERS_Truck_Capabilities__c') or '').split(';') if c.strip()}
                     for a in raw.get('assets') or []}
        self.truck_names = {a['Id']: a.get('Name') for a in raw.get('assets') or []}
        self.absences = defaultdict(list)
        for r in raw.get('absences') or []:
            a, b = parse_dt(r.get('Start')), parse_dt(r.get('End'))
            if a and b:
                self.absences[r['ResourceId']].append((a, b, r.get('Type')))
        self.skills = defaultdict(set)
        for x in raw.get('skills') or []:
            self.skills[x['ServiceResourceId']].add((x.get('Skill') or {}).get('MasterLabel'))
        self.lat, self.lon = _gps_series(raw.get('gps') or [])

    # ── shift ──
    def on_shift(self, d: str, t) -> bool:
        if not any(a <= t < b for a, b in self.logins.get(d, ())):
            return False
        return not any(a <= t < b for a, b, _ in self.absences.get(d, ()))

    def truck_caps(self, d: str, t) -> set:
        for a, b, aid in self.trucks.get(d, ()):
            if a <= t < b:
                return self.caps.get(aid, set())
        return set()

    def qualified(self, d: str, required: set, t) -> bool:
        """WOLI skills are a subset of driver skills plus the logged-in truck's capabilities (S9)."""
        if not required:
            return True
        return required <= (self.skills.get(d, set()) | self.truck_caps(d, t))

    # ── GPS ──
    def position(self, d: str, t, max_age_min: float = 30, slack_min: float = 5):
        """(lat, lon, fix_ts) or None when there is no fix or it is too old."""
        cut = t + timedelta(minutes=slack_min)
        la = _latest(self.lat.get(d), cut)
        lo = _latest(self.lon.get(d), cut)
        if la is None or lo is None:
            return None
        if max_age_min is not None and (t - la[0]).total_seconds() / 60 > max_age_min:
            return None
        return la[1], lo[1], la[0]

    def gps_track(self, d: str, keep_at=(), min_gap_s: int = 120, min_move_mi: float = 0.1) -> list:
        """Downsampled [epoch_s, lat, lon] (architecture 5.4). keep_at = timestamps whose
        preceding fix must survive (assignment events)."""
        lats = self.lat.get(d) or ([], [])
        lons = self.lon.get(d) or ([], [])
        if not lats[0] or not lons[0]:
            return []
        forced = set()
        for t in keep_at:
            i = bisect_right(lats[0], t) - 1
            if i >= 0:
                forced.add(i)
        out, last = [], None
        for i, (ts, la) in enumerate(zip(*lats)):
            lo = _latest(self.lon.get(d), ts)
            if lo is None:
                continue
            if (last is None or i in forced or (ts - last[0]).total_seconds() >= min_gap_s
                    or (haversine(last[1], last[2], la, lo[1]) or 0) >= min_move_mi):
                out.append([int(ts.timestamp()), la, lo[1]])
                last = (ts, la, lo[1])
        return out


def _latest(series, cut):
    if not series:
        return None
    ts, vals = series
    i = bisect_right(ts, cut) - 1
    return (ts[i], vals[i]) if i >= 0 else None


def _gps_series(rows: list):
    lat, lon = defaultdict(list), defaultdict(list)
    for g in rows:
        try:
            v = float(g['NewValue'])
        except (TypeError, ValueError, KeyError):
            continue
        ts = parse_dt(g.get('CreatedDate'))
        if ts is None:
            continue
        (lat if g.get('Field') == 'LastKnownLatitude' else lon)[g['ServiceResourceId']].append((ts, v))
    def pack(series: dict) -> dict:
        out = {}
        for k, v in series.items():
            v.sort(key=lambda x: x[0])
            out[k] = ([t for t, _ in v], [x for _, x in v])
        return out
    return pack(lat), pack(lon)


def _login_intervals(ah: list, pre_start, open_end) -> dict:
    """Per driver [(start, end)] from login/logout/swap rows (Henry's shift rule)."""
    ev = defaultdict(list)
    for a in ah:
        t, old, new = parse_dt(a['CreatedDate']), a.get('OldValue'), a.get('NewValue')
        if new and not old:
            ev[new].append((t, 'in'))
        elif old and not new:
            ev[old].append((t, 'out'))
        elif old and new:
            ev[old].append((t, 'out'))
            ev[new].append((t, 'in'))
    out = defaultdict(list)
    for d, es in ev.items():
        es.sort(key=lambda x: (x[0], x[1]))
        cur = None
        for t, k in es:
            if k == 'in' and cur is None:
                cur = t
            elif k == 'out' and cur is not None:
                out[d].append((cur, t))
                cur = None
            elif k == 'out':
                out[d].append((pre_start, t))
        if cur is not None:
            out[d].append((cur, open_end))
    return dict(out)


def _truck_intervals(ah: list, open_end) -> dict:
    """Per driver [(start, end, asset_id)]: which truck they were in, for its capabilities."""
    out, opened = defaultdict(list), {}
    for a in ah:
        t, old, new = parse_dt(a['CreatedDate']), a.get('OldValue'), a.get('NewValue')
        if old and (old, a['AssetId']) in opened:
            out[old].append((opened.pop((old, a['AssetId'])), t, a['AssetId']))
        if new:
            opened[(new, a['AssetId'])] = t
    for (d, aid), t in opened.items():
        out[d].append((t, open_end, aid))
    return dict(out)
