param location string
param prefix string

@secure()
param adminPassword string

param adminLogin string = 'dbadmin'
param databaseName string = 'jobscraper'

// Unique server name scoped to this resource group
var serverName = '${prefix}-db-${uniqueString(resourceGroup().id)}'

resource server 'Microsoft.DBforPostgreSQL/flexibleServers@2022-12-01' = {
  name: serverName
  location: location
  sku: {
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    administratorLogin: adminLogin
    administratorLoginPassword: adminPassword
    version: '16'
    storage: {
      storageSizeGB: 32
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
  }
}

// Firewall rules live in dbFirewall.bicep (#126), a standalone module scoped
// to the ACA environment's outbound IPs — they need containerApp outputs, and
// this module deploys before containerApp.
resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2022-12-01' = {
  parent: server
  name: databaseName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

output serverFqdn string = server.properties.fullyQualifiedDomainName
output serverName string = serverName
output databaseName string = databaseName
output adminLogin string = adminLogin
