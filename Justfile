# Justfile
# Call it like this: just pipeline DATE=2026-05-27

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

ingest:
    uv run scripts/db_ingest.py --run-date {{DATE}}

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

# Apply db/schema.sql to a target database. Pass DATABASE_URL explicitly for Azure:
#   just db-init DATABASE_URL="postgresql://dbadmin:<pw>@<fqdn>:5432/jobscraper?sslmode=require"
db-init DATABASE_URL='':
    uv run python -c "
import os, psycopg
url = '{{DATABASE_URL}}' or os.environ['DATABASE_URL']
sql = open('db/schema.sql').read()
with psycopg.connect(url) as conn:
    conn.autocommit = True
    conn.execute(sql)
print('schema applied')
"

db-up:
    docker compose up db -d

db-down:
    docker compose down

dev:
    uv run honcho start

build-images:
    docker build --target backend -t job-api -f docker/app.Dockerfile .
    docker build --target scraper -t job-scraper -f docker/app.Dockerfile .
