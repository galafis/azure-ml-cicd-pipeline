// =============================================================================
// Azure ML Compute Resources
// =============================================================================
// Author: Gabriel Demetrios Lafis
// =============================================================================

@description('Azure region')
param location string

@description('Deployment environment')
param environment string

@description('Base name for resources')
param baseName string

@description('ML Workspace name')
param workspaceName string

@description('VM size for compute cluster')
param vmSize string

@description('Maximum number of nodes')
param maxNodes int

@description('Subnet ID for compute cluster')
param subnetId string

@description('Resource tags')
param tags object

// =============================================================================
// Reference existing workspace
// =============================================================================

resource mlWorkspace 'Microsoft.MachineLearningServices/workspaces@2023-10-01' existing = {
  name: workspaceName
}

// =============================================================================
// Training Compute Cluster
// =============================================================================

resource trainingCluster 'Microsoft.MachineLearningServices/workspaces/computes@2023-10-01' = {
  parent: mlWorkspace
  name: '${environment}-cpu-cluster'
  location: location
  tags: tags
  properties: {
    computeType: 'AmlCompute'
    properties: {
      vmSize: vmSize
      vmPriority: environment == 'dev' ? 'LowPriority' : 'Dedicated'
      scaleSettings: {
        minNodeCount: 0
        maxNodeCount: maxNodes
        nodeIdleTimeBeforeScaleDown: environment == 'prod' ? 'PT5M' : 'PT2M'
      }
      subnet: environment != 'dev' ? {
        id: subnetId
      } : null
      enableNodePublicIp: environment == 'dev'
      remoteLoginPortPublicAccess: 'Disabled'
    }
  }
}

// =============================================================================
// GPU Compute Cluster (Prod only)
// =============================================================================

resource gpuCluster 'Microsoft.MachineLearningServices/workspaces/computes@2023-10-01' = if (environment == 'prod') {
  parent: mlWorkspace
  name: 'prod-gpu-cluster'
  location: location
  tags: tags
  properties: {
    computeType: 'AmlCompute'
    properties: {
      vmSize: 'Standard_NC6s_v3'
      vmPriority: 'Dedicated'
      scaleSettings: {
        minNodeCount: 0
        maxNodeCount: 4
        nodeIdleTimeBeforeScaleDown: 'PT10M'
      }
      subnet: {
        id: subnetId
      }
      enableNodePublicIp: false
      remoteLoginPortPublicAccess: 'Disabled'
    }
  }
}

// =============================================================================
// Compute Instance (Dev only)
// =============================================================================

resource computeInstance 'Microsoft.MachineLearningServices/workspaces/computes@2023-10-01' = if (environment == 'dev') {
  parent: mlWorkspace
  name: 'dev-compute-instance'
  location: location
  tags: tags
  properties: {
    computeType: 'ComputeInstance'
    properties: {
      vmSize: 'Standard_DS2_v2'
      schedules: {
        computeStartStop: [
          {
            action: 'Stop'
            triggerType: 'Cron'
            cron: {
              expression: '0 20 * * 1-5'
              startTime: '2024-01-01T00:00:00Z'
              timeZone: 'UTC'
            }
            status: 'Enabled'
          }
        ]
      }
    }
  }
}

// =============================================================================
// Outputs
// =============================================================================

output computeClusterName string = trainingCluster.name
