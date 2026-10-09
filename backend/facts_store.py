"""Daily facts, storage: write a built day, read a range, say which days are covered, retention.

A day counts as covered (safe to read instead of Salesforce) only when it was computed by the current FACTS_VERSION and
late enough that the day's calls have settled:
  a past UTC day      computed at least SETTLE_HOURS after the day ended
  today (UTC)         computed within the last FRESH_TODAY_MIN minutes
  a day in the future nothing to read, counts as covered
Anything else makes the caller use today's Salesforce path for the whole range.
"""

import json
import logging
from datetime import date, datetime, timedelta, timezone

import db_adapter
import speed3_db
from facts_build import FACTS_VERSION

log = logging.getLogger('facts_store')

SETTLE_HOURS = 3             # before the nightly trends run (00:05 Eastern = 04:05 or 05:05 UTC), so it finds yesterday ready
FINAL_HOURS = 28            # the last recompute of a day happens this long after it ended
FRESH_TODAY_MIN = 90
TODAY_EVERY_MIN = 60
KEEP_DAYS = 15         # owner 2026-10-09: no longer than 15 days; a longer range reads Salesforce (not "covered")

_NUM = ('r_total', 'r_completed', 'r_declined', 'r_cancelled', 'r_first_total', 'r_first_accepted', 'r_second_total',
        'r_second_accepted', 'r_accepted', 'r_accepted_completed', 't_volume', 't_completed', 't_auto', 't_fsl_volume',
        't_towbook_volume', 't_fleet_sum', 't_fleet_n', 't_sla_hits', 't_tb_sum', 't_tb_n')
_COLS = ('territory_id', 'day', 'territory_name') + _NUM + ('ata_json', 'pta_json', 'pts_json')


def day_end(day: str) -> datetime:
    return datetime.combine(date.fromisoformat(day) + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)


def write_day(db, built: dict) -> None:
    """Replace one day (its garage rows and its day row) in the caller's transaction. Only our own two tables."""
    day = built['day']
    db.execute('DELETE FROM facts_garage_day WHERE day = %s', (day,))
    marks = ', '.join(['%s'] * len(_COLS))
    for tid, g in built['garages'].items():
        db.execute(f'INSERT INTO facts_garage_day ({", ".join(_COLS)}) VALUES ({marks})',
                   (tid, day, g['territory_name']) + tuple(g[k] for k in _NUM)
                   + (json.dumps(g['ata']), json.dumps(g['pta']), json.dumps(g['pts'])))
    db.execute('DELETE FROM facts_day WHERE day = %s', (day,))
    db.execute('INSERT INTO facts_day (day, computed_at, version, sa_count, reassignments) VALUES (%s, %s, %s, %s, %s)',
               (day, speed3_db.iso(built['computed_at']), built['version'], built['sa_count'], built['reassignments']))


def day_rows(days: list) -> dict:
    """{day text: {'computed_at': datetime, 'version', 'sa_count', 'reassignments'}} for the days that exist."""
    if not days:
        return {}
    with db_adapter.reader() as db:
        rows = db.execute('SELECT day, computed_at, version, sa_count, reassignments FROM facts_day WHERE day >= %s AND day <= %s',
                          (min(days), max(days))).fetchall()
    return {str(r['day'])[:10]: {'computed_at': speed3_db.as_dt(r['computed_at']), 'version': r['version'],
                                 'sa_count': r['sa_count'], 'reassignments': r['reassignments']} for r in rows}


def is_covered(day: str, row: dict | None, now: datetime) -> bool:
    if day > now.date().isoformat():
        return True
    if not row or row['version'] != FACTS_VERSION:
        return False
    if day == now.date().isoformat():
        return now - row['computed_at'] <= timedelta(minutes=FRESH_TODAY_MIN)
    return row['computed_at'] >= day_end(day) + timedelta(hours=SETTLE_HOURS)


def covered(first: str, last: str, now: datetime | None = None) -> bool:
    """True when every UTC day from `first` to `last` (YYYY-MM-DD, inclusive) may be read from the facts."""
    now = now or datetime.now(timezone.utc)
    a, b = date.fromisoformat(first), date.fromisoformat(last)
    if b < a:
        return False
    days = [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]
    try:
        if not speed3_db.ensure_schema('facts'):
            return False
        have = day_rows([d for d in days if d <= now.date().isoformat()])
    except Exception as e:
        log.warning('facts coverage check failed, using Salesforce: %s', e)
        return False
    return all(is_covered(d, have.get(d), now) for d in days)


def read_garage_days(first: str, last: str) -> list:
    """Garage-day rows for the range, the three value lists decoded."""
    with db_adapter.reader() as db:
        rows = db.execute(f'SELECT {", ".join(_COLS)} FROM facts_garage_day WHERE day >= %s AND day <= %s ORDER BY day, territory_id',
                          (first, last)).fetchall()
    for r in rows:
        r['day'] = str(r['day'])[:10]
        r['ata'], r['pta'], r['pts'] = (json.loads(r.pop(k)) for k in ('ata_json', 'pta_json', 'pts_json'))
    return rows


def needs_refresh(day: str, row: dict | None, now: datetime) -> bool:
    """The job's schedule: today hourly; a past day once after it settled and once more at FINAL_HOURS; then never."""
    end = day_end(day)
    if row is None or row['version'] != FACTS_VERSION:
        return True
    if now < end:
        return now - row['computed_at'] >= timedelta(minutes=TODAY_EVERY_MIN)
    settled, final = end + timedelta(hours=SETTLE_HOURS), end + timedelta(hours=FINAL_HOURS)
    if row['computed_at'] < settled:
        return now >= settled
    if row['computed_at'] < final:
        return now >= final
    return False


def purge(now: datetime | None = None, keep_days: int = KEEP_DAYS) -> dict:
    """Retention: drop facts older than `keep_days` (only ever our own two tables)."""
    cut = ((now or datetime.now(timezone.utc)) - timedelta(days=keep_days)).date().isoformat()
    with db_adapter.writer() as db:
        db.execute('DELETE FROM facts_garage_day WHERE day < %s', (cut,))
        garages = db.rowcount
        db.execute('DELETE FROM facts_day WHERE day < %s', (cut,))
        return {'garage_days': garages, 'days': db.rowcount}
