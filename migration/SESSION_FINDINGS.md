# Handoff: FSLAPP-main
**Written**: 2026-06-05T17:01:47Z
**Project path**: /Users/abdennourlaaroubi/Library/CloudStorage/OneDrive-EnProIndustriesInc/AAA/Dev/FSL/FSL/apidev/FSLAPP

## Goal
Perform a full Salesforce Summer '26 (API v67.0, release=262) impact analysis on the AAA WCNY FSL org and FSLAPP codebase. Produce a verified, facts-only consultant report for business admin, FSL admin, and DevOps teams. Also upgrade the SF API version in the FSLAPP backend and generate a PDF action report.

## Current State
- **PDF report created**: `FSLAPP/migration/SF_Summer26_Migration_Report.pdf` — full action report for DevOps team
- **API version upgraded**: `sf_client.py` and 6 other backend files changed from v59/v60 → v65.0 with a centralized `SF_API_VERSION = 'v65.0'` constant. Tested live — 4315 SF calls, 0 errors confirmed.
- **Handoff + findings document** being written now (this file)
- **No code committed yet** — user has not said "push" or "deploy"

## Files Modified This Session

### FSLAPP Backend (API version upgrade)
- `backend/sf_client.py` — Added `SF_API_VERSION = 'v65.0'` constant (line 17); replaced 3× hardcoded `v60.0` with `{SF_API_VERSION}` f-string (lines 218, 253, 268)
- `backend/routers/accounting.py` — Added `SF_API_VERSION` to import (line 6); replaced 1× `v60.0` (line 427)
- `backend/optimizer_sync.py` — Added `SF_API_VERSION` to import (line 12); replaced 2× `v59.0` with f-string references (lines 80, 149)
- `backend/optimizer_blob_sync.py` — Replaced 1× `v59.0` → `v65.0` (line 44, plain string — no sf_client import)
- `backend/optimizer_extractor/discover.py` — Replaced 1× `v59.0` → `v65.0` (line 26)
- `backend/optimizer_extractor/runner.py` — Replaced 1× `v59.0` → `v65.0` (line 55)
- `backend/optimizer_extractor/retrieve.py` — Replaced 2× `v59.0` → `v65.0` (lines 199, 209)

### New Files Created
- `migration/SF_Summer26_Migration_Report.pdf` — Full consultant PDF for DevOps team
- `migration/generate_report.py` — Python script that generates the PDF (uses reportlab)

## What Is Working
- **SF_API_VERSION = 'v65.0'** is live and confirmed: `GET /api/health` returns `salesforce.errors: 0`, `total_calls: 4315`, `breaker_open: false`. SF record URLs in API responses confirm `/services/data/v65.0/` is active.
- **FleetPulse app** running at `localhost:8000`, serving live data from `aaawcny.my.salesforce.com`
- **SF_TOKEN_URL** verified: `https://aaawcny.my.salesforce.com/services/oauth2/token` — My Domain, correct format
- **SAML SSO** verified in live org via SOQL: 2 `SamlSsoConfig` records (`MicrosoftAzure_WCNY`, `Azure_Portal_SSO`) — confirms multi-config SAML framework already active, no migration needed

## What Changed (summary of all edits)
- Centralized SF API version across 7 backend files — single constant to bump in future
- Created `migration/` folder with PDF action report
- Upgraded API version from scattered v59/v60 to v65.0

## What Was Tried That Failed
- **WebFetch for SF release notes** — help.salesforce.com is a JS SPA, WebFetch returns empty. Solution: use Chrome browser extension (`mcp__claude-in-chrome__javascript_tool` with `document.body.innerText`) — this works.
- **`get_page_text` browser tool** — returns "Modal Body..." stub. Only JS extraction works.
- **`FriendlyName`, `SsoType`, `Name` fields on SamlSsoConfig** — these fields don't exist. Use `Id`, `DeveloperName`, `Version`, `Issuer`, `LoginUrl` only.
- **Temp API version bump to v65.0** — user said "stop revert back" when done before workflow completed. Wait for analysis before making code changes — learned to get facts first.

## Open Issues / Known Bugs

