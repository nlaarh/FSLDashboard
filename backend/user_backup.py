"""User backup — syncs Postgres core.users to SQLite after every mutation.

Recovery path:
  POST /api/admin/users/restore-missing
  → downloads latest Azure Blob backup (Postgres-sourced)
  → inserts missing rows into Postgres core.* (ON CONFLICT DO NOTHING)

Fallback: if Postgres is unreachable, user_backup.load() falls back to an
AES-encrypted file at ~/.fslapp/users_backup.enc.
"""

import base64, json, logging, os, time

log = logging.getLogger("user_backup")

_ON_AZURE = bool(os.environ.get("WEBSITE_SITE_NAME"))
_BACKUP_DIR = "/home/fslapp" if _ON_AZURE else os.path.expanduser("~/.fslapp")
FILE_BACKUP_PATH = os.path.join(_BACKUP_DIR, "users_backup.enc")

_ALL_COLS = [
    "username",
    "name",
    "role",
    "email",
    "phone",
    "password_hash",
    "salt",
    "active",
    "created_at",
    "department",
]


# ── Postgres helpers ──────────────────────────────────────────────────────────

def _pg_load() -> list[dict] | None:
    """Load all users from Postgres core.users. Returns None on failure."""
    try:
        import pg_pool

        with pg_pool.reader() as conn:
            with conn.cursor() as cur:
                cur.execute("SET search_path = core, public")
                cur.execute(f"SELECT {', '.join(_ALL_COLS)} FROM users")
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        log.info(f"[user_backup] Loaded {len(rows)} users from Postgres")
        return rows
    except Exception as e:
        log.warning(f"[user_backup] Postgres load failed: {e}")
        return None


def _sqlite_upsert(rows: list[dict]) -> bool:
    """Upsert rows into SQLite users table. Returns True on success."""
    try:
        import database as db

        with db.get_db() as conn:
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO users
                        (username, name, role, email, phone, password_hash, salt, active, created_at, department)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(username) DO UPDATE SET
                        name = excluded.name,
                        role = excluded.role,
                        email = excluded.email,
                        phone = excluded.phone,
                        password_hash = excluded.password_hash,
                        salt = excluded.salt,
                        active = excluded.active,
                        created_at = excluded.created_at,
                        department = excluded.department
                    """,
                    [row.get(c) for c in _ALL_COLS],
                )
        log.info(f"[user_backup] SQLite sync: {len(rows)} users upserted")
        return True
    except Exception as e:
        log.warning(f"[user_backup] SQLite sync failed: {e}")
        return False


# ── Encrypted file fallback ───────────────────────────────────────────────────

def _get_fernet():
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    passphrase = os.environ.get("FSLAPP_BACKUP_KEY") or os.environ.get("ADMIN_PIN", "")
    if not passphrase:
        raise RuntimeError(
            "FSLAPP_BACKUP_KEY or ADMIN_PIN env var required for file backup"
        )
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"fslapp_user_backup_v1_static_salt",
        iterations=200_000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))
    return Fernet(key)


def _file_save(user_rows: list[dict]) -> bool:
    try:
        f = _get_fernet()
        payload = json.dumps(
            {"version": 2, "timestamp": time.time(), "users": user_rows}
        )
        encrypted = f.encrypt(payload.encode())
        os.makedirs(_BACKUP_DIR, exist_ok=True)
        tmp = FILE_BACKUP_PATH + ".tmp"
        with open(tmp, "wb") as fp:
            fp.write(encrypted)
        os.replace(tmp, FILE_BACKUP_PATH)
        log.info(f"[user_backup] File backup written: {len(user_rows)} users")
        return True
    except Exception as e:
        log.error(f"[user_backup] File backup failed: {e}")
        return False


def _file_load() -> list[dict] | None:
    if not os.path.exists(FILE_BACKUP_PATH):
        return None
    try:
        from cryptography.fernet import InvalidToken

        f = _get_fernet()
        with open(FILE_BACKUP_PATH, "rb") as fp:
            data = json.loads(f.decrypt(fp.read()).decode())
        return data["users"]
    except Exception as e:
        log.error(f"[user_backup] File load failed: {e}")
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def save() -> None:
    """Read users from Postgres core.users and sync to SQLite.
    Also writes an encrypted file backup. Fire-and-forget.
    """
    rows = _pg_load()
    if rows is None:
        return
    _sqlite_upsert(rows)
    _file_save(rows)


def load() -> list[dict]:
    """Load users from Postgres core.users or encrypted file fallback.
    Raises RuntimeError if neither source is available.
    """
    rows = _pg_load()
    if rows is not None:
        return rows
    rows = _file_load()
    if rows is not None:
        log.warning("[user_backup] Using file fallback — Postgres was unavailable")
        return rows
    raise RuntimeError(
        "No user backup available (Postgres unreachable, no file backup found)"
    )


def backup_info() -> dict:
    """Return metadata about the current backup state without exposing user data."""
    info = {"postgres": {}, "file": {}}
    try:
        import pg_pool

        with pg_pool.reader() as conn:
            with conn.cursor() as cur:
                cur.execute("SET search_path = core, public")
                cur.execute("SELECT COUNT(*) FROM users")
                count = cur.fetchone()[0]
        info["postgres"] = {"ok": True, "count": count}
    except Exception as e:
        info["postgres"] = {"ok": False, "error": str(e)}

    if os.path.exists(FILE_BACKUP_PATH):
        try:
            data = _file_load()
            info["file"] = {
                "ok": True,
                "count": len(data) if data else 0,
                "path": FILE_BACKUP_PATH,
                "size_bytes": os.path.getsize(FILE_BACKUP_PATH),
            }
        except Exception as e:
            info["file"] = {"ok": False, "path": FILE_BACKUP_PATH, "error": str(e)}
    else:
        info["file"] = {"ok": False, "exists": False}

    return info
