# FSLAPP Postgres — Provisioning & Local Dev

**Status:** Files for review. **No Azure resources have been created yet.**

This directory contains everything needed to provision the shared FSLAPP
PostgreSQL Flexible Server and connect to it from both your Mac and the
`fslapp-nyaaa` App Service.

## What gets created

| Resource | Name | Region | SKU | Cost |
|---|---|---|---|---|
| Postgres Flexible Server | `fslapp-pg` | `canadacentral` | `Standard_B2s` (2 vCore, 4 GB) | $24.82/mo |
| Storage | 64 GB Premium SSD v2, 3000 IOPS, auto-grow | | | $5.76/mo |
| Backup | 7-day PITR, LRS | | | included |
| Database | `fslapp` (single shared DB) | | | included |
| Schemas | `optimizer`, `core`, `accounting`, `ops` (empty placeholders for future features) | | | |
| Firewall rule 1 | local-dev-mac-nlaaroubi → 74.77.8.242/32 | | | |
| Firewall rule 2 | AllowAllAzureServicesAndResourcesWithinAzureIps → 0.0.0.0 | | | |
| Auth | Microsoft Entra ID **only** — no admin password | | | |
| **Total** | | | | **~$31/mo** |

## What does NOT get created (deferred to later phases)

- **Redis** (Phase 2) — your decision: defer
- **Application Insights, alerts** — separate work item
- **Private Endpoint / VNet integration** — public + Entra auth is sufficient at this stage
- **High Availability / geo-redundant backup** — sandbox; flip on for prod later

---

## Files in this directory

| File | What it does |
|---|---|
| `main.bicep` | Declarative ARM template. Creates the server, configures it, opens firewall, creates the `fslapp` database. |
| `main.parameters.json` | Parameter values for the deployment (region, SKU, IP, etc.). |
| `init-schema.sql` | Post-deploy: creates schemas, all 8 optimizer tables, indexes, role grants, migration tracking. |
| `deploy.sh` | One-command wrapper: signs in, runs Bicep, enables managed identity, runs `init-schema.sql`, sets App Service env vars. **Idempotent.** |
| `README.md` | This file. |

---

## Pre-deployment checks (run these before approving)

```bash
# 1. You're logged in to the right subscription
az account show --query name -o tsv     # → "AAAWCNY Azure Sandbox"

# 2. Bicep linter passes (catches typos before sending to Azure)
az bicep build --file main.bicep --stdout > /dev/null && echo "OK"

# 3. Preview what will be created (no resources are touched)
./deploy.sh --whatif
```

The `--whatif` output should list ~7 resources to **Create**, 0 to **Modify**,
0 to **Delete**.

---

## Deployment runbook

```bash
cd /Users/abdennourlaaroubi/Library/CloudStorage/OneDrive-EnProIndustriesInc/AAA/Dev/FSL/FSL/apidev/FSLAPP/infra/postgres
./deploy.sh
```

**What happens, step by step:**

1. `az login` already done (you do this once per day)
2. Subscription set to `AAAWCNY Azure Sandbox`
3. Your AAD object ID auto-injected into the parameters file (no hand editing)
4. Your current public IP verified against `74.77.8.242` (script asks if mismatch)
5. **Bicep deployment** — creates server, configs, firewall, database (~3-5 min)
6. **Managed identity assignment** on `fslapp-nyaaa` App Service (10s)
7. **Postgres AAD admin** added for the App Service identity (5s)
8. **Schema initialization** — runs `init-schema.sql` via `psql` (10s, with Entra token auth)
9. **App Service config** — writes `FSLAPP_PG_HOST`, `FSLAPP_PG_DATABASE`, `OPT_DB_BACKEND=postgres` env vars

**Total wall-clock: 4-6 minutes.**

**Rollback:** `az group deployment delete` removes everything. The DuckDB
file at `~/.fslapp/optimizer.duckdb` is untouched.

---

## Connecting from this Mac (local dev)

```bash
# One-time setup (per shell session)
export PGPASSWORD=$(az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv)
export PGUSER=$(az ad signed-in-user show --query userPrincipalName -o tsv)

# Connect
psql "host=fslapp-pg.postgres.database.azure.com dbname=fslapp sslmode=require"
```

