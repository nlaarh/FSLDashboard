# FSLAPP — Azure Infrastructure Reference

## App Service

**Resource:** `fslapp-nyaaa` (App Service, East US 2)
**Resource Group:** `rg-nlaaroubi-sbx-eus2-001`
**Subscription:** `e287db16-b6ae-415e-bd52-41c8ec5a8f08`
**URL:** https://fslapp-nyaaa.azurewebsites.net

---

## Key Azure Portal Links

### App Service Overview (restart here)
https://portal.azure.com/#@nyaaa.com/resource/subscriptions/e287db16-b6ae-415e-bd52-41c8ec5a8f08/resourceGroups/rg-nlaaroubi-sbx-eus2-001/providers/Microsoft.Web/sites/fslapp-nyaaa/appServices

> **Restart:** Click the **Restart** button in the top toolbar.

### Environment Variables (API keys, connection strings)
https://portal.azure.com/#@nyaaa.com/resource/subscriptions/e287db16-b6ae-415e-bd52-41c8ec5a8f08/resourceGroups/rg-nlaaroubi-sbx-eus2-001/providers/Microsoft.Web/sites/fslapp-nyaaa/environmentVariablesAppSettings

> **To update a key:** Click the variable → edit value → **Apply** → **Confirm** → app restarts automatically.

---

## Key Environment Variables

| Variable | Purpose |
|---|---|
| `SF_USERNAME` | Salesforce connected app username |
| `SF_PASSWORD` | Salesforce password + security token |
| `SF_CLIENT_ID` | Salesforce OAuth client ID |
| `SF_CLIENT_SECRET` | Salesforce OAuth client secret |
| `AUTH_SECRET` | HMAC secret for session cookie signing |
| `ADMIN_PIN` | 6-digit PIN for the `/admin` panel |
| `FSLAPP_PG_HOST` | Azure PostgreSQL server hostname |
| `FSLAPP_PG_DATABASE` | PostgreSQL database name (`fslapp`) |
| `FSLAPP_PG_USER` | PostgreSQL Entra user (nlaaroubi@nyaaa.com) |
| `AZURE_STORAGE_CONNECTION_STRING` | Blob storage for DB backups |

---

## Support Lead Access

To grant a support lead the ability to restart the app and update env variables:

1. Go to the App Service resource (link above)
2. Left sidebar → **Access control (IAM)** → **Add role assignment**
3. Role: **Contributor** (scoped to this App Service only)
4. Assign to the support lead's Azure AD account

This gives them restart + env var access without touching anything else in the subscription.

---

## Deployment

Deployment is triggered automatically by pushing to the `main` branch on GitHub.
GitHub Actions builds the frontend, copies to `backend/static/`, and deploys to Azure.

See `DEPLOY_INSTRUCTIONS.md` for manual deployment steps.
