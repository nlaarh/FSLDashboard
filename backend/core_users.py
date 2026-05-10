"""Postgres CRUD for core.users — primary user store when USERS_PRIMARY=postgres."""

import logging
import time

import bcrypt
import pg_pool

log = logging.getLogger("core_users")

_BCRYPT_ROUNDS = 12

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


def _hash_password(password: str) -> tuple[str, str]:
    pw_bytes = password.encode("utf-8")
    h = bcrypt.hashpw(pw_bytes, bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("utf-8")
    return h, "bcrypt"


def _row_to_public(row: dict) -> dict:
    """Match SQLite get_user / find_by_email return shape."""
    return {
        "username": row.get("username"),
        "name": row.get("name"),
        "role": row.get("role"),
        "email": row.get("email", ""),
        "active": bool(row.get("active", 1)),
        "department": row.get("department") or "",
    }


def _row_to_full(row: dict) -> dict:
    """Match SQLite list_users / update_user return shape."""
    return {
        "username": row.get("username"),
        "name": row.get("name"),
        "role": row.get("role"),
        "email": row.get("email", ""),
        "phone": row.get("phone", ""),
        "active": bool(row.get("active", 1)),
        "created": row.get("created_at"),
        "department": row.get("department") or "",
    }


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _get_raw(username: str) -> dict | None:
    """Return raw row including password_hash and salt."""
    with pg_pool.reader() as conn:
        with conn.cursor() as cur:
            cur.execute("SET search_path = core, public")
            cur.execute("SELECT * FROM users WHERE username = %s", (username,))
            rows = pg_pool.rows_as_dicts(cur)
            return rows[0] if rows else None


def _run_update(username: str, sets: list[str], params: list) -> None:
    if not sets:
        return
    params.append(username)
    with pg_pool.writer() as conn:
        with conn.cursor() as cur:
            cur.execute("SET search_path = core, public")
            cur.execute(
                f"UPDATE users SET {', '.join(sets)} WHERE username = %s",
                params,
            )
        conn.commit()


# ── Public API ────────────────────────────────────────────────────────────────

def get_user(username: str) -> dict | None:
    try:
        with pg_pool.reader() as conn:
            with conn.cursor() as cur:
                cur.execute("SET search_path = core, public")
                cur.execute("SELECT * FROM users WHERE username = %s", (username,))
                rows = pg_pool.rows_as_dicts(cur)
                if rows:
                    return _row_to_public(rows[0])
    except Exception as e:
        log.warning(f"[core_users] get_user failed: {e}")
        raise
    return None


def get_user_with_hash(username: str) -> dict | None:
    """Return raw row including password_hash and salt (for authenticate)."""
    try:
        return _get_raw(username)
    except Exception as e:
        log.warning(f"[core_users] get_user_with_hash failed: {e}")
        raise


def find_by_email(email: str) -> dict | None:
    try:
        with pg_pool.reader() as conn:
            with conn.cursor() as cur:
                cur.execute("SET search_path = core, public")
                cur.execute(
                    "SELECT * FROM users WHERE LOWER(email) = LOWER(%s) AND active = 1",
                    (email,),
                )
                rows = pg_pool.rows_as_dicts(cur)
                if rows:
                    return _row_to_public(rows[0])
    except Exception as e:
        log.warning(f"[core_users] find_by_email failed: {e}")
        raise
    return None


def list_users() -> list[dict]:
    try:
        with pg_pool.reader() as conn:
            with conn.cursor() as cur:
                cur.execute("SET search_path = core, public")
                cur.execute("SELECT * FROM users ORDER BY username")
                rows = pg_pool.rows_as_dicts(cur)
                return [_row_to_full(r) for r in rows]
    except Exception as e:
        log.warning(f"[core_users] list_users failed: {e}")
        raise


def create_user(
    username,
    name,
    role,
    email,
    phone,
    password_hash,
    salt,
    active,
    created_at,
    department,
):
    try:
        with pg_pool.writer() as conn:
            with conn.cursor() as cur:
                cur.execute("SET search_path = core, public")
                cur.execute(
                    """
                    INSERT INTO users
                        (username, name, role, email, phone, password_hash, salt, active, created_at, department)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        username,
                        name,
                        role,
                        email,
                        phone,
                        password_hash,
                        salt,
                        active,
                        created_at,
                        department,
                    ),
                )
            conn.commit()
    except Exception as e:
        log.warning(f"[core_users] create_user failed: {e}")
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise ValueError(f"User '{username}' already exists")
        raise


def update_user(
    username,
    name=None,
    role=None,
    department=None,
    password=None,
    active=None,
    email=None,
    phone=None,
):
    try:
        # Ensure user exists
        row = _get_raw(username)
        if not row:
            raise ValueError(f"User '{username}' not found")

        sets = []
        params = []
        if name is not None:
            sets.append("name = %s")
            params.append(name)
        if role is not None:
            sets.append("role = %s")
            params.append(role)
        if department is not None:
            sets.append("department = %s")
            params.append(department)
        if email is not None:
            sets.append("email = %s")
            params.append(email)
        if phone is not None:
            sets.append("phone = %s")
            params.append(phone)
        if active is not None:
            sets.append("active = %s")
            params.append(1 if active else 0)
        if password is not None:
            h, salt = _hash_password(password)
            sets.append("password_hash = %s")
            params.append(h)
            sets.append("salt = %s")
            params.append(salt)

        _run_update(username, sets, params)

        # Return updated row
        updated = _get_raw(username)
        return _row_to_full(updated)
    except ValueError:
        raise
    except Exception as e:
        log.warning(f"[core_users] update_user failed: {e}")
        raise


def update_password_hash(username: str, password_hash: str, salt: str) -> None:
    """Direct hash update for bcrypt auto-migration."""
    try:
        _run_update(
            username,
            ["password_hash = %s", "salt = %s"],
            [password_hash, salt],
        )
    except Exception as e:
        log.warning(f"[core_users] update_password_hash failed: {e}")
        raise


def delete_user(username):
    try:
        row = _get_raw(username)
        if not row:
            raise ValueError(f"User '{username}' not found")
        _run_update(username, ["active = %s"], [0])
    except ValueError:
        raise
    except Exception as e:
        log.warning(f"[core_users] delete_user failed: {e}")
        raise


def restore_user(username):
    try:
        row = _get_raw(username)
        if not row:
            raise ValueError(f"User '{username}' not found")
        _run_update(username, ["active = %s"], [1])
        updated = _get_raw(username)
        return _row_to_public(updated)
    except ValueError:
        raise
    except Exception as e:
        log.warning(f"[core_users] restore_user failed: {e}")
        raise
