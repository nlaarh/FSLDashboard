"""Create the access matrix tables and seed them from the current code defaults.

    python migrations/roles_matrix.py --preview   # prints the SQL and row counts; opens NO database connection
    python migrations/roles_matrix.py --apply     # creates the tables and seeds (run once, after a backup)

Additive only: users is not touched. feature_access gets one row per editable feature copied from
permissions.FEATURE_ROLES (existing rows are kept); user_extra_roles starts empty, so every user keeps
exactly their single role and every feature exactly its current roles. The app works with or without these tables.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from permissions import FEATURE_ROLES, LOCKED_FEATURES  # noqa: E402
from repositories.access import DDL  # noqa: E402

SEED_SQL = ("INSERT INTO feature_access (feature, roles, updated_by, updated_at) "
            "VALUES (%s, %s, 'migration', CURRENT_TIMESTAMP) ON CONFLICT (feature) DO NOTHING")


def seed_rows() -> list[tuple[str, str]]:
    return [(f, json.dumps(sorted(r))) for f, r in FEATURE_ROLES.items() if f not in LOCKED_FEATURES]


def preview() -> None:
    print("-- PREVIEW only: nothing is connected or written --")
    for ddl in DDL:
        print(ddl.strip() + ";")
    for row in seed_rows():
        print(f"{SEED_SQL}  -- {row}")
    print(f"-- would create 2 tables, seed {len(seed_rows())} feature_access rows, 0 user_extra_roles rows")


def apply() -> None:
    import db_adapter
    with db_adapter.writer() as db:
        for ddl in DDL:
            db.execute(ddl)
        for row in seed_rows():
            db.execute(SEED_SQL, row)
        db.commit()
    print(f"Created tables and seeded {len(seed_rows())} feature_access rows.")


if __name__ == "__main__":
    if sys.argv[1:] == ["--preview"]:
        preview()
    elif sys.argv[1:] == ["--apply"]:
        apply()
    else:
        sys.exit(__doc__)
