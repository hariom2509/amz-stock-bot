"""
Telegram inline keyboard builders.
"""
from __future__ import annotations

from typing import List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.utils.urls import build_affiliate_url


def buy_now_keyboard(url: str) -> InlineKeyboardMarkup:
    """Keyboard with store-specific 'BUY NOW' affiliate button."""
    affiliate_url = build_affiliate_url(url)
    is_fk = "flipkart" in url.lower() or "fkrt" in url.lower()
    label = "🛒 BUY ON FLIPKART" if is_fk else "🛒 BUY ON AMAZON"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, url=affiliate_url)]
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
    """Inline keyboard attached to items in /list with interactive Stop/Start toggle and store-specific affiliate link."""
    toggle_btn = (
        InlineKeyboardButton("🛑 Stop", callback_data=f"pause:{asin}")
        if is_active
        else InlineKeyboardButton("▶️ Start", callback_data=f"resume:{asin}")
    )
    affiliate_url = build_affiliate_url(url)
    is_fk = "flipkart" in url.lower() or "fkrt" in url.lower() or asin.startswith("FK_")
    open_label = "🔗 Open Flipkart" if is_fk else "🔗 Open Amazon"
    return InlineKeyboardMarkup([
        [
            toggle_btn,
            InlineKeyboardButton("🗑 Remove", callback_data=f"remove:{asin}"),
            InlineKeyboardButton(open_label, url=affiliate_url),
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
