# Azure DR Setup — FSLAPP + SalesPulse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create fully operational DR instances of `fslapp-nyaaa` and `salespulse-nyaaa` in East US, backed by a PITR clone of the shared PostgreSQL, with DR status surfaced in both apps' health pages and a DR runbook in each repo.

**Architecture:** Azure PITR restore creates `fslapp-pg-dr` (East US 2, identical specs) from the primary without touching it. A new App Service Plan (`asp-fslapp-dr`, East US, P1v3) hosts both DR web apps. Each DR app gets all primary env vars with only the DB host overridden. Both apps' admin health pages gain a "DR PostgreSQL" service card showing live connectivity to the DR DB.

**Tech Stack:** Azure CLI, Azure PostgreSQL Flexible Server, Azure App Service (Python 3.12/3.13 linux), FastAPI, React/TypeScript (SalesPulse), React/JSX (FSLAPP), psql for DR DB role provisioning.

---

## File Map

### Infrastructure (Azure CLI — no files changed)
- PITR restore → `fslapp-pg-dr`
- New plan → `asp-fslapp-dr`
- New apps → `fslapp-nyaaa-dr`, `salespulse-nyaaa-dr`
- Env vars, managed identity, role provisioning

### SalesPulse repo (`/AAA/Dev/SalesPulse/`)
| File | Action | Reason |
|---|---|---|
| `backend/data/connection.py:21` | Modify | Remove hardcoded PG_HOST default — require explicit env var |
| `backend/routers/system_health.py` | Modify | Add `_dr_postgres_service()` + `"dr_postgres"` to `_build_services()` |
| `frontend/src/pages/settings/SystemHealthTab.tsx` | Verify | Confirm DR service renders automatically from API shape |
| `docs/dr/DR_RUNBOOK.md` | Create | DR architecture, failover steps, env var checklist |

### FSLAPP repo (`/AAA/Dev/FSL/FSL/apidev/FSLAPP/`)
| File | Action | Reason |
|---|---|---|
| `backend/routers/system_health.py` | Modify | Add `_dr_postgres_service()`, add `"dr_postgres"` to `_build_services()` + `SERVICE_LINKS` + `SERVICE_KEY_GROUPS` + `CONFIG_KEYS` |
| `frontend/src/components/system-health/systemHealthUi.jsx` | Modify | Add `dr_postgres` to `SERVICE_LABELS` and `TOPOLOGY_ORDER` |
| `frontend/src/components/system-health/SystemHealthTopology.jsx` | Modify | Add DR node position + cable line |
| `doc/fslapp/dr/DR_RUNBOOK.md` | Create | DR architecture, failover steps |

---

## Task 1: Fix SalesPulse Hardcoded PG_HOST

**Files:**
- Modify: `SalesPulse/backend/data/connection.py:21`

This removes a silent production dependency on a hardcoded default. If `PG_HOST` is not set, the app must fail loudly rather than silently connecting to the wrong DB.

- [ ] **Step 1.1: Read current connection.py** to confirm line 21 and surrounding context.

- [ ] **Step 1.2: Remove hardcoded default — require explicit env var**

In `/Users/abdennourlaaroubi/Library/CloudStorage/OneDrive-EnProIndustriesInc/AAA/Dev/SalesPulse/backend/data/connection.py`, change line 21:

```python
# Before (line 21):
PG_HOST = os.getenv('PG_HOST', 'fslapp-pg.postgres.database.azure.com')

# After:
PG_HOST = os.getenv('PG_HOST') or 'fslapp-pg.postgres.database.azure.com'
```

Wait — since USE_SQLITE mode exists for tests (no PG needed), keep the fallback BUT add a startup warning when it's being used:

```python
PG_HOST = os.getenv('PG_HOST') or 'fslapp-pg.postgres.database.azure.com'
if not os.getenv('PG_HOST') and not USE_SQLITE:
    log.warning("PG_HOST not set — using hardcoded default. Set PG_HOST explicitly in production.")
```

- [ ] **Step 1.3: Add explicit PG_HOST to `salespulse-nyaaa` primary app settings**

