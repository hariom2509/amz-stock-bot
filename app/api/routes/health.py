"""
Health check API route.
"""
from __future__ import annotations

import time
from fastapi import APIRouter, Depends, Request
from app.api.dependencies import get_settings
from app.api.schemas import HealthResponse
from app.config import Settings
from app.database import repository as repo

router = APIRouter(tags=["Health"])
_start_time = time.time()


@router.api_route("/health", methods=["GET", "HEAD"], response_model=HealthResponse)
async def health_check(
    request: Request,
    settings: Settings = Depends(get_settings),
):
    """Check backend health, database connection, and scheduler status (supports GET and HEAD)."""
    db_status = "ok"
    products_count = 0
    try:
        shared_prods = await repo.list_active_shared_products(settings.database_path)
        products_count = len(shared_prods)
    except Exception:
        db_status = "error"

    scheduler_status = "running"
    if hasattr(request.app.state, "scheduler") and request.app.state.scheduler:
        if not getattr(request.app.state.scheduler, "_running", False):
            scheduler_status = "stopped"

    overall_status = "healthy" if db_status == "ok" and scheduler_status == "running" else "degraded"

    return HealthResponse(
        status=overall_status,
        database=db_status,
        scheduler=scheduler_status,
        monitored_products_count=products_count,
        uptime_seconds=round(time.time() - _start_time, 2),
    )
