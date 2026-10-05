"""Call Story: "normal" stage times from report-card day snapshots (architecture 5). 0 Salesforce calls.

Per snapshot, once: every scored SA's segments (call_story_segments.extract) are saved next to the snapshot
as <tid>_<date>.segments.cs1.json, regenerated when the snapshot is newer. At story time the rows for the 56 days
before the call (anchored to the call, so a story reads the same tomorrow) are pooled into percentiles with the
fallback chain: garage x channel x key x 4 h block x daytype -> garage x channel x key -> channel x key
(all garages) -> key over all channels, only for the dispatcher-owned S7/S8/S9 (O5) -> none.
"""

from collections import defaultdict
from datetime import date, timedelta

import report_card_store as store
from call_story_segments import extract, norm_key
from utils import parse_dt

LEVELS = ('garage_channel_segment_block', 'garage_channel_segment', 'channel_segment', 'segment_all_channels')


def segment_rows(snapshot: dict, cfg: dict) -> list:
    """Compact norm rows for every in-day, non-drop SA of a snapshot."""
    jobs = defaultdict(list)
    for s in snapshot['sas']:
        if s.get('busy') and s.get('final_driver_id') and not s['is_drop_off']:
            jobs[s['final_driver_id']].append((parse_dt(s['busy'][0]), parse_dt(s['busy'][1]), s['id']))

    def open_jobs(d, t, exclude):
        return sum(1 for a, b, sid in jobs.get(d, ()) if a <= t < b and sid != exclude)
    channels = {d['id']: d['channel'] for d in snapshot['drivers']}
    out = []
    for sa in snapshot['sas']:
        if not sa['in_day'] or sa['is_drop_off']:
            continue
        for seg in extract(sa, cfg, open_jobs, channels.get, snapshot['territory']['name']):
            if seg['minutes'] is not None:
                out.append({'g': seg['garage'], 'c': seg['channel'], 'k': norm_key(seg), 'm': seg['minutes'],
                            'b': seg['et_hour_block'], 'd': seg['daytype']})
    return out


def day_rows(territory_id: str, service_date: str, cfg: dict) -> list:
    cached = store.load_segments(territory_id, service_date)
    if cached is not None:
        return cached['rows']
    snap = store.load_snapshot(territory_id, service_date)
    if snap is None:
        return []
    rows = segment_rows(snap, cfg)
    store.save_segments(territory_id, service_date, {'rules_version': cfg['rules_version'], 'rows': rows})
    return rows


class Norms:
    def __init__(self, rows_by_day: dict, window: tuple, cfg: dict):
        self.rows = [r for rows in rows_by_day.values() for r in rows]
        self.days = len(rows_by_day)
        self.window = window
        self.cfg = cfg
        self._cache = {}

    @classmethod
    def for_call(cls, call_date: str, cfg: dict) -> 'Norms':
        """All built days in [call_date - lookback, call_date - 1], every garage (levels 3-4 pool garages)."""
        d = date.fromisoformat(call_date)
        lo, hi = (d - timedelta(days=cfg['baseline']['lookback_days'])).isoformat(), (d - timedelta(days=1)).isoformat()
        days = {(t, day): day_rows(t, day, cfg) for t, day in store.list_days() if lo <= day <= hi}
        return cls(days, (lo, hi), cfg)

    def baseline(self, seg: dict) -> dict | None:
        """First level of the fallback chain with n >= min_n; else the deepest level with data, labelled."""
        key = norm_key(seg)
        b = self.cfg['baseline']
        levels = [
            (LEVELS[0], lambda r: r['g'] == seg['garage'] and r['c'] == seg['channel'] and r['k'] == key
             and r['b'] == seg['et_hour_block'] and (not b['split_weekend'] or r['d'] == seg['daytype'])),
            (LEVELS[1], lambda r: r['g'] == seg['garage'] and r['c'] == seg['channel'] and r['k'] == key),
            (LEVELS[2], lambda r: r['c'] == seg['channel'] and r['k'] == key),
        ]
        if seg['kind'] in b['pooled_all_channels_segments']:
            levels.append((LEVELS[3], lambda r: r['k'] == key))
        best = None
        for name, keep in levels:
            vals = sorted(r['m'] for r in self.rows if keep(r))
            if not vals:
                continue
            best = self._stats(name, vals)
            if len(vals) >= b['min_n']:
                return best
        return best

    def _stats(self, level: str, vals: list) -> dict:
        pct = lambda q: round(vals[min(len(vals) - 1, int(q * len(vals)))], 1)
        return {'p50': pct(.5), 'p75': pct(.75), 'p90': pct(.9), 'p95': pct(.95), 'n': len(vals),
                'key_level': level, 'days_covered': self.days, 'window': list(self.window)}
