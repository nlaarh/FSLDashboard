"""User management — Postgres-only via repositories/users.py.

All database access goes through repositories/users.py (which uses db_adapter).
No SQLite fallback. Sessions tracked in-memory (cleared on restart).
"""

import hashlib, os, secrets, time, threading

import bcrypt
import user_backup
from repositories import users as _user_repo
from repositories import user_sessions as _session_repo

_sess_lock = threading.Lock()
_sessions: dict[str, dict] = {}
_sess_last_flush: dict[str, float] = {}   # token -> last DB touch timestamp
_TOUCH_INTERVAL = 60                       # max one DB write per session per minute


# ── Password hashing ─────────────────────────────────────────────────────────

_BCRYPT_ROUNDS = 12


def _hash_password(password: str, _salt: str = None) -> tuple[str, str]:
    """Hash password with bcrypt. Returns (hash, 'bcrypt').
    The _salt param is ignored for bcrypt but kept for API compatibility."""
    pw_bytes = password.encode("utf-8")
    h = bcrypt.hashpw(pw_bytes, bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("utf-8")
    return h, "bcrypt"


def _check_password_legacy(password: str, stored_hash: str, salt: str) -> bool:
    """Check against legacy SHA-256 + salt (for migration only)."""
    h = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return secrets.compare_digest(h, stored_hash)


def _check_password(password: str, stored_hash: str, salt: str) -> bool:
    """Check password against stored hash.
    If salt == 'bcrypt', use bcrypt. Otherwise fall back to legacy SHA-256.
    """
    if not stored_hash:
        return False
    # Detect bcrypt by prefix
    if salt == "bcrypt" or stored_hash.startswith(("$2b$", "$2a$", "$2y$")):
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
    # Legacy SHA-256
    return _check_password_legacy(password, stored_hash, salt)


# ── Seed / ensure users ──────────────────────────────────────────────────────
# Passwords come from env vars — never stored in source code.
# (username, env_var, display_name, role, email, department)

_SEED_USER_DEFS = [
    # Core / admin
    ('admin',               'SEED_PASS_ADMIN',          'Admin',              'admin',          '',                        ''),
    ('nlaaroubi@nyaaa.com', 'SEED_PASS_NLAAROUBI',      'Nour Laaroubi',     'superadmin',     'nlaaroubi@nyaaa.com',     'executive'),
    # ERS managers — full access
    ('tingraham@nyaaa.com', 'SEED_PASS_TINGRAHAM',      'Tina Ingraham',     'ers-manager',    'tingraham@nyaaa.com',     'ers'),
    ('dfisher@nyaaa.com',   'SEED_PASS_DFISHER',        'D Fisher',          'ers-manager',    'dfisher@nyaaa.com',       'ers'),
    ('shorn@nyaaa.com',     'SEED_PASS_SHORN',          'S Horn',            'ers-manager',    'shorn@nyaaa.com',         'ers'),
    ('rprendergast@nyaaa.com','SEED_PASS_RPRENDERGAST', 'Robert Prendergast','ers-manager',    'rprendergast@nyaaa.com',  'ers'),
    ('cmacneil@nyaaa.com',  'SEED_PASS_CMACNEIL',       'Chris Macneil',    'ers-manager',    'cmacneil@nyaaa.com',      'ers'),
    ('tcoulter@nyaaa.com',  'SEED_PASS_TCOULTER',        'Todd Coulter',    'ers-manager',    'tcoulter@nyaaa.com',      'ers'),
    ('mmika@nyaaa.com',     'SEED_PASS_MMIKA',           'Mark Mika',       'ers-manager',    'mmika@nyaaa.com',         'ers'),
    ('rlyle@nyaaa.com',     'SEED_PASS_RLYLE',           'Robert Lyle',     'ers-manager',    'rlyle@nyaaa.com',         'ers'),
    ('jcarroll@nyaaa.com',  'SEED_PASS_JCARROLL',        'Jon Carroll',     'ers-manager',    'jcarroll@nyaaa.com',      'ers'),
    ('jharrington@nyaaa.com','SEED_PASS_JHARRINGTON',    'Jeremy Harrington','ers-manager',    'jharrington@nyaaa.com',   'ers'),
    # ERS supervisors — no accounting, no admin
    ('sgancasz@nyaaa.com',  'SEED_PASS_SGANCASZ',        'Shawn Gancasz',   'ers-supervisor', 'sgancasz@nyaaa.com',      'ers'),
    ('mtrichilo@nyaaa.com', 'SEED_PASS_MTRICHILO',       'Mary Trichilo',   'ers-supervisor', 'mtrichilo@nyaaa.com',     'ers'),
    ('khartman@nyaaa.com',  'SEED_PASS_KHARTMAN',        'Kristin Hartman', 'ers-supervisor', 'khartman@nyaaa.com',      'ers'),
    ('calger@nyaaa.com',    'SEED_PASS_CALGER',           'Cat Alger',      'ers-supervisor', 'calger@nyaaa.com',        'ers'),
    ('dkalenda@nyaaa.com',  'SEED_PASS_DKALENDA',         'Deborah Kalenda','ers-supervisor', 'dkalenda@nyaaa.com',      'ers'),
    # Executive
    ('jnixon@nyaaa.com',    'SEED_PASS_JNIXON',          'J Nixon',        'executive',      'jnixon@nyaaa.com',        'executive'),
    # Finance — accounting only
    ('dbrown@nyaaa.com',    'SEED_PASS_DBROWN',           'Denise Brown',   'finance',        'dbrown@nyaaa.com',        'finance'),
    ('ksmeal@nyaaa.com',    'SEED_PASS_KSMEAL',           'Kerry Smeal',    'finance',        'ksmeal@nyaaa.com',        'finance'),
]


def seed_users():
    """Ensure all defined users exist with correct roles. Creates missing users,
    updates role/dept for existing ones.  Passwords read from SEED_PASS_* env vars
    — only set on initial creation (never overwrite existing passwords)."""
    import logging
    _log = logging.getLogger('users')

    for username, env_var, name, role, email, department in _SEED_USER_DEFS:
        existing = _user_repo.get_user(username)
        if existing:
            _user_repo.update_user(
                username, name=name, role=role, department=department, email=email
            )
            continue
        password = os.getenv(env_var)
        if not password:
            _log.warning(f"Skipping seed for {username}: {env_var} not set in env")
            continue
        h, salt = _hash_password(password)
        _user_repo.create_user(
            username, name, role, email, '', h, salt, 1, time.time(), department
        )
        _log.info(f"Seeded user {username} ({role})")
    _trigger_backup()


def migrate_json_users():
    """No-op: JSON migration was a one-time operation."""
    pass


# ── Public API ────────────────────────────────────────────────────────────────

def _dept(row) -> str:
    try:
        return row['department'] or ''
    except Exception:
        return ''


def _trigger_backup():
    """Fire-and-forget: sync Postgres → SQLite backup + encrypted file."""
    try:
        user_backup.save()
    except Exception:
        pass  # backup failure must never crash the main operation


def find_by_email(email: str) -> dict | None:
    """Find active user by email (case-insensitive)."""
    return _user_repo.find_by_email(email)


def authenticate(username: str, password: str) -> dict | None:
    row = _user_repo.get_user_with_hash(username)
    if row and row.get('active'):
        if _check_password(password, row['password_hash'], row['salt']):
            # If this was a legacy hash, transparently migrate to bcrypt
            if row['salt'] != 'bcrypt' and not row['password_hash'].startswith(("$2b$", "$2a$", "$2y$")):
                h, salt = _hash_password(password)
                _user_repo.update_password_hash(username, h, salt)
            return {"username": row['username'], "name": row['name'], "role": row['role'],
                    "email": row['email'], "department": _dept(row)}
    return None


def get_user(username: str) -> dict | None:
    return _user_repo.get_user(username)


def get_user_with_hash(username: str) -> dict | None:
    """Return user dict including password_hash and salt fields."""
    return _user_repo.get_user_with_hash(username)


def check_password_against_user(username: str, password: str) -> bool:
    """Return True if the provided password matches the user's current password."""
    row = _user_repo.get_user_with_hash(username)
    if not row:
        return False
    return _check_password(password, row['password_hash'], row['salt'])


def list_users() -> list[dict]:
    return _user_repo.list_users()


def create_user(username: str, password: str, name: str, role: str = "viewer",
                email: str = "", phone: str = "", department: str = "") -> dict:
    h, salt = _hash_password(password)
    _user_repo.create_user(
        username, name, role, email, phone, h, salt, 1, time.time(), department
    )
    _trigger_backup()
    return {"username": username, "name": name, "role": role,
            "email": email, "phone": phone, "department": department}


def update_user(username: str, name: str = None, role: str = None, department: str = None,
                password: str = None, active: bool = None, email: str = None, phone: str = None) -> dict:
    result = _user_repo.update_user(
        username, name=name, role=role, department=department,
        password=password, active=active, email=email, phone=phone
    )
    _trigger_backup()
    return result


def delete_user(username: str):
    """Soft-delete: deactivates the user (active=0). Row is kept so it can be restored.
    Use this instead of hard DELETE to prevent accidental permanent data loss."""
    _user_repo.delete_user(username)
    with _sess_lock:
        to_remove = [t for t, s in _sessions.items() if s["user"] == username]
        for t in to_remove:
            del _sessions[t]
    _trigger_backup()


def restore_user(username: str) -> dict:
    """Restore a soft-deleted (inactive) user by setting active=1."""
    result = _user_repo.restore_user(username)
    _trigger_backup()
    return result


def invalidate_user_sessions(username: str):
    """Destroy all active sessions for a given user (e.g., after password reset)."""
    with _sess_lock:
        to_remove = [t for t, s in _sessions.items() if s["user"] == username]
        for t in to_remove:
            del _sessions[t]


# ── Session management ────────────────────────────────────────────────────────

def create_session(username: str, role: str, name: str, department: str = '') -> str:
    token = secrets.token_hex(32)
    with _sess_lock:
        _sessions[token] = {"user": username, "name": name, "role": role, "department": department,
                            "login_time": time.time(), "last_seen": time.time()}
    _session_repo.record_login(token, username, name, role, department)
    return token


def _maybe_touch(token: str, now: float) -> None:
    """Write to DB at most once per _TOUCH_INTERVAL seconds per session."""
    if now - _sess_last_flush.get(token, 0) >= _TOUCH_INTERVAL:
        _sess_last_flush[token] = now
        _session_repo.touch_session(token)


def get_session(token: str) -> dict | None:
    with _sess_lock:
        sess = _sessions.get(token)
        now = time.time()
        if sess and now - sess["login_time"] > 36000:  # 10 hours
            del _sessions[token]
            _sess_last_flush.pop(token, None)
            return None
        if sess:
            sess["last_seen"] = now
            _maybe_touch(token, now)
            return dict(sess)
    persisted = _session_repo.get_session(token)
    if not persisted:
        return None
    now = time.time()
    _maybe_touch(token, now)
    return {
        "user": persisted["username"],
        "name": persisted.get("name") or persisted["username"],
        "role": persisted.get("role") or "",
        "department": persisted.get("department") or "",
        "login_time": persisted["login_time"],
        "last_seen": persisted["last_seen"],
    }


def destroy_session(token: str):
    with _sess_lock:
        _sessions.pop(token, None)
    _session_repo.close_session(token)


def list_sessions() -> list[dict]:
    with _sess_lock:
        now = time.time()
        expired = []
        for token, sess in _sessions.items():
            if now - sess["login_time"] > 36000:  # 10 hours
                expired.append(token)
        for t in expired:
            del _sessions[t]
    return _session_repo.list_active_sessions()
