"""Dependencies for the API, including route imports and any shared utilities"""

from typing import Annotated
from fastapi import Depends, Request
from psycopg_pool import AsyncConnectionPool
from .auth import Principal, current_principal
from .schemas import User
from .starter_set import ensure_starter_set
from .users import get_or_provision_user


async def get_pool(request: Request) -> AsyncConnectionPool:
    # Safely retrieve the pool from the FastAPI app state
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        raise RuntimeError("Connection pool not initialized")
    return pool


Pool = Annotated[AsyncConnectionPool, Depends(get_pool)]
Auth = Annotated[Principal, Depends(current_principal)]


async def current_user(pool: Pool, principal: Auth) -> User:
    async with pool.connection() as conn:
        row = await get_or_provision_user(conn, principal)
        await ensure_starter_set(conn, row)
    return User.model_validate(row)


CurrentUser = Annotated[User, Depends(current_user)]
