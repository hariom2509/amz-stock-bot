"""
Pydantic API Request/Response Schemas.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


# ── Auth & User Schemas ──────────────────────────────────────────────────

class DeviceRegisterRequest(BaseModel):
    client_token: Optional[str] = Field(
        None, description="Optional client-generated raw token. If omitted, server generates one."
    )


class DeviceRegisterResponse(BaseModel):
    public_id: str
    client_token: str
    message: str = "Device registered successfully"


class UserProfileResponse(BaseModel):
    public_id: str
    telegram_linked: bool
    telegram_chat_id: Optional[int] = None
    telegram_connected_at: Optional[datetime] = None
    watch_count: int
    watch_limit: int
    turbo_watch_count: int
    turbo_watch_limit: int


# ── Telegram Linking Schemas ──────────────────────────────────────────────

class TelegramLinkResponse(BaseModel):
    deep_link_url: str
    expires_in_seconds: int


class TelegramStatusResponse(BaseModel):
    linked: bool
    connected_at: Optional[datetime] = None


# ── Product Schemas ───────────────────────────────────────────────────────

class AddProductRequest(BaseModel):
    url: str = Field(..., description="Amazon product URL (e.g. https://www.amazon.in/dp/B0XXXXXXXX)")


class ProductResponse(BaseModel):
    asin: str
    title: Optional[str] = None
    url: str
    status: str
    status_display: str
    status_emoji: str
    price: Optional[str] = None
    price_display: str
    currency: str = "INR"
    mode: str
    mode_emoji: str
    monitoring: bool
    last_checked_at: Optional[datetime] = None
    last_checked_display: str = "Never"
    created_at: Optional[datetime] = None


class ProductListResponse(BaseModel):
    count: int
    limit: int
    products: List[ProductResponse]


# ── Health Schema ─────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = "healthy"
    database: str = "ok"
    scheduler: str = "running"
    monitored_products_count: int = 0
    uptime_seconds: float = 0.0
