"""Health API routes
- WIP, just scaffolding for now
"""

from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/health")
def health_check():
    return {"status": "healthy"}