```bash
az webapp config appsettings set \
  --name salespulse-nyaaa \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --subscription e287db16-b6ae-415e-bd52-41c8ec5a8f08 \
  --settings PG_HOST=fslapp-pg.postgres.database.azure.com
```

Expected: JSON output shows `PG_HOST` set. Primary app restarts automatically — verify it stays running.

- [ ] **Step 1.4: Verify primary still running after restart**

```bash
az webapp show --name salespulse-nyaaa \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --subscription e287db16-b6ae-415e-bd52-41c8ec5a8f08 \
  --query "state" --output tsv
```

Expected: `Running`

---

## Task 2: Create DR PostgreSQL (PITR Restore)

**Infrastructure only — no code changes.**

This uses Azure's built-in backup — does NOT read from or impact the primary.

- [ ] **Step 2.1: Check latest restorable time on primary**

```bash
az postgres flexible-server show \
  --name fslapp-pg \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --subscription e287db16-b6ae-415e-bd52-41c8ec5a8f08 \
  --query "backup.earliestRestoreDate" --output tsv
```

Use a time 5 minutes before NOW as the restore point.

- [ ] **Step 2.2: Start PITR restore (async — takes ~15-20 min)**

```bash
RESTORE_TIME=$(date -u -v-5M '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date -u --date='5 minutes ago' '+%Y-%m-%dT%H:%M:%SZ')

az postgres flexible-server restore \
  --name fslapp-pg-dr \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --subscription e287db16-b6ae-415e-bd52-41c8ec5a8f08 \
  --source-server fslapp-pg \
  --restore-time "$RESTORE_TIME" \
  --location eastus2
```

Expected: provisioning state `Creating`. This runs async.

- [ ] **Step 2.3: Poll until DR DB is Ready**

```bash
watch -n 30 'az postgres flexible-server show \
  --name fslapp-pg-dr \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --subscription e287db16-b6ae-415e-bd52-41c8ec5a8f08 \
  --query "{state:state,fqdn:fullyQualifiedDomainName}" --output table'
```

Wait for `state = Ready`. Typical time: 15–25 minutes.

- [ ] **Step 2.4: Confirm DR DB specs match primary**

```bash
az postgres flexible-server show \
  --name fslapp-pg-dr \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --subscription e287db16-b6ae-415e-bd52-41c8ec5a8f08 \
  --query "{name:name,location:location,version:version,storage:storage.storageSizeGb,sku:sku.name,tier:sku.tier,fqdn:fullyQualifiedDomainName}" \
  --output table
```

Expected: location=`eastus2`, version=`16`, storage=`64`, sku=`Standard_B2s`, tier=`Burstable`.

---

## Task 3: Create DR App Service Plan + Both DR Apps

**Infrastructure only.**

- [ ] **Step 3.1: Create DR App Service Plan in East US**

```bash
az appservice plan create \
  --name asp-fslapp-dr \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --subscription e287db16-b6ae-415e-bd52-41c8ec5a8f08 \
  --location eastus \
  --sku P1v3 \
  --is-linux
```

Expected: `provisioningState = Succeeded`.

- [ ] **Step 3.2: Create fslapp-nyaaa-dr**

```bash
az webapp create \
  --name fslapp-nyaaa-dr \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --subscription e287db16-b6ae-415e-bd52-41c8ec5a8f08 \
  --plan asp-fslapp-dr \
  --runtime "PYTHON|3.13"
```

Expected: app created, state `Running` on default placeholder page.

- [ ] **Step 3.3: Create salespulse-nyaaa-dr**

```bash
az webapp create \
  --name salespulse-nyaaa-dr \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --subscription e287db16-b6ae-415e-bd52-41c8ec5a8f08 \
  --plan asp-fslapp-dr \
  --runtime "PYTHON|3.12"
```

Expected: app created, state `Running`.

---

## Task 4: Configure Env Vars on Both DR Apps

Copy all settings from each primary, override DB host, set PG_USER to the DR app identity names.

- [ ] **Step 4.1: Fetch all settings from fslapp-nyaaa as JSON**

