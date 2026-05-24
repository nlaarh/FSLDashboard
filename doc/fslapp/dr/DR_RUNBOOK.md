# FSLAPP — Disaster Recovery Runbook

**Contact:** nlaaroubi@nyaaa.com  
**Last updated:** 2026-05-24  
**RTO target:** ~15 minutes (manual procedure)  
**RPO target:** ~5 minutes (Azure PITR granularity)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        PRIMARY (active)                         │
│                                                                 │
│  fslapp-nyaaa.azurewebsites.net          Canada Central         │
│  App Service P1v3 · Python 3.13                                 │
│       │                                                         │
│       │  FSLAPP_PG_HOST=fslapp-pg.postgres.database.azure.com   │
│       ▼                                                         │
│  fslapp-pg.postgres.database.azure.com   East US 2              │
│  PG Flexible Server PG16 · 64 GiB                               │
│  Schemas: core  optimizer  (shared with SalesPulse → sales)     │
└─────────────────────────────────────────────────────────────────┘

                         PITR restore (periodic)
                                │
                                ▼

┌─────────────────────────────────────────────────────────────────┐
│                     DR STANDBY (idle until failover)            │
│                                                                 │
│  fslapp-nyaaa-dr.azurewebsites.net       West US 2              │
│  App Service P1v3 · Python 3.13                                 │
│       │                                                         │
│       │  FSLAPP_PG_HOST=fslapp-pg-dr.postgres.database.azure.com│
│       ▼                                                         │
│  fslapp-pg-dr.postgres.database.azure.com  East US 2            │
│  PG Flexible Server PG16 · 64 GiB  (independent PITR clone)    │
│  Schemas: core  optimizer  sales                                │
└─────────────────────────────────────────────────────────────────┘
```

**Key architectural facts:**
- `fslapp-pg-dr` is a **PITR clone**, not a streaming replica. It is an independent server created by restoring from `fslapp-pg` at a point in time. There is no continuous replication and no "promote" command.
- The DR DB is shared by both FSLAPP and SalesPulse (schemas `core`/`optimizer` and `sales` respectively). Failing over the DB means **both apps must be redirected simultaneously** — see [Cross-App Coordination](#cross-app-coordination).
- Auth uses Azure Entra managed identities — zero secrets in connection strings. Each app's system-assigned identity must be an Entra user in the PG server with schema grants.

---

## DR Resource Inventory

| Resource | Type | Region | Spec | URL / Hostname |
|---|---|---|---|---|
| `fslapp-nyaaa` | App Service (primary) | Canada Central | P1v3 Premium, Python 3.13 | https://fslapp-nyaaa.azurewebsites.net |
| `fslapp-nyaaa-dr` | App Service (DR) | West US 2 | P1v3 Premium, Python 3.13 | https://fslapp-nyaaa-dr.azurewebsites.net |
| `fslapp-pg` | PG Flexible Server (primary) | East US 2 | PG16, Burstable B2s, 64 GiB | fslapp-pg.postgres.database.azure.com |
| `fslapp-pg-dr` | PG Flexible Server (DR clone) | East US 2 | PG16, Burstable B2s, 64 GiB | fslapp-pg-dr.postgres.database.azure.com |

**Subscription:** `e287db16-b6ae-415e-bd52-41c8ec5a8f08`  
**Resource group:** `rg-nlaaroubi-sbx-eus2-001`

> **Note:** `doc/fslapp/AZURE_INFRASTRUCTURE.md` lists FSLAPP's primary App Service in East US 2 — that is outdated. The primary App Service (`fslapp-nyaaa`) is in **Canada Central**. The DR App Service (`fslapp-nyaaa-dr`) is in **West US 2**.

---

## Normal Operations (Standby Mode)

In normal operation:
- `fslapp-nyaaa` serves all traffic, connected to `fslapp-pg`.
- `fslapp-nyaaa-dr` is **running but idle** (or stopped to reduce cost). It is not proxied by Traffic Manager and receives no user traffic.
- `fslapp-pg-dr` is refreshed periodically (see [DR DB Refresh](#dr-db-refresh-procedure)).
- The DR DB is tested quarterly by performing a smoke-test failover to confirm connectivity and identity grants are intact.

**Estimated data lag:** Equals time since the last PITR refresh. If refreshed weekly, worst-case lag is 7 days. If refreshed daily, worst-case is 24 hours.

---

## Health Page (Admin Panel)

The admin panel (`/admin`) includes a **System Health** tab that reports both primary and DR PostgreSQL status:

- **PostgreSQL card:** Live connectivity ping to `FSLAPP_PG_HOST`
- **DR PostgreSQL card:** Connectivity check against `FSLAPP_PG_DR_HOST` (token-authenticated)

To see DR status navigate to:
```
https://fslapp-nyaaa.azurewebsites.net/admin
```
Enter the admin PIN and open the **System Health** section.

---

## Pre-Failover Prerequisites

Before a failover will succeed, verify these are already in place (they should be set up at DR creation time, not during an incident):

### 1. DR App has code deployed

The DR App Service must have the current application code. Verify:
```bash
az webapp show \
  --name fslapp-nyaaa-dr \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --query "state" --output tsv
