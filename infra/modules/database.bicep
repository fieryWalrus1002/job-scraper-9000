param location string
param prefix string

@secure()
param adminPassword string

param adminLogin string = 'dbadmin'
param databaseName string = 'jobscraper'

@description('Optional home/client IP for direct psql access via the public endpoint. Empty string skips the rule.')
param homeClientIp string = ''

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

// Public access stays enabled (the flexible-server default) but is firewalled
// to this single rule: app traffic arrives via the private endpoint instead
// (dbPrivateEndpoint.bicep, #161), so no Azure-side IPs need allowing.
resource homeRule 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2022-12-01' = if (homeClientIp != '') {
  parent: server
  name: 'AllowHomeClient'
  properties: {
    startIpAddress: homeClientIp
    endIpAddress: homeClientIp
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
