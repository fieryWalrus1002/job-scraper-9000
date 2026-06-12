# Justfile
# Call it like this: just pipeline DATE=2026-05-27

# Automatically load a .env file from the repo root into all recipes
set dotenv-load

# Default to today's date using backticks, but customizable
DATE := `date +%F`

scrape:
    uv run job-scraper-9000 run-config config/search.yml --save --run-date {{DATE}}

prefilter:
    uv run job-scraper-9000 prefilter --run-date {{DATE}}

filter-remote:
    uv run job-scraper-9000 remote-filter --run-date {{DATE}}

filter-skills:
    uv run job-scraper-9000 skills-fit --run-date {{DATE}}

ingest DATE=DATE:
    uv run job-scraper-9000 ingest \
      --input "data/scored/{{DATE}}/skills_fit_scored.jsonl" \
      --schema-path "db/schema.sql"

# Ingest a fresh db with this one
ingest-init DATE=DATE:
    uv run job-scraper-9000 ingest \
      --input "data/scored/{{DATE}}/skills_fit_scored.jsonl" \
      --schema-path "db/schema.sql" \
      --apply-schema

pipeline:
    just scrape
    just prefilter
    just filter-remote
    just filter-skills
    just ingest

run-overnight:
    #!/usr/bin/env bash
    set -euo pipefail
    DATABASE_URL="host=${AZURE_POSTGRES_SERVER} port=5432 dbname=${AZURE_POSTGRES_DB} user=${AZURE_POSTGRES_USER} password=${AZURE_POSTGRES_PASSWORD} sslmode=require" \
        uv run job-scraper-9000 overnight --run-date "$(date +%F)"

sync-types:
    uv run scripts/export_openapi.py --out frontend/openapi.json
    cd frontend && npx --no-install openapi-typescript openapi.json -o src/schema.gen.ts

frontend:
    cd frontend && npm run dev -- --port 5173

frontend-build:
    cd frontend && npm run build

frontend-lint:
    cd frontend && npm run lint

backend:
    @echo "Starting FastAPI backend on port 8000..."
    uv run uvicorn src.api.main:app --reload --port 8000

migrate:
    uv run alembic upgrade head

db-up:
    docker compose up db -d

db-down:
    docker compose down

dev:
    uv run honcho start

build-images:
    docker build --target backend -t job-api -f docker/app.Dockerfile .
    docker build --target scraper -t job-scraper -f docker/app.Dockerfile .
    docker build -t job-ingest -f docker/ingest.Dockerfile .

# Upload scored JSONL to Azure Blob Storage pending container.
# Requires AZURE_STORAGE_ACCOUNT in .env and an active `az login` session
# (uses --auth-mode login; no AZURE_STORAGE_KEY needed).
upload-blob DATE=DATE:
    az storage blob upload \
      --account-name "$AZURE_STORAGE_ACCOUNT" \
      --container-name pending \
      --name "{{DATE}}/skills_fit_scored.jsonl" \
      --file "data/scored/{{DATE}}/skills_fit_scored.jsonl" \
      --auth-mode login \
      --overwrite

# Build and push the API container image to Azure Container Registry and trigger a new revision
ship-api:
    #!/usr/bin/env bash
    set -euo pipefail

    echo "====> Fetching container registry details from Azure..."
    ACR_LOGIN_SERVER=$(az acr list -g rg-jobscraper --query "[0].loginServer" -o tsv)
    ACR_NAME="${ACR_LOGIN_SERVER%%.*}"

    echo "====> Authenticating with ACR: ${ACR_NAME}..."
    az acr login --name "${ACR_NAME}"

    echo "====> Building API image..."
    docker build --target backend -f docker/app.Dockerfile -t "${ACR_LOGIN_SERVER}/jobscraper-api:latest" .

    echo "====> Pushing image to Azure..."
    docker push "${ACR_LOGIN_SERVER}/jobscraper-api:latest"

    echo "====> Triggering new ACA revision..."
    az containerapp update \
      --name jobscraper-api \
      --resource-group rg-jobscraper \
      --image "${ACR_LOGIN_SERVER}/jobscraper-api:latest"

    echo "====> Done! New revision is live."

