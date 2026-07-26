"""
Database models (dataclasses) for Amazon Stock Watcher.

Python-level representations of database rows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class StockStatus(str, Enum):
    """Possible stock states for a watched product."""
    IN_STOCK = "IN_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


class MonitoringMode(str, Enum):
    """Monitoring speed mode."""
    NORMAL = "NORMAL"
    TURBO = "TURBO"


@dataclass
class User:
    """An application user / device identity."""
    id: int
    public_id: str
    auth_token_hash: str
    telegram_chat_id: Optional[int] = None
    telegram_connected_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @property
    def is_telegram_connected(self) -> bool:
        return self.telegram_chat_id is not None


@dataclass
class TelegramLinkToken:
    """Temporary linking token for connecting Telegram chat."""
    id: int
    user_id: int
    token_hash: str
    expires_at: datetime
    used_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    @property
    def is_expired(self) -> bool:
        now = datetime.now(self.expires_at.tzinfo) if self.expires_at.tzinfo else datetime.utcnow()
        return now > self.expires_at

    @property
    def is_valid(self) -> bool:
        return self.used_at is None and not self.is_expired


@dataclass
class Product:
    """A unique Amazon product tracked centrally (shared across users)."""
    id: int
    asin: str
    canonical_url: str
    title: Optional[str] = None
    status: StockStatus = StockStatus.UNKNOWN
    price: Optional[str] = None
    currency: str = "INR"
    consecutive_failures: int = 0
    last_checked_at: Optional[datetime] = None
    next_check_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @property
    def status_emoji(self) -> str:
        return {
            StockStatus.IN_STOCK: "🟢",
            StockStatus.OUT_OF_STOCK: "🔴",
            StockStatus.UNKNOWN: "⏳",
            StockStatus.BLOCKED: "⏳",
            StockStatus.ERROR: "⚠️",
        }.get(self.status, "⏳")

    @property
    def display_status(self) -> str:
        return {
            StockStatus.IN_STOCK: "In Stock",
            StockStatus.OUT_OF_STOCK: "Out of Stock",
            StockStatus.UNKNOWN: "Checking...",
            StockStatus.BLOCKED: "Checking...",
            StockStatus.ERROR: "Check Error",
        }.get(self.status, "Checking...")



@dataclass
class UserWatch:
    """A user's subscription to monitor a Product."""
    id: int
    user_id: int
    product_id: int
    monitoring_enabled: bool = True
    monitoring_mode: MonitoringMode = MonitoringMode.NORMAL
    alert_sent_for_current_stock_state: bool = False
    last_alerted_at: Optional[datetime] = None
    last_status_changed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class WatchedProduct:
    """
    Combined view model of Product + UserWatch (used by bot, alerts, tests).
    Maintains 100% backward compatibility with legacy single-user code.
    """
    id: int
    telegram_chat_id: int
    asin: str
    url: str

    # Product info
    title: Optional[str] = None
    status: StockStatus = StockStatus.UNKNOWN
    price: Optional[str] = None
    currency: str = "INR"

    # Monitoring state
    monitoring_enabled: bool = True
    monitoring_mode: MonitoringMode = MonitoringMode.NORMAL

    # Timing
    last_checked_at: Optional[datetime] = None
    last_status_changed_at: Optional[datetime] = None
    last_alerted_at: Optional[datetime] = None
    next_check_at: Optional[datetime] = None

    # Alert deduplication
    alert_sent_for_current_stock_state: bool = False
    consecutive_failures: int = 0

    # Record timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @property
    def status_emoji(self) -> str:
        return {
            StockStatus.IN_STOCK: "🟢",
            StockStatus.OUT_OF_STOCK: "🔴",
            StockStatus.UNKNOWN: "⏳",
            StockStatus.BLOCKED: "⏳",
            StockStatus.ERROR: "⚠️",
        }.get(self.status, "⏳")

    @property
    def mode_emoji(self) -> str:
        return "⚡" if self.monitoring_mode == MonitoringMode.TURBO else "🔄"

    @property
    def display_price(self) -> str:
        if self.price:
            return f"₹{self.price}"
        return "Price: Unknown"

    @property
    def display_title(self) -> str:
        return self.title or f"ASIN: {self.asin}"

    @property
    def display_status(self) -> str:
        return {
            StockStatus.IN_STOCK: "In Stock",
            StockStatus.OUT_OF_STOCK: "Out of Stock",
            StockStatus.UNKNOWN: "Checking...",
            StockStatus.BLOCKED: "Checking...",
            StockStatus.ERROR: "Check Error",
        }.get(self.status, "Checking...")

