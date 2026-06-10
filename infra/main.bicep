targetScope = 'resourceGroup'

// ============================================================
// Parameters
// ============================================================

param location string = resourceGroup().location
@minLength(5)
param prefix string = 'jobscraper'
param tenantId string = subscription().tenantId
param clientId string
param imageTag string = 'latest'

@secure()
param clientSecret string

@secure()
@description('Password for the Postgres admin login. Interpolated into DATABASE_URL — common reserved characters are percent-encoded automatically, but avoid single quotes.')
param dbAdminPassword string

param dbAdminLogin string = 'dbadmin'

@description('Optional home/client IP allowed through the Postgres firewall for direct psql access. Set HOME_CLIENT_IP in .env; empty skips the rule.')
param homeClientIp string = ''

@secure()
@description('Contents of config/auth.yml — the allowed_emails allowlist injected as a volume-mounted file.')
param authConfig string

// Bicep has no uriEncode(); encode the characters that break a psycopg connection string.
// % must go first to avoid double-encoding any already-present percent signs.
var dbPasswordEncoded = replace(replace(replace(replace(dbAdminPassword, '%', '%25'), '@', '%40'), '#', '%23'), ':', '%3A')

// ============================================================
// Modules
// ============================================================

module logs 'modules/loganalytics.bicep' = {
  name: 'loganalytics'
  params: {
    location: location
    prefix: prefix
  }
}

// User-assigned identity for ACR pulls (#126) — shared by the container app
// and the ingest job. registry.bicep grants it AcrPull; no admin credentials
// are distributed anywhere.
module identity 'modules/identity.bicep' = {
  name: 'identity'
  params: {
    location: location
    prefix: prefix
  }
}

module registry 'modules/registry.bicep' = {
  name: 'registry'
  params: {
    location: location
    prefix: prefix
    acrPullPrincipalId: identity.outputs.principalId
  }
}

module database 'modules/database.bicep' = {
  name: 'database'
  params: {
    location: location
    prefix: prefix
    adminLogin: dbAdminLogin
    adminPassword: dbAdminPassword
  }
}

// Role-named symbol, type-named file: the backend API is a container app.
// NOTE: this module also creates the shared ACA *environment* that the
// ingest job runs in (acaEnvironmentId output).
module backendApi 'modules/containerApp.bicep' = {
  name: 'backendApi'
  params: {
    location: location
    prefix: prefix
    logAnalyticsCustomerId: logs.outputs.customerId
    logAnalyticsSharedKey: logs.outputs.sharedKey
    acrLoginServer: registry.outputs.loginServer
    acrPullIdentityId: identity.outputs.identityId
    imageTag: imageTag
    databaseUrl: 'postgresql://${dbAdminLogin}:${dbPasswordEncoded}@${database.outputs.serverFqdn}:5432/${database.outputs.databaseName}?sslmode=require'
    authConfig: authConfig
    // The container app's authConfig (#152) trusts only requests proxied by
    // this SWA, keyed on its default hostname. This makes backendApi depend
    // on frontendSwa. NOTE for #133: adding a SWA->backend linkedBackend will
    // make frontendSwa depend on backendApi, creating a cycle — break it by
    // modelling linkedBackend as a separate resource that depends on both.
    swaHostname: frontendSwa.outputs.swaHostname
  }
}

// Storage account name lives here (not in the module) so the resource ID can
// be built with `resourceId(...)` for the `listKeys` call below — module
// outputs aren't statically resolvable for listKeys arguments. `take` lowercases
// and clamps to the Azure limit (3-24 chars, lowercase alphanumeric).
var storageAccountName = take('${toLower(replace(prefix, '-', ''))}ingest', 24)

module storage 'modules/storageAccount.bicep' = {
  name: 'storageAccount'
  params: {
    location: location
    storageAccountName: storageAccountName
  }
}

// Derived inline so the account key never appears in deployment outputs.
var storageConnectionString = 'DefaultEndpointsProtocol=https;AccountName=${storageAccountName};AccountKey=${listKeys(resourceId('Microsoft.Storage/storageAccounts', storageAccountName), '2023-05-01').keys[0].value};EndpointSuffix=core.windows.net'

module ingestJob 'modules/ingestJob.bicep' = {
  name: 'ingestJob'
  // listKeys in storageConnectionString uses resourceId() (a string), not a
  // module output, so the dependency on `storage` must be declared explicitly.
  dependsOn: [storage]
  params: {
    location: location
    prefix: prefix
    acaEnvironmentId: backendApi.outputs.acaEnvironmentId
    acrLoginServer: registry.outputs.loginServer
    acrPullIdentityId: identity.outputs.identityId
    databaseUrl: 'postgresql://${dbAdminLogin}:${dbPasswordEncoded}@${database.outputs.serverFqdn}:5432/${database.outputs.databaseName}?sslmode=require'
    storageConnectionString: storageConnectionString
    imageTag: imageTag
  }
}

module frontendSwa 'modules/staticWebApp.bicep' = {
  name: 'frontendSwa'
  params: {
    location: location
    prefix: prefix
    tenantId: tenantId
    clientId: clientId
    clientSecret: clientSecret
  }
}

// Postgres firewall (#126). Standalone leaf module for the same reason as
// linkedBackend: it needs the container app's outbound IPs, but database
// deploys before backendApi. Replaces the old AllowAzureServices 0.0.0.0
// rule (deleting that live rule is a one-time manual step — incremental
// deployments don't remove resources dropped from the template).
module dbFirewall 'modules/dbFirewall.bicep' = {
  name: 'dbFirewall'
  params: {
    serverName: database.outputs.serverName
    acaOutboundIps: backendApi.outputs.outboundIps
    homeClientIp: homeClientIp
  }
}

// SWA -> ACA backend link (#133). Standalone module depending on BOTH
// frontendSwa and backendApi. It must not live inside either module:
// backendApi already depends on frontendSwa (swaHostname, #152), so nesting
// the link under frontendSwa would create a cycle. As a separate leaf the
// graph stays acyclic.
module linkedBackend 'modules/linkedBackend.bicep' = {
  name: 'linkedBackend'
  params: {
    swaName: '${prefix}-swa'
    backendResourceId: backendApi.outputs.containerAppId
    backendName: '${prefix}-api'
    region: location
  }
}

// ============================================================
// Outputs
// ============================================================

output swaUrl string = 'https://${frontendSwa.outputs.swaHostname}'
output acrLoginServer string = registry.outputs.loginServer
output containerAppFqdn string = backendApi.outputs.containerAppFqdn
output containerAppId string = backendApi.outputs.containerAppId
output storageAccountName string = storage.outputs.storageAccountName