### P0 — BREAKS OCTOBER 2026 (Winter '27)
1. **`sf_client.py` OAuth** — `grant_type=password` (lines 169-181) will be rejected by Salesforce. Must migrate to `client_credentials`. Requires SF Admin to enable Client Credentials Flow on FSLAPP Connected App first, then code change, then remove `SF_USERNAME`/`SF_PASSWORD`/`SF_SECURITY_TOKEN` from Azure App Service.

2. **Mulesoft `aaa-wcny-genesys-sf-bulk-papi`** — `salesforce:oauth-user-pass-connection` at `src/main/mule/genSfGlobalConfig.xml:39`. Must migrate to `salesforce:jwt-connection` using `salesforce-ers-sys/src/main/mule/global.xml` lines 33-39 as template.

3. **Mulesoft `aaa-wcny-salesforce-lead-import-app`** — `salesforce:oauth-user-pass-connection` at `src/main/mule/global.xml:17`. Same fix as above.

4. **Mulesoft `aaa-wcny-cx360-papi`** — Active config in `src/main/resources/properties/common-config.properties` lines 191-196 has plaintext `salesforce.auth.password`, `salesforce.auth.username`, `salesforce.auth.securityToken`. Must migrate to `salesforce:oauth-client-credentials-connection`.

### P1 — BREAKS JUNE 2027 (Summer '27)
5. **Mulesoft `ers-transfer-prc` streaming** — 3 `salesforce:subscribe-channel-listener` elements at `src/main/mule/ers-transfer-prc-api.xml` lines 194, 243, 259. Need `<reconnect frequency="5000" count="5" blocking="false"/>` inside the jwt-connection block in `global.xml` lines 15-19.

### Security (Immediate)
6. **Plaintext credentials in Git**:
   - `aaa-wcny-breadfinancial-sf-bulk-papi/src/main/resources/properties/common-config.properties` lines 10-15: `consumerKey`, `consumerSecret`, `password`, `securityToken` in plaintext
   - `aaa-wcny-cx360-papi/src/main/resources/properties/common-config.properties` lines 191-196: `password`, `securityToken`, `consumerSecret` in plaintext
   - Fix: rotate credentials in SF, replace with `${secure::}` references, store in Anypoint Secrets Manager

### Business / Admin (This Week)
7. **Dispatcher tab rename** — "Field Service" → "Classic Dispatch Console". Notify Alger, Hartman, Kalenda, Harrington, Carroll.
8. **Integration user profile permission** — `apiintegration@nyaaa.com` needs "View All Profiles" system permission enabled.

## What To Do Next

1. **Commit the API version upgrade** (when user says "push"): `git add backend/sf_client.py backend/routers/accounting.py backend/optimizer_sync.py backend/optimizer_blob_sync.py backend/optimizer_extractor/` + `git commit`

2. **OAuth migration for FleetPulse (T1)**: SF Admin enables Client Credentials on Connected App → Developer updates `sf_client.py` lines 169-181 → Azure Admin removes 3 env vars → test with `curl localhost:8000/api/health`

3. **Mulesoft OAuth audits (T2, T3, T4)**: Mulesoft developer opens each project in Anypoint Studio, replaces `oauth-user-pass-connection` with JWT pattern from `salesforce-ers-sys`

4. **Rotate plaintext credentials (S1)**: SF Admin resets Connected App secrets + user passwords, developer replaces with `${secure::}` references

5. **Dispatcher communication (B1)**: FSL Admin emails 5 dispatchers

6. **View All Profiles (B2)**: SF Admin grants permission to `apiintegration@nyaaa.com`

## Key Context / Gotchas

### Org & Authentication
- **SF org**: `aaawcny.my.salesforce.com` (production, always live data)
- **Integration user**: `apiintegration@nyaaa.com` (FleetPulse), `mulesoftintegration@nyaaa.com` (Mulesoft CX360)
- **SF_TOKEN_URL**: `https://aaawcny.my.salesforce.com/services/oauth2/token` (My Domain — already correct)
- **SAML**: 2 configs (`MicrosoftAzure_WCNY`, `Azure_Portal_SSO`), both on SAML 2.0 via Azure AD — already on multi-config framework, no migration needed
- **deploy**: ONLY via `git push` — NEVER `az webapp up`. User will say "push" or "deploy" explicitly.

