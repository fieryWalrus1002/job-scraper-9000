FROM ghcr.io/astral-sh/uv:python3.13-bookworm AS builder
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-editable --no-install-project

FROM python:3.13-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY src/ingest ./ingest
COPY db/schema.sql ./db/schema.sql
ENV PATH="/app/.venv/bin:$PATH"
ENTRYPOINT ["python", "-m", "ingest.cli"]
