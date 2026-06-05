param location string
param prefix string

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: '${prefix}ingest'
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

var accountKey = storage.listKeys().keys[0].value

output storageAccountName string = storage.name
output connectionString string = 'DefaultEndpointsProtocol=https;AccountName=${storage.name};AccountKey=${accountKey};EndpointSuffix=core.windows.net'