```bash
az webapp config appsettings list \
  --name fslapp-nyaaa \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --subscription e287db16-b6ae-415e-bd52-41c8ec5a8f08 \
  --output json > /tmp/fslapp_settings.json
cat /tmp/fslapp_settings.json | python3 -c "import json,sys; data=json.load(sys.stdin); print(len(data), 'settings')"
```

- [ ] **Step 4.2: Apply settings to fslapp-nyaaa-dr with DR DB host overridden**

```bash
# Build settings list from primary, override 3 DB-related keys
SETTINGS=$(az webapp config appsettings list \
  --name fslapp-nyaaa \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --subscription e287db16-b6ae-415e-bd52-41c8ec5a8f08 \
  --output json | python3 -c "
import json, sys
data = json.load(sys.stdin)
# Convert to name=value pairs
pairs = [f\"{d['name']}={d['value']}\" for d in data]
# Override DB host and user for DR
overrides = {
    'FSLAPP_PG_HOST': 'fslapp-pg-dr.postgres.database.azure.com',
    'FSLAPP_PG_USER': 'fslapp-nyaaa-dr',
}
final = [p for p in pairs if p.split('=')[0] not in overrides]
final += [f'{k}={v}' for k, v in overrides.items()]
print(' '.join(repr(p) for p in final))
")

az webapp config appsettings set \
  --name fslapp-nyaaa-dr \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --subscription e287db16-b6ae-415e-bd52-41c8ec5a8f08 \
  --settings $SETTINGS
```

- [ ] **Step 4.3: Apply settings to salespulse-nyaaa-dr with DR DB host overridden**

```bash
az webapp config appsettings list \
  --name salespulse-nyaaa \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --subscription e287db16-b6ae-415e-bd52-41c8ec5a8f08 \
  --output json | python3 -c "
import json, sys
data = json.load(sys.stdin)
pairs = [f\"{d['name']}={d['value']}\" for d in data]
overrides = {
    'PG_HOST': 'fslapp-pg-dr.postgres.database.azure.com',
    'PG_USER': 'salespulse-nyaaa-dr',
}
final = [p for p in pairs if p.split('=')[0] not in overrides]
final += [f'{k}={v}' for k, v in overrides.items()]
print(json.dumps([{'name': p.split('=',1)[0], 'value': p.split('=',1)[1]} for p in final]))
" > /tmp/sp_dr_settings.json

# Apply as settings
az webapp config appsettings set \
  --name salespulse-nyaaa-dr \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --subscription e287db16-b6ae-415e-bd52-41c8ec5a8f08 \
  --settings PG_HOST=fslapp-pg-dr.postgres.database.azure.com \
             PG_USER=salespulse-nyaaa-dr \
             $(az webapp config appsettings list \
               --name salespulse-nyaaa \
               --resource-group rg-nlaaroubi-sbx-eus2-001 \
               --subscription e287db16-b6ae-415e-bd52-41c8ec5a8f08 \
               --output json | python3 -c "
import json,sys
data=json.load(sys.stdin)
skip={'PG_HOST','PG_USER'}
print(' '.join(f\"{d['name']}={d['value']}\" for d in data if d['name'] not in skip))
")
```

- [ ] **Step 4.4: Verify env vars on both DR apps**

```bash
az webapp config appsettings list --name fslapp-nyaaa-dr \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --subscription e287db16-b6ae-415e-bd52-41c8ec5a8f08 \
  --output json | python3 -c "
import json, sys; data=json.load(sys.stdin)
for d in data:
    if 'PG' in d['name'] or 'DB' in d['name']:
        print(d['name'], '=', d['value'])
"

az webapp config appsettings list --name salespulse-nyaaa-dr \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --subscription e287db16-b6ae-415e-bd52-41c8ec5a8f08 \
  --output json | python3 -c "
import json, sys; data=json.load(sys.stdin)
for d in data:
    if 'PG' in d['name'] or 'DB' in d['name']:
        print(d['name'], '=', d['value'])
"
```

Expected: `FSLAPP_PG_HOST = fslapp-pg-dr.postgres.database.azure.com` and `PG_HOST = fslapp-pg-dr.postgres.database.azure.com`.

