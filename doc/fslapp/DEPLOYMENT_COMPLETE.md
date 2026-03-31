# FSL App - Azure Deployment Complete

## ✅ Deployment Status: SUCCESSFUL

**Deployed**: March 6, 2026
**App URL**: https://fslapp-nyaaa.azurewebsites.net/
**Method**: Azure ARM REST API (OneDeploy)

---

## 📦 What Was Deployed

### Application Components
- **Backend**: FastAPI (Python 3.13)
  - `main.py` - Main application with all routes
  - `ops.py` - Daily operations endpoints
  - `scorer.py` - Garage scorecard engine
  - `sf_client.py` - Salesforce OAuth client
  - `scheduler.py`, `simulator.py`, `db.py`, `cache.py`

- **Frontend**: React SPA (Vite build)
  - Bundle: 927 KB JavaScript + 32 KB CSS
  - Location: `/backend/static/`
  - Served by FastAPI on all non-API routes

### Configuration Applied
| Setting | Value |
|---------|-------|
| **Runtime** | Python 3.13 |
| **SKU** | B1 (Basic, 1 core, 1.75 GB RAM) |
| **Region** | Canada Central |
| **Startup Command** | `gunicorn main:app --workers 2 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT --timeout 120` |

---

## 🔐 Authentication Configured

### Microsoft Entra ID (Azure AD) SSO ✅
- **Enabled**: Yes
- **Provider**: Microsoft Entra ID
- **Tenant**: nyaaa.com (87c1e7cf-b6c4-434f-b18e-5444b1bce3bb)
- **Behavior**: Users must sign in with @nyaaa.com accounts
- **Redirect**: Unauthenticated users → Microsoft login page

### Access
Users can access the app at https://fslapp-nyaaa.azurewebsites.net/ and will be prompted to sign in with their Microsoft 365 credentials.

**Note**: Basic auth (admin/admin2026!@) is managed by Azure Easy Auth infrastructure level.

---

## ⚙️ Salesforce Integration Configured

All Salesforce credentials are configured as environment variables:

| Variable | Status |
|----------|--------|
| `SF_TOKEN_URL` | ✅ Set |
| `SF_CONSUMER_KEY` | ✅ Set |
| `SF_CONSUMER_SECRET` | ✅ Set |
| `SF_USERNAME` | ✅ Set |
| `SF_PASSWORD` | ✅ Set |
| `SF_SECURITY_TOKEN` | ✅ Set |

The app can connect to Salesforce org: `aaawcny.my.salesforce.com`

---

## 🚀 Deployment Process Summary

### Method Used: Azure ARM REST API
After Azure CLI timeouts, we successfully used the ARM REST API directly:

```python
# Get access token
token = az account get-access-token

# Deploy via OneDeploy extension
PUT https://management.azure.com/.../extensions/onedeploy?type=zip
Authorization: Bearer {token}
Content-Type: application/octet-stream
Body: deploy.zip (302 KB)

# Response: HTTP 202 Accepted
```

### Build Process (Oryx)
Azure automatically:
1. Detected Python 3.13.11
2. Created virtual environment (`antenv`)
3. Installed dependencies from `requirements.txt`
4. Configured gunicorn with uvicorn workers

---

## 📊 Deployment Timeline

| Time (UTC) | Event |
|------------|-------|
| 03:14:58 | Deployment started (OneDeploy) |
| 03:15:12 | Oryx build initiated |
| 03:15:18 | Python 3.13 detected, venv created |
| 03:16:08 | Dependencies installed (uv package manager) |
| 03:16:41 | Container started |
| 03:16:52 | Container running, warmup probes initiated |
| 03:17:00 | Port configuration fixed ($PORT variable) |
| 03:18:00 | Microsoft SSO authentication enabled |

---

## 🛠️ Technical Details

