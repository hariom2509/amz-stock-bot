"""
Telegram inline keyboard builders.
"""
from __future__ import annotations

from typing import List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.utils.urls import build_affiliate_url


def buy_now_keyboard(url: str) -> InlineKeyboardMarkup:
    """Keyboard with a single 'BUY NOW' affiliate button linking to the product."""
    affiliate_url = build_affiliate_url(url)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 BUY NOW", url=affiliate_url)]
    ])


def product_action_keyboard(asin: str) -> InlineKeyboardMarkup:
    """Keyboard with common actions for a product."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Status", callback_data=f"status:{asin}"),
            InlineKeyboardButton("🔄 Check Now", callback_data=f"check:{asin}"),
        ],
        [
            InlineKeyboardButton("⏸ Stop", callback_data=f"pause:{asin}"),
            InlineKeyboardButton("🗑 Remove", callback_data=f"remove:{asin}"),
        ],
    ])


def list_item_keyboard(asin: str, is_active: bool, url: str) -> InlineKeyboardMarkup:
    """Inline keyboard attached to items in /list with interactive Stop/Start toggle and affiliate link."""
    toggle_btn = (
        InlineKeyboardButton("🛑 Stop", callback_data=f"pause:{asin}")
        if is_active
        else InlineKeyboardButton("▶️ Start", callback_data=f"resume:{asin}")
    )
    affiliate_url = build_affiliate_url(url)
    return InlineKeyboardMarkup([
        [
            toggle_btn,
            InlineKeyboardButton("🗑 Remove", callback_data=f"remove:{asin}"),
            InlineKeyboardButton("🔗 Open Amazon", url=affiliate_url),
        ]
    ])


def confirm_remove_keyboard(asin: str) -> InlineKeyboardMarkup:
    """Confirmation keyboard for product removal."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes, Remove", callback_data=f"confirm_remove:{asin}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_remove:{asin}"),
        ]
    ])
