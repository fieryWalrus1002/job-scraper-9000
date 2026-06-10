// Private endpoint for Postgres (#161). App traffic to the DB stays inside
// the VNet; the server's public endpoint remains enabled but is firewalled to
// the home IP only (see database.bicep — flexible server supports both at
// once).
//
// DNS is split-horizon: the privatelink zone below is linked to the VNet, so
// inside it the server's normal FQDN resolves to the private endpoint IP,
// while from outside (home psql) it still resolves to the public IP. The
// DATABASE_URL therefore never changes.
param location string
param prefix string
param serverName string
param vnetId string
param peSubnetId string

resource server 'Microsoft.DBforPostgreSQL/flexibleServers@2022-12-01' existing = {
  name: serverName
}

resource dnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.postgres.database.azure.com'
  location: 'global'
}

resource dnsZoneVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: dnsZone
  name: '${prefix}-vnet-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnetId
    }
  }
}

resource pe 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  name: '${prefix}-db-pe'
  location: location
  properties: {
    subnet: {
      id: peSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${prefix}-db-pe-conn'
        properties: {
          privateLinkServiceId: server.id
          groupIds: ['postgresqlServer']
        }
      }
    ]
  }
}

// Registers the PE's private IP in the privatelink zone automatically.
resource peDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-04-01' = {
  parent: pe
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'postgres'
        properties: {
          privateDnsZoneId: dnsZone.id
        }
      }
    ]
  }
}
