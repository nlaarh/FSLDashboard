#!/bin/bash
# Enable Microsoft Entra ID SSO (Easy Auth) on FSLAPP
# Usage: .azure/enable-sso.sh [app-name]
#
# This locks the app behind your nyaaa.com Microsoft login.
# Only users in your AAA tenant can access the app.

set -e

APP_NAME="${1:-fslapp-nyaaa}"
RG="rg-nlaaroubi-sbx-eus2-001"
TENANT_ID="87c1e7cf-b6c4-434f-b18e-5444b1bce3bb"

echo "=== Enabling Microsoft SSO ==="
echo "  App:    $APP_NAME"
echo "  Tenant: AAA Western and Central New York"
echo ""

# Step 1: Register app in Entra ID
echo "[1/3] Registering app in Entra ID..."
APP_REG=$(az ad app create \
  --display-name "FSLAPP" \
  --sign-in-audience "AzureADMyOrg" \
  --web-redirect-uris "https://$APP_NAME.azurewebsites.net/.auth/login/aad/callback" \
  --query "{appId:appId, objectId:id}" \
  -o json)

CLIENT_ID=$(echo "$APP_REG" | python3 -c "import sys,json; print(json.load(sys.stdin)['appId'])")
echo "  Client ID: $CLIENT_ID"

# Step 2: Create client secret
echo "[2/3] Creating client secret..."
SECRET=$(az ad app credential reset \
  --id "$CLIENT_ID" \
  --display-name "fslapp-secret" \
  --query "password" -o tsv)
echo "  Secret created"

# Step 3: Enable Easy Auth on the web app
echo "[3/3] Enabling Easy Auth..."
az webapp auth microsoft update \
  --name "$APP_NAME" \
  --resource-group "$RG" \
  --client-id "$CLIENT_ID" \
  --client-secret "$SECRET" \
  --issuer "https://login.microsoftonline.com/$TENANT_ID/v2.0" \
  --yes \
  --output none

az webapp auth update \
  --name "$APP_NAME" \
  --resource-group "$RG" \
  --enabled true \
  --action LoginWithAzureActiveDirectory \
  --output none

echo ""
echo "=== SSO Enabled ==="
echo "  URL: https://$APP_NAME.azurewebsites.net"
echo "  Auth: Microsoft login required (nyaaa.com tenant only)"
echo "  Client ID: $CLIENT_ID"
echo ""
echo "  To disable: az webapp auth update --name $APP_NAME --resource-group $RG --enabled false"