# Build the frontend and deploy to Azure Static Web Apps.
# Requires an active `az login` session. Installs the SWA CLI on first run via npx.
ship-frontend:
    #!/usr/bin/env bash
    set -euo pipefail

    echo "====> Building frontend..."
    npm --prefix frontend ci
    AZURE_TENANT_ID=$(az account show --query tenantId -o tsv)
    (cd frontend && AZURE_TENANT_ID="$AZURE_TENANT_ID" npm run build)

    echo "====> Fetching SWA deployment token from Azure..."
    SWA_TOKEN=$(az staticwebapp secrets list \
        --name jobscraper-swa \
        --resource-group rg-jobscraper \
        --query "properties.apiKey" -o tsv)

    echo "====> Deploying to Azure Static Web Apps..."
    npx --yes @azure/static-web-apps-cli deploy ./frontend/dist \
        --deployment-token "$SWA_TOKEN" \
        --env production

    echo "====> Done! Live at https://lemon-moss-05209ca1e.7.azurestaticapps.net"


# Build and push the ingestion container image to Azure Container Registry
ship-ingest:
    #!/usr/bin/env bash
    set -euo pipefail

    echo "====> Fetching container registry details from Azure..."
    ACR_LOGIN_SERVER=$(az acr list -g rg-jobscraper --query "[0].loginServer" -o tsv)
    ACR_NAME="${ACR_LOGIN_SERVER%%.*}"

    echo "====> Authenticating with ACR: ${ACR_NAME}..."
    az acr login --name "${ACR_NAME}"

    echo "====> Building ingest container image..."
    docker build -f docker/ingest.Dockerfile -t "${ACR_LOGIN_SERVER}/jobscraper-ingest:latest" .

    echo "====> Pushing image to Azure..."
    docker push "${ACR_LOGIN_SERVER}/jobscraper-ingest:latest"

    echo "====> Success! Image is live at ${ACR_LOGIN_SERVER}/jobscraper-ingest:latest"

# Deploy or update Azure infrastructure via Bicep.
# Secrets are passed at runtime from .env — never stored in main.bicepparam.
# Requires: AZURE_POSTGRES_PASSWORD and AZURE_CLIENT_SECRET in .env, config/auth.yml present.
# Optional: HOME_CLIENT_IP in .env for the Postgres AllowHomeClient firewall rule.
# Must run as an Owner-level identity: the template creates an AcrPull role assignment.
deploy-infra:
    #!/usr/bin/env bash
    set -euo pipefail
    export AUTH_CONFIG="$(cat config/auth.yml)"

    az deployment group create \
      --resource-group rg-jobscraper \
      --template-file infra/main.bicep \
      --parameters infra/main.bicepparam

connect-az-db:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "===> pgcli connect to Azure PostgreSQL..."
    PGPASSWORD=${AZURE_POSTGRES_PASSWORD} pgcli -h "${AZURE_POSTGRES_SERVER}" -p 5432 -U "${AZURE_POSTGRES_USER}" -d "${AZURE_POSTGRES_DB}"

# Push a user's filled config into the AZURE DB (not local).
#   just push-user-config-az --user-email a@b.com --profile F --search F
push-user-config-az *ARGS:
    #!/usr/bin/env bash
    set -euo pipefail
    DATABASE_URL="host=${AZURE_POSTGRES_SERVER} port=5432 dbname=${AZURE_POSTGRES_DB} user=${AZURE_POSTGRES_USER} password=${AZURE_POSTGRES_PASSWORD} sslmode=require" \
        uv run scripts/push_user_config.py {{ARGS}}

# Materialize user configs FROM the AZURE DB into runs/<user>/ (not local).
#   just pull-user-configs-az --all   |   just pull-user-configs-az --user-email a@b.com
pull-user-configs-az *ARGS:
    #!/usr/bin/env bash
    set -euo pipefail
    DATABASE_URL="host=${AZURE_POSTGRES_SERVER} port=5432 dbname=${AZURE_POSTGRES_DB} user=${AZURE_POSTGRES_USER} password=${AZURE_POSTGRES_PASSWORD} sslmode=require" \
        uv run scripts/pull_user_configs.py {{ARGS}}

watch-az-ingest:
    watch -n 15 'az containerapp job execution list \
        --name jobscraper-ingest-job \
        --resource-group rg-jobscraper \
        --query "[].{name:name,status:properties.status,start:properties.startTime}" \
        -o table'
