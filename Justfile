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
