// =============================================================================
// Azure Storage Account for ML Workspace
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
// Storage Account
// =============================================================================

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: 'st${replace(baseName, '-', '')}${uniqueSuffix}'
  location: location
  tags: tags
  sku: {
    name: environment == 'prod' ? 'Standard_GRS' : 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
    accessTier: 'Hot'
    networkAcls: environment == 'prod' ? {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
      virtualNetworkRules: [
        {
          id: subnetId
          action: 'Allow'
        }
      ]
    } : {
      defaultAction: 'Allow'
    }
    encryption: {
      services: {
        blob: {
          enabled: true
          keyType: 'Account'
        }
        file: {
          enabled: true
          keyType: 'Account'
        }
      }
      keySource: 'Microsoft.Storage'
    }
  }
}

// =============================================================================
// Blob Containers
// =============================================================================

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storageAccount
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: environment == 'prod' ? 30 : 7
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: environment == 'prod' ? 30 : 7
    }
  }
}

resource trainingDataContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: 'training-data'
  properties: {
    publicAccess: 'None'
  }
}

resource modelArtifactsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: 'model-artifacts'
  properties: {
    publicAccess: 'None'
  }
}

resource evaluationContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: 'evaluation-results'
  properties: {
    publicAccess: 'None'
  }
}

// =============================================================================
// Private Endpoint (Staging & Prod)
// =============================================================================

resource privateEndpoint 'Microsoft.Network/privateEndpoints@2023-09-01' = if (environment != 'dev') {
  name: 'pe-storage-${baseName}'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: subnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'storage-connection'
        properties: {
          privateLinkServiceId: storageAccount.id
          groupIds: [
            'blob'
          ]
        }
      }
    ]
  }
}

// =============================================================================
// Outputs
// =============================================================================

output storageAccountId string = storageAccount.id
output storageAccountName string = storageAccount.name
