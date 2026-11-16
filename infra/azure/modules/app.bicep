// Container Apps environment (in the virtual network), the API, and the
// Alembic migration job. Secrets are Key Vault references resolved with the
// API's managed identity - no secret values in this template or the app.
param env string
param location string
param apiImage string
param sqlImage string
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
  // First platform_admin login, seeded at startup if the user doesn't exist.
  { name: 'admin-password', env: 'SAAS_JOB_API_BOOTSTRAP_ADMIN_PASSWORD' }
  { name: 'gateway-tokens-json', env: 'SAAS_JOB_API_GATEWAY_TOKENS_JSON' }
  { name: 'gateway-tenants-json', env: 'SAAS_JOB_API_GATEWAY_TENANTS_JSON' }
]

var settings = [
  { name: 'SAAS_JOB_API_LOG_LEVEL', value: 'INFO' }
  { name: 'SAAS_JOB_API_BOOTSTRAP_ADMIN_USERNAME', value: 'platform-admin' }
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

// Read-only SQL from an operator laptop while PostgreSQL stays private:
// infra/azure/sql.sh starts this job with QUERY_B64 (base64 SQL) and prints
// its log. Each run sets a fresh random password, valid for 15 minutes and
// never output, on the role cv_readonly (SELECT only, read-only
// transactions, no access to tables holding token or password hashes), and
// runs the query as that role - never as the admin.
// Container Apps (like Kubernetes) turns "$$" in a command into "$", so the
// SQL below uses named dollar quotes ($do$) and must never contain "$$".
var sqlScript = '''
set -eu
trap 'echo "---- end (exit $?) ----"' EXIT
q=$(printf %s "${QUERY_B64:-}" | base64 -d)
[ -n "$q" ] || { echo "no query: start the job with QUERY_B64" >&2; exit 2; }
pw=$(head -c 48 /dev/urandom | base64 | tr -dc A-Za-z0-9 | head -c 32)
until=$(date -u -d "@$(( $(date +%s) + 900 ))" '+%Y-%m-%d %H:%M:%S+00')
psql "$DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -v pw="$pw" -v until="$until" <<'SQL'
DO $do$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_readonly') THEN CREATE ROLE cv_readonly LOGIN; END IF;
END $do$;
ALTER ROLE cv_readonly PASSWORD :'pw' VALID UNTIL :'until';
ALTER ROLE cv_readonly SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE saas TO cv_readonly;
GRANT USAGE ON SCHEMA public TO cv_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO cv_readonly;
DO $do$ DECLARE t text; BEGIN
  FOR t IN SELECT DISTINCT table_name FROM information_schema.columns
           WHERE table_schema = 'public'
             AND (column_name LIKE '%token_hash%' OR column_name LIKE '%password%' OR column_name LIKE '%secret%')
  LOOP EXECUTE format('REVOKE SELECT ON %I FROM cv_readonly', t); END LOOP;
END $do$;
SQL
host=$(printf %s "$DATABASE_URL" | sed -E 's#^[a-z]+://[^@]+@([^:/?]+).*#\1#')
echo "---- query (as cv_readonly) ----"
printf '%s\n' "$q"
echo "---- result ----"
PGPASSWORD=$pw psql "host=$host port=5432 dbname=saas user=cv_readonly sslmode=require" \
  -X -v ON_ERROR_STOP=1 -P pager=off -P footer=on -c "$q"
'''

resource sql 'Microsoft.App/jobs@2024-03-01' = {
  name: 'caj-cv360-sql-${env}'
  location: location
  identity: identity
  dependsOn: [pull]
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 300
      replicaRetryLimit: 0
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      registries: registries
      secrets: [{ name: 'database-url', keyVaultUrl: '${keyVaultUri}secrets/database-url', identity: identityId }]
    }
    template: {
      containers: [
        {
          name: 'sql'
          image: sqlImage
          command: ['/bin/sh', '-c', sqlScript]
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          env: [
            { name: 'DATABASE_URL', secretRef: 'database-url' }
            { name: 'QUERY_B64', value: '' }
          ]
        }
      ]
    }
  }
}

output apiUrl string = 'https://${api.properties.configuration.ingress.fqdn}'
output migrationJobName string = migrate.name
output sqlJobName string = sql.name