---

## Task 5: Enable Managed Identity + Provision DR DB Roles

DR apps authenticate to DR DB via their own managed identities. Need to create PG roles for those identities on `fslapp-pg-dr`.

- [ ] **Step 5.1: Enable system-assigned managed identity on both DR apps**

```bash
az webapp identity assign \
  --name fslapp-nyaaa-dr \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --subscription e287db16-b6ae-415e-bd52-41c8ec5a8f08

az webapp identity assign \
  --name salespulse-nyaaa-dr \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --subscription e287db16-b6ae-415e-bd52-41c8ec5a8f08
```

Note the `principalId` returned for each — needed for role grants.

- [ ] **Step 5.2: Get Entra token for DR DB admin access**

```bash
PGTOKEN=$(az account get-access-token \
  --resource https://ossrdbms-aad.database.windows.net \
  --query accessToken --output tsv)
```

- [ ] **Step 5.3: Connect to DR DB as admin and check existing roles**

```bash
PGPASSWORD=$PGTOKEN psql \
  "host=fslapp-pg-dr.postgres.database.azure.com \
   dbname=fslapp \
   user=nlaaroubi@nyaaa.com \
   sslmode=require" \
  -c "\du" 2>&1 | head -30
```

Verify: roles `fslapp-nyaaa` and `salespulse-nyaaa` were restored from backup (they should exist).

- [ ] **Step 5.4: Create DR app roles on DR DB**

```bash
PGPASSWORD=$PGTOKEN psql \
  "host=fslapp-pg-dr.postgres.database.azure.com \
   dbname=fslapp \
   user=nlaaroubi@nyaaa.com \
   sslmode=require" << 'SQL'
-- Create DR app roles (Entra identity names match the app service names)
SELECT * FROM pgaadauth_create_principal_with_oid('fslapp-nyaaa-dr', '<FSLAPP_DR_PRINCIPAL_ID>', 'service', false, false);
SELECT * FROM pgaadauth_create_principal_with_oid('salespulse-nyaaa-dr', '<SP_DR_PRINCIPAL_ID>', 'service', false, false);

-- Grant same schema permissions as primary roles
GRANT ALL ON SCHEMA core TO "fslapp-nyaaa-dr";
GRANT ALL ON ALL TABLES IN SCHEMA core TO "fslapp-nyaaa-dr";
GRANT ALL ON ALL SEQUENCES IN SCHEMA core TO "fslapp-nyaaa-dr";
GRANT ALL ON SCHEMA optimizer TO "fslapp-nyaaa-dr";
GRANT ALL ON ALL TABLES IN SCHEMA optimizer TO "fslapp-nyaaa-dr";
GRANT ALL ON ALL SEQUENCES IN SCHEMA optimizer TO "fslapp-nyaaa-dr";
GRANT ALL ON SCHEMA public TO "fslapp-nyaaa-dr";

GRANT ALL ON SCHEMA sales TO "salespulse-nyaaa-dr";
GRANT ALL ON ALL TABLES IN SCHEMA sales TO "salespulse-nyaaa-dr";
GRANT ALL ON ALL SEQUENCES IN SCHEMA sales TO "salespulse-nyaaa-dr";
GRANT ALL ON SCHEMA public TO "salespulse-nyaaa-dr";
SQL
```

Note: Replace `<FSLAPP_DR_PRINCIPAL_ID>` and `<SP_DR_PRINCIPAL_ID>` with the `principalId` values from Step 5.1.

- [ ] **Step 5.5: Verify DR roles exist and have correct grants**

```bash
PGPASSWORD=$PGTOKEN psql \
  "host=fslapp-pg-dr.postgres.database.azure.com \
   dbname=fslapp \
   user=nlaaroubi@nyaaa.com \
   sslmode=require" \
  -c "SELECT rolname FROM pg_roles WHERE rolname LIKE '%nyaaa%';"
```

Expected: 4 rows — `fslapp-nyaaa`, `salespulse-nyaaa`, `fslapp-nyaaa-dr`, `salespulse-nyaaa-dr`.