```
Expected: `Running`. If the app is stopped, start it:
```bash
az webapp start --name fslapp-nyaaa-dr --resource-group rg-nlaaroubi-sbx-eus2-001
```

### 2. DR App has system-assigned managed identity enabled

```bash
az webapp identity show \
  --name fslapp-nyaaa-dr \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --query "principalId" --output tsv
```
Expected: a non-empty GUID. If empty, enable it:
```bash
az webapp identity assign \
  --name fslapp-nyaaa-dr \
  --resource-group rg-nlaaroubi-sbx-eus2-001
```

### 3. DR App identity is an Entra user on the DR DB with schema grants

The managed identity of `fslapp-nyaaa-dr` must exist as a PostgreSQL Entra user in `fslapp-pg-dr` with grants on `core` and `optimizer`. Connect to the DR DB as an Entra admin and run:

```sql
-- Run as admin (e.g. nlaaroubi@nyaaa.com) against fslapp-pg-dr/fslapp
-- Confirm the MI user exists and has grants:
\du fslapp-nyaaa-dr

-- If missing, create and grant:
CREATE ROLE "fslapp-nyaaa-dr" WITH LOGIN;
SECURITY LABEL FOR "pgaadauth" ON ROLE "fslapp-nyaaa-dr" IS 'aadauth';
GRANT USAGE ON SCHEMA core TO "fslapp-nyaaa-dr";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA core TO "fslapp-nyaaa-dr";
GRANT USAGE ON SCHEMA optimizer TO "fslapp-nyaaa-dr";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA optimizer TO "fslapp-nyaaa-dr";
-- Ensure future tables are also covered:
ALTER DEFAULT PRIVILEGES IN SCHEMA core GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "fslapp-nyaaa-dr";
ALTER DEFAULT PRIVILEGES IN SCHEMA optimizer GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "fslapp-nyaaa-dr";
```

> **PITR grant inheritance:** PITR clones inherit user roles and grants from the source server at restore time. After a fresh PITR refresh, re-verify — roles copy but Entra bindings may need to be re-created.

### 4. DR App env vars are correct

Verify all required env vars exist on `fslapp-nyaaa-dr` (see [Env Var Checklist](#env-var-checklist)). Any env vars missing at DR creation time will cause failures during failover.

---

## Failover Procedure

**Trigger:** Primary app (`fslapp-nyaaa`) or primary DB (`fslapp-pg`) is unavailable or critically degraded with no ETA on recovery.

**Coordinate with SalesPulse:** If failing over the DB, SalesPulse must also redirect simultaneously. See [Cross-App Coordination](#cross-app-coordination).

### Step 1 — Declare incident and set timer

Note the start time. Target: traffic on DR within 15 minutes.

```bash
# Set variables used across all steps
SUB="e287db16-b6ae-415e-bd52-41c8ec5a8f08"
RG="rg-nlaaroubi-sbx-eus2-001"
DR_APP="fslapp-nyaaa-dr"
DR_DB_HOST="fslapp-pg-dr.postgres.database.azure.com"
```

### Step 2 — Start the DR App Service (if stopped)

```bash
az webapp start --name $DR_APP --resource-group $RG
```

Wait ~30 seconds for startup.

### Step 3 — Point DR App at DR DB

```bash
az webapp config appsettings set \
  --name $DR_APP \
  --resource-group $RG \
  --settings \
    FSLAPP_PG_HOST="fslapp-pg-dr.postgres.database.azure.com" \
    FSLAPP_PG_DATABASE="fslapp" \
    FSLAPP_PG_USER="fslapp-nyaaa-dr"
