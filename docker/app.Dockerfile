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
COPY alembic.ini ./
COPY migrations/ ./migrations/
ENV PATH="/app/.venv/bin:$PATH"
# The image installs deps with --no-install-project, so first-party packages
# aren't pip-installed — they run straight off /app/src and must be importable
# as top-level modules (the same layout as local `uv sync` and the tests:
# `from api...`, `from user_config import ...`). Without this, any absolute
# cross-package import (e.g. the settings router importing user_config) raises
# ModuleNotFoundError at startup and the app crash-loops.
ENV PYTHONPATH="/app/src"

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

# STAGE 4: CI/CD Utility Target (Reviewer & Summarizer)
FROM ghcr.io/astral-sh/uv:python3.13-bookworm AS ci-runner
WORKDIR /app

# Project manifests, so the frozen sync below has project context.
COPY pyproject.toml uv.lock ./

# Reuse the resolved virtualenv from the builder stage.
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"

# Source and scripts for the review/summarizer tooling. `prompts/` is
# force-included by the hatch wheel build (pyproject.toml), so the sync below
# fails without it.
COPY src/ /app/src/
COPY scripts/ /app/scripts/
COPY prompts/ /app/prompts/

# Manifests and force-included assets are present, so this resolves against the
# locked dependencies.
RUN uv sync --frozen

# Default to an interactive shell for the CI/CD utility container.
CMD ["/bin/bash"]
