from __future__ import annotations

import asyncio
import logging
import os
import sys
import traceback
from contextlib import asynccontextmanager
from typing import NoReturn

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from . import auth as _auth
from .routes import (
    applications_router,
    eval_router,
    health_router,
    jobs_router,
    me_router,
    settings_router,
    upcoming_steps_router,
)
from .users import sync_users


load_dotenv()

# Without this, the root logger sits at WARNING with no handler and every
# log.info() in the API (JIT-link events, the one-time claim-keys line) is
# silently dropped in production — only the raw sys.stderr writes survive.
# basicConfig is a no-op if a handler is already configured (e.g. by tests).
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(levelname)s [%(name)s] %(message)s",
)

log = logging.getLogger(__name__)


async def _flush_and_exit(msg: str, code: int = 3) -> NoReturn:
    """Write `msg` to stderr, sleep so the ACA log shipper can forward it, then exit `code`."""
    sys.stderr.write(msg)
    sys.stderr.flush()
    delay = int(os.environ.get("LOG_FLUSH_DELAY", "5"))
    await asyncio.sleep(delay)
    sys.exit(code)


@asynccontextmanager
async def lifespan(app: FastAPI):
    url = os.environ.get("DATABASE_URL")
    if not url:
        _msg = (
            "\n" + "=" * 60 + "\n"
            "CRITICAL CONFIGURATION ERROR:\n"
            "DATABASE_URL environment variable is missing or empty.\n"
            "The application cannot start without a database connection.\n"
            + "=" * 60
            + "\n"
        )
        log.critical(_msg)
        await _flush_and_exit(_msg)

    def _run_migrations() -> None:
        cfg = AlembicConfig("alembic.ini")
        alembic_command.upgrade(cfg, "head")

    try:
        sys.stderr.write("STARTUP: running Alembic migrations…\n")
        sys.stderr.flush()
        await asyncio.to_thread(_run_migrations)
        sys.stderr.write("STARTUP: migrations complete\n")
        sys.stderr.flush()

        pool = AsyncConnectionPool(
            url,
            kwargs={"row_factory": dict_row, "connect_timeout": 5},
            min_size=2,
            max_size=10,
            open=False,
        )
        await pool.open()
        app.state.pool = pool

        sys.stderr.write("STARTUP: db pool open\n")
        sys.stderr.flush()

        if os.environ.get(_auth.BYPASS_VAR) == "1":
            sys.stderr.write("STARTUP: auth bypass (dev) — do not use in production\n")
            sys.stderr.flush()
        else:
            auth_users = _auth.load_auth_config()
            _auth.init(auth_users)
            async with pool.connection() as conn:
                await sync_users(conn, auth_users)
            sys.stderr.write(
                f"STARTUP: auth enforced (allowlist={len(auth_users)} entries), "
                "users synced\n"
            )
            sys.stderr.flush()
    except Exception:
        _msg = (
            "\n" + "=" * 60 + "\n"
            "CRITICAL STARTUP FAILURE:\n" + traceback.format_exc() + "=" * 60 + "\n"
        )
        log.critical(_msg)
        await _flush_and_exit(_msg)

    yield
    if getattr(app.state, "pool", None) is not None:
        await app.state.pool.close()


app = FastAPI(lifespan=lifespan)

# CORS is a fallback for direct API access (curl, Postman, non-proxied dev).
# Primary path in dev is the Vite proxy; in production, Azure SWA routes /api/*.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register the routers exposed by routes/__init__.py
app.include_router(health_router, prefix="/api")
app.include_router(jobs_router, prefix="/api")
app.include_router(applications_router, prefix="/api")
app.include_router(eval_router, prefix="/api")
app.include_router(me_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(upcoming_steps_router, prefix="/api")
