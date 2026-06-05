FROM python:3.13-slim

# Set system environment variables for python optimization
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies if required by psycopg (binary version handles this cleanly)
# Install uv to manage dependencies instantly inside the container
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install only the production runtime dependency required by the script
RUN uv pip install --system psycopg[binary]

# Copy the two explicit files needed for execution
COPY db/schema.sql ./db/schema.sql
COPY scripts/db_ingest.py ./db_ingest.py

# Make the execution script executable
RUN chmod +x ./db_ingest.py

# Set the default entrypoint to your deterministic script
ENTRYPOINT ["python3", "./db_ingest.py"]
