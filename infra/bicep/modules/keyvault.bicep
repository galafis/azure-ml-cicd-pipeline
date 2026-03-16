// =============================================================================
// Azure Key Vault
// =============================================================================
// Author: Gabriel Demetrios Lafis
// =============================================================================

@description('Azure region')
param location string

@description('Deployment environment')
param environment string

@description('Base name for resources')
param baseName string

@description('Unique suffix for globally unique names')
param uniqueSuffix string

@description('Subnet ID for private endpoint')
param subnetId string

@description('Resource tags')
param tags object

// =============================================================================
// Key Vault
// =============================================================================

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-${baseName}-${uniqueSuffix}'
  location: location
  tags: tags
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: environment == 'prod' ? 90 : 30
    enablePurgeProtection: environment == 'prod' ? true : null
    publicNetworkAccess: environment == 'prod' ? 'Disabled' : 'Enabled'
    networkAcls: environment == 'prod' ? {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
      virtualNetworkRules: [
        {
          id: subnetId
        }
      ]
    } : {
      defaultAction: 'Allow'
    }
  }
}

// =============================================================================
// Diagnostic Settings
// =============================================================================

resource diagnosticSettings 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-${keyVault.name}'
  scope: keyVault
  properties: {
    logs: [
      {
        categoryGroup: 'audit'
        enabled: true
        retentionPolicy: {
          days: environment == 'prod' ? 90 : 30
          enabled: true
        }
      }
      {
        categoryGroup: 'allLogs'
        enabled: true
        retentionPolicy: {
          days: environment == 'prod' ? 90 : 30
          enabled: true
        }
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
        retentionPolicy: {
          days: environment == 'prod' ? 90 : 30
          enabled: true
        }
      }
    ]
  }
}

// =============================================================================
// Private Endpoint (Staging & Prod)
// =============================================================================

resource privateEndpoint 'Microsoft.Network/privateEndpoints@2023-09-01' = if (environment != 'dev') {
  name: 'pe-kv-${baseName}'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: subnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'kv-connection'
        properties: {
          privateLinkServiceId: keyVault.id
          groupIds: [
            'vault'
          ]
        }
      }
    ]
  }
}

// =============================================================================
// Outputs
// =============================================================================

output keyVaultId string = keyVault.id
output keyVaultName string = keyVault.name
output keyVaultUri string = keyVault.properties.vaultUri