**Token lifetime:** Entra access tokens last 60 minutes. If you get a
`PAM authentication failed` error mid-session, just re-run the
`PGPASSWORD=…` line.

**Optional: a shell alias to make this one command:**
```bash
# Add to ~/.zshrc
alias fslapp-pg='PGPASSWORD=$(az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv) PGUSER=$(az ad signed-in-user show --query userPrincipalName -o tsv) psql "host=fslapp-pg.postgres.database.azure.com dbname=fslapp sslmode=require"'
```

**From Python (also works locally):**
```python
import os, psycopg
from azure.identity import DefaultAzureCredential

token = DefaultAzureCredential().get_token('https://ossrdbms-aad.database.windows.net/.default').token
with psycopg.connect(
    host='fslapp-pg.postgres.database.azure.com',
    dbname='fslapp',
    user=os.environ.get('PGUSER') or 'nlaaroubi@nyaaa.com',
    password=token,
    sslmode='require',
) as conn:
    print(conn.execute('SELECT current_user, version()').fetchone())
```

---

## What the App Service does at runtime

The backend's `optimizer_db.py` (replaced by `optimizer_db_pg.py` in Phase 1
implementation) uses `DefaultAzureCredential` which automatically picks up
the App Service's system-assigned managed identity. No connection strings
in env, no passwords, no rotation.

Connection pool config (in `backend/db.py`, written separately):
- Writer pool (blob_sync thread): `min_size=1, max_size=2, timeout=10`
- Reader pool (FastAPI requests): `min_size=2, max_size=10, timeout=5`
- Token refresh: hooked into psycopg's `connect_timeout` callback so each new
  connection grabs a fresh AAD token (auto-refreshes before the 60-min expiry)

---

## Cost evolution as more FSLAPP features migrate

The same B2s instance hosts the optimizer today. Add accounting / users / ops
schemas later — same DB, same connection pool. **You don't pay extra for
schemas.** When CPU usage on B2s gets sustained > 60%, one-click resize to:

| SKU | vCore | RAM | Monthly | When |
|---|---|---|---|---|
| **B2s** (current) | 2 | 4 GB | $24.82 | Phase 1 (optimizer only) |
| **B2ms** | 2 | 8 GB | $49.65 | When 2-3 features migrated |
| **D2ds_v5** | 2 | 8 GB | $96.36 | When >5 features + non-burstable workload |

Storage grows ~3 GB/yr at current optimizer rate. 64 GB lasts ~20 years.
Auto-grow handles bumps without intervention.

---

## Risks called out in the design doc that are now mitigated here

| Risk | Mitigation in this provisioning |
|---|---|
| B2s CPU exhaustion under backfill | `--whatif` previews; can swap SKU to B2ms in `main.parameters.json` and re-run before backfill |
| Connection storm at 4 uvicorn workers | `db.py` pool caps at 10 readers + 2 writers = 12 per worker × 4 = 48, well under server's ~85 connection cap |
| Silent DuckDB-dialect drift in new code | `init-schema.sql` enforces real PG types (TIMESTAMPTZ, vector); CI test against PG (separate work item) |
| App Service IP changes break firewall | `AllowAllAzureServicesAndResourcesWithinAzureIps` is wildcard; security via Entra-only auth, not IP |
| Local dev IP changes (Spectrum re-provisioning) | One CLI: `az postgres flexible-server firewall-rule update -g … -s fslapp-pg -n local-dev-mac-nlaaroubi --start-ip-address NEW --end-ip-address NEW` |
| Lost local Entra token mid-session | Tokens last 60 min; just re-run the `PGPASSWORD` env var line |

---

## When you're ready

1. Read `main.bicep` end-to-end (~150 lines, declarative — no surprises)
2. Read `init-schema.sql` end-to-end (~150 lines, idempotent CREATE IF NOT EXISTS)
3. Read `deploy.sh` end-to-end (~100 lines, the only script that runs commands)
4. Run `./deploy.sh --whatif` to preview
5. Tell me **"deploy"** → I run `./deploy.sh` (or you do)

Until you say "deploy", **nothing in Azure changes**.
