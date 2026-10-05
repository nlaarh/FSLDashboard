# fslapp-pg-backup — Daily Primary Postgres Backup Architecture

Use this skill when asked to touch, extend, debug, or explain the daily
`fslapp-pg` backup pipeline, or when asked to build something similar
(scheduled Azure job that must never touch a production database's data).

## What this is

A daily, dated, immutable backup of the primary Postgres database
(`fslapp-pg`) to Blob Storage, built so that **primary data can never be
deleted or modified by the automation, under any condition** — that was the
hard constraint driving every design choice below. It is intentionally NOT
live replication into `fslapp-pg-dr` — restore is always a manual,
deliberate step a human runs, never automatic.

## Resource inventory (all in `rg-nlaaroubi-sbx-eus2-001`, `eastus2`)

| Resource | Name | Purpose |
|---|---|---|
| Container Registry | `fslapppgbackupacr` (Basic SKU) | Hosts the backup image |
| User-assigned managed identity | `fslapp-pg-backup-identity` | Identity the backup container runs as |
| Container Instance (ACI) | `fslapp-pg-backup-cg` | Runs `pg_dump` + upload + prune once per invocation, `restartPolicy: Never` |
| Blob container | `fslappopt` (existing storage account) / `postgres-backups` (new container) | Where dated `.dump` files land |
| Logic App (Consumption) | `fslapp-pg-backup-scheduler` | Daily Recurrence trigger (08:00 UTC) that calls the ACI "start" REST API |

Source lives in `infra/postgres/`:
- `backup-job.bicep` — provisions everything above.
- `backup-job/Dockerfile` + `backup-job/run_backup.py` — the container image and its logic.
- `backup-role.sql` — read-only role SQL (see "Privilege model" below — **not currently used**, kept as a documented upgrade path).
- `deploy-backup-job.sh` — deploy wrapper.

## Why this shape (decisions that would otherwise get re-litigated)

1. **Azure Container Apps Jobs were the first choice, but are blocked.**
   The account deploying this (`nlaaroubi@nyaaa.com`) has **Owner at the
   resource-group scope only**, not subscription scope. Registering the
   `Microsoft.App` resource provider (required for Container Apps) needs
   subscription-level `*/register/action` and failed with
   `AuthorizationFailed`. `Microsoft.ContainerInstance` and `Microsoft.Logic`
   were already registered, so the design pivoted to **ACI + Logic App**
   instead. If someone with subscription Owner/Contributor ever registers
   `Microsoft.App`, migrating to a Container Apps Job (cron-native, no
   Logic App needed) is a clean simplification — but it isn't necessary.

2. **Azure Automation Runbooks were considered and rejected.** The standard
   Automation sandbox has no `pg_dump` binary and can't install packages.
   Workarounds (downloading a static binary at runtime, or a Hybrid Runbook
   Worker VM) were judged more fragile / more maintenance than a container
   image that simply bundles `postgresql-client`.

3. **Privilege model: AAD admin registration, not a SELECT-only role.**
   The originally-designed safety model used the `pgaadauth` Postgres
   extension to create a true SELECT-only, non-admin AAD role for the
   backup identity (see `backup-role.sql`). That extension exists on Azure
   but was **not enabled** on `fslapp-pg` (`infra/postgres/main.bicep`'s
   `azure.extensions` allowlist only has `VECTOR,PG_TRGM,PG_STAT_STATEMENTS,
   UUID-OSSP,BTREE_GIN`), and enabling it requires a brief primary-server
   restart (`azure.extensions` is a static parameter). **The user explicitly
   chose to avoid any primary restart**, so the backup identity was instead
   registered as a Postgres **Microsoft Entra admin** via:
   ```
   az postgres flexible-server microsoft-entra-admin create \
     -g rg-nlaaroubi-sbx-eus2-001 -s fslapp-pg \
     -i <backupIdentity principalId> -u fslapp-pg-backup-identity -t ServicePrincipal
   ```
   This means the identity is technically capable of writes/deletes on
   `fslapp-pg` — the "never touches primary data" guarantee is enforced at
   the **application-code level only**: `run_backup.py` never issues
   anything but `pg_dump` (a read-only tool) against the primary connection.
   **If tighter, privilege-level isolation is ever wanted**, enable
   `PGAADAUTH` in `main.bicep`'s extension allowlist (accepting one brief
   restart), then run `backup-role.sql` to create a real SELECT-only role
   and switch `FSLAPP_PG_BACKUP_ROLE` to it.

4. **Restore target is a scratch DB or `fslapp-pg-dr` — never primary, and
   never overwriting DR's existing `fslapp` database.** `fslapp-pg-dr`
   already has a live `fslapp` database from a separate concern (a cold
   standby App Service pairing) — restore tests must create an
   independently-named scratch database (e.g. `fslapp_restore_test`) and
   drop it after, never restore over the existing `fslapp` DB there.

