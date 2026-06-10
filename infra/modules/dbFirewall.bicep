// Postgres firewall rules (#126). Standalone module: the ACA allow rules need
// the container app's outbound IPs, but database.bicep deploys before
// containerApp (it feeds databaseUrl). Same acyclic-leaf pattern as
// linkedBackend — don't nest these rules inside database.bicep.
param serverName string

@description('Outbound IPs of the Container Apps environment; one single-address allow rule per IP.')
param acaOutboundIps array

@description('Optional home/client IP for direct psql access. Empty string skips the rule.')
param homeClientIp string = ''

resource server 'Microsoft.DBforPostgreSQL/flexibleServers@2022-12-01' existing = {
  name: serverName
}

// Rule names encode the IP so a rotation creates a new rule instead of
// silently mutating an old one. Azure does not guarantee stable outbound IPs
// for Consumption environments: if they rotate, DB connections fail loudly
// until `just deploy-infra` is re-run to pick up the new IPs. Incremental
// deployments never delete rules — stale ones must be removed with
// `az postgres flexible-server firewall-rule delete`.
resource acaRules 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2022-12-01' = [
  for ip in acaOutboundIps: {
    parent: server
    name: 'AllowAca-${replace(ip, '.', '-')}'
    properties: {
      startIpAddress: ip
      endIpAddress: ip
    }
  }
]

resource homeRule 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2022-12-01' = if (homeClientIp != '') {
  parent: server
  name: 'AllowHomeClient'
  properties: {
    startIpAddress: homeClientIp
    endIpAddress: homeClientIp
  }
}
