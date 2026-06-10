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

module registry 'modules/registry.bicep' = {
  name: 'registry'
  params: {
    location: location
    prefix: prefix
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

module containerApp 'modules/containerApp.bicep' = {
  name: 'containerApp'
  params: {
    location: location
    prefix: prefix
    logAnalyticsCustomerId: logs.outputs.customerId
    logAnalyticsSharedKey: logs.outputs.sharedKey
    acrLoginServer: registry.outputs.loginServer
    acrPassword: registry.outputs.adminPassword
    imageTag: imageTag
    databaseUrl: 'postgresql://${dbAdminLogin}:${dbPasswordEncoded}@${database.outputs.serverFqdn}:5432/${database.outputs.databaseName}?sslmode=require'
    authConfig: authConfig
    // The container app's authConfig (#152) trusts only requests proxied by
    // this SWA, keyed on its default hostname. This makes containerApp depend
    // on staticWebApp. NOTE for #133: adding a SWA->backend linkedBackend will
    // make staticWebApp depend on containerApp, creating a cycle — break it by
    // modelling linkedBackend as a separate resource that depends on both.
    swaHostname: staticWebApp.outputs.swaHostname
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
    acaEnvironmentId: containerApp.outputs.acaEnvironmentId
    acrLoginServer: registry.outputs.loginServer
    acrPassword: registry.outputs.adminPassword
    databaseUrl: 'postgresql://${dbAdminLogin}:${dbPasswordEncoded}@${database.outputs.serverFqdn}:5432/${database.outputs.databaseName}?sslmode=require'
    storageConnectionString: storageConnectionString
    imageTag: imageTag
  }
}

module staticWebApp 'modules/staticWebApp.bicep' = {
  name: 'staticWebApp'
  params: {
    location: location
    prefix: prefix
    tenantId: tenantId
    clientId: clientId
    clientSecret: clientSecret
  }
}

// ============================================================
// Outputs
// ============================================================

output swaUrl string = 'https://${staticWebApp.outputs.swaHostname}'
output acrLoginServer string = registry.outputs.loginServer
output containerAppFqdn string = containerApp.outputs.containerAppFqdn
output containerAppId string = containerApp.outputs.containerAppId
output storageAccountName string = storage.outputs.storageAccountName