### Mulesoft Auth Summary (verified from code)
| Project | Auth Type | Status |
|---------|-----------|--------|
| salesforce-ers-sys | JWT Bearer | ✅ Safe |
| ers-transfer-prc | JWT Bearer | ✅ Safe (streaming reconnect needed) |
| aaa-wcny-genesys-sf-bulk-papi | oauth-user-pass-connection | ⚠️ Breaks Oct 2026 |
| aaa-wcny-salesforce-lead-import-app | oauth-user-pass-connection | ⚠️ Breaks Oct 2026 |
| aaa-wcny-cx360-papi | HTTP password flow | ⚠️ Breaks Oct 2026 |
| aaa-wcny-breadfinancial-sf-bulk-papi | username-password (sandbox only?) | ⚠️ Verify if prod |

### SF API Version
- `sf_client.py`: now v65.0 (was v60.0) — centralized as `SF_API_VERSION = 'v65.0'` at line 17
- `optimizer_extractor/` files: v65.0 as plain string (no sf_client import — standalone CLI tools)
- `sfdx-project.json`: sourceApiVersion = 65.0 (unchanged, matches now)
- Summer '26 = v67.0. v65.0 is NOT being retired — safe. v31-40 are the ones being retired.
- Do NOT upgrade to v67.0 until `WITH SECURITY_ENFORCED` audit is done (will cause compile failure)

### FSL Business Configs — All Safe
No FSL scheduling policies, work rules, service objectives, operating hours, optimizer schedules, resource absences, skills, or territories are affected by Summer '26. All FSL changes are opt-in additions.

### Browser Automation
- Chrome extension tools require `mcp__claude-in-chrome__*` — ToolSearch before first use
- `get_page_text` returns "Modal Body..." for SF help pages — use `javascript_tool` with `document.body.innerText` instead
- SF Help is a JS SPA — always `sleep 4` after `navigate` before reading
- Tab IDs reset each session — always call `tabs_context_mcp` first

### Release Notes URLs (Summer '26 = release=262)
- Release Updates: `https://help.salesforce.com/s/articleView?id=release-notes.rn_ru.htm&release=262&type=5`
- Field Service: `https://help.salesforce.com/s/articleView?id=release-notes.rn_fieldservice.htm&release=262&type=5`
- Development: `https://help.salesforce.com/s/articleView?id=release-notes.rn_development.htm&release=262&type=5`
- Automation: `https://help.salesforce.com/s/articleView?id=release-notes.rn_automate.htm&release=262&type=5`
- Security: `https://help.salesforce.com/s/articleView?id=release-notes.rn_security.htm&release=262&type=5`

### Mulesoft Project Paths
All at: `/Users/abdennourlaaroubi/Library/CloudStorage/OneDrive-EnProIndustriesInc/AAA/Dev/Muesoft/`
JWT template to copy: `salesforce-ers-sys/src/main/mule/global.xml` lines 33-39

## Commands To Know

```bash
# Verify FleetPulse SF connection
curl http://localhost:8000/api/health

# Check SF API version currently in use
grep -n "SF_API_VERSION\|v[0-9][0-9]\.0" FSLAPP/backend/sf_client.py

# Find all remaining hardcoded SF API version strings
grep -rn "v[0-9][0-9]\.0" FSLAPP/backend/ --include="*.py"

# Run PDF generator
cd FSLAPP/migration && python3 generate_report.py

# Scan Mulesoft for OAuth flow types
grep -rn "oauth-user-pass\|jwt-connection\|client-credentials\|grant_type" \
  /AAA/Dev/Muesoft/ --include="*.xml" | grep -v test

# Check SAML SSO config in live org (via SF MCP tool)
# sf_soql: SELECT Id, DeveloperName, Version, Issuer FROM SamlSsoConfig

# Verify integration user profile permission
# sf_soql: SELECT Id, Profile.Name, UserType FROM User WHERE Username = 'apiintegration@nyaaa.com'
```
