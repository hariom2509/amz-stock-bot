"""
Telegram Alert Manager.

Sends stock alert messages via the Telegram Bot API.
Designed to be fire-and-forget — does not block monitoring.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Union

from telegram import Bot
from telegram.error import TelegramError

from app.database.models import WatchedProduct, Product
from app.bot.keyboards import buy_now_keyboard

logger = logging.getLogger(__name__)


class AlertManager:
    """
    Sends Telegram notifications for stock events.
    Thread-safe for asyncio (single event loop).
    """

    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send_in_stock_alert(
        self,
        product: Union[WatchedProduct, Product],
        detected_at: datetime,
    ) -> None:
        """Send an IN STOCK alert to product.telegram_chat_id (legacy single-user mode)."""
        chat_id = getattr(product, "telegram_chat_id", None)
        if not chat_id:
            logger.warning(f"send_in_stock_alert called without telegram_chat_id for ASIN={product.asin}")
            return
        await self.send_in_stock_alert_to(chat_id, product, detected_at)

    async def send_in_stock_alert_to(
        self,
        chat_id: int,
        product: Union[WatchedProduct, Product],
        detected_at: datetime,
    ) -> None:
        """
        Send an IN STOCK alert to a specific Telegram chat_id.

        Primary multi-user notification. Uses inline keyboard with Buy Now button.
        """
        detected_str = detected_at.strftime("%Y-%m-%d %H:%M:%S UTC")

        price_line = f"💰 {product.display_price}" if product.price else "💰 Price: Unknown"

        text = (
            f"🚨 <b>AMAZON STOCK ALERT</b>\n\n"
            f"<b>{_escape(product.display_title)}</b>\n\n"
            f"🟢 <b>IN STOCK</b>\n"
            f"{price_line}\n\n"
            f"⏱ Detected: {detected_str}\n"
            f"🔖 ASIN: <code>{product.asin}</code>"
        )

        url = getattr(product, "url", getattr(product, "canonical_url", ""))
        keyboard = buy_now_keyboard(url)

        await self._send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
        )

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup=None,
        parse_mode: str = "HTML",
    ) -> None:
        """Send a generic message."""
        await self._send_message(chat_id, text, reply_markup, parse_mode)

    async def _send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup=None,
        parse_mode: str = "HTML",
    ) -> None:
        """Internal send with basic retry logic."""
        import asyncio

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                    disable_web_page_preview=True,
                )
                return
            except TelegramError as e:
                if attempt < max_attempts:
                    wait = 2 ** attempt  # 2, 4 seconds
                    logger.warning(
                        f"Telegram send failed (attempt {attempt}/{max_attempts}): {e}. "
                        f"Retrying in {wait}s..."
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(
                        f"Telegram send failed after {max_attempts} attempts: {e}"
                    )
                    raise


def _escape(text: str) -> str:
    """Escape HTML special characters for Telegram HTML parse mode."""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
