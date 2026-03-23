#!/bin/bash
# FSLAPP Azure Deployment Script
# Usage: .azure/deploy.sh [app-name]
#
# Prerequisites:
#   - Azure CLI installed (brew install azure-cli)
#   - Logged in (az login)
#   - Subscription set (az account set -s "AAAWCNY Azure Sandbox")

set -e

APP_NAME="${1:-fslapp-nyaaa}"
RG="rg-nlaaroubi-sbx-eus2-001"
LOCATION="canadacentral"
PLAN_NAME="AABC"
SKU="B1"
RUNTIME="PYTHON:3.13"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"

echo "=== FSLAPP Azure Deployment ==="
echo "  App:      $APP_NAME.azurewebsites.net"
echo "  RG:       $RG"
echo "  Location: $LOCATION"
echo ""

# Step 1: Build React frontend
echo "[1/6] Building React frontend..."
cd "$FRONTEND_DIR"
npm run build
rm -rf "$BACKEND_DIR/static"
cp -r dist "$BACKEND_DIR/static"
echo "  React build copied to backend/static/"

# Step 2: Create App Service Plan (if not exists)
echo "[2/6] Creating App Service Plan..."
az appservice plan create \
  --name "$PLAN_NAME" \
  --resource-group "$RG" \
  --location "$LOCATION" \
  --sku "$SKU" \
  --is-linux \
  --output none 2>/dev/null || true
echo "  Plan: $PLAN_NAME ($SKU)"

# Step 3: Create Web App (if not exists)
echo "[3/6] Creating Web App..."
az webapp create \
  --name "$APP_NAME" \
  --resource-group "$RG" \
  --plan "$PLAN_NAME" \
  --runtime "$RUNTIME" \
  --output none 2>/dev/null || true
echo "  Web App: $APP_NAME"

# Step 4: Configure app settings (Salesforce credentials)
echo "[4/6] Configuring app settings..."
# IMPORTANT: Use grep -m1 to match ONLY the first (active) line, not commented-out UAT lines.
# The .env file has both PROD and UAT credentials — without -m1, grep returns both
# and creates multi-line values that break SF auth. (Lesson learned: March 23, 2026 outage)
ENV_FILE="$PROJECT_DIR/../.env"
if [ -f "$ENV_FILE" ]; then
  az webapp config appsettings set \
    --name "$APP_NAME" \
    --resource-group "$RG" \
    --settings \
      SF_TOKEN_URL="$(grep -m1 '^SF_TOKEN_URL=' "$ENV_FILE" | cut -d= -f2-)" \
      SF_CONSUMER_KEY="$(grep -m1 '^SF_CONSUMER_KEY=' "$ENV_FILE" | cut -d= -f2-)" \
      SF_CONSUMER_SECRET="$(grep -m1 '^SF_CONSUMER_SECRET=' "$ENV_FILE" | cut -d= -f2-)" \
      SF_USERNAME="$(grep -m1 '^SF_USERNAME=' "$ENV_FILE" | cut -d= -f2-)" \
      SF_PASSWORD="$(grep -m1 '^SF_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)" \
      SF_SECURITY_TOKEN="$(grep -m1 '^SF_SECURITY_TOKEN=' "$ENV_FILE" | cut -d= -f2-)" \
      SCM_DO_BUILD_DURING_DEPLOYMENT=true \
    --output none
  echo "  Salesforce credentials configured from .env"
else
  echo "  WARNING: .env file not found at $ENV_FILE"
  echo "  You must set SF_* app settings manually in Azure Portal"
fi

# Step 5: Set startup command
echo "[5/6] Setting startup command..."
az webapp config set \
  --name "$APP_NAME" \
  --resource-group "$RG" \
  --startup-file "gunicorn main:app --workers 2 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --timeout 120" \
  --output none

# Step 6: Deploy backend (with static files)
echo "[6/6] Deploying to Azure..."
cd "$BACKEND_DIR"
az webapp up \
  --name "$APP_NAME" \
  --resource-group "$RG" \
  --runtime "$RUNTIME" \
  --sku "$SKU"

# Step 7: Warm cache so first user never waits
echo "[7/7] Warming cache..."
APP_URL="https://$APP_NAME.azurewebsites.net"
# Wait for app to be ready
for i in $(seq 1 30); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$APP_URL/api/health" 2>/dev/null)
  if [ "$STATUS" = "200" ]; then
    break
  fi
  echo "  Waiting for app to start ($i/30)..."
  sleep 5
done
# Trigger synchronous warmup of all cache keys
WARMUP=$(curl -s -X POST "$APP_URL/api/warmup" 2>/dev/null)
echo "  Cache warmup: $WARMUP"

echo ""
echo "=== Deployment Complete ==="
echo "  URL: $APP_URL"
echo "  Cache is warm — first user gets instant data."
echo ""
echo "  Next: Enable SSO authentication"
echo "  Run:  .azure/enable-sso.sh $APP_NAME"