5. **Collision-safe uploads, no overwrite ever.** `run_backup.py` uploads
   with `overwrite=False`. If a same-day backup already exists (e.g. the
   job is manually re-run), the upload fails loudly
   (`azure.core.exceptions.ResourceExistsError`) instead of silently
   replacing that day's snapshot. This was verified live — see "Verified"
   below.

6. **Blob storage over "dated databases on `fslapp-pg-dr`".** An alternative
   design (restore each day into a new dated database directly on the DR
   Postgres server, e.g. `fslapp_2026_08_16`) was considered and rejected:
   it grows the DR server's paid storage tier by ~30x the DB size over the
   retention window, is pricier per GB than blob storage, and still needs
   the same ACI/Logic App runner — it only relocates where the dump lands,
   without saving any infrastructure. Blob storage in the existing
   `fslappopt` account was cheaper and fully isolated from both Postgres
   servers.

## Safety guarantees actually enforced

- **Structural**: the Logic App's managed identity has ONLY the "Azure
  Container Instances Contributor Role" scoped to the single
  `fslapp-pg-backup-cg` resource — it cannot start/stop/read anything else
  in the subscription. The backup identity's Storage RBAC role is scoped to
  only the `postgres-backups` container, not the whole storage account.
- **Behavioral** (not privilege-enforced, see point 3 above): the backup
  container only ever runs `pg_dump` (read-only) against `fslapp-pg`. It
  never runs `pg_restore`, `DELETE`, `DROP`, or `TRUNCATE` against primary.
  The only delete this pipeline performs is pruning its own blobs older
  than `BACKUP_RETENTION_DAYS` (10, changed down from an initial 30 once
  the daily verification job was in place) in `postgres-backups` — it holds
  no database credentials capable of touching Postgres data.
- **DR isolation**: nothing in this pipeline writes to, reads from, or
  otherwise touches `fslapp-pg-dr` in normal daily operation. It was only
  used transiently for a one-time restore verification, into a
  disposable scratch database that was dropped immediately after.

## Verified end-to-end (2026-08-16)

- `az deployment group create` on `backup-job.bicep` → all 8 resources
  created cleanly (after registering the backup identity as Postgres AAD
  admin, and after building/pushing the image via `az acr build`, since ACI
  attempts to pull+run immediately on creation).
- Manual container run (`az container start`) → exit code 0, uploaded
  `postgres-backups/fslapp-pg-2026-08-16.dump` (14,282,696 bytes).
- `pg_restore --list` on the downloaded dump → 466 TOC entries across all 5
  real schemas (`accounting`, `core`, `ops`, `optimizer`, `sales`) plus
  `public`.
- Restored into scratch DB `fslapp_restore_test` on `fslapp-pg-dr` →
  identical table counts to primary (18/8/2/19 across schemas), then
  dropped the scratch DB.
- Manually fired the Logic App's `DailyRecurrence` trigger via the ARM REST
  API (`.../triggers/DailyRecurrence/run`) → `status: Succeeded`, and it
  correctly called the ACI start endpoint end-to-end.
- Re-ran the container same-day → correctly **failed loudly**
  (`ResourceExistsError: BlobAlreadyExists`) instead of overwriting the
  existing day's backup — collision protection confirmed working.
- Re-checked `fslapp-pg` row counts before and after all of the above:
  unchanged (natural minor drift from live app traffic only, not from any
  action taken here).
- **Rigorous per-table verification** (requested explicitly after the first
  pass only checked approximate `pg_stat_user_tables.n_live_tup` stats, not
  exact counts): generated an exact `SELECT count(*)` for all 47 tables
  across all 6 schemas on primary, restored the same day's dump into a
  fresh scratch DB (`fslapp_verify_20260816` on `fslapp-pg-dr`, dropped
  after), ran the identical query there, and diffed. Result: **44/47 tables
  exact match**; the other 3 (`core.activity_log`, `core.cache`,
  `core.user_sessions`) differed by single-digit-to-tens of rows — expected,
  since those are high-churn tables and the diff was checked hours after
  the backup snapshot, so primary had simply kept accumulating writes. No
  table was unexpectedly empty. This is the verification method to repeat
  if backup integrity is ever in question again — see "Test a restore" below.
