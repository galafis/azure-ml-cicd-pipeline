// =============================================================================
// Azure Networking Infrastructure
// =============================================================================
// VNet, subnets, and NSG for Azure ML workspace isolation.
// Author: Gabriel Demetrios Lafis
// =============================================================================

@description('Azure region')
param location string

@description('Deployment environment')
param environment string

@description('Base name for resources')
param baseName string

@description('VNet address prefix')
param vnetAddressPrefix string

@description('Resource tags')
param tags object

// =============================================================================
// Variables
// =============================================================================

var subnetPrefixBase = split(vnetAddressPrefix, '.')[0]
var subnetPrefixSecond = split(vnetAddressPrefix, '.')[1]

// =============================================================================
// Network Security Group
// =============================================================================

resource nsg 'Microsoft.Network/networkSecurityGroups@2023-09-01' = {
  name: 'nsg-${baseName}'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'AllowAzureMLInbound'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'AzureMachineLearning'
          destinationAddressPrefix: '*'
          sourcePortRange: '*'
          destinationPortRange: '44224'
          description: 'Allow Azure ML control plane'
        }
      }
      {
        name: 'AllowBatchNodeManagement'
        properties: {
          priority: 110
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'BatchNodeManagement'
          destinationAddressPrefix: '*'
          sourcePortRange: '*'
          destinationPortRange: '29876-29877'
          description: 'Allow Batch node management'
        }
      }
      {
        name: 'AllowAzureADOutbound'
        properties: {
          priority: 100
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureActiveDirectory'
          sourcePortRange: '*'
          destinationPortRange: '443'
          description: 'Allow Azure AD authentication'
        }
      }
      {
        name: 'AllowAzureMLOutbound'
        properties: {
          priority: 110
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureMachineLearning'
          sourcePortRange: '*'
          destinationPortRange: '443'
          description: 'Allow Azure ML API access'
        }
      }
      {
        name: 'AllowStorageOutbound'
        properties: {
          priority: 120
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'Storage'
          sourcePortRange: '*'
          destinationPortRange: '443'
          description: 'Allow Azure Storage access'
        }
      }
      {
        name: 'AllowKeyVaultOutbound'
        properties: {
          priority: 130
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureKeyVault'
          sourcePortRange: '*'
          destinationPortRange: '443'
          description: 'Allow Key Vault access'
        }
      }
      {
        name: 'AllowACROutbound'
        properties: {
          priority: 140
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureContainerRegistry'
          sourcePortRange: '*'
          destinationPortRange: '443'
          description: 'Allow ACR access'
        }
      }
    ]
  }
}

// =============================================================================
// Virtual Network
// =============================================================================

resource vnet 'Microsoft.Network/virtualNetworks@2023-09-01' = {
  name: 'vnet-${baseName}'
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        vnetAddressPrefix
      ]
    }
    subnets: [
      {
        name: 'snet-training'
        properties: {
          addressPrefix: '${subnetPrefixBase}.${subnetPrefixSecond}.1.0/24'
          networkSecurityGroup: {
            id: nsg.id
          }
          serviceEndpoints: [
            { service: 'Microsoft.Storage' }
            { service: 'Microsoft.KeyVault' }
            { service: 'Microsoft.ContainerRegistry' }
          ]
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
      {
        name: 'snet-inference'
        properties: {
          addressPrefix: '${subnetPrefixBase}.${subnetPrefixSecond}.2.0/24'
          networkSecurityGroup: {
            id: nsg.id
          }
          serviceEndpoints: [
            { service: 'Microsoft.Storage' }
            { service: 'Microsoft.KeyVault' }
          ]
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
      {
        name: 'snet-data'
        properties: {
          addressPrefix: '${subnetPrefixBase}.${subnetPrefixSecond}.3.0/24'
          networkSecurityGroup: {
            id: nsg.id
          }
          serviceEndpoints: [
            { service: 'Microsoft.Storage' }
          ]
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
      {
        name: 'snet-management'
        properties: {
          addressPrefix: '${subnetPrefixBase}.${subnetPrefixSecond}.4.0/24'
          networkSecurityGroup: {
            id: nsg.id
          }
          serviceEndpoints: [
            { service: 'Microsoft.KeyVault' }
          ]
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
    ]
  }
}

// =============================================================================
// Outputs
// =============================================================================

output vnetName string = vnet.name
output vnetId string = vnet.id
output trainingSubnetId string = vnet.properties.subnets[0].id
output inferenceSubnetId string = vnet.properties.subnets[1].id
output dataSubnetId string = vnet.properties.subnets[2].id
output managementSubnetId string = vnet.properties.subnets[3].id
