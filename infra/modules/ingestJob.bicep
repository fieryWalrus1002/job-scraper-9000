param location string
param prefix string
param acaEnvironmentId string
param acrLoginServer string

@description('Resource ID of the user-assigned identity that holds AcrPull on the registry.')
param acrPullIdentityId string

@secure()
param databaseUrl string

@secure()
param storageConnectionString string

// Set to 'placeholder' on first deploy before the real image exists in ACR.
param imageTag string = 'placeholder'

resource ingestJob 'Microsoft.App/jobs@2024-03-01' = {
  name: '${prefix}-ingest-job'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${acrPullIdentityId}': {}
    }
  }
  properties: {
    environmentId: acaEnvironmentId
    configuration: {
      triggerType: 'Event'
      replicaTimeout: 1800
      replicaRetryLimit: 1
      eventTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
        scale: {
          minExecutions: 0
          maxExecutions: 1
          pollingInterval: 60
          rules: [
            {
              name: 'blob-trigger'
              type: 'azure-blob'
              metadata: {
                blobContainerName: 'pending'
                blobCountPerJob: '1'
              }
              auth: [
                {
                  secretRef: 'storage-conn-str'
                  triggerParameter: 'connection'
                }
              ]
            }
          ]
        }
      }
      secrets: [
        { name: 'database-url', value: databaseUrl }
        { name: 'storage-conn-str', value: storageConnectionString }
      ]
      registries: [
        {
          server: acrLoginServer
          identity: acrPullIdentityId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'ingest'
          image: imageTag == 'placeholder'
            ? 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
            : '${acrLoginServer}/${prefix}-ingest:${imageTag}'
          command: [
            'python'
            '-m'
            'ingest.cli'
            '--schema-path'
            'db/schema.sql'
            '--apply-schema'
            '--blob-mode'
          ]
          env: [
            { name: 'DATABASE_URL', secretRef: 'database-url' }
            { name: 'AZURE_STORAGE_CONNECTION_STRING', secretRef: 'storage-conn-str' }
          ]
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
        }
      ]
    }
  }
}