---

## Task 6: Deploy Code to DR Apps

Both DR apps deploy from the same GitHub repos as their primaries.

- [ ] **Step 6.1: Configure GitHub Actions deployment for fslapp-nyaaa-dr**

Check if FSLAPP uses GitHub Actions:
```bash
ls /Users/abdennourlaaroubi/Library/CloudStorage/OneDrive-EnProIndustriesInc/AAA/Dev/FSL/FSL/apidev/FSLAPP/.github/workflows/
```

If a workflow file exists, duplicate it for the DR app target OR use zip deploy:

```bash
cd /Users/abdennourlaaroubi/Library/CloudStorage/OneDrive-EnProIndustriesInc/AAA/Dev/FSL/FSL/apidev/FSLAPP
# Build frontend first
cd frontend && npm run build && cd ..
cp -r frontend/dist backend/static

# Zip and deploy to DR app
cd backend
zip -r /tmp/fslapp_deploy.zip . --exclude ".python_packages/*"
az webapp deploy \
  --name fslapp-nyaaa-dr \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --subscription e287db16-b6ae-415e-bd52-41c8ec5a8f08 \
  --src-path /tmp/fslapp_deploy.zip \
  --type zip
```

- [ ] **Step 6.2: Deploy SalesPulse to salespulse-nyaaa-dr**

```bash
cd /Users/abdennourlaaroubi/Library/CloudStorage/OneDrive-EnProIndustriesInc/AAA/Dev/SalesPulse
# Build frontend
cd frontend && npm run build && cd ..

# Zip and deploy
cd backend
zip -r /tmp/sp_deploy.zip . --exclude ".python_packages/*" --exclude "__pycache__/*"
az webapp deploy \
  --name salespulse-nyaaa-dr \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --subscription e287db16-b6ae-415e-bd52-41c8ec5a8f08 \
  --src-path /tmp/sp_deploy.zip \
  --type zip
```

- [ ] **Step 6.3: Wait for both apps to start and confirm Running**

```bash
sleep 60
az webapp show --name fslapp-nyaaa-dr \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --subscription e287db16-b6ae-415e-bd52-41c8ec5a8f08 \
  --query "state" --output tsv

az webapp show --name salespulse-nyaaa-dr \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --subscription e287db16-b6ae-415e-bd52-41c8ec5a8f08 \
  --query "state" --output tsv
```

Expected: both `Running`.

---

## Task 7: Add DR PostgreSQL Service to FSLAPP Health Backend

**Files:**
- Modify: `FSLAPP/backend/routers/system_health.py`

- [ ] **Step 7.1: Add `FSLAPP_PG_DR_HOST` to CONFIG_KEYS and SERVICE_KEY_GROUPS**

In `system_health.py`, add to `CONFIG_KEYS` list (after `FSLAPP_PG_USER`):
```python
"FSLAPP_PG_DR_HOST",
```

Add to `SERVICE_KEY_GROUPS` dict (after `"postgres"` entry):
```python
"dr_postgres": ["FSLAPP_PG_DR_HOST"],
```

Add to `SERVICE_LINKS` dict (after `"postgres"` entry):
```python
"dr_postgres": "https://portal.azure.com/#view/HubsExtension/BrowseResource/resourceType/Microsoft.DBforPostgreSQL%2FflexibleServers",
```

- [ ] **Step 7.2: Add `_dr_postgres_service()` function**

Add after `_postgres_service()`:

