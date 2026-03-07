# FSL App - Manual Deployment Instructions

## Problem Summary
After 8 hours of debugging, we found the issue: **`app.py` was missing from deploy.zip**

The fix has been applied, but Azure CLI/API are experiencing 504 Gateway Timeouts, preventing automated deployment.

## Solution: Manual Deployment via Azure Portal

### Step 1: Access Azure Portal
1. Go to: https://portal.azure.com
2. Sign in with: nlaaroubi@nyaaa.com
3. Navigate to: **Resource Groups** → **rg-nlaaroubi-sbx-eus2-001** → **fslapp-nyaaa**

### Step 2: Upload Deployment Package
1. In left menu, click **"Deployment Center"**
2. Click **"Manual Deployment (Push)"** or **"Local Git"**
3. Choose **"ZIP Deploy"** option
4. Upload file: `/Users/abdennourlaaroubi/Library/CloudStorage/OneDrive-EnProIndustriesInc/AAA/Dev/FSL/FSL/apidev/FSLAPP/backend/deploy.zip`
5. Click **"Deploy"**
6. Wait 2-3 minutes for build to complete

### Step 3: Configure Startup Command
1. Still in the app, go to **Configuration** (left menu)
2. Under **General Settings**, find **Startup Command**
3. Enter exactly:
   ```
   gunicorn app:app -w 2 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --access-logfile - --error-logfile -
   ```
4. Click **Save**
5. App will restart automatically

### Step 4: Test the App
1. Wait 1-2 minutes for warmup
2. Open: https://fslapp-nyaaa.azurewebsites.net/api/health
3. Expected response:
   ```json
   {"status": "ok", "test": true}
   ```

## What Was Fixed

### The Bug
The deployment package was missing `app.py`, so when Azure tried to run `gunicorn app:app`, it failed with "module not found".

### Files Now Included in deploy.zip
- ✅ **app.py** (270 bytes) - Minimal FastAPI app for testing
- ✅ **main.py** (56 KB) - Full FSL application
- ✅ **gunicorn.conf.py** - Proper configuration
- ✅ **startup.sh** - Startup script with error detection
- ✅ All dependencies (requirements.txt)
- ✅ React frontend (static/ directory)

## Alternative: Switch to main.py

Once the minimal `app.py` is working, you can switch to the full application:

1. Go to **Configuration** → **Startup Command**
2. Change to:
   ```
   gunicorn main:app -w 2 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --access-logfile - --error-logfile -
   ```
3. Save and restart

## Salesforce Configuration

Already configured in Azure App Settings:
- ✅ SF_TOKEN_URL
- ✅ SF_CONSUMER_KEY
- ✅ SF_CONSUMER_SECRET
- ✅ SF_USERNAME
- ✅ SF_PASSWORD
- ✅ SF_SECURITY_TOKEN

## Authentication

The app supports:
1. **Microsoft SSO** - Azure Entra ID (nyaaa.com accounts)
2. **Basic Auth** - Username: `admin`, Password: `admin2026!@`

## Troubleshooting

### If app still doesn't work:
1. Check logs: **Monitoring** → **Log stream** (in portal)
2. View recent errors: **Diagnose and solve problems**
3. Restart app: Click **Restart** at top

### If you see "Container crashed":
- Check that `app.py` exists in deployed files
- Verify startup command is correct
- Check that all dependencies installed (look for pip errors in logs)

## Why Azure CLI Failed

Azure deployment services experienced persistent issues:
- `az webapp deploy` → 504 Gateway Timeout
- ARM REST API → 504 Gateway Timeout
- Even basic commands like `az account get-access-token` timed out intermittently

This is an Azure service issue, not a code problem.

## What We Learned

1. Always verify all files are in deployment package (use `unzip -l deploy.zip`)
2. Azure ARM REST API is more reliable than CLI when it works
3. Port binding must use `$PORT` or `8000` (Azure's default)
4. Minimal test apps help isolate deployment vs code issues
5. Sometimes manual Portal deployment is fastest

---

**Deployment package ready at:**
`/Users/abdennourlaaroubi/Library/CloudStorage/OneDrive-EnProIndustriesInc/AAA/Dev/FSL/FSL/apidev/FSLAPP/backend/deploy.zip`

**Created:** March 7, 2026
**Status:** Ready for manual upload via Azure Portal