```

The app restarts automatically on settings change. Wait ~30 seconds.

### Step 4 — Verify DR App is healthy

```bash
# HTTP smoke test
curl -sf https://fslapp-nyaaa-dr.azurewebsites.net/api/health | python3 -m json.tool

# PostgreSQL connectivity (via admin health endpoint — requires PIN)
curl -sf -X POST https://fslapp-nyaaa-dr.azurewebsites.net/api/admin/system/health \
  -H "Content-Type: application/json" \
  -d '{"pin":"<ADMIN_PIN>"}' | python3 -m json.tool
```

Confirm:
- HTTP 200 from `/api/health`
- `postgres.status == "healthy"` in system health response

If PostgreSQL shows unhealthy, re-check [Pre-Failover Prerequisites](#pre-failover-prerequisites) step 3.

### Step 5 — Redirect users to DR URL

DNS is not managed automatically. Route users to the DR URL by one of:
- Posting to the internal status channel with the DR URL
- Updating any DNS CNAME or Traffic Manager profile pointing at the app hostname
- Updating any hard-coded links in internal tools to `fslapp-nyaaa-dr.azurewebsites.net`

### Step 6 — Confirm and document

- Note actual recovery time
- Log the PITR restore point time from Step 4 response (`backup_recovery.azure.latest_time` if present) to quantify data lag
- Notify stakeholders

---

## Rollback to Primary

Once `fslapp-pg` is confirmed healthy:

### Step 1 — Verify primary DB is healthy

```bash
# Quick TCP check
nc -zv fslapp-pg.postgres.database.azure.com 5432
```

### Step 2 — Assess data divergence

While on DR, writes went to `fslapp-pg-dr`. If any data was written that must be preserved (e.g. new WOA reviews, user changes), export from DR DB before cutting back:

```bash
# Connect to DR DB and export diverged tables
pg_dump \
  --host fslapp-pg-dr.postgres.database.azure.com \
  --username fslapp-nyaaa-dr \
  --dbname fslapp \
  --schema core \
  --table core.woa_reviews \
  --table core.users \
  --table core.settings \
  --format plain \
  --file /tmp/dr_export_$(date +%Y%m%d_%H%M%S).sql
```

Import into primary before switching back.

### Step 3 — Redirect primary app back to primary DB

```bash
az webapp config appsettings set \
  --name fslapp-nyaaa \
  --resource-group $RG \
  --settings \
    FSLAPP_PG_HOST="fslapp-pg.postgres.database.azure.com" \
    FSLAPP_PG_USER="fslapp-nyaaa"
