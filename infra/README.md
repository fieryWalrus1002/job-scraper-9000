# Job Scraper 9000 - Azure Infrastructure

```bash
# Create resource group (first time only):
az group create --name rg-jobscraper --location westus2

# Deploy:
az deployment group create \
--resource-group rg-jobscraper \
--template-file main.bicep \
--parameters main.bicepparam \
--parameters clientSecret=${CLIENT_SECRET}

# After deploy, link the SWA backend (manual step):
az staticwebapp backends link \
--name jobscraper-swa \
--resource-group rg-jobscraper \
--backend-resource-id <containerAppId from outputs> \
--backend-region eastus
```

Also update `frontend/public/staticwebapp.config.json` with your tenant ID before deploying the frontend.

## Known issues

**First deploy fails on container app — image not found**

On initial deploy the ACR is empty, so the container app revision fails with `MANIFEST_UNKNOWN: manifest tagged by "latest" is not found`. Fix: set `imageTag = 'placeholder'` in `main.bicepparam` for the first deploy. This swaps in `mcr.microsoft.com/azuredocs/containerapps-helloworld:latest` so the container app provisions successfully. After building and pushing the real image to ACR, redeploy with the actual tag.

```bash
az deployment group show -g rg-jobscraper -n main --query properties.outputs
```

This will then return the following output with the values you need to update in `frontend/public/staticwebapp.config.json` and link the SWA backend:

```json
{
  "acrLoginServer": {
    "type": "String",
    "value": "jobscraperyuohc35a34v2g.azurecr.io"
  },
  "containerAppFqdn": {
    "type": "String",
    "value": "jobscraper-api.happywave-b8ffb476.westus2.azurecontainerapps.io"
  },
  "containerAppId": {
    "type": "String",
    "value": "/subscriptions/1f487098-d357-4feb-86a2-2d50cf33ab58/resourceGroups/rg-jobscraper/providers/Microsoft.App/containerApps/jobscraper-api"
  },
  "swaUrl": {
    "type": "String",
    "value": "https://lemon-moss-05209ca1e.7.azurestaticapps.net"
  }
}
```

Like so:

```bash
az staticwebapp backends link \
--name jobscraper-swa \
--resource-group rg-jobscraper \
--backend-resource-id /subscriptions/1f487098-d357-4feb-86a2-2d50cf33ab58/resourceGroups/rg-jobscraper/providers/Microsoft.App/containerApps/jobscraper-api \
--backend-region westus2
```

And then you'll need to get into the EntraId portal to add the redirect URI. It was:
Entra ID → App registrations → job-scraper-9000 → Authentication → Add a platform → Web

Set redirect URI to:
https://lemon-moss-05209ca1e.7.azurestaticapps.net/.auth/login/aad/callback

Next,you can visit it. At this time, it was a "please check back later" message, but thats because we haven't deployed the frontend yet. After we deploy the frontend, you should see the actual app.

You can check the backend status with:

```bash
az staticwebapp backends show -n jobscraper-swa -g rg-jobscraper
```

## Building and pushing the backend image

Now we're building the frontend, which will push the image to ACR, so we can redeploy the bicep with the correct image tag and link the SWA backend. After that, we should be good to go!

```bash
# Log in to ACR
az acr login --name jobscraperyuohc35a34v2g

# Build and push the backend image to ACR
docker build -f docker/app.Dockerfile --target backend -t jobscraperyuohc35a34v2g.azurecr.io/jobscraper-api:latest .

# Push to ACR
docker push jobscraperyuohc35a34v2g.azurecr.io/jobscraper-api:latest
```

## Create the resources with the correct image tag

We just run the same command we used above, and bicep will figure out what changed and update the container app with the new image tag.

## Deploy the frontend to SWA

Deploy the frontend to SWA. First build it, then get the deployment token and push:

```bash
cd frontend && npm run build
az staticwebapp secrets list \
--name jobscraper-swa \
--resource-group rg-jobscraper \
--query "properties.apiKey" -o tsv
```

Then deploy with the token:

```bash
npx @azure/static-web-apps-cli deploy dist \
--deployment-token $SWA_TOKEN \
--env production
```

This required the install of `@azure/static-web-apps-cli@2.0.9` globally.

It should work fine. If you're dumb and forgot to add the email you're using in config/auth.yml, then you'll need to rebuild and run this:

```bash
az containerapp update \
--name jobscraper-api \
--resource-group rg-jobscraper \
--resource-group rg-jobscraper \
--image jobscraperyuohc35a34v2g.azurecr.io/jobscraper-api:latest
```

This will update the container app, which will trigger the SWA backend to update, which will trigger the frontend to update, and then you should be good to go!

## Deploying with database

The Bicep now provisions a PostgreSQL Flexible Server and wires `DATABASE_URL`
into the container app automatically. Pass `dbAdminPassword` at deploy time
(same pattern as `clientSecret`):

```bash
az deployment group create \
  --resource-group rg-jobscraper \
  --template-file infra/main.bicep \
  --parameters infra/main.bicepparam \
  --parameters clientSecret='<your-client-secret>' \
  --parameters dbAdminPassword='<your-db-password>'
```

After the deploy completes, run the schema migration once:

```bash
just db-init DATABASE_URL="postgresql://dbadmin:<pw>@<server-fqdn>:5432/jobscraper?sslmode=require"
```

The server FQDN is in the deployment outputs:

```bash
az deployment group show -g rg-jobscraper -n main --query properties.outputs
```

> **Note:** `DATABASE_URL` is stored as an ACA secret (`secretref:database-url`) so
> the connection string is not exposed in plain-text env vars. Managed Identity
> would be the next step up in security posture but requires more Entra ID setup.

## Injecting DATABASE_URL

`DATABASE_URL` must be set as a secret-backed env var — not a plain env var — so the connection string isn't exposed in the ACA config.

```bash
# Store the connection string as an ACA secret
az containerapp secret set \
  --name jobscraper-api \
  --resource-group rg-jobscraper \
  --secrets "database-url=<postgres-connection-string>"

# Wire the secret to the DATABASE_URL env var
az containerapp update \
  --name jobscraper-api \
  --resource-group rg-jobscraper \
  --set-env-vars "DATABASE_URL=secretref:database-url"
```

The connection string format for psycopg is:
`postgresql://user:password@host:5432/dbname?sslmode=require`

To verify the secret is wired correctly (value will show as `secretref:database-url`, not the raw string):

```bash
az containerapp show \
  --name jobscraper-api \
  --resource-group rg-jobscraper \
  --query "properties.template.containers[0].env"
```

## Backend deployment

Register the Microsoft.App provider if you haven't already:

```bash
az provider show -n Microsoft.App --query registrationState -o tsv
```

It returned Registered for me. Next step, containerapp udpate:

```bash
az containerapp update \
--name jobscraper-api \
--resource-group rg-jobscraper \
--image jobscraperyuohc35a34v2g.azurecr.io/jobscraper-api:latest
```
