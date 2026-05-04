#!/usr/bin/env bash
# Deploy FSLAPP Postgres Flexible Server.
#
# Idempotent: re-running is safe. The Bicep is declarative — Azure diffs and
# applies only what changed.
#
# Usage:
#   ./deploy.sh              # deploy
#   ./deploy.sh --whatif     # preview changes without applying
#   ./deploy.sh --post-only  # skip ARM deploy, run only post-config (managed identity, schema init)
#
# Pre-reqs:
#   - az CLI logged in: `az login` then `az account set --subscription "AAAWCNY Azure Sandbox"`
#   - bicep installed (auto-installed by az on first use)
#   - psql installed locally for init-schema.sql

set -euo pipefail
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# ─── Config ─────────────────────────────────────────────────────────────────
SUBSCRIPTION_NAME="AAAWCNY Azure Sandbox"
RESOURCE_GROUP="rg-nlaaroubi-sbx-eus2-001"
SERVER_NAME="fslapp-pg"
DATABASE_NAME="fslapp"
APP_SERVICE_NAME="fslapp-nyaaa"
PARAMS_FILE="$SCRIPT_DIR/main.parameters.json"
TEMPLATE_FILE="$SCRIPT_DIR/main.bicep"
SCHEMA_INIT_FILE="$SCRIPT_DIR/init-schema.sql"

WHAT_IF=0
POST_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --whatif|--what-if) WHAT_IF=1 ;;
    --post-only) POST_ONLY=1 ;;
    *) echo "Unknown arg: $arg"; exit 1 ;;
  esac
done

# ─── Sanity ─────────────────────────────────────────────────────────────────
echo "── Verifying Azure CLI session ──"
az account set --subscription "$SUBSCRIPTION_NAME"
CURRENT_SUB=$(az account show --query name -o tsv)
echo "  subscription: $CURRENT_SUB"
CURRENT_USER=$(az ad signed-in-user show --query userPrincipalName -o tsv)
CURRENT_OBJECTID=$(az ad signed-in-user show --query id -o tsv)
echo "  signed in as: $CURRENT_USER ($CURRENT_OBJECTID)"

# Inject signed-in user's objectId into parameters file (avoids hand-editing JSON)
TMP_PARAMS=$(mktemp)
trap 'rm -f $TMP_PARAMS' EXIT
jq --arg oid "$CURRENT_OBJECTID" --arg upn "$CURRENT_USER" \
   '.parameters.aadAdminObjectId.value = $oid
    | .parameters.aadAdminPrincipalName.value = $upn' \
   "$PARAMS_FILE" > "$TMP_PARAMS"

FW_START=$(jq -r '.parameters.devFirewallStartIp.value' "$TMP_PARAMS")
FW_END=$(jq -r '.parameters.devFirewallEndIp.value' "$TMP_PARAMS")
DETECTED_IP=$(curl -s --max-time 5 https://ifconfig.me)
echo "  firewall range:    $FW_START → $FW_END"
echo "  current public IP: $DETECTED_IP"
if [ "$FW_START" = "0.0.0.0" ] && [ "$FW_END" = "255.255.255.255" ]; then
  echo "  ℹ️  Open firewall — security via Entra-only auth + TLS. Travel-friendly."
fi

# ─── ARM deploy ─────────────────────────────────────────────────────────────
if [ $POST_ONLY -eq 0 ]; then
  echo
  echo "── Deploying Postgres Flexible Server (Bicep) ──"
  if [ $WHAT_IF -eq 1 ]; then
    az deployment group what-if \
      --resource-group "$RESOURCE_GROUP" \
      --template-file "$TEMPLATE_FILE" \
      --parameters "@$TMP_PARAMS"
    echo "  what-if complete; no resources changed."
    exit 0
  fi

  az deployment group create \
    --resource-group "$RESOURCE_GROUP" \
    --template-file "$TEMPLATE_FILE" \
    --parameters "@$TMP_PARAMS" \
    --query 'properties.outputs' \
    -o table

  SERVER_FQDN=$(az postgres flexible-server show \
    -g "$RESOURCE_GROUP" -n "$SERVER_NAME" \
    --query fullyQualifiedDomainName -o tsv)
  echo "  server FQDN: $SERVER_FQDN"
fi

# ─── Post-config ────────────────────────────────────────────────────────────
echo
echo "── Enabling system-assigned managed identity on $APP_SERVICE_NAME ──"
APP_IDENTITY_PRINCIPAL_ID=$(az webapp identity assign \
  -g "$RESOURCE_GROUP" -n "$APP_SERVICE_NAME" \
  --query principalId -o tsv)
echo "  managed identity principalId: $APP_IDENTITY_PRINCIPAL_ID"

echo
echo "── Granting App Service managed identity access to Postgres (Entra) ──"
# Add the App Service managed identity as an Entra admin on the Postgres server.
# This is the only way to authorize a non-user principal for AAD auth on PG Flex.
az postgres flexible-server ad-admin create \
  -g "$RESOURCE_GROUP" -s "$SERVER_NAME" \
  -i "$APP_IDENTITY_PRINCIPAL_ID" \
  -u "$APP_SERVICE_NAME" \
  -t ServicePrincipal \
  --output none || echo "  (already exists, continuing)"

echo
echo "── Initializing schemas (optimizer, core, accounting, …) ──"
SERVER_FQDN="${SERVER_NAME}.postgres.database.azure.com"
PGUSER="$CURRENT_USER"
PGPASSWORD=$(az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv)
echo "  connecting as: $PGUSER (Entra token, valid 60 min)"
PGPASSWORD="$PGPASSWORD" psql \
  "host=$SERVER_FQDN dbname=$DATABASE_NAME user=$PGUSER sslmode=require" \
  -v ON_ERROR_STOP=1 \
  -f "$SCHEMA_INIT_FILE"

echo
echo "── Set App Service config so the backend knows where to connect ──"
az webapp config appsettings set \
  -g "$RESOURCE_GROUP" -n "$APP_SERVICE_NAME" \
  --settings \
    FSLAPP_PG_HOST="$SERVER_FQDN" \
    FSLAPP_PG_DATABASE="$DATABASE_NAME" \
    FSLAPP_PG_USER="$APP_SERVICE_NAME" \
    FSLAPP_PG_AUTH=entra \
    OPT_DB_BACKEND=postgres \
  --output none
echo "  app settings written. Backend will read FSLAPP_PG_HOST on next restart."

echo
echo "── Done ──"
cat <<EOF

✅ Postgres Flexible Server deployed.

   Server:   $SERVER_FQDN
   Database: $DATABASE_NAME
   Auth:     Entra ID (no passwords)
   Backup:   7-day PITR
   Firewall: $FW_START → $FW_END (any public IP) + AllowAllAzureServices
             Security boundary: Entra-only auth + TLS

Next steps:
  1. Test local connection:
       export PGPASSWORD=\$(az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv)
       psql "host=$SERVER_FQDN dbname=$DATABASE_NAME user=$CURRENT_USER sslmode=require"

  2. Run the optimizer ETL when ready:
       python -m migrations.duckdb_to_postgres   # (TBD — separate script)

  3. App Service does not auto-restart. To pick up the new env vars:
       az webapp restart -g $RESOURCE_GROUP -n $APP_SERVICE_NAME

EOF
