"""Speed batch 3: the four new Postgres tables, their one-time creation, and the single-leader lock.

Nothing here runs unless a feature flag is on (replay_gps_store, daily_facts): deploying the code creates no table and
writes no row. The DDL is additive and idempotent (CREATE ... IF NOT EXISTS only: no ALTER, no DROP, no data rewrite).
The owner approves it once; the same text is applied by `ensure_schema('gps')` / `ensure_schema('facts')` the first time
its flag is switched on, or by Kathy with psql (the statements are GPS_SQL and FACTS_SQL, one per list item).

Tables (all in the app schema `core`, which db_adapter puts on the search path):
  driver_gps_points   one row per recorded driver position (the Replay map reads these instead of ServiceResourceHistory)
  driver_gps_samples  one row per successful 60 s sampler run: what proves a time window is fully covered
  facts_day           one row per UTC day: when it was computed, how many appointments, assignments changed
  facts_garage_day    one row per garage per UTC day: counts, ATA/PTA values, Towbook/FSL split
"""

import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

import db_adapter

log = logging.getLogger('speed3_db')

GPS_SQL = [
    """CREATE TABLE IF NOT EXISTS driver_gps_points (
    resource_id TEXT NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,
    lat         DOUBLE PRECISION NOT NULL,
    lon         DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (resource_id, ts)
)""",
    "CREATE INDEX IF NOT EXISTS idx_driver_gps_points_ts ON driver_gps_points (ts)",
    """CREATE TABLE IF NOT EXISTS driver_gps_samples (
    sampled_at     TIMESTAMPTZ PRIMARY KEY,
    rows_seen      INTEGER NOT NULL,
    points_written INTEGER NOT NULL
)""",
]

FACTS_SQL = [
    """CREATE TABLE IF NOT EXISTS facts_day (
    day           DATE PRIMARY KEY,
    computed_at   TIMESTAMPTZ NOT NULL,
    version       INTEGER NOT NULL,
    sa_count      INTEGER NOT NULL,
    reassignments INTEGER NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS facts_garage_day (
    territory_id     TEXT NOT NULL,
    day              DATE NOT NULL,
    territory_name   TEXT NOT NULL,
    r_total          INTEGER NOT NULL,
    r_completed      INTEGER NOT NULL,
    r_declined       INTEGER NOT NULL,
    r_cancelled      INTEGER NOT NULL,
    r_first_total    INTEGER NOT NULL,
    r_first_accepted INTEGER NOT NULL,
    r_second_total   INTEGER NOT NULL,
    r_second_accepted INTEGER NOT NULL,
    r_accepted       INTEGER NOT NULL,
    r_accepted_completed INTEGER NOT NULL,
    ata_json         TEXT NOT NULL,
    pta_json         TEXT NOT NULL,
    pts_json         TEXT NOT NULL,
    t_volume         INTEGER NOT NULL,
    t_completed      INTEGER NOT NULL,
    t_auto           INTEGER NOT NULL,
    t_fsl_volume     INTEGER NOT NULL,
    t_towbook_volume INTEGER NOT NULL,
    t_fleet_sum      DOUBLE PRECISION NOT NULL,
    t_fleet_n        INTEGER NOT NULL,
    t_sla_hits       INTEGER NOT NULL,
    t_tb_sum         DOUBLE PRECISION NOT NULL,
    t_tb_n           INTEGER NOT NULL,
    PRIMARY KEY (territory_id, day)
)""",
    "CREATE INDEX IF NOT EXISTS idx_facts_garage_day_day ON facts_garage_day (day)",
]

SCHEMA_SQL = GPS_SQL + FACTS_SQL
_GROUPS = {'gps': GPS_SQL, 'facts': FACTS_SQL}

_ready = set()
_ready_lock = threading.Lock()


def ensure_schema(group: str) -> bool:
    """Create one group of tables ('gps' or 'facts') once per process. False (never an exception) when the database
    refuses, so callers fall back to today's path."""
    if group in _ready:
        return True
    with _ready_lock:
        if group in _ready:
            return True
        try:
            with db_adapter.writer() as db:
                for stmt in _GROUPS[group]:
                    db.execute(stmt)
            _ready.add(group)
            log.info('speed batch 3 %s tables ensured', group)
        except Exception as e:
            log.warning('speed batch 3 %s tables could not be created: %s', group, e)
    return group in _ready


def iso(dt: datetime) -> str:
    """One fixed UTC text form, so values compare the same on Postgres and on the SQLite test fake."""
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')


def as_dt(v) -> datetime:
    """A timestamp column back as an aware UTC datetime (Postgres returns datetime, the SQLite fake returns text)."""
    if isinstance(v, datetime):                      # Postgres hands back the session's zone (e.g. -04:00): always convert to UTC
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    return datetime.fromisoformat(str(v).replace('Z', '+00:00')).astimezone(timezone.utc)


def lock_key(name: str) -> int:
    """Stable key for a Postgres advisory lock (Python's hash() is randomised per process, so a CRC is used)."""
    import zlib
    return zlib.crc32(f'fslapp-speed3:{name}'.encode())


@contextmanager
def leader(name: str):
    """Yield an open writer connection if this worker is the only one running `name` right now, else None.

    Uses a transaction-level advisory lock: taken without waiting, released when the transaction ends, so a crashed
    worker can never leave it stuck. Everything written inside the block commits together, or not at all.
    On a database without advisory locks (the SQLite test fake) the caller is the leader.
    """
    with db_adapter.writer() as db:
        if db.backend == 'postgres':
            row = db.execute('SELECT pg_try_advisory_xact_lock(%s) AS got', (lock_key(name),)).fetchone()
            if not row or not row['got']:
                yield None
                return
        yield db
