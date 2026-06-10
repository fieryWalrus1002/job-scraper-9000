// Custom VNet for private networking (#161). The ACA environment is injected
// into acaInfraSubnet; private endpoints (Postgres) live in peSubnet so NSG /
// policy concerns stay separable from the ACA infrastructure range.
param location string
param prefix string

resource vnet 'Microsoft.Network/virtualNetworks@2023-04-01' = {
  name: '${prefix}-vnet'
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: ['10.10.0.0/16']
    }
    subnets: [
      {
        // Consumption-only ACA environments require a /23 or larger and no
        // subnet delegation (workload-profiles envs would need /27 + a
        // Microsoft.App/environments delegation instead).
        name: 'aca-infra'
        properties: {
          addressPrefix: '10.10.0.0/23'
        }
      }
      {
        name: 'private-endpoints'
        properties: {
          addressPrefix: '10.10.2.0/24'
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
    ]
  }
}

output vnetId string = vnet.id
// Index-addressed: keep in sync with the subnets array above.
output acaInfraSubnetId string = vnet.properties.subnets[0].id
output peSubnetId string = vnet.properties.subnets[1].id
