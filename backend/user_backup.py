"""User backup — mirrors SQLite users table to Azure Postgres after every mutation.

Recovery path:
  POST /api/admin/users/restore-backup
  → reads public.users_mirror from Postgres
  → INSERT OR IGNORE into SQLite (skips existing, restores missing)
  → returns { restored, skipped, total }

Fallback: if Postgres is unreachable (e.g. no az login locally), falls back
to an AES-encrypted file at ~/.fslapp/users_backup.enc.

Password hashes (SHA-256+salt) are stored — never plaintext passwords.
"""

import base64, json, logging, os, time
from contextlib import contextmanager

log = logging.getLogger('user_backup')

_ON_AZURE = bool(os.environ.get('WEBSITE_SITE_NAME'))
_BACKUP_DIR = '/home/fslapp' if _ON_AZURE else os.path.expanduser('~/.fslapp')
FILE_BACKUP_PATH = os.path.join(_BACKUP_DIR, 'users_backup.enc')

_ALL_COLS = ['username', 'name', 'role', 'email', 'phone',
             'password_hash', 'salt', 'active', 'created_at', 'department']


# ── Postgres ──────────────────────────────────────────────────────────────────

def _ensure_pg_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.users_mirror (
                username     TEXT PRIMARY KEY,
                name         TEXT,
                role         TEXT,
                email        TEXT,
                phone        TEXT,
                password_hash TEXT NOT NULL,
                salt         TEXT NOT NULL,
                active       INTEGER DEFAULT 1,
                created_at   DOUBLE PRECISION,
                department   TEXT DEFAULT '',
                synced_at    TIMESTAMPTZ DEFAULT now()
            )
        """)
    conn.commit()


def _pg_save(user_rows: list[dict]) -> bool:
    """Upsert all user rows into Postgres. Returns True on success."""
    try:
        import pg_pool
        with pg_pool.writer() as conn:
            _ensure_pg_table(conn)
            with conn.cursor() as cur:
                for row in user_rows:
                    cur.execute("""
                        INSERT INTO public.users_mirror
                            (username, name, role, email, phone, password_hash, salt, active, created_at, department, synced_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                        ON CONFLICT (username) DO UPDATE SET
                            name          = EXCLUDED.name,
                            role          = EXCLUDED.role,
                            email         = EXCLUDED.email,
                            phone         = EXCLUDED.phone,
                            password_hash = EXCLUDED.password_hash,
                            salt          = EXCLUDED.salt,
                            active        = EXCLUDED.active,
                            created_at    = EXCLUDED.created_at,
                            department    = EXCLUDED.department,
                            synced_at     = now()
                    """, [row.get(c) for c in _ALL_COLS])
            conn.commit()
        log.info(f'[user_backup] Postgres sync: {len(user_rows)} users upserted')
        return True
    except Exception as e:
        log.warning(f'[user_backup] Postgres sync failed: {e}')
        return False


def _pg_load() -> list[dict] | None:
    """Load all users from Postgres mirror. Returns None if unavailable."""
    try:
        import pg_pool
        with pg_pool.reader() as conn:
            _ensure_pg_table(conn)
            with conn.cursor() as cur:
                cur.execute(f"SELECT {', '.join(_ALL_COLS)} FROM public.users_mirror")
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        log.info(f'[user_backup] Loaded {len(rows)} users from Postgres')
        return rows
    except Exception as e:
        log.warning(f'[user_backup] Postgres load failed: {e}')
        return None


# ── Encrypted file fallback ────────────────────────────────────────────────────

def _get_fernet():
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    passphrase = os.environ.get('FSLAPP_BACKUP_KEY') or os.environ.get('ADMIN_PIN', '')
    if not passphrase:
        raise RuntimeError('FSLAPP_BACKUP_KEY or ADMIN_PIN env var required for file backup')
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                     salt=b'fslapp_user_backup_v1_static_salt', iterations=200_000)
    key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))
    return Fernet(key)


def _file_save(user_rows: list[dict]) -> bool:
    try:
        f = _get_fernet()
        payload = json.dumps({'version': 2, 'timestamp': time.time(), 'users': user_rows})
        encrypted = f.encrypt(payload.encode())
        os.makedirs(_BACKUP_DIR, exist_ok=True)
        tmp = FILE_BACKUP_PATH + '.tmp'
        with open(tmp, 'wb') as fp:
            fp.write(encrypted)
        os.replace(tmp, FILE_BACKUP_PATH)
        log.info(f'[user_backup] File backup written: {len(user_rows)} users')
        return True
    except Exception as e:
        log.error(f'[user_backup] File backup failed: {e}')
        return False


def _file_load() -> list[dict] | None:
    if not os.path.exists(FILE_BACKUP_PATH):
        return None
    try:
        from cryptography.fernet import InvalidToken
        f = _get_fernet()
        with open(FILE_BACKUP_PATH, 'rb') as fp:
            data = json.loads(f.decrypt(fp.read()).decode())
        return data['users']
    except Exception as e:
        log.error(f'[user_backup] File load failed: {e}')
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def save(user_rows: list[dict]) -> None:
    """Sync users to Postgres (primary) and encrypted file (fallback). Fire-and-forget."""
    pg_ok = _pg_save(user_rows)
    if not pg_ok:
        _file_save(user_rows)  # only write file if Postgres failed


def load() -> list[dict]:
    """Load users from Postgres (primary) or encrypted file (fallback).
    Raises RuntimeError if neither source is available."""
    rows = _pg_load()
    if rows is not None:
        return rows
    rows = _file_load()
    if rows is not None:
        log.warning('[user_backup] Using file fallback — Postgres was unavailable')
        return rows
    raise RuntimeError('No user backup available (Postgres unreachable, no file backup found)')


def backup_info() -> dict:
    """Return metadata about the current backup state without exposing user data."""
    info = {'postgres': {}, 'file': {}}
    try:
        import pg_pool
        with pg_pool.reader() as conn:
            _ensure_pg_table(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*), MAX(synced_at) FROM public.users_mirror")
                row = cur.fetchone()
        info['postgres'] = {'ok': True, 'count': row[0], 'last_sync': str(row[1]) if row[1] else None}
    except Exception as e:
        info['postgres'] = {'ok': False, 'error': str(e)}

    if os.path.exists(FILE_BACKUP_PATH):
        try:
            data = _file_load()
            info['file'] = {'ok': True, 'count': len(data) if data else 0,
                            'path': FILE_BACKUP_PATH,
                            'size_bytes': os.path.getsize(FILE_BACKUP_PATH)}
        except Exception as e:
            info['file'] = {'ok': False, 'path': FILE_BACKUP_PATH, 'error': str(e)}
    else:
        info['file'] = {'ok': False, 'exists': False}

    return info
