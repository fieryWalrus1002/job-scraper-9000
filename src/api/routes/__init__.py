from .health import router as health_router
from .jobs import router as jobs_router
from .applications import router as applications_router
from .eval import router as eval_router
from .me import router as me_router
from .settings import router as settings_router
from .upcoming_steps import router as upcoming_steps_router

# Gets around ruff's "F401 '...' imported but unused" for FastAPI routers
__all__ = [
    "health_router",
    "jobs_router",
    "applications_router",
    "eval_router",
    "me_router",
    "settings_router",
    "upcoming_steps_router",
]
