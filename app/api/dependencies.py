"""
FastAPI Dependencies.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, HTTPException, Header, status
from app.auth import service as auth_service
from app.config import Settings, load_settings
from app.database.models import User

logger = logging.getLogger(__name__)


def get_settings() -> Settings:
    return load_settings()


async def get_current_user(
    authorization: Optional[str] = Header(None),
    settings: Settings = Depends(get_settings),
) -> User:
    """
    FastAPI dependency that extracts Bearer token from Authorization header,
    hashes it, and returns the authenticated User object.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Expected 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = parts[1].strip()
    user = await auth_service.authenticate_token(settings.database_path, token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired client token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user
