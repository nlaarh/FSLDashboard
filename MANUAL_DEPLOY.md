# FSLAPP Deployment Guide

**Live URL:** https://fslapp-nyaaa.azurewebsites.net
**Login:** `admin` / `admin2026!@`
**Last deployed:** March 7, 2026

---

## How Deployment Works

Deployment is fully automated via GitHub Actions. Push to `main` and it deploys.

```
git push origin main
    |
    v
GitHub Actions (.github/workflows/deploy.yml)
    |-- Build React frontend (npm ci && npm run build)
    |-- Copy frontend/dist -> backend/static
    |-- Zip source code + static assets
    |-- Upload zip to Azure Kudu API
    v
Azure App Service (Oryx build)
    |-- Detects requirements.txt
    |-- pip install into antenv/ virtual environment
    |-- Starts: gunicorn main:app
    v
App live at https://fslapp-nyaaa.azurewebsites.net
```

Build + deploy takes ~4 minutes total (1 min GitHub Actions + 3 min Oryx build on Azure).

---

## How to Redeploy

### Automatic (recommended)

Just push to `main`:

```bash
cd /Users/abdennourlaaroubi/Library/CloudStorage/OneDrive-EnProIndustriesInc/AAA/Dev/FSL/FSL/apidev/FSLAPP
git add -A
git commit -m "Your change description"
git push origin main
```

GitHub Actions triggers automatically. Monitor at:
https://github.com/nlaarh/FSLDashboard/actions

Wait ~4 minutes, then test: https://fslapp-nyaaa.azurewebsites.net/api/health

### Manual trigger (no code changes)

```bash
gh workflow run deploy.yml --repo nlaarh/FSLDashboard --ref main
```

Or go to GitHub Actions tab > "Deploy to Azure App Service" > "Run workflow".

### Manual via Azure Portal (emergency fallback)

1. Build the zip locally:
   ```bash
   cd backend
   zip -r deploy.zip main.py app.py sf_client.py ops.py db.py \
     cache.py scorer.py scheduler.py simulator.py \
     gunicorn.conf.py startup.sh requirements.txt static/
   ```
2. Go to https://portal.azure.com > fslapp-nyaaa > Deployment Center
3. Upload `deploy.zip`
4. Wait 3 min for Oryx to build

---

## Azure Configuration

### Resource Details

| Setting | Value |
|---------|-------|
| App Name | `fslapp-nyaaa` |
| Resource Group | `rg-nlaaroubi-sbx-eus2-001` |
| Subscription | AAAWCNY Azure Sandbox |
| Location | Canada Central |
| Plan | AABC (B1 - 1.75 GB RAM, 1 vCPU) |
| Runtime | Python 3.13 (Linux) |
| Startup Command | `gunicorn main:app --workers 2 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --timeout 120` |

### App Settings (Environment Variables)

Set in Azure Portal > Configuration > Application settings:

| Setting | Purpose |
|---------|---------|
| `SF_TOKEN_URL` | Salesforce OAuth endpoint |
| `SF_CONSUMER_KEY` | Salesforce connected app key |
| `SF_CONSUMER_SECRET` | Salesforce connected app secret |
| `SF_USERNAME` | Salesforce API username |
| `SF_PASSWORD` | Salesforce API password |
| `SF_SECURITY_TOKEN` | Salesforce security token |
| `ADMIN_USER` | App login username (default: admin) |
| `ADMIN_PASSWORD` | App login password |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | `true` (Oryx builds Python deps) |
| `ENABLE_ORYX_BUILD` | `true` |

To update credentials:
```bash
az webapp config appsettings set --name fslapp-nyaaa \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --settings SF_TOKEN_URL="..." SF_CONSUMER_KEY="..." ...
```

### GitHub Secrets

Set in https://github.com/nlaarh/FSLDashboard/settings/secrets/actions:

| Secret | Purpose |
|--------|---------|
| `AZURE_DEPLOY_USER` | Kudu publishing username (starts with `$fslapp-nyaaa`) |
| `AZURE_DEPLOY_PASS` | Kudu publishing password |

To refresh these if deployment auth fails:
```bash
# Get new credentials
az webapp deployment list-publishing-profiles \
  --name fslapp-nyaaa \
  --resource-group rg-nlaaroubi-sbx-eus2-001 \
  --query "[?publishMethod=='MSDeploy'].[userName,userPWD]" -o tsv

# Update GitHub secrets
gh secret set AZURE_DEPLOY_USER --repo nlaarh/FSLDashboard --body '<username>'
gh secret set AZURE_DEPLOY_PASS --repo nlaarh/FSLDashboard --body '<password>'
```

