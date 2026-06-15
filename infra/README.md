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

## ACR auth: managed identity, no admin credentials (#126)

The registry has `adminUserEnabled: false`. Image pulls use a shared
user-assigned managed identity (`modules/identity.bicep`) granted `AcrPull`
on the registry; no registry password exists anywhere in ACA secrets.

- **CI and local pushes are unaffected**: `az acr login` exchanges an Entra
  token, and both the CI service principal (Contributor on the resource
  group) and your own account already have push/pull through RBAC.
- **Deploying needs Owner-level rights**: the template creates a role
  assignment, which requires `Microsoft.Authorization/roleAssignments/write`
  (Owner or User Access Administrator) on the resource group. Run
  `just deploy-infra` as yourself, not as the Contributor-only CI principal.
- **First-deploy flake**: RBAC propagation can lag a few minutes, so the
  first revision after switching to identity-based pulls may fail with an
  image-pull error. Re-running the deploy (or `az containerapp update`)
  fixes it.

## Postgres networking: private endpoint hybrid (#161)

App traffic to Postgres rides a private endpoint inside a custom VNet; the
server's public endpoint stays enabled but firewalled to a single
`AllowHomeClient` rule fed by `HOME_CLIENT_IP` in `.env` (personal info —
never committed). Flexible server supports both access modes at once.

- `modules/vnet.bicep` — VNet with an `aca-infra` /23 (consumption-only ACA
  minimum) and a `private-endpoints` /24.
- `modules/dbPrivateEndpoint.bicep` — private endpoint + the
  `privatelink.postgres.database.azure.com` zone, linked to the VNet.
- DNS is split-horizon: the same `DATABASE_URL` FQDN resolves to the private
  IP inside the VNet and the public IP from home, so `just connect-az-db`
  is unchanged.

### One-time cutover runbook (#161)

VNet injection on an ACA environment is **create-time-only** — `what-if`
shows it as an innocent property Create, but the deploy fails against the
live environment. The API is down between steps 2 and 3.

```bash
# 1. Unlink the SWA backend (it points at the app being deleted)
az staticwebapp backends unlink -n jobscraper-swa -g rg-jobscraper

# 2. Delete the apps, then the environment (env can't be deleted while apps exist)
az containerapp delete -n jobscraper-api -g rg-jobscraper --yes
az containerapp job delete -n jobscraper-ingest-job -g rg-jobscraper --yes
az containerapp env delete -n jobscraper-env -g rg-jobscraper --yes

# 3. Recreate everything (env in VNet, apps, PE, DNS, SWA relink)
just deploy-infra

# 4. Verify: app responds via SWA, then confirm the DB connection is private
az containerapp exec -n jobscraper-api -g rg-jobscraper --command sh
#   inside: getent hosts <db-fqdn>   -> should print a 10.10.2.x address
```

The SWA hostname and Entra redirect URI are unaffected (the link is by
resource ID, the auth boundary keys on the SWA hostname). The ACA FQDN
changes; nothing references it statically.

**Post-cutover firewall cleanup** — incremental deployments never delete
rules dropped from the template. Remove everything except `AllowHomeClient`:

```bash
az postgres flexible-server firewall-rule list -g rg-jobscraper --server-name <server> -o table
az postgres flexible-server firewall-rule delete -g rg-jobscraper --server-name <server> --rule-name AllowAzureServices --yes
# ...and any ClientIPAddress_* / legacy home-IP rules
```

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
    "value": "<YOUR-ACR-LOGIN-SERVER>"
  },
  "containerAppFqdn": {
    "type": "String",
    "value": "<YOUR-ACA-FQDN>"
  },
  "containerAppId": {
    "type": "String",
    "value": "/subscriptions/<YOUR-SUBSCRIPTION-ID>/resourceGroups/rg-jobscraper/providers/Microsoft.App/containerApps/jobscraper-api"
  },
  "swaUrl": {
    "type": "String",
    "value": "<YOUR-SWA-URL>"
  }
}
```

Like so:

```bash
az staticwebapp backends link \
--name jobscraper-swa \
--resource-group rg-jobscraper \
--backend-resource-id /subscriptions/<YOUR-SUBSCRIPTION-ID>/resourceGroups/rg-jobscraper/providers/Microsoft.App/containerApps/jobscraper-api \
--backend-region westus2
```

And then you'll need to get into the EntraId portal to add the redirect URI. It was:
Entra ID → App registrations → job-scraper-9000 → Authentication → Add a platform → Web

Set redirect URI to:
`<YOUR-SWA-URL>/.auth/login/aad/callback`

Next, you can visit it. At this time, it was a "please check back later" message, but that's because we haven't deployed the frontend yet. After we deploy the frontend, you should see the actual app.

You can check the backend status with:

```bash
az staticwebapp backends show -n jobscraper-swa -g rg-jobscraper
```

## Building and pushing the backend image

Now we're building the frontend, which will push the image to ACR, so we can redeploy the bicep with the correct image tag and link the SWA backend. After that, we should be good to go!

```bash
# Log in to ACR
az acr login --name <YOUR-ACR-NAME>

