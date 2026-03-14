# FSLAPP Azure Deployment Guide

## Architecture
- **Combined deployment**: FastAPI serves both API (`/api/*`) and React SPA (all other routes)
- **Azure App Service** (Linux, Python 3.13, B1 tier ~$13/mo)
- **Authentication**: Microsoft Entra ID Easy Auth (SSO with nyaaa.com accounts)
- **No Claude API needed**: App is 100% self-contained (Salesforce data → Python logic → metrics)

## Prerequisites
1. Azure CLI installed: `brew install azure-cli`
2. Logged in: `az login`
3. Node.js installed (for React build)
4. Salesforce credentials in `apidev/.env`

## Quick Deploy (First Time)
```bash
cd FSLAPP

# 1. Deploy app
.azure/deploy.sh fslapp-nyaaa

# 2. Enable SSO (one-time)
.azure/enable-sso.sh fslapp-nyaaa
```

## Redeploy (Code Updates)
```bash
cd FSLAPP

# Rebuild frontend + deploy
.azure/deploy.sh fslapp-nyaaa
```

## Environment Variables (set in Azure Portal or via deploy.sh)
| Variable | Description |
|----------|-------------|
| SF_TOKEN_URL | Salesforce OAuth token endpoint |
| SF_CONSUMER_KEY | Connected App consumer key |
| SF_CONSUMER_SECRET | Connected App consumer secret |
| SF_USERNAME | Salesforce API username |
| SF_PASSWORD | Salesforce API password |
| SF_SECURITY_TOKEN | Salesforce security token |

## How It Works

### Request Flow
```
User → Azure Easy Auth (Microsoft login) → App Service → FastAPI
                                                          ├── /api/* → Python backend (SOQL → Salesforce)
                                                          └── /*     → React SPA (static files)
```

### Authentication Flow
1. User visits `https://fslapp-nyaaa.azurewebsites.net`
2. Azure intercepts → redirects to Microsoft login
3. User signs in with their `@nyaaa.com` account
4. Azure validates token → allows request through to app
5. No code changes needed — all handled at infrastructure level

### Backend Files
| File | Purpose |
|------|---------|
| main.py | FastAPI app, all API routes, serves React SPA |
| ops.py | Daily operations endpoints (live SOQL) |
| scorer.py | Garage scorecard engine (8 weighted dimensions) |
| sf_client.py | Salesforce OAuth + query client |
| db.py | DuckDB local cache for historical data |
| cache.py | In-memory cache with TTL |
| scheduler.py | Scheduling simulation |
| simulator.py | What-if scenario engine |
| startup.sh | Azure startup command (gunicorn + uvicorn) |

## Troubleshooting

### View logs
```bash
az webapp log tail --name fslapp-nyaaa --resource-group rg-nlaaroubi-sbx-eus2-001
```

### SSH into container
```bash
az webapp ssh --name fslapp-nyaaa --resource-group rg-nlaaroubi-sbx-eus2-001
```

### Restart app
```bash
az webapp restart --name fslapp-nyaaa --resource-group rg-nlaaroubi-sbx-eus2-001
```

### Check app settings
```bash
az webapp config appsettings list --name fslapp-nyaaa --resource-group rg-nlaaroubi-sbx-eus2-001 -o table
```

## Costs
- **B1 App Service Plan**: ~$13/month (1 core, 1.75 GB RAM)
- **Entra ID**: Free (included with Microsoft 365)
- **Salesforce API**: No extra cost (uses existing connected app)
- **Claude API**: Not required
