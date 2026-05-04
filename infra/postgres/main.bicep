// FSLAPP Postgres Flexible Server — single shared DB for all FSLAPP features.
//
// Phase 1 hosts the optimizer schema (replaces DuckDB). Future phases add
// schemas for accounting, core/users, ops, and pgvector RAG.
//
// Auth: Microsoft Entra ID only — no admin password, no shared secrets.
// Network: public access + firewall (Mac local IP + AllowAllAzureServices).
// Storage: 64 GB Premium SSD v2 with auto-grow.
//
// Deploy:
//   az login
//   az deployment group create \
//     --resource-group rg-nlaaroubi-sbx-eus2-001 \
//     --template-file main.bicep \
//     --parameters @main.parameters.json

@description('Postgres server name (lowercase, dashes only). Becomes <name>.postgres.database.azure.com')
param serverName string = 'fslapp-pg'

@description('Region. eastus2 chosen for US data residency (AAA member data). fslapp-nyaaa App Service is in Canada Central — accept ~30ms cross-region latency until App Service is migrated to US.')
param location string = 'eastus2'

@description('Postgres major version. 16 has best pgvector + extension story.')
param postgresVersion string = '16'

@description('Compute SKU. B2s = 2 vCore burstable, 4 GB RAM, ~$24.82/mo. B2ms = 4 GB → 8 GB, $49/mo for backfill bursts.')
@allowed(['Standard_B1ms','Standard_B2s','Standard_B2ms','Standard_D2ds_v5','Standard_D4ds_v5'])
param skuName string = 'Standard_B2s'

@description('Storage size in GB. Premium SSD v2 (3000 IOPS by default). 64 GB at $0.090/GB = ~$5.76/mo.')
param storageSizeGB int = 64

@description('Backup retention in days. 7 = free tier. 14/30 cost extra.')
@minValue(7)
@maxValue(35)
param backupRetentionDays int = 7

@description('Microsoft Entra admin object ID — the user who can grant other AAD principals access. Get with: az ad signed-in-user show --query id -o tsv')
param aadAdminObjectId string

@description('Microsoft Entra admin display name (UPN preferred).')
param aadAdminPrincipalName string

@description('Microsoft Entra admin principal type.')
@allowed(['User','ServicePrincipal','Group'])
param aadAdminPrincipalType string = 'User'

@description('Allow connections from any public IP. Security boundary is Microsoft Entra ID auth + TLS, not IP filtering. Set to a /32 (e.g. 74.77.8.242) to lock down later.')
param devFirewallStartIp string = '0.0.0.0'

@description('End of dev firewall range. Keep at 255.255.255.255 with start=0.0.0.0 to allow any public IP, OR set to the same /32 as devFirewallStartIp for a single-host lockdown.')
param devFirewallEndIp string = '255.255.255.255'

@description('Tags applied to all resources for cost tracking.')
param tags object = {
  app: 'fslapp'
  env: 'sandbox'
  owner: 'nlaaroubi'
  costCenter: 'data-platform'
}

// ── Postgres Flexible Server ───────────────────────────────────────────────
resource pg 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: serverName
  location: location
  tags: tags
  sku: {
    name: skuName
    tier: startsWith(skuName, 'Standard_B') ? 'Burstable' : 'GeneralPurpose'
  }
  properties: {
    version: postgresVersion
    storage: {
      storageSizeGB: storageSizeGB
      autoGrow: 'Enabled'
      type: 'Premium_LRS'    // Premium SSD v1: zone-agnostic, fixed tier (Azure infers from size)
                             // 64 GB → P6 (~$8.69/mo, 240 IOPS, 50 MB/s — plenty for our load)
    }
    backup: {
      backupRetentionDays: backupRetentionDays
      geoRedundantBackup: 'Disabled'   // sandbox; flip to Enabled for prod ($extra)
    }
    highAvailability: {
      mode: 'Disabled'                  // sandbox; flip to ZoneRedundant for prod
    }
    network: {
      publicNetworkAccess: 'Enabled'    // Phase 1: public + firewall + Entra auth
    }
    authConfig: {
      activeDirectoryAuth: 'Enabled'
      passwordAuth: 'Disabled'           // Entra ID ONLY — no admin password ever exists
      tenantId: subscription().tenantId
    }
  }
}

// ── Server-level config ────────────────────────────────────────────────────
// Whitelist required extensions. azure_pg_admin role auto-granted to AAD admin.
resource pgConfigExtensions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: pg
  name: 'azure.extensions'
  properties: {
    value: 'VECTOR,PG_TRGM,PG_STAT_STATEMENTS,UUID-OSSP,BTREE_GIN'
    source: 'user-override'
  }
}

resource pgConfigSslMode 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: pg
  name: 'require_secure_transport'
  properties: {
    value: 'on'
    source: 'user-override'
  }
}

resource pgConfigStatementTimeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: pg
  name: 'statement_timeout'
  properties: {
    value: '30000'   // 30s — caps runaway queries
    source: 'user-override'
  }
}

resource pgConfigIdleTimeout 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: pg
  name: 'idle_in_transaction_session_timeout'
  properties: {
    value: '60000'   // 60s — frees connections held by crashed clients
    source: 'user-override'
  }
}

// ── Microsoft Entra ID admin (the only way to log in) ─────────────────────
resource pgAadAdmin 'Microsoft.DBforPostgreSQL/flexibleServers/administrators@2024-08-01' = {
  parent: pg
  name: aadAdminObjectId
  properties: {
    principalName: aadAdminPrincipalName
    principalType: aadAdminPrincipalType
    tenantId: subscription().tenantId
  }
}

// ── Firewall ───────────────────────────────────────────────────────────────
// Rule 1: Dev access. Default 0.0.0.0–255.255.255.255 (any public IP).
// Security boundary is Microsoft Entra ID auth + TLS, NOT this firewall.
// Tighten to a single /32 (set start==end) when locking down for prod.
resource pgFirewallDev 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: pg
  name: 'dev-access-entra-auth-required'
  properties: {
    startIpAddress: devFirewallStartIp
    endIpAddress: devFirewallEndIp
  }
}

// Rule 2: Allow ANY Azure resource (covers fslapp-nyaaa's 31 outbound IPs without enumerating).
// Security comes from Entra-only auth — non-authorized Azure resources cannot authenticate.
// "0.0.0.0" is the magic IP that means "AllowAllAzureServicesAndResourcesWithinAzureIps".
resource pgFirewallAzureServices 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: pg
  name: 'AllowAllAzureServicesAndResourcesWithinAzureIps'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

// ── Database ───────────────────────────────────────────────────────────────
// Single shared `fslapp` database. Schemas (optimizer, core, accounting, …)
// are created in init-schema.sql post-deployment.
resource pgDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: pg
  name: 'fslapp'
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

// ── Outputs (for the deploy.sh wrapper to consume) ─────────────────────────
output serverFqdn string = pg.properties.fullyQualifiedDomainName
output serverName string = pg.name
output databaseName string = pgDatabase.name
output region string = location
output sku string = skuName
output storageGB int = storageSizeGB
output connectionStringTemplate string = 'host=${pg.properties.fullyQualifiedDomainName} dbname=fslapp sslmode=require'