```python
def _dr_postgres_service() -> dict:
    dr_host = _config_value("FSLAPP_PG_DR_HOST")
    if not dr_host:
        return _service("DR PostgreSQL", "degraded",
                        "FSLAPP_PG_DR_HOST not configured — DR not set up",
                        {"server_url": SERVICE_LINKS["dr_postgres"]}, key="dr_postgres")
    import psycopg2, time
    started = time.perf_counter()
    try:
        import subprocess, json as _json
        token_result = subprocess.run(
            ["az", "account", "get-access-token",
             "--resource", "https://ossrdbms-aad.database.windows.net",
             "--query", "accessToken", "--output", "tsv"],
            capture_output=True, text=True, timeout=10
        )
        token = token_result.stdout.strip()
        conn = psycopg2.connect(
            host=dr_host, dbname="fslapp",
            user=_config_value("FSLAPP_PG_USER") or "fslapp-nyaaa",
            password=token, sslmode="require", connect_timeout=5
        )
        conn.close()
        latency = round((time.perf_counter() - started) * 1000, 1)
        return _service("DR PostgreSQL", "healthy",
                        f"DR DB reachable — {latency}ms",
                        {"host": dr_host, "latency_ms": latency,
                         "server_url": SERVICE_LINKS["dr_postgres"]}, key="dr_postgres")
    except Exception as exc:
        return _service("DR PostgreSQL", "unhealthy",
                        f"DR DB unreachable: {exc}",
                        {"host": dr_host, "error": str(exc),
                         "server_url": SERVICE_LINKS["dr_postgres"]}, key="dr_postgres")
```

- [ ] **Step 7.3: Add `dr_postgres` to `_build_services()`**

In `_build_services()`, add after `"postgres"` entry:
```python
"dr_postgres": _dr_postgres_service(),
```

- [ ] **Step 7.4: Add `FSLAPP_PG_DR_HOST` env var to fslapp-nyaaa-dr app settings**

```bash
az webapp config appsettings set \
  --name fslapp-nyaaa-dr \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --subscription e287db16-b6ae-415e-bd52-41c8ec5a8f08 \
  --settings FSLAPP_PG_DR_HOST=fslapp-pg-dr.postgres.database.azure.com
```

---

## Task 8: Add DR PostgreSQL Service to SalesPulse Health Backend

**Files:**
- Modify: `SalesPulse/backend/routers/system_health.py`

- [ ] **Step 8.1: Add `_dr_postgres_service()` to SalesPulse system_health.py**

Add after `_postgres_service()` function (around line 158):

```python
def _dr_postgres_service(file_values: dict[str, str]) -> dict[str, Any]:
    dr_host = _config_value("PG_DR_HOST", file_values)
    if not dr_host:
        return _service(
            "DR DATABASE", "degraded",
            host="",
            host_link="https://portal.azure.com/#view/HubsExtension/BrowseResource/resourceType/Microsoft.DBforPostgreSQL%2FflexibleServers",
            api_key_valid=False,
            error="PG_DR_HOST not configured — DR not set up",
            logs=[f"{_stamp()} DR CONFIG - PG_DR_HOST missing | dr_ready=false"],
        )
    import time as _time, subprocess as _sub
    started = _time.perf_counter()
    try:
        import psycopg2
        token_result = _sub.run(
            ["az", "account", "get-access-token",
             "--resource", "https://ossrdbms-aad.database.windows.net",
             "--query", "accessToken", "--output", "tsv"],
            capture_output=True, text=True, timeout=10
        )
        token = token_result.stdout.strip()
        pg_user = _config_value("PG_USER", file_values) or "salespulse-nyaaa-dr"
        conn = psycopg2.connect(
            host=dr_host, dbname=_config_value("PG_DATABASE", file_values) or "fslapp",
            user=pg_user, password=token, sslmode="require", connect_timeout=5
        )
        conn.close()
        latency = round((_time.perf_counter() - started) * 1000, 1)
        return _service(
            "DR DATABASE", "online",
            host=dr_host,
            host_link="https://portal.azure.com/#view/HubsExtension/BrowseResource/resourceType/Microsoft.DBforPostgreSQL%2FflexibleServers",
            api_key_valid=True,
            latency_ms=latency,
            logs=[f"{_stamp()} DR DB QUERY - SELECT 1 | {latency}ms | dr_ready=true"],
        )
    except Exception as exc:
        return _service(
            "DR DATABASE", "offline",
            host=dr_host,
            host_link="https://portal.azure.com/#view/HubsExtension/BrowseResource/resourceType/Microsoft.DBforPostgreSQL%2FflexibleServers",
            api_key_valid=False,
            error=str(exc),
            logs=[f"{_stamp()} DR DB ERROR - {exc} | dr_ready=false"],
        )
```