```

### Step 4 — Verify primary app is healthy

```bash
curl -sf https://fslapp-nyaaa.azurewebsites.net/api/health | python3 -m json.tool
```

### Step 5 — Stop or idle the DR App Service (optional, to save cost)

```bash
az webapp stop --name $DR_APP --resource-group $RG
```

### Step 6 — Schedule DR DB refresh

The DR DB data is now stale relative to primary. Schedule a refresh (see below) within 24 hours.

---

## DR DB Refresh Procedure

The DR DB is a static PITR clone — it does not replicate continuously. Refresh it periodically (recommended: weekly, or before a planned maintenance window).

**Time required:** ~15-30 minutes (Azure provisions the new server)  
**Downtime impact:** None on primary. DR unavailable during refresh (expected).

> **Important:** PITR cannot restore in-place. The procedure renames the old DR server, restores a new one, then deletes the old one. Re-run Entra grant setup after each refresh.

### Step 1 — Note restore target time

Pick the restore point (typically "now" for freshest data, or a specific ISO timestamp):

```bash
RESTORE_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Restoring to: $RESTORE_TIME"
```

### Step 2 — Rename the existing DR server (safety net before delete)

```bash
# Azure PG Flexible Server does not support rename via CLI — stop the server
# then delete it only after the new restore is confirmed healthy (Step 5).
# Document the old server name for reference:
OLD_DR="fslapp-pg-dr-old-$(date +%Y%m%d)"
echo "Will delete old DR after confirmation: fslapp-pg-dr"
```

### Step 3 — Delete the existing DR server

```bash
az postgres flexible-server delete \
  --name fslapp-pg-dr \
  --resource-group $RG \
  --yes
```

> The deletion may take 2-5 minutes.

### Step 4 — Restore a new PITR clone

```bash
az postgres flexible-server restore \
  --name fslapp-pg-dr \
  --resource-group $RG \
  --source-server fslapp-pg \
  --restore-time "$RESTORE_TIME" \
  --location eastus2
```

Monitor provisioning state:
```bash
watch -n 10 az postgres flexible-server show \
  --name fslapp-pg-dr \
  --resource-group $RG \
  --query "state" --output tsv
```

Wait for state: `Ready`

### Step 5 — Re-apply Entra grants (required after every restore)

PITR clones roles from the source but Entra bindings for managed identities may not carry over. Always re-run:

```bash
# Connect as Entra admin
psql "host=fslapp-pg-dr.postgres.database.azure.com \
      dbname=fslapp \
      user=nlaaroubi@nyaaa.com \
      sslmode=require"
```

Then run the SQL from [Pre-Failover Prerequisites step 3](#3-dr-app-identity-is-an-entra-user-on-the-dr-db-with-schema-grants) for both `fslapp-nyaaa-dr` and `salespulse-nyaaa-dr` (SalesPulse uses the same DB).

### Step 6 — Smoke test

```bash
# Point a test curl at the DR health endpoint via the DR app
curl -sf https://fslapp-nyaaa-dr.azurewebsites.net/api/admin/system/health \
  -H "Content-Type: application/json" \
  -d '{"pin":"<ADMIN_PIN>"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['services']['dr_postgres']['status'])"
