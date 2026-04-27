"""
Health check endpoint.

Returns a simple status to verify the backend is running.
"""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}
