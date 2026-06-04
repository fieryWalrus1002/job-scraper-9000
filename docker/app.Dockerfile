# These will be served in Azure Container Apps as two separate container targets, but
# we can build them together in one Dockerfile to share the common dependency installation step.
# Or split em up. Docker will cache the first few layers anyway so it doesn't make much difference.

# STAGE 1: Shared Builder
FROM ghcr.io/astral-sh/uv:python3.13-bookworm AS builder
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-editable --no-install-project

# STAGE 2: Backend Runtime Target
FROM python:3.13-slim-bookworm AS backend
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY src/ /app/src/
COPY config/ /app/config/
ENV PATH="/app/.venv/bin:$PATH"

# TODO: Need to mount the proper data/ folder it will be reading and writing

EXPOSE 8000
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# STAGE 3: Scraper Runtime Target
FROM python:3.13-slim-bookworm AS scraper
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY src/ /app/src/
COPY config/ /app/config/
ENV PATH="/app/.venv/bin:$PATH"

# Defaults to running the overnight pipeline
# TODO: Still gotta set up the mounting for the data volumes it will write to,
# but this is the basic idea for the scraper container target.
CMD ["job-scraper-9000", "pipeline"]
