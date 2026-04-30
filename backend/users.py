"""User management — SQLite-based user store with session tracking.

Users stored in SQLite database (fslapp.db). Passwords hashed with SHA-256 + salt.
Sessions tracked in-memory (cleared on restart).
"""

import hashlib, secrets, time, threading

import database as db

_sess_lock = threading.Lock()
_sessions: dict[str, dict] = {}


# ── Password hashing ─────────────────────────────────────────────────────────

def _hash_password(password: str, salt: str = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return h, salt


def _check_password(password: str, stored_hash: str, salt: str) -> bool:
    h, _ = _hash_password(password, salt)
    return secrets.compare_digest(h, stored_hash)


# ── Seed default users (only if users table is empty) ────────────────────────
# Passwords come from env vars — never stored in source code.

_SEED_USER_DEFS = [
    ('admin',               'SEED_PASS_ADMIN',     'Admin',         'admin',      '',                    ''),
    ('tingraham@nyaaa.com', 'SEED_PASS_TINGRAHAM', 'Tina Ingraham', 'manager',    'tingraham@nyaaa.com', ''),
    ('dfisher@nyaaa.com',   'SEED_PASS_DFISHER',   'D Fisher',      'manager',    'dfisher@nyaaa.com',   ''),
    ('nlaaroubi@nyaaa.com', 'SEED_PASS_NLAAROUBI', 'Nour Laaroubi', 'superadmin', 'nlaaroubi@nyaaa.com', ''),
    ('shorn@nyaaa.com',     'SEED_PASS_SHORN',     'S Horn',        'manager',    'shorn@nyaaa.com',     ''),
    ('jnixon@nyaaa.com',    'SEED_PASS_JNIXON',    'J Nixon',       'officer',    'jnixon@nyaaa.com',    ''),
]


def seed_users():
    """Seed default users ONLY if users table is empty. Passwords read from SEED_PASS_* env vars."""
    import os, logging
    _log = logging.getLogger('users')
    with db.get_db() as conn:
        count = conn.execute("SELECT COUNT(*) cnt FROM users").fetchone()['cnt']
        if count > 0:
            return  # users exist, don't touch
        seeded = 0
        for username, env_var, name, role, email, phone in _SEED_USER_DEFS:
            password = os.getenv(env_var)
            if not password:
                _log.warning(f"Skipping seed for {username}: {env_var} not set in env")
                continue
            h, salt = _hash_password(password)
            conn.execute(
                "INSERT OR IGNORE INTO users (username, name, role, email, phone, password_hash, salt, active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)",
                (username, name, role, email, phone, h, salt, time.time()),
            )
            seeded += 1
        if seeded == 0:
            _log.error("Users table is empty and no SEED_PASS_* env vars found — set them in .env")


def migrate_json_users():
    """One-time migration: read users.json → insert into SQLite → rename to .bak."""
    import os, json
    from pathlib import Path
    json_path = Path(os.path.expanduser('~/.fslapp/users.json'))
    if not json_path.exists():
        return
    try:
        users = json.loads(json_path.read_text())
    except Exception:
        return
    with db.get_db() as conn:
        for username, u in users.items():
            conn.execute(
                """INSERT OR IGNORE INTO users (username, name, role, email, phone, password_hash, salt, active, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (username, u.get('name', username), u.get('role', 'viewer'), u.get('email', ''),
                 u.get('phone', ''), u['password_hash'], u['salt'],
                 1 if u.get('active', True) else 0, u.get('created', time.time())),
            )
    try:
        json_path.rename(json_path.with_suffix('.json.migrated'))
    except Exception:
        pass


# ── Public API ────────────────────────────────────────────────────────────────

def _dept(row) -> str:
    try:
        return row['department'] or ''
    except Exception:
        return ''


def authenticate(username: str, password: str) -> dict | None:
    with db.get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ? AND active = 1", (username,)).fetchone()
        if not row:
            return None
        if _check_password(password, row['password_hash'], row['salt']):
            return {"username": row['username'], "name": row['name'], "role": row['role'],
                    "email": row['email'], "department": _dept(row)}
    return None


def get_user(username: str) -> dict | None:
    with db.get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not row:
            return None
        return {"username": row['username'], "name": row['name'], "role": row['role'],
                "email": row['email'], "active": bool(row['active']), "department": _dept(row)}


def list_users() -> list[dict]:
    with db.get_db() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY username").fetchall()
        return [{"username": r['username'], "name": r['name'], "role": r['role'],
                 "email": r['email'], "phone": r['phone'], "active": bool(r['active']),
                 "created": r['created_at'], "department": _dept(r)} for r in rows]


def create_user(username: str, password: str, name: str, role: str = "viewer",
                email: str = "", phone: str = "", department: str = "") -> dict:
    h, salt = _hash_password(password)
    try:
        with db.get_db() as conn:
            conn.execute(
                "INSERT INTO users (username, name, role, email, phone, password_hash, salt, active, created_at, department) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                (username, name, role, email, phone, h, salt, time.time(), department),
            )
    except Exception:
        raise ValueError(f"User '{username}' already exists")
    return {"username": username, "name": name, "role": role, "email": email, "phone": phone, "department": department}


def update_user(username: str, name: str = None, role: str = None, department: str = None,
                password: str = None, active: bool = None, email: str = None, phone: str = None) -> dict:
    with db.get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not row:
            raise ValueError(f"User '{username}' not found")
        updates = []
        params = []
        if name is not None:
            updates.append("name = ?"); params.append(name)
        if role is not None:
            updates.append("role = ?"); params.append(role)
        if department is not None:
            updates.append("department = ?"); params.append(department)
        if email is not None:
            updates.append("email = ?"); params.append(email)
        if phone is not None:
            updates.append("phone = ?"); params.append(phone)
        if active is not None:
            updates.append("active = ?"); params.append(1 if active else 0)
        if password is not None:
            h, salt = _hash_password(password)
            updates.append("password_hash = ?"); params.append(h)
            updates.append("salt = ?"); params.append(salt)
        if updates:
            params.append(username)
            conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE username = ?", params)
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return {"username": row['username'], "name": row['name'], "role": row['role'],
                "active": bool(row['active']), "email": row['email'], "phone": row['phone'],
                "department": _dept(row)}


def delete_user(username: str):
    with db.get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not row:
            raise ValueError(f"User '{username}' not found")
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
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
    return token


def get_session(token: str) -> dict | None:
    with _sess_lock:
        sess = _sessions.get(token)
        if not sess:
            return None
        if time.time() - sess["login_time"] > 86400:
            del _sessions[token]
            return None
        sess["last_seen"] = time.time()
        return dict(sess)


def destroy_session(token: str):
    with _sess_lock:
        _sessions.pop(token, None)


def list_sessions() -> list[dict]:
    now = time.time()
    result = []
    with _sess_lock:
        expired = []
        for token, sess in _sessions.items():
            if now - sess["login_time"] > 86400:
                expired.append(token)
                continue
            result.append({"user": sess["user"], "name": sess["name"], "role": sess["role"],
                           "login_time": sess["login_time"], "last_seen": sess["last_seen"],
                           "idle_min": round((now - sess["last_seen"]) / 60)})
        for t in expired:
            del _sessions[t]
    return sorted(result, key=lambda s: s["last_seen"], reverse=True)
