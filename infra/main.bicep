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
  }
}

module storage 'modules/storageAccount.bicep' = {
  name: 'storageAccount'
  params: {
    location: location
    prefix: prefix
  }
}

// Derived inline so the account key never appears in deployment outputs.
var storageConnectionString = 'DefaultEndpointsProtocol=https;AccountName=${storage.outputs.storageAccountName};AccountKey=${listKeys(storage.outputs.storageAccountId, '2023-05-01').keys[0].value};EndpointSuffix=core.windows.net'

module ingestJob 'modules/ingestJob.bicep' = {
  name: 'ingestJob'
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