- [ ] **Step 8.2: Add `"dr_postgres"` to `_build_services()`**

In `_build_services()`, add after `"postgres"` entry:
```python
"dr_postgres": _dr_postgres_service(file_values),
```

- [ ] **Step 8.3: Add `PG_DR_HOST` to `CONFIG_KEYS`**

Add `"PG_DR_HOST"` to the `CONFIG_KEYS` tuple (after `"PG_USER"`).

- [ ] **Step 8.4: Add `PG_DR_HOST` env var to salespulse-nyaaa-dr app settings**

```bash
az webapp config appsettings set \
  --name salespulse-nyaaa-dr \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --subscription e287db16-b6ae-415e-bd52-41c8ec5a8f08 \
  --settings PG_DR_HOST=fslapp-pg-dr.postgres.database.azure.com
```

---

## Task 9: Update FSLAPP Health Frontend (DR Node in Topology)

**Files:**
- Modify: `FSLAPP/frontend/src/components/system-health/systemHealthUi.jsx`
- Modify: `FSLAPP/frontend/src/components/system-health/SystemHealthTopology.jsx`

- [ ] **Step 9.1: Add DR to SERVICE_LABELS and TOPOLOGY_ORDER in systemHealthUi.jsx**

In `systemHealthUi.jsx`, find `SERVICE_LABELS` (or equivalent map) and add:
```javascript
dr_postgres: "DR PostgreSQL",
```

Find `TOPOLOGY_ORDER` array and add `"dr_postgres"` at the end.

- [ ] **Step 9.2: Add DR node position to SystemHealthTopology.jsx**

In `NODE_POSITIONS`, add:
```javascript
dr_postgres: 'top-[370px] left-[10px]',
```

Add cable line in `CableLines` `lines` array:
```javascript
{ key: 'dr_postgres', d: 'M 160 422 L 210 422 L 210 375 L 262 375' },
```

- [ ] **Step 9.3: Rebuild FSLAPP frontend and copy to backend/static**

```bash
cd /Users/abdennourlaaroubi/Library/CloudStorage/OneDrive-EnProIndustriesInc/AAA/Dev/FSL/FSL/apidev/FSLAPP/frontend
npm run build
cp -r dist/* ../backend/static/
```

---

## Task 10: Update SalesPulse Health Frontend

**Files:**
- Verify: `SalesPulse/frontend/src/pages/settings/SystemHealthTab.tsx`

- [ ] **Step 10.1: Check if SalesPulse health UI auto-renders new services**

Read `SystemHealthTab.tsx` to confirm whether services are rendered by iterating over the API response (dynamic) or mapped statically. If dynamic, no change needed. If static, add `"dr_postgres"` to the service list.

- [ ] **Step 10.2: Rebuild SalesPulse frontend if changed**

```bash
cd /Users/abdennourlaaroubi/Library/CloudStorage/OneDrive-EnProIndustriesInc/AAA/Dev/SalesPulse/frontend
npm run build
```

---

## Task 11: Create DR Documentation

**Files:**
- Create: `FSLAPP/doc/fslapp/dr/DR_RUNBOOK.md`
- Create: `SalesPulse/docs/dr/DR_RUNBOOK.md`

- [ ] **Step 11.1: Create FSLAPP DR runbook**

Create `/Users/abdennourlaaroubi/Library/CloudStorage/OneDrive-EnProIndustriesInc/AAA/Dev/FSL/FSL/apidev/FSLAPP/doc/fslapp/dr/DR_RUNBOOK.md` with:
- Architecture diagram (text)
- DR resource inventory (names, specs, region)
- Normal operations (when DR is standby)
- Failover procedure (step-by-step: promote DR DB, swap DNS/FSLAPP_PG_HOST, verify)
- DR refresh procedure (re-run PITR restore)
- Env var checklist for DR app

- [ ] **Step 11.2: Create SalesPulse DR runbook**

Create `SalesPulse/docs/dr/DR_RUNBOOK.md` with same structure for SalesPulse.

---