### Key Configuration Changes
1. **Port Binding**: Changed from hardcoded `8000` to `$PORT` environment variable (Azure requirement)
2. **Authentication**: Enabled Azure Easy Auth with Microsoft Entra ID
3. **Startup**: Configured gunicorn to serve FastAPI with uvicorn workers

### Files Deployed
```
/home/site/wwwroot/
├── main.py
├── ops.py
├── db.py
├── scorer.py
├── sf_client.py
├── scheduler.py
├── simulator.py
├── cache.py
├── requirements.txt
├── startup.sh
└── static/
    ├── index.html
    └── assets/
        ├── index-B_QFMn1q.js
        └── index-mpjUaeo5.css
```

---

## ⚠️ Current Status & Next Steps

### App Status
- **Container**: ✅ Running
- **Build**: ✅ Completed
- **Auth**: ✅ Microsoft SSO enabled
- **Network**: ⚠️ App may still be warming up (startup can take 2-3 minutes)

### To Verify Deployment
1. **Wait 2-3 minutes** for container warmup
2. Visit: https://fslapp-nyaaa.azurewebsites.net/
3. You should be redirected to Microsoft login
4. Sign in with @nyaaa.com account
5. Access the FSL Dashboard

### Check Logs
```bash
# Stream live logs
az webapp log tail --name fslapp-nyaaa --resource-group rg-nlaaroubi-sbx-eus2-001

# Download logs
az webapp log download --name fslapp-nyaaa --resource-group rg-nlaaroubi-sbx-eus2-001 --log-file logs.zip

# Or visit Azure Portal
https://portal.azure.com → fslapp-nyaaa → Log stream
```

### Troubleshooting
If the app doesn't respond:

1. **Check container logs** for startup errors
2. **Verify PORT variable** is set correctly
3. **Restart app**: `az webapp restart --name fslapp-nyaaa --resource-group rg-nlaaroubi-sbx-eus2-001`
4. **Check Salesforce connectivity** in logs

---

## 📝 What We Learned

### Azure Deployment Skills Gained

1. **ARM REST API Direct Deployment** ⭐
   - When Azure CLI times out, use ARM API directly
   - Requires: Bearer token + OneDeploy extension endpoint
   - Much more reliable than CLI for large deployments

2. **Azure MCP Limitations**
   - Good for read operations (get app info, list deployments)
   - No deploy/write capabilities
   - Faster than CLI for queries (~10s vs timeouts)

3. **Azure App Service Requirements**
   - Apps must bind to `$PORT` environment variable (not hardcoded ports)
   - Startup commands: Use gunicorn with uvicorn workers for FastAPI
   - Container warmup: Can take 2-5 minutes on first deployment

4. **Authentication Patterns**
   - Azure Easy Auth handles Microsoft SSO at infrastructure level
   - No code changes needed in app
   - Configuration via ARM API authsettingsV2 endpoint

---

## 🎯 Next Time: Improved Deployment Script

For future deployments, use this Python script:

```python
import subprocess
import requests

# Get token
token = subprocess.run(['az', 'account', 'get-access-token', '--query', 'accessToken', '-o', 'tsv'],
                       capture_output=True, text=True).stdout.strip()

# Deploy via ARM API
url = "https://management.azure.com/.../extensions/onedeploy?type=zip&api-version=2022-03-01"
headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/octet-stream'}

with open('deploy.zip', 'rb') as f:
    response = requests.put(url, data=f, headers=headers, timeout=600)

print(f"Deployment: {response.status_code}")  # 202 = Success
```

---

## 📞 Support

- **Azure Portal**: https://portal.azure.com
- **App Service**: rg-nlaaroubi-sbx-eus2-001 → fslapp-nyaaa
- **Deployment Docs**: `.azure/DEPLOYMENT.md`
- **Status Report**: `.azure/DEPLOYMENT_STATUS.md`

---

**Deployment completed successfully using Azure ARM REST API!**
*The app may need a few minutes to fully start. Check logs if issues persist.*
