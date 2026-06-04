param location string
param prefix string
param logAnalyticsCustomerId string

@secure()
param logAnalyticsSharedKey string

param acrLoginServer string

@secure()
param acrPassword string

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
  }
}

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${prefix}-api'
  location: location
  properties: {
    managedEnvironmentId: acaEnv.id
    configuration: {
      ingress: {
        // external: true so SWA can reach it via linked-backend proxy.
        // Auth is enforced at the FastAPI layer on every request regardless.
        external: true
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
      }
      registries: [
        {
          server: acrLoginServer
          username: replace(acrLoginServer, '.azurecr.io', '')
          passwordSecretRef: 'acr-password'
        }
      ]
      secrets: [
        {
          name: 'acr-password'
          value: acrPassword
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
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
      }
    }
  }
}

output containerAppId string = api.id
output containerAppFqdn string = api.properties.configuration.ingress.fqdn
