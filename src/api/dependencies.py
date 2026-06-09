"""Dependencies for the API, including route imports and any shared utilities"""

from typing import Annotated
from fastapi import Depends, Request
from psycopg_pool import AsyncConnectionPool
from .auth import Principal, current_principal


async def get_pool(request: Request) -> AsyncConnectionPool:
    # Safely retrieve the pool from the FastAPI app state
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        raise RuntimeError("Connection pool not initialized")
    return pool


Pool = Annotated[AsyncConnectionPool, Depends(get_pool)]
Auth = Annotated[Principal, Depends(current_principal)]
