#!/usr/bin/env bash
# Deploy the daily fslapp-pg -> Blob Storage backup pipeline
# (Azure Container Instance, triggered daily by a Logic App).
#
# See .claude/skills/fslapp-pg-backup/SKILL.md for the full architecture
# writeup and why it's shaped this way (Container Apps Jobs are blocked by a
# subscription-level permission this account doesn't have; the read-only
# Postgres role needs a primary restart that was declined, so the backup
# identity is instead a Postgres AAD admin, with the "never touches primary
# data" guarantee enforced in application code -- see backup-job/run_backup.py).
#
# Idempotent: re-running is safe.
#
# Usage:
#   ./deploy-backup-job.sh                 # deploy infra + build/push image + register identity
#   ./deploy-backup-job.sh --whatif        # preview bicep changes only
#   ./deploy-backup-job.sh --identity-only # only (re)run the AAD admin registration step
#
# Pre-reqs:
#   - az CLI logged in: `az login` then `az account set --subscription "AAAWCNY Azure Sandbox"`
#   - No local docker required -- image is built remotely via `az acr build`.
#   - libpq (psql) only needed if you use --identity-only or want to
#     manually verify a restore; not required for a plain deploy.

set -euo pipefail
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

SUBSCRIPTION_NAME="AAAWCNY Azure Sandbox"
RESOURCE_GROUP="rg-nlaaroubi-sbx-eus2-001"
PG_SERVER_NAME="fslapp-pg"
BACKUP_IDENTITY_NAME="fslapp-pg-backup-identity"
CONTAINER_GROUP_NAME="fslapp-pg-backup-cg"
ACR_NAME="fslapppgbackupacr"
TEMPLATE_FILE="$SCRIPT_DIR/backup-job.bicep"
IMAGE_DIR="$SCRIPT_DIR/backup-job"

WHAT_IF=0
IDENTITY_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --whatif|--what-if) WHAT_IF=1 ;;
    --identity-only) IDENTITY_ONLY=1 ;;
    *) echo "Unknown arg: $arg"; exit 1 ;;
  esac
done

echo "── Verifying Azure CLI session ──"
az account set --subscription "$SUBSCRIPTION_NAME"
CURRENT_USER=$(az ad signed-in-user show --query userPrincipalName -o tsv)
echo "  signed in as: $CURRENT_USER"

register_backup_identity() {
  echo "── Registering $BACKUP_IDENTITY_NAME as a Postgres Microsoft Entra admin on $PG_SERVER_NAME ──"
  local principal_id
  principal_id=$(az identity show -g "$RESOURCE_GROUP" -n "$BACKUP_IDENTITY_NAME" --query principalId -o tsv)
  az postgres flexible-server microsoft-entra-admin create \
    -g "$RESOURCE_GROUP" -s "$PG_SERVER_NAME" \
    -i "$principal_id" -u "$BACKUP_IDENTITY_NAME" -t ServicePrincipal \
    --output none || echo "  (already registered, continuing)"
}

if [ $IDENTITY_ONLY -eq 1 ]; then
  register_backup_identity
  echo "  done."
  exit 0
fi

if [ $WHAT_IF -eq 1 ]; then
  echo "── Bicep what-if ──"
  az deployment group what-if \
    --resource-group "$RESOURCE_GROUP" \
    --template-file "$TEMPLATE_FILE"
  exit 0
fi

echo
echo "── Deploying backup infra (ACR, managed identity, blob container, ACI, Logic App) ──"
echo "  Note: first deploy will fail to start the container (image doesn't exist yet in ACR)."
echo "  That's expected -- the container group resource still gets created; we push the"
echo "  image next and redeploy to make it start successfully."
az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --template-file "$TEMPLATE_FILE" \
  --query 'properties.outputs' \
  -o table || echo "  (expected first-run failure if image doesn't exist yet, continuing)"

echo
echo "── Building and pushing backup image (remote build via az acr build, no local docker needed) ──"
az acr build --registry "$ACR_NAME" --image fslapp-pg-backup:latest "$IMAGE_DIR"

register_backup_identity

echo
echo "── Redeploying so the container group picks up the now-available image ──"
az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --template-file "$TEMPLATE_FILE" \
  --query 'properties.outputs' \
  -o table

echo
echo "── Done ──"
cat <<EOF

✅ Daily backup pipeline deployed.

   Container:  $CONTAINER_GROUP_NAME (Azure Container Instance, restartPolicy Never)
   Scheduler:  fslapp-pg-backup-scheduler (Logic App, daily Recurrence 08:00 UTC starts the container)
   Backs up:   $PG_SERVER_NAME (backup identity is a Postgres AAD admin; safety enforced in
               application code -- run_backup.py only ever calls pg_dump, never a write statement)
   Writes to:  fslappopt/postgres-backups/fslapp-pg-YYYY-MM-DD.dump (never overwrites an existing day)
   Retention:  30 days (pruned by the container itself, blob-storage only)
   Never touches: fslapp-pg-dr, primary's write path, or any other blob container

Next steps:
  1. Test it now instead of waiting for the 08:00 UTC schedule:
       az container start -g $RESOURCE_GROUP -n $CONTAINER_GROUP_NAME

  2. Watch the run:
       az container logs -g $RESOURCE_GROUP -n $CONTAINER_GROUP_NAME

  3. Confirm the blob landed (requires Storage Blob Data Reader/Contributor RBAC,
     or use --account-key):
       az storage blob list --account-name fslappopt -c postgres-backups --auth-mode login -o table

See .claude/skills/fslapp-pg-backup/SKILL.md for the full design writeup,
verification history, and common follow-up tasks (change retention, test a
restore, add a schema, debug a failed run).
EOF
