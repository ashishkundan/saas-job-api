// Container Apps environment (in the virtual network), the API, and the
// Alembic migration job. Secrets are Key Vault references resolved with the
// API's managed identity - no secret values in this template or the app.
param env string
param location string
param apiImage string
param acrName string
param infrastructureSubnetId string
param logAnalyticsWorkspaceId string
param identityId string
param identityPrincipalId string
param keyVaultUri string
param minReplicas int
param maxReplicas int

var acrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d' // AcrPull (built-in)

// Key Vault secret name -> container app secret name / environment variable.
var vaultSecrets = [
  { name: 'database-url', env: 'SAAS_JOB_API_DATABASE_URL' }
  { name: 'admin-token', env: 'SAAS_JOB_API_ADMIN_TOKEN' }
  { name: 'jwt-secret', env: 'SAAS_JOB_API_JWT_SECRET' }
  { name: 'gateway-tokens-json', env: 'SAAS_JOB_API_GATEWAY_TOKENS_JSON' }
  { name: 'gateway-tenants-json', env: 'SAAS_JOB_API_GATEWAY_TENANTS_JSON' }
]

var settings = [
  { name: 'SAAS_JOB_API_LOG_LEVEL', value: 'INFO' }
  { name: 'SAAS_JOB_API_RESERVATION_TTL_SECONDS', value: '60.0' }
  { name: 'SAAS_JOB_API_DEFAULT_MAX_JOBS', value: '20' }
  { name: 'SAAS_JOB_API_DEFAULT_POLL_AFTER_MS', value: '2000' }
  { name: 'SAAS_JOB_API_SCHEDULER_ENABLED', value: 'true' }
  { name: 'SAAS_JOB_API_SCHEDULER_TICK_INTERVAL_SECONDS', value: '30.0' }
  // 2 replicas x 10 + the migration job stays under B1ms's ~35 connections.
  { name: 'SAAS_JOB_API_DB_POOL_MIN_SIZE', value: '2' }
  { name: 'SAAS_JOB_API_DB_POOL_MAX_SIZE', value: '10' }
]

var secretEnv = [for s in vaultSecrets: { name: s.env, secretRef: s.name }]

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
}

resource pull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identityId, acrPull)
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPull)
    principalId: identityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-cv360-${env}'
  location: location
  properties: {
    vnetConfiguration: { infrastructureSubnetId: infrastructureSubnetId, internal: false }
    workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }]
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: reference(logAnalyticsWorkspaceId, '2023-09-01').customerId
        sharedKey: listKeys(logAnalyticsWorkspaceId, '2023-09-01').primarySharedKey
      }
    }
  }
}

var identity = { type: 'UserAssigned', userAssignedIdentities: { '${identityId}': {} } }
var registries = [{ server: registry.properties.loginServer, identity: identityId }]

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-cv360-api-${env}'
  location: location
  identity: identity
  dependsOn: [pull]
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: true, targetPort: 8080, transport: 'auto', allowInsecure: false }
      registries: registries
      secrets: [for s in vaultSecrets: { name: s.name, keyVaultUrl: '${keyVaultUri}secrets/${s.name}', identity: identityId }]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: apiImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: concat(settings, secretEnv)
          probes: [
            { type: 'Liveness', httpGet: { path: '/healthz', port: 8080 }, periodSeconds: 30 }
            { type: 'Readiness', httpGet: { path: '/healthz', port: 8080 }, periodSeconds: 10 }
          ]
        }
      ]
      scale: { minReplicas: minReplicas, maxReplicas: maxReplicas }
    }
  }
}

// `az containerapp job start` runs `alembic upgrade head` with the same
// image before a new API revision is rolled out.
resource migrate 'Microsoft.App/jobs@2024-03-01' = {
  name: 'caj-cv360-migrate-${env}'
  location: location
  identity: identity
  dependsOn: [pull]
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 600
      replicaRetryLimit: 0
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      registries: registries
      secrets: [{ name: 'database-url', keyVaultUrl: '${keyVaultUri}secrets/database-url', identity: identityId }]
    }
    template: {
      containers: [
        {
          name: 'migrate'
          image: apiImage
          command: ['alembic', 'upgrade', 'head']
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          env: [{ name: 'SAAS_JOB_API_DATABASE_URL', secretRef: 'database-url' }]
        }
      ]
    }
  }
}

output apiUrl string = 'https://${api.properties.configuration.ingress.fqdn}'
output migrationJobName string = migrate.name
