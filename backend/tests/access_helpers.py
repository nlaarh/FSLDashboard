"""Helpers shared by the access matrix tests."""
import json
import time

import access_store
from permissions import FEATURE_ROLES, LOCKED_FEATURES


def add_user(db, username, role="viewer", name=None, active=1):
    db.execute("INSERT OR REPLACE INTO users (username, name, role, password_hash, salt, active, created_at, department) "
               "VALUES (?, ?, ?, 'x', 'bcrypt', ?, ?, '')", (username, name or username, role, active, time.time()))
    db.commit()


def seed_features(db):
    """Same rows the migration script inserts."""
    for f, roles in FEATURE_ROLES.items():
        if f not in LOCKED_FEATURES:
            db.execute("INSERT OR IGNORE INTO feature_access (feature, roles, updated_by) VALUES (?, ?, 'migration')",
                       (f, json.dumps(sorted(roles))))
    db.commit()
    access_store.invalidate()


def add_extra(db, username, role):
    db.execute("INSERT INTO user_extra_roles (username, role) VALUES (?, ?)", (username, role))
    db.commit()
    access_store.invalidate()


def hide_access_tables(db, *names):
    """Simulate missing tables in the throwaway in-memory test database by renaming them."""
    for name in names:
        db.execute(f"ALTER TABLE {name} RENAME TO {name}_hidden")
    db.commit()