```

Expected: `healthy`

---

## Cross-App Coordination

FSLAPP and SalesPulse share `fslapp-pg`. **If you fail over or refresh the DB, both apps are affected.**

| Scenario | FSLAPP action | SalesPulse action |
|---|---|---|
| `fslapp-pg` fails | Redirect `fslapp-nyaaa-dr` to `fslapp-pg-dr` | Redirect `salespulse-nyaaa-dr` to `fslapp-pg-dr` |
| `fslapp-nyaaa` fails only | Point DNS/users to `fslapp-nyaaa-dr` (DR DB optional) | No action needed |
| DB refresh | Verify `fslapp-nyaaa-dr` health after refresh | Verify `salespulse-nyaaa-dr` health after refresh |

See SalesPulse DR runbook: `SalesPulse/docs/dr/DR_RUNBOOK.md`

---

## Env Var Checklist for `fslapp-nyaaa-dr`

All env vars listed here must be set in **Azure Portal → fslapp-nyaaa-dr → Configuration → Application settings**.

| Variable | Required Value for DR | Notes |
|---|---|---|
| `FSLAPP_PG_HOST` | `fslapp-pg-dr.postgres.database.azure.com` | Points at DR DB |
| `FSLAPP_PG_DATABASE` | `fslapp` | Same DB name as primary |
| `FSLAPP_PG_USER` | `fslapp-nyaaa-dr` | DR app's own managed identity name |
| `FSLAPP_PG_SCHEMA` | `optimizer` | Same as primary |
| `FSLAPP_PG_DR_HOST` | `fslapp-pg-dr.postgres.database.azure.com` | Informational — health panel display |
| `DB_PRIMARY` | `postgres` | Informational only — does not switch backends |
| `SF_TOKEN_URL` | Same as primary | Copy from `fslapp-nyaaa` settings |
| `SF_CONSUMER_KEY` | Same as primary | Copy from `fslapp-nyaaa` settings |
| `SF_CONSUMER_SECRET` | Same as primary | Copy from `fslapp-nyaaa` settings |
| `SF_USERNAME` | Same as primary | Copy from `fslapp-nyaaa` settings |
| `SF_PASSWORD` | Same as primary | Copy from `fslapp-nyaaa` settings |
| `SF_SECURITY_TOKEN` | Same as primary | Copy from `fslapp-nyaaa` settings |
| `GOOGLE_MAPS_API_KEY` | Same as primary | Copy from `fslapp-nyaaa` settings |
| `OPENAI_API_KEY` | Same as primary | Copy from `fslapp-nyaaa` settings |
| `ANTHROPIC_API_KEY` | Same as primary | Copy from `fslapp-nyaaa` settings |
| `ADMIN_PIN` | Same as primary (or unique DR PIN) | Required for system health checks |
| `GITHUB_TOKEN` | Same as primary | Required for GitHub integration |
| `AGENTMAIL_API_KEY` | Same as primary | Required for email features |
| `AGENTMAIL_INBOX` | Same as primary | Required for email features |
| `AZURE_STORAGE_CONNECTION_STRING` | Same as primary | Required for blob backups |

> **Copy all env vars from primary in one command:**
> ```bash
> # Export primary settings (review before applying to DR)
> az webapp config appsettings list \
>   --name fslapp-nyaaa \
>   --resource-group rg-nlaaroubi-sbx-eus2-001 \
>   --output json > /tmp/fslapp_primary_settings.json
>
> # Then apply to DR, overriding the DB-specific vars:
> az webapp config appsettings set \
>   --name fslapp-nyaaa-dr \
>   --resource-group rg-nlaaroubi-sbx-eus2-001\
>   --settings @/tmp/fslapp_primary_settings.json
>
> # Override the DB host and user to point at DR:
> az webapp config appsettings set \
>   --name fslapp-nyaaa-dr \
>   --resource-group rg-nlaaroubi-sbx-eus2-001 \
>   --settings \
>     FSLAPP_PG_HOST="fslapp-pg-dr.postgres.database.azure.com" \
>     FSLAPP_PG_USER="fslapp-nyaaa-dr"
> ```

---

## Quick Reference

| Situation | First command |
|---|---|
| Check DR app status | `az webapp show --name fslapp-nyaaa-dr --resource-group rg-nlaaroubi-sbx-eus2-001 --query state -o tsv` |
| Start DR app | `az webapp start --name fslapp-nyaaa-dr --resource-group rg-nlaaroubi-sbx-eus2-001` |
| Failover DB (key step) | `az webapp config appsettings set --name fslapp-nyaaa-dr ... FSLAPP_PG_HOST=fslapp-pg-dr...` |
| Check DR DB reachable | Admin panel → System Health → DR PostgreSQL card |
| Refresh DR DB | Delete `fslapp-pg-dr`, then `az postgres flexible-server restore --source-server fslapp-pg` |
| Roll back to primary | Set `FSLAPP_PG_HOST=fslapp-pg.postgres.database.azure.com` on `fslapp-nyaaa` |
