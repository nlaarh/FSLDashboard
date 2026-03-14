# Manual Deployment Instructions

## Issue
Azure CLI deployment commands are failing with 504 Gateway Timeout errors.
This is an Azure service issue, not a problem with our code.

## What's Ready
- ✅ Frontend built: `backend/static/` (React SPA)
- ✅ Backend code: All Python files in `backend/`
- ✅ Deployment package: `backend/deploy.zip` (302 KB)
- ✅ Salesforce credentials: Already configured in Azure App Service
- ✅ App Service: Running at https://fslapp-nyaaa.azurewebsites.net/

## Manual Deployment Options

### Option 1: Azure Portal (Recommended - 5 minutes)
1. Open https://portal.azure.com
2. Navigate to: Home → App Services → `fslapp-nyaaa`
3. In left menu, click **Deployment Center**
4. Choose **Zip Deploy** tab
5. Click **Browse** and select: `/Users/abdennourlaaroubi/Library/CloudStorage/OneDrive-EnProIndustriesInc/AAA/Dev/FSL/FSL/apidev/FSLAPP/backend/deploy.zip`
6. Click **Deploy**
7. Wait 2-3 minutes for deployment to complete
8. Visit: https://fslapp-nyaaa.azurewebsites.net/

### Option 2: VS Code Azure Extension
1. Install "Azure App Service" extension in VS Code
2. Sign in to Azure
3. Right-click on `backend` folder
4. Choose "Deploy to Web App"
5. Select `fslapp-nyaaa`

### Option 3: Azure Cloud Shell (Better Network)
1. Go to https://shell.azure.com
2. Upload `deploy.zip`:
   ```bash
   # After uploading file
   az webapp deploy \
     --name fslapp-nyaaa \
     --resource-group rg-nlaaroubi-sbx-eus2-001 \
     --src-path deploy.zip \
     --type zip
   ```

### Option 4: Direct Kudu Upload
1. Go to: https://fslapp-nyaaa.scm.azurewebsites.net/ZipDeployUI
2. Drag and drop `deploy.zip` onto the page
3. Wait for upload to complete

## Verify Deployment
Once deployed, verify:
1. App loads: https://fslapp-nyaaa.azurewebsites.net/
2. API works: https://fslapp-nyaaa.azurewebsites.net/api/ops/territories
3. Check logs: Azure Portal → App Service → Log stream

## Next Step: Enable SSO
After successful deployment:
```bash
cd FSLAPP
.azure/enable-sso.sh fslapp-nyaaa
```

---
**Prepared**: March 6, 2026
**Deploy Package**: `backend/deploy.zip`
**App URL**: https://fslapp-nyaaa.azurewebsites.net/
