"""Single source of truth for Azure Postgres connections (FSLAPP shared DB).

Used by `optimizer_db_pg.py` and any future FSLAPP feature that hits Postgres.
Connections authenticate via Microsoft Entra ID — never a password.

Token lifecycle:
- DefaultAzureCredential picks up: managed identity → Mac `az login` → env vars
- Tokens last ~60 min. Pool refreshes via per-connect callback so each NEW
  connection grabs a fresh token before it's handed out.
- max_lifetime=55min recycles connections before tokens expire mid-query.

Pool design:
- Reader pool: short-lived per-request connections from FastAPI handlers
- Writer pool: small, long-lived for the blob_sync background thread
- Both connect to the same server; differ in size + timeout.
"""

import os
import logging
import threading
from typing import Optional
from contextlib import contextmanager

import psycopg
from psycopg_pool import ConnectionPool
from azure.identity import DefaultAzureCredential

log = logging.getLogger('pg_pool')

# ── Configuration (read once at import; .env should be loaded already) ──────
PG_HOST     = os.environ.get('FSLAPP_PG_HOST',     'fslapp-pg.postgres.database.azure.com')
PG_DATABASE = os.environ.get('FSLAPP_PG_DATABASE', 'fslapp')
PG_USER     = os.environ.get('FSLAPP_PG_USER',     'nlaaroubi@nyaaa.com')
PG_SCHEMA   = os.environ.get('FSLAPP_PG_SCHEMA',   'optimizer')

READER_MIN_SIZE = int(os.environ.get('FSLAPP_PG_READER_MIN', '2'))
READER_MAX_SIZE = int(os.environ.get('FSLAPP_PG_READER_MAX', '10'))
READER_TIMEOUT  = int(os.environ.get('FSLAPP_PG_READER_TIMEOUT_S', '5'))

WRITER_MIN_SIZE = int(os.environ.get('FSLAPP_PG_WRITER_MIN', '1'))
WRITER_MAX_SIZE = int(os.environ.get('FSLAPP_PG_WRITER_MAX', '2'))
WRITER_TIMEOUT  = int(os.environ.get('FSLAPP_PG_WRITER_TIMEOUT_S', '10'))

_credential: Optional[DefaultAzureCredential] = None
_credential_lock = threading.Lock()


def _get_credential() -> DefaultAzureCredential:
    """Lazy singleton. Walks: managed identity → CLI → env vars."""
    global _credential
    if _credential is None:
        with _credential_lock:
            if _credential is None:
                _credential = DefaultAzureCredential(
                    exclude_visual_studio_code_credential=True,
                    exclude_interactive_browser_credential=True,
                )
    return _credential


def _get_token() -> str:
    """Fetch a fresh Postgres-scoped Entra access token."""
    return _get_credential().get_token(
        'https://ossrdbms-aad.database.windows.net/.default'
    ).token


def _configure_connection(conn: psycopg.Connection) -> None:
    """Per-connection setup. Runs ONCE when the pool opens a new connection."""
    with conn.cursor() as cur:
        cur.execute(f"SET search_path = {PG_SCHEMA}, public")
    conn.commit()


# ── Pools (lazy-init, thread-safe) ──────────────────────────────────────────
_reader_pool: Optional[ConnectionPool] = None
_writer_pool: Optional[ConnectionPool] = None
_pool_lock = threading.Lock()


class _TokenAuthConnectionPool(ConnectionPool):
    """ConnectionPool subclass that injects a fresh Entra token each time it
    establishes a new physical connection. Existing pooled connections persist
    regardless of token expiry — only NEW connections need a fresh token.
    """

    def _resolve_kwargs(self) -> dict:
        kwargs = super()._resolve_kwargs()
        kwargs['password'] = _get_token()
        return kwargs


def _make_pool(name: str, min_size: int, max_size: int, timeout: int) -> ConnectionPool:
    """Create a pool with token-injection at connect time."""
    return _TokenAuthConnectionPool(
        conninfo=None,
        kwargs={
            'host':    PG_HOST,
            'dbname':  PG_DATABASE,
            'user':    PG_USER,
            'sslmode': 'require',
        },
        min_size=min_size,
        max_size=max_size,
        timeout=timeout,
        max_lifetime=55 * 60,    # rotate before 60-min token expiry
        max_idle=10 * 60,
        name=name,
        configure=_configure_connection,
        open=False,
    )


def get_reader_pool() -> ConnectionPool:
    """Reader pool for FastAPI request handlers."""
    global _reader_pool
    if _reader_pool is None:
        with _pool_lock:
            if _reader_pool is None:
                _reader_pool = _make_pool(
                    'reader', READER_MIN_SIZE, READER_MAX_SIZE, READER_TIMEOUT,
                )
                _reader_pool.open()
                log.info(f"[pg_pool] reader pool opened: min={READER_MIN_SIZE} max={READER_MAX_SIZE}")
    return _reader_pool


def get_writer_pool() -> ConnectionPool:
    """Writer pool for the blob_sync background thread."""
    global _writer_pool
    if _writer_pool is None:
        with _pool_lock:
            if _writer_pool is None:
                _writer_pool = _make_pool(
                    'writer', WRITER_MIN_SIZE, WRITER_MAX_SIZE, WRITER_TIMEOUT,
                )
                _writer_pool.open()
                log.info(f"[pg_pool] writer pool opened: min={WRITER_MIN_SIZE} max={WRITER_MAX_SIZE}")
    return _writer_pool


@contextmanager
def reader():
    """Borrow a reader connection. Returned to pool on exit."""
    with get_reader_pool().connection() as conn:
        yield conn


@contextmanager
def writer():
    """Borrow a writer connection. Returned to pool on exit."""
    with get_writer_pool().connection() as conn:
        yield conn


def close_pools() -> None:
    """Shutdown both pools (e.g., at FastAPI shutdown)."""
    global _reader_pool, _writer_pool
    if _reader_pool is not None:
        _reader_pool.close(); _reader_pool = None
        log.info("[pg_pool] reader pool closed")
    if _writer_pool is not None:
        _writer_pool.close(); _writer_pool = None
        log.info("[pg_pool] writer pool closed")


def rows_as_dicts(cur) -> list[dict]:
    """Convert a psycopg cursor's rows into list[dict] using column names."""
    cols = [d[0] for d in cur.description] if cur.description else []
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def health_check() -> dict:
    """Connectivity smoke test."""
    try:
        with reader() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_user, current_database(), version()")
                row = cur.fetchone()
        return {
            'ok': True,
            'host': PG_HOST,
            'database': PG_DATABASE,
            'user': row[0],
            'version': row[2].split(' on ')[0],
        }
    except Exception as e:
        log.exception("[pg_pool] health check failed")
        return {'ok': False, 'host': PG_HOST, 'error': str(e)}


if __name__ == '__main__':
    # python -m pg_pool — quick smoke test from CLI
    import json
    from pathlib import Path
    from dotenv import load_dotenv
    # Load .env from apidev root (sibling of FSLAPP)
    load_dotenv(Path(__file__).resolve().parents[2] / '.env')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    print(json.dumps(health_check(), indent=2))
    close_pools()