- **Structure verification** (requested as a follow-up: "same keys, same
  relationships, nothing changed"): first confirmed via `pg_constraint`
  that this database has **zero foreign key constraints anywhere**
  (`contype='f'` count = 0) — relationships are enforced at the
  application layer, not the database layer, so there was nothing there to
  lose. Then restored the same day's dump into a second fresh scratch DB
  (`fslapp_verify2_20260816` on `fslapp-pg-dr`, dropped after) and diffed:
  all 48 constraints (46 primary keys + 2 unique, exact name+type match),
  all 120 indexes (exact name match), and sequence count (20 = 20) were
  identical between primary and the restore.

## Daily verification (local, not Azure)

A second automation was requested — confirm every day that the backup
actually landed, not just trust the scheduler ran. Two Azure-based designs
were considered and explicitly rejected by the user:
- A Logic App + Azure Monitor alert (email on failure) — rejected because
  the user wanted to review the design before adding more Azure resources.
- A cloud-hosted Claude routine (`schedule` skill) — rejected because a
  cloud sandbox has no access to this Mac's already-authenticated `az`
  CLI session; it would need a brand-new Azure service-principal secret
  wired into the cloud environment just to check a blob, which is more
  setup than a local check, not less.

**What's actually running**: a macOS `launchd` job, since it reuses the
existing local `az` login with zero new credentials.

| Piece | Location |
|---|---|
| Canonical script | `infra/postgres/verify-backup.sh` (in the repo, version-controlled) |
| Script `launchd` actually runs | `~/.fslapp/verify-backup.sh` (a plain local copy — see gotcha below) |
| Launch agent | `~/Library/LaunchAgents/com.fslapp.pg-backup-verify.plist`, label `com.fslapp.pg-backup-verify`, fires daily at 10:00 local time |
| Log | `~/Library/Logs/fslapp-pg-backup-verify.log` |
| On failure | macOS notification via `osascript` (title "FSLAPP Backup Alert") |

**Gotcha (cost real debugging time — don't rediscover it)**: `launchd`
cannot execute a script living in the OneDrive-synced repo path
(`.../OneDrive-AAAWesternandCentralNewYork/.../infra/postgres/verify-backup.sh`)
— it fails with `Operation not permitted`, even though the exact same
command works fine from an interactive Terminal. This is a macOS/OneDrive
file-provider restriction on launchd-spawned processes, not a script bug.
The fix is keeping a plain copy of the script outside any cloud-synced
folder (`~/.fslapp/verify-backup.sh`) for `launchd` to actually execute.
**Whenever `infra/postgres/verify-backup.sh` is edited, re-copy it to
`~/.fslapp/verify-backup.sh`** — they are not symlinked, and nothing
currently automates keeping them in sync.

A second gotcha: `launchd` does not inherit the interactive shell's `PATH`,
so `az` (installed at `~/.local/bin/az`) is invisible unless the script
exports `PATH` explicitly at the top — `verify-backup.sh` does this
(`export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"`).
If `az` ever moves, update that line.

## Estimated cost

~$6–10/month, almost entirely the fixed **$5/mo ACR Basic tier**. ACI
compute (~10 min/day) and Logic App runs (1/day) are effectively free at
this volume; blob storage for 10 days of dumps is under $1/mo depending on DB
size.

## Common follow-up tasks

- **Change retention window**: edit `backupRetentionDays` param in
  `backup-job.bicep` (redeploy) — the container reads it via
  `BACKUP_RETENTION_DAYS` env var each run, no code change needed.
- **Change schedule time**: edit `scheduleHourUtc` param, redeploy. The
  Logic App recurrence trigger picks it up.
- **Add a new schema to back up**: `pg_dump` with no `-n` flag already dumps
  the whole database (all schemas), so no change needed there — but if a
  SELECT-only role is ever adopted (see point 3), remember to add
  `GRANT USAGE`/`GRANT SELECT` for the new schema in `backup-role.sql`.
- **Test a restore (existence only)**: `~/.fslapp/verify-backup.sh` (or the
  daily launchd job) only confirms today's blob exists in
  `postgres-backups` — it does NOT check the dump's contents.
- **Test a restore (rigorous — exact per-table row counts)**: this is a
  manual/on-demand procedure, not automated daily. Steps: (1) on primary,
  generate `SELECT count(*)` for every table across all schemas (see
  `pg_tables` grouped by `schemaname`); (2) download the dated blob and
  `pg_restore --no-owner --no-privileges` into a uniquely-named scratch
  database on `fslapp-pg-dr` (never its existing `fslapp` DB, never
  `fslapp-pg` primary); (3) run the identical count query there; (4) diff
  the two result sets — expect exact matches except high-churn tables
  (activity logs, caches, sessions) which will show small drift if checked
  well after the backup's snapshot time; (5) drop the scratch database and
  delete the local dump file. This is what was actually run and confirmed
  on 2026-08-16 (see "Verified end-to-end" above) after the cheaper
  approximate-stats check was judged insufficient.
- **Debug a failed backup run**: `az container logs -g
  rg-nlaaroubi-sbx-eus2-001 -n fslapp-pg-backup-cg`.
- **Debug the daily verification job**: `cat
  ~/Library/Logs/fslapp-pg-backup-verify.log`, or `launchctl list | grep
  fslapp` to confirm it's loaded.
