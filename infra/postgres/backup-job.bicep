// Daily fslapp-pg -> Blob Storage backup, run entirely inside Azure.
//
// Read-only against primary Postgres (fslapp-pg): the backup container's
// managed identity is granted a SELECT-only Postgres role (see
// backup-role.sql), and its Azure RBAC role assignment is scoped to only the
// postgres-backups blob container (never account-wide, never fslapp-pg-dr).
// It never deletes anything except its own backup blobs older than
// backupRetentionDays.
//
// Architecture: Azure Container Apps Jobs need the Microsoft.App resource
// provider, which requires subscription-level (not resource-group-level)
// permission to register -- not available on this account. Instead:
//   - Azure Container Instance (ACI), restartPolicy 'Never', runs the actual
//     pg_dump + upload + prune logic once per invocation, then stops.
//   - A Logic App (Consumption) with a Recurrence trigger calls the ACI
//     "start" REST API daily to kick off a fresh run. The Logic App's
//     managed identity is granted ONLY the "Container Instances Contributor"
//     role, scoped to this one container group -- it cannot touch anything
//     else, including Postgres or any other storage.
//
// Deploy: see deploy-backup-job.sh

@description('Region. Same as fslapp-pg for lowest latency.')
param location string = 'eastus2'

@description('Existing Postgres server name to back up.')
param pgServerName string = 'fslapp-pg'

@description('Existing storage account name (same one used for optimizer files).')
param storageAccountName string = 'fslappopt'

@description('New blob container name dedicated to Postgres backups.')
param backupContainerName string = 'postgres-backups'

@description('Days to retain daily backups before the job prunes them.')
param backupRetentionDays int = 7

@description('Daily recurrence hour (UTC) for the Logic App trigger.')
param scheduleHourUtc int = 8

@description('Anchor date for the recurrence schedule (deploy-time default; only the date part is used to seed the daily interval).')
param scheduleStartDate string = utcNow('yyyy-MM-dd')

@description('Tags applied to all resources for cost tracking.')
param tags object = {
  app: 'fslapp'
  env: 'sandbox'
  owner: 'nlaaroubi'
  costCenter: 'data-platform'
  purpose: 'pg-backup'
}

var acrName = 'fslapppgbackupacr'
var identityName = 'fslapp-pg-backup-identity'
var containerGroupName = 'fslapp-pg-backup-cg'
var logicAppName = 'fslapp-pg-backup-scheduler'
var aciApiVersion = '2023-05-01'

// ── Container registry to host the backup image ────────────────────────────
resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: acrName
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false // pull via managed identity only
  }
}

// ── User-assigned managed identity for the backup container itself ────────
// Read-only Postgres role (backup-role.sql) + write access scoped to only
// the postgres-backups blob container. This identity has no other access.
resource backupIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: location
  tags: tags
}

resource acrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, backupIdentity.id, 'AcrPull')
  scope: acr
  properties: {
    principalId: backupIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d') // AcrPull
  }
}

// ── Existing storage account + new backups-only container ────────────────
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: storageAccountName
}

resource blobServices 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' existing = {
  parent: storageAccount
  name: 'default'
}

resource backupContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobServices
  name: backupContainerName
  properties: {
    publicAccess: 'None'
  }
}

// Scope this role assignment to ONLY the postgres-backups container -- not
// account-wide -- so this identity cannot touch optimizer-files or anything
// else in the storage account.
resource blobDataContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(backupContainer.id, backupIdentity.id, 'StorageBlobDataContributor')
  scope: backupContainer
  properties: {
    principalId: backupIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe') // Storage Blob Data Contributor
  }
}

// ── Container Instance: does the actual pg_dump + upload + prune ─────────
// restartPolicy 'Never' means it runs once to completion and stops -- the
// Logic App below just restarts it once a day; it is not a long-running
// service and has no inbound network exposure.
resource backupContainerGroup 'Microsoft.ContainerInstance/containerGroups@2023-05-01' = {
  name: containerGroupName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${backupIdentity.id}': {}
    }
  }
  properties: {
    osType: 'Linux'
    restartPolicy: 'Never'
    imageRegistryCredentials: [
      {
        server: '${acrName}.azurecr.io'
        identity: backupIdentity.id
      }
    ]
    containers: [
      {
        name: 'pg-backup'
        properties: {
          image: '${acrName}.azurecr.io/fslapp-pg-backup:latest'
          resources: {
            requests: {
              cpu: 1
              memoryInGB: 1
            }
          }
          environmentVariables: [
            { name: 'FSLAPP_PG_HOST', value: '${pgServerName}.postgres.database.azure.com' }
            { name: 'FSLAPP_PG_DATABASE', value: 'fslapp' }
            { name: 'FSLAPP_PG_BACKUP_ROLE', value: identityName }
            { name: 'BACKUP_STORAGE_ACCOUNT', value: storageAccountName }
            { name: 'BACKUP_CONTAINER', value: backupContainerName }
            { name: 'BACKUP_RETENTION_DAYS', value: string(backupRetentionDays) }
            { name: 'AZURE_CLIENT_ID', value: backupIdentity.properties.clientId }
          ]
        }
      }
    ]
  }
  dependsOn: [
    acrPullRole
    blobDataContributorRole
  ]
}

// ── Logic App: daily timer that only starts the one container group ──────
// Managed identity scoped to "Container Instances Contributor" on THIS
// container group ONLY -- it cannot start/stop/read anything else in the
// subscription, including Postgres, other storage, or other containers.
resource schedulerLogicApp 'Microsoft.Logic/workflows@2019-05-01' = {
  name: logicAppName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    state: 'Enabled'
    definition: {
      '$schema': 'https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#'
      contentVersion: '1.0.0.0'
      triggers: {
        DailyRecurrence: {
          type: 'Recurrence'
          recurrence: {
            frequency: 'Day'
            interval: 1
            startTime: '${scheduleStartDate}T${padLeft(string(scheduleHourUtc), 2, '0')}:00:00Z'
            timeZone: 'UTC'
          }
        }
      }
      actions: {
        StartBackupContainer: {
          type: 'Http'
          inputs: {
            method: 'POST'
            uri: '${environment().resourceManager}${backupContainerGroup.id}/start?api-version=${aciApiVersion}'
            authentication: {
              type: 'ManagedServiceIdentity'
            }
          }
        }
      }
    }
  }
}

resource logicAppAciStarterRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(backupContainerGroup.id, schedulerLogicApp.id, 'ContainerInstancesContributor')
  scope: backupContainerGroup
  properties: {
    principalId: schedulerLogicApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5d977122-f97e-4b4d-a52f-6b43003ddb4d') // Azure Container Instances Contributor Role
  }
}

output acrLoginServer string = acr.properties.loginServer
output backupIdentityClientId string = backupIdentity.properties.clientId
output backupIdentityPrincipalId string = backupIdentity.properties.principalId
output containerGroupName string = backupContainerGroup.name
output containerName string = backupContainerName
output logicAppName string = schedulerLogicApp.name
