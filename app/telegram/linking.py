"""
Telegram Linking Service.

Handles temporary secure deep-link tokens for connecting user devices to Telegram chat IDs.
Flow:
  Extension -> API: request link token
  API -> Backend: generate raw link token, store SHA-256 hash with 15min expiry
  API -> Extension: return deep link URL: https://t.me/<BOT_USERNAME>?start=<token>
  User -> Telegram: taps Start (/start <token>)
  Telegram Bot -> Backend: validate & consume token -> link chat_id to user
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

from app.database import repository as repo
from app.database.models import User, TelegramLinkToken


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


async def generate_telegram_link(
    db_path: str,
    user_id: int,
    bot_username: str,
    ttl_seconds: int = 900,
) -> Tuple[str, str, datetime]:
    """
    Generate a single-use deep-link URL for Telegram connection.

    Returns:
        (raw_token, deep_link_url, expires_at)
    """
    raw_token = secrets.token_urlsafe(16)
    token_h = hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

    await repo.create_link_token(
        db_path=db_path,
        user_id=user_id,
        token_hash=token_h,
        expires_at=expires_at,
    )

    clean_botname = bot_username.replace("@", "").strip()
    deep_link_url = f"https://t.me/{clean_botname}?start={raw_token}"
    return raw_token, deep_link_url, expires_at


async def consume_telegram_link_token(
    db_path: str,
    raw_token: str,
    chat_id: int,
) -> Optional[User]:
    """
    Validate and consume a link token from Telegram /start <token>.
    Links user.telegram_chat_id to chat_id.

    Returns User if successfully linked, None if token invalid/expired/used.
    """
    if not raw_token or not raw_token.strip():
        return None

    token_h = hash_token(raw_token.strip())
    token = await repo.consume_link_token(db_path, token_h)
    if not token:
        return None

    # Link chat ID to user
    await repo.link_user_telegram(db_path, token.user_id, chat_id)
    return await repo.get_user_by_public_id(db_path, str(token.user_id))
