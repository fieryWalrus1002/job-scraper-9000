param location string
param prefix string

// Storage account names must be lowercase alphanumeric, 3-24 chars, globally unique.
// Lowercase the prefix and clamp the final name to 24 chars so an uppercase or
// long prefix doesn't fail deployment with an invalid name.
var rawName = '${toLower(replace(prefix, '-', ''))}ingest'
var storageAccountName = length(rawName) > 24 ? substring(rawName, 0, 24) : rawName

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource pendingContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'pending'
  properties: {
    publicAccess: 'None'
  }
}

resource processedContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'processed'
  properties: {
    publicAccess: 'None'
  }
}

// Dead-letter container for poison blobs (unparseable JSONL etc.) so the KEDA
// trigger doesn't re-fire on the same bad blob indefinitely.
resource failedContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'failed'
  properties: {
    publicAccess: 'None'
  }
}

output storageAccountName string = storage.name
output storageAccountId string = storage.id