---

## Project Structure

```
FSLAPP/
  frontend/           React app (Vite)
    src/
    package.json
  backend/            FastAPI app
    main.py           Full application (routes, auth, Salesforce queries)
    app.py            Minimal test app (health check only)
    sf_client.py      Salesforce OAuth + SOQL client
    ops.py            Daily ops API endpoints
    scorer.py         Garage scoring logic
    scheduler.py      Schedule generation
    simulator.py      Dispatch simulation
    cache.py          In-memory TTL cache
    db.py             DuckDB module (unused, kept for future)
    requirements.txt  Python dependencies
    static/           Pre-built React (committed as fallback)
  .github/
    workflows/
      deploy.yml      GitHub Actions deployment pipeline
```

### Dependencies (requirements.txt)

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
requests==2.32.3
python-dotenv==1.0.1
pydantic==2.10.4
gunicorn==22.0.0
```

No duckdb, numpy, or pandas. Lightweight install (~30s on Oryx).

---

## Troubleshooting

### App not responding after deploy

1. **Wait 4 minutes** - Oryx build + container startup takes time
2. Check health: `curl https://fslapp-nyaaa.azurewebsites.net/api/health`
3. If timeout, check container state:
   ```bash
   az webapp show --name fslapp-nyaaa \
     --resource-group rg-nlaaroubi-sbx-eus2-001 --query 'state' -o tsv
   ```
4. If "Stopped", start it: `az webapp start --name fslapp-nyaaa --resource-group rg-nlaaroubi-sbx-eus2-001`

### Container keeps crashing (exit code 1)

Check docker logs in Azure Portal:
- Go to fslapp-nyaaa > Monitoring > Log stream
- Or: Diagnose and solve problems > Application Logs

Common causes:
- **Missing dependency** - Add to `requirements.txt` and redeploy
- **Import error** - Test locally first: `cd backend && python3 -c "import main"`
- **Port mismatch** - Startup command must bind to port 8000

### Deployment returns 401

Kudu basic auth may be disabled. Re-enable:
```bash
az rest --method put \
  --url "https://management.azure.com/subscriptions/e287db16-b6ae-415e-bd52-41c8ec5a8f08/resourceGroups/rg-nlaaroubi-sbx-eus2-001/providers/Microsoft.Web/sites/fslapp-nyaaa/basicPublishingCredentialsPolicies/scm?api-version=2022-09-01" \
  --body '{"properties":{"allow":true}}'
```

### Oryx build fails

Check that `SCM_DO_BUILD_DURING_DEPLOYMENT=true` is set:
```bash
az webapp config appsettings list --name fslapp-nyaaa \
  --resource-group rg-nlaaroubi-sbx-eus2-001 --query "[?name=='SCM_DO_BUILD_DURING_DEPLOYMENT']"
```

### GitHub Actions deploy step fails

1. Check the run log: https://github.com/nlaarh/FSLDashboard/actions
2. If Kudu auth error, refresh publishing credentials (see GitHub Secrets section above)
3. If network timeout, re-run the workflow

---

## Key Lessons Learned

1. **Let Oryx build on Azure** - Do NOT pre-package Python dependencies. Azure's Oryx build system creates a proper `antenv/` virtual environment that the container knows how to activate. Pre-packaging `.python_packages/` causes ABI mismatches and path issues.

2. **SCM basic auth must be enabled** - Azure may have it disabled by policy. Without it, all Kudu-based deployments (zip deploy, publish profile, GitHub Actions) return 401.

3. **Python version must match** - Azure runs Python 3.13. If you ever pre-install packages, they must be compiled for 3.13 + Linux x86_64. The `.so` files are version-specific.

4. **Startup command binds to port 8000** - Azure's default. Don't use `$PORT` without testing — the container entrypoint handles port forwarding.

5. **Azure Entra ID auth is separate** - Currently disabled. The app has its own login (admin/password). To re-enable SSO, configure it in Portal > Authentication.

6. **Don't restart during deploy** - Azure's Oryx restarts the SCM container during builds. Running config changes or restarts simultaneously causes "Deployment stopped due to SCM container restart" errors. Wait for deploy to finish first.
