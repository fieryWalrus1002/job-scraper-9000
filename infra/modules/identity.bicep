param location string
param prefix string

// Shared by the container app and the ingest job to pull images from ACR
// (#126). User-assigned rather than system-assigned: the AcrPull role
// assignment must exist before the apps first pull with the identity, and a
// system-assigned identity only exists once its app does — which deadlocks
// the image pull on first deploy.
resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-acr-pull'
  location: location
}

output identityId string = uami.id
output principalId string = uami.properties.principalId
