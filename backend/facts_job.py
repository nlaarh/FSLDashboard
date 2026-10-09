"""Daily facts, the job and the backfill tool.

Job (a daemon thread started from main.py; does nothing until the flag `daily_facts` is on): every 5 minutes it looks at
today and the two days before and rebuilds a day only when facts_store.needs_refresh says so: today at most hourly, a
past day once after it settled (3 h) and once more at 28 h. One day is 4 sequential Salesforce reads (about 13 requests).
Only one worker runs it (advisory lock). Retention runs once a day.

Backfill, one day at a time with a pause between days (Salesforce is shared with dispatchers):
    python facts_job.py backfill 2026-09-10 2026-10-08            # dry run: prints the days and what it would do
    python facts_job.py backfill 2026-09-10 2026-10-08 --yes      # does it
"""

import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone

import facts_build
import facts_store
import speed3_db

log = logging.getLogger('facts_job')
FLAG = 'daily_facts'
TICK_S = 300
LOOKBACK_DAYS = 2            # today, yesterday, the day before
RETENTION_EVERY_S = 24 * 3600
MAX_BACKFILL_DAYS = 120


def refresh_day(day: str) -> dict | None:
    """Build one day from Salesforce and store it, if this worker is the leader. None when another worker holds the lock."""
    with speed3_db.leader('facts_job') as db:
        if db is None:
            return None
        built = facts_build.build_day(day)
        facts_store.write_day(db, built)
        return {'day': day, 'garages': len(built['garages']), 'sa_count': built['sa_count'], 'requests': built['requests']}


def due_days(now: datetime) -> list:
    today = now.date()
    days = [(today - timedelta(days=i)).isoformat() for i in range(LOOKBACK_DAYS, -1, -1)]
    have = facts_store.day_rows(days)
    return [d for d in days if facts_store.needs_refresh(d, have.get(d), now)]


def run_once(now: datetime | None = None) -> list:
    """One pass of the job. Returns what it built."""
    now = now or datetime.now(timezone.utc)
    done = []
    for day in due_days(now):
        res = refresh_day(day)
        if res is None:
            break                                    # another worker is the leader
        log.info('facts built: %s', res)
        done.append(res)
    return done


def run_forever():
    import feature_flags
    log.info('daily facts job started (idle until flag %s is on)', FLAG)
    last_purge = 0.0
    while True:
        try:
            if feature_flags.is_on(FLAG) and speed3_db.ensure_schema('facts'):
                run_once()
                if time.time() - last_purge > RETENTION_EVERY_S:
                    last_purge = time.time()
                    log.info('facts retention purge: %s', facts_store.purge())
        except Exception as e:
            log.warning('daily facts pass failed: %s', e)
        time.sleep(TICK_S)


def backfill(first: str, last: str, pause_s: float = 3.0, yes: bool = False, out=print) -> list:
    a, b = date.fromisoformat(first), date.fromisoformat(last)
    days = [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]
    if not days or len(days) > MAX_BACKFILL_DAYS:
        raise SystemExit(f'give a range of 1 to {MAX_BACKFILL_DAYS} days')
    out(f'{len(days)} days, {days[0]} to {days[-1]}, about {13 * len(days)} Salesforce requests, one day at a time')
    if not yes:
        out('dry run: nothing written. Add --yes to run.')
        return []
    if not speed3_db.ensure_schema('facts'):
        raise SystemExit('the facts tables could not be created or reached')
    done = []
    for day in days:
        for _ in range(30):                          # wait for the nightly job if it holds the lock
            res = refresh_day(day)
            if res is not None:
                break
            time.sleep(10)
        else:
            raise SystemExit(f'could not get the lock for {day}')
        out(f'{day}: {res["garages"]} garages, {res["sa_count"]} appointments, {res["requests"]} requests')
        done.append(res)
        time.sleep(pause_s)
    return done


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['backfill'])
    ap.add_argument('first')
    ap.add_argument('last')
    ap.add_argument('--yes', action='store_true')
    ap.add_argument('--pause', type=float, default=3.0)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    backfill(args.first, args.last, pause_s=args.pause, yes=args.yes)
    sys.exit(0)
