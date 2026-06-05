from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine, pool, text

load_dotenv()

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

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


def run_migrations_online() -> None:
    connectable = create_engine(_sa_url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
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
