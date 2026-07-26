"""
Telegram Linking API Routes.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from app.api.dependencies import get_current_user, get_settings
from app.api.schemas import TelegramLinkResponse, TelegramStatusResponse
from app.config import Settings
from app.database import repository as repo
from app.database.models import User
from app.telegram import linking as telegram_linking

router = APIRouter(prefix="/api/v1/telegram", tags=["Telegram"])


@router.post("/link", response_model=TelegramLinkResponse)
async def create_telegram_link(
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """Generate a temporary single-use deep link URL to connect Telegram."""
    _, deep_link_url, expires_at = await telegram_linking.generate_telegram_link(
        db_path=settings.database_path,
        user_id=current_user.id,
        bot_username=settings.bot_username,
        ttl_seconds=settings.link_token_ttl_seconds,
    )
    return TelegramLinkResponse(
        deep_link_url=deep_link_url,
        expires_in_seconds=settings.link_token_ttl_seconds,
    )


@router.get("/status", response_model=TelegramStatusResponse)
async def get_telegram_status(
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """Check if the current user has connected their Telegram account."""
    # Refresh user state from database
    fresh_user = await repo.get_user_by_public_id(settings.database_path, current_user.public_id)
    u = fresh_user or current_user

    return TelegramStatusResponse(
        linked=u.is_telegram_connected,
        connected_at=u.telegram_connected_at,
    )


@router.delete("/link")
async def disconnect_telegram(
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """Disconnect Telegram account from the user profile."""
    await repo.unlink_user_telegram(settings.database_path, current_user.id)
    return {"message": "Telegram disconnected successfully"}
