"""One-time migration: copy SQLite data → Postgres core schema.

Downloads the latest db-backup JSON from Azure Blob and inserts into
the core.* tables in production Postgres. Safe to re-run — uses INSERT OR IGNORE
(ON CONFLICT DO NOTHING in Postgres).

Usage:
    cd FSLAPP/backend
    python -m migrations.sqlite_to_core
"""

import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')
log = logging.getLogger('sqlite_to_core')

_CONN      = os.environ.get('AZ_OPT_CONNECTION_STRING')
_CONTAINER = os.environ.get('AZ_OPT_CONTAINER', 'optimizer-files')
_FOLDER    = 'db-backups'

_TABLES = ['users', 'settings', 'bonus_tiers', 'accounting_rates',
           'woa_reviews', 'watchlist_manual']


def _download_latest_backup() -> dict:
    from azure.storage.blob import BlobServiceClient
    client = BlobServiceClient.from_connection_string(_CONN)
    container = client.get_container_client(_CONTAINER)
    blobs = sorted(
        [b for b in container.list_blobs(name_starts_with=f"{_FOLDER}/fslapp_")],
        key=lambda b: b.name,
        reverse=True,
    )
    if not blobs:
        raise RuntimeError("No backups found in Azure Blob Storage")
    latest = blobs[0].name
    log.info(f"Downloading backup: {latest}")
    raw = container.get_blob_client(latest).download_blob().readall()
    data = json.loads(raw)
    log.info(f"Backup exported at: {data.get('_exported_at', 'unknown')}")
    return data


def _get_pg_conn():
    """Get a raw psycopg connection using Entra ID token."""
    import psycopg
    from azure.identity import DefaultAzureCredential
    token = DefaultAzureCredential(
        exclude_visual_studio_code_credential=True,
        exclude_interactive_browser_credential=True,
    ).get_token('https://ossrdbms-aad.database.windows.net/.default').token

    return psycopg.connect(
        host=os.environ.get('FSLAPP_PG_HOST', 'fslapp-pg.postgres.database.azure.com'),
        dbname=os.environ.get('FSLAPP_PG_DATABASE', 'fslapp'),
        user=os.environ.get('FSLAPP_PG_USER', 'nlaaroubi@nyaaa.com'),
        password=token,
        sslmode='require',
        options='-c search_path=core,public',
    )


def _insert_table(conn, table: str, rows: list):
    if not rows:
        log.info(f"  {table}: 0 rows (skipped)")
        return
    cols = list(rows[0].keys())
    col_names = ', '.join(f'"{c}"' for c in cols)
    placeholders = ', '.join(['%s'] * len(cols))
    sql = (f'INSERT INTO "{table}" ({col_names}) VALUES ({placeholders}) '
           f'ON CONFLICT DO NOTHING')
    values = [tuple(r.get(c) for c in cols) for r in rows]
    with conn.cursor() as cur:
        cur.executemany(sql, values)
    log.info(f"  {table}: {len(rows)} rows attempted (conflicts silently skipped)")


def main():
    if not _CONN:
        log.error("AZ_OPT_CONNECTION_STRING not set")
        sys.exit(1)

    log.info("=== SQLite → Postgres core migration ===")
    data = _download_latest_backup()

    log.info("Connecting to Postgres...")
    conn = _get_pg_conn()

    try:
        for table in _TABLES:
            rows = data.get(table, [])
            _insert_table(conn, table, rows)
        conn.commit()
        log.info("=== Migration complete ===")
    except Exception as e:
        conn.rollback()
        log.error(f"Migration failed: {e}")
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
