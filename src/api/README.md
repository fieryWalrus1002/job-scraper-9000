# FastAPI Backend

Read-only REST API serving scored job postings from the `raw.scored_job_postings` Postgres table.

## Endpoints

| Method | Path                     | Description                     |
| ------ | ------------------------ | ------------------------------- |
| `GET`  | `/api/health`            | Health check                    |
| `GET`  | `/api/jobs`              | Paginated job list with filters |
| `GET`  | `/api/jobs/{dedup_hash}` | Full job detail                 |

### `GET /api/jobs` query params

| Param                             | Type                     | Description                                                                                           |
| --------------------------------- | ------------------------ | ----------------------------------------------------------------------------------------------------- |
| `min_score` / `max_score`         | int 1–5                  | Filter by fit score                                                                                   |
| `remote_classification`           | enum                     | `fully_remote`, `location_restricted`, `remote_with_occasional_travel`, `remote_with_frequent_travel` |
| `min_posted_at` / `max_posted_at` | date                     | Filter by posting date                                                                                |
| `search`                          | string ≤200              | ILIKE search on title + description                                                                   |
| `limit`                           | int 1–1000 (default 500) | Page size                                                                                             |
| `offset`                          | int ≥0 (default 0)       | Page offset                                                                                           |

## Running locally

```bash
just backend          # uvicorn on :8000
just frontend         # Vite dev server on :5173 (proxies /api → :8000)
just dev              # both via honcho
```

Requires `DATABASE_URL` in `.env`:

```
DATABASE_URL=postgresql://jobscraper:jobscraper@localhost:5432/jobscraper
```

## Tests

```bash
uv run pytest tests/api/
```

No live database required — tests use a mock connection pool via `app.dependency_overrides`.
