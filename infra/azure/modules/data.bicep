// PostgreSQL Flexible Server, reachable only inside the virtual network
// (VNet injection: no public endpoint). TLS is required by the server.
param env string
param location string
param subnetId string
param privateDnsZoneId string
param adminLogin string
@secure()
param adminPassword string

@description('Burstable B1ms (~35 usable connections) for dev; GeneralPurpose for production.')
param skuName string = 'Standard_B1ms'
param skuTier string = 'Burstable'

resource server 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: 'psql-cv360-${env}'
  location: location
  sku: { name: skuName, tier: skuTier }
  properties: {
    version: '17'
    administratorLogin: adminLogin
    administratorLoginPassword: adminPassword
    authConfig: { passwordAuth: 'Enabled', activeDirectoryAuth: 'Disabled' }
    storage: { storageSizeGB: 32, autoGrow: 'Enabled' }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
    network: {
      delegatedSubnetResourceId: subnetId
      privateDnsZoneArmResourceId: privateDnsZoneId
      publicNetworkAccess: 'Disabled'
    }
  }
}

resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: server
  name: 'saas'
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
}

output fqdn string = server.properties.fullyQualifiedDomainName
output databaseName string = database.name
