// The API's managed identity, its read access to the application Key Vault,
// the database URL secret, and a private endpoint for the vault.
param env string
param location string
param keyVaultName string
param privateEndpointSubnetId string
param keyVaultDnsZoneId string
@secure()
param databaseUrl string

var keyVaultSecretsUser = '4633458b-17de-408a-b874-0445c86b69e6'

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource apiIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-cv360-api-${env}'
  location: location
}

resource secretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, apiIdentity.id, keyVaultSecretsUser)
  scope: vault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUser)
    principalId: apiIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource databaseUrlSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'database-url'
  properties: { value: databaseUrl, contentType: 'text/plain' }
}

resource endpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-${keyVaultName}'
  location: location
  properties: {
    subnet: { id: privateEndpointSubnetId }
    privateLinkServiceConnections: [
      { name: 'vault', properties: { privateLinkServiceId: vault.id, groupIds: ['vault'] } }
    ]
  }
}

resource endpointDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: endpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [{ name: 'vault', properties: { privateDnsZoneId: keyVaultDnsZoneId } }]
  }
}

// The app module runs after this whole module (role assignment, secret and
// private endpoint included), so the container app can read its secrets.
output apiIdentityId string = apiIdentity.id
output apiIdentityPrincipalId string = apiIdentity.properties.principalId
output keyVaultUri string = vault.properties.vaultUri
