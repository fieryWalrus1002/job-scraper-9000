param location string
param prefix string

// Default hostname of the linked Static Web App (e.g. lemon-moss-...azurestaticapps.net).
// Used as the azureStaticWebApps auth provider clientId on the authConfig below.
param swaHostname string

// CAUTION: VNet injection is create-time-only. Changing this on a live
// environment fails — the env must be deleted and recreated (runbook in
// infra/README.md, #161).
param infrastructureSubnetId string

param logAnalyticsCustomerId string

@secure()
param authConfig string

@secure()
param logAnalyticsSharedKey string

param acrLoginServer string

@description('Resource ID of the user-assigned identity that holds AcrPull on the registry.')
param acrPullIdentityId string

@secure()
param databaseUrl string

// Set to 'placeholder' on first deploy before the real image exists in ACR.
// After pushing the image, redeploy with the real tag.
param imageTag string = 'placeholder'

resource acaEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${prefix}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsCustomerId
        sharedKey: logAnalyticsSharedKey
      }
    }
    vnetConfiguration: {
      infrastructureSubnetId: infrastructureSubnetId
      // internal: false keeps the public ingress endpoint — required by the
      // SWA linked backend (#133); the trust boundary stays Easy Auth (#152),
      // not network reachability. Only DB traffic moves onto the VNet (#161).
      internal: false
    }
  }
}

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${prefix}-api'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${acrPullIdentityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: acaEnv.id
    configuration: {
      ingress: {
        // external: true so SWA can reach it via linked-backend proxy.
        //
        // SECURITY: external ingress is NOT made safe by FastAPI-layer auth.
        // FastAPI trusts X-MS-CLIENT-PRINCIPAL, which any direct caller could
        // forge. The real trust boundary is ACA built-in auth (Easy Auth) with
        // the azureStaticWebApps identity provider — see the `apiAuth`
        // authConfig resource below, which rejects any request not
        // authenticated through the linked SWA *before* it reaches the
        // container. Codified in #152 so a redeploy can't silently drop the
        // boundary (it was previously applied out-of-band when the SWA backend
        // was linked).
        external: true
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
      }
      registries: [
        {
          server: acrLoginServer
          identity: acrPullIdentityId
        }
      ]
      secrets: [
        {
          name: 'database-url'
          value: databaseUrl
        }
        {
          name: 'auth-config'
          value: authConfig
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: imageTag == 'placeholder'
            ? 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
            : '${acrLoginServer}/${prefix}-api:${imageTag}'
          env: [
            {
              name: 'AUTH_BYPASS'
              value: '0'
            }
            {
              name: 'DATABASE_URL'
              secretRef: 'database-url'
            }
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          volumeMounts: [
            {
              volumeName: 'auth-config-vol'
              mountPath: '/app/config'
            }
          ]
        }
      ]
      volumes: [
        {
          name: 'auth-config-vol'
          storageType: 'Secret'
          secrets: [
            {
              secretRef: 'auth-config'
              path: 'auth.yml'
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
      }
    }
  }
}

// The trust boundary for #152. ACA built-in auth (Easy Auth) rejects any
// request that did not arrive authenticated through the linked SWA, before it
// reaches the container — so the forgeable X-MS-CLIENT-PRINCIPAL header can
// only be set by the SWA proxy, never by a direct caller of the external FQDN.
resource apiAuth 'Microsoft.App/containerApps/authConfigs@2024-03-01' = {
  parent: api
  name: 'current'
  properties: {
    platform: {
      enabled: true
    }
    globalValidation: {
      // Return401 (not RedirectToLoginPage): this is an API backend, not a
      // browser surface. The interactive login flow lives in front, on the SWA.
      unauthenticatedClientAction: 'Return401'
    }
    identityProviders: {
      azureStaticWebApps: {
        enabled: true
        registration: {
          clientId: swaHostname
        }
      }
    }
  }
}

output containerAppId string = api.id
output containerAppFqdn string = api.properties.configuration.ingress.fqdn
output acaEnvironmentId string = acaEnv.id
