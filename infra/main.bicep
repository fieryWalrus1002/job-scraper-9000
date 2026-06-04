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
