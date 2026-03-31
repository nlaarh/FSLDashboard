# FSLAPP Azure Deployment — MANDATORY READ BEFORE ANY DEPLOY

## ========================================================
## RULE #0: ONLY DEPLOY VIA GIT PUSH. PERIOD.
## ========================================================
## NEVER use `az webapp deploy`, `curl zipdeploy`, Kudu VFS,
## or ANY manual deployment method for Python code.
## The ONLY deploy method is: git push origin main
## GitHub Actions handles EVERYTHING automatically.
##
## Violation of this rule on Mar 9 2026 caused:
## - Multiple stuck Oryx builds (409 deploy lock)
## - Corrupted output.tar.zst
## - 2+ hours of downtime
## - Setting SCM_DO_BUILD_DURING_DEPLOYMENT=false broke pip install
## - Changing startup command broke path resolution
## ========================================================

## The ONLY Deploy Process (Proven, Repeatable)

### Step 1: Make changes locally
- Edit backend/*.py, frontend/src/*.jsx, etc.

### Step 2: Build frontend
```bash
cd FSLAPP/frontend && npm run build
```

### Step 3: Copy build to backend/static
```bash
cd FSLAPP && rm -rf backend/static && cp -r frontend/dist backend/static
```

### Step 4: Commit and push
```bash
cd FSLAPP
git add backend/main.py frontend/src/pages/MyPage.jsx backend/static/  # specific files only
git commit -m "Description"
git push origin main
```

### Step 5: Wait ~4 minutes
GitHub Actions automatically:
1. Builds React frontend (redundant but harmless)
2. Creates deploy.zip from `backend/` (*.py, startup.sh, requirements.txt, static/)
3. POSTs to Kudu zipdeploy
4. Oryx runs pip install into antenv/ virtualenv
5. Creates output.tar.zst cache
6. Gunicorn starts

### Step 6: Verify
```bash
curl -s -o /dev/null -w "%{http_code}" https://fslapp-nyaaa.azurewebsites.net/api/health
```
Accept 200, 401, or 302 as "alive". If 503/000, wait 60s more.

### Step 7: If deploy fails, check logs
```bash
gh run view --repo nlaarh/FSLDashboard --log-failed  # GitHub Actions logs
# Then Kudu logs:
TOKEN=$(az account get-access-token --resource https://management.azure.com --query accessToken -o tsv)
curl -s "https://fslapp-nyaaa.scm.azurewebsites.net/api/vfs/LogFiles/$(date -u +%Y_%m_%d)_lw0sdlwk0005XI_default_docker.log" -H "Authorization: Bearer $TOKEN" | tail -30
```

## Architecture
- **Repo**: `nlaarh/FSLDashboard` on GitHub
- **Azure App**: `fslapp-nyaaa` (Python 3.13 Linux App Service)
- **Resource Group**: `rg-nlaaroubi-sbx-eus2-001`
- **Pipeline**: GitHub Actions → Kudu ZIP Deploy → Oryx builds on server → gunicorn starts
- **Workflow**: `.github/workflows/deploy.yml` (triggers on push to main)
- **Startup**: Oryx extracts output.tar.zst to /tmp/<hash>, activates antenv, runs gunicorn

## Recovery from Corrupted State
If the app is completely broken (stuck deploys, corrupted cache):

```bash
# 1. Stop
az webapp stop -g rg-nlaaroubi-sbx-eus2-001 -n fslapp-nyaaa

# 2. Delete everything in wwwroot
TOKEN=$(az account get-access-token --resource https://management.azure.com --query accessToken -o tsv)
curl -X DELETE "https://fslapp-nyaaa.scm.azurewebsites.net/api/vfs/site/wwwroot/?recursive=true" \
  -H "Authorization: Bearer $TOKEN" -H "If-Match: *"

# 3. Start app back
az webapp start -g rg-nlaaroubi-sbx-eus2-001 -n fslapp-nyaaa

# 4. Trigger fresh deploy
gh workflow run deploy.yml --repo nlaarh/FSLDashboard --ref main

# 5. Wait ~5 min for full Oryx rebuild (pip install from scratch)
```

## NEVER DO These Things
1. **NEVER** use `az webapp deploy` or `curl` to zipdeploy directly
2. **NEVER** upload files via Kudu VFS API for Python code
3. **NEVER** change `SCM_DO_BUILD_DURING_DEPLOYMENT` setting
4. **NEVER** change the startup command on Azure (it's configured correctly)
5. **NEVER** delete output.tar.zst — it contains pip-installed packages
6. **NEVER** delete static/assets/ via VFS during deploy

## Critical Technical Details
- deploy.zip is created from INSIDE `backend/` dir → files at zip root (no `backend/` prefix)
- Oryx extracts output.tar.zst to `/tmp/<hash>`, NOT `/home/site/wwwroot`
- Startup command: `gunicorn main:app --workers 1 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000`
- PYTHONPATH is set by Oryx to include antenv virtualenv
- deploy.yml uses `*.py` glob to include ALL Python files
- Kudu credentials in GitHub Secrets: `AZURE_DEPLOY_USER`, `AZURE_DEPLOY_PASS`

## Environment Variables (Azure Portal, NOT .env)
- `SF_CONSUMER_KEY`, `SF_CONSUMER_SECRET`, `SF_USERNAME`, `SF_PASSWORD`, `SF_SECURITY_TOKEN`
- `ADMIN_PIN`
- `AUTH_SECRET`

## Debugging
- **Kudu console**: `https://fslapp-nyaaa.scm.azurewebsites.net/`
- **Log stream**: `https://fslapp-nyaaa.scm.azurewebsites.net/api/logstream`
- **VFS browse**: `https://fslapp-nyaaa.scm.azurewebsites.net/api/vfs/site/wwwroot/`
- **Docker logs**: Check `*_default_docker.log` in LogFiles/ for app stdout/stderr
- **SCM logs**: Check `*_default_scm_docker.log` for Oryx build output
