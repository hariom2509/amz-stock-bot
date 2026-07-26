"""
Telegram inline keyboard builders.
"""
from __future__ import annotations

from typing import List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def buy_now_keyboard(url: str) -> InlineKeyboardMarkup:
    """Keyboard with a single 'Buy Now' button linking to the product."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 BUY NOW", url=url)]
    ])


def product_action_keyboard(asin: str) -> InlineKeyboardMarkup:
    """Keyboard with common actions for a product."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Status", callback_data=f"status:{asin}"),
            InlineKeyboardButton("🔄 Check Now", callback_data=f"check:{asin}"),
        ],
        [
            InlineKeyboardButton("⏸ Pause", callback_data=f"pause:{asin}"),
            InlineKeyboardButton("🗑 Remove", callback_data=f"remove:{asin}"),
        ],
    ])


def confirm_remove_keyboard(asin: str) -> InlineKeyboardMarkup:
    """Confirmation keyboard for product removal."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes, Remove", callback_data=f"confirm_remove:{asin}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_remove:{asin}"),
        ]
    ])
