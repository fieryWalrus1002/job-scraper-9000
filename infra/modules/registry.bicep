param location string
@minLength(5)
param prefix string

@description('Principal ID of the managed identity granted AcrPull on this registry.')
param acrPullPrincipalId string

// ACR names: alphanumeric only, 5-50 chars, globally unique
var acrName = take('${replace(prefix, '-', '')}${uniqueString(resourceGroup().id)}', 50)

// Admin user disabled (#126): the container app and ingest job pull via
// managed identity + AcrPull below; CI and local `az acr login` authenticate
// with Entra tokens (the CI service principal's Contributor role includes
// ACR push/pull), so nothing needs the long-lived admin password.
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
  }
}

// AcrPull built-in role.
var acrPullRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '7f951dda-4ed3-4680-a7ca-43fe172d538d'
)

// Deploying role assignments requires Owner / User Access Administrator on
// the resource group — infra deploys are run by a human owner, not the
// Contributor-only CI service principal.
resource acrPullAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, acrPullPrincipalId, acrPullRoleId)
  scope: acr
  properties: {
    roleDefinitionId: acrPullRoleId
    principalId: acrPullPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output loginServer string = acr.properties.loginServer
output acrName string = acr.name
