#!/usr/bin/env bash
# Quick check: did today's fslapp-pg backup blob land in postgres-backups?
# Read-only. Uses the storage account key (fetched via management-plane,
# already have Owner on this resource group) purely to check blob existence
# -- no new Azure role assignments, no writes anywhere.
#
# Usage: ./verify-backup.sh
# Exit code 0 = backup found for today, 1 = missing.

set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"

RESOURCE_GROUP="rg-nlaaroubi-sbx-eus2-001"
STORAGE_ACCOUNT="fslappopt"
CONTAINER="postgres-backups"
TODAY=$(date -u +%F)
BLOB_NAME="fslapp-pg-${TODAY}.dump"

ACCOUNT_KEY=$(az storage account keys list --account-name "$STORAGE_ACCOUNT" -g "$RESOURCE_GROUP" --query "[0].value" -o tsv)

EXISTS=$(az storage blob exists \
  --account-name "$STORAGE_ACCOUNT" \
  --account-key "$ACCOUNT_KEY" \
  -c "$CONTAINER" -n "$BLOB_NAME" \
  --query exists -o tsv)

if [ "$EXISTS" = "true" ]; then
  echo "OK: $BLOB_NAME found."
  exit 0
else
  echo "MISSING: $BLOB_NAME not found in $CONTAINER -- today's backup did not complete."
  exit 1
fi
