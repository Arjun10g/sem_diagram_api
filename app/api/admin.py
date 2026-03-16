"""
app/api/admin.py
================
Admin endpoints for viewing database statistics.
All routes require the ADMIN_API_KEY header.

Set ADMIN_API_KEY in your environment — if not set, the admin
endpoints return 503 to prevent accidental open access.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Header, HTTPException

from app.db.database import get_stats

router = APIRouter(prefix="/admin", tags=["admin"])

_ADMIN_KEY = os.environ.get("ADMIN_API_KEY", "")


def _check_key(x_api_key: str = Header(..., alias="X-Api-Key")) -> None:
    if not _ADMIN_KEY:
        raise HTTPException(503, detail="Admin API key not configured on server.")
    if x_api_key != _ADMIN_KEY:
        raise HTTPException(403, detail="Invalid API key.")


@router.get("/stats")
async def admin_stats(
    hours: int = 24,
    x_api_key: str = Header(..., alias="X-Api-Key"),
) -> dict:
    """
    Return aggregated statistics from the database.

    Query params:
        hours (int): lookback window in hours. Default 24, max 720 (30 days).

    Headers:
        X-Api-Key: your ADMIN_API_KEY value
    """
    _check_key(x_api_key)
    hours = max(1, min(hours, 720))
    return await get_stats(hours=hours)


@router.get("/health-db")
async def admin_health_db(
    x_api_key: str = Header(..., alias="X-Api-Key"),
) -> dict:
    """Check database connectivity."""
    _check_key(x_api_key)
    try:
        stats = await get_stats(hours=1)
        connected = "error" not in stats
    except Exception as exc:
        return {"db_connected": False, "error": str(exc)}
    return {"db_connected": connected}
