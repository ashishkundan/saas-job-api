// Virtual network: Container Apps, PostgreSQL (VNet-injected, no public
// endpoint) and private endpoints each get their own subnet.
param env string
param location string

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: 'vnet-cv360-${env}'
  location: location
  properties: {
    addressSpace: { addressPrefixes: ['10.40.0.0/16'] }
    subnets: [
      {
        // Container Apps environment (workload profiles: /27 minimum).
        name: 'snet-aca'
        properties: {
          addressPrefix: '10.40.0.0/23'
          delegations: [{ name: 'aca', properties: { serviceName: 'Microsoft.App/environments' } }]
        }
      }
      {
        name: 'snet-psql'
        properties: {
          addressPrefix: '10.40.2.0/24'
          delegations: [{ name: 'psql', properties: { serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers' } }]
        }
      }
      {
        name: 'snet-pe'
        properties: {
          addressPrefix: '10.40.3.0/24'
          privateEndpointNetworkPolicies: 'Enabled'
        }
      }
    ]
  }
}

resource postgresZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.postgres.database.azure.com'
  location: 'global'
}

resource keyVaultZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.vaultcore.azure.net'
  location: 'global'
}

resource postgresZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: postgresZone
  name: vnet.name
  location: 'global'
  properties: { virtualNetwork: { id: vnet.id }, registrationEnabled: false }
}

resource keyVaultZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: keyVaultZone
  name: vnet.name
  location: 'global'
  properties: { virtualNetwork: { id: vnet.id }, registrationEnabled: false }
}

output containerAppsSubnetId string = vnet.properties.subnets[0].id
output postgresSubnetId string = vnet.properties.subnets[1].id
output privateEndpointSubnetId string = vnet.properties.subnets[2].id
// Module outputs are available only once every resource here (including the
// zone links the server and endpoint rely on) is deployed.
output postgresDnsZoneId string = postgresZone.id
output keyVaultDnsZoneId string = keyVaultZone.id