# Build and push the backend image to ACR
docker build -f docker/app.Dockerfile --target backend -t <YOUR-ACR-LOGIN-SERVER>/jobscraper-api:latest .

# Push to ACR
docker push <YOUR-ACR-LOGIN-SERVER>/jobscraper-api:latest
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
--image <YOUR-ACR-LOGIN-SERVER>/jobscraper-api:latest
```

This will update the container app, which will trigger the SWA backend to update, which will trigger the frontend to update, and then you should be good to go!

## Deploying with database

The Bicep now provisions a PostgreSQL Flexible Server and wires `DATABASE_URL`
into the container app automatically. Pass `dbAdminPassword` at deploy time
(same pattern as `clientSecret`):

```bash
az deployment group create \
  --resource-group rg-jobscraper \
  --template-file main.bicep \
  --parameters main.bicepparam \
  --parameters clientSecret='<your-client-secret>' \
  --parameters dbAdminPassword='<your-db-password>'
```

> **Note:** `DATABASE_URL` is stored as an ACA secret (`secretref:database-url`) so
> the connection string is not exposed in plain-text env vars. Managed Identity
> would be the next step up in security posture but requires more Entra ID setup.

Schema is owned by Alembic (migrations run on API lifespan startup); the ingest
job applies no DDL and ingests against the already-migrated database, which is
not exposed externally.

## Ingest: decoupled blob → ACA Job (Phase 15)

The overnight pipeline is **produce-only** — it writes per-user scored files
locally and never writes `raw.job_scores`. Ingest is fully decoupled and runs
*inside* Azure, next to the DB, so the home machine never needs a Postgres
firewall rule against the private-endpoint DB.

Flow:

1. **Produce** — `just run-overnight` writes
   `data/pipeline_runs/<run_id>/<slug>/skills_fit/scored.jsonl` per user. Each
   record is stamped with its owning `user_email`.

1. **Upload** — `just upload-blob RUN_ID=<run_id>` walks the run and uploads
   one blob per user to the `pending` container as
   `pending/<run_id>/<slug>__scored.jsonl`. Auth is AAD (`az --auth-mode login`);
   the operator's identity needs the **Storage Blob Data Contributor** role on
   the storage account (no account key on the laptop).

1. **Ingest** — the `<prefix>-ingest-job` ACA Job (`modules/ingestJob.bicep`)
   has a KEDA `azure-blob` trigger on `pending` (`blobCountPerJob=1`,
   `parallelism=1`), so **one blob per user fans out one Job execution per
   user**. It runs `python -m ingest.cli --blob-mode` and, per blob:

   - success → moves the blob to the `processed` container;
   - empty blob → `processed` (no-op success);
   - unparseable JSONL or unresolvable user → `failed` with a `reason` metadata
     tag (dead-letter, so KEDA doesn't re-trigger on the same poison blob).

   Records self-route by their stamped `user_email`, so the Job passes no global
   `--user-email`. The DB is reached over the private endpoint; storage uses an
   account-key connection string secret (moving the Job to managed identity is a
   tracked follow-up).

Watch executions:

```bash
just watch-az-ingest    # az containerapp job execution list, refreshed
```

### End-to-end dry-run validation (non-prod)

Validate the whole chain against a **non-prod** DB + storage account before
trusting a real overnight run — point `DATABASE_URL` / storage at a throwaway
target, never prod:

```bash
# 1. Produce a small run locally (or reuse an existing data/pipeline_runs/<run_id>).
just run-overnight                      # note the run_id from the summary

# 2. Dry-run the local ingest first — parses + resolves every user, writes nothing.
uv run scripts/ingest_run.py --run-id <run_id> --dry-run

# 3. Upload to the NON-PROD storage account's `pending` container.
AZURE_STORAGE_ACCOUNT=<nonprod-account> just upload-blob RUN_ID=<run_id>

# 4. Watch the ACA Job fan out one execution per blob; confirm blobs land in
#    `processed` (success) and none in `failed`.
just watch-az-ingest

# 5. Confirm scores in the non-prod DB, routed to the right users.
#    psql/pgcli: SELECT u.email, count(*) FROM raw.job_scores s
#                JOIN app.users u ON u.id = s.user_id GROUP BY u.email;
```

A blob in `failed/` carries a `reason` tag (`unparseable_jsonl` /
`unresolvable_user`) — inspect it, fix the cause, and re-upload; the dead-letter
means it won't silently retry.

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

It returned Registered for me. Next step, containerapp update:

```bash
az containerapp update \
--name jobscraper-api \
--resource-group rg-jobscraper \
--image <YOUR-ACR-LOGIN-SERVER>/jobscraper-api:latest
```
