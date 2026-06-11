from __future__ import annotations

import logging
import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine, pool, text

load_dotenv()

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

log = logging.getLogger("alembic.env")

# App-wide id for the migration advisory lock (arbitrary constant, "jobs" in
# hex). Concurrent `alembic upgrade` runs — multiple ACA replicas migrating on
# lifespan startup during a rolling deploy, or a CLI run alongside them —
# serialize on this lock instead of racing through the version table (#153).
_MIGRATION_LOCK_ID = 0x6A6F6273

# Build the SQLAlchemy URL from DATABASE_URL, switching to the psycopg3 driver.
_raw_url = os.environ.get("DATABASE_URL")
if not _raw_url:
    raise RuntimeError(
        "DATABASE_URL is not set — create a .env file or export it before running migrations"
    )
# Pass the URL straight to create_engine instead of set_main_option, which would
# run it through configparser's BasicInterpolation and choke on '%' in the password.
_sa_url = _raw_url.replace("postgresql://", "postgresql+psycopg://", 1)

target_metadata = None


def run_migrations_offline() -> None:
    context.configure(
        url=_sa_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema="app",
    )
    with context.begin_transaction():
        context.run_migrations()


# Fail fast if the DB is unreachable rather than waiting for the OS TCP timeout (~63 s).
_CONNECT_TIMEOUT_S = 5


def run_migrations_online() -> None:
    connectable = create_engine(
        _sa_url,
        poolclass=pool.NullPool,
        connect_args={"connect_timeout": _CONNECT_TIMEOUT_S},
    )
    with connectable.connect() as connection:
        # Session-level advisory lock: survives commits and is held until this
        # connection closes at the end of the `with` block, so the schema
        # bootstrap and every migration run under it.
        locked = connection.execute(
            text("SELECT pg_try_advisory_lock(:id)"), {"id": _MIGRATION_LOCK_ID}
        ).scalar()
        if not locked:
            log.info("Migration advisory lock held by another process; waiting…")
            connection.execute(
                text("SELECT pg_advisory_lock(:id)"), {"id": _MIGRATION_LOCK_ID}
            )
            log.info("Migration advisory lock acquired; continuing")
        # app schema must exist before Alembic creates its version table there.
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS app"))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema="app",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
