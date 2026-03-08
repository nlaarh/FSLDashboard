"""User management — JSON file-based user store with session tracking.

Users stored at ~/.fslapp/users.json. Passwords hashed with SHA-256 + salt.
Sessions tracked in-memory (cleared on restart).
"""

import os, json, hashlib, secrets, time, threading
from pathlib import Path

_USERS_FILE = Path(os.path.expanduser("~/.fslapp/users.json"))
_lock = threading.Lock()

# In-memory session store: token -> {user, role, login_time, last_seen}
_sessions: dict[str, dict] = {}
_sess_lock = threading.Lock()


# ── Password hashing ─────────────────────────────────────────────────────────

def _hash_password(password: str, salt: str = None) -> tuple[str, str]:
    """Hash password with SHA-256 + random salt. Returns (hash, salt)."""
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return h, salt


def _check_password(password: str, stored_hash: str, salt: str) -> bool:
    h, _ = _hash_password(password, salt)
    return secrets.compare_digest(h, stored_hash)


# ── User store ────────────────────────────────────────────────────────────────

def _load_users() -> dict:
    """Load users from JSON file. Returns {username: {...}}."""
    with _lock:
        if not _USERS_FILE.exists():
            return {}
        try:
            return json.loads(_USERS_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            return {}


def _save_users(users: dict):
    """Save users to JSON file."""
    with _lock:
        _USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _USERS_FILE.write_text(json.dumps(users, indent=2))


def _ensure_default_admin():
    """Create default admin if no users exist."""
    users = _load_users()
    if not users:
        h, salt = _hash_password("admin2026!@")
        users["admin"] = {
            "name": "Admin",
            "role": "admin",
            "password_hash": h,
            "salt": salt,
            "created": time.time(),
            "active": True,
        }
        _save_users(users)


# Initialize on import
_ensure_default_admin()


# ── Public API ────────────────────────────────────────────────────────────────

def authenticate(username: str, password: str) -> dict | None:
    """Verify credentials. Returns user dict (without password) or None."""
    users = _load_users()
    user = users.get(username)
    if not user or not user.get("active", True):
        return None
    if _check_password(password, user["password_hash"], user["salt"]):
        return {
            "username": username,
            "name": user.get("name", username),
            "role": user.get("role", "viewer"),
        }
    return None


def list_users() -> list[dict]:
    """List all users (without passwords)."""
    users = _load_users()
    result = []
    for username, u in users.items():
        result.append({
            "username": username,
            "name": u.get("name", username),
            "role": u.get("role", "viewer"),
            "active": u.get("active", True),
            "created": u.get("created"),
        })
    return sorted(result, key=lambda u: u["username"])


def create_user(username: str, password: str, name: str, role: str = "viewer") -> dict:
    """Create a new user. Raises ValueError if exists."""
    users = _load_users()
    if username in users:
        raise ValueError(f"User '{username}' already exists")
    h, salt = _hash_password(password)
    users[username] = {
        "name": name,
        "role": role,
        "password_hash": h,
        "salt": salt,
        "created": time.time(),
        "active": True,
    }
    _save_users(users)
    return {"username": username, "name": name, "role": role}


def update_user(username: str, name: str = None, role: str = None,
                password: str = None, active: bool = None) -> dict:
    """Update user fields. Raises ValueError if not found."""
    users = _load_users()
    if username not in users:
        raise ValueError(f"User '{username}' not found")
    u = users[username]
    if name is not None:
        u["name"] = name
    if role is not None:
        u["role"] = role
    if active is not None:
        u["active"] = active
    if password is not None:
        h, salt = _hash_password(password)
        u["password_hash"] = h
        u["salt"] = salt
    _save_users(users)
    return {"username": username, "name": u["name"], "role": u["role"], "active": u["active"]}


def delete_user(username: str):
    """Delete a user. Raises ValueError if not found."""
    users = _load_users()
    if username not in users:
        raise ValueError(f"User '{username}' not found")
    del users[username]
    _save_users(users)
    # Also kill their sessions
    with _sess_lock:
        to_remove = [t for t, s in _sessions.items() if s["user"] == username]
        for t in to_remove:
            del _sessions[t]


# ── Session management ────────────────────────────────────────────────────────

def create_session(username: str, role: str, name: str) -> str:
    """Create a session token for an authenticated user."""
    token = secrets.token_hex(32)
    with _sess_lock:
        _sessions[token] = {
            "user": username,
            "name": name,
            "role": role,
            "login_time": time.time(),
            "last_seen": time.time(),
        }
    return token


def get_session(token: str) -> dict | None:
    """Get session info. Updates last_seen. Returns None if invalid/expired."""
    with _sess_lock:
        sess = _sessions.get(token)
        if not sess:
            return None
        # Expire after 24h
        if time.time() - sess["login_time"] > 86400:
            del _sessions[token]
            return None
        sess["last_seen"] = time.time()
        return dict(sess)


def destroy_session(token: str):
    """Remove a session."""
    with _sess_lock:
        _sessions.pop(token, None)


def list_sessions() -> list[dict]:
    """List all active sessions (for admin view)."""
    now = time.time()
    result = []
    with _sess_lock:
        expired = []
        for token, sess in _sessions.items():
            if now - sess["login_time"] > 86400:
                expired.append(token)
                continue
            result.append({
                "user": sess["user"],
                "name": sess["name"],
                "role": sess["role"],
                "login_time": sess["login_time"],
                "last_seen": sess["last_seen"],
                "idle_min": round((now - sess["last_seen"]) / 60),
            })
        for t in expired:
            del _sessions[t]
    return sorted(result, key=lambda s: s["last_seen"], reverse=True)
