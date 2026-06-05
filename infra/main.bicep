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
@description('Password for the Postgres admin login. Must not contain URL-reserved characters (@, :, /, ?, #) — it is interpolated directly into the DATABASE_URL connection string.')
param dbAdminPassword string

param dbAdminLogin string = 'dbadmin'

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
    databaseUrl: 'postgresql://${dbAdminLogin}:${dbAdminPassword}@${database.outputs.serverFqdn}:5432/${database.outputs.databaseName}?sslmode=require'
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
