param location string
@minLength(5)
param prefix string

// ACR names: alphanumeric only, 5-50 chars, globally unique
var acrName = take('${replace(prefix, '-', '')}${uniqueString(resourceGroup().id)}', 50)

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true
  }
}

output loginServer string = acr.properties.loginServer
output acrName string = acr.name

@secure()
output adminPassword string = acr.listCredentials().passwords[0].value
