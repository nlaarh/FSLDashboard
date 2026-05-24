# FSLPulse — Infrastructure Admin Guide

**Application:** FSLPulse (FSL Operations Dashboard)  
**Superadmin:** nlaaroubi@nyaaa.com  
**Last Updated:** 2026-05-24  
**RTO Target:** 15 minutes (manual DR procedure)  
**RPO Target:** ~5 minutes (Azure PITR granularity)

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Resource Inventory](#2-resource-inventory)
3. [Azure Portal Quick Links](#3-azure-portal-quick-links)
4. [Application Monitoring](#4-application-monitoring)
5. [Routine Maintenance](#5-routine-maintenance)
6. [Deployment](#6-deployment)
7. [DR Failover Procedure](#7-dr-failover-procedure)
8. [DR Database Refresh](#8-dr-database-refresh)
9. [Troubleshooting](#9-troubleshooting)
10. [Emergency Contacts & Escalation](#10-emergency-contacts--escalation)

---

## 1. Architecture Overview

### System Diagram

```mermaid
graph TD
    DEV["Developer Workstation"] -->|git push to main| GH["GitHub\nnlaarh/FSLDashboard"]
    GH -->|GitHub Actions CI/CD\n~4 min build + deploy| PRIMARY_APP

    subgraph PRIMARY ["PRIMARY — Canada Central"]
        PRIMARY_APP["fslapp-nyaaa\nApp Service P1v3\nPython 3.13\nfslapp-nyaaa.azurewebsites.net"]
    end

    subgraph DR_REGION ["DR — West US 2"]
        DR_APP["fslapp-nyaaa-dr\nApp Service P1v3\nPython 3.13\nfslapp-nyaaa-dr.azurewebsites.net\n(idle until failover)"]
    end

    subgraph DB_REGION ["Database — East US 2"]
        PRIMARY_DB[("fslapp-pg\nPostgreSQL 16\nBurstable B2s · 64 GiB\nSchemas: core · optimizer\nco-tenant: sales")]
        DR_DB[("fslapp-pg-dr\nPostgreSQL 16 · 64 GiB\nPITR clone — refreshed periodically\nSchemas: core · optimizer · sales")]
    end

    subgraph SAAS ["External Services"]
        SF["Salesforce\naaawcny.lightning.force.com\nOAuth2 managed identity"]
        GMAPS["Google Maps API"]
        OPENAI["OpenAI / Anthropic / Google AI"]
        GITHUB["GitHub API\nnlaarh/FSLDashboard"]
    end

    subgraph COTENANT ["Co-Tenant Application"]
        SALESPULSE["SalesPulse App\nShares fslapp-pg\n(schema: sales)"]
    end

    PRIMARY_APP -->|FSLAPP_PG_HOST\nEntra managed identity| PRIMARY_DB
    DR_APP -->|FSLAPP_PG_HOST (DR env)\nEntra managed identity| DR_DB
    PRIMARY_DB -.->|PITR restore\nperiodic refresh| DR_DB
    SALESPULSE -->|schema: sales| PRIMARY_DB

    PRIMARY_APP --> SF
    PRIMARY_APP --> GMAPS
    PRIMARY_APP --> OPENAI
    PRIMARY_APP --> GITHUB

    style PRIMARY fill:#1e3a5f,color:#ffffff,stroke:#3b82f6
    style DR_REGION fill:#3b1f1f,color:#ffffff,stroke:#ef4444
    style DB_REGION fill:#1a3a2a,color:#ffffff,stroke:#22c55e
    style SAAS fill:#2a1a3a,color:#ffffff,stroke:#a855f7
    style COTENANT fill:#2a2a1a,color:#ffffff,stroke:#f59e0b
```

### Key Architectural Facts

- **No continuous DB replication.** `fslapp-pg-dr` is a PITR clone, not a streaming replica. It must be manually refreshed. Data lag equals time since last refresh (see [Section 8](#8-dr-database-refresh)).
- **Auth uses Azure Entra managed identities.** Zero passwords in database connection strings. Each app's system-assigned identity is a PostgreSQL Entra user with schema grants.
- **Shared DB — dual-app impact.** `fslapp-pg` is shared between FSLPulse (`core`, `optimizer`, `accounting`, `ops` schemas) and SalesPulse (`sales` schema). Any DB-level failover or maintenance affects both apps simultaneously.
- **DR app is idle by default.** `fslapp-nyaaa-dr` is not proxied by Traffic Manager and receives no user traffic in normal operations. It may be stopped to reduce cost.
- **Startup command:** `gunicorn main:app --workers 2 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --timeout 120`

---

## 2. Resource Inventory

| Resource | Type | Region | Tier | URL / Hostname | Purpose |
|---|---|---|---|---|---|
| `fslapp-nyaaa` | App Service | Canada Central | P1v3 PremiumV3 | https://fslapp-nyaaa.azurewebsites.net | Primary application |
| `fslapp-nyaaa-dr` | App Service | West US 2 | P1v3 PremiumV3 | https://fslapp-nyaaa-dr.azurewebsites.net | DR standby application |
| `AABC` | App Service Plan | Canada Central | P1v3 PremiumV3 | — | Primary app hosting plan |
| `asp-fslapp-dr` | App Service Plan | West US 2 | P1v3 PremiumV3 | — | DR app hosting plan |
| `fslapp-pg` | PostgreSQL Flexible Server | East US 2 | PG16, Burstable B2s, 64 GiB | fslapp-pg.postgres.database.azure.com | Primary database |
| `fslapp-pg-dr` | PostgreSQL Flexible Server | East US 2 | PG16, Burstable B2s, 64 GiB | fslapp-pg-dr.postgres.database.azure.com | DR database (PITR clone) |
| `rg-nlaaroubi-sbx-eus2-001` | Resource Group | East US 2 | — | Azure Portal | All resources container |

**Subscription:** `e287db16-b6ae-415e-bd52-41c8ec5a8f08`  
**Tenant:** `@nyaaa.com`  
**GitHub Repo:** https://github.com/nlaarh/FSLDashboard  

### Environment Variables Reference

| Variable | Set On | Purpose |
|---|---|---|
| `FSLAPP_PG_HOST` | Primary + DR | PostgreSQL server hostname |
| `FSLAPP_PG_DR_HOST` | Primary + DR | DR PostgreSQL hostname (health panel display) |
| `FSLAPP_PG_DATABASE` | Primary + DR | Database name (`fslapp`) |
| `FSLAPP_PG_USER` | Primary + DR | App's managed identity name for Entra PG auth |
| `FSLAPP_PG_AUTH` | Primary + DR | Auth mode (`entra`) |
| `SF_TOKEN_URL` | Primary + DR | Salesforce OAuth2 token endpoint URL |
| `SF_CONSUMER_KEY` | Primary + DR | Salesforce connected app consumer key |
| `SF_CONSUMER_SECRET` | Primary + DR | Salesforce connected app consumer secret |
| `SF_USERNAME` | Primary + DR | Salesforce API username (`apiintegration@nyaaa.com`) |
| `SF_PASSWORD` | Primary + DR | Salesforce API user password |
| `SF_SECURITY_TOKEN` | Primary + DR | Salesforce API security token |
| `ADMIN_PIN` | Primary + DR | 6-digit PIN for the `/admin` panel |
| `AUTH_SECRET` | Primary + DR | HMAC secret for session cookie signing |
| `GOOGLE_MAPS_API_KEY` | Primary + DR | Google Maps JavaScript API key |
| `OPENAI_API_KEY` | Primary + DR | OpenAI API key |
| `ANTHROPIC_API_KEY` | Primary + DR | Anthropic Claude API key |
| `GITHUB_TOKEN` | Primary + DR | GitHub PAT (repo scope) |
| `AZ_OPT_STORAGE_ACCOUNT` | Primary + DR | Azure Blob storage account for optimizer files |
| `AZ_OPT_STORAGE_KEY` | Primary + DR | Azure Blob storage account key |
| `AZ_OPT_CONNECTION_STRING` | Primary + DR | Azure Blob full connection string |
| `OPT_DB_BACKEND` | Primary + DR | Optimizer DB backend (`duckdb`) |

---

## 3. Azure Portal Quick Links

> Bookmark this section. All links open directly to the relevant resource blade — no searching required.

### Primary App Service

| Action | Direct Link |
|---|---|
| Overview / Restart | https://portal.azure.com/#@nyaaa.com/resource/subscriptions/e287db16-b6ae-415e-bd52-41c8ec5a8f08/resourceGroups/rg-nlaaroubi-sbx-eus2-001/providers/Microsoft.Web/sites/fslapp-nyaaa/appServices |
| Environment Variables | https://portal.azure.com/#@nyaaa.com/resource/subscriptions/e287db16-b6ae-415e-bd52-41c8ec5a8f08/resourceGroups/rg-nlaaroubi-sbx-eus2-001/providers/Microsoft.Web/sites/fslapp-nyaaa/environmentVariablesAppSettings |

### DR App Service

| Action | Direct Link |
|---|---|
| Overview / Restart | https://portal.azure.com/#@nyaaa.com/resource/subscriptions/e287db16-b6ae-415e-bd52-41c8ec5a8f08/resourceGroups/rg-nlaaroubi-sbx-eus2-001/providers/Microsoft.Web/sites/fslapp-nyaaa-dr/appServices |
| Environment Variables | https://portal.azure.com/#@nyaaa.com/resource/subscriptions/e287db16-b6ae-415e-bd52-41c8ec5a8f08/resourceGroups/rg-nlaaroubi-sbx-eus2-001/providers/Microsoft.Web/sites/fslapp-nyaaa-dr/environmentVariablesAppSettings |

### Databases

| Resource | Direct Link |
|---|---|
| Primary PostgreSQL (`fslapp-pg`) | https://portal.azure.com/#@nyaaa.com/resource/subscriptions/e287db16-b6ae-415e-bd52-41c8ec5a8f08/resourceGroups/rg-nlaaroubi-sbx-eus2-001/providers/Microsoft.DBforPostgreSQL/flexibleServers/fslapp-pg/overview |
| DR PostgreSQL (`fslapp-pg-dr`) | https://portal.azure.com/#@nyaaa.com/resource/subscriptions/e287db16-b6ae-415e-bd52-41c8ec5a8f08/resourceGroups/rg-nlaaroubi-sbx-eus2-001/providers/Microsoft.DBforPostgreSQL/flexibleServers/fslapp-pg-dr/overview |

### Resource Group

| Resource | Direct Link |
|---|---|
| All resources | https://portal.azure.com/#@nyaaa.com/resource/subscriptions/e287db16-b6ae-415e-bd52-41c8ec5a8f08/resourceGroups/rg-nlaaroubi-sbx-eus2-001/overview |

### External Services

| Service | Link |
|---|---|
| GitHub Actions (deployment status) | https://github.com/nlaarh/FSLDashboard/actions |
| GitHub Repo Secrets | https://github.com/nlaarh/FSLDashboard/settings/secrets/actions |
| Salesforce org | https://aaawcny.lightning.force.com |

---

## 4. Application Monitoring

### Primary Health Checks

| Check | How |
|---|---|
| App is up | `GET https://fslapp-nyaaa.azurewebsites.net/api/health` — expect HTTP 200 |
| Admin panel | https://fslapp-nyaaa.azurewebsites.net/admin — enter `ADMIN_PIN` |
| System Health tab | Navigate to `/admin` → click **System Health** tab |
| DR health | https://fslapp-nyaaa-dr.azurewebsites.net/api/health |

### Admin Panel System Health Page

URL: **https://fslapp-nyaaa.azurewebsites.net/admin** → System Health tab

The health page performs quota-safe checks (no external API calls) and reports the following service cards:

| Service Card | What It Checks | Status Meanings |
|---|---|---|
| **Application** | FastAPI process uptime, PID, Python version | `healthy` = process running normally |
| **Azure App Service** | `WEBSITE_SITE_NAME` env var presence | `healthy` = running in Azure; `degraded` = running locally |
| **PostgreSQL** | Live TCP connection to `FSLAPP_PG_HOST` via Entra token | `healthy` = connected; `unhealthy` = connection failed |
| **DR PostgreSQL** | Live TCP connection to `FSLAPP_PG_DR_HOST` | `healthy` = DR DB reachable; `unhealthy` = unreachable |
| **DuckDB Local Cache** | Checks if `~/.fslapp/fsl_data.duckdb` file exists | `healthy` = exists; `degraded` = not yet created |
| **Shared Cache** | L1 memory + L2 disk cache stats and pending count | `degraded` if >10 pending entries |
| **Salesforce** | SF OAuth config present + circuit breaker state | `unhealthy` if circuit breaker is open |
| **Google Maps** | `GOOGLE_MAPS_API_KEY` presence | `healthy` = key configured |
| **AI Providers** | `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_AI_API_KEY` | `healthy` = at least one key configured |
| **GitHub** | `GITHUB_TOKEN` presence | `healthy` = token configured |

> **Note:** The health page does NOT make live pings to external APIs (Salesforce, Google Maps, OpenAI). It checks configuration presence and in-process stats only. This is intentional to protect API quotas.

### Reading Azure Logs

**From Azure Portal (real-time log stream):**

1. Open App Service Overview link (Section 3)
2. Left sidebar → **Monitoring** → **Log stream**
3. Logs stream in real-time from stdout/stderr

**From az CLI:**

```bash
# Tail live log stream
az webapp log tail \
  --name fslapp-nyaaa \
  --resource-group rg-nlaaroubi-sbx-eus2-001

# Download last 24h of logs as zip
az webapp log download \
  --name fslapp-nyaaa \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --log-file /tmp/fslapp-logs.zip
```

**Application log path inside container:** `/home/LogFiles/` (accessible via Kudu console)

**Kudu console** (file browser + live shell inside container):
```
https://fslapp-nyaaa.scm.azurewebsites.net/DebugConsole
```

### Checking App State via CLI

```bash
RG="rg-nlaaroubi-sbx-eus2-001"

# Check primary app state
az webapp show --name fslapp-nyaaa --resource-group $RG --query "state" -o tsv

# Check DR app state
az webapp show --name fslapp-nyaaa-dr --resource-group $RG --query "state" -o tsv

# Check primary DB state
az postgres flexible-server show --name fslapp-pg --resource-group $RG --query "state" -o tsv

# Check DR DB state
az postgres flexible-server show --name fslapp-pg-dr --resource-group $RG --query "state" -o tsv
```

Expected values: `Running` (app) / `Ready` (database)

---

## 5. Routine Maintenance

> For all `az CLI` commands, authenticate first: `az login` with your `@nyaaa.com` account.

---

### 5.1 Rotate Salesforce Credentials

Salesforce credentials expire when an admin resets the API user password or when the connected app is regenerated. **All five SF variables must be updated together.**

**Variables to update:**
- `SF_TOKEN_URL` — OAuth token endpoint (e.g. `https://login.salesforce.com/services/oauth2/token`)
- `SF_CONSUMER_KEY` — Connected app consumer key
- `SF_CONSUMER_SECRET` — Connected app consumer secret
- `SF_USERNAME` — API user login (`apiintegration@nyaaa.com`)
- `SF_PASSWORD` — API user password
- `SF_SECURITY_TOKEN` — Security token appended to password for API auth

**How to get updated values:**
1. Log in to Salesforce: https://aaawcny.lightning.force.com
2. Setup → Apps → App Manager → find the connected app → View → copy Consumer Key and Secret
3. For security token: Setup → My Personal Information → Reset My Security Token (only if resetting)

**Update via az CLI (primary app):**

```bash
RG="rg-nlaaroubi-sbx-eus2-001"

az webapp config appsettings set \
  --name fslapp-nyaaa \
  --resource-group $RG \
  --settings \
    SF_TOKEN_URL="https://login.salesforce.com/services/oauth2/token" \
    SF_CONSUMER_KEY="<new_consumer_key>" \
    SF_CONSUMER_SECRET="<new_consumer_secret>" \
    SF_USERNAME="apiintegration@nyaaa.com" \
    SF_PASSWORD="<new_password>" \
    SF_SECURITY_TOKEN="<new_security_token>"
```

The app restarts automatically after the settings change. Wait ~30 seconds, then verify:

```bash
curl -sf https://fslapp-nyaaa.azurewebsites.net/api/health
```

**Update via Portal:**

1. Open [Primary App Service Env Vars](#azure-portal-quick-links)
2. Click each SF variable → edit value → Apply
3. After all changes → click **Confirm** — app restarts once

**Also update DR app** (repeat with `--name fslapp-nyaaa-dr`):

```bash
az webapp config appsettings set \
  --name fslapp-nyaaa-dr \
  --resource-group $RG \
  --settings \
    SF_TOKEN_URL="https://login.salesforce.com/services/oauth2/token" \
    SF_CONSUMER_KEY="<new_consumer_key>" \
    SF_CONSUMER_SECRET="<new_consumer_secret>" \
    SF_USERNAME="apiintegration@nyaaa.com" \
    SF_PASSWORD="<new_password>" \
    SF_SECURITY_TOKEN="<new_security_token>"
```

---

### 5.2 Rotate Google Maps API Key

```bash
RG="rg-nlaaroubi-sbx-eus2-001"

# Primary
az webapp config appsettings set \
  --name fslapp-nyaaa \
  --resource-group $RG \
  --settings GOOGLE_MAPS_API_KEY="<new_key>"

# DR
az webapp config appsettings set \
  --name fslapp-nyaaa-dr \
  --resource-group $RG \
  --settings GOOGLE_MAPS_API_KEY="<new_key>"
```

**Via Portal:** Open Env Vars link → click `GOOGLE_MAPS_API_KEY` → enter new value → Apply → Confirm.

---

### 5.3 Rotate OpenAI / Anthropic / Google AI API Keys

Each key is independent. Update only the one(s) being rotated.

```bash
RG="rg-nlaaroubi-sbx-eus2-001"

# OpenAI
az webapp config appsettings set \
  --name fslapp-nyaaa --resource-group $RG \
  --settings OPENAI_API_KEY="<new_key>"

# Anthropic
az webapp config appsettings set \
  --name fslapp-nyaaa --resource-group $RG \
  --settings ANTHROPIC_API_KEY="<new_key>"
```

Repeat with `--name fslapp-nyaaa-dr` for the DR app.

---

### 5.4 Change ADMIN_PIN

The `ADMIN_PIN` is a 6-digit number that gates access to the `/admin` panel.

```bash
RG="rg-nlaaroubi-sbx-eus2-001"

# Primary
az webapp config appsettings set \
  --name fslapp-nyaaa \
  --resource-group $RG \
  --settings ADMIN_PIN="<new_6_digit_pin>"

# DR
az webapp config appsettings set \
  --name fslapp-nyaaa-dr \
  --resource-group $RG \
  --settings ADMIN_PIN="<new_6_digit_pin>"
```

> Communicate the new PIN to all admin users before changing it. The app does not have a PIN reset flow — if the PIN is lost, it must be reset via this procedure.

---

### 5.5 Rotate GITHUB_TOKEN

The `GITHUB_TOKEN` is a GitHub Personal Access Token (PAT) with `repo` scope used for GitHub integration features.

1. Go to https://github.com/settings/tokens → Generate new token (classic) → `repo` scope
2. Copy the new token

```bash
RG="rg-nlaaroubi-sbx-eus2-001"

# Primary
az webapp config appsettings set \
  --name fslapp-nyaaa \
  --resource-group $RG \
  --settings GITHUB_TOKEN="<new_token>"

# DR
az webapp config appsettings set \
  --name fslapp-nyaaa-dr \
  --resource-group $RG \
  --settings GITHUB_TOKEN="<new_token>"
```

**Also update GitHub Actions secrets** (used during deployment):

```bash
gh secret set AZURE_DEPLOY_USER --repo nlaarh/FSLDashboard --body '<kudu_username>'
gh secret set AZURE_DEPLOY_PASS --repo nlaarh/FSLDashboard --body '<kudu_password>'
```

To get fresh Kudu publishing credentials:

```bash
az webapp deployment list-publishing-profiles \
  --name fslapp-nyaaa \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --query "[?publishMethod=='MSDeploy'].[userName,userPWD]" -o tsv
```

---

### 5.6 Restart the App

**Restart is required when:** env vars are updated via CLI (Portal updates auto-restart), or if the app is unresponsive but the container is running.

```bash
# Restart primary
az webapp restart --name fslapp-nyaaa --resource-group rg-nlaaroubi-sbx-eus2-001

# Restart DR
az webapp restart --name fslapp-nyaaa-dr --resource-group rg-nlaaroubi-sbx-eus2-001
```

**Via Portal:** Open App Service Overview → click **Restart** in the top toolbar → confirm.

---

## 6. Deployment

### 6.1 How Deployment Works (Primary)

Deployment to the primary app (`fslapp-nyaaa`) is fully automated via GitHub Actions.

```
git push origin main
    │
    ▼
GitHub Actions (.github/workflows/deploy.yml)
    ├─ Build React frontend (npm ci && npm run build)
    ├─ Copy frontend/dist → backend/static/
    ├─ Zip source code + static assets
    └─ Upload zip to Azure Kudu API (fslapp-nyaaa.scm.azurewebsites.net)
         │
         ▼
    Azure App Service (Oryx build)
         ├─ Detects requirements.txt
         ├─ pip install into antenv/ virtual environment
         └─ Starts: gunicorn main:app --workers 2 ...
              │
              ▼
         Live at https://fslapp-nyaaa.azurewebsites.net
```

**Build time:** ~4 minutes total (1 min GitHub Actions + 3 min Oryx build)

### 6.2 Monitor a Deployment

```
https://github.com/nlaarh/FSLDashboard/actions
```

Watch for the "Deploy to Azure App Service" workflow. Green checkmark = deployed. If it fails, click the run for error details.

### 6.3 Manually Trigger a Deployment (No Code Changes)

```bash
gh workflow run deploy.yml --repo nlaarh/FSLDashboard --ref main
```

Or via GitHub: Actions tab → "Deploy to Azure App Service" → **Run workflow** → Run workflow.

### 6.4 Deploy to DR (Manual Zip Deploy)

The DR app does NOT have GitHub Actions configured. Deploy manually after any primary deployment.

**Step 1 — Build the zip locally:**

```bash
cd /path/to/FSL/apidev/FSLAPP

# Build React frontend
cd frontend && npm ci && npm run build
cp -r dist ../backend/static/

# Create deployment zip
cd ../backend
zip -r deploy.zip . \
  --exclude "*.pyc" \
  --exclude "__pycache__/*" \
  --exclude ".git/*" \
  --exclude "*.duckdb"
```

**Step 2 — Deploy to DR App Service:**

```bash
az webapp deploy \
  --name fslapp-nyaaa-dr \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --src-path backend/deploy.zip \
  --type zip
```

If the CLI times out (504 Gateway Timeout), use Azure Cloud Shell instead:

1. Go to https://shell.azure.com
2. Upload `deploy.zip`
3. Run the `az webapp deploy` command above

**Step 3 — Verify DR deployment:**

```bash
curl -sf https://fslapp-nyaaa-dr.azurewebsites.net/api/health
```

Expect HTTP 200.

### 6.5 Verify a Deployment Succeeded

```bash
# Health check
curl -sf https://fslapp-nyaaa.azurewebsites.net/api/health | python3 -m json.tool

# App state
az webapp show \
  --name fslapp-nyaaa \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --query "state" -o tsv
```

Expected: `Running` from app state, HTTP 200 from health endpoint.

### 6.6 Deployment Notes

> **Do NOT pre-package Python dependencies.** Let Oryx build on Azure. Pre-packaging causes ABI mismatches.

> **SCM basic auth must be enabled.** If GitHub Actions returns 401, re-enable:
> ```bash
> az rest --method put \
>   --url "https://management.azure.com/subscriptions/e287db16-b6ae-415e-bd52-41c8ec5a8f08/resourceGroups/rg-nlaaroubi-sbx-eus2-001/providers/Microsoft.Web/sites/fslapp-nyaaa/basicPublishingCredentialsPolicies/scm?api-version=2022-09-01" \
>   --body '{"properties":{"allow":true}}'
> ```

> **Oryx does NOT clean old static assets.** If the frontend shows stale UI after a deploy, manually overwrite `static/index.html` via Kudu VFS API:
> ```bash
> # Replace <KUDU_USER> and <KUDU_PASS> with publishing credentials
> curl -u "<KUDU_USER>:<KUDU_PASS>" -X PUT \
>   "https://fslapp-nyaaa.scm.azurewebsites.net/api/vfs/site/wwwroot/static/index.html" \
>   -H "If-Match: *" \
>   --data-binary @backend/static/index.html
> ```

---

## 7. DR Failover Procedure

**When to declare a failover:** Primary app (`fslapp-nyaaa`) or primary DB (`fslapp-pg`) is unavailable or critically degraded with no ETA on recovery.

> **CRITICAL:** `fslapp-pg` is shared with SalesPulse. If failing over the DB, the SalesPulse admin must redirect `salespulse-nyaaa` simultaneously. Contact: nlaaroubi@nyaaa.com.

### Pre-Failover Checklist (verify these are already in place — not during an incident)

- [ ] DR App (`fslapp-nyaaa-dr`) has current code deployed
- [ ] DR App has system-assigned managed identity enabled
- [ ] DR App managed identity is an Entra user on `fslapp-pg-dr` with schema grants
- [ ] All env vars are configured on DR App (see [Section 2 env var table](#environment-variables-reference))

**Verify DR App code is deployed:**
```bash
az webapp show \
  --name fslapp-nyaaa-dr \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --query "state" -o tsv
# Expected: Running
```

**Verify DR App managed identity:**
```bash
az webapp identity show \
  --name fslapp-nyaaa-dr \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --query "principalId" -o tsv
# Expected: a non-empty GUID
```

---

### Failover Steps

```bash
# Variables used throughout all steps
SUB="e287db16-b6ae-415e-bd52-41c8ec5a8f08"
RG="rg-nlaaroubi-sbx-eus2-001"
DR_APP="fslapp-nyaaa-dr"
DR_DB_HOST="fslapp-pg-dr.postgres.database.azure.com"
```

#### Step 1 — Declare incident and set timer

Note the current time. Target: traffic on DR within 15 minutes.

#### Step 2 — Start the DR App Service (if stopped)

```bash
az webapp start --name $DR_APP --resource-group $RG
```

Wait ~30 seconds for startup.

#### Step 3 — Point DR App at DR DB

```bash
az webapp config appsettings set \
  --name $DR_APP \
  --resource-group $RG \
  --settings \
    FSLAPP_PG_HOST="fslapp-pg-dr.postgres.database.azure.com" \
    FSLAPP_PG_DATABASE="fslapp" \
    FSLAPP_PG_USER="fslapp-nyaaa-dr"
```

The app restarts automatically. Wait ~30 seconds.

#### Step 4 — Verify DR App is healthy

```bash
# HTTP smoke test
curl -sf https://fslapp-nyaaa-dr.azurewebsites.net/api/health | python3 -m json.tool
```

Confirm HTTP 200. Then verify DB connectivity via admin health endpoint (requires ADMIN_PIN):

```bash
curl -sf -X POST https://fslapp-nyaaa-dr.azurewebsites.net/api/admin/system/health \
  -H "Content-Type: application/json" \
  -d '{"pin":"<ADMIN_PIN>"}' | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('Overall:', d['status'])
print('Postgres:', d['services']['postgres']['status'])
print('DR Postgres:', d['services']['dr_postgres']['status'])
"
```

Expected: `postgres.status == "healthy"`. If unhealthy, see [Troubleshooting — PostgreSQL connection fails](#92-postgresql-connection-fails).

#### Step 5 — Redirect users to DR URL

There is no automatic DNS failover configured. Route users by:

1. Posting to internal communications channel:  
   **DR URL:** https://fslapp-nyaaa-dr.azurewebsites.net
2. Updating any DNS CNAME or Traffic Manager profile pointing to the primary hostname
3. Updating hard-coded links in internal tools or SSO redirect URIs

#### Step 6 — Confirm and document

- Record actual recovery time (target: ≤15 min from declaration)
- Note PITR restore time to quantify data lag (time since last DR DB refresh)
- Notify stakeholders of DR URL and expected data lag

---

### Rollback to Primary

Once `fslapp-pg` (primary DB) is confirmed healthy:

#### Step 1 — Verify primary DB is reachable

```bash
nc -zv fslapp-pg.postgres.database.azure.com 5432
# Expected: Connection succeeded
```

#### Step 2 — Assess data written during DR

While on DR, writes went to `fslapp-pg-dr`. If any data must be preserved (WOA reviews, user changes, settings), export from DR before cutting back:

```bash
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

Import into primary before switching.

#### Step 3 — Switch primary app back to primary DB

```bash
az webapp config appsettings set \
  --name fslapp-nyaaa \
  --resource-group $RG \
  --settings \
    FSLAPP_PG_HOST="fslapp-pg.postgres.database.azure.com" \
    FSLAPP_PG_USER="fslapp-nyaaa"
```

#### Step 4 — Verify primary app is healthy

```bash
curl -sf https://fslapp-nyaaa.azurewebsites.net/api/health | python3 -m json.tool
```

#### Step 5 — Redirect users back to primary URL

https://fslapp-nyaaa.azurewebsites.net

#### Step 6 — Idle the DR App Service (optional cost savings)

```bash
az webapp stop --name $DR_APP --resource-group $RG
```

#### Step 7 — Schedule DR DB refresh

The DR DB is now stale relative to primary. Refresh within 24 hours (see Section 8).

---

## 8. DR Database Refresh

The DR database (`fslapp-pg-dr`) is a static PITR clone. It does not replicate continuously. Refresh it periodically to minimize RPO.

**Recommended frequency:** Weekly (or before planned maintenance windows)  
**Time required:** 15–30 minutes  
**Downtime impact:** None on primary. DR unavailable during refresh (expected).  
**Data lag after refresh:** Equals time since `RESTORE_TIME` was set.

> **CRITICAL: PITR cannot restore in-place.** The procedure deletes the old DR server and creates a new one with the same name. Entra grants must be re-applied after every refresh.

> **CRITICAL: Shared DB.** After refresh, SalesPulse's `salespulse-nyaaa-dr` also needs its Entra grants re-applied on `fslapp-pg-dr`. Coordinate with SalesPulse admin.

### Step 1 — Note restore target time

```bash
# Use current time for freshest data
RESTORE_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Restoring to: $RESTORE_TIME"

# Or use a specific past timestamp (ISO 8601 UTC):
# RESTORE_TIME="2026-05-24T12:00:00Z"
```

`--restore-time` accepts any ISO 8601 UTC timestamp within the backup retention window (default 7 days). Choose a time when the source DB was in a known-good state.

### Step 2 — Delete the existing DR server

```bash
RG="rg-nlaaroubi-sbx-eus2-001"

az postgres flexible-server delete \
  --name fslapp-pg-dr \
  --resource-group $RG \
  --yes
```

> Deletion takes 2–5 minutes.

### Step 3 — Restore a new PITR clone

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

Wait for: `Ready` (typically 15–25 minutes).

### Step 4 — Re-apply Entra grants

PITR clones Postgres roles from the source but Entra managed identity bindings do not always carry over. Always re-run after every restore.

Connect to the DR DB as Entra admin:

```bash
psql "host=fslapp-pg-dr.postgres.database.azure.com \
      dbname=fslapp \
      user=nlaaroubi@nyaaa.com \
      sslmode=require"
```

Then run for `fslapp-nyaaa-dr` (FSLPulse DR identity):

```sql
-- If role does not exist yet:
CREATE ROLE "fslapp-nyaaa-dr" WITH LOGIN;
SECURITY LABEL FOR "pgaadauth" ON ROLE "fslapp-nyaaa-dr" IS 'aadauth';

-- Grant schema access (FSLPulse schemas)
GRANT USAGE ON SCHEMA core TO "fslapp-nyaaa-dr";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA core TO "fslapp-nyaaa-dr";
GRANT USAGE ON SCHEMA optimizer TO "fslapp-nyaaa-dr";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA optimizer TO "fslapp-nyaaa-dr";

-- Cover future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA core
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "fslapp-nyaaa-dr";
ALTER DEFAULT PRIVILEGES IN SCHEMA optimizer
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "fslapp-nyaaa-dr";
```

Also re-apply grants for SalesPulse DR identity (coordinate with SalesPulse admin):

```sql
-- SalesPulse DR identity (contact SalesPulse admin for their exact role name)
GRANT USAGE ON SCHEMA sales TO "salespulse-nyaaa-dr";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA sales TO "salespulse-nyaaa-dr";
```

### Step 5 — Smoke test

```bash
curl -sf -X POST https://fslapp-nyaaa-dr.azurewebsites.net/api/admin/system/health \
  -H "Content-Type: application/json" \
  -d '{"pin":"<ADMIN_PIN>"}' \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('DR Postgres:', d['services']['dr_postgres']['status'])
"
```

Expected: `healthy`

---

## 9. Troubleshooting

### 9.1 App Returns 503

**Symptoms:** Browser or curl gets HTTP 503 from https://fslapp-nyaaa.azurewebsites.net

**Likely causes:**
1. App Service is stopped
2. Container crashed and is restarting
3. Gunicorn worker pool exhausted (application overloaded)

**Diagnose:**

```bash
# Check app state
az webapp show \
  --name fslapp-nyaaa \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --query "state" -o tsv

# Tail logs for crash reason
az webapp log tail \
  --name fslapp-nyaaa \
  --resource-group rg-nlaaroubi-sbx-eus2-001
```

**Fix:**

```bash
# Start if stopped
az webapp start --name fslapp-nyaaa --resource-group rg-nlaaroubi-sbx-eus2-001

# Or restart if running but unresponsive
az webapp restart --name fslapp-nyaaa --resource-group rg-nlaaroubi-sbx-eus2-001
```

If the app keeps crashing (exit code 1), check logs for import errors or missing dependencies, then redeploy.

---

### 9.2 App Returns 500

**Symptoms:** App loads but specific API calls return HTTP 500 Internal Server Error

**Likely causes:**
1. Salesforce OAuth failure (expired credentials)
2. PostgreSQL connection failure
3. Missing environment variable
4. Application bug introduced in latest deployment

**Diagnose:**

```bash
# Check system health (replace PIN)
curl -sf -X POST https://fslapp-nyaaa.azurewebsites.net/api/admin/system/health \
  -H "Content-Type: application/json" \
  -d '{"pin":"<ADMIN_PIN>"}' | python3 -m json.tool

# Tail logs for stack trace
az webapp log tail \
  --name fslapp-nyaaa \
  --resource-group rg-nlaaroubi-sbx-eus2-001
```

**Fix by root cause:**
- **Salesforce auth failure:** Rotate SF credentials (Section 5.1)
- **PostgreSQL failure:** See Section 9.3
- **Missing env var:** Add the variable (Section 5) and restart
- **Code bug:** Redeploy previous commit via GitHub Actions (`git revert` + push to main)

---

### 9.3 PostgreSQL Connection Fails

**Symptoms:** System health page shows `postgres.status == "unhealthy"`, app cannot load data from DB

**Likely causes:**
1. Entra token acquisition failing (az CLI not authenticated inside container)
2. PG server is stopped or restarting
3. Managed identity lacks schema grants
4. Network/firewall rule blocking connection

**Diagnose:**

```bash
# Check DB server state
az postgres flexible-server show \
  --name fslapp-pg \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --query "state" -o tsv

# Start DB if stopped
az postgres flexible-server start \
  --name fslapp-pg \
  --resource-group rg-nlaaroubi-sbx-eus2-001
```

**Verify managed identity:**

```bash
# Confirm identity is enabled on App Service
az webapp identity show \
  --name fslapp-nyaaa \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --query "principalId" -o tsv
```

If the identity is missing, re-assign it:

```bash
az webapp identity assign \
  --name fslapp-nyaaa \
  --resource-group rg-nlaaroubi-sbx-eus2-001
```

Then reconnect to the PG server as Entra admin and re-grant schema permissions to `fslapp-nyaaa`.

---

### 9.4 Salesforce Auth Fails

**Symptoms:** System health shows `salesforce.status == "unhealthy"`, SF circuit breaker is open, live dispatch/SA data not loading

**Likely causes:**
1. SF_PASSWORD or SF_SECURITY_TOKEN expired or changed
2. SF_CONSUMER_KEY / SF_CONSUMER_SECRET rotated
3. Salesforce org locked the API user account (too many failed logins)

**Diagnose:**

1. Open Admin Panel → System Health → Salesforce card
2. If `breaker_open: true`, the SF client is in circuit-breaker mode (too many consecutive failures)
3. Check logs:
   ```bash
   az webapp log tail \
     --name fslapp-nyaaa \
     --resource-group rg-nlaaroubi-sbx-eus2-001
   ```
   Look for `OAuth` or `401` errors.

**Fix:**

1. Rotate SF credentials (Section 5.1) with fresh values from Salesforce Setup
2. After updating, restart the app — the circuit breaker resets on restart:
   ```bash
   az webapp restart --name fslapp-nyaaa --resource-group rg-nlaaroubi-sbx-eus2-001
   ```
3. If the API user account is locked in Salesforce: Salesforce admin must unlock the user (Setup → Users → unlock)

---

### 9.5 GitHub Actions Deployment Fails

**Symptoms:** GitHub Actions workflow shows red ✗, deployment did not complete

**Diagnose:**
1. https://github.com/nlaarh/FSLDashboard/actions — click the failed run
2. Check which step failed (npm build, zip, or Kudu upload)

**Common fixes:**

| Error | Fix |
|---|---|
| `401 Unauthorized` on Kudu upload | Refresh publishing credentials and update GitHub secrets (Section 5.5) |
| `504 Gateway Timeout` on upload | Re-run the workflow — transient Azure issue |
| npm build fails | Check for frontend dependency or build errors in the log |
| Oryx build fails | Check `requirements.txt` for invalid packages |

---

### 9.6 Stale Frontend After Deployment

**Symptoms:** App deployed but users still see old UI, browser console references missing JS files

**Cause:** Oryx merges files on top of existing ones without deleting old assets. Old `index.html` may persist.

**Fix:**

```bash
# Get Kudu credentials (from publishing profile)
KUDU_USER="<publishing_username>"
KUDU_PASS="<publishing_password>"

# Delete old static assets
curl -u "$KUDU_USER:$KUDU_PASS" -X DELETE \
  "https://fslapp-nyaaa.scm.azurewebsites.net/api/vfs/site/wwwroot/static/assets/?recursive=true" \
  -H "If-Match: *"

# Overwrite index.html with the new version
curl -u "$KUDU_USER:$KUDU_PASS" -X PUT \
  "https://fslapp-nyaaa.scm.azurewebsites.net/api/vfs/site/wwwroot/static/index.html" \
  -H "If-Match: *" \
  --data-binary @backend/static/index.html

# Restart
az webapp restart --name fslapp-nyaaa --resource-group rg-nlaaroubi-sbx-eus2-001
```

---

## 10. Emergency Contacts & Escalation

| Role | Contact | Scope |
|---|---|---|
| **Superadmin** | nlaaroubi@nyaaa.com | All infrastructure, Azure subscription, Salesforce org, GitHub repo |

### Escalation Path

1. **Level 1 — Self-service:** Use this guide. Most issues resolved by Section 9 diagnostics + Section 5 credential rotation.
2. **Level 2 — Superadmin:** Contact nlaaroubi@nyaaa.com with:
   - Timestamp of when issue started
   - Which URL/endpoint is failing
   - HTTP status code or error message
   - Screenshot of Admin Panel System Health page (if accessible)
   - Last GitHub Actions deployment: https://github.com/nlaarh/FSLDashboard/actions
3. **Level 3 — Azure Support:** Open a ticket at https://portal.azure.com if the issue is Azure infrastructure (App Service platform outage, PG server unresponsive to CLI commands).

### Quick Reference — First Commands to Run

| Situation | First command |
|---|---|
| App is down (503/504) | `az webapp show --name fslapp-nyaaa --resource-group rg-nlaaroubi-sbx-eus2-001 --query state -o tsv` |
| App crashing | `az webapp log tail --name fslapp-nyaaa --resource-group rg-nlaaroubi-sbx-eus2-001` |
| DB unreachable | `az postgres flexible-server show --name fslapp-pg --resource-group rg-nlaaroubi-sbx-eus2-001 --query state -o tsv` |
| SF auth broken | Admin Panel → System Health → Salesforce card; then Section 5.1 |
| Trigger DR failover | Start at Section 7 |
| Refresh DR DB | Start at Section 8 |
| Rotate SF credentials | Section 5.1 |
| Change ADMIN_PIN | Section 5.4 |
| Check deployment status | https://github.com/nlaarh/FSLDashboard/actions |
