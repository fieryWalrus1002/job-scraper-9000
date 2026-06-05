# docker/README.md

This folder contains the Dockerfiles and related configuration for containerizing the scraper, the backend, and the frontend components.

## Backend & Scraper Containerization

The FastAPI backend and the scraper pipelines are built from the `app.Dockerfile`. It is structured with multi-stage builds to optimize layer caching and image size, allowing us to build both targets from a shared dependency installation step.

The backend target is set up to run the FastAPI application, while the scraper target is configured to execute the job scraping pipeline. Both targets will need proper volume mounting for the data they read and write, which will be configured in the deployment stage when we set up Azure Container Apps.

## Frontend Containerization

The frontend is intended to be deployed to Azure Static Web Apps, which does not require a custom Dockerfile. For local integration testing, I've included a `frontend.Dockerfile` that builds the React application and serves it using a simple static file server. This allows us to run the frontend in a container locally while connecting to the backend API also running in a container, simulating the production environment more closely.

## Deployment

With these dockerfiles, we're reaching past the local dev stage and preparing for deployment to Azure Cloud.

### 1. Local Integration Testing

The integration testing workflow involves running our frontend, backend, and pipeline via Docker Compose to guarantee local environment symmetry. The backend will be exposed on port 8000, while the frontend runs on port 8080.

To start the local environment, you can run:

```bash
docker compose up
```

This will start both the backend and the frontend, but will not automatically run the scraper pipeline. To trigger the scraper pipeline, you can use:

```bash
docker compose run --rm scraper
```

At this point we'll have two long-running dockerized services active locally: the FastAPI backend (reading/writing to the shared data volume) and the React frontend that connects to it.

### 2. Azure Container Apps Deployment

Using Bicep templates we can automate the provisioning of the Azure resources. GitHub Actions will be set up to handle the CI/CD pipeline, automatically building and pushing the Docker images to Azure Container Registry and deploying the frontend to Azure Static Web Apps on push to the main branch.

We will need to provision the following Azure resources:

- An Azure Container App for the FastAPI backend
- An Azure Container Apps Job for the scraper pipeline
- An Azure Static Web App for the React frontend
- An Azure Storage Account for the data storage (Azure Files or Azure Blob Storage)

The backend will be configured to scale down to zero when idle. The scraper will run nightly. Both of these will have the necessary environment variables and volume mounts configured to access shared data storage.

As the frontend will be deployed to Azure Static Web Apps, it will not use the same Dockerfile we used for integration testing. Instead, it will be built and deployed directly from the React source code. The frontend will route API requests seamlessly using relative paths (/api/...).

### 3. Blob Storage Ingest Pipeline

Scored JSONL files are uploaded to an Azure Storage Account (`pending` container). An Azure Container Apps Job watches that container with a KEDA `azure-blob` trigger — when a blob arrives, the job spins up, ingests the data into PostgreSQL, and moves the blob to the `processed` container. The Bicep for the storage account and job lives in `infra/modules/storageAccount.bicep` and `infra/modules/ingestJob.bicep`.

#### Build and push the ingest image

```bash
docker build -f docker/ingest.Dockerfile -t <YOUR-ACR-LOGIN-SERVER>/jobscraper-ingest:latest .
docker push <YOUR-ACR-LOGIN-SERVER>/jobscraper-ingest:latest
```

#### Upload a scored file (triggers the ingest job)

```bash
# From repo root — AZURE_STORAGE_ACCOUNT must be set in .env
just upload-blob DATE=2026-06-04
```

The KEDA trigger polls every 60 s. Once the blob is detected, the ACA Job fires, ingests the data, and moves the blob to `processed/`.

#### Testing the ingest container locally

```bash
# 1. Build
docker build -f docker/ingest.Dockerfile -t jobscraper-ingest:latest .

# 2. Run against local Postgres with a file mount
docker run --rm \
  --network="host" \
  -v "$(pwd)/data:/app/data" \
  jobscraper-ingest:latest \
  --db-url "postgresql://jobscraper:jobscraper@127.0.0.1:5432/jobscraper" \
  --input "/app/data/scored/2026-06-04/skills_fit_scored.jsonl" \
  --schema-path "/app/db/schema.sql"

# 3. Test blob mode locally (needs a real storage account or Azurite)
docker run --rm \
  --network="host" \
  -e DATABASE_URL="postgresql://jobscraper:jobscraper@127.0.0.1:5432/jobscraper" \
  -e AZURE_STORAGE_CONNECTION_STRING="<connection-string>" \
  jobscraper-ingest:latest \
  --schema-path "db/schema.sql" \
  --apply-schema \
  --blob-mode
```
