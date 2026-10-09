"""Our own record of driver positions, so the Replay map no longer reads ServiceResourceHistory (28 to 44 s, a long
running request in the shared org).

Every 60 s one worker (advisory lock, see speed3_db.leader) asks Salesforce for the FSL drivers whose record changed
since the last run (one small query on ServiceResource, about 0.5 s) and stores each new position. Replay reads the
stored points when the flag `replay_gps_store` is on AND the driver's window is fully covered by successful samples;
anything else goes the old way. Off means no table is touched.
"""

import logging
import time
from datetime import datetime, timedelta, timezone

import db_adapter
import speed3_db
from sf_client import sf_query_all
from utils import parse_dt

log = logging.getLogger('gps_store')

FLAG = 'replay_gps_store'
SAMPLE_EVERY_S = 60
MAX_GAP_S = 300            # a window with no successful sample for longer than this is not "covered"
MAX_LOOKBACK_MIN = 60      # after an outage the sampler asks for at most this much history
KEEP_DAYS = 15         # owner 2026-10-09: no longer than 15 days; older Replay days read Salesforce (not "covered")
HEARTBEAT_S = 300          # a parked driver still gets one point every 5 min
MOVE_DEG = 0.0001          # about 11 m: smaller moves count as parked
RETENTION_EVERY_S = 3600       # hourly, so the table never holds much more than 15 days
MAX_POINTS = 300_000           # hard cap (~2x the expected 15 days): above it nothing is written and Replay reads Salesforce

_last = {}                 # resource id -> (epoch, lat, lon) of the last point stored by this worker
_state = {'retention': 0.0}


def _sample_soql(since: datetime) -> str:
    return ("SELECT Id, LastKnownLatitude, LastKnownLongitude, LastKnownLocationDate FROM ServiceResource "
            f"WHERE IsActive = true AND ResourceType = 'T' AND SystemModstamp >= {since.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")


def keep_point(prev, ts: float, lat: float, lon: float) -> bool:
    """Store a position when it is the first seen, moved about 11 m, or is a 5 minute heartbeat for a parked driver."""
    if prev is None:
        return True
    p_ts, p_lat, p_lon = prev
    if ts <= p_ts:
        return False
    return abs(lat - p_lat) >= MOVE_DEG or abs(lon - p_lon) >= MOVE_DEG or ts - p_ts >= HEARTBEAT_S


def points_from(records: list, last: dict) -> list:
    """[(resource_id, aware datetime, lat, lon)] worth storing from the ServiceResource rows; updates `last`."""
    out = []
    for r in sorted(records, key=lambda r: r.get('LastKnownLocationDate') or ''):
        ts, lat, lon = parse_dt(r.get('LastKnownLocationDate')), r.get('LastKnownLatitude'), r.get('LastKnownLongitude')
        if ts is None or lat is None or lon is None:
            continue
        rid, epoch = r['Id'], ts.timestamp()
        if keep_point(last.get(rid), epoch, lat, lon):
            out.append((rid, ts, float(lat), float(lon)))
            last[rid] = (epoch, lat, lon)
    return out


def sample_once(now: datetime | None = None) -> dict | None:
    """One sampler run. Returns {'rows_seen', 'points_written'} or None when another worker holds the lock.
    The Salesforce read happens inside the lock; nothing is written if it fails, and a failed run records no sample,
    so the gap shows up honestly in the coverage check."""
    now = now or datetime.now(timezone.utc)
    with speed3_db.leader('gps_sampler') as db:
        if db is None:
            return None
        row = db.execute('SELECT max(sampled_at) AS last FROM driver_gps_samples').fetchone()
        floor = now - timedelta(minutes=MAX_LOOKBACK_MIN)
        since = max(speed3_db.as_dt(row['last']) - timedelta(seconds=5), floor) if row and row['last'] else now - timedelta(minutes=5)
        count = db.execute('SELECT count(*) AS n FROM driver_gps_points').fetchone()['n']
        if count >= MAX_POINTS:                  # never grow past the cap; no sample is recorded, so Replay falls back to Salesforce
            log.warning('GPS store at its cap (%s points >= %s): not sampling until the hourly cleanup runs', count, MAX_POINTS)
            return {'rows_seen': 0, 'points_written': 0, 'capped': True}
        records = sf_query_all(_sample_soql(since))
        points = points_from(records, _last)
        written = 0
        for rid, ts, lat, lon in points:
            db.execute('INSERT INTO driver_gps_points (resource_id, ts, lat, lon) VALUES (%s, %s, %s, %s) '
                       'ON CONFLICT DO NOTHING', (rid, speed3_db.iso(ts), lat, lon))
            written += max(db.rowcount, 0)
        db.execute('INSERT INTO driver_gps_samples (sampled_at, rows_seen, points_written) VALUES (%s, %s, %s) '
                   'ON CONFLICT DO NOTHING', (speed3_db.iso(now), len(records), written))
        return {'rows_seen': len(records), 'points_written': written}


