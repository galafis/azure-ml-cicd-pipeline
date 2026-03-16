// =============================================================================
// Azure Machine Learning Workspace
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

@description('Storage account resource ID')
param storageAccountId string

@description('Key Vault resource ID')
param keyVaultId string

@description('Subnet ID for private endpoint')
param subnetId string

@description('Resource tags')
param tags object

// =============================================================================
// Application Insights
// =============================================================================

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: 'log-${baseName}-${uniqueSuffix}'
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: environment == 'prod' ? 90 : 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${baseName}-${uniqueSuffix}'
  location: location
  kind: 'web'
  tags: tags
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
    RetentionInDays: environment == 'prod' ? 90 : 30
  }
}

// =============================================================================
// Container Registry
// =============================================================================

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'acr${replace(baseName, '-', '')}${uniqueSuffix}'
  location: location
  tags: tags
  sku: {
    name: environment == 'prod' ? 'Premium' : 'Standard'
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: environment == 'prod' ? 'Disabled' : 'Enabled'
  }
}

// =============================================================================
// ML Workspace
// =============================================================================

resource mlWorkspace 'Microsoft.MachineLearningServices/workspaces@2023-10-01' = {
  name: 'mlw-${baseName}-${uniqueSuffix}'
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    friendlyName: 'ML Workspace (${environment})'
    description: 'Azure ML workspace for ${environment} environment'
    storageAccount: storageAccountId
    keyVault: keyVaultId
    applicationInsights: appInsights.id
    containerRegistry: containerRegistry.id
    publicNetworkAccess: environment == 'prod' ? 'Disabled' : 'Enabled'
    v1LegacyMode: false
  }
}

// =============================================================================
// Private Endpoint (Staging & Prod)
// =============================================================================

resource privateEndpoint 'Microsoft.Network/privateEndpoints@2023-09-01' = if (environment != 'dev') {
  name: 'pe-mlw-${baseName}'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: subnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'mlw-connection'
        properties: {
          privateLinkServiceId: mlWorkspace.id
          groupIds: [
            'amlworkspace'
          ]
        }
      }
    ]
  }
}

// =============================================================================
// Diagnostic Settings
// =============================================================================

resource diagnosticSettings 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-${mlWorkspace.name}'
  scope: mlWorkspace
  properties: {
    workspaceId: logAnalytics.id
    logs: [
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
// Outputs
// =============================================================================

output workspaceName string = mlWorkspace.name
output workspaceId string = mlWorkspace.id
output appInsightsKey string = appInsights.properties.InstrumentationKey
output containerRegistryName string = containerRegistry.name