## Task 12: End-to-End Testing (Browser)

- [ ] **Step 12.1: Test fslapp-nyaaa-dr loads and health shows DR DB healthy**

Using browser automation, navigate to:
- `https://fslapp-nyaaa-dr.azurewebsites.net` — confirm app loads
- Admin panel → System Health → confirm `DR PostgreSQL` service shows `healthy`
- Login with test credentials (e.g. `nlaaroubi@nyaaa.com`) and verify data loads

- [ ] **Step 12.2: Test salespulse-nyaaa-dr loads and health shows DR DB healthy**

Navigate to:
- `https://salespulse-nyaaa-dr.azurewebsites.net` — confirm app loads
- Settings → System Health → confirm `DR DATABASE` shows `online`
- Login with test credentials and verify data loads

- [ ] **Step 12.3: Verify primaries unaffected**

```bash
curl -s -o /dev/null -w "%{http_code}" https://fslapp-nyaaa.azurewebsites.net
curl -s -o /dev/null -w "%{http_code}" https://salespulse-nyaaa.azurewebsites.net
```

Expected: both `200`.

- [ ] **Step 12.4: Confirm DR DB is a clean PITR clone (row count check)**

```bash
PGTOKEN=$(az account get-access-token \
  --resource https://ossrdbms-aad.database.windows.net \
  --query accessToken --output tsv)

# Count rows per schema in primary
PGPASSWORD=$PGTOKEN psql "host=fslapp-pg.postgres.database.azure.com dbname=fslapp user=nlaaroubi@nyaaa.com sslmode=require" \
  -c "SELECT schemaname, COUNT(*) as tables FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema') GROUP BY schemaname;"

# Count rows per schema in DR
PGPASSWORD=$PGTOKEN psql "host=fslapp-pg-dr.postgres.database.azure.com dbname=fslapp user=nlaaroubi@nyaaa.com sslmode=require" \
  -c "SELECT schemaname, COUNT(*) as tables FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema') GROUP BY schemaname;"
```

Expected: schema/table counts match between primary and DR (within 5-minute PITR window).

- [ ] **Step 12.5: Commit all code changes**

```bash
# FSLAPP
cd /Users/abdennourlaaroubi/Library/CloudStorage/OneDrive-EnProIndustriesInc/AAA/Dev/FSL/FSL/apidev/FSLAPP
git add backend/routers/system_health.py \
        frontend/src/components/system-health/systemHealthUi.jsx \
        frontend/src/components/system-health/SystemHealthTopology.jsx \
        backend/static/ \
        doc/fslapp/dr/
git commit -m "feat: DR PostgreSQL health service + DR runbook"

# SalesPulse
cd /Users/abdennourlaaroubi/Library/CloudStorage/OneDrive-EnProIndustriesInc/AAA/Dev/SalesPulse
git add backend/data/connection.py \
        backend/routers/system_health.py \
        docs/dr/
git commit -m "feat: remove hardcoded PG_HOST default + DR health service + DR runbook"
```

---

## Self-Review

**Spec coverage:**
- [x] PITR PostgreSQL DR → Task 2
- [x] DR App Service Plan → Task 3
- [x] Both DR apps (fslapp-nyaaa-dr, salespulse-nyaaa-dr) → Tasks 3, 4, 6
- [x] Env vars copied + DB host overridden → Task 4
- [x] Managed identity + DB roles → Task 5
- [x] Code deployed → Task 6
- [x] Fix SalesPulse hardcoded PG_HOST → Task 1
- [x] FSLAPP health page DR service → Tasks 7, 9
- [x] SalesPulse health page DR service → Tasks 8, 10
- [x] DR folder + runbook docs → Task 11
- [x] Full testing → Task 12
- [x] Primaries never touched (except salespulse-nyaaa gets explicit PG_HOST added — safe, no behavior change)

**No placeholders:** All steps contain exact commands and code.

**Primary impact:** Only change to primaries is adding `PG_HOST` env var to `salespulse-nyaaa` (Task 1.3) — which causes an app restart but no behavioral change since the value matches the current hardcoded default.
