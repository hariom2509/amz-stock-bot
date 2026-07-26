"""
Authentication & User API Routes.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from app.api.dependencies import get_current_user, get_settings
from app.api.schemas import (
    DeviceRegisterRequest,
    DeviceRegisterResponse,
    UserProfileResponse,
)
from app.auth import service as auth_service
from app.config import Settings
from app.database import repository as repo
from app.database.models import User

router = APIRouter(prefix="/api/v1", tags=["Auth"])


@router.post("/auth/register", response_model=DeviceRegisterResponse)
async def register_device(
    req: DeviceRegisterRequest = None,
    settings: Settings = Depends(get_settings),
):
    """Register a new device identity."""
    token_input = req.client_token if req else None
    user, raw_token = await auth_service.register_device(
        settings.database_path, client_token=token_input
    )
    return DeviceRegisterResponse(
        public_id=user.public_id,
        client_token=raw_token,
    )


@router.get("/me", response_model=UserProfileResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """Get profile & limits for current user."""
    watch_count = await repo.count_user_watches(settings.database_path, current_user.id)
    turbo_count = await repo.count_user_turbo_watches(settings.database_path, current_user.id)

    return UserProfileResponse(
        public_id=current_user.public_id,
        telegram_linked=current_user.is_telegram_connected,
        telegram_chat_id=current_user.telegram_chat_id,
        telegram_connected_at=current_user.telegram_connected_at,
        watch_count=watch_count,
        watch_limit=settings.max_watches_per_user,
        turbo_watch_count=turbo_count,
        turbo_watch_limit=settings.max_turbo_watches_per_user,
    )
