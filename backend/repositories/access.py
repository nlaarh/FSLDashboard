"""Access matrix repository: feature_access and user_extra_roles tables (created by migrations/roles_matrix.py)."""

import json
from datetime import datetime, timezone

import db_adapter

DDL = (
    """CREATE TABLE IF NOT EXISTS feature_access (
        feature TEXT PRIMARY KEY,
        roles TEXT NOT NULL,
        updated_by TEXT,
        updated_at TIMESTAMPTZ
    )""",
    """CREATE TABLE IF NOT EXISTS user_extra_roles (
        username TEXT NOT NULL,
        role TEXT NOT NULL,
        added_by TEXT,
        added_at TIMESTAMPTZ,
        PRIMARY KEY (username, role)
    )""",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_feature_rows() -> list[dict]:
    with db_adapter.reader() as db:
        db.execute("SELECT feature, roles FROM feature_access")
        return db.fetchall()


def read_extra_rows() -> list[dict]:
    with db_adapter.reader() as db:
        db.execute("SELECT username, role FROM user_extra_roles")
        return db.fetchall()


def save_features(changes: dict, actor: str) -> None:
    """One transaction. A list stores the roles; None deletes the row (back to the code default)."""
    with db_adapter.writer() as db:
        for feature, roles in changes.items():
            if roles is None:
                db.execute("DELETE FROM feature_access WHERE feature = %s", (feature,))
            else:
                db.execute(
                    """INSERT INTO feature_access (feature, roles, updated_by, updated_at) VALUES (%s, %s, %s, %s)
                       ON CONFLICT (feature) DO UPDATE SET roles = EXCLUDED.roles,
                       updated_by = EXCLUDED.updated_by, updated_at = EXCLUDED.updated_at""",
                    (feature, json.dumps(sorted(roles)), actor, _now()),
                )
        db.commit()


def save_user_roles(plan: list, actor: str) -> None:
    """plan: [(username, primary, set of extra roles)]. Primary role and extra roles of every user in ONE transaction."""
    with db_adapter.writer() as db:
        for username, primary, roles in plan:
            db.execute("UPDATE users SET role = %s WHERE username = %s", (primary, username))
            db.execute("DELETE FROM user_extra_roles WHERE username = %s", (username,))
            for role in sorted(roles):
                db.execute("INSERT INTO user_extra_roles (username, role, added_by, added_at) VALUES (%s, %s, %s, %s)",
                           (username, role, actor, _now()))
        db.commit()


def _user_filter(q: str, role: str) -> tuple[str, list]:
    where, params = "1=1", []
    if q:
        where += " AND (LOWER(u.username) LIKE %s OR LOWER(u.name) LIKE %s)"
        params += [f"%{q.lower()}%"] * 2
    if role:
        where += " AND (u.role = %s OR u.username IN (SELECT username FROM user_extra_roles WHERE role = %s))"
        params += [role, role]
    return where, params


def list_users_page(page: int, page_size: int, q: str = "", role: str = "") -> tuple[int, list[dict]]:
    """(total, rows) of users with their extra roles, ordered by username."""
    where, params = _user_filter(q, role)
    with db_adapter.reader() as db:
        db.execute(f"SELECT COUNT(*) AS n FROM users u WHERE {where}", params)
        total = db.fetchone()["n"]
        db.execute(
            f"SELECT u.username, u.name, u.active, u.department, u.role FROM users u WHERE {where} "
            "ORDER BY u.username LIMIT %s OFFSET %s", params + [page_size, (page - 1) * page_size])
        rows = db.fetchall()
        extras: dict[str, list[str]] = {}
        if rows:
            marks = ",".join(["%s"] * len(rows))
            db.execute(f"SELECT username, role FROM user_extra_roles WHERE username IN ({marks}) ORDER BY role",
                       [r["username"] for r in rows])
            for e in db.fetchall():
                extras.setdefault(e["username"], []).append(e["role"])
    return total, [{**r, "active": bool(r["active"]), "department": r["department"] or "",
                    "extra": extras.get(r["username"], [])} for r in rows]


def count_active_superadmins(excluding: set) -> int:
    with db_adapter.reader() as db:
        db.execute("SELECT username FROM users WHERE role = 'superadmin' AND active = 1")
        return len([r for r in db.fetchall() if r["username"] not in excluding])
