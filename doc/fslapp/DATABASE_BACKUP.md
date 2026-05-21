# FSLAPP Database Backup & Restore

## Architecture Overview

Two backup layers protect the SQLite database:

| Layer | What | Where | When |
|-------|------|--------|------|
| 1 | SQLite → Azure Blob (JSON) | `optimizer-files/db-backups/` | Automatic every 6h, keeps last 7 |
| 2 | Azure Blob → Postgres `core.*` | `fslapp-pg.postgres.database.azure.com` | Manual (run `sqlite_to_core.py`) |

**Tables backed up:** `users`, `settings`, `bonus_tiers`, `accounting_rates`, `woa_reviews`, `watchlist_manual`

**Tables NOT backed up:** `cache`, `activity_log`, `opt_sync_audit` (ephemeral — safe to lose)

---

## Running a Manual Backup

```bash
cd FSL/apidev/FSLAPP/backend
source ../../venv/bin/activate

python3 -c "
from dotenv import load_dotenv
load_dotenv('../../.env')
import db_backup
db_backup.backup_now()
"
```

The auto-backup thread also runs every 6 hours after app startup (5-minute stagger on first run).

---

## Listing Available Backups

```bash
cd FSL/apidev/FSLAPP/backend
source ../../venv/bin/activate

python3 -c "
from dotenv import load_dotenv; load_dotenv('../../.env')
import os
from azure.storage.blob import BlobServiceClient
c = BlobServiceClient.from_connection_string(os.environ['AZ_OPT_CONNECTION_STRING'])
blobs = sorted(
    c.get_container_client(os.environ['AZ_OPT_CONTAINER']).list_blobs(name_starts_with='db-backups/fslapp_'),
    key=lambda b: b.name,
    reverse=True
)
for b in blobs:
    print(b.name, f'{b.size:,} bytes')
"
```

---

## Restore: SQLite from Azure Blob (Layer 1)

### Automatic (already wired in)

On every app startup, if SQLite is empty (e.g., after container crash or corruption), `main.py` calls `db_backup.restore_latest()` automatically. No manual action needed.

### Manual restore (latest backup)

Use this to restore on a fresh machine or after manually deleting the SQLite file:

```bash
cd FSL/apidev/FSLAPP/backend
source ../../venv/bin/activate

python3 -c "
from dotenv import load_dotenv
load_dotenv('../../.env')
import db_backup
db_backup.restore_latest()
"
```

### Full rollback to a specific backup

The restore uses `INSERT OR IGNORE` — it will NOT overwrite rows that already exist. To do a true rollback to an older snapshot:

1. Stop the app
2. Delete (or rename) the SQLite file: `~/.fslapp/fslapp.db`
3. Restart the app — auto-restore will pull the latest blob on startup

To roll back to a specific older snapshot instead of the latest, manually download the blob and call `_import_tables`:

```bash
python3 -c "
from dotenv import load_dotenv; load_dotenv('../../.env')
import os, json
from azure.storage.blob import BlobServiceClient
import db_backup

# Replace with the target snapshot name from the listing above
SNAPSHOT = 'db-backups/fslapp_20260509_061605.json'

c = BlobServiceClient.from_connection_string(os.environ['AZ_OPT_CONNECTION_STRING'])
raw = c.get_container_client(os.environ['AZ_OPT_CONTAINER']).get_blob_client(SNAPSHOT).download_blob().readall()
data = json.loads(raw)
db_backup._import_tables(data)
print('Restored from', SNAPSHOT)
"
```

---

## Sync to Postgres (Layer 2)

Syncs the latest Azure Blob backup into Postgres `core.*`. Safe to re-run — uses `ON CONFLICT DO NOTHING`.

```bash
cd FSL/apidev/FSLAPP/backend
source ../../venv/bin/activate

python3 -c "
from dotenv import load_dotenv
load_dotenv('../../.env')
import migrations.sqlite_to_core as m
m.main()
"
```

Requires: `az login` active as `nlaaroubi@nyaaa.com` (Entra ID auth for Postgres).

---

## Important: Always Use `load_dotenv`, Not `source .env`

The `AZ_OPT_CONNECTION_STRING` value contains semicolons. Bash's `source .env` mangles it, causing:

```
ValueError: Connection string missing required connection details.
```

Always load environment variables via Python's `dotenv.load_dotenv('../../.env')`, as shown in all examples above.

---

## File Locations

| File | Purpose |
|------|---------|
| `backend/db_backup.py` | Backup/restore logic, background thread |
| `backend/migrations/sqlite_to_core.py` | Sync blob backup → Postgres |
| `infra/postgres/init-schema.sql` | Postgres `core.*` schema DDL |
| `~/.fslapp/fslapp.db` | Live SQLite database |
| Azure Blob `optimizer-files/db-backups/` | JSON snapshots (last 7) |
| `fslapp-pg.postgres.database.azure.com/fslapp` (schema `core`) | Postgres secondary store |
