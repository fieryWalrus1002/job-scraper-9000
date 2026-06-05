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

connect-az-db:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "===> pgcli connect to Azure PostgreSQL..."
    pgcli -h "${AZURE_POSTGRES_SERVER}" -p 5432 -U "${AZURE_POSTGRES_USER}" -d "${AZURE_POSTGRES_DB}"


watch-az-ingest:
    watch -n 15 'az containerapp job execution list \
        --name jobscraper-ingest-job \
        --resource-group rg-jobscraper \
        --query "[].{name:name,status:properties.status,start:properties.startTime}" \
        -o table'
