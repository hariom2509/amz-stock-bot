"""
Products Management API Routes.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from app.api.dependencies import get_current_user, get_settings
from app.api.schemas import (
    AddProductRequest,
    ProductListResponse,
    ProductResponse,
)
from app.config import Settings
from app.database import repository as repo
from app.database.models import User, Product, UserWatch, MonitoringMode, StockStatus
from app.utils.urls import normalize_url, looks_like_amazon_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/products", tags=["Products"])


def _format_last_checked(ts: Optional[datetime]) -> str:
    if not ts:
        return "Never"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    diff = now - ts
    if diff < timedelta(minutes=1):
        return f"{max(0, int(diff.total_seconds()))}s ago"
    elif diff < timedelta(hours=1):
        return f"{int(diff.total_seconds() // 60)}m ago"
    else:
        return ts.strftime("%H:%M UTC")


def _to_product_response(product: Product, watch: UserWatch) -> ProductResponse:
    w_prod = repo._build_watched_product(watch, product, 0)

    return ProductResponse(
        asin=product.asin,
        title=product.title,
        url=product.canonical_url,
        status=product.status.value,
        status_display=w_prod.display_status,
        status_emoji=w_prod.status_emoji,
        price=product.price,
        price_display=w_prod.display_price,
        currency=product.currency,
        mode=watch.monitoring_mode.value,
        mode_emoji=w_prod.mode_emoji,
        monitoring=watch.monitoring_enabled,
        last_checked_at=product.last_checked_at,
        last_checked_display=_format_last_checked(product.last_checked_at),
        created_at=watch.created_at,
    )


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def add_product(
    req: AddProductRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """Add a new product to watch."""
    url = req.url.strip()
    if not looks_like_amazon_url(url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Amazon URL. Only amazon.in and amzn.in URLs are accepted.",
        )

    result = normalize_url(url)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not extract ASIN from URL.",
        )

    canonical_url, asin = result

    # Check watch count limit
    current_count = await repo.count_user_watches(settings.database_path, current_user.id)
    if current_count >= settings.max_watches_per_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Watch limit reached. You can watch up to {settings.max_watches_per_user} products.",
        )

    # Get or create shared product
    product = await repo.get_or_create_product(settings.database_path, asin, canonical_url)

    # Subscribe user
    try:
        watch = await repo.add_user_watch(settings.database_path, current_user.id, product.id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )

    # Trigger immediate check if scheduler present
    scheduler = request.app.state.scheduler if hasattr(request.app.state, "scheduler") else None
    if scheduler:
        await scheduler.trigger_immediate_check(product)

    return _to_product_response(product, watch)


@router.get("", response_model=ProductListResponse)
async def list_products(
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """List all watched products for current user."""
    watches_and_prods = await repo.list_user_watches(settings.database_path, current_user.id)
    prods = [_to_product_response(p, w) for w, p in watches_and_prods]
    return ProductListResponse(
        count=len(prods),
        limit=settings.max_watches_per_user,
        products=prods,
    )


@router.get("/{asin}", response_model=ProductResponse)
async def get_product(
    asin: str,
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """Get status of a watched product by ASIN."""
    asin_clean = asin.strip().upper()
    product = await repo.get_product_by_asin(settings.database_path, asin_clean)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    watch = await repo.get_user_watch(settings.database_path, current_user.id, product.id)
    if not watch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not in your watch list")

    return _to_product_response(product, watch)


@router.delete("/{asin}")
async def remove_product(
    asin: str,
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """Remove product from user's watchlist."""
    asin_clean = asin.strip().upper()
    product = await repo.get_product_by_asin(settings.database_path, asin_clean)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    deleted = await repo.remove_user_watch(settings.database_path, current_user.id, product.id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not in your watch list")

    return {"message": f"Product {asin_clean} removed from watch list"}


@router.post("/{asin}/check", response_model=ProductResponse)
async def trigger_check(
    asin: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """Force an immediate check for a product."""
    asin_clean = asin.strip().upper()
    product = await repo.get_product_by_asin(settings.database_path, asin_clean)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    watch = await repo.get_user_watch(settings.database_path, current_user.id, product.id)
    if not watch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not in your watch list")

    scheduler = request.app.state.scheduler if hasattr(request.app.state, "scheduler") else None
    if scheduler:
        await scheduler.trigger_immediate_check(product)

    return _to_product_response(product, watch)


@router.post("/{asin}/turbo", response_model=ProductResponse)
async def set_turbo_mode(
    asin: str,
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """Enable Turbo monitoring mode for a product (max 1 per user)."""
    asin_clean = asin.strip().upper()
    product = await repo.get_product_by_asin(settings.database_path, asin_clean)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    watch = await repo.get_user_watch(settings.database_path, current_user.id, product.id)
    if not watch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not in your watch list")

    # Check user turbo limit
    turbo_count = await repo.count_user_turbo_watches(settings.database_path, current_user.id)
    if watch.monitoring_mode != MonitoringMode.TURBO and turbo_count >= settings.max_turbo_watches_per_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Turbo limit reached. You can have at most {settings.max_turbo_watches_per_user} product in Turbo mode.",
        )

    await repo.update_user_watch_state(settings.database_path, watch.id, monitoring_mode=MonitoringMode.TURBO)
    fresh_watch = await repo.get_user_watch(settings.database_path, current_user.id, product.id)
    return _to_product_response(product, fresh_watch)


@router.post("/{asin}/normal", response_model=ProductResponse)
async def set_normal_mode(
    asin: str,
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """Return product monitoring to Normal mode."""
    asin_clean = asin.strip().upper()
    product = await repo.get_product_by_asin(settings.database_path, asin_clean)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    watch = await repo.get_user_watch(settings.database_path, current_user.id, product.id)
    if not watch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not in your watch list")

    await repo.update_user_watch_state(settings.database_path, watch.id, monitoring_mode=MonitoringMode.NORMAL)
    fresh_watch = await repo.get_user_watch(settings.database_path, current_user.id, product.id)
    return _to_product_response(product, fresh_watch)


@router.post("/{asin}/pause", response_model=ProductResponse)
async def pause_monitoring(
    asin: str,
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """Pause monitoring for a product."""
    asin_clean = asin.strip().upper()
    product = await repo.get_product_by_asin(settings.database_path, asin_clean)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    watch = await repo.get_user_watch(settings.database_path, current_user.id, product.id)
    if not watch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not in your watch list")

    await repo.update_user_watch_state(settings.database_path, watch.id, monitoring_enabled=False)
    fresh_watch = await repo.get_user_watch(settings.database_path, current_user.id, product.id)
    return _to_product_response(product, fresh_watch)


@router.post("/{asin}/resume", response_model=ProductResponse)
async def resume_monitoring(
    asin: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """Resume paused monitoring for a product."""
    asin_clean = asin.strip().upper()
    product = await repo.get_product_by_asin(settings.database_path, asin_clean)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    watch = await repo.get_user_watch(settings.database_path, current_user.id, product.id)
    if not watch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not in your watch list")

    await repo.update_user_watch_state(settings.database_path, watch.id, monitoring_enabled=True)
    fresh_watch = await repo.get_user_watch(settings.database_path, current_user.id, product.id)

    scheduler = request.app.state.scheduler if hasattr(request.app.state, "scheduler") else None
    if scheduler:
        await scheduler.trigger_immediate_check(product)

    return _to_product_response(product, fresh_watch)
