FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN uv pip install --system psycopg[binary] azure-storage-blob

COPY src/ingest ./ingest
COPY db/schema.sql ./db/schema.sql

ENTRYPOINT ["python", "-m", "ingest.cli"]
