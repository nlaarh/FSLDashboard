"""User repository — unified CRUD via db_adapter.

Replaces direct calls to core_users.py and users.py database functions.
All SQL uses %%s placeholders (db_adapter handles SQLite conversion).
"""

import logging

import bcrypt
import db_adapter

log = logging.getLogger("repo.users")

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
    h = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("utf-8")
    return h, "bcrypt"


def _row_to_public(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {
        "username": row.get("username"),
        "name": row.get("name"),
        "role": row.get("role"),
        "email": row.get("email", ""),
        "active": bool(row.get("active", 1)),
        "department": row.get("department") or "",
    }


def _row_to_full(row: dict | None) -> dict | None:
    if row is None:
        return None
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


def _get_raw(username: str) -> dict | None:
    """Return raw row including password_hash and salt."""
    with db_adapter.reader() as db:
        db.execute("SELECT * FROM users WHERE username = %s", (username,))
        return db.fetchone()


def get_user(username: str) -> dict | None:
    try:
        with db_adapter.reader() as db:
            db.execute("SELECT * FROM users WHERE username = %s", (username,))
            row = db.fetchone()
            if row:
                return _row_to_public(row)
    except Exception as e:
        log.warning(f"[repo.users] get_user failed: {e}")
        raise
    return None


def get_user_with_hash(username: str) -> dict | None:
    """Return raw row including password_hash and salt (for authenticate)."""
    try:
        return _get_raw(username)
    except Exception as e:
        log.warning(f"[repo.users] get_user_with_hash failed: {e}")
        raise


def find_by_email(email: str) -> dict | None:
    """Find active user by email (case-insensitive)."""
    try:
        with db_adapter.reader() as db:
            db.execute(
                "SELECT * FROM users WHERE LOWER(email) = LOWER(%s) AND active = 1",
                (email,),
            )
            row = db.fetchone()
            if row:
                return _row_to_public(row)
    except Exception as e:
        log.warning(f"[repo.users] find_by_email failed: {e}")
        raise
    return None


def list_users() -> list[dict]:
    try:
        with db_adapter.reader() as db:
            db.execute("SELECT * FROM users ORDER BY username")
            rows = db.fetchall()
            return [_row_to_full(r) for r in rows if r is not None]
    except Exception as e:
        log.warning(f"[repo.users] list_users failed: {e}")
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
        with db_adapter.writer() as db:
            db.execute(
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
            db.commit()
    except Exception as e:
        log.warning(f"[repo.users] create_user failed: {e}")
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

        if not sets:
            return _row_to_full(row)

        params.append(username)
        with db_adapter.writer() as db:
            db.execute(
                f"UPDATE users SET {', '.join(sets)} WHERE username = %s",
                params,
            )
            db.commit()

        updated = _get_raw(username)
        return _row_to_full(updated)
    except ValueError:
        raise
    except Exception as e:
        log.warning(f"[repo.users] update_user failed: {e}")
        raise


def update_password_hash(username: str, password_hash: str, salt: str) -> None:
    """Direct hash update for bcrypt auto-migration."""
    try:
        with db_adapter.writer() as db:
            db.execute(
                "UPDATE users SET password_hash = %s, salt = %s WHERE username = %s",
                (password_hash, salt, username),
            )
            db.commit()
    except Exception as e:
        log.warning(f"[repo.users] update_password_hash failed: {e}")
        raise


def delete_user(username):
    """Soft-delete: deactivates the user (active=0)."""
    try:
        row = _get_raw(username)
        if not row:
            raise ValueError(f"User '{username}' not found")
        with db_adapter.writer() as db:
            db.execute(
                "UPDATE users SET active = %s WHERE username = %s",
                (0, username),
            )
            db.commit()
    except ValueError:
        raise
    except Exception as e:
        log.warning(f"[repo.users] delete_user failed: {e}")
        raise


def restore_user(username):
    """Restore a soft-deleted (inactive) user by setting active=1."""
    try:
        row = _get_raw(username)
        if not row:
            raise ValueError(f"User '{username}' not found")
        with db_adapter.writer() as db:
            db.execute(
                "UPDATE users SET active = %s WHERE username = %s",
                (1, username),
            )
            db.commit()
        updated = _get_raw(username)
        return _row_to_public(updated)
    except ValueError:
        raise
    except Exception as e:
        log.warning(f"[repo.users] restore_user failed: {e}")
        raise
