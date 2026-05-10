#!/usr/bin/env python3
"""One-time migration: ALL SQLite tables → Postgres core schema."""

import os
import sys
import time
import logging
import sqlite3
import psycopg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("migrate_all")

SQLITE_DB = os.path.expanduser("~/.fslapp/fslapp.db")
PG_HOST = os.environ.get('FSLAPP_PG_HOST', 'fslapp-pg.postgres.database.azure.com')
PG_DB = os.environ.get('FSLAPP_PG_DATABASE', 'fslapp')
PG_USER = os.environ.get('FSLAPP_PG_USER', 'nlaaroubi@nyaaa.com')

sys.path.insert(0, os.path.dirname(__file__))
import pg_pool


def get_pg_conn():
    token = pg_pool._get_token()
    return psycopg.connect(
        host=PG_HOST, dbname=PG_DB, user=PG_USER,
        password=token, sslmode='require'
    )


def table_exists(pg_conn, table):
    with pg_conn.cursor() as cur:
        cur.execute("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'core' AND table_name = %s
        """, (table,))
        return cur.fetchone() is not None


def create_tables(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("SET statement_timeout = '5min'")
        cur.execute("SET search_path = core, public")

        # activity_log
        cur.execute('DROP TABLE IF EXISTS activity_log CASCADE')
        cur.execute('''
            CREATE TABLE activity_log (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                "user" TEXT,
                action TEXT NOT NULL,
                endpoint TEXT,
                method TEXT DEFAULT 'GET',
                status_code INTEGER,
                duration_ms REAL,
                ip TEXT,
                user_agent TEXT,
                detail TEXT
            )
        ''')
        cur.execute('CREATE INDEX idx_log_timestamp ON activity_log(timestamp)')
        cur.execute('CREATE INDEX idx_log_user ON activity_log("user")')

        # cache
        cur.execute('DROP TABLE IF EXISTS cache CASCADE')
        cur.execute('''
            CREATE TABLE cache (
                key TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                expires_at REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cur.execute('CREATE INDEX idx_cache_expires ON cache(expires_at)')

        # opt_sync_audit
        cur.execute('DROP TABLE IF EXISTS opt_sync_audit CASCADE')
        cur.execute('''
            CREATE TABLE opt_sync_audit (
                id SERIAL PRIMARY KEY,
                started_at TIMESTAMP NOT NULL,
                finished_at TIMESTAMP,
                status TEXT NOT NULL,
                runs_found INTEGER DEFAULT 0,
                runs_inserted INTEGER DEFAULT 0,
                runs_skipped INTEGER DEFAULT 0,
                runs_failed INTEGER DEFAULT 0,
                verdicts_inserted INTEGER DEFAULT 0,
                rows_purged INTEGER DEFAULT 0,
                error_detail TEXT,
                duration_ms INTEGER
            )
        ''')

        # password_reset_tokens
        cur.execute('DROP TABLE IF EXISTS password_reset_tokens CASCADE')
        cur.execute('''
            CREATE TABLE password_reset_tokens (
                token TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                email TEXT NOT NULL,
                pin TEXT NOT NULL,
                expires_at REAL NOT NULL,
                validated INTEGER DEFAULT 0,
                validation_token TEXT,
                validation_expires_at REAL,
                attempts INTEGER DEFAULT 0,
                created_at REAL DEFAULT EXTRACT(EPOCH FROM CURRENT_TIMESTAMP)
            )
        ''')
        cur.execute('CREATE INDEX idx_reset_tokens_email ON password_reset_tokens(email)')
        cur.execute('CREATE INDEX idx_reset_tokens_val ON password_reset_tokens(validation_token)')

        # users_password_backup
        cur.execute('DROP TABLE IF EXISTS users_password_backup CASCADE')
        cur.execute('''
            CREATE TABLE users_password_backup (
                username TEXT PRIMARY KEY,
                old_password_hash TEXT NOT NULL,
                old_salt TEXT NOT NULL
            )
        ''')

    pg_conn.commit()
    log.info("Tables created in Postgres.")


def migrate_table(sqlite_conn, pg_conn, table, columns, where=None, params=()):
    """Migrate a table using executemany for speed."""
    sql = f"SELECT {', '.join(columns)} FROM {table}"
    if where:
        sql += f" WHERE {where}"
    rows = sqlite_conn.execute(sql, params).fetchall()
    if not rows:
        log.info(f"{table}: 0 rows")
        return 0

    placeholders = ', '.join(['%s'] * len(columns))
    with pg_conn.cursor() as cur:
        cur.execute(f"DELETE FROM {table}")
        cur.executemany(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
            [tuple(r[c] for c in columns) for r in rows]
        )
    pg_conn.commit()
    log.info(f"{table}: {len(rows)} rows migrated")
    return len(rows)


def main():
    log.info(f"SQLite source: {SQLITE_DB}")
    if not os.path.exists(SQLITE_DB):
        log.error("SQLite DB not found!")
        sys.exit(1)

    sqlite_conn = sqlite3.connect(SQLITE_DB)
    sqlite_conn.row_factory = sqlite3.Row

    pg_conn = get_pg_conn()
    log.info("Connected to Postgres.")

    # Create tables
    create_tables(pg_conn)

    # 1. users (already migrated, just verify count)
    migrate_table(sqlite_conn, pg_conn, 'users',
        ['username', 'name', 'role', 'email', 'phone', 'password_hash', 'salt', 'active', 'created_at', 'department'])

    # 2. activity_log - last 3 days only
    three_days_ago = time.time() - (3 * 24 * 60 * 60)
    rows = sqlite_conn.execute(
        "SELECT * FROM activity_log WHERE timestamp > datetime(?, 'unixepoch')",
        (three_days_ago,)
    ).fetchall()
    log.info(f"activity_log (last 3 days): {len(rows)} rows")
    if rows:
        cols = ['id', 'timestamp', 'user', 'action', 'endpoint', 'method',
                'status_code', 'duration_ms', 'ip', 'user_agent', 'detail']
        pg_cols = ['id', 'timestamp', '"user"', 'action', 'endpoint', 'method',
                   'status_code', 'duration_ms', 'ip', 'user_agent', 'detail']
        placeholders = ', '.join(['%s'] * len(cols))
        with pg_conn.cursor() as cur:
            cur.execute("DELETE FROM activity_log")
            cur.executemany(
                f"INSERT INTO activity_log ({', '.join(pg_cols)}) VALUES ({placeholders})",
                [tuple(r[c] for c in cols) for r in rows]
            )
        pg_conn.commit()

    # 3. cache
    migrate_table(sqlite_conn, pg_conn, 'cache',
        ['key', 'data', 'expires_at', 'created_at'])

    # 4. opt_sync_audit
    migrate_table(sqlite_conn, pg_conn, 'opt_sync_audit',
        ['id', 'started_at', 'finished_at', 'status', 'runs_found', 'runs_inserted',
         'runs_skipped', 'runs_failed', 'verdicts_inserted', 'rows_purged', 'error_detail', 'duration_ms'])

    # 5. password_reset_tokens
    migrate_table(sqlite_conn, pg_conn, 'password_reset_tokens',
        ['token', 'username', 'email', 'pin', 'expires_at', 'validated',
         'validation_token', 'validation_expires_at', 'attempts', 'created_at'])

    # 6. users_password_backup
    migrate_table(sqlite_conn, pg_conn, 'users_password_backup',
        ['username', 'old_password_hash', 'old_salt'])

    # 7. settings
    migrate_table(sqlite_conn, pg_conn, 'settings',
        ['key', 'value', 'updated_at'])

    # 8. accounting_rates
    migrate_table(sqlite_conn, pg_conn, 'accounting_rates',
        ['code', 'label', 'value', 'unit', 'notes', 'category', 'updated_at'])

    # 9. bonus_tiers
    migrate_table(sqlite_conn, pg_conn, 'bonus_tiers',
        ['id', 'min_pct', 'bonus_per_sa', 'label', 'sort_order'])

    # 10. watchlist_manual
    migrate_table(sqlite_conn, pg_conn, 'watchlist_manual',
        ['sa_number', 'sa_id', 'added_by', 'added_at'])

    # 11. woa_reviews
    migrate_table(sqlite_conn, pg_conn, 'woa_reviews',
        ['woa_id', 'status', 'note', 'reviewer', 'reviewed_at'])

    # Verify
    log.info("--- Verification ---")
    tables = [
        'users', 'activity_log', 'cache', 'opt_sync_audit', 'password_reset_tokens',
        'users_password_backup', 'settings', 'accounting_rates', 'bonus_tiers',
        'watchlist_manual', 'woa_reviews'
    ]
    with pg_conn.cursor() as cur:
        for t in tables:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            cnt = cur.fetchone()[0]
            log.info(f"  {t}: {cnt} rows")

    sqlite_conn.close()
    pg_conn.close()
    log.info("Migration complete.")


if __name__ == "__main__":
    main()
