from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool, text

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
_sa_url = _raw_url.replace("postgresql://", "postgresql+psycopg://", 1)
config.set_main_option("sqlalchemy.url", _sa_url)

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
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
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
