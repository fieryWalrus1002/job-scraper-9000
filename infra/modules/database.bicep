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

// startIpAddress == endIpAddress == '0.0.0.0' is Azure's convention for
// "allow connections from any Azure service" (including ACA outbound IPs).
resource firewallAzureServices 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2022-12-01' = {
  parent: server
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

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
