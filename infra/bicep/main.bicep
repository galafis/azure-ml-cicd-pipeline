// =============================================================================
// Main Bicep Orchestration - Azure ML CI/CD Infrastructure
// =============================================================================
// Deploys complete Azure ML infrastructure with networking, security,
// compute, storage, and monitoring resources.
//
// Author: Gabriel Demetrios Lafis
// =============================================================================

targetScope = 'resourceGroup'

// =============================================================================
// Parameters
// =============================================================================

@description('Deployment environment')
@allowed([
  'dev'
  'staging'
  'prod'
])
param environment string = 'dev'

@description('Azure region for resource deployment')
param location string = resourceGroup().location

@description('Project name prefix for resource naming')
param projectName string = 'mlpipeline'

@description('Tags applied to all resources')
param tags object = {
  project: 'azure-ml-cicd-pipeline'
  environment: environment
  managedBy: 'bicep'
}

// Networking parameters
@description('Virtual network address prefix')
param vnetAddressPrefix string = environment == 'prod' ? '10.2.0.0/16' : (environment == 'staging' ? '10.1.0.0/16' : '10.0.0.0/16')

// Compute parameters
@description('Compute cluster VM size')
param computeVmSize string = environment == 'prod' ? 'Standard_NC6s_v3' : 'Standard_DS3_v2'

@description('Maximum compute cluster nodes')
param computeMaxNodes int = environment == 'prod' ? 8 : (environment == 'staging' ? 4 : 2)

// =============================================================================
// Resource Naming Convention
// =============================================================================

var baseName = '${projectName}-${environment}'
var uniqueSuffix = uniqueString(resourceGroup().id, environment)

// =============================================================================
// Module: Networking
// =============================================================================

module networking 'modules/networking.bicep' = {
  name: 'networking-${environment}'
  params: {
    location: location
    environment: environment
    baseName: baseName
    vnetAddressPrefix: vnetAddressPrefix
    tags: tags
  }
}

// =============================================================================
// Module: Key Vault
// =============================================================================

module keyvault 'modules/keyvault.bicep' = {
  name: 'keyvault-${environment}'
  params: {
    location: location
    environment: environment
    baseName: baseName
    uniqueSuffix: uniqueSuffix
    subnetId: networking.outputs.managementSubnetId
    tags: tags
  }
}

// =============================================================================
// Module: Storage
// =============================================================================

module storage 'modules/storage.bicep' = {
  name: 'storage-${environment}'
  params: {
    location: location
    environment: environment
    baseName: baseName
    uniqueSuffix: uniqueSuffix
    subnetId: networking.outputs.dataSubnetId
    tags: tags
  }
}

// =============================================================================
// Module: ML Workspace
// =============================================================================

module mlWorkspace 'modules/ml-workspace.bicep' = {
  name: 'ml-workspace-${environment}'
  params: {
    location: location
    environment: environment
    baseName: baseName
    uniqueSuffix: uniqueSuffix
    storageAccountId: storage.outputs.storageAccountId
    keyVaultId: keyvault.outputs.keyVaultId
    subnetId: networking.outputs.trainingSubnetId
    tags: tags
  }
}

// =============================================================================
// Module: Compute
// =============================================================================

module compute 'modules/compute.bicep' = {
  name: 'compute-${environment}'
  params: {
    location: location
    environment: environment
    baseName: baseName
    workspaceName: mlWorkspace.outputs.workspaceName
    vmSize: computeVmSize
    maxNodes: computeMaxNodes
    subnetId: networking.outputs.trainingSubnetId
    tags: tags
  }
}

// =============================================================================
// Outputs
// =============================================================================

output workspaceName string = mlWorkspace.outputs.workspaceName
output workspaceId string = mlWorkspace.outputs.workspaceId
output storageAccountName string = storage.outputs.storageAccountName
output keyVaultName string = keyvault.outputs.keyVaultName
output keyVaultUri string = keyvault.outputs.keyVaultUri
output vnetName string = networking.outputs.vnetName
output computeClusterName string = compute.outputs.computeClusterName