def purge(now: datetime | None = None, keep_days: int = KEEP_DAYS) -> dict:
    """Retention: drop points and samples older than `keep_days` (only ever our own two tables)."""
    cut = speed3_db.iso((now or datetime.now(timezone.utc)) - timedelta(days=keep_days))
    with db_adapter.writer() as db:
        db.execute('DELETE FROM driver_gps_points WHERE ts < %s', (cut,))
        points = db.rowcount
        db.execute('DELETE FROM driver_gps_samples WHERE sampled_at < %s', (cut,))
        return {'points': points, 'samples': db.rowcount}


def covered(sample_times: list, t0: datetime, t1: datetime, now: datetime | None = None) -> bool:
    """True when successful samples leave no hole longer than MAX_GAP_S anywhere in [t0, min(t1, now)]."""
    now = now or datetime.now(timezone.utc)
    end = min(t1, now)
    if end <= t0:
        return False
    prev = t0
    for s in sorted(sample_times):
        if s < t0 or s > end:
            continue
        if (s - prev).total_seconds() > MAX_GAP_S:
            return False
        prev = s
    return (end - prev).total_seconds() <= MAX_GAP_S


def stored_gps_rows(wanted: dict, now: datetime | None = None) -> tuple[list, set]:
    """({'ServiceResourceId', 'Field', 'NewValue', 'CreatedDate'} rows shaped like ServiceResourceHistory, ids covered).

    `wanted` is {resource id: (window start, window end)}. A driver whose window is not fully covered is left out of the
    covered set so the caller reads Salesforce for that driver exactly as before. Any database problem returns nothing
    covered. Rows are shaped like the Salesforce history so the same Timelines code downsamples them."""
    if not wanted:
        return [], set()
    try:
        if not speed3_db.ensure_schema('gps'):
            return [], set()
        lo = min(w[0] for w in wanted.values()) - timedelta(seconds=MAX_GAP_S)
        hi = max(w[1] for w in wanted.values()) + timedelta(seconds=MAX_GAP_S)
        with db_adapter.reader() as db:
            samples = [speed3_db.as_dt(r['sampled_at']) for r in db.execute(
                'SELECT sampled_at FROM driver_gps_samples WHERE sampled_at >= %s AND sampled_at <= %s',
                (speed3_db.iso(lo), speed3_db.iso(hi))).fetchall()]
            rows, ok = [], set()
            for rid, (t0, t1) in wanted.items():
                if not covered(samples, t0, t1, now):
                    continue
                ok.add(rid)
                for r in db.execute('SELECT ts, lat, lon FROM driver_gps_points WHERE resource_id = %s AND ts >= %s AND ts <= %s '
                                    'ORDER BY ts', (rid, speed3_db.iso(t0), speed3_db.iso(t1))).fetchall():
                    stamp = speed3_db.as_dt(r['ts']).strftime('%Y-%m-%dT%H:%M:%S.000+0000')
                    rows.append({'ServiceResourceId': rid, 'Field': 'LastKnownLatitude', 'NewValue': repr(r['lat']), 'CreatedDate': stamp})
                    rows.append({'ServiceResourceId': rid, 'Field': 'LastKnownLongitude', 'NewValue': repr(r['lon']), 'CreatedDate': stamp})
        return rows, ok
    except Exception as e:
        log.warning('stored GPS read failed, using Salesforce: %s', e)
        return [], set()


def run_forever():
    """Background loop (one daemon thread per worker; the advisory lock keeps it to one sampler overall)."""
    import feature_flags
    log.info('GPS sampler thread started (idle until flag %s is on)', FLAG)
    while True:
        started = time.time()
        try:
            if feature_flags.is_on(FLAG) and speed3_db.ensure_schema('gps'):
                res = sample_once()
                if res:
                    log.debug('GPS sample: %s', res)
                if started - _state['retention'] > RETENTION_EVERY_S:
                    _state['retention'] = started
                    if res is not None:
                        log.info('GPS retention purge: %s', purge())
        except Exception as e:
            log.warning('GPS sample failed: %s', e)
        time.sleep(max(5.0, SAMPLE_EVERY_S - (time.time() - started)))
