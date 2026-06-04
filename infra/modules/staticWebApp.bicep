param location string
param prefix string
param tenantId string
param clientId string

@secure()
param clientSecret string

resource swa 'Microsoft.Web/staticSites@2023-12-01' = {
  name: '${prefix}-swa'
  location: location
  sku: {
    name: 'Standard'
    tier: 'Standard'
  }
  properties: {}
}

resource appSettings 'Microsoft.Web/staticSites/config@2023-12-01' = {
  parent: swa
  name: 'appsettings'
  properties: {
    AZURE_TENANT_ID: tenantId
    AZURE_CLIENT_ID: clientId
    AZURE_CLIENT_SECRET: clientSecret
  }
}

output swaHostname string = swa.properties.defaultHostname
output swaId string = swa.id
