from fastapi import APIRouter

from ..dependencies import CurrentUser
from ..schemas import User

router = APIRouter(prefix="/me", tags=["Me"])


@router.get("", response_model=User)
async def get_me(user: CurrentUser):
    """The authenticated user's own record — drives role-aware frontend UI."""
    return user
